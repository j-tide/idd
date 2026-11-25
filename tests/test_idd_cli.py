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


IDD_BIN = Path(__file__).resolve().parents[1] / "scripts/idd"


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
    save_state(state)
    print(json.dumps(pr))
    sys.exit(0)

if args[:2] == ["pr", "merge"]:
    num = args[2]
    pr = state["prs"][str(num)]
    subject = arg_val(args, "--subject") or pr["title"]
    body = Path(arg_val(args, "--body-file")).read_text(encoding="utf-8") if arg_val(args, "--body-file") else pr["body"]
    if "--auto" in args:
        pr["autoMergeRequest"] = True
        save_state(state)
        print("auto-merge enabled")
        sys.exit(0)

    head = pr["headRefName"]
    base = pr["baseRefName"]
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
            "delete_branch_on_merge": True,
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
    def _write_task(self, wt: Path, goal: str, num: int, title: str, status: str, issue: str = "#42") -> Path:
        task_dir = wt / "TASK" / goal
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / f"TASK-{num:02d}-step.md"
        path.write_text(
            f"# TASK-{num:02d}：{title}\n\n"
            f"- Goal: {goal}\n"
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

            res = subprocess.run(
                [sys.executable, str(IDD_BIN), "start", "local-refactor", "--json"],
                cwd=str(repo),
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
            self.assertIn("Goal: 42-export-csv", dry_pr)
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

            # Now land with --force-clean-evidence
            land_res = h.run_idd("land", "42", "--force-clean-evidence")
            self.assertIn("Squash Merge 直线合入", land_res.stdout)
            self.assertFalse(wt.exists(), "Worktree should be removed after land")

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
            self.assertIn("delete_branch_on_merge: True", applied)


if __name__ == "__main__":
    unittest.main()
