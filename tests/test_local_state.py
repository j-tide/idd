"""Configuration transactions shared by CLI commands and the local board."""

from concurrent.futures import ThreadPoolExecutor
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
                with self.assertRaises(local_state.HostConfigError):
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
                    with self.assertRaises(local_state.HostConfigError):
                        local_state.set_host("new.example", {"forge": "gitlab"})
                    with self.assertRaises(local_state.HostConfigError):
                        local_state.remove_hosts(("existing.example",))
                    self.assertEqual(path.read_bytes(), raw)
            raw = b'{"existing.example":{"custom":"keep"}}'
            path.write_bytes(raw)
            with mock.patch.object(Path, "read_text", side_effect=PermissionError("unreadable")):
                with self.assertRaises(local_state.HostConfigError):
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
