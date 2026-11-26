"""End-to-end unit tests for the `idd` CLI using real temporary git repos + a stateful fake `gh`."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import idd_cli  # noqa: E402
from version import parse_skill_version  # noqa: E402


IDD_BIN = SCRIPTS_DIR / "idd"
IDD_CLI = SCRIPTS_DIR / "idd_cli.py"


FAKE_GH_SCRIPT = r"""#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STATE_FILE = Path(os.environ["FAKE_GH_STATE"])
ORIGIN_DIR = Path(os.environ["FAKE_GH_ORIGIN"])


def load_state():
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def arg_val(args, flag):
    if flag in args:
        idx = args.index(flag)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None


def arg_vals(args, flag):
    vals = []
    for idx, tok in enumerate(args):
        if tok == flag and idx + 1 < len(args):
            vals.append(args[idx + 1])
    return vals


def origin_head_oid(branch):
    if not branch:
        return ""
    proc = subprocess.run(
        ["git", "--git-dir", str(ORIGIN_DIR), "rev-parse", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


args = sys.argv[1:]
state = load_state()
state.setdefault("calls", []).append(args)

if args[:2] == ["issue", "create"]:
    num = state.setdefault("next_issue", 50)
    state["next_issue"] = num + 1
    title = arg_val(args, "--title") or f"Issue {num}"
    body = arg_val(args, "--body") or ""
    body_file = arg_val(args, "--body-file")
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    labels = [{"name": l} for l in arg_vals(args, "--label")]
    url = f"https://github.com/acme/demo/issues/{num}"
    state["issues"][str(num)] = {
        "number": num,
        "title": title,
        "body": body,
        "labels": labels,
        "state": "OPEN",
        "url": url,
    }
    save_state(state)
    print(url)
    sys.exit(0)

if args[:2] == ["issue", "view"]:
    num = args[2]
    issue = state["issues"].get(str(num))
    if not issue:
        print(f"issue {num} not found", file=sys.stderr)
        sys.exit(1)
    save_state(state)
    print(json.dumps(issue))
    sys.exit(0)

if args[:2] == ["issue", "list"]:
    req_state = (arg_val(args, "--state") or "open").upper()
    items = [
        v for v in state["issues"].values()
        if req_state == "ALL" or v.get("state", "OPEN").upper() == req_state
    ]
    items.sort(key=lambda x: x["number"])
    save_state(state)
    print(json.dumps(items))
    sys.exit(0)

if args[:2] == ["issue", "edit"]:
    num = args[2]
    if state.get("fail_issue_edit"):
        print("injected issue edit failure", file=sys.stderr)
        sys.exit(1)
    issue = state["issues"][str(num)]
    bf = arg_val(args, "--body-file")
    if bf:
        issue["body"] = Path(bf).read_text(encoding="utf-8")
    save_state(state)
    print(issue["url"])
    sys.exit(0)

if args[:2] == ["pr", "list"]:
    head = arg_val(args, "--head")
    req_state = (arg_val(args, "--state") or "open").upper()
    items = [
        pr for pr in state["prs"].values()
        if (req_state == "ALL" or pr.get("state", "OPEN").upper() == req_state)
        and (not head or pr.get("headRefName") == head)
    ]
    items.sort(key=lambda x: x["number"])
    save_state(state)
    print(json.dumps(items))
    sys.exit(0)

if args[:2] == ["pr", "create"]:
    num = state.setdefault("next_pr", 10)
    state["next_pr"] = num + 1
    title = arg_val(args, "--title") or f"PR {num}"
    body = Path(arg_val(args, "--body-file")).read_text(encoding="utf-8") if arg_val(args, "--body-file") else ""
    base = arg_val(args, "--base") or "main"
    head = arg_val(args, "--head") or ""
    url = f"https://github.com/acme/demo/pull/{num}"
    state["prs"][str(num)] = {
        "number": num,
        "title": title,
        "body": body,
        "baseRefName": base,
        "headRefName": head,
        "headRefOid": origin_head_oid(head),
        "state": "OPEN",
        "isDraft": "--draft" in args,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": state.get("default_checks", []),
        "url": url,
    }
    save_state(state)
    print(url)
    sys.exit(0)

if args[:2] == ["pr", "edit"]:
    num = args[2]
    pr = state["prs"][str(num)]
    if arg_val(args, "--title"):
        pr["title"] = arg_val(args, "--title")
    if arg_val(args, "--body-file"):
        pr["body"] = Path(arg_val(args, "--body-file")).read_text(encoding="utf-8")
    oid = origin_head_oid(pr.get("headRefName", ""))
    if oid:
        pr["headRefOid"] = oid
    save_state(state)
    print(pr["url"])
    sys.exit(0)

if args[:2] == ["pr", "view"]:
    ref = args[2] if len(args) > 2 and not args[2].startswith("-") else None
    pr = state["prs"].get(str(ref)) if ref else None
    if not pr and not ref:
        br = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
        for item in state["prs"].values():
            if item.get("headRefName") == br:
                pr = item
                break
    if not pr:
        print(f"pr {ref} not found", file=sys.stderr)
        sys.exit(1)
    if state.get("stale_pr_view_polls", 0) > 0:
        state["stale_pr_view_polls"] -= 1
    else:
        oid = origin_head_oid(pr.get("headRefName", ""))
        if oid:
            pr["headRefOid"] = oid
    save_state(state)
    print(json.dumps(pr))
    sys.exit(0)

if args[:2] == ["pr", "merge"]:
    num = args[2]
    pr = state["prs"][str(num)]
    subject = arg_val(args, "--subject") or pr["title"]
    body = Path(arg_val(args, "--body-file")).read_text(encoding="utf-8") if arg_val(args, "--body-file") else pr["body"]
    expected_commit = arg_val(args, "--match-head-commit")
    head = pr["headRefName"]
    oid = origin_head_oid(head)
    if expected_commit and oid and expected_commit != oid:
        print(f"Head commit {expected_commit} does not match {oid}", file=sys.stderr)
        sys.exit(1)
    if "--auto" in args:
        pr["autoMergeRequest"] = True
        save_state(state)
        print("auto-merge enabled")
        sys.exit(0)

    base = pr["baseRefName"]
    if oid:
        pr["headRefOid"] = oid
    tree = subprocess.check_output(["git", "--git-dir", str(ORIGIN_DIR), "rev-parse", f"refs/heads/{head}^{{tree}}"], text=True).strip()
    parent = subprocess.check_output(["git", "--git-dir", str(ORIGIN_DIR), "rev-parse", f"refs/heads/{base}"], text=True).strip()
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "GitHub")
    env.setdefault("GIT_AUTHOR_EMAIL", "noreply@github.com")
    env.setdefault("GIT_COMMITTER_NAME", "GitHub")
    env.setdefault("GIT_COMMITTER_EMAIL", "noreply@github.com")
    msg = f"{subject}\n\n{body}"
    squash_sha = subprocess.check_output(
        ["git", "--git-dir", str(ORIGIN_DIR), "commit-tree", tree, "-p", parent, "-m", msg],
        text=True,
        env=env,
    ).strip()
    subprocess.check_call(["git", "--git-dir", str(ORIGIN_DIR), "update-ref", f"refs/heads/{base}", squash_sha])
    if "--delete-branch" in args:
        subprocess.run(["git", "--git-dir", str(ORIGIN_DIR), "update-ref", "-d", f"refs/heads/{head}"], check=False)
    pr["state"] = "MERGED"
    pr["mergedSquashSha"] = squash_sha
    for m in re.finditer(r"Closes\s+#(\d+)", body):
        if m.group(1) in state["issues"]:
            state["issues"][m.group(1)]["state"] = "CLOSED"
    save_state(state)
    print(f"Merged {pr['url']}")
    sys.exit(0)

if args[:2] == ["run", "view"]:
    run_id = args[2]
    print(state.get("run_logs", {}).get(str(run_id), ""))
    save_state(state)
    sys.exit(0)

if args[:1] == ["api"]:
    if "PATCH" in args:
        state["repo_settings"].update({
            "allow_merge_commit": False,
            "allow_squash_merge": True,
            "delete_branch_on_merge": False,
        })
    save_state(state)
    print(json.dumps(state["repo_settings"]))
    sys.exit(0)

print(f"Unhandled fake gh args: {args}", file=sys.stderr)
sys.exit(1)
"""


class GitHubHarness:
    """Manage a real bare remote + local repo + fake `gh` shim inside a temporary directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.repo = root / "demo"
        self.bin_dir = root / "bin"
        self.state_file = root / "gh_state.json"

        self.bin_dir.mkdir(parents=True)
        self.gh_bin = self.bin_dir / "gh"
        self.gh_bin.write_text(FAKE_GH_SCRIPT, encoding="utf-8")
        self.gh_bin.chmod(self.gh_bin.stat().st_mode | stat.S_IXUSR)

        self.state = {
            "next_issue": 50,
            "next_pr": 10,
            "issues": {
                "42": {
                    "number": 42,
                    "title": "Export CSV report",
                    "body": "Need CSV export on dashboard.\n\n- [ ] Support UTF-8 BOM",
                    "labels": [{"name": "enhancement"}],
                    "state": "OPEN",
                    "url": "https://github.com/acme/demo/issues/42",
                },
                "43": {
                    "number": 43,
                    "title": "Fix dark mode flicker",
                    "body": "Flash on initial load.",
                    "labels": [{"name": "bug"}],
                    "state": "OPEN",
                    "url": "https://github.com/acme/demo/issues/43",
                },
            },
            "prs": {},
            "run_logs": {},
            "default_checks": [{"name": "ci / test", "status": "COMPLETED", "conclusion": "SUCCESS"}],
            "repo_settings": {
                "full_name": "acme/demo",
                "allow_merge_commit": True,
                "allow_squash_merge": True,
                "allow_rebase_merge": True,
                "delete_branch_on_merge": False,
                "allow_auto_merge": True,
            },
            "calls": [],
        }
        self.save_state()

        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(self.origin), str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Tester"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.com"], check=True)

        (self.repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".env\nconfig/local/\n", encoding="utf-8")
        (self.repo / ".worktreeinclude").write_text("# local secrets\n.env\nconfig/local/*.json\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "README.md", ".gitignore", ".worktreeinclude"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-m", "chore: initial commit"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "--git-dir", str(self.origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "set-head", "origin", "main"], check=True)

        # Untracked gitignored files that should be copied via .worktreeinclude
        (self.repo / ".env").write_text("API_KEY=local-test\n", encoding="utf-8")
        (self.repo / "config/local").mkdir(parents=True)
        (self.repo / "config/local/dev.json").write_text('{"debug": true}\n', encoding="utf-8")

    def save_state(self) -> None:
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_state(self) -> dict:
        self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
        return self.state

    def run_idd(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_GH_STATE"] = str(self.state_file)
        env["FAKE_GH_ORIGIN"] = str(self.origin)
        env["IDD_NO_AUTO_UPDATE"] = "1"
        env["IDD_CONFIG_DIR"] = str(self.root / "idd-config")
        env.pop("IDD_WORKTREE_ROOT", None)
        return subprocess.run(
            [sys.executable, str(IDD_BIN), *args],
            cwd=str(cwd or self.repo),
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )


class TestIddCli(unittest.TestCase):
    def _write_task(self, wt: Path, issue_dir: str, num: int, title: str, status: str, issue: str = "#42") -> Path:
        task_dir = wt / "TASK" / issue_dir
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / f"TASK-{num:02d}-step.md"
        path.write_text(
            f"# TASK-{num:02d}：{title}\n\n"
            f"- Issue: {issue}\n"
            f"- Status: {status}\n"
            f"- Depends on: none\n"
            f"- Test: pytest tests/test_export.py\n\n"
            f"## 验证方式\n- Command: pytest tests/test_export.py\n- Expected: passed\n\n"
            f"## 执行结果\n- Outcome: {'passed' if status == 'done' else 'pending'}\n",
            encoding="utf-8",
        )
        return path

    def test_start_creates_worktree_syncs_includes_and_is_idempotent_across_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            first = json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)
            wt_path = Path(first["worktree"])
            self.assertFalse(first["reused"])
            self.assertEqual(first["branch"], "feat/42-export-csv")
            self.assertEqual(wt_path, (h.root / "demo-worktrees/42-export-csv").resolve())
            self.assertEqual((wt_path / ".env").read_text(encoding="utf-8"), "API_KEY=local-test\n")
            self.assertEqual((wt_path / "config/local/dev.json").read_text(encoding="utf-8"), '{"debug": true}\n')

            # Second call (e.g., from a different tool inside another worktree) must reuse wt_path cleanly
            other = json.loads(h.run_idd("start", "43", "--json").stdout)
            other_wt = Path(other["worktree"])
            self.assertEqual(other["branch"], "fix/43-fix-dark-mode-flicker")

            reused = json.loads(h.run_idd("start", "42", "--json", cwd=other_wt).stdout)
            self.assertTrue(reused["reused"])
            self.assertEqual(Path(reused["worktree"]), wt_path)
            self.assertFalse((wt_path.parent / "42-export-csv-worktrees").exists())

    def test_offline_slug_start_works_without_gh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "localrepo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            (repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

            env = dict(os.environ)
            env["IDD_CONFIG_DIR"] = str(tmp_path / "idd-config")
            env["IDD_NO_AUTO_UPDATE"] = "1"
            res = subprocess.run(
                [sys.executable, str(IDD_BIN), "start", "local-refactor", "--json"],
                cwd=str(repo),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(res.stdout)
            self.assertEqual(data["branch"], "feat/local-refactor")
            self.assertEqual(Path(data["worktree"]), (tmp_path / "localrepo-worktrees/local-refactor").resolve())

    def test_sync_updates_issue_progress_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            self._write_task(wt, "42-export-csv", 1, "定义 CSV 接口", "done")
            self._write_task(wt, "42-export-csv", 2, "前端下载按钮", "in_progress")

            h.run_idd("sync", "42")
            body1 = h.load_state()["issues"]["42"]["body"]
            self.assertIn("Need CSV export on dashboard.", body1)
            self.assertEqual(body1.count("<!-- idd:progress:start -->"), 1)
            self.assertIn("- [x] TASK-01：定义 CSV 接口", body1)
            self.assertIn("- [ ] TASK-02：前端下载按钮 *(in_progress)*", body1)

            # Update TASK-02 -> done and sync again from inside worktree without issue arg
            self._write_task(wt, "42-export-csv", 2, "前端下载按钮", "done")
            h.run_idd("sync", cwd=wt)
            body2 = h.load_state()["issues"]["42"]["body"]
            self.assertEqual(body2.count("<!-- idd:progress:start -->"), 1)
            self.assertIn("- [x] TASK-02：前端下载按钮", body2)
            self.assertNotIn("*(in_progress)*", body2)

    def test_pr_ci_and_land_full_linear_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            # Commit TASK-01 and TASK-02
            self._write_task(wt, "42-export-csv", 1, "增加 CSV 后端导出接口", "done")
            (wt / "export.py").write_text("def export(): return 'a,b\\n'\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(wt), "commit", "-m",
                    "feat: 增加 CSV 后端导出接口\n\nTask: 42-export-csv/TASK-01\nRefs: #42\nTest: pytest tests/test_export.py — 3 passed",
                ],
                check=True,
                capture_output=True,
            )

            self._write_task(wt, "42-export-csv", 2, "补齐编码与边界测试", "done")
            (wt / "test_export.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(wt), "commit", "-m",
                    "test: 补齐编码与边界测试\n\nTask: 42-export-csv/TASK-02\nRefs: #42\nTest: pytest tests/test_export.py — 5 passed",
                ],
                check=True,
                capture_output=True,
            )

            # Dry-run PR
            dry_pr = h.run_idd("pr", "42", "--dry-run").stdout
            self.assertNotIn("Goal:", dry_pr)
            self.assertIn("Closes #42", dry_pr)
            self.assertIn("TASK-01 增加 CSV 后端导出接口", dry_pr)
            self.assertIn("Test: pytest tests/test_export.py — 5 passed", dry_pr)

            # Real PR creation
            pr_out = h.run_idd("pr", "42").stdout
            self.assertIn("已创建 PR", pr_out)

            # Test CI failure log diagnosis
            state = h.load_state()
            pr_num = str(next(iter(state["prs"].keys())))
            state["prs"][pr_num]["statusCheckRollup"] = [
                {
                    "name": "ci / lint",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://github.com/acme/demo/actions/runs/998877/jobs/1",
                }
            ]
            state["run_logs"]["998877"] = "ERR: unused import in export.py:1"
            h.save_state()

            ci_out = h.run_idd("ci", "42").stdout
            self.assertIn("[FAIL] ci / lint", ci_out)
            self.assertIn("unused import in export.py:1", ci_out)

            # Status board check while CI fails
            status_json = json.loads(h.run_idd("status", "--json").stdout)
            by_num = {row["issue_number"]: row for row in status_json["issues"]}
            self.assertEqual(by_num[42]["stage"], "🛠️ 修 CI")
            self.assertEqual(by_num[42]["task_progress"], "2 / 2")
            self.assertEqual(by_num[43]["stage"], "⚪ 待认领")

            # Mark CI green, advance origin/main to exercise auto-rebase, and test evidence guard
            state["prs"][pr_num]["statusCheckRollup"] = [
                {"name": "ci / lint", "status": "COMPLETED", "conclusion": "SUCCESS"}
            ]
            h.save_state()

            # Advance origin/main via a temporary helper clone
            helper_clone = h.root / "helper-main"
            subprocess.run(["git", "clone", str(h.origin), str(helper_clone)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(helper_clone), "checkout", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(helper_clone), "config", "user.name", "Other"], check=True)
            subprocess.run(["git", "-C", str(helper_clone), "config", "user.email", "other@example.com"], check=True)
            (helper_clone / "CHANGELOG.md").write_text("unrelated change\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(helper_clone), "add", "CHANGELOG.md"], check=True)
            subprocess.run(["git", "-C", str(helper_clone), "commit", "-m", "docs: unrelated main update"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(helper_clone), "push", "origin", "main"], check=True, capture_output=True)

            # Add evidence file and commit so clean guard triggers
            ev_file = wt / "TASK/42-export-csv/evidence/TASK-01/sample.txt"
            ev_file.parent.mkdir(parents=True)
            ev_file.write_text("sanitized evidence\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "docs: add evidence"], check=True, capture_output=True)

            blocked_land = h.run_idd("land", "42", "--dry-run", check=False)
            self.assertEqual(blocked_land.returncode, 2)
            self.assertIn("evidence", blocked_land.stderr)

            # Now land with --force-clean-evidence (default retains branch + worktree)
            land_res = h.run_idd("land", "42", "--force-clean-evidence")
            self.assertIn("Squash Merge 直线合入", land_res.stdout)
            self.assertIn("已保留本地与远端分支：feat/42-export-csv", land_res.stdout)
            self.assertTrue(wt.exists(), "Worktree should be retained by default after land")
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(h.repo), "show-ref", "--verify", "--quiet", "refs/heads/feat/42-export-csv"]
                ).returncode,
                0,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "--git-dir", str(h.origin), "show-ref", "--verify", "--quiet", "refs/heads/feat/42-export-csv"]
                ).returncode,
                0,
            )

            # Verify local main fast-forwarded, linear (0 merge commits), TASK/42-export-csv removed, code present
            merge_count = subprocess.check_output(
                ["git", "-C", str(h.repo), "rev-list", "--merges", "--count", "main"],
                text=True,
            ).strip()
            self.assertEqual(merge_count, "0")
            self.assertTrue((h.repo / "export.py").is_file())
            self.assertTrue((h.repo / "CHANGELOG.md").is_file())
            self.assertFalse((h.repo / "TASK/42-export-csv").exists())

            final_state = h.load_state()
            self.assertEqual(final_state["prs"][pr_num]["state"], "MERGED")
            self.assertEqual(final_state["issues"]["42"]["state"], "CLOSED")
            self.assertIn("TASK-01 增加 CSV 后端导出接口", final_state["prs"][pr_num]["body"])
            wt_head = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()
            merge_calls = [c for c in final_state["calls"] if c[:2] == ["pr", "merge"]]
            self.assertTrue(merge_calls)
            self.assertIn("--match-head-commit", merge_calls[-1])
            idx = merge_calls[-1].index("--match-head-commit")
            self.assertEqual(merge_calls[-1][idx + 1], wt_head)

    def test_repo_init_and_issue_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            created = json.loads(
                h.run_idd("issue", "create", "--title", "Add webhook", "--body", "Details", "--label", "feat", "--json").stdout
            )
            self.assertEqual(created["number"], 50)
            self.assertIn("/issues/50", created["url"])

            applied = h.run_idd("repo-init", "--apply").stdout
            self.assertIn("allow_merge_commit: False", applied)
            self.assertIn("allow_squash_merge: True", applied)
            self.assertIn("delete_branch_on_merge: False", applied)

    def test_version_flag_and_missing_subcommand(self) -> None:
        res = subprocess.run([sys.executable, str(IDD_BIN), "--version"], capture_output=True, text=True, check=True)
        self.assertIn(f"idd {parse_skill_version()}", res.stdout)
        no_args = subprocess.run([sys.executable, str(IDD_BIN)], capture_output=True, text=True, check=False)
        self.assertEqual(no_args.returncode, 2)

    def test_cleanup_verifies_head_oid_and_preserves_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "实现导出", "done")
            (wt / "export.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(wt), "commit", "-m",
                    "feat: 实现导出\n\nTask: 42-export-csv/TASK-01\nRefs: #42\nTest: pytest — 1 passed",
                ],
                check=True,
                capture_output=True,
            )
            h.run_idd("pr", "42")
            h.run_idd("land", "42")
            self.assertTrue(wt.exists())

            # Extra post-merge local commit: working tree is clean, but HEAD != merged PR headRefOid
            subprocess.run(
                ["git", "-C", str(wt), "commit", "--allow-empty", "-m", "feat: post-merge local wip"],
                check=True,
                capture_output=True,
            )
            skipped = h.run_idd("cleanup").stdout
            self.assertTrue(wt.exists(), "cleanup MUST NOT remove worktree with post-merge local commit")
            self.assertIn("headRefOid 不一致", skipped)

            # Reset back to merged PR commit -> cleanup removes ONLY worktree directory, keeping local & remote branches
            subprocess.run(["git", "-C", str(wt), "reset", "--hard", "HEAD~1"], check=True, capture_output=True)
            cleaned = h.run_idd("cleanup").stdout
            self.assertIn("已移除工作树目录", cleaned)
            self.assertIn("保留分支 feat/42-export-csv", cleaned)
            self.assertFalse(wt.exists())
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(h.repo), "show-ref", "--verify", "--quiet", "refs/heads/feat/42-export-csv"]
                ).returncode,
                0,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "--git-dir", str(h.origin), "show-ref", "--verify", "--quiet", "refs/heads/feat/42-export-csv"]
                ).returncode,
                0,
            )

    def test_branch_naming_enforces_eight_types_and_blocks_tool_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            for bad in ("codex/bad-branch", "claude/bad-branch", "feature/bad-branch", "bugfix/bad"):
                res = h.run_idd("start", bad, check=False)
                self.assertNotEqual(res.returncode, 0, f"Expected failure for {bad}")
                self.assertIn("不符合 IDD 规范", res.stderr)
                self.assertIn("git branch -m", res.stderr)

            # Valid typed slug target without issue
            perf_data = json.loads(h.run_idd("start", "perf/cache-layer", "--json").stdout)
            self.assertEqual(perf_data["branch"], "perf/cache-layer")

            # Verify --prefix accepts all 8 allowed types (test remaining types quickly)
            for idx, branch_type in enumerate(["refactor", "docs", "test", "ci", "chore"], start=100):
                res = json.loads(h.run_idd("start", f"local-item-{idx}", "--prefix", branch_type, "--json").stdout)
                self.assertEqual(res["branch"], f"{branch_type}/local-item-{idx}")

            # Start #42 legitimately, then rename branch to forbidden `codex/42-export-csv`
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            self._write_task(wt, "42-export-csv", 1, "测试拦截", "done")
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 测试"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(wt), "branch", "-m", "codex/42-export-csv"], check=True)

            for cmd_args in (["start", "42"], ["sync", "42"], ["pr", "42"], ["land", "42"]):
                blocked = h.run_idd(*cmd_args, cwd=wt, check=False)
                self.assertNotEqual(blocked.returncode, 0, f"{cmd_args} should block codex/42-export-csv")
                self.assertIn("codex/", blocked.stderr)
                self.assertIn("feat/42-export-csv", blocked.stderr)

            # Zero invasive git hooks installed
            hooks_dir = h.repo / ".git/hooks"
            custom_hooks = [p.name for p in hooks_dir.iterdir() if not p.name.endswith(".sample")]
            self.assertEqual(custom_hooks, [])

    def test_safe_auto_update_and_upgrade_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            skill_origin = tmp_path / "skill_origin.git"
            skill_repo = tmp_path / "skill_repo"
            upstream_pusher = tmp_path / "upstream_pusher"
            cache_dir = tmp_path / "cache"
            work_repo = tmp_path / "work_repo"

            subprocess.run(["git", "init", "--bare", "-b", "main", str(skill_origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(skill_origin), str(skill_repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(skill_repo), "checkout", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(skill_repo), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(skill_repo), "config", "user.email", "test@example.com"], check=True)
            (skill_repo / "README.md").write_text("v1\n", encoding="utf-8")
            (skill_repo / "scripts").mkdir()
            idd_script = skill_repo / "scripts/idd"
            idd_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            idd_script.chmod(idd_script.stat().st_mode | stat.S_IXUSR)
            subprocess.run(["git", "-C", str(skill_repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(skill_repo), "commit", "-m", "init skill"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(skill_repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
            subprocess.run(["git", "--git-dir", str(skill_origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

            # Separate work repo where user runs `idd status --local-only --json`
            work_repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(work_repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(work_repo), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(work_repo), "config", "user.email", "test@example.com"], check=True)
            (work_repo / "f.txt").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(work_repo), "add", "f.txt"], check=True)
            subprocess.run(["git", "-C", str(work_repo), "commit", "-m", "init work"], check=True, capture_output=True)

            # Push commit #2 to skill_origin
            subprocess.run(["git", "clone", str(skill_origin), str(upstream_pusher)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(upstream_pusher), "config", "user.name", "Upstream"], check=True)
            subprocess.run(["git", "-C", str(upstream_pusher), "config", "user.email", "up@example.com"], check=True)
            (upstream_pusher / "README.md").write_text("v2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(upstream_pusher), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(upstream_pusher), "commit", "-m", "feat: skill v2 update"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(upstream_pusher), "push", "origin", "main"], check=True, capture_output=True)

            env = dict(os.environ)
            env["IDD_SKILL_DIR"] = str(skill_repo)
            env["IDD_CACHE_DIR"] = str(cache_dir)
            env["IDD_CONFIG_DIR"] = str(tmp_path / "idd-config")
            env["IDD_UPDATE_INTERVAL"] = "3600"
            env.pop("IDD_NO_AUTO_UPDATE", None)

            # Background auto-update safely fast-forwards clean main
            subprocess.run([sys.executable, str(IDD_CLI), "--_bg-auto-update"], env=env, check=True, capture_output=True)
            self.assertEqual((skill_repo / "README.md").read_text(encoding="utf-8"), "v2\n")

            # Next command prints notice to stderr without breaking JSON on stdout
            res1 = subprocess.run(
                [sys.executable, str(IDD_BIN), "status", "--local-only", "--json"],
                cwd=str(work_repo),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIsInstance(json.loads(res1.stdout), dict)
            self.assertIn("✨ idd 已自动同步至最新", res1.stderr)
            self.assertIn("feat: skill v2 update", res1.stderr)

            # Subsequent command does not repeat the already-shown notice
            res2 = subprocess.run(
                [sys.executable, str(IDD_BIN), "status", "--local-only", "--json"],
                cwd=str(work_repo),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotIn("✨ idd 已自动同步至最新", res2.stderr)

            # Make skill_repo dirty and push commit #3
            (skill_repo / "README.md").write_text("local-dirty-edit\n", encoding="utf-8")
            head_before = subprocess.check_output(["git", "-C", str(skill_repo), "rev-parse", "HEAD"], text=True).strip()
            (upstream_pusher / "README.md").write_text("v3\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(upstream_pusher), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(upstream_pusher), "commit", "-m", "feat: skill v3 update"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(upstream_pusher), "push", "origin", "main"], check=True, capture_output=True)

            # Background auto-update MUST skip merging when dirty
            subprocess.run([sys.executable, str(IDD_CLI), "--_bg-auto-update"], env=env, check=True, capture_output=True)
            head_after = subprocess.check_output(["git", "-C", str(skill_repo), "rev-parse", "HEAD"], text=True).strip()
            self.assertEqual(head_before, head_after)
            self.assertEqual((skill_repo / "README.md").read_text(encoding="utf-8"), "local-dirty-edit\n")

            # Command notifies user on stderr that remote has updates
            res3 = subprocess.run(
                [sys.executable, str(IDD_BIN), "status", "--local-only", "--json"],
                cwd=str(work_repo),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIsInstance(json.loads(res3.stdout), dict)
            self.assertIn("idd upgrade", res3.stderr)

            # `idd upgrade` while dirty refuses without clobbering local changes
            up_dirty = subprocess.run(
                [sys.executable, str(IDD_BIN), "upgrade"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(up_dirty.returncode, 0)
            self.assertEqual((skill_repo / "README.md").read_text(encoding="utf-8"), "local-dirty-edit\n")

            # Clean dirty file and run `idd upgrade`
            subprocess.run(["git", "-C", str(skill_repo), "checkout", "--", "README.md"], check=True)
            up_clean = subprocess.run(
                [sys.executable, str(IDD_BIN), "upgrade"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("已更新 idd", up_clean.stdout)
            self.assertEqual((skill_repo / "README.md").read_text(encoding="utf-8"), "v3\n")
            state_json = json.loads((cache_dir / "update_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state_json["behind_count"], 0)

    def test_start_auto_pushes_branch_sets_correct_upstream_and_supports_no_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            first = json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)
            wt42 = Path(first["worktree"])
            self.assertTrue(first["pushed"])
            self.assertEqual(
                subprocess.run(
                    ["git", "--git-dir", str(h.origin), "show-ref", "--verify", "--quiet", "refs/heads/feat/42-export-csv"]
                ).returncode,
                0,
            )
            upstream42 = subprocess.check_output(
                ["git", "-C", str(wt42), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                text=True,
            ).strip()
            self.assertEqual(upstream42, "origin/feat/42-export-csv")

            # `--no-push` keeps branch local and MUST NOT bind upstream to origin/main
            second = json.loads(h.run_idd("start", "43", "--no-push", "--json").stdout)
            wt43 = Path(second["worktree"])
            self.assertFalse(second["pushed"])
            self.assertNotEqual(
                subprocess.run(
                    [
                        "git",
                        "--git-dir",
                        str(h.origin),
                        "show-ref",
                        "--verify",
                        "--quiet",
                        "refs/heads/fix/43-fix-dark-mode-flicker",
                    ]
                ).returncode,
                0,
            )
            up_proc = subprocess.run(
                ["git", "-C", str(wt43), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(up_proc.returncode, 0)

            # Reusing existing unpushed worktree via `idd start 43` auto-pushes it to origin
            reused = json.loads(h.run_idd("start", "43", "--json").stdout)
            self.assertTrue(reused["reused"])
            self.assertTrue(reused["pushed"])
            self.assertEqual(
                subprocess.run(
                    [
                        "git",
                        "--git-dir",
                        str(h.origin),
                        "show-ref",
                        "--verify",
                        "--quiet",
                        "refs/heads/fix/43-fix-dark-mode-flicker",
                    ]
                ).returncode,
                0,
            )
            upstream43 = subprocess.check_output(
                ["git", "-C", str(wt43), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                text=True,
            ).strip()
            self.assertEqual(upstream43, "origin/fix/43-fix-dark-mode-flicker")

    def test_sync_auto_pushes_commits_and_respects_no_push(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            initial_remote_sha = subprocess.check_output(
                ["git", "--git-dir", str(h.origin), "rev-parse", "refs/heads/feat/42-export-csv"],
                text=True,
            ).strip()

            self._write_task(wt, "42-export-csv", 1, "增加 CSV 导出", "done")
            (wt / "csv.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 增加 CSV 导出"], check=True, capture_output=True)
            local_sha = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()
            self.assertNotEqual(local_sha, initial_remote_sha)

            # `--no-push` updates Issue body without pushing branch
            h.run_idd("sync", "42", "--no-push")
            self.assertIn("- [x] TASK-01：增加 CSV 导出", h.load_state()["issues"]["42"]["body"])
            remote_after_no_push = subprocess.check_output(
                ["git", "--git-dir", str(h.origin), "rev-parse", "refs/heads/feat/42-export-csv"],
                text=True,
            ).strip()
            self.assertEqual(remote_after_no_push, initial_remote_sha)

            # Default `idd sync` updates Issue body AND pushes local commit to origin
            sync_out = h.run_idd("sync", "42").stdout
            self.assertIn("已同步推送分支至远端：origin/feat/42-export-csv", sync_out)
            remote_after_sync = subprocess.check_output(
                ["git", "--git-dir", str(h.origin), "rev-parse", "refs/heads/feat/42-export-csv"],
                text=True,
            ).strip()
            self.assertEqual(remote_after_sync, local_sha)

    def test_check_acceptance_criteria_markdown_edge_cases(self) -> None:
        sample = (
            "## 背景\n\n"
            "- [ ] 非验收复选框\n\n"
            "## 1. 验收标准（必选）\n\n"
            "- [ ] 支持 UTF-8 BOM\n"
            "- [x] 已完成的一项\n"
            "  * [ ] 缩进星号项\n"
            "  + [ ] 缩进加号项\n"
            "  1. [ ] 有序列表项\n"
            "### 子验收条件\n"
            "- [ ] 子标题下的验收项\n"
            "- [ ] 保底刷新 `<!-- idd:progress:start -->` 进度块\n\n"
            "```markdown\n"
            "## 验收标准\n"
            "<!-- idd:progress:start -->\n"
            "- [ ] 代码块里的示例不能改\n"
            "```\n\n"
            "~~~\n"
            "- [ ] 波浪线代码块不能改\n"
            "~~~\n\n"
            "- [ ] 代码块之后同节验收项\n\n"
            "## 后续计划\n\n"
            "- [ ] 下一期优化项\n\n"
            "## Acceptance Criteria\n\n"
            "- [ ] English item\n"
            "- [X] Uppercase already checked\n\n"
            "<!-- idd:progress:start -->\n"
            "## 执行进度（IDD 自动同步）\n"
            "- [ ] TASK-01：进度块内保持原样\n"
            "<!-- idd:progress:end -->\n"
        )
        updated, count = idd_cli.check_acceptance_criteria(sample)
        self.assertEqual(count, 8)
        self.assertIn("- [ ] 非验收复选框", updated)
        self.assertIn("- [x] 支持 UTF-8 BOM", updated)
        self.assertIn("- [x] 已完成的一项", updated)
        self.assertIn("  * [x] 缩进星号项", updated)
        self.assertIn("  + [x] 缩进加号项", updated)
        self.assertIn("  1. [x] 有序列表项", updated)
        self.assertIn("- [x] 子标题下的验收项", updated)
        self.assertIn("- [x] 保底刷新 `<!-- idd:progress:start -->` 进度块", updated)
        self.assertIn("- [ ] 代码块里的示例不能改", updated)
        self.assertIn("- [ ] 波浪线代码块不能改", updated)
        self.assertIn("- [x] 代码块之后同节验收项", updated)
        self.assertIn("- [ ] 下一期优化项", updated)
        self.assertIn("- [x] English item", updated)
        self.assertIn("- [X] Uppercase already checked", updated)
        self.assertIn("- [ ] TASK-01：进度块内保持原样", updated)

        # Idempotent on second run
        updated2, count2 = idd_cli.check_acceptance_criteria(updated)
        self.assertEqual(count2, 0)
        self.assertEqual(updated2, updated)

        # Preserves CRLF and missing trailing newline
        crlf = "## 验收\r\n- [ ] 行一\r\n- [ ] 行二"
        crlf_out, crlf_count = idd_cli.check_acceptance_criteria(crlf)
        self.assertEqual(crlf_count, 2)
        self.assertEqual(crlf_out, "## 验收\r\n- [x] 行一\r\n- [x] 行二")

    def test_land_checks_acceptance_criteria_and_respects_flags(self) -> None:
        issue_body_template = (
            "## 范围\n\n"
            "- [ ] 范围说明框（不应被勾选）\n\n"
            "## 验收标准\n\n"
            "- [ ] 验收项一：支持导出\n"
            "- [ ] 验收项二：单测通过\n\n"
            "## 后续计划\n\n"
            "- [ ] 二期规划\n"
        )

        # Case 1: --dry-run preview and default land checks acceptance + syncs TASK progress
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["42"]["body"] = issue_body_template
            h.save_state()

            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            # Sync initial in_progress state to Issue #42, then finish TASK-01 without running sync again
            self._write_task(wt, "42-export-csv", 1, "导出 CSV", "in_progress")
            h.run_idd("sync", "42")
            self.assertIn("- [ ] TASK-01：导出 CSV *(in_progress)*", h.load_state()["issues"]["42"]["body"])

            self._write_task(wt, "42-export-csv", 1, "导出 CSV", "done")
            (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 导出 CSV"], check=True, capture_output=True)
            h.run_idd("pr", "42")

            dry_out = h.run_idd("land", "42", "--dry-run").stdout
            self.assertIn("合入后勾选 Issue 验收标准: 是（将勾选 2 项）", dry_out)
            self.assertIn("- [ ] 验收项一：支持导出", h.load_state()["issues"]["42"]["body"])

            land_out = h.run_idd("land", "42").stdout
            self.assertIn("已自动勾选 Issue #42 验收标准（2 项）", land_out)
            final_body = h.load_state()["issues"]["42"]["body"]
            self.assertIn("- [ ] 范围说明框（不应被勾选）", final_body)
            self.assertIn("- [x] 验收项一：支持导出", final_body)
            self.assertIn("- [x] 验收项二：单测通过", final_body)
            self.assertIn("- [ ] 二期规划", final_body)
            self.assertIn("- [x] TASK-01：导出 CSV", final_body)
            self.assertNotIn("*(in_progress)*", final_body)

        # Case 2: --auto waits for CI and does NOT prematurely check acceptance criteria
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["42"]["body"] = issue_body_template
            h.save_state()

            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "导出 CSV", "done")
            (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 导出 CSV"], check=True, capture_output=True)
            h.run_idd("pr", "42")

            dry_auto = h.run_idd("land", "42", "--auto", "--dry-run").stdout
            self.assertIn("暂不勾选（--auto 等待 CI 期间不提前勾选）", dry_auto)

            auto_out = h.run_idd("land", "42", "--auto").stdout
            self.assertIn("开启自动 Squash 合并", auto_out)
            body_after_auto = h.load_state()["issues"]["42"]["body"]
            self.assertIn("- [ ] 验收项一：支持导出", body_after_auto)
            self.assertIn("- [ ] 验收项二：单测通过", body_after_auto)

        # Case 2: --no-check-acceptance skips acceptance boxes
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["42"]["body"] = issue_body_template
            h.save_state()

            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "导出 CSV", "done")
            (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 导出 CSV"], check=True, capture_output=True)
            h.run_idd("pr", "42")

            dry_skip = h.run_idd("land", "42", "--no-check-acceptance", "--dry-run").stdout
            self.assertIn("合入后勾选 Issue 验收标准: 否（已传 --no-check-acceptance）", dry_skip)

            land_skip = h.run_idd("land", "42", "--no-check-acceptance").stdout
            self.assertNotIn("已自动勾选", land_skip)
            body_after_skip = h.load_state()["issues"]["42"]["body"]
            self.assertIn("- [ ] 验收项一：支持导出", body_after_skip)
            self.assertIn("- [ ] 验收项二：单测通过", body_after_skip)

        # Case 3: Issue update failure prints non-fatal warning and still fast-forwards main
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["42"]["body"] = issue_body_template
            h.state["fail_issue_edit"] = True
            h.save_state()

            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "导出 CSV", "done")
            (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 导出 CSV"], check=True, capture_output=True)
            h.run_idd("pr", "42")

            warn_res = h.run_idd("land", "42")
            self.assertEqual(warn_res.returncode, 0)
            self.assertIn("⚠️ 合入已成功，但自动更新 Issue #42 验收标准失败", warn_res.stdout)
            self.assertIn("本地 `main` 已快进至：", warn_res.stdout)
            self.assertTrue((h.repo / "export.py").is_file())

    def test_pr_and_land_avoid_duplicate_conventional_title_prefixes(self) -> None:
        self.assertEqual(idd_cli._format_conventional_title("fix", "修复断连"), "fix: 修复断连")
        self.assertEqual(idd_cli._format_conventional_title("fix", "fix: 修复断连"), "fix: 修复断连")
        self.assertEqual(idd_cli._format_conventional_title("fix", "Feat(ui)!: 支持筛选"), "feat(ui)!: 支持筛选")
        self.assertEqual(idd_cli._format_conventional_title("fix", "FIX：修复中文冒号"), "fix: 修复中文冒号")
        self.assertEqual(idd_cli._format_conventional_title("feat", "API: 新增接口"), "feat: API: 新增接口")

        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["43"]["title"] = "fix: 过滤遗留任务"
            h.save_state()

            wt = Path(
                json.loads(h.run_idd("start", "43", "--prefix", "fix", "--slug", "legacy-tasks", "--json").stdout)[
                    "worktree"
                ]
            )
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            self._write_task(wt, "43-legacy-tasks", 1, "过滤遗留任务", "done", issue="#43")
            (wt / "legacy.py").write_text("clean = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(wt),
                    "commit",
                    "-m",
                    "fix: 过滤遗留任务\n\nTask: 43-legacy-tasks/TASK-01\nRefs: #43\nTest: pytest — 1 passed",
                ],
                check=True,
                capture_output=True,
            )

            dry_pr = h.run_idd("pr", "43", "--dry-run").stdout
            self.assertIn("Title: fix: 过滤遗留任务 (#43)", dry_pr)
            self.assertNotIn("fix: fix:", dry_pr)

            h.run_idd("pr", "43")
            prs = list(h.load_state()["prs"].values())
            self.assertEqual(len(prs), 1)
            self.assertEqual(prs[0]["title"], "fix: 过滤遗留任务 (#43)")

            dry_land = h.run_idd("land", "43", "--dry-run").stdout
            self.assertIn("Squash 提交标题: fix: 过滤遗留任务 (#43)", dry_land)
            self.assertNotIn("fix: fix:", dry_land)

    def test_first_time_repo_init_hint_prompts_once_and_marks_aligned(self) -> None:
        self.assertEqual(
            idd_cli.evaluate_repo_init_settings(
                {"forge": "github", "settings": {"allow_merge_commit": False, "allow_squash_merge": True, "delete_branch_on_merge": False}}
            ),
            (True, []),
        )
        self.assertEqual(
            idd_cli.evaluate_repo_init_settings(
                {"forge": "gitlab", "settings": {"merge_method": "ff", "squash_option": "always", "remove_source_branch_after_merge": False}}
            ),
            (True, []),
        )
        self.assertEqual(
            idd_cli.evaluate_repo_init_settings({"forge": "gitlab", "settings": {"merge_method": None, "squash_option": None}}),
            (True, []),
        )

        # 1. Unaligned GitHub repo prompts once on first onboarding command, then stops repeating and updates on apply
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            first_out = h.run_idd("issue", "create", "--title", "Test onboarding", "--body", "desc").stdout
            self.assertIn("💡 首次接管提示", first_out)
            self.assertIn("allow_merge_commit=true（建议 false）", first_out)
            self.assertIn("idd repo-init --apply", first_out)

            repos_file = h.root / "idd-config" / "repos.json"
            repos_data = json.loads(repos_file.read_text(encoding="utf-8"))
            self.assertEqual(repos_data["repos"][0]["repo_init_state"], "prompted")

            second_out = h.run_idd("start", "42", "--slug", "export-csv").stdout
            self.assertNotIn("💡 首次接管提示", second_out)

            h.run_idd("repo-init", "--apply")
            repos_after = json.loads(repos_file.read_text(encoding="utf-8"))
            self.assertEqual(repos_after["repos"][0]["repo_init_state"], "aligned")

        # 2. Already-aligned GitHub repo skips prompt and records `aligned`
        with tempfile.TemporaryDirectory() as tmp:
            h2 = GitHubHarness(Path(tmp))
            h2.state["repo_settings"].update(
                {"allow_merge_commit": False, "allow_squash_merge": True, "delete_branch_on_merge": False}
            )
            h2.save_state()
            start_out = h2.run_idd("start", "42", "--slug", "export-csv").stdout
            self.assertNotIn("💡 首次接管提示", start_out)
            repos_data2 = json.loads((h2.root / "idd-config" / "repos.json").read_text(encoding="utf-8"))
            self.assertEqual(repos_data2["repos"][0]["repo_init_state"], "aligned")

        # 3. `--json` mode keeps valid JSON with `repo_init_hint`
        with tempfile.TemporaryDirectory() as tmp:
            h3 = GitHubHarness(Path(tmp))
            created_json = json.loads(
                h3.run_idd("issue", "create", "--title", "JSON onboarding", "--body", "desc", "--json").stdout
            )
            self.assertEqual(created_json["repo_init_hint"]["command"], "idd repo-init --apply")
            self.assertIn("allow_merge_commit=true（建议 false）", created_json["repo_init_hint"]["mismatches"])

    def test_merge_progress_block_ignores_inline_and_fenced_markers(self) -> None:
        original = (
            "## 范围\n\n"
            "- 保底刷新 `<!-- idd:progress:start -->` 与 `<!-- idd:progress:end -->` 进度块。\n\n"
            "```markdown\n"
            "<!-- idd:progress:start -->\n"
            "## 示例进度\n"
            "- [ ] 示例任务\n"
            "<!-- idd:progress:end -->\n"
            "```\n\n"
            "## 非目标\n\n"
            "- 不改其他内容。\n\n"
            "## 验收标准\n\n"
            "- [ ] 验收项 A\n"
        )
        block_v1 = (
            "<!-- idd:progress:start -->\n"
            "## 执行进度（IDD 自动同步）\n"
            "- [ ] TASK-01：初始化\n"
            "<!-- idd:progress:end -->"
        )
        merged_v1 = idd_cli.merge_progress_block(original, block_v1)
        self.assertIn("## 非目标", merged_v1)
        self.assertIn("- [ ] 验收项 A", merged_v1)
        self.assertIn("- [ ] 示例任务", merged_v1)
        self.assertIn("- [ ] TASK-01：初始化", merged_v1)
        self.assertEqual(merged_v1.count("<!-- idd:progress:start -->"), 3)

        block_v2 = (
            "<!-- idd:progress:start -->\n"
            "## 执行进度（IDD 自动同步）\n"
            "- [x] TASK-01：初始化\n"
            "<!-- idd:progress:end -->"
        )
        merged_v2 = idd_cli.merge_progress_block(merged_v1, block_v2)
        self.assertIn("## 非目标", merged_v2)
        self.assertIn("- [ ] 验收项 A", merged_v2)
        self.assertIn("- [ ] 示例任务", merged_v2)
        self.assertIn("- [x] TASK-01：初始化", merged_v2)
        self.assertNotIn("- [ ] TASK-01：初始化", merged_v2)

        # Orphan standalone start marker before a real standalone progress block must not wipe prose
        with_orphan = (
            "## 备注\n\n"
            "<!-- idd:progress:start -->\n"
            "保留这段说明。\n\n"
            f"{block_v1}\n"
        )
        merged_orphan = idd_cli.merge_progress_block(with_orphan, block_v2)
        self.assertIn("保留这段说明。", merged_orphan)
        self.assertIn("- [x] TASK-01：初始化", merged_orphan)
        self.assertNotIn("- [ ] TASK-01：初始化", merged_orphan)

    def test_sync_and_land_preserve_body_with_inline_progress_markers(self) -> None:
        issue_body = (
            "## 范围\n\n"
            "- 合入后保底刷新 `<!-- idd:progress:start -->` 进度块。\n\n"
            "## 非目标\n\n"
            "- 不改网页手工合入流程。\n\n"
            "## 验收标准\n\n"
            "- [ ] 保留正文各节并勾选验收框\n"
            "- [ ] 刷新 `<!-- idd:progress:start -->` 进度条\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["42"]["body"] = issue_body
            h.save_state()

            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)

            self._write_task(wt, "42-export-csv", 1, "修复进度块匹配", "in_progress")
            h.run_idd("sync", "42")
            body_sync1 = h.load_state()["issues"]["42"]["body"]
            self.assertIn("## 非目标", body_sync1)
            self.assertIn("- [ ] 保留正文各节并勾选验收框", body_sync1)
            self.assertIn("- [ ] TASK-01：修复进度块匹配 *(in_progress)*", body_sync1)

            self._write_task(wt, "42-export-csv", 1, "修复进度块匹配", "done")
            (wt / "fix.py").write_text("fixed = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "fix: 修复进度块匹配"], check=True, capture_output=True)
            h.run_idd("sync", "42")
            body_sync2 = h.load_state()["issues"]["42"]["body"]
            self.assertIn("## 非目标", body_sync2)
            self.assertIn("- [ ] 保留正文各节并勾选验收框", body_sync2)
            self.assertIn("- [x] TASK-01：修复进度块匹配", body_sync2)

            h.run_idd("pr", "42")
            land_out = h.run_idd("land", "42").stdout
            self.assertIn("已自动勾选 Issue #42 验收标准（2 项）", land_out)
            final_body = h.load_state()["issues"]["42"]["body"]
            self.assertIn("## 非目标", final_body)
            self.assertIn("- [x] 保留正文各节并勾选验收框", final_body)
            self.assertIn("- [x] 刷新 `<!-- idd:progress:start -->` 进度条", final_body)
            self.assertIn("- [x] TASK-01：修复进度块匹配", final_body)


if __name__ == "__main__":
    unittest.main()
