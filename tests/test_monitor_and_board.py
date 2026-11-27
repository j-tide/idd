"""End-to-end tests for global repo registry, live worktree pulse, `idd watch`, and `idd board`."""

from __future__ import annotations

import errno
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import struct
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

import board_ui  # noqa: E402
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
                    self.assertIn("resolvePrimaryLink", html)
                    self.assertIn("renderPrimaryLinkBtn", html)
                    self.assertNotIn("renderOpenIssueBtn", html)
                    self.assertIn("renderReposView", html)
                    self.assertIn("cleanup-drawer", html)
                    self.assertIn('id="view-repos" class="sb-item active"', html)
                    self.assertIn('localStorage.getItem("idd_board_view") || "repos"', html)
                    self.assertIn('["repos", "kanban", "list"]', html)
                    self.assertNotIn("view-cockpit", html)
                    self.assertNotIn("workbench-grid", html)
                    self.assertNotIn("renderCockpitView", html)
                    self.assertIn("auth_alerts", html)
                    self.assertIn("forge_syncing", html)
                    self.assertIn("forge_connections", html)
                    self.assertIn("renderForgeStatus", html)
                    self.assertIn("buildHandoffPrompt", html)
                    self.assertNotIn("backlog", html.lower())
                    self.assertNotIn("__IDD_VERSION__", html)
                    self.assertNotIn("cdn.", html.lower())
                    for element_id in (
                        "top-progress",
                        "status-cluster",
                        "forge-status-group",
                        "forge-status-popover",
                        "view-repos",
                        "view-kanban",
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
                    self.assertNotIn("sync-banner-wrap", html)
                    self.assertNotIn("renderSyncBanner", html)
                    self.assertNotIn("本地工作树已就绪，正在后台同步", html)
                    self.assertNotIn("已快速恢复上次视图，正在拉取最新状态", html)
                    self.assertIn(".workspace > #top-alerts-wrap:empty", html)
                    self.assertIn("#sync-btn { min-width: 88px; justify-content: center; }", html)
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
                    self.assertTrue(snap1["local_only"])
                    self.assertIn("github", snap1["forge_connections"])
                    self.assertIn("gitlab", snap1["forge_connections"])
                    self.assertIn(snap1["forge_connections"]["github"]["status"], ("local_only", "unconfigured"))

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

            # Even if main later deletes historical TASK/, the older worktree must still hide inherited TASKs via merge-base
            subprocess.run(["git", "-C", str(repo), "rm", "-rf", "--quiet", "TASK"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: clean main legacy tasks"], check=True, capture_output=True)
            snap_after_main_clean = monitor.collect_repo_snapshot(repo, local_only=True, register=False)
            self.assertEqual(snap_after_main_clean["local_only_items"], [])
            self.assertEqual([r["issue_number"] for r in snap_after_main_clean["issues"]], [42])

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

    @staticmethod
    def _make_handler(path: str, wfile: object) -> board_ui.BoardRequestHandler:
        handler = board_ui.BoardRequestHandler.__new__(board_ui.BoardRequestHandler)
        handler.path = path
        handler.command = "GET"
        handler.requestline = f"GET {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.headers = {}
        handler.close_connection = False
        handler.wfile = wfile
        handler.cache = monitor.ForgeSnapshotCache(ttl_seconds=30.0)
        handler.root = None
        handler.global_mode = False
        handler.local_only = True
        handler.version = "0.0.3"
        return handler

    def test_board_handler_ignores_client_disconnect_without_double_error(self) -> None:
        class _BrokenPipeWfile:
            def __init__(self, exc: BaseException) -> None:
                self.exc = exc

            def write(self, _data: bytes) -> int:
                raise self.exc

        for endpoint in ("/api/snapshot", "/api/auth/status"):
            for exc in (BrokenPipeError("broken pipe"), ConnectionResetError("reset by peer")):
                handler = self._make_handler(endpoint, _BrokenPipeWfile(exc))
                with (
                    mock.patch.object(monitor, "collect_scope_snapshot", return_value={"issues": []}),
                    mock.patch.object(monitor, "collect_auth_hosts_status", return_value={"hosts": []}),
                    mock.patch.object(handler, "_send_json", wraps=handler._send_json) as spy_send,
                ):
                    handler.do_GET()
                self.assertTrue(handler.close_connection)
                self.assertEqual([call.args[0] for call in spy_send.call_args_list], [HTTPStatus.OK])

        # Real business exception still returns 500 JSON when client is connected
        ok_buf = io.BytesIO()
        handler_500 = self._make_handler("/api/snapshot", ok_buf)
        with mock.patch.object(monitor, "collect_scope_snapshot", side_effect=RuntimeError("boom")):
            handler_500.do_GET()
        raw_resp = ok_buf.getvalue().decode("utf-8")
        self.assertIn("500 Internal Server Error", raw_resp)
        self.assertIn('"error": "boom"', raw_resp)

        # Business exception followed by client disconnect during 500 write still exits cleanly
        handler_500_broken = self._make_handler("/api/auth/status", _BrokenPipeWfile(BrokenPipeError("gone")))
        with mock.patch.object(monitor, "collect_auth_hosts_status", side_effect=RuntimeError("auth boom")):
            handler_500_broken.do_GET()
        self.assertTrue(handler_500_broken.close_connection)

    def test_board_server_handle_error_suppresses_disconnects_only(self) -> None:
        server = board_ui.BoardHTTPServer(("127.0.0.1", 0), board_ui.BoardRequestHandler, bind_and_activate=False)
        try:
            for exc in (
                BrokenPipeError("broken"),
                ConnectionResetError("reset"),
                ConnectionAbortedError("aborted"),
                OSError(errno.EPIPE, "epipe"),
            ):
                stderr_buf = io.StringIO()
                try:
                    raise exc
                except BaseException:
                    with mock.patch("sys.stderr", new=stderr_buf):
                        server.handle_error(None, ("127.0.0.1", 12345))
                self.assertEqual(stderr_buf.getvalue(), "")

            unexpected_buf = io.StringIO()
            try:
                raise RuntimeError("unexpected server error")
            except RuntimeError:
                with mock.patch("sys.stderr", new=unexpected_buf):
                    server.handle_error(None, ("127.0.0.1", 12345))
            self.assertIn("RuntimeError: unexpected server error", unexpected_buf.getvalue())
        finally:
            server.server_close()

    def test_board_live_server_aborted_clients_produce_no_stderr_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir(parents=True, exist_ok=True)
            empty_dir = root / "workspace"
            empty_dir.mkdir(parents=True, exist_ok=True)

            sub_env = dict(os.environ)
            sub_env["IDD_CONFIG_DIR"] = str(cfg)
            sub_env["IDD_NO_BROWSER"] = "1"
            sub_env["PYTHONUNBUFFERED"] = "1"

            proc = subprocess.Popen(
                [sys.executable, str(IDD_BIN), "board", "--host", "127.0.0.1", "--port", "0", "--local-only", "--no-open"],
                cwd=str(empty_dir),
                env=sub_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                banner = proc.stdout.readline().strip()
                m = re.search(r"http://127\.0\.0\.1:(\d+)", banner)
                self.assertIsNotNone(m, f"Unexpected board startup output: {banner!r}")
                port = int(m.group(1))
                linger_rst = struct.pack("ii", 1, 0)

                # (a) Connect and immediately send RST without sending request bytes
                for _ in range(3):
                    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger_rst)
                    sock.close()

                # (b) Send HTTP requests (HTML + API) and immediately abort socket before reading
                for req_path in ("/", "/api/snapshot", "/api/auth/status"):
                    for _ in range(3):
                        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger_rst)
                        sock.sendall(f"GET {req_path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("ascii"))
                        sock.close()

                # Confirm server stays healthy after aborted connections
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    health = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(health["ok"])
            finally:
                proc.terminate()
                try:
                    _, stderr_out = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _, stderr_out = proc.communicate(timeout=5)

            self.assertNotIn("Traceback", stderr_out)
            self.assertNotIn("BrokenPipeError", stderr_out)
            self.assertNotIn("ConnectionResetError", stderr_out)

    def test_board_auto_repo_init_on_token_save_and_manual_retry_endpoint(self) -> None:
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

                # 1. Save token with `auto_repo_init: false` (skipped) -> marks `pending` with mismatches
                req_save_skip = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps(
                        {"host": gl_base, "token": "glpat-secret", "forge": "gitlab", "auto_repo_init": False}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_save_skip, timeout=5) as resp:
                    saved_skip = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(saved_skip["ok"])
                    self.assertEqual(len(saved_skip["repo_init_results"]), 1)
                    self.assertEqual(saved_skip["repo_init_results"][0]["state"], "pending")

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap_pending = json.loads(resp.read().decode("utf-8"))
                ri_pending = snap_pending["repos"][0]["repo_init"]
                self.assertEqual(ri_pending["state"], "pending")
                self.assertTrue(any("squash_commit_template=" in x for x in ri_pending["mismatches"]))

                # 2. `/api/repo/init` enforces CSRF and registered-repo whitelist
                req_no_csrf = urllib.request.Request(
                    f"{base_url}/api/repo/init",
                    data=json.dumps({"repo_path": str(repo)}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as csrf_err:
                    urllib.request.urlopen(req_no_csrf, timeout=5)
                self.assertEqual(csrf_err.exception.code, 403)
                csrf_err.exception.close()

                req_bad_repo = urllib.request.Request(
                    f"{base_url}/api/repo/init",
                    data=json.dumps({"repo_path": str(empty_dir)}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as bad_repo_err:
                    urllib.request.urlopen(req_bad_repo, timeout=5)
                self.assertEqual(bad_repo_err.exception.code, 403)
                bad_repo_err.exception.close()

                # 3. Simulated 403 on PUT keeps `pending` + error in snapshot
                gl_state.fail_repo_init_put = True
                req_retry_fail = urllib.request.Request(
                    f"{base_url}/api/repo/init",
                    data=json.dumps({"repo_path": str(repo)}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_retry_fail, timeout=5) as resp:
                    fail_res = json.loads(resp.read().decode("utf-8"))
                    self.assertFalse(fail_res["ok"])
                    self.assertEqual(fail_res["failed_count"], 1)
                    self.assertIn("403", fail_res["error"])

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap_err = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(snap_err["repos"][0]["repo_init"]["state"], "pending")
                self.assertIn("403", snap_err["repos"][0]["repo_init"]["error"])

                # 4. Retry succeeds once permissions are restored -> `aligned` + Squash template saved
                gl_state.fail_repo_init_put = False
                req_retry_ok = urllib.request.Request(
                    f"{base_url}/api/repo/init",
                    data=json.dumps({"repo_path": str(repo)}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_retry_ok, timeout=5) as resp:
                    ok_res = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(ok_res["ok"])
                    self.assertEqual(ok_res["applied_count"], 1)

                self.assertEqual(gl_state.project_settings["merge_method"], "ff")
                self.assertEqual(gl_state.project_settings["squash_option"], "always")
                self.assertFalse(gl_state.project_settings["remove_source_branch_after_merge"])
                self.assertEqual(gl_state.project_settings["squash_commit_template"], "%{title}\n\n%{description}")

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap_aligned = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(snap_aligned["repos"][0]["repo_init"]["state"], "aligned")
                self.assertEqual(snap_aligned["repos"][0]["repo_init"]["error"], "")

                # 5. Reset GitLab settings & `repos.json` state -> default `auto_repo_init: true` aligns automatically on `/api/auth/save`
                gl_state.project_settings.update({
                    "merge_method": "merge",
                    "squash_option": "default_off",
                    "remove_source_branch_after_merge": True,
                    "squash_commit_template": "%{title}",
                })
                with mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": str(cfg)}, clear=False):
                    monitor.set_repo_init_meta(repo, "")

                req_save_auto = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps({"host": gl_base, "token": "glpat-secret", "forge": "gitlab"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_save_auto, timeout=5) as resp:
                    saved_auto = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(saved_auto["ok"])
                    self.assertEqual(len(saved_auto["repo_init_results"]), 1)
                    self.assertTrue(saved_auto["repo_init_results"][0]["aligned"])
                self.assertEqual(gl_state.project_settings["merge_method"], "ff")
                self.assertEqual(gl_state.project_settings["squash_commit_template"], "%{title}\n\n%{description}")
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

    def test_forge_connections_states_and_gh_username_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            cfg.mkdir(parents=True, exist_ok=True)
            env_patch = {"IDD_CONFIG_DIR": str(cfg)}
            with mock.patch.dict(os.environ, env_patch, clear=False):
                for key in ("GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "GITLAB_PRIVATE_TOKEN"):
                    os.environ.pop(key, None)

                # 1. `gh auth status` username parsing (modern "account X" and legacy "as X")
                monitor._GH_CLI_CACHE["checked_at"] = 0.0
                fake_proc_new = subprocess.CompletedProcess(
                    ["gh", "auth", "status"],
                    0,
                    stdout="github.com\n  ✓ Logged in to github.com account j-tide (keyring)\n",
                    stderr="",
                )
                with (
                    mock.patch.object(monitor.shutil, "which", return_value="/usr/bin/gh"),
                    mock.patch.object(monitor.subprocess, "run", return_value=fake_proc_new),
                ):
                    ok, user = monitor._check_gh_cli_status(ttl=30.0)
                    self.assertTrue(ok)
                    self.assertEqual(user, "j-tide")

                monitor._GH_CLI_CACHE["checked_at"] = 0.0
                fake_proc_old = subprocess.CompletedProcess(
                    ["gh", "auth", "status"],
                    0,
                    stdout="",
                    stderr="github.com\n  ✓ Logged in to github.com as octocat (oauth_token)\n",
                )
                with (
                    mock.patch.object(monitor.shutil, "which", return_value="/usr/bin/gh"),
                    mock.patch.object(monitor.subprocess, "run", return_value=fake_proc_old),
                ):
                    ok, user = monitor._check_gh_cli_status(ttl=30.0)
                    self.assertTrue(ok)
                    self.assertEqual(user, "octocat")

                # 2. `_build_forge_connections` across states
                with mock.patch.object(monitor, "_check_gh_cli_status", return_value=(False, "")):
                    empty_conns = monitor._build_forge_connections([], local_only=False)
                    self.assertEqual(empty_conns["github"]["status"], "unconfigured")
                    self.assertEqual(empty_conns["gitlab"]["status"], "unconfigured")

                    # Connected GitHub repo stays `connected` during background TTL revalidation
                    gh_connected = monitor._build_forge_connections(
                        [
                            {
                                "repo_name": "idd",
                                "repo_url": "https://github.com/j-tide/idd",
                                "forge": "github",
                                "forge_host": "github.com",
                                "forge_api_base": "https://github.com",
                                "forge_connected": True,
                                "forge_syncing": True,
                                "forge_error": "",
                                "auth_alert": None,
                                "forge_fetched_at": 1234.0,
                            }
                        ]
                    )
                    self.assertEqual(gh_connected["github"]["status"], "connected")
                    self.assertEqual(gh_connected["github"]["connected_repos"], 1)

                    # Syncing, partial, auth_required, error, and local_only
                    mixed = monitor._build_forge_connections(
                        [
                            {
                                "repo_name": "gh-sync",
                                "repo_url": "https://github.com/acme/gh-sync",
                                "forge": "github",
                                "forge_host": "github.com",
                                "forge_api_base": "https://github.com",
                                "forge_connected": False,
                                "forge_syncing": True,
                                "forge_error": "",
                                "auth_alert": None,
                                "forge_fetched_at": 0.0,
                            },
                            {
                                "repo_name": "gl-ok",
                                "repo_url": "http://10.0.0.5:8080/team/gl-ok",
                                "forge": "gitlab",
                                "forge_host": "10.0.0.5:8080",
                                "forge_api_base": "http://10.0.0.5:8080",
                                "forge_connected": True,
                                "forge_syncing": False,
                                "forge_error": "",
                                "auth_alert": None,
                                "forge_fetched_at": 1234.0,
                            },
                            {
                                "repo_name": "gl-bad",
                                "repo_url": "http://10.0.0.5:8080/team/gl-bad",
                                "forge": "gitlab",
                                "forge_host": "10.0.0.5:8080",
                                "forge_api_base": "http://10.0.0.5:8080",
                                "forge_connected": False,
                                "forge_syncing": False,
                                "forge_error": "无法连接 GitLab",
                                "auth_alert": None,
                                "forge_fetched_at": 1234.0,
                            },
                        ]
                    )
                    self.assertEqual(mixed["github"]["status"], "syncing")
                    self.assertEqual(mixed["gitlab"]["status"], "partial")
                    self.assertEqual(mixed["gitlab"]["connected_repos"], 1)
                    self.assertEqual(mixed["gitlab"]["total_repos"], 2)

                    gl_err = monitor._build_forge_connections(
                        [
                            {
                                "repo_name": "gl-only",
                                "repo_url": "http://10.0.0.5:8080/team/gl-only",
                                "forge": "gitlab",
                                "forge_host": "10.0.0.5:8080",
                                "forge_api_base": "http://10.0.0.5:8080",
                                "forge_connected": False,
                                "forge_syncing": False,
                                "forge_error": "无法连接 GitLab",
                                "auth_alert": None,
                                "forge_fetched_at": 1234.0,
                            }
                        ]
                    )
                    self.assertEqual(gl_err["gitlab"]["status"], "error")
                    self.assertEqual(gl_err["gitlab"]["error"], "无法连接 GitLab")

                    gl_auth = monitor._build_forge_connections(
                        [
                            {
                                "repo_name": "gl-auth",
                                "repo_url": "http://10.0.0.5:8080/team/gl-auth",
                                "forge": "gitlab",
                                "forge_host": "10.0.0.5:8080",
                                "forge_api_base": "http://10.0.0.5:8080",
                                "forge_connected": False,
                                "forge_syncing": False,
                                "forge_error": "GitLab 鉴权失败（HTTP 401）",
                                "auth_alert": {"host": "10.0.0.5:8080", "api_base": "http://10.0.0.5:8080"},
                                "forge_fetched_at": 1234.0,
                            }
                        ]
                    )
                    self.assertEqual(gl_auth["gitlab"]["status"], "auth_required")

                    local_conns = monitor._build_forge_connections(
                        [
                            {
                                "repo_name": "idd",
                                "repo_url": "https://github.com/j-tide/idd",
                                "forge": "github",
                                "forge_host": "github.com",
                                "forge_api_base": "https://github.com",
                                "forge_connected": False,
                                "forge_syncing": False,
                                "forge_error": "",
                                "auth_alert": None,
                                "forge_fetched_at": 0.0,
                            }
                        ],
                        local_only=True,
                    )
                    self.assertEqual(local_conns["github"]["status"], "local_only")
                    self.assertEqual(local_conns["gitlab"]["status"], "unconfigured")

    def test_board_forge_connections_transitions_auth_connected_and_offline(self) -> None:
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
            threading.Thread(target=gl_server.serve_forever, daemon=True).start()

            subprocess.run(
                ["git", "-C", str(repo), "remote", "set-url", "origin", f"{gl_base}/dept/sub/demo.git"],
                check=True,
            )

            sub_env = dict(env)
            sub_env["PYTHONUNBUFFERED"] = "1"
            for key in ("GITLAB_TOKEN", "GITLAB_PRIVATE_TOKEN", "IDD_FORGE"):
                sub_env.pop(key, None)
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
            gl_closed = False
            try:
                assert proc.stdout is not None
                banner = proc.stdout.readline().strip()
                m = re.search(r"(http://127\.0\.0\.1:\d+)", banner)
                self.assertIsNotNone(m, f"Unexpected board startup output: {banner!r}")
                base_url = m.group(1)

                def _wait_settled(refresh: bool = False) -> dict:
                    url = f"{base_url}/api/snapshot?refresh=1" if refresh else f"{base_url}/api/snapshot"
                    with urllib.request.urlopen(url, timeout=5) as resp:
                        snap = json.loads(resp.read().decode("utf-8"))
                    deadline = time.monotonic() + 5.0
                    while snap.get("forge_syncing") and time.monotonic() < deadline:
                        time.sleep(0.05)
                        with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                            snap = json.loads(resp.read().decode("utf-8"))
                    return snap

                # 1. Missing token -> `auth_required`
                snap_auth = _wait_settled(refresh=False)
                gl_conn = snap_auth["forge_connections"]["gitlab"]
                self.assertEqual(gl_conn["status"], "auth_required")
                self.assertEqual(gl_conn["total_repos"], 1)
                self.assertEqual(gl_conn["connected_repos"], 0)

                # 2. Save valid token -> `connected`
                req_save = urllib.request.Request(
                    f"{base_url}/api/auth/save",
                    data=json.dumps({"host": gl_base, "token": "glpat-secret", "forge": "gitlab"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_save, timeout=5) as resp:
                    self.assertTrue(json.loads(resp.read().decode("utf-8"))["ok"])

                snap_ok = _wait_settled(refresh=False)
                gl_conn_ok = snap_ok["forge_connections"]["gitlab"]
                self.assertEqual(gl_conn_ok["status"], "connected")
                self.assertEqual(gl_conn_ok["connected_repos"], 1)
                self.assertEqual(gl_conn_ok["hosts"][0]["username"], "j.tide")
                self.assertEqual(gl_conn_ok["hosts"][0]["auth_source"], "hosts.json")

                # 3. Token rejected (401) -> `auth_required`
                gl_state.expected_token = "rotated-secret"
                snap_expired = _wait_settled(refresh=True)
                self.assertEqual(snap_expired["forge_connections"]["gitlab"]["status"], "auth_required")

                # 4. Server unreachable -> `error` with message
                gl_server.shutdown()
                gl_server.server_close()
                gl_closed = True
                snap_err = _wait_settled(refresh=True)
                self.assertEqual(snap_err["forge_connections"]["gitlab"]["status"], "error")
                self.assertTrue(snap_err["forge_connections"]["gitlab"]["error"])
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
                if not gl_closed:
                    gl_server.shutdown()
                    gl_server.server_close()

    def test_board_primary_link_switches_to_pr_or_mr_when_change_exists(self) -> None:
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to evaluate board_ui.py helper functions")

        script_match = re.search(r"<script>(.*)</script>", board_ui.BOARD_HTML, re.S)
        self.assertIsNotNone(script_match)
        assert script_match is not None
        js_src = script_match.group(1)

        def _extract_js_fn(name: str) -> str:
            marker = f"function {name}("
            start = js_src.index(marker)
            brace_start = js_src.index("{", start)
            depth = 0
            for idx in range(brace_start, len(js_src)):
                ch = js_src[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return js_src[start : idx + 1]
            raise AssertionError(f"Unclosed JS function: {name}")

        harness_js = "\n".join(
            [
                "const state = { lang: 'zh' };",
                "const ICONS = { externalLink: '<path />' };",
                *(
                    _extract_js_fn(fn_name)
                    for fn_name in (
                        "isEn",
                        "tr",
                        "escapeHtml",
                        "safeUrl",
                        "icon",
                        "renderIdHtml",
                        "resolvePrimaryLink",
                        "renderPrimaryLinkBtn",
                    )
                ),
                r"""
                const assert = require('assert');

                const ghNoPr = {
                  _kind: 'issue',
                  issue_number: 21,
                  url: 'https://github.com/o/r/issues/21',
                  forge_type: 'github',
                  change: null
                };
                const ghWithPr = {
                  _kind: 'issue',
                  issue_number: 21,
                  stage: '🔵 待合入',
                  url: 'https://github.com/o/r/issues/21',
                  forge_type: 'github',
                  change: { number: 22, url: 'https://github.com/o/r/pull/22', checks_overall: 'PASS' }
                };
                const glWithMr = {
                  _kind: 'issue',
                  issue_number: 9,
                  stage: '🔵 待合入',
                  url: 'https://gitlab.example.com/g/p/-/issues/9',
                  forge_type: 'gitlab',
                  change: { number: 7, url: 'https://gitlab.example.com/g/p/-/merge_requests/7', checks_overall: 'PASS' }
                };
                const orphanGh = {
                  _kind: 'orphan',
                  number: 30,
                  url: 'https://github.com/o/r/pull/30',
                  forge_type: 'github',
                  mr_label: 'PR',
                  change: { number: 30, url: 'https://github.com/o/r/pull/30' }
                };
                const orphanGlFallback = {
                  _kind: 'orphan',
                  number: 12,
                  url: 'https://gitlab.example.com/g/p/-/merge_requests/12',
                  forge_type: 'gitlab',
                  mr_label: 'MR'
                };
                const unsafeChange = {
                  _kind: 'issue',
                  issue_number: 5,
                  url: 'https://github.com/o/r/issues/5',
                  forge_type: 'github',
                  change: { number: 6, url: 'javascript:alert(1)' }
                };
                const emptyChangeUrl = {
                  _kind: 'issue',
                  issue_number: 6,
                  url: 'https://github.com/o/r/issues/6',
                  forge_type: 'github',
                  change: { number: 8, url: '' }
                };
                const localOnly = {
                  _kind: 'local',
                  issue: 'scratch-task',
                  forge_type: 'local'
                };

                // Chinese mode
                state.lang = 'zh';
                const btnNoPrZh = renderPrimaryLinkBtn(ghNoPr, 'btn-xs');
                assert(btnNoPrZh.includes('href="https://github.com/o/r/issues/21"'));
                assert(btnNoPrZh.includes('<span>打开 Issue</span>'));
                assert(btnNoPrZh.includes('data-stop-open="1"'));

                const btnGhPrZh = renderPrimaryLinkBtn(ghWithPr, 'btn-xs');
                assert(btnGhPrZh.includes('href="https://github.com/o/r/pull/22"'));
                assert(btnGhPrZh.includes('<span>打开 PR</span>'));
                assert(!btnGhPrZh.includes('打开 Issue'));
                const idHtml = renderIdHtml(ghWithPr);
                assert(idHtml.includes('href="https://github.com/o/r/issues/21"'));
                assert(idHtml.includes('>#21</a>'));

                const btnGlMrZh = renderPrimaryLinkBtn(glWithMr, 'btn-xs');
                assert(btnGlMrZh.includes('href="https://gitlab.example.com/g/p/-/merge_requests/7"'));
                assert(btnGlMrZh.includes('<span>打开 MR</span>'));

                const btnOrphGhZh = renderPrimaryLinkBtn(orphanGh, 'btn-xs');
                assert(btnOrphGhZh.includes('href="https://github.com/o/r/pull/30"'));
                assert(btnOrphGhZh.includes('<span>打开 PR</span>'));

                const btnOrphGlZh = renderPrimaryLinkBtn(orphanGlFallback, 'btn-xs');
                assert(btnOrphGlZh.includes('href="https://gitlab.example.com/g/p/-/merge_requests/12"'));
                assert(btnOrphGlZh.includes('<span>打开 MR</span>'));

                assert(renderPrimaryLinkBtn(unsafeChange, 'btn-xs').includes('href="https://github.com/o/r/issues/5"'));
                assert(renderPrimaryLinkBtn(unsafeChange, 'btn-xs').includes('<span>打开 Issue</span>'));
                assert(renderPrimaryLinkBtn(emptyChangeUrl, 'btn-xs').includes('href="https://github.com/o/r/issues/6"'));
                assert.strictEqual(renderPrimaryLinkBtn(localOnly, 'btn-xs'), '');

                const consoleBtn = renderPrimaryLinkBtn(ghWithPr, 'btn-sm', { iconSize: 12, stopOpen: false });
                assert(consoleBtn.includes('class="btn btn-sm"'));
                assert(consoleBtn.includes('width="12"'));
                assert(!consoleBtn.includes('data-stop-open'));

                // English mode
                state.lang = 'en';
                assert(renderPrimaryLinkBtn(ghNoPr, 'btn-xs').includes('<span>Open Issue</span>'));
                assert(renderPrimaryLinkBtn(ghWithPr, 'btn-xs').includes('<span>Open PR</span>'));
                assert(renderPrimaryLinkBtn(glWithMr, 'btn-xs').includes('<span>Open MR</span>'));
                assert(renderPrimaryLinkBtn(orphanGlFallback, 'btn-xs').includes('<span>Open MR</span>'));
                console.log('JS_PRIMARY_LINK_OK');
                """,
            ]
        )

        proc = subprocess.run(
            [node_bin, "-e", harness_js],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("JS_PRIMARY_LINK_OK", proc.stdout)

    def test_board_auto_merge_config_endpoints_security_and_ui_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            outside_dir = root / "outside"
            outside_dir.mkdir()
            repo, _, _, env = _create_repo_harness(root / "repo", "demo", cfg)

            sub_env = dict(env)
            sub_env["PYTHONUNBUFFERED"] = "1"
            with mock.patch.dict(os.environ, {"IDD_CONFIG_DIR": str(cfg)}, clear=False):
                monitor.register_repo(repo)

            proc = subprocess.Popen(
                [sys.executable, str(IDD_BIN), "board", "--host", "127.0.0.1", "--port", "0", "--local-only", "--no-open"],
                cwd=str(outside_dir),
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

                # 1. Initial GET /api/config & /api/snapshot default to False
                with urllib.request.urlopen(f"{base_url}/api/config", timeout=5) as resp:
                    cfg_data = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(cfg_data["ok"])
                    self.assertFalse(cfg_data["auto_merge"])

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap0 = json.loads(resp.read().decode("utf-8"))
                    self.assertFalse(snap0["config"]["auto_merge"])
                    self.assertFalse(snap0["repos"][0]["auto_merge"]["enabled"])
                    self.assertEqual(snap0["repos"][0]["auto_merge"]["source"], "global")

                # 2. Missing CSRF header -> 403
                req_no_csrf = urllib.request.Request(
                    f"{base_url}/api/config/auto-merge",
                    data=json.dumps({"scope": "global", "enabled": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as csrf_err:
                    urllib.request.urlopen(req_no_csrf, timeout=5)
                self.assertEqual(csrf_err.exception.code, 403)
                csrf_err.exception.close()

                # 3. Repo-level scope is rejected -> 400
                req_bad_repo = urllib.request.Request(
                    f"{base_url}/api/config/auto-merge",
                    data=json.dumps({"scope": "repo", "repo_path": str(repo), "value": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as repo_err:
                    urllib.request.urlopen(req_bad_repo, timeout=5)
                self.assertEqual(repo_err.exception.code, 400)
                repo_err.exception.close()

                # 4. Invalid payload type -> 400
                req_bad_val = urllib.request.Request(
                    f"{base_url}/api/config/auto-merge",
                    data=json.dumps({"scope": "global", "enabled": "yes"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as val_err:
                    urllib.request.urlopen(req_bad_val, timeout=5)
                self.assertEqual(val_err.exception.code, 400)
                val_err.exception.close()

                # 5. Toggle global ON (omitting scope) -> snapshot reflects global=True and repo enabled=True
                req_g_on = urllib.request.Request(
                    f"{base_url}/api/config/auto-merge",
                    data=json.dumps({"enabled": True}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_g_on, timeout=5) as resp:
                    g_res = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(g_res["ok"])
                    self.assertTrue(g_res["auto_merge"])

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap1 = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(snap1["config"]["auto_merge"])
                    self.assertTrue(snap1["repos"][0]["auto_merge"]["enabled"])
                    self.assertEqual(snap1["repos"][0]["auto_merge"]["source"], "global")

                # 6. Toggle global OFF with explicit scope -> snapshot reflects False
                req_g_off = urllib.request.Request(
                    f"{base_url}/api/config/auto-merge",
                    data=json.dumps({"scope": "global", "enabled": False}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-IDD-Request": "1"},
                    method="POST",
                )
                with urllib.request.urlopen(req_g_off, timeout=5) as resp:
                    g_off_res = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(g_off_res["ok"])
                    self.assertFalse(g_off_res["auto_merge"])

                with urllib.request.urlopen(f"{base_url}/api/snapshot", timeout=5) as resp:
                    snap2 = json.loads(resp.read().decode("utf-8"))
                    self.assertFalse(snap2["config"]["auto_merge"])
                    self.assertFalse(snap2["repos"][0]["auto_merge"]["enabled"])
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

        # Verify UI markers and JS syntax validity
        html_doc = board_ui.BOARD_HTML
        self.assertIn("data-am-global-toggle", html_doc)
        self.assertIn("data-am-quick-global", html_doc)
        self.assertIn("am-confirm-overlay", html_doc)
        self.assertIn("am-confirm-modal", html_doc)
        self.assertIn("openAutoMergeConfirm", html_doc)
        self.assertIn("PR 自动准入", html_doc)
        self.assertNotIn("data-am-repo-val", html_doc)
        self.assertNotIn("data-am-quick-repo", html_doc)
        self.assertNotIn("sb-auto-tag", html_doc)
        self.assertNotIn("全局自动合入", html_doc)
        self.assertIn("/api/config/auto-merge", html_doc)

        node_bin = shutil.which("node")
        if node_bin:
            script_match = re.search(r"<script>\s*([\s\S]*?)\s*</script>", html_doc)
            self.assertIsNotNone(script_match)
            js_src = script_match.group(1)
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=True) as js_tmp:
                js_tmp.write(js_src)
                js_tmp.flush()
                chk = subprocess.run([node_bin, "--check", js_tmp.name], capture_output=True, text=True, check=False)
                self.assertEqual(chk.returncode, 0, chk.stderr or chk.stdout)

            def _extract_js_fn(name: str) -> str:
                marker = f"function {name}("
                start = js_src.index(marker)
                brace_start = js_src.index("{", start)
                depth = 0
                for idx in range(brace_start, len(js_src)):
                    ch = js_src[idx]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            return js_src[start : idx + 1]
                raise AssertionError(f"Unclosed JS function: {name}")

            ui_harness = "\n".join(
                [
                    """
                    const els = {};
                    function mkEl(id) {
                      return {
                        id,
                        textContent: '',
                        innerHTML: '',
                        className: '',
                        style: {},
                        attrs: {},
                        classList: {
                          set: new Set(),
                          add(c) { this.set.add(c); },
                          remove(c) { this.set.delete(c); },
                          contains(c) { return this.set.has(c); }
                        },
                        setAttribute(k, v) { this.attrs[k] = String(v); }
                      };
                    }
                    ['ws-title','ws-logo','scope-tag','ws-repo-link-wrap','am-confirm-overlay','am-confirm-modal'].forEach((id) => {
                      els[id] = mkEl(id);
                    });
                    const document = { getElementById: (id) => els[id] || null };
                    const ICONS = { branch: '<b/>', github: '<gh/>', gitlab: '<gl/>', externalLink: '<ext/>', alertTriangle: '<w/>', pr: '<pr/>', x: '<x/>', check: '<c/>' };
                    const state = {
                      lang: 'zh',
                      selectedRepo: 'ALL',
                      repoInitRunning: {},
                      autoMergeSaving: {},
                      amConfirm: null,
                      snapshot: {
                        global: true,
                        config: { auto_merge: false },
                        repos: [
                          {
                            repo_path: '/repos/gh',
                            repo_name: 'gh-repo',
                            repo_url: 'https://github.com/o/gh-repo',
                            forge: 'github',
                            repo_init: { state: 'aligned' },
                            auto_merge: { enabled: false, source: 'global' }
                          },
                          {
                            repo_path: '/repos/gl',
                            repo_name: 'gl-repo',
                            repo_url: 'https://gitlab.example.com/g/gl-repo',
                            forge: 'gitlab',
                            repo_init: { state: 'aligned' },
                            auto_merge: { enabled: false, source: 'global' }
                          }
                        ]
                      }
                    };
                    """,
                    *(
                        _extract_js_fn(fn_name)
                        for fn_name in (
                            "isEn",
                            "tr",
                            "escapeHtml",
                            "safeUrl",
                            "icon",
                            "forgeIcon",
                            "forgeLabel",
                            "renderRepoChip",
                            "renderWorkspaceHeader",
                            "openAutoMergeConfirm",
                            "closeAutoMergeConfirm",
                            "renderAutoMergeConfirmModal",
                        )
                    ),
                    """
                    const assert = require('assert');

                    // 1. Global workspace hides redundant #scope-tag and displays "PR 自动准入" without scope suffix
                    renderWorkspaceHeader(state.snapshot);
                    assert.strictEqual(els['scope-tag'].style.display, 'none');
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('PR 自动准入: 关'));
                    assert(!els['ws-repo-link-wrap'].innerHTML.includes('全局自动合入'));

                    state.snapshot.config.auto_merge = true;
                    renderWorkspaceHeader(state.snapshot);
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('PR 自动准入: 开'));
                    assert(!els['ws-repo-link-wrap'].innerHTML.includes('(全局)'));

                    // 2. Single GitHub & GitLab repo headers follow global state without (全局) / (仓库)
                    state.selectedRepo = '/repos/gh';
                    renderWorkspaceHeader(state.snapshot);
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('PR 自动准入: 开'));
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('data-am-quick-global="1"'));
                    assert(!els['ws-repo-link-wrap'].innerHTML.includes('(全局)'));
                    assert(!els['ws-repo-link-wrap'].innerHTML.includes('(仓库)'));

                    state.selectedRepo = '/repos/gl';
                    renderWorkspaceHeader(state.snapshot);
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('MR 自动准入: 开'));
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('data-am-quick-global="1"'));
                    assert(!els['ws-repo-link-wrap'].innerHTML.includes('(全局)'));
                    assert(!els['ws-repo-link-wrap'].innerHTML.includes('(仓库)'));

                    state.snapshot.config.auto_merge = false;
                    renderWorkspaceHeader(state.snapshot);
                    assert(els['ws-repo-link-wrap'].innerHTML.includes('MR 自动准入: 关'));

                    // 3. Confirmation warning modal opens before any mutation & closes on cancel
                    openAutoMergeConfirm(true, 'PR');
                    assert.ok(state.amConfirm);
                    assert.strictEqual(els['am-confirm-overlay'].attrs['aria-hidden'], 'false');
                    assert(els['am-confirm-overlay'].classList.contains('open'));
                    assert(els['am-confirm-modal'].innerHTML.includes('确认开启 PR 自动准入？'));
                    assert(els['am-confirm-modal'].innerHTML.includes('确认开启 PR 自动准入'));
                    assert(els['am-confirm-modal'].innerHTML.includes('Squash 直线合入'));
                    assert(!els['am-confirm-modal'].innerHTML.includes('未单独覆盖'));

                    closeAutoMergeConfirm();
                    assert.strictEqual(state.amConfirm, null);
                    assert.strictEqual(els['am-confirm-overlay'].attrs['aria-hidden'], 'true');
                    assert(!els['am-confirm-overlay'].classList.contains('open'));

                    // 4. Disable modal renders global restore-manual explanation
                    state.snapshot.config.auto_merge = true;
                    openAutoMergeConfirm(false, 'MR');
                    assert.ok(state.amConfirm);
                    assert(els['am-confirm-modal'].innerHTML.includes('确认关闭 MR 自动准入？'));
                    assert(els['am-confirm-modal'].innerHTML.includes('恢复人工把关'));
                    assert(els['am-confirm-modal'].innerHTML.includes('立即全局生效'));
                    console.log('JS_PR_AUTO_APPROVE_MODAL_OK');
                    """,
                ]
            )
            ui_proc = subprocess.run([node_bin, "-e", ui_harness], capture_output=True, text=True, check=False)
            self.assertEqual(ui_proc.returncode, 0, ui_proc.stderr or ui_proc.stdout)
            self.assertIn("JS_PR_AUTO_APPROVE_MODAL_OK", ui_proc.stdout)

    def test_board_top_alert_box_uses_soft_amber_outline_and_warn_icon_badge(self) -> None:
        html_doc = board_ui.BOARD_HTML
        self.assertNotIn("border-left: 3px solid var(--amber)", html_doc)
        alert_match = re.search(r"\.auth-alert-box\s*\{([^}]*)\}", html_doc)
        self.assertIsNotNone(alert_match)
        alert_block = alert_match.group(1)
        self.assertNotIn("border-left:", alert_block)
        self.assertIn("border: 1px solid var(--amber-border);", alert_block)
        self.assertIn("border-radius: 14px;", alert_block)

        self.assertIn("--amber-border: rgba(251, 191, 36, 0.26);", html_doc)
        self.assertIn("--amber-border: rgba(217, 119, 6, 0.28);", html_doc)
        self.assertIn(".alert-warn-ic {", html_doc)
        self.assertIn(".auth-alert-box .policy-repo-row {", html_doc)
        self.assertIn("#top-alerts-wrap {", html_doc)

        node_bin = shutil.which("node")
        if node_bin:
            script_match = re.search(r"<script>\s*([\s\S]*?)\s*</script>", html_doc)
            self.assertIsNotNone(script_match)
            js_src = script_match.group(1)
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=True) as js_tmp:
                js_tmp.write(js_src)
                js_tmp.flush()
                chk = subprocess.run([node_bin, "--check", js_tmp.name], capture_output=True, text=True, check=False)
                self.assertEqual(chk.returncode, 0, chk.stderr or chk.stdout)

            def _extract_js_fn(name: str) -> str:
                marker = f"function {name}("
                start = js_src.index(marker)
                brace_start = js_src.index("{", start)
                depth = 0
                for idx in range(brace_start, len(js_src)):
                    ch = js_src[idx]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            return js_src[start : idx + 1]
                raise AssertionError(f"Unclosed JS function: {name}")

            harness = "\n".join(
                [
                    """
                    const topWrap = { innerHTML: '' };
                    const document = { getElementById: (id) => (id === 'top-alerts-wrap' ? topWrap : null) };
                    const ICONS = {
                      github: '<gh/>',
                      gitlab: '<gl/>',
                      terminal: '<tm/>',
                      externalLink: '<ext/>',
                      compass: '<cmp/>',
                      alertTriangle: '<warn/>',
                      check: '<ok/>',
                      refresh: '<rf/>'
                    };
                    const state = {
                      lang: 'zh',
                      authSavingHost: '',
                      authErrors: {},
                      tokenDrafts: {},
                      repoInitRunning: {},
                      repoInitErrors: {},
                      repoInitBannerDismissed: false,
                      lastTopAlertsSig: ''
                    };
                    """,
                    *(
                        _extract_js_fn(fn_name)
                        for fn_name in (
                            "isEn",
                            "tr",
                            "escapeHtml",
                            "safeUrl",
                            "icon",
                            "forgeIcon",
                            "renderTopAlerts",
                        )
                    ),
                    """
                    const assert = require('assert');
                    renderTopAlerts({
                      auth_alerts: [
                        {
                          forge: 'gitlab',
                          host: 'gitlab.example.com',
                          api_base: 'https://gitlab.example.com',
                          token_url: 'https://gitlab.example.com/-/user_settings/personal_access_tokens',
                          repos: ['core-api']
                        }
                      ],
                      repos: [
                        {
                          repo_path: '/repos/core-api',
                          repo_name: 'core-api',
                          repo_url: 'https://gitlab.example.com/g/core-api',
                          forge: 'gitlab',
                          forge_connected: true,
                          repo_init: { state: 'pending', mismatches: ['merge_method=merge'] }
                        }
                      ]
                    });
                    assert.strictEqual((topWrap.innerHTML.match(/class="auth-alert-box"/g) || []).length, 2);
                    assert(topWrap.innerHTML.includes('<span class="alert-warn-ic"><svg'));
                    assert(topWrap.innerHTML.includes('<warn/>'));
                    console.log('JS_TOP_ALERT_BOX_OK');
                    """,
                ]
            )
            ui_proc = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, check=False)
            self.assertEqual(ui_proc.returncode, 0, ui_proc.stderr or ui_proc.stdout)
            self.assertIn("JS_TOP_ALERT_BOX_OK", ui_proc.stdout)

    def test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees(self) -> None:
        html_doc = board_ui.BOARD_HTML
        for removed_token in ("wt-rail-list", "sb-hdr-wts", "sb-filters", "并行目录", "view-cockpit", "workbench-grid", "console-sticky", "renderCockpitView", "sb-plat-tag"):
            self.assertNotIn(removed_token, html_doc)
        self.assertIsNone(re.search(r">\s*(?:GH|GL)\s*<", html_doc))
        for view_id in ("view-repos", "view-kanban", "view-list"):
            self.assertIn(view_id, html_doc)
        for layout_token in ("repo-section", "repo-grid", "ws-top-deck", "telemetry-strip", "bento-kpis", "bento-card", "stat-strip", "align-items: stretch;", ".workspace > #top-alerts-wrap:empty", "toggle-cleanup", "toggle-ready", "cleanup-drawer"):
            self.assertIn(layout_token, html_doc)

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to evaluate board_ui.py layout helpers")

        script_match = re.search(r"<script>\s*([\s\S]*?)\s*</script>", html_doc)
        self.assertIsNotNone(script_match)
        assert script_match is not None
        js_src = script_match.group(1)

        def _extract_js_fn(name: str) -> str:
            marker = f"function {name}("
            start = js_src.index(marker)
            brace_start = js_src.index("{", start)
            depth = 0
            for idx in range(brace_start, len(js_src)):
                ch = js_src[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return js_src[start : idx + 1]
            raise AssertionError(f"Unclosed JS function: {name}")

        fn_names = (
            "isEn",
            "tr",
            "escapeHtml",
            "safeUrl",
            "icon",
            "forgeIcon",
            "forgeLabel",
            "parseStage",
            "isItemAlert",
            "collectItems",
            "matchesFilters",
            "getProgressNumbers",
            "shortWorktreePath",
            "shortDirSlug",
            "collectRetainedWorktrees",
            "getStageQuickCli",
            "buildHandoffPrompt",
            "resolveRepoMeta",
            "renderRepoChip",
            "renderIdHtml",
            "renderChangeInline",
            "localizeAgo",
            "renderPulseSummary",
            "renderSegBar",
            "renderSidebarReposAndWorktrees",
            "renderKpis",
            "resolvePrimaryLink",
            "renderPrimaryLinkBtn",
            "cardBucket",
            "renderCard",
            "renderReposView",
            "renderInspector",
        )
        harness = "\n".join(
            [
                """
                const makeOverlayEl = () => ({
                  innerHTML: '',
                  attrs: {},
                  classes: new Set(),
                  classList: {
                    add(c) { this._p.classes.add(c); },
                    remove(c) { this._p.classes.delete(c); }
                  },
                  setAttribute(k, v) { this.attrs[k] = v; }
                });
                const overlayEl = makeOverlayEl();
                overlayEl.classList._p = overlayEl;
                const panelEl = makeOverlayEl();
                panelEl.classList._p = panelEl;
                const els = {
                  kpis: { innerHTML: '' },
                  'bento-kpis': { innerHTML: '' },
                  'repo-pills': { innerHTML: '' },
                  'sb-repo-cnt': { textContent: '' },
                  'inspector-overlay': overlayEl,
                  'inspector-panel': panelEl
                };
                const document = { getElementById: (id) => els[id] || null };
                const ICONS = {
                  github: '<gh/>', gitlab: '<gl/>', terminal: '<tm/>', externalLink: '<ext/>',
                  copy: '<cp/>', folder: '<fd/>', branch: '<br/>', trash: '<tr/>',
                  chevronRight: '<cr/>', chevronDown: '<cd/>', x: '<x/>',
                  radar: '<rd/>', gear: '<gr/>', checkCircle: '<cc/>', queue: '<qu/>', sparkle: '<sp/>', layers: '<ly/>'
                };
                const state = {
                  lang: 'zh',
                  viewMode: 'cockpit',
                  selectedRepo: 'ALL',
                  search: '',
                  worktreeOnly: false,
                  alertsOnly: false,
                  readyOnly: false,
                  todoOnly: false,
                  cleanupOnly: false,
                  cleanupDrawerOpen: false,
                  inspectedKey: null,
                  inspectorTab: 'tasks',
                  repoInitRunning: {},
                  snapshot: {
                    repos: [
                      {
                        repo_path: '/repos/demo',
                        repo_name: 'demo',
                        repo_url: 'https://github.com/o/demo',
                        forge: 'github',
                        retained_idle_worktrees: [
                          {
                            worktree: '/repos/demo-worktrees/33-ui',
                            name: '33-ui',
                            branch: 'feat/33-ui',
                            issue_number: 33,
                            last_active_ago: '2 天前',
                            last_commit_sha: '5f11a98'
                          }
                        ]
                      }
                    ],
                    issues: [
                      {
                        repo_path: '/repos/demo',
                        repo_name: 'demo',
                        repo_url: 'https://github.com/o/demo',
                        forge_type: 'github',
                        issue_number: 44,
                        title: 'fix(board): fix ci',
                        stage: '🔴 修 CI',
                        worktree: '/repos/demo-worktrees/44-fix',
                        branch: 'fix/44-fix',
                        url: 'https://github.com/o/demo/issues/44',
                        change: { number: 46, url: 'https://github.com/o/demo/pull/46', checks_overall: 'FAIL' },
                        tasks: [{ id: 'TASK-01', title: 'step1', status: 'done' }],
                        counts: { done: 1, in_progress: 0, blocked: 0, planned: 0 },
                        pulse: { dirty_count: 1, insertions: 5, deletions: 2, last_active_ago: '刚刚', changed_files: [{ code: 'M', path: 'a.py' }] }
                      },
                      {
                        repo_path: '/repos/demo',
                        repo_name: 'demo',
                        repo_url: 'https://github.com/o/demo',
                        forge_type: 'github',
                        issue_number: 41,
                        title: 'feat: ready',
                        stage: '🔵 待合入',
                        worktree: '/repos/demo-worktrees/41-ready',
                        branch: 'feat/41-ready',
                        url: 'https://github.com/o/demo/issues/41',
                        change: { number: 45, url: 'https://github.com/o/demo/pull/45', checks_overall: 'PASS' },
                        tasks: [{ id: 'TASK-01', title: 'step1', status: 'done' }],
                        counts: { done: 1, in_progress: 0, blocked: 0, planned: 0 }
                      },
                      {
                        repo_path: '/repos/demo',
                        repo_name: 'demo',
                        repo_url: 'https://github.com/o/demo',
                        forge_type: 'github',
                        issue_number: 42,
                        title: 'feat: coding',
                        stage: '🟡 开发中',
                        worktree: '/repos/demo-worktrees/42-coding',
                        branch: 'feat/42-coding',
                        url: 'https://github.com/o/demo/issues/42',
                        tasks: [{ id: 'TASK-01', title: 'step1', status: 'in_progress' }],
                        counts: { done: 0, in_progress: 1, blocked: 0, planned: 0 }
                      },
                      {
                        repo_path: '/repos/demo',
                        repo_name: 'demo',
                        repo_url: 'https://github.com/o/demo',
                        forge_type: 'github',
                        issue_number: 47,
                        title: 'feat: queued',
                        stage: '⚪ 待处理',
                        worktree: '',
                        branch: '',
                        url: 'https://github.com/o/demo/issues/47',
                        tasks: [],
                        counts: {}
                      }
                    ],
                    local_only_items: [],
                    orphan_changes: []
                  }
                };
                """,
                *(_extract_js_fn(n) for n in fn_names),
                """
                const assert = require('assert');

                // 0. Legacy viewMode 'cockpit' falls back to 'repos'
                if (!['repos', 'kanban', 'list'].includes(state.viewMode)) {
                  state.viewMode = 'repos';
                }
                assert.strictEqual(state.viewMode, 'repos');

                // 1. Retained worktree aggregated into telemetry strip & collapsed drawer by default
                const retained = collectRetainedWorktrees(state.snapshot, false);
                assert.strictEqual(retained.length, 1);
                assert.strictEqual(retained[0]._kind, 'retained');
                assert.strictEqual(retained[0].title, '33-ui');

                renderKpis(state.snapshot);
                assert(els.kpis.innerHTML.includes('data-kpi-action="toggle-cleanup"'));
                assert(els.kpis.innerHTML.includes('<span class="stat-lbl">可清理</span><span class="stat-val">1</span>'));
                assert(els.kpis.innerHTML.includes('data-kpi-action="toggle-ready"'));
                assert(els.kpis.innerHTML.includes('<span class="stat-lbl">待合入</span><span class="stat-val">1</span>'));
                assert(els['bento-kpis'].innerHTML.includes('Issue 状态'));
                assert(els['bento-kpis'].innerHTML.includes('TASK 拆分进度'));
                assert(els['bento-kpis'].innerHTML.includes('PR / MR 与合入'));
                assert(els['bento-kpis'].innerHTML.includes('bento-segs'));
                assert(els['bento-kpis'].innerHTML.includes('bento-slot'));

                renderSidebarReposAndWorktrees(state.snapshot);
                assert(!els['repo-pills'].innerHTML.includes('>GH<'));
                assert(!els['repo-pills'].innerHTML.includes('>GL<'));
                assert(!els['repo-pills'].innerHTML.includes('sb-plat-tag'));

                const items = collectItems(false);
                const htmlCollapsed = renderReposView(items, state.snapshot);
                assert(htmlCollapsed.includes('class="repo-section" data-forge="github"'));
                assert(htmlCollapsed.includes('class="repo-grid"'));
                assert(htmlCollapsed.includes('class="id-link is-pill"'));
                assert(!htmlCollapsed.includes('进入仓库主页'));
                assert(!htmlCollapsed.includes('<div class="card-meta"><a class="forge-chip'));
                assert(!htmlCollapsed.includes('<div class="card-meta"><span class="forge-chip'));
                assert(htmlCollapsed.includes('data-toggle-cleanup-drawer="1"'));
                assert(!htmlCollapsed.includes('class="cleanup-body"'));
                // Verify stage priority ordering inside repo section: #44 (修 CI) -> #42 (开发中) -> #41 (待合入) -> #47 (待处理)
                const idx44 = htmlCollapsed.indexOf('#44');
                const idx42 = htmlCollapsed.indexOf('#42');
                const idx41 = htmlCollapsed.indexOf('#41');
                const idx47 = htmlCollapsed.indexOf('#47');
                assert(idx44 !== -1 && idx44 < idx42 && idx42 < idx41 && idx41 < idx47, 'expected stage priority ordering in repo grid');

                // Ready-only chip filters down to ready items (#41)
                state.readyOnly = true;
                const readyItems = collectItems(false);
                assert.deepStrictEqual(readyItems.map((x) => x.issue_number), [41]);
                state.readyOnly = false;

                // 2. Expanding drawer reveals retained directory card with 已合入 badge and idd cleanup action
                state.cleanupDrawerOpen = true;
                const htmlExpanded = renderReposView(items, state.snapshot);
                assert(htmlExpanded.includes('class="cleanup-body"'));
                assert(htmlExpanded.includes('33-ui'));
                assert(htmlExpanded.includes('已合入'));
                assert(htmlExpanded.includes('data-copy-val="idd cleanup"'));

                // 3. cleanupOnly mode filters to cleanable worktrees and shows per-repo idd cleanup button & prompt
                state.cleanupOnly = true;
                const htmlCleanupOnly = renderReposView(retained, state.snapshot);
                assert(htmlCleanupOnly.includes('cd /repos/demo &amp;&amp; idd cleanup'));
                assert(htmlCleanupOnly.includes('33-ui'));
                assert(buildHandoffPrompt(retained[0]).includes('idd cleanup'));

                // 4. Smart stage quick CLI commands across all 5 stages & inspector drawer integration
                const byNum = new Map(items.map((x) => [x.issue_number, x]));
                assert.strictEqual(getStageQuickCli(byNum.get(47)).cmd, 'cd /repos/demo && idd start 47');
                assert.strictEqual(getStageQuickCli(byNum.get(44)).cmd, 'cd /repos/demo-worktrees/44-fix && idd ci 44 --logs');
                assert.strictEqual(getStageQuickCli(byNum.get(41)).cmd, 'cd /repos/demo-worktrees/41-ready && idd land 41');
                assert.strictEqual(getStageQuickCli(byNum.get(42)).cmd, 'cd /repos/demo-worktrees/42-coding && idd sync 42');
                assert.strictEqual(getStageQuickCli(retained[0]).cmd, 'cd /repos/demo && idd cleanup');

                const inspectorExpectations = [
                  [byNum.get(47)._key, 'cd /repos/demo &amp;&amp; idd start 47'],
                  [byNum.get(44)._key, 'cd /repos/demo-worktrees/44-fix &amp;&amp; idd ci 44 --logs'],
                  [byNum.get(41)._key, 'cd /repos/demo-worktrees/41-ready &amp;&amp; idd land 41'],
                  [byNum.get(42)._key, 'cd /repos/demo-worktrees/42-coding &amp;&amp; idd sync 42'],
                  [retained[0]._key, 'cd /repos/demo &amp;&amp; idd cleanup']
                ];
                for (const [k, expectedCmd] of inspectorExpectations) {
                  state.inspectedKey = k;
                  renderInspector();
                  assert(panelEl.classes.has('open'), 'inspector panel should open for ' + k);
                  assert(panelEl.innerHTML.includes(expectedCmd), 'inspector should include ' + expectedCmd);
                }

                console.log('JS_REDESIGNED_LAYOUT_OK');
                """,
            ]
        )
        proc = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("JS_REDESIGNED_LAYOUT_OK", proc.stdout)

    def test_status_row_stage_and_stale_badge_matrix(self) -> None:
        base_kwargs = {
            "issue_number": 44,
            "title": "docs(readme): rewrite",
            "url": "https://github.com/acme/idd/issues/44",
            "mr_label": "PR",
            "mr_prefix": "#",
            "repo_name": "idd",
            "repo_path": "/repos/idd",
            "repo_url": "https://github.com/acme/idd",
            "forge_type": "github",
            "forge_connected": True,
        }

        def _make_item(counts: dict[str, int], *, total: int | None = None, done: int | None = None, pulse: dict | None = None) -> dict:
            full_counts = {s: 0 for s in monitor.task_status.STATUSES}
            full_counts.update(counts)
            t_total = total if total is not None else sum(full_counts.values())
            t_done = done if done is not None else full_counts["done"]
            return {
                "issue": "44-readme",
                "worktree": "/repos/idd-worktrees/44-readme",
                "branch": "docs/44-readme",
                "total": t_total,
                "done": t_done,
                "counts": full_counts,
                "tasks": [],
                "pulse": pulse or {"dirty_count": 0, "unpushed_commits": 0, "git_op": ""},
            }

        pr_pass = {"number": 46, "checks_overall": "PASS", "isDraft": False, "url": "https://github.com/acme/idd/pull/46"}
        pr_fail = {"number": 46, "checks_overall": "FAIL", "isDraft": False, "url": "https://github.com/acme/idd/pull/46"}
        pr_none = {"number": 46, "checks_overall": "NONE", "isDraft": False, "url": "https://github.com/acme/idd/pull/46"}

        # 1. PR PASS + TASK-01 done + TASK-02 in_progress + dirty & unpushed -> developing + stale badge
        row1 = monitor._build_status_row(
            item=_make_item({"done": 1, "in_progress": 1}, pulse={"dirty_count": 11, "unpushed_commits": 3, "git_op": ""}),
            change=pr_pass,
            **base_kwargs,
        )
        self.assertEqual(row1["stage"], "🟡 开发中")
        self.assertTrue(row1["change_stale"])
        self.assertIn("CI 全绿 (待同步)", row1["change_summary"])

        # 2. PR PASS + unfinished TASK + clean & synced -> developing, not stale
        row2 = monitor._build_status_row(
            item=_make_item({"done": 1, "in_progress": 1}),
            change=pr_pass,
            **base_kwargs,
        )
        self.assertEqual(row2["stage"], "🟡 开发中")
        self.assertFalse(row2["change_stale"])
        self.assertIn("✅ CI 全绿", row2["change_summary"])

        # 3. PR PASS + all tasks done (1/1) + dirty / unpushed / git_op -> developing + stale
        for pulse_case in (
            {"dirty_count": 1, "unpushed_commits": 0, "git_op": ""},
            {"dirty_count": 0, "unpushed_commits": 2, "git_op": ""},
            {"dirty_count": 0, "unpushed_commits": 0, "git_op": "rebasing"},
        ):
            row_u = monitor._build_status_row(
                item=_make_item({"done": 1}, pulse=pulse_case),
                change=pr_pass,
                **base_kwargs,
            )
            self.assertEqual(row_u["stage"], "🟡 开发中", pulse_case)
            self.assertTrue(row_u["change_stale"], pulse_case)
            self.assertIn("待同步", row_u["change_summary"], pulse_case)

        # 4. PR PASS + blocked=1 -> 受阻
        row_blk = monitor._build_status_row(
            item=_make_item({"done": 1, "blocked": 1}),
            change=pr_pass,
            **base_kwargs,
        )
        self.assertEqual(row_blk["stage"], "⛔ 受阻")

        # 5. PR FAIL + in_progress=1 + dirty=1 -> 修 CI still wins
        row_fail = monitor._build_status_row(
            item=_make_item({"done": 1, "in_progress": 1}, pulse={"dirty_count": 2, "unpushed_commits": 0, "git_op": ""}),
            change=pr_fail,
            **base_kwargs,
        )
        self.assertEqual(row_fail["stage"], "🛠️ 修 CI")
        self.assertTrue(row_fail["change_stale"])
        self.assertIn("CI 失败 (待同步)", row_fail["change_summary"])

        # 6. PR PASS + done + cancelled + clean & synced -> 待合入
        row_can = monitor._build_status_row(
            item=_make_item({"done": 1, "cancelled": 1}),
            change=pr_pass,
            **base_kwargs,
        )
        self.assertEqual(row_can["stage"], "🔵 待合入")
        self.assertFalse(row_can["change_stale"])

        # 7. PR PASS + total=0 (TASK cleaned before land) + clean & synced -> 待合入
        row_empty_tasks = monitor._build_status_row(
            item=_make_item({}, total=0, done=0),
            change=pr_pass,
            **base_kwargs,
        )
        self.assertEqual(row_empty_tasks["stage"], "🔵 待合入")
        self.assertFalse(row_empty_tasks["change_stale"])

        # 8. PR PASS + item=None (no local worktree) -> 待合入
        row_no_item = monitor._build_status_row(item=None, change=pr_pass, **base_kwargs)
        self.assertEqual(row_no_item["stage"], "🔵 待合入")
        self.assertFalse(row_no_item["change_stale"])

        # 9. PR NONE + stale -> format_change_badge indicates 待同步
        row_none_stale = monitor._build_status_row(
            item=_make_item({"done": 1}, pulse={"dirty_count": 1, "unpushed_commits": 0, "git_op": ""}),
            change=pr_none,
            **base_kwargs,
        )
        self.assertEqual(row_none_stale["stage"], "🟡 开发中")
        self.assertIn("无 CI (待同步)", row_none_stale["change_summary"])

        # 10. No PR + done=1 + dirty=1 -> 开发中; clean + unpushed=1 -> 待提 PR
        row_no_pr_dirty = monitor._build_status_row(
            item=_make_item({"done": 1}, pulse={"dirty_count": 1, "unpushed_commits": 0, "git_op": ""}),
            change=None,
            **base_kwargs,
        )
        self.assertEqual(row_no_pr_dirty["stage"], "🟡 开发中")

        row_no_pr_unpushed = monitor._build_status_row(
            item=_make_item({"done": 1}, pulse={"dirty_count": 0, "unpushed_commits": 1, "git_op": ""}),
            change=None,
            **base_kwargs,
        )
        self.assertEqual(row_no_pr_unpushed["stage"], "🟢 待提 PR")

    def test_board_ui_stale_badge_and_handoff_js(self) -> None:
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node binary not available for board_ui JS verification")

        html = board_ui.BOARD_HTML
        script_match = re.search(r"<script>\s*([\s\S]*?)\s*</script>", html)
        self.assertIsNotNone(script_match)
        assert script_match is not None
        js_src = script_match.group(1)

        def _extract_js_fn(name: str) -> str:
            marker = f"function {name}("
            start = js_src.index(marker)
            brace_start = js_src.index("{", start)
            depth = 0
            for idx in range(brace_start, len(js_src)):
                ch = js_src[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return js_src[start : idx + 1]
            raise AssertionError(f"Unclosed JS function: {name}")

        harness = "\n".join(
            [
                """
                const state = { lang: 'zh' };
                """,
                *(
                    _extract_js_fn(fn_name)
                    for fn_name in (
                        "isEn",
                        "tr",
                        "escapeHtml",
                        "safeUrl",
                        "parseStage",
                        "getProgressNumbers",
                        "renderChangeInline",
                        "buildHandoffPrompt",
                    )
                ),
                """
                const assert = require('assert');
                const stalePassItem = {
                  _kind: 'issue',
                  issue_number: 44,
                  title: 'rewrite README',
                  stage: '🟡 开发中',
                  worktree: '/wt/44',
                  branch: 'docs/44-readme',
                  done: 1,
                  total: 2,
                  current_task: 'TASK-02',
                  change_stale: true,
                  pulse: { dirty_count: 0, unpushed_commits: 3, git_op: '' },
                  change: { number: 46, checks_overall: 'PASS', url: 'https://github.com/acme/idd/pull/46' }
                };
                const zhStale = renderChangeInline(stalePassItem);
                assert(zhStale.includes('tone-warning'), zhStale);
                assert(zhStale.includes('CI 全绿（待同步）'), zhStale);

                const handoff = buildHandoffPrompt(stalePassItem);
                assert(!handoff.includes('idd land'), handoff);
                assert(handoff.includes('TASK-02'), handoff);

                const cleanPass = renderChangeInline({
                  forge_type: 'github',
                  change_stale: false,
                  pulse: { dirty_count: 0, unpushed_commits: 0, git_op: '' },
                  change: { number: 46, checks_overall: 'PASS', url: 'https://github.com/acme/idd/pull/46' }
                });
                assert(cleanPass.includes('tone-success'), cleanPass);
                assert(cleanPass.includes('CI 全绿'), cleanPass);
                assert(!cleanPass.includes('待同步'), cleanPass);

                const failStale = renderChangeInline({
                  forge_type: 'github',
                  change_stale: true,
                  pulse: { dirty_count: 1, unpushed_commits: 0, git_op: '' },
                  change: { number: 46, checks_overall: 'FAIL', url: 'https://github.com/acme/idd/pull/46' }
                });
                assert(failStale.includes('tone-danger'), failStale);

                state.lang = 'en';
                const enStalePass = renderChangeInline({
                  forge_type: 'github',
                  pulse: { dirty_count: 0, unpushed_commits: 2, git_op: '' },
                  change: { number: 46, checks_overall: 'PASS', url: 'https://github.com/acme/idd/pull/46' }
                });
                assert(enStalePass.includes('tone-warning'), enStalePass);
                assert(enStalePass.includes('CI PASS (stale)'), enStalePass);

                const enStaleNone = renderChangeInline({
                  forge_type: 'github',
                  change_stale: true,
                  change: { number: 46, checks_overall: 'NONE', url: 'https://github.com/acme/idd/pull/46' }
                });
                assert(enStaleNone.includes('tone-warning'), enStaleNone);
                assert(enStaleNone.includes('Out of sync'), enStaleNone);

                console.log('JS_STALE_BADGE_AND_HANDOFF_OK');
                """,
            ]
        )
        proc = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("JS_STALE_BADGE_AND_HANDOFF_OK", proc.stdout)

    def test_e2e_appended_task_after_green_pr_returns_to_developing_and_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            repo, _, _, env = _create_repo_harness(root / "h", "demo-app", cfg)

            wt = Path(json.loads(self._run(env, repo, "start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            tdir = wt / "TASK/42-export-csv"
            tdir.mkdir(parents=True)
            (tdir / "TASK-01-impl.md").write_text(
                "# TASK-01：实现导出\n\n- Issue: #42\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                encoding="utf-8",
            )
            (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(wt), "commit", "-m", "feat: 实现导出\n\nTask: 42-export-csv/TASK-01\nRefs: #42\nTest: pytest — 1 passed"],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "-C", str(wt), "push", "-u", "origin", "HEAD"], check=True, capture_output=True)
            self._run(env, repo, "pr", "42")

            snap_ready = json.loads(self._run(env, repo, "status", "-g", "--json").stdout)
            row_ready = next(r for r in snap_ready["issues"] if r["issue_number"] == 42)
            self.assertEqual(row_ready["stage"], "🔵 待合入")
            self.assertFalse(row_ready["change_stale"])
            self.assertEqual(snap_ready["summary"]["ready_to_land_count"], 1)

            # Append TASK-02 in_progress and make local dirty edits without pushing
            (tdir / "TASK-02-docs.md").write_text(
                "# TASK-02：补充截图\n\n- Issue: #42\n- Status: in_progress\n- Depends on: TASK-01\n- Test: pytest\n",
                encoding="utf-8",
            )
            (wt / "export.py").write_text("ok = True\nv = 2\n", encoding="utf-8")

            snap_dev = json.loads(self._run(env, repo, "status", "-g", "--json").stdout)
            row_dev = next(r for r in snap_dev["issues"] if r["issue_number"] == 42)
            self.assertEqual(row_dev["stage"], "🟡 开发中")
            self.assertTrue(row_dev["change_stale"])
            self.assertIn("待同步", row_dev["change_summary"])
            self.assertEqual(snap_dev["summary"]["ready_to_land_count"], 0)

            term_out = self._run(env, repo, "status").stdout
            self.assertIn("待同步", term_out)
            self.assertIn("开发中", term_out)

    def test_board_motion_tokens_reduced_motion_and_tty_watch_frame(self) -> None:
        html_doc = board_ui.BOARD_HTML
        for token in (
            "--ease-out:",
            "--ease-spring:",
            "--ease-pop:",
            "--ease-in:",
            "--dur-press:",
            "--dur-fast:",
            "--dur-panel:",
            "--focus-ring:",
            "prefers-reduced-motion: reduce",
            ".btn:disabled",
            "reconcileMainContent",
            "syncSegmentedIndicator",
            "max-width: 560px",
            "已完成",
            "进行中",
            "待执行",
        ):
            self.assertIn(token, html_doc)
        self.assertNotIn("transition: all", html_doc)
        # Verify spin class on busy save/apply buttons
        self.assertIn('(saving ? " spin" : "")', html_doc)
        self.assertIn('(busy ? " spin" : "")', html_doc)
        self.assertIn('(activeBusy ? " spin" : "")', html_doc)
        # Verify TTY watch formatter avoids full-screen clear and uses synchronized output
        tty_out = monitor._format_tty_watch_frame("line1\nline2")
        self.assertNotIn("\x1b[2J", tty_out)
        self.assertTrue(tty_out.startswith("\x1b[?2026h\x1b[H"))
        self.assertIn("\x1b[K\n", tty_out)
        self.assertTrue(tty_out.endswith("\x1b[K\x1b[J\x1b[?2026l"))

    def test_board_collapsed_sidebar_and_header_pill_layout_css(self) -> None:
        html_doc = board_ui.BOARD_HTML
        collapsed_brand_match = re.search(
            r"body\.sidebar-collapsed \.sb-brand\s*\{([^}]*)\}",
            html_doc,
        )
        self.assertIsNotNone(collapsed_brand_match)
        assert collapsed_brand_match is not None
        collapsed_brand_css = collapsed_brand_match.group(1)
        self.assertIn("flex-direction: column;", collapsed_brand_css)
        self.assertIn("gap: 6px;", collapsed_brand_css)

        self.assertIn(
            "@media (max-width: 780px)",
            html_doc,
        )
        self.assertIn(
            "body.sidebar-collapsed .sb-brand { flex-direction: row; justify-content: space-between; padding: 2px 4px 8px; }",
            html_doc,
        )

        icon_btn_match = re.search(r"\.icon-btn\s*\{([^}]*)\}", html_doc)
        self.assertIsNotNone(icon_btn_match)
        assert icon_btn_match is not None
        self.assertIn("flex-shrink: 0;", icon_btn_match.group(1))

        wrap_match = re.search(r"#ws-repo-link-wrap\s*\{([^}]*)\}", html_doc)
        self.assertIsNotNone(wrap_match)
        assert wrap_match is not None
        wrap_css = wrap_match.group(1)
        self.assertIn("display: inline-flex;", wrap_css)
        self.assertIn("gap: 8px;", wrap_css)
        self.assertIn("#ws-repo-link-wrap:empty {\n      display: none;\n    }", html_doc)

        pill_override_match = re.search(
            r"#ws-repo-link-wrap \.forge-chip,\s*#ws-repo-link-wrap \.btn-xs\s*\{([^}]*)\}",
            html_doc,
        )
        self.assertIsNotNone(pill_override_match)
        assert pill_override_match is not None
        pill_override_css = pill_override_match.group(1)
        self.assertIn("height: 26px;", pill_override_css)
        self.assertIn("border-radius: 999px;", pill_override_css)

        am_pill_match = re.search(r"\.am-header-pill\s*\{([^}]*)\}", html_doc)
        self.assertIsNotNone(am_pill_match)
        assert am_pill_match is not None
        self.assertIn("white-space: nowrap;", am_pill_match.group(1))


if __name__ == "__main__":
    unittest.main()
