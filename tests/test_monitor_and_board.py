"""End-to-end tests for global repo registry, live worktree pulse, `idd watch`, and `idd board`."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request

from test_gitlab_forge import MockGitLabState, make_handler
from test_idd_cli import FAKE_GH_SCRIPT, IDD_BIN, SCRIPTS_DIR, parse_skill_version

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import monitor  # noqa: E402


def _create_repo_harness(
    base_dir: Path,
    repo_name: str,
    config_dir: Path,
    issues: dict[str, dict] | None = None,
) -> tuple[Path, Path, Path, dict[str, str]]:
    """Create a real bare origin + cloned repo + isolated fake `gh` env sharing `config_dir`."""
    base_dir.mkdir(parents=True, exist_ok=True)
    origin = base_dir / f"{repo_name}.git"
    repo = base_dir / repo_name
    bin_dir = base_dir / "bin"
    state_file = base_dir / "gh_state.json"

    bin_dir.mkdir(parents=True, exist_ok=True)
    gh_bin = bin_dir / "gh"
    gh_bin.write_text(FAKE_GH_SCRIPT, encoding="utf-8")
    gh_bin.chmod(0o755)

    default_issues = issues or {
        "42": {
            "number": 42,
            "title": f"{repo_name} export csv",
            "body": "Export CSV support",
            "labels": [{"name": "feat"}],
            "state": "OPEN",
            "url": f"https://github.com/acme/{repo_name}/issues/42",
        },
        "43": {
            "number": 43,
            "title": f"{repo_name} dark flicker",
            "body": "Fix flicker",
            "labels": [{"name": "bug"}],
            "state": "OPEN",
            "url": f"https://github.com/acme/{repo_name}/issues/43",
        },
    }
    state = {
        "next_issue": 50,
        "next_pr": 10,
        "issues": default_issues,
        "prs": {},
        "run_logs": {},
        "default_checks": [{"name": "ci / test", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "repo_settings": {
            "default_branch": "main",
            "allow_merge_commit": False,
            "allow_squash_merge": True,
            "allow_rebase_merge": False,
            "delete_branch_on_merge": False,
        },
        "calls": [],
    }
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)

    (repo / "README.md").write_text(f"# {repo_name}\n", encoding="utf-8")
    (repo / "app.py").write_text("line1 = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md", "app.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: initial commit"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
    subprocess.run(["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "set-head", "origin", "main"], check=True)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_GH_STATE"] = str(state_file)
    env["FAKE_GH_ORIGIN"] = str(origin)
    env["IDD_NO_AUTO_UPDATE"] = "1"
    env["IDD_NO_BROWSER"] = "1"
    env["IDD_CONFIG_DIR"] = str(config_dir)
    env.pop("IDD_WORKTREE_ROOT", None)
    return repo, origin, state_file, env


class TestMonitorAndBoard(unittest.TestCase):
    def _run(self, env: dict[str, str], cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(IDD_BIN), *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

    def test_global_repo_registry_auto_registers_lists_prunes_and_removes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            repo_a, _, _, env_a = _create_repo_harness(root / "h_a", "alpha-app", cfg)
            repo_b, _, _, env_b = _create_repo_harness(root / "h_b", "beta-api", cfg)

            self._run(env_a, repo_a, "start", "42", "--slug", "export-csv", "--json")
            self._run(env_b, repo_b, "start", "43", "--json")

            repos_file = cfg / "repos.json"
            self.assertTrue(repos_file.is_file())
            listed = json.loads(self._run(env_a, root, "repos", "--json").stdout)
            names = {r["name"] for r in listed["repos"]}
            self.assertEqual(names, {"alpha-app", "beta-api"})

            # Delete repo_b directory & prune stale entries
            shutil.rmtree(repo_b)
            pruned = json.loads(self._run(env_a, root, "repos", "prune", "--json").stdout)
            self.assertEqual(pruned["removed_count"], 1)
            self.assertEqual(pruned["remaining"], 1)

            # Explicit unregister of repo_a
            self._run(env_a, root, "repos", "remove", str(repo_a))
            after = json.loads(self._run(env_a, root, "repos", "list", "--json").stdout)
            self.assertEqual(after["repos"], [])

    def test_auto_global_status_from_non_git_dir_and_worktree_live_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            empty_dir = root / "unbound-workspace"
            empty_dir.mkdir()

            repo_a, _, _, env_a = _create_repo_harness(root / "h_a", "alpha-app", cfg)
            repo_b, _, _, env_b = _create_repo_harness(root / "h_b", "beta-api", cfg)

            wt_a = Path(json.loads(self._run(env_a, repo_a, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            self._run(env_b, repo_b, "start", "43", "--json")

            # Add in_progress + planned TASK and uncommitted code edits in wt_a
            task_dir = wt_a / "TASK/42-export-csv"
            task_dir.mkdir(parents=True)
            (task_dir / "TASK-01-impl.md").write_text(
                "# TASK-01：实现核心接口\n\n"
                "- Issue: #42\n"
                "- Status: in_progress\n"
                "- Depends on: none\n"
                "- Test: pytest\n",
                encoding="utf-8",
            )
            (task_dir / "TASK-02-test.md").write_text(
                "# TASK-02：补充测试\n\n"
                "- Issue: #42\n"
                "- Status: planned\n"
                "- Depends on: TASK-01\n"
                "- Test: pytest\n",
                encoding="utf-8",
            )
            (wt_a / "app.py").write_text("line1 = 1\nline2 = 2\nline3 = 3\n", encoding="utf-8")
            (wt_a / "new_helper.py").write_text("def helper():\n    return 42\n", encoding="utf-8")

            # Running `idd status` in an empty non-git directory automatically aggregates globally
            global_json = json.loads(self._run(env_a, empty_dir, "status", "--local-only", "--json").stdout)
            self.assertTrue(global_json["global"])
            self.assertEqual(global_json["summary"]["repo_count"], 2)
            self.assertGreaterEqual(global_json["summary"]["active_worktrees"], 2)
            self.assertEqual(global_json["summary"]["in_progress_tasks"], 1)

            alpha_snap = next(r for r in global_json["repos"] if r["repo_name"] == "alpha-app")
            issue42 = next(i for i in alpha_snap["issues"] if i["issue_number"] == 42)
            self.assertIn("TASK-01", issue42["current_task"])
            pulse = issue42["pulse"]
            self.assertEqual(pulse["activity_state"], "active")
            self.assertGreaterEqual(pulse["dirty_count"], 2)
            self.assertGreaterEqual(pulse["insertions"], 2)
            changed_paths = {f["path"] for f in pulse["changed_files"]}
            self.assertIn("app.py", changed_paths)
            self.assertIn("new_helper.py", changed_paths)

            md_out = self._run(env_a, empty_dir, "status", "--local-only").stdout
            self.assertIn("全局 IDD 进度总览", md_out)
            self.assertIn("alpha-app", md_out)
            self.assertIn("beta-api", md_out)
            self.assertIn("实时脉搏", md_out)

    def test_retained_post_land_worktree_vs_newly_started_worktree_without_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            repo, _, _, env = _create_repo_harness(root / "h", "demo-app", cfg)

            # Start #42, finish TASK-01, PR, land -> worktree is retained & clean, Issue #42 closed
            wt42 = Path(json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            tdir = wt42 / "TASK/42-export-csv"
            tdir.mkdir(parents=True)
            (tdir / "TASK-01-impl.md").write_text(
                "# TASK-01：实现导出\n\n- Issue: #42\n- Status: done\n- Depends on: none\n- Test: pytest\n\n## 执行结果\n- Outcome: passed\n",
                encoding="utf-8",
            )
            (wt42 / "export.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt42), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(wt42), "commit", "-m",
                    "feat: 实现导出\n\nTask: 42-export-csv/TASK-01\nRefs: #42\nTest: pytest — 1 passed",
                ],
                check=True,
                capture_output=True,
            )
            self._run(env, repo, "pr", "42")
            self._run(env, repo, "land", "42")
            self.assertTrue(wt42.exists())

            # Start open Issue #43 BEFORE creating TASK-01.md, and make a dirty edit
            wt43 = Path(json.loads(self._run(env, repo, "start", "43", "--json").stdout)["worktree"])
            (wt43 / "app.py").write_text("line1 = 1\nfix = True\n", encoding="utf-8")

            snap = json.loads(self._run(env, repo, "status", "--json").stdout)
            by_num = {row["issue_number"]: row for row in snap["issues"]}

            # Closed & clean retained post-land #42 must NOT masquerade as an active open row
            self.assertNotIn(42, by_num)
            self.assertEqual(len(snap["retained_idle_worktrees"]), 1)
            self.assertEqual(snap["retained_idle_worktrees"][0]["branch"], "feat/42-export-csv")

            # Newly started open Issue #43 binds immediately even without TASK/
            self.assertIn(43, by_num)
            self.assertEqual(by_num[43]["stage"], "🟡 开发中")
            self.assertTrue(by_num[43]["worktree"])
            self.assertGreaterEqual(by_num[43]["pulse"]["dirty_count"], 1)

    def test_watch_once_renders_global_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            empty_dir = root / "empty"
            empty_dir.mkdir()
            repo, _, _, env = _create_repo_harness(root / "h", "watch-repo", cfg)
            wt = Path(json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            tdir = wt / "TASK/42-export-csv"
            tdir.mkdir(parents=True)
            (tdir / "TASK-01-impl.md").write_text(
                "# TASK-01：编写同步逻辑\n\n- Issue: #42\n- Status: in_progress\n- Depends on: none\n- Test: pytest\n",
                encoding="utf-8",
            )

            out = self._run(env, empty_dir, "watch", "--once", "--local-only").stdout
            self.assertIn("IDD 实时监控（全局仓库）", out)
            self.assertIn("watch-repo", out)
            self.assertIn("▶ TASK-01", out)
            self.assertIn("🟢", out)

    def test_board_web_server_serves_offline_ui_and_live_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            empty_dir = root / "empty"
            empty_dir.mkdir()
            repo, _, _, env = _create_repo_harness(root / "h", "board-repo", cfg)
            wt = Path(json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])

            sub_env = dict(env)
            sub_env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                [sys.executable, str(IDD_BIN), "board", "--host", "127.0.0.1", "--port", "0", "--no-open", "--local-only"],
                cwd=str(empty_dir),
                env=sub_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                banner = proc.stdout.readline().strip()
                m = re.search(r"(http://127\.0\.0\.1:\d+)", banner)
                self.assertIsNotNone(m, f"Unexpected board startup output: {banner!r}")
                base_url = m.group(1)

                with urllib.request.urlopen(f"{base_url}/api/health", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    health = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(health["ok"])
                    self.assertEqual(health["version"], parse_skill_version())

                with urllib.request.urlopen(f"{base_url}/", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    html = resp.read().decode("utf-8")
                    self.assertIn("IDD 实时开发监控看板", html)
                    self.assertIn('data-theme="dark"', html)
                    self.assertIn(f"v{parse_skill_version()}", html)
                    self.assertIn("待处理 Issue", html)
                    self.assertIn("跨 Agent 接力提示词", html)
                    self.assertIn("Cross-Agent Handoff Prompt", html)
                    self.assertIn("打开 Issue", html)
                    self.assertIn("Open Issue", html)
                    self.assertIn("wt-tasks-strip", html)
                    self.assertIn("auth_alerts", html)
                    self.assertIn("forge_syncing", html)
                    self.assertIn("buildHandoffPrompt", html)
                    self.assertNotIn("backlog", html.lower())
                    self.assertNotIn("__IDD_VERSION__", html)
                    self.assertNotIn("cdn.", html.lower())
                    for element_id in (
                        "top-progress",
                        "sync-banner-wrap",
                        "view-cockpit",
                        "view-kanban",
                        "view-repos",
                        "view-list",
                        "inspector-panel",
                        "lang-btn",
                        "setup-btn",
                        "top-alerts-wrap",
                        "setup-modal",
                    ):
                        self.assertIn(element_id, html)
                    for loading_token in (
                        "renderLoadingState",
                        "renderMainSkeleton",
                        "idd_board_last_snap:",
                        "data-retry-init",
                        "初始化中",
                        "Initializing",
                    ):
                        self.assertIn(loading_token, html)
                    self.assertIn("forge-chip", html)
                    self.assertIn("shortDirSlug(it.worktree, it.repo_name, it.branch)", html)
                    self.assertIn("display: none !important;", html)
                    self.assertIn("body.sidebar-collapsed .show-collapsed { display: inline-grid !important; }", html)
                    node_bin = shutil.which("node")
                    if node_bin:
                        script_match = re.search(r"<script>(.*)</script>", html, re.S)
                        self.assertIsNotNone(script_match)
                        assert script_match is not None
                        js_check = subprocess.run(
                            [node_bin, "--check"],
                            input=script_match.group(1),
                            text=True,
                            capture_output=True,
                        )
                        self.assertEqual(js_check.returncode, 0, js_check.stderr)

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap1 = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(snap1["summary"]["repo_count"], 1)

                # Modify a file in wt and confirm live snapshot updates without restart
                (wt / "live_edit.py").write_text("print('live')\n", encoding="utf-8")
                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap2 = json.loads(resp.read().decode("utf-8"))
                    row42 = next(r for r in snap2["issues"] if r["issue_number"] == 42)
                    self.assertEqual(row42["pulse"]["dirty_count"], 1)
                    self.assertEqual(row42["pulse"]["activity_state"], "active")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()

    def test_status_terminal_styling_color_controls_and_single_repo_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            workspace = fake_home / "workspace"
            cfg = fake_home / ".config" / "idd"
            empty_dir = root / "outside"
            empty_dir.mkdir()

            repo, _, state_file, env = _create_repo_harness(workspace / "h", "styled-app", cfg)
            env["HOME"] = str(fake_home)

            wt = Path(json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            tdir = wt / "TASK/42-export-csv"
            tdir.mkdir(parents=True)
            (tdir / "TASK-01-api.md").write_text(
                "# TASK-01：实现接口\n\n- Issue: #42\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                encoding="utf-8",
            )
            (tdir / "TASK-02-ui.md").write_text(
                "# TASK-02：美化界面\n\n- Issue: #42\n- Status: in_progress\n- Depends on: TASK-01\n- Test: pytest\n",
                encoding="utf-8",
            )
            (wt / "app.py").write_text("line1 = 1\nline2 = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(wt), "commit", "-m", "feat: 实现接口\n\nTask: 42-export-csv/TASK-01\nRefs: #42"],
                check=True,
                capture_output=True,
            )
            self._run(env, repo, "pr", "42")

            state = json.loads(state_file.read_text(encoding="utf-8"))
            pr_num = str(next(iter(state["prs"].keys())))
            state["prs"][pr_num]["statusCheckRollup"] = [
                {"name": "ci / test", "status": "COMPLETED", "conclusion": "FAILURE"}
            ]
            state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

            # 1. Single-repo plain non-TTY output
            single_plain = self._run(env, repo, "status").stdout
            self.assertNotIn("\x1b[", single_plain)
            self.assertIn("◆ IDD", single_plain)
            self.assertIn("仓库状态总览", single_plain)
            self.assertIn("~/workspace/h/styled-app", single_plain)
            self.assertIn("实时脉搏", single_plain)
            self.assertIn("█", single_plain)
            self.assertIn("░", single_plain)
            self.assertIn("待处理 Issue", single_plain)
            self.assertIn("✗ CI 失败", single_plain)

            # 2. Global plain non-TTY output
            global_plain = self._run(env, empty_dir, "status", "-g").stdout
            self.assertNotIn("\x1b[", global_plain)
            self.assertIn("全局 IDD 进度总览", global_plain)
            self.assertIn("~/workspace/h/styled-app", global_plain)

            # 3. FORCE_COLOR=1 emits ANSI escapes, NO_COLOR=1 suppresses them
            color_env = dict(env)
            color_env.pop("NO_COLOR", None)
            color_env["FORCE_COLOR"] = "1"
            color_out = self._run(color_env, repo, "status").stdout
            self.assertIn("\x1b[", color_out)

            nocolor_env = dict(color_env)
            nocolor_env["NO_COLOR"] = "1"
            nocolor_out = self._run(nocolor_env, repo, "status").stdout
            self.assertNotIn("\x1b[", nocolor_out)

            # 4. --json remains valid pure JSON even under FORCE_COLOR=1
            json_out = self._run(color_env, repo, "status", "--json").stdout
            parsed = json.loads(json_out)
            self.assertEqual(parsed["repo_name"], "styled-app")

    def test_monitor_filters_inherited_main_tasks_and_deduplicates_pulse_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            repo, origin, _, env = _create_repo_harness(root / "h", "legacy-repo", cfg)
            subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", "https://github.com/acme/legacy-repo.git"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", f"url.{origin}.insteadOf", "https://github.com/acme/legacy-repo.git"], check=True)

            # Seed 8 historical non-issue TASK directories committed on main
            for idx in range(1, 9):
                old_dir = repo / "TASK" / f"old-feature-{idx}"
                old_dir.mkdir(parents=True, exist_ok=True)
                (old_dir / "TASK-01.md").write_text(
                    f"# TASK-01：历史遗留 {idx}\n\n- Issue: old-feature-{idx}\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                    encoding="utf-8",
                )
            subprocess.run(["git", "-C", str(repo), "add", "TASK"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: seed legacy tasks"], check=True, capture_output=True)

            # Also create a worktree matching an already-done non-issue main/TASK/old-feature-1 dir -> should be filtered out
            done_wt = root / "done-legacy-wt"
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "-b", "feature/old-feature-1", str(done_wt), "main"],
                check=True,
                capture_output=True,
            )

            # Create an isolated worktree for #42 with 2 split TASKs
            wt42 = Path(json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            tdir = wt42 / "TASK/42-export-csv"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "TASK-01-impl.md").write_text(
                "# TASK-01：实现接口\n\n- Issue: #42\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                encoding="utf-8",
            )
            (tdir / "TASK-02-test.md").write_text(
                "# TASK-02：补充测试\n\n- Issue: #42\n- Status: in_progress\n- Depends on: TASK-01\n- Test: pytest\n",
                encoding="utf-8",
            )

            with mock.patch.object(monitor, "inspect_worktree_pulse", wraps=monitor.inspect_worktree_pulse) as spy_pulse:
                snap = monitor.collect_repo_snapshot(repo, local_only=True, register=False)
                self.assertLessEqual(spy_pulse.call_count, 2)

            self.assertEqual(snap["local_only_items"], [])
            self.assertEqual(len(snap["issues"]), 1)
            row42 = snap["issues"][0]
            self.assertEqual(row42["issue_number"], 42)
            self.assertEqual(row42["url"], "https://github.com/acme/legacy-repo/issues/42")
            self.assertEqual([t["status"] for t in row42["tasks"]], ["done", "in_progress"])

    def test_async_forge_cache_non_blocking_and_host_deduplicated_auth_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            repo1, _, _, _ = _create_repo_harness(root / "h1", "svc-one", cfg)
            repo2, _, _, _ = _create_repo_harness(root / "h2", "svc-two", cfg)
            subprocess.run(["git", "-C", str(repo1), "remote", "set-url", "origin", "http://127.0.0.1:19999/org/svc-one.git"], check=True)
            subprocess.run(["git", "-C", str(repo2), "remote", "set-url", "origin", "http://127.0.0.1:19999/org/svc-two.git"], check=True)

            with mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": str(cfg)}, clear=False):
                os.environ.pop("GITLAB_TOKEN", None)
                os.environ.pop("GITLAB_PRIVATE_TOKEN", None)
                for rec_repo in (repo1, repo2):
                    monitor.register_repo(rec_repo)

                cache = monitor.ForgeSnapshotCache(ttl_seconds=30.0)
                t0 = time.perf_counter()
                fast_snap = monitor.collect_global_snapshot(
                    current_cwd=root,
                    forge_cache=cache,
                    allow_stale_async=True,
                )
                elapsed = time.perf_counter() - t0
                self.assertLess(elapsed, 2.0)
                self.assertTrue(fast_snap["forge_syncing"])

                sync_snap = monitor.collect_global_snapshot(
                    current_cwd=root,
                    forge_cache=cache,
                    force_refresh=True,
                    allow_stale_async=False,
                )
                self.assertFalse(sync_snap["forge_syncing"])
                self.assertEqual(len(sync_snap["auth_alerts"]), 1)
                alert = sync_snap["auth_alerts"][0]
                self.assertEqual(alert["api_base"], "http://127.0.0.1:19999")
                self.assertEqual(set(alert["repos"]), {"svc-one", "svc-two"})
                self.assertIn("idd auth login http://127.0.0.1:19999 --token", alert["login_cmd"])
                self.assertEqual(len(sync_snap["warnings"]), 1)

    def test_board_in_browser_token_save_status_logout_and_repo_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            empty_dir = root / "workspace"
            empty_dir.mkdir()
            repo, origin, _, env = _create_repo_harness(root / "gl", "demo", cfg)

            gl_state = MockGitLabState(origin)
            gl_server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(gl_state))
            gl_port = gl_server.server_address[1]
            gl_base = f"http://127.0.0.1:{gl_port}"
            gl_state.base_url = gl_base
            gl_state.issues[1] = {
                "iid": 1,
                "title": "浏览器直接填令牌同步 GitLab Issue",
                "description": "Zero CLI login",
                "labels": ["feat"],
                "state": "opened",
                "web_url": f"{gl_base}/dept/sub/demo/-/issues/1",
            }
            threading.Thread(target=gl_server.serve_forever, daemon=True).start()

            subprocess.run(
                ["git", "-C", str(repo), "remote", "set-url", "origin", f"{gl_base}/dept/sub/demo.git"],
                check=True,
            )

            sub_env = dict(env)
            sub_env["PYTHONUNBUFFERED"] = "1"
            sub_env.pop("GITLAB_TOKEN", None)
            sub_env.pop("GITLAB_PRIVATE_TOKEN", None)
            sub_env.pop("IDD_FORGE", None)
            with mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": str(cfg)}, clear=False):
                monitor.register_repo(repo)

            proc = subprocess.Popen(
                [sys.executable, str(IDD_BIN), "board", "--host", "127.0.0.1", "--port", "0", "--no-open"],
                cwd=str(empty_dir),
                env=sub_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                banner = proc.stdout.readline().strip()
                m = re.search(r"(http://127\.0\.0\.1:\d+)", banner)
                self.assertIsNotNone(m, f"Unexpected board startup output: {banner!r}")
                base_url = m.group(1)

                # 1. Wait briefly for initial async probe to record missing GitLab token alert
                deadline = time.monotonic() + 4.0
                snap_before = {}
                while time.monotonic() < deadline:
                    with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                        snap_before = json.loads(resp.read().decode("utf-8"))
                    if not snap_before.get("forge_syncing") and snap_before.get("auth_alerts"):
                        break
                    time.sleep(0.05)
                self.assertEqual(len(snap_before.get("auth_alerts", [])), 1)
                self.assertEqual(snap_before["repos"][0]["forge"], "gitlab")
                self.assertEqual(snap_before["repos"][0]["repo_url"], f"{gl_base}/dept/sub/demo")

                with urllib.request.urlopen(f"{base_url}/api/auth/status", timeout=5) as resp:
                    st_before = json.loads(resp.read().decode("utf-8"))
                    self.assertGreaterEqual(st_before["unconfigured_count"], 1)
                    gl_host = next(h for h in st_before["hosts"] if h["api_base"] == gl_base)
                    self.assertFalse(gl_host["configured"])
                    self.assertEqual(gl_host["repos"][0]["url"], f"{gl_base}/dept/sub/demo")

                # 2. Reject missing CSRF header or foreign Origin
                req_no_csrf = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps({"host": gl_base, "token": "glpat-secret"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as csrf_err:
                    urllib.request.urlopen(req_no_csrf, timeout=5)
                self.assertEqual(csrf_err.exception.code, 403)
                csrf_err.exception.close()

                req_bad_origin = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps({"host": gl_base, "token": "glpat-secret"}).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-IDD-Request": "1",
                        "Origin": "https://evil.example.com",
                    },
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as origin_err:
                    urllib.request.urlopen(req_bad_origin, timeout=5)
                self.assertEqual(origin_err.exception.code, 403)
                origin_err.exception.close()

                # 3. Reject invalid token via live `/api/v4/user` verification
                req_bad_tok = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps({"host": gl_base, "token": "wrong-token"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as bad_tok_err:
                    urllib.request.urlopen(req_bad_tok, timeout=5)
                self.assertEqual(bad_tok_err.exception.code, 400)
                bad_payload = json.loads(bad_tok_err.exception.read().decode("utf-8"))
                self.assertFalse(bad_payload["ok"])
                bad_tok_err.exception.close()

                # 4. Save valid token directly via browser API -> verifies, writes 0600 hosts.json, and loads Issues!
                req_save = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps({"host": gl_base, "token": "glpat-secret", "forge": "gitlab"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_save, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    saved = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(saved["ok"])
                    self.assertEqual(saved["username"], "j.tide")

                hosts_path = cfg / "hosts.json"
                self.assertTrue(hosts_path.is_file())
                self.assertEqual(stat.S_IMODE(hosts_path.stat().st_mode), 0o600)

                with urllib.request.urlopen(f"{base_url}/api/auth/status", timeout=5) as resp:
                    raw_status_txt = resp.read().decode("utf-8")
                    self.assertNotIn("glpat-secret", raw_status_txt)
                    st_after = json.loads(raw_status_txt)
                    gl_after = next(h for h in st_after["hosts"] if h["api_base"] == gl_base)
                    self.assertTrue(gl_after["configured"])
                    self.assertEqual(gl_after["username"], "j.tide")

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap_after = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(snap_after["auth_alerts"], [])
                    self.assertEqual(len(snap_after["issues"]), 1)
                    issue1 = snap_after["issues"][0]
                    self.assertEqual(issue1["issue_number"], 1)
                    self.assertEqual(issue1["forge_type"], "gitlab")
                    self.assertEqual(issue1["repo_url"], f"{gl_base}/dept/sub/demo")
                    self.assertEqual(issue1["url"], f"{gl_base}/dept/sub/demo/-/issues/1")

                # 5. Logout removes saved host token cleanly
                req_logout = urllib.request.Request(
                    f"{base_url}/api/auth/logout",
                    data=json.dumps({"host": gl_base}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_logout, timeout=5) as resp:
                    out_logout = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(out_logout["ok"])
                    self.assertTrue(out_logout["removed"])
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
                gl_server.shutdown()
                gl_server.server_close()

    def test_pulse_detects_unpushed_branch_and_ahead_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            repo, _, _, env = _create_repo_harness(root / "h", "pulse-repo", cfg)

            wt = Path(
                json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--no-push", "--json").stdout)[
                    "worktree"
                ]
            )
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            pulse_unpushed = monitor.inspect_worktree_pulse(
                wt,
                branch="feat/42-export-csv",
                has_origin=True,
                default_branch="main",
            )
            self.assertEqual(pulse_unpushed["remote_state"], "unpushed_branch")
            self.assertFalse(pulse_unpushed["remote_branch_exists"])
            self.assertIn("未推远端", pulse_unpushed["pulse_summary"])

            status_unpushed = self._run(env, repo, "status", "--local-only").stdout
            watch_unpushed = self._run(env, repo, "watch", "--once", "--local-only").stdout
            self.assertIn("未推远端", status_unpushed)
            self.assertIn("未推远端", watch_unpushed)

            # Push branch -> synced
            subprocess.run(["git", "-C", str(wt), "push", "-u", "origin", "HEAD"], check=True, capture_output=True)
            pulse_synced = monitor.inspect_worktree_pulse(
                wt,
                branch="feat/42-export-csv",
                has_origin=True,
                default_branch="main",
            )
            self.assertEqual(pulse_synced["remote_state"], "synced")
            self.assertTrue(pulse_synced["remote_branch_exists"])
            self.assertEqual(pulse_synced["unpushed_commits"], 0)

            # Add 1 local commit without pushing -> ahead
            (wt / "app.py").write_text("line1 = 1\nline2 = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "app.py"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: local only commit"], check=True, capture_output=True)

            pulse_ahead = monitor.inspect_worktree_pulse(
                wt,
                branch="feat/42-export-csv",
                has_origin=True,
                default_branch="main",
            )
            self.assertEqual(pulse_ahead["remote_state"], "ahead")
            self.assertEqual(pulse_ahead["unpushed_commits"], 1)
            self.assertIn("↑1待推送", pulse_ahead["pulse_summary"])

            status_ahead = self._run(env, repo, "status", "--local-only").stdout
            self.assertIn("↑1 待推送", status_ahead)


if __name__ == "__main__":
    unittest.main()
