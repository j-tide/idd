"""Configuration transactions shared by CLI commands and the local board."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import local_state
import repo_registry


class TestLocalState(unittest.TestCase):
    def test_concurrent_cli_updates_keep_every_host_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            env = dict(os.environ, IDD_CONFIG_DIR=str(cfg), IDD_NO_AUTO_UPDATE="1")
            hosts = [f"forge-{i}.example.test" for i in range(12)]

            def login(host):
                subprocess.run(
                    [sys.executable, "-B", str(SCRIPTS / "idd"), "auth", "login", host,
                     "--no-verify", "--token", "fixture"],
                    env=env, check=True, capture_output=True, text=True,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(login, hosts))
            path = cfg / "hosts.json"
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(saved), set(hosts))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(cfg.stat().st_mode), 0o700)

    def test_removal_policies_and_failed_write_preserve_other_entries(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": tmp}):
            port, bare, other = "forge.example:8888", "forge.example", "other.example"
            for host in (port, bare, other):
                local_state.set_host(host, {"forge": "gitlab", "custom": host})
            self.assertTrue(local_state.remove_hosts((port, bare), first_only=True))
            self.assertEqual(set(local_state.load_hosts_config()), {bare, other})
            local_state.set_host(port, {"forge": "gitlab"})
            self.assertTrue(local_state.remove_hosts((port, bare)))
            path = local_state.get_hosts_path()
            original = path.read_bytes()
            with mock.patch.object(local_state.os, "replace", side_effect=OSError("read-only")):
                with self.assertRaises(local_state.LocalStateError):
                    local_state.set_host("new.example", {"forge": "github"})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(local_state.load_hosts_config()[other]["custom"], other)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_corrupt_or_unreadable_hosts_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": tmp}):
            path = local_state.get_hosts_path()
            for raw in (b'{"incomplete":', b'[]', b'\xff'):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    self.assertEqual(local_state.load_hosts_config(), {})
                    with self.assertRaises(local_state.LocalStateError):
                        local_state.set_host("new.example", {"forge": "gitlab"})
                    with self.assertRaises(local_state.LocalStateError):
                        local_state.remove_hosts(("existing.example",))
                    self.assertEqual(path.read_bytes(), raw)
            raw = b'{"existing.example":{"custom":"keep"}}'
            path.write_bytes(raw)
            with mock.patch.object(Path, "read_text", side_effect=PermissionError("unreadable")):
                with self.assertRaises(local_state.LocalStateError):
                    local_state.set_host("new.example", {"forge": "gitlab"})
            self.assertEqual(path.read_bytes(), raw)
            path.write_bytes(b"[]")
            cmd = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "idd"), "auth", "login", "new.example",
                 "--no-verify", "--token", "fixture"],
                env=dict(os.environ, IDD_NO_AUTO_UPDATE="1"), capture_output=True, text=True,
            )
            self.assertEqual(cmd.returncode, 1)
            self.assertIn("无法更新主机配置", cmd.stderr)
            self.assertNotIn("Traceback", cmd.stderr)
            self.assertEqual(path.read_bytes(), b"[]")

    def test_settings_and_registry_keep_legacy_data_and_survive_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": tmp}):
            repo = Path(tmp).resolve() / "project"
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            settings = local_state.get_config_path()
            settings.write_text('{"another_setting": 4}', encoding="utf-8")
            local_state.set_global_auto_merge(True)
            self.assertEqual(json.loads(settings.read_text()), {"another_setting": 4, "auto_merge": True})
            registry = repo_registry.get_repos_path()
            registry.write_text(json.dumps([{"path": str(repo), "repo_init_state": "prompted"}]))
            self.assertEqual(repo_registry.load_registered_repos()[0]["path"], str(repo))
            self.assertEqual(repo_registry.get_repo_init_meta(repo)["state"], "pending")
            repo_registry.register_repo(repo)
            self.assertEqual(json.loads(registry.read_text())["repos"][0]["path"], str(repo))
            for path in (settings, registry):
                path.write_bytes(b'{"broken":')
            self.assertFalse(local_state.get_global_auto_merge())
            with self.assertRaises(local_state.LocalStateError):
                local_state.set_global_auto_merge(True)
            self.assertEqual(repo_registry.load_registered_repos(), [])
            self.assertEqual(repo_registry.register_repo(repo)["path"], str(repo))
            repo_registry.set_repo_init_meta(repo, "pending")
            with self.assertRaises(local_state.LocalStateError):
                repo_registry.register_repo(repo, required=True)
            with self.assertRaises(local_state.LocalStateError):
                repo_registry.unregister_repo(repo)
            for path in (settings, registry):
                self.assertEqual(path.read_bytes(), b'{"broken":')

    def test_list_remains_readable_when_pruning_cannot_write(self):
        from idd_cli import main
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": tmp, "IDD_NO_AUTO_UPDATE": "1"}):
            live = Path(tmp).resolve() / "live"
            subprocess.run(["git", "init", str(live)], check=True, capture_output=True)
            stale = live.with_name("missing")
            registry = repo_registry.get_repos_path()
            original = json.dumps({"repos": [{"path": str(live)}, {"path": str(stale)}, {"path": str(stale)}]})
            registry.write_text(original)
            with mock.patch.object(repo_registry, "atomic_write_json", side_effect=OSError("disk full")):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["repos", "list", "--json"]), 0)
                self.assertEqual([r["path"] for r in json.loads(output.getvalue())["repos"]], [str(live)])
                error = io.StringIO()
                with redirect_stderr(error):
                    self.assertEqual(main(["repos", "prune", "--json"]), 1)
                self.assertIn("disk full", error.getvalue())
                self.assertEqual(registry.read_text(), original)
            self.assertEqual(repo_registry.prune_registered_repos(), (1, 1))
            self.assertEqual(repo_registry.prune_registered_repos(), (0, 1))
