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
    if state.get("cleanup_pending_polls", 0) > 0:
        state["pending_check_polls"] = state.pop("cleanup_pending_polls")
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
    seq = state.get("pending_check_polls", 0)
    if seq > 0:
        state["pending_check_polls"] = seq - 1
        pr["statusCheckRollup"] = [{"name": "ci / test", "status": "IN_PROGRESS", "conclusion": ""}]
    elif "settled_checks" in state:
        pr["statusCheckRollup"] = state["settled_checks"]
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
        if state.get("fail_repo_init_patch"):
            save_state(state)
            print("gh: 403 Forbidden (Must have admin rights to Repository.)", file=sys.stderr)
            sys.exit(1)
        state["repo_settings"].update({
            "allow_merge_commit": False,
            "allow_squash_merge": True,
            "delete_branch_on_merge": False,
            "squash_merge_commit_title": "PR_TITLE",
            "squash_merge_commit_message": "PR_BODY",
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
                "squash_merge_commit_title": "COMMIT_OR_PR_TITLE",
                "squash_merge_commit_message": "COMMIT_MESSAGES",
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

    def run_idd(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_GH_STATE"] = str(self.state_file)
        env["FAKE_GH_ORIGIN"] = str(self.origin)
        env["IDD_NO_AUTO_UPDATE"] = "1"
        env["IDD_CONFIG_DIR"] = str(self.root / "idd-config")
        env.pop("IDD_WORKTREE_ROOT", None)
        if extra_env:
            env.update(extra_env)
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
            self.assertIn("## 变更内容", dry_pr)
            self.assertIn("- **TASK-01** 增加 CSV 后端导出接口", dry_pr)
            self.assertIn("## 验证记录", dry_pr)
            self.assertIn("| TASK-02 | `pytest tests/test_export.py` | 5 passed |", dry_pr)
            self.assertNotIn("### TASK-01", dry_pr)

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
            self.assertIn("- **TASK-01** 增加 CSV 后端导出接口", final_state["prs"][pr_num]["body"])
            self.assertIn("| TASK-02 | `pytest tests/test_export.py` | 5 passed |", final_state["prs"][pr_num]["body"])
            squash_msg = subprocess.check_output(
                ["git", "-C", str(h.repo), "log", "-1", "--format=%B", "main"],
                text=True,
            )
            self.assertIn("TASK-01: 增加 CSV 后端导出接口", squash_msg)
            self.assertIn("Test: pytest tests/test_export.py — 5 passed", squash_msg)
            self.assertNotIn("### ", squash_msg)
            self.assertNotIn("**Test:**", squash_msg)
            self.assertNotIn("<details>", squash_msg)
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
                h.run_idd("issue", "create", "--title", "feat: Add webhook", "--body", "Details", "--label", "feat", "--json").stdout
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
                {
                    "forge": "github",
                    "settings": {
                        "allow_merge_commit": False,
                        "allow_squash_merge": True,
                        "delete_branch_on_merge": False,
                        "squash_merge_commit_title": "PR_TITLE",
                        "squash_merge_commit_message": "PR_BODY",
                    },
                }
            ),
            (True, []),
        )
        gh_bad, gh_mm = idd_cli.evaluate_repo_init_settings(
            {
                "forge": "github",
                "settings": {
                    "allow_merge_commit": False,
                    "allow_squash_merge": True,
                    "delete_branch_on_merge": False,
                    "squash_merge_commit_title": "COMMIT_OR_PR_TITLE",
                    "squash_merge_commit_message": "COMMIT_MESSAGES",
                },
            }
        )
        self.assertFalse(gh_bad)
        self.assertIn("squash_merge_commit_title=COMMIT_OR_PR_TITLE（建议 PR_TITLE）", gh_mm)
        self.assertIn("squash_merge_commit_message=COMMIT_MESSAGES（建议 PR_BODY）", gh_mm)

        self.assertEqual(
            idd_cli.evaluate_repo_init_settings(
                {
                    "forge": "gitlab",
                    "settings": {
                        "merge_method": "ff",
                        "squash_option": "always",
                        "remove_source_branch_after_merge": False,
                        "squash_commit_template": "%{title}\n\n%{description}",
                    },
                }
            ),
            (True, []),
        )
        gl_bad, gl_mm = idd_cli.evaluate_repo_init_settings(
            {
                "forge": "gitlab",
                "settings": {
                    "merge_method": "ff",
                    "squash_option": "always",
                    "remove_source_branch_after_merge": False,
                    "squash_commit_template": "%{title}",
                },
            }
        )
        self.assertFalse(gl_bad)
        self.assertTrue(any("squash_commit_template=" in m for m in gl_mm))

        self.assertEqual(
            idd_cli.evaluate_repo_init_settings({"forge": "gitlab", "settings": {"merge_method": None, "squash_option": None}}),
            (True, []),
        )

        # 1. Default first-time GitHub onboarding auto-applies `repo-init --apply` including PR_TITLE / PR_BODY
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            first_out = h.run_idd("issue", "create", "--title", "feat: Test onboarding", "--body", "desc").stdout
            self.assertIn("✅ 首次接管已自动初始化 GitHub 仓库线性 Squash 策略与提交模板", first_out)

            repos_file = h.root / "idd-config" / "repos.json"
            repos_data = json.loads(repos_file.read_text(encoding="utf-8"))
            self.assertEqual(repos_data["repos"][0]["repo_init_state"], "aligned")

            settings_after = h.load_state()["repo_settings"]
            self.assertFalse(settings_after["allow_merge_commit"])
            self.assertEqual(settings_after["squash_merge_commit_title"], "PR_TITLE")
            self.assertEqual(settings_after["squash_merge_commit_message"], "PR_BODY")

            second_out = h.run_idd("start", "42", "--slug", "export-csv").stdout
            self.assertNotIn("首次接管", second_out)

        # 2. `--no-repo-init` skips auto-apply, persists `pending`, shows in `idd repos list`, and clears on `repo-init --apply`
        with tempfile.TemporaryDirectory() as tmp:
            h2 = GitHubHarness(Path(tmp))
            skipped_out = h2.run_idd("issue", "create", "--title", "feat: Skip init", "--body", "desc", "--no-repo-init").stdout
            self.assertIn("已跳过自动初始化 GitHub 仓库线性 Squash 策略", skipped_out)
            self.assertIn("allow_merge_commit=true（建议 false）", skipped_out)

            repos_file2 = h2.root / "idd-config" / "repos.json"
            repos_data2 = json.loads(repos_file2.read_text(encoding="utf-8"))
            self.assertEqual(repos_data2["repos"][0]["repo_init_state"], "pending")
            self.assertIn("allow_merge_commit=true（建议 false）", repos_data2["repos"][0]["repo_init_mismatches"])

            repos_list = h2.run_idd("repos", "list").stdout
            self.assertIn("[待初始化策略: idd repo-init --apply]", repos_list)

            h2.run_idd("repo-init", "--apply")
            repos_after2 = json.loads(repos_file2.read_text(encoding="utf-8"))
            self.assertEqual(repos_after2["repos"][0]["repo_init_state"], "aligned")
            self.assertNotIn("repo_init_mismatches", repos_after2["repos"][0])

        # 3. 403 / permission failure on auto-apply does NOT block `issue create` and persists `pending` + error
        with tempfile.TemporaryDirectory() as tmp:
            h3 = GitHubHarness(Path(tmp))
            h3.state["fail_repo_init_patch"] = True
            h3.save_state()
            fail_out = h3.run_idd("issue", "create", "--title", "feat: Perm fail", "--body", "desc").stdout
            self.assertIn("已创建 Issue #50", fail_out)
            self.assertIn("未完成", fail_out)
            self.assertIn("403 Forbidden", fail_out)

            repos_file3 = h3.root / "idd-config" / "repos.json"
            repos_data3 = json.loads(repos_file3.read_text(encoding="utf-8"))
            self.assertEqual(repos_data3["repos"][0]["repo_init_state"], "pending")
            self.assertIn("403 Forbidden", repos_data3["repos"][0]["repo_init_error"])

            h3.state["fail_repo_init_patch"] = False
            h3.save_state()
            h3.run_idd("repo-init", "--apply")
            repos_after3 = json.loads(repos_file3.read_text(encoding="utf-8"))
            self.assertEqual(repos_after3["repos"][0]["repo_init_state"], "aligned")
            self.assertNotIn("repo_init_error", repos_after3["repos"][0])

        # 4. `--json` mode keeps valid JSON with `repo_init_hint`
        with tempfile.TemporaryDirectory() as tmp:
            h4 = GitHubHarness(Path(tmp))
            created_json = json.loads(
                h4.run_idd("issue", "create", "--title", "feat: JSON onboarding", "--body", "desc", "--json").stdout
            )
            self.assertEqual(created_json["repo_init_hint"]["status"], "applied")
            self.assertEqual(created_json["repo_init_hint"]["command"], "idd repo-init --apply")

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

    def test_issue_title_validation_short_scope_and_flags(self) -> None:
        # Valid normalized formats
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("feat: 支持导出 CSV"),
            "feat: 支持导出 CSV",
        )
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("fix(sync): 避免误匹配行内标记"),
            "fix(sync): 避免误匹配行内标记",
        )
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("Feat(Repo-Init)!：中文冒号"),
            "feat(repo-init)!: 中文冒号",
        )

        # --type / --scope assembly & idempotency
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("补齐校验", issue_type="fix", scope="land"),
            "fix(land): 补齐校验",
        )
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("fix: 补齐校验", issue_type="fix", scope="land"),
            "fix(land): 补齐校验",
        )
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("fix(land): 补齐校验", issue_type="fix", scope="LAND"),
            "fix(land): 补齐校验",
        )

        # Escape hatch --raw
        self.assertEqual(
            idd_cli.validate_and_format_issue_title("Tracking Q4 roadmap", raw=True),
            "Tracking Q4 roadmap",
        )
        with self.assertRaises(idd_cli.IddError):
            idd_cli.validate_and_format_issue_title("Tracking Q4", issue_type="feat", raw=True)
        with self.assertRaises(idd_cli.IddError):
            idd_cli.validate_and_format_issue_title("Tracking Q4", scope="ui", raw=True)

        # Invalid or missing prefixes, conflicts, empty/multiline
        for bad_title in (
            "",
            "   ",
            "line1\nline2",
            "修复导出空指针",
            "feat(): 空括号",
            "feat(repo-init-and-templates): 太长的括号作用域",
            "fix(sync land): 含空格",
            "fix(sync,land): 含逗号",
            "fix(cli/sync): 含斜杠",
            "fix(同步): 含中文",
        ):
            with self.assertRaises(idd_cli.IddError, msg=f"should reject {bad_title!r}"):
                idd_cli.validate_and_format_issue_title(bad_title)

        with self.assertRaises(idd_cli.IddError):
            idd_cli.validate_and_format_issue_title("fix: 描述", issue_type="feat")
        with self.assertRaises(idd_cli.IddError):
            idd_cli.validate_and_format_issue_title("fix(sync): 描述", scope="land")
        with self.assertRaises(idd_cli.IddError):
            idd_cli.validate_and_format_issue_title("描述", scope="sync")

    def test_issue_create_cli_validation_and_start_title_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))

            # Unprefixed title without --type or --raw is rejected cleanly
            bad_res = h.run_idd("issue", "create", "--title", "修复进度块匹配", check=False)
            self.assertNotEqual(bad_res.returncode, 0)
            self.assertIn("不符合 IDD 命名规范", bad_res.stderr)
            self.assertIn("--raw", bad_res.stderr)

            # Overlong scope (>16 chars) is rejected cleanly
            long_scope_res = h.run_idd(
                "issue",
                "create",
                "--title",
                "feat(very-long-module-name): 过长作用域",
                check=False,
            )
            self.assertNotEqual(long_scope_res.returncode, 0)
            self.assertIn("最多 16 字符", long_scope_res.stderr)

            # --type + --scope succeeds and stores normalized title
            created = json.loads(
                h.run_idd(
                    "issue",
                    "create",
                    "--type",
                    "fix",
                    "--scope",
                    "sync",
                    "--title",
                    "避免误匹配行内标记",
                    "--json",
                ).stdout
            )
            self.assertEqual(created["title"], "fix(sync): 避免误匹配行内标记")
            issue_id_1 = str(created["number"])
            self.assertEqual(h.load_state()["issues"][issue_id_1]["title"], "fix(sync): 避免误匹配行内标记")

            # --raw bypasses validation
            raw_created = json.loads(
                h.run_idd("issue", "create", "--title", "Q4 Milestone Tracker", "--raw", "--json").stdout
            )
            self.assertEqual(raw_created["title"], "Q4 Milestone Tracker")

            # idd start infers prefix from title even with no labels, and avoids `fix-sync` duplication
            h.state["issues"]["60"] = {
                "number": 60,
                "title": "fix(sync): 避免误匹配行内标记",
                "body": "",
                "labels": [],
                "state": "OPEN",
                "url": "https://github.com/acme/demo/issues/60",
            }
            h.state["issues"]["61"] = {
                "number": 61,
                "title": "refactor(land): 拆分合入流程",
                "body": "",
                "labels": [],
                "state": "OPEN",
                "url": "https://github.com/acme/demo/issues/61",
            }
            h.save_state()

            started_60 = json.loads(h.run_idd("start", "60", "--json").stdout)
            self.assertEqual(started_60["branch"], "fix/60-sync")
            self.assertEqual(started_60["issue"], "60-sync")

            # Explicit --prefix overrides title <type>
            started_61 = json.loads(h.run_idd("start", "61", "--prefix", "perf", "--json").stdout)
            self.assertEqual(started_61["branch"], "perf/61-land")

            # Legacy unprefixed Issue with bug label still falls back to fix/
            started_43 = json.loads(h.run_idd("start", "43", "--json").stdout)
            self.assertEqual(started_43["branch"], "fix/43-fix-dark-mode-flicker")

    def test_config_auto_merge_global_repo_override_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            h = GitHubHarness(tmp_path)

            # Default is disabled globally and per-repo
            initial = json.loads(h.run_idd("config", "--json").stdout)
            self.assertFalse(initial["global"]["auto_merge"])
            self.assertFalse(initial["repo"]["auto_merge"]["enabled"])
            self.assertEqual(initial["repo"]["auto_merge"]["source"], "global")
            self.assertIsNone(initial["repo"]["auto_merge"]["repo_override"])

            # Non-git directory without -g/--global rejects repo-level toggle
            outside = tmp_path / "outside"
            outside.mkdir()
            err_res = h.run_idd("config", "auto-merge", "on", cwd=outside, check=False)
            self.assertNotEqual(err_res.returncode, 0)
            self.assertIn("-g/--global", err_res.stderr)

            # Global inherit is rejected
            bad_global = h.run_idd("config", "auto-merge", "inherit", "-g", check=False)
            self.assertNotEqual(bad_global.returncode, 0)

            # Enable globally
            g_on = json.loads(h.run_idd("config", "auto-merge", "on", "-g", "--json").stdout)
            self.assertTrue(g_on["auto_merge"])
            inherited = json.loads(h.run_idd("config", "auto-merge", "status", "--json").stdout)
            self.assertTrue(inherited["auto_merge"]["enabled"])
            self.assertEqual(inherited["auto_merge"]["source"], "global")
            self.assertIsNone(inherited["auto_merge"]["repo_override"])

            # Override off at repo level
            r_off = json.loads(h.run_idd("config", "auto-merge", "off", "--json").stdout)
            self.assertFalse(r_off["auto_merge"]["enabled"])
            self.assertEqual(r_off["auto_merge"]["source"], "repo")
            self.assertFalse(r_off["auto_merge"]["repo_override"])

            # Ensure register_repo / repo-init metadata writes do NOT clobber auto_merge
            h.run_idd("status", "--local-only")
            h.run_idd("repo-init", "--apply")
            after_writes = json.loads(h.run_idd("config", "--json").stdout)
            self.assertFalse(after_writes["repo"]["auto_merge"]["enabled"])
            self.assertFalse(after_writes["repo"]["auto_merge"]["repo_override"])

            repos_list_txt = h.run_idd("repos", "list").stdout
            self.assertIn("[auto-merge: off]", repos_list_txt)

            # Inherit clears override and falls back to global=True
            r_inh = json.loads(h.run_idd("config", "auto-merge", "inherit", "--json").stdout)
            self.assertTrue(r_inh["auto_merge"]["enabled"])
            self.assertEqual(r_inh["auto_merge"]["source"], "global")
            self.assertIsNone(r_inh["auto_merge"]["repo_override"])

            # Status JSON exposes auto_merge and global config
            status_json = json.loads(h.run_idd("status", "--local-only", "--json").stdout)
            self.assertTrue(status_json["auto_merge"]["enabled"])
            g_status_json = json.loads(h.run_idd("status", "-g", "--local-only", "--json").stdout)
            self.assertTrue(g_status_json["config"]["auto_merge"])
            status_txt = h.run_idd("status", "--local-only").stdout
            self.assertIn("自动合入: 开", status_txt)

    def test_pr_auto_merge_waits_for_ci_and_lands_linearly(self) -> None:
        fast_env = {
            "IDD_CI_GRACE_SECONDS": "0",
            "IDD_CI_POLL_INTERVAL": "0.01",
            "IDD_LAND_SYNC_INTERVAL": "0.01",
        }
        # Case 1: Global auto_merge enabled -> pr waits for pending CI (initial + cleanup commit) -> lands & checks acceptance
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["issues"]["42"]["body"] = "## 验收标准\n\n- [ ] 支持导出 CSV\n"
            h.state["default_checks"] = [{"name": "ci / test", "status": "IN_PROGRESS", "conclusion": ""}]
            h.state["pending_check_polls"] = 2
            h.state["cleanup_pending_polls"] = 2
            h.state["settled_checks"] = [{"name": "ci / test", "status": "COMPLETED", "conclusion": "SUCCESS"}]
            h.save_state()

            h.run_idd("config", "auto-merge", "on", "-g", extra_env=fast_env)
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json", extra_env=fast_env).stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "导出 CSV", "done")
            (wt / "export.py").write_text("csv_ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 导出 CSV"], check=True, capture_output=True)

            # Dry-run previews Auto-Merge status without pushing/merging
            dry_out = h.run_idd("pr", cwd=wt, extra_env=fast_env, *("--dry-run",)).stdout if False else h.run_idd("pr", "--dry-run", cwd=wt, extra_env=fast_env).stdout
            self.assertIn("Auto-Merge: 开启（来源：全局配置）", dry_out)

            pr_res = h.run_idd("pr", cwd=wt, extra_env=fast_env)
            self.assertIn("已开启自动准入合入（来源：全局配置）", pr_res.stdout)
            self.assertIn("CI 检查通过（PASS），自动执行 Squash 直线合入", pr_res.stdout)
            self.assertIn("已通过 Squash Merge 直线合入 PR #10", pr_res.stdout)
            self.assertIn("已自动勾选 Issue #42 验收标准（1 项）", pr_res.stdout)
            self.assertTrue((h.repo / "export.py").is_file())
            self.assertFalse((h.repo / "TASK/42-export-csv").exists())
            final_state = h.load_state()
            self.assertEqual(final_state["prs"]["10"]["state"], "MERGED")
            self.assertIn("- [x] 支持导出 CSV", final_state["issues"]["42"]["body"])

        # Case 2: Repo with no remote CI (NONE) allows auto-merge
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["default_checks"] = []
            h.save_state()
            h.run_idd("config", "auto-merge", "on", extra_env=fast_env)
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json", extra_env=fast_env).stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "无 CI 仓库放行", "done")
            (wt / "no_ci.py").write_text("ok = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 无 CI 放行"], check=True, capture_output=True)

            pr_res = h.run_idd("pr", cwd=wt, extra_env=fast_env)
            self.assertIn("仓库未配置远端 CI（NONE），按本地测试通过放行", pr_res.stdout)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "MERGED")

    def test_pr_auto_merge_safety_guards_and_cli_overrides(self) -> None:
        fast_env = {
            "IDD_CI_GRACE_SECONDS": "0",
            "IDD_CI_POLL_INTERVAL": "0.01",
            "IDD_LAND_SYNC_INTERVAL": "0.01",
        }
        # Case 1: CI fails -> preserves TASK/, prints logs, exit code 3; fix & re-run pr succeeds
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.state["default_checks"] = [
                {
                    "name": "ci / pytest",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://github.com/acme/demo/actions/runs/888",
                }
            ]
            h.state["run_logs"]["888"] = "AssertionError: boom"
            h.save_state()
            h.run_idd("config", "auto-merge", "on", extra_env=fast_env)

            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json", extra_env=fast_env).stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "修复 CI", "done")
            (wt / "app.py").write_text("bad = True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 触发 CI 失败"], check=True, capture_output=True)

            fail_res = h.run_idd("pr", cwd=wt, check=False, extra_env=fast_env)
            self.assertEqual(fail_res.returncode, 3)
            self.assertIn("AssertionError: boom", fail_res.stderr)
            self.assertTrue((wt / "TASK/42-export-csv").is_dir(), "TASK/ must remain intact when CI fails")
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "OPEN")

            # Fix code, turn CI green, re-run `idd pr` -> updates PR and auto-lands
            h.state["default_checks"] = [{"name": "ci / pytest", "status": "COMPLETED", "conclusion": "SUCCESS"}]
            h.state["settled_checks"] = [{"name": "ci / pytest", "status": "COMPLETED", "conclusion": "SUCCESS"}]
            h.save_state()
            (wt / "app.py").write_text("bad = False\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "app.py"], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "fix: 修复 CI 失败"], check=True, capture_output=True)

            heal_res = h.run_idd("pr", cwd=wt, extra_env=fast_env)
            self.assertIn("已更新 PR #10", heal_res.stdout)
            self.assertIn("已通过 Squash Merge 直线合入 PR #10", heal_res.stdout)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "MERGED")

        # Case 2: evidence/ attachment blocks auto-merge safely (exit code 2); --no-auto-merge and --draft skip
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            h.run_idd("config", "auto-merge", "on", extra_env=fast_env)
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json", extra_env=fast_env).stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "附带证据", "done")
            ev_dir = wt / "TASK/42-export-csv/evidence/TASK-01"
            ev_dir.mkdir(parents=True)
            (ev_dir / "trace.txt").write_text("evidence", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 含证据文件"], check=True, capture_output=True)

            # --draft + --auto-merge rejected
            conflict_flags = h.run_idd("pr", "--draft", "--auto-merge", cwd=wt, check=False, extra_env=fast_env)
            self.assertNotEqual(conflict_flags.returncode, 0)

            # --draft skips config-enabled auto_merge
            draft_res = h.run_idd("pr", "--draft", cwd=wt, extra_env=fast_env)
            self.assertIn("跳过自动准入与合入", draft_res.stdout)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "OPEN")

            # --no-auto-merge skips config-enabled auto_merge
            no_am_res = h.run_idd("pr", "--no-auto-merge", cwd=wt, extra_env=fast_env)
            self.assertIn("已更新 PR #10", no_am_res.stdout)
            self.assertNotIn("已开启自动准入合入", no_am_res.stdout)

            # With auto_merge active, evidence/ pauses with exit code 2
            ev_res = h.run_idd("pr", cwd=wt, check=False, extra_env=fast_env)
            self.assertEqual(ev_res.returncode, 2)
            self.assertIn("evidence", ev_res.stderr)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "OPEN")

        # Case 3: Default off + explicit `idd pr --auto-merge`, and `idd land --wait-ci`
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json", extra_env=fast_env).stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "临时开启", "done")
            (wt / "feat.py").write_text("ok = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 临时参数合入"], check=True, capture_output=True)

            # Without --auto-merge (default off), PR stays open
            h.run_idd("pr", cwd=wt, extra_env=fast_env)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "OPEN")

            # Explicit `idd land --wait-ci` waits for cleanup commit CI and lands
            h.load_state()
            h.state["cleanup_pending_polls"] = 2
            h.state["settled_checks"] = [{"name": "ci / test", "status": "COMPLETED", "conclusion": "SUCCESS"}]
            h.save_state()
            land_res = h.run_idd("land", "42", "--wait-ci", extra_env=fast_env)
            self.assertIn("已通过 Squash Merge 直线合入 PR #10", land_res.stdout)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "MERGED")

        # Case 4: Default off + explicit `idd pr --auto-merge`
        with tempfile.TemporaryDirectory() as tmp:
            h = GitHubHarness(Path(tmp))
            wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json", extra_env=fast_env).stdout)["worktree"])
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
            self._write_task(wt, "42-export-csv", 1, "CLI 覆盖开启", "done")
            (wt / "cli_override.py").write_text("ok = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-m", "feat: 命令行 --auto-merge 合入"], check=True, capture_output=True)

            pr_override = h.run_idd("pr", "--auto-merge", cwd=wt, extra_env=fast_env)
            self.assertIn("已开启自动准入合入（来源：命令行 --auto-merge）", pr_override.stdout)
            self.assertIn("已通过 Squash Merge 直线合入 PR #10", pr_override.stdout)
            self.assertEqual(h.load_state()["prs"]["10"]["state"], "MERGED")

    def test_build_issue_summary_markdown_and_test_formatting(self) -> None:
        self.assertEqual(
            idd_cli._format_test_summary_line("uv run --offline --locked --extra dev python -m pytest -o addopts='' -q tests/ — 95 passed"),
            "- **Test:** `pytest tests/` — 95 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("uv run pytest tests/ — 4505 passed, 11 skipped; tests/packaging/ — 3 passed"),
            "**Test:**\n\n- `pytest tests/` — 4505 passed, 11 skipped\n- `tests/packaging/` — 3 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line(
                "uv run --offline --locked --extra dev python -m pytest -o addopts='' -q "
                "tests/integrations/test_wecom_rendering.py tests/integrations/test_wecom.py "
                "tests/integrations/test_wecom_connection.py tests/integrations/test_wecom_group_names.py "
                "tests/integrations/test_wecom_relay.py tests/review/test_notifications.py "
                "tests/architecture/test_dependencies.py — 379 passed; compileall/alembic/diff-check passed"
            ),
            "**Test:**\n\n- `pytest`（7 个测试文件） — 379 passed\n- `compileall/alembic/diff-check` — passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line(
                "corepack pnpm test --maxWorkers=2 — 93 files, 1219 passed; "
                "corepack pnpm typecheck — 0 errors; "
                "corepack pnpm test:architecture — 4 passed"
            ),
            "**Test:**\n\n- `pnpm test` — 93 files, 1219 passed\n- `pnpm typecheck` — 0 errors\n- `pnpm test:architecture` — 4 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v — 23 passed"),
            "- **Test:** `unittest test_monitor_and_board` — 23 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("python3 -m unittest discover -s tests -v — 89 passed"),
            "- **Test:** `unittest tests` — 89 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("cmd1; cmd2 — 10 passed"),
            "- **Test:** `cmd1; cmd2` — 10 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("`pytest tests/test_a.py` — 4 passed"),
            "- **Test:** `pytest tests/test_a.py` — 4 passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("echo `ok` — passed"),
            "- **Test:** `` echo `ok` `` — passed",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("未记录"),
            "- **Test:** 未记录",
        )
        self.assertEqual(
            idd_cli._format_test_summary_line("未在提交中记录"),
            "- **Test:** 未在提交中记录",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            (repo / "README.md").write_text("init\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: init"], check=True, capture_output=True)

            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat/6-review"], check=True, capture_output=True)
            task_dir = repo / "TASK" / "6-review"
            task_dir.mkdir(parents=True)
            (task_dir / "TASK-01-context.md").write_text(
                "# TASK-01：扩展独立复核上下文\n\n"
                "- Issue: #6\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                encoding="utf-8",
            )
            (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            commit_msg_1 = (
                "feat(review): 扩展独立复核上下文\n\n"
                "第一段说明包含上下文细节。\n\n"
                "第二段列出关键点：\n"
                "- 含文件头与扩展窗口\n"
                "- 零 I/O 关联符号变更\n\n"
                "Task: 6-review/TASK-01\n"
                "Refs: #6\n"
                "Test: uv run --offline --locked -q tests/review/ — 95 passed"
            )
            subprocess.run(["git", "-C", str(repo), "commit", "-m", commit_msg_1], check=True, capture_output=True)

            # Single TASK with issue_title=None must not leak '###' or 'TASK-01' into suggested_title
            single_title, single_pr_body, single_commit_body = idd_cli.build_issue_summaries(
                repo, "6-review", 6, "main", issue_title=None
            )
            self.assertEqual(single_title, "feat: 扩展独立复核上下文 (#6)")
            self.assertNotIn("###", single_title)
            self.assertNotIn("TASK-01", single_title)
            expected_single_pr = (
                "Closes #6\n\n"
                "## 变更内容\n\n"
                "- **TASK-01** 扩展独立复核上下文\n\n"
                "  第一段说明包含上下文细节。\n\n"
                "  第二段列出关键点：\n"
                "  - 含文件头与扩展窗口\n"
                "  - 零 I/O 关联符号变更\n\n"
                "## 验证记录\n\n"
                "| 任务 | 验证项 | 结果 |\n"
                "| --- | --- | --- |\n"
                "| TASK-01 | `tests/review/` | 95 passed |\n\n"
                "<details>\n"
                "<summary>完整验证命令</summary>\n\n"
                "- **TASK-01:** `uv run --offline --locked -q tests/review/`\n\n"
                "</details>\n"
            )
            self.assertEqual(single_pr_body, expected_single_pr)
            expected_single_commit = (
                "Closes #6\n\n"
                "TASK-01: 扩展独立复核上下文\n\n"
                "第一段说明包含上下文细节。\n\n"
                "第二段列出关键点：\n"
                "- 含文件头与扩展窗口\n"
                "- 零 I/O 关联符号变更\n\n"
                "Test: tests/review/ — 95 passed\n"
            )
            self.assertEqual(single_commit_body, expected_single_commit)
            self.assertNotIn("###", single_commit_body)
            self.assertNotIn("**", single_commit_body)
            self.assertNotIn("<details>", single_commit_body)

            # Second TASK with multiple Test: lines should accumulate and avoid <details> when not simplified
            (task_dir / "TASK-02-docs.md").write_text(
                "# TASK-02：同步文档\n\n"
                "- Issue: #6\n- Status: done\n- Depends on: TASK-01\n- Test: pytest\n",
                encoding="utf-8",
            )
            (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(repo), "commit", "-m",
                    "docs: 同步文档\n\nTask: 6-review/TASK-02\nRefs: #6\n"
                    "Test: pytest tests/a.py — 10 passed\n"
                    "Test: pytest tests/b.py — 3 passed",
                ],
                check=True,
                capture_output=True,
            )
            _, multi_pr_body, multi_commit_body = idd_cli.build_issue_summaries(
                repo, "6-review", 6, "main", issue_title="fix(review): 收敛噪音"
            )
            self.assertIn(
                "- **TASK-02** 同步文档\n\n## 验证记录",
                multi_pr_body,
            )
            self.assertIn(
                "| TASK-02 | `pytest tests/a.py` | 10 passed |\n"
                "|  | `pytest tests/b.py` | 3 passed |\n",
                multi_pr_body,
            )
            self.assertIn(
                "TASK-02: 同步文档\nTest:\n- pytest tests/a.py — 10 passed\n- pytest tests/b.py — 3 passed\n",
                multi_commit_body,
            )

            # Short unsimplified commands must not produce a redundant <details> block
            (task_dir / "TASK-01-context.md").unlink()
            (repo / "c.py").write_text("z = 3\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(repo), "commit", "-m",
                    "docs: 精简验证\n\nTask: 6-review/TASK-02\nRefs: #6\nTest: pytest tests/b.py — 3 passed",
                ],
                check=True,
                capture_output=True,
            )
            _, short_pr_body, short_commit_body = idd_cli.build_issue_summaries(
                repo, "6-review", 6, "main", issue_title="docs: 精简验证"
            )
            self.assertNotIn("<details>", short_pr_body)
            self.assertEqual(
                short_commit_body,
                "Closes #6\n\nTASK-02: 精简验证\nTest: pytest tests/b.py — 3 passed\n",
            )

    def test_pr_summary_table_regression_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            (repo / "README.md").write_text("init\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: init"], check=True, capture_output=True)

            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat/19-ai-status"], check=True, capture_output=True)
            task_dir = repo / "TASK" / "19-ai-status"
            task_dir.mkdir(parents=True)

            # 1. Compound command with 3 files + semicolons inside result parentheses
            (task_dir / "TASK-01-a.md").write_text(
                "# TASK-01：顶栏 AI 状态休眠态与动效\n\n- Issue: #19\n- Status: done\n- Depends on: none\n- Test: pnpm\n",
                encoding="utf-8",
            )
            (repo / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(repo), "commit", "-m",
                    "feat(console): 顶栏 AI 状态休眠态与动效\n\n"
                    "Task: 19-ai-status/TASK-01\n"
                    "Refs: #19\n"
                    "Test: pnpm test a.test.ts b.test.ts c.test.ts && pnpm test:architecture — passed (3 files / 16 tests; architecture 4 passed)",
                ],
                check=True,
                capture_output=True,
            )

            # 2. Long deep single file path should be shortened to basename + kept in <details>
            (task_dir / "TASK-02-b.md").write_text(
                "# TASK-02：管理视角全局总闸面板\n\n- Issue: #19\n- Status: done\n- Depends on: TASK-01\n- Test: pnpm\n",
                encoding="utf-8",
            )
            (repo / "b.ts").write_text("export const b = 2;\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(repo), "commit", "-m",
                    "feat(console): 管理视角全局总闸面板\n\n"
                    "Task: 19-ai-status/TASK-02\n"
                    "Refs: #19\n"
                    "Test: pnpm test apps/console/src/modules/projects/components/PlatformGlobalControls.test.ts && pnpm test:architecture — passed (1 file / 3 tests; architecture 4 passed)",
                ],
                check=True,
                capture_output=True,
            )

            # 3. Backtick-wrapped command followed by parenthetical note + pipe char in another check
            (task_dir / "TASK-03-c.md").write_text(
                "# TASK-03：全站文案同步与全量验收\n\n- Issue: #19\n- Status: done\n- Depends on: TASK-02\n- Test: pnpm\n",
                encoding="utf-8",
            )
            (repo / "c.ts").write_text("export const c = 3;\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(repo), "commit", "-m",
                    "feat(console): 全站文案同步与全量验收\n\n"
                    "Task: 19-ai-status/TASK-03\n"
                    "Refs: #19\n"
                    "Test: `pnpm typecheck && pnpm test:runtime && pnpm test:architecture` (CI 3 项检查) — passed (typecheck 0 errors; runtime 71 passed; architecture 4 passed)\n"
                    "Test: grep -E \"foo|bar\" README.md — passed (ok | verified)",
                ],
                check=True,
                capture_output=True,
            )

            # 4. Unrecorded check
            (task_dir / "TASK-04-d.md").write_text(
                "# TASK-04：补充说明文档\n\n- Issue: #19\n- Status: done\n- Depends on: TASK-03\n- Test: 未记录\n",
                encoding="utf-8",
            )
            (repo / "d.ts").write_text("export const d = 4;\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(repo), "commit", "-m",
                    "docs: 补充说明文档\n\nTask: 19-ai-status/TASK-04\nRefs: #19",
                ],
                check=True,
                capture_output=True,
            )

            _, pr_body, commit_body = idd_cli.build_issue_summaries(
                repo, "19-ai-status", 19, "main", issue_title="feat(console): 顶栏与总闸优化"
            )
            self.assertNotIn("### TASK-", pr_body)
            self.assertIn(
                "## 变更内容\n\n"
                "- **TASK-01** 顶栏 AI 状态休眠态与动效\n"
                "- **TASK-02** 管理视角全局总闸面板\n"
                "- **TASK-03** 全站文案同步与全量验收\n"
                "- **TASK-04** 补充说明文档\n",
                pr_body,
            )
            self.assertIn(
                "| TASK-01 | `pnpm test`（3 个测试文件）、`pnpm test:architecture` | passed (3 files / 16 tests; architecture 4 passed) |",
                pr_body,
            )
            self.assertIn(
                "| TASK-02 | `pnpm test`（`PlatformGlobalControls.test.ts`）、`pnpm test:architecture` | passed (1 file / 3 tests; architecture 4 passed) |",
                pr_body,
            )
            self.assertIn(
                "| TASK-03 | `pnpm typecheck`、`pnpm test:runtime`、`pnpm test:architecture`（CI 3 项检查） | passed (typecheck 0 errors; runtime 71 passed; architecture 4 passed) |",
                pr_body,
            )
            self.assertIn(
                r'|  | `grep -E "foo\|bar" README.md` | passed (ok \| verified) |',
                pr_body,
            )
            self.assertIn("| TASK-04 | — | 未记录 |", pr_body)
            self.assertNotIn("``", pr_body)
            self.assertNotIn("(3 个测试目标)", pr_body)
            self.assertIn(
                "- **TASK-01:** `pnpm test a.test.ts b.test.ts c.test.ts && pnpm test:architecture`",
                pr_body,
            )
            self.assertIn(
                "- **TASK-02:** `pnpm test apps/console/src/modules/projects/components/PlatformGlobalControls.test.ts && pnpm test:architecture`",
                pr_body,
            )
            self.assertNotIn("- **TASK-03:**", pr_body)

            # Squash commit body remains zero-Markdown plain text
            self.assertNotIn("## ", commit_body)
            self.assertNotIn("| 任务 |", commit_body)
            self.assertNotIn("**TASK-", commit_body)
            self.assertNotIn("`", commit_body)
            self.assertNotIn("<details>", commit_body)
            self.assertIn(
                "- pnpm typecheck && pnpm test:runtime && pnpm test:architecture (CI 3 项检查) — passed (typecheck 0 errors; runtime 71 passed; architecture 4 passed)",
                commit_body,
            )

    def test_land_blocks_unfinished_tasks_and_allows_force_or_terminal_states(self) -> None:
        # 1. planned / in_progress / blocked block `idd land` (including `--dry-run`) unless `--force-unfinished-tasks`
        for status_val in ("in_progress", "planned", "blocked"):
            with self.subTest(status=status_val), tempfile.TemporaryDirectory() as tmp:
                h = GitHubHarness(Path(tmp))
                wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
                subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
                subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
                tdir = wt / "TASK/42-export-csv"
                tdir.mkdir(parents=True)
                (tdir / "TASK-01-impl.md").write_text(
                    "# TASK-01：实现接口\n\n- Issue: #42\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                    encoding="utf-8",
                )
                (tdir / "TASK-02-extra.md").write_text(
                    f"# TASK-02：补齐配图\n\n- Issue: #42\n- Status: {status_val}\n- Depends on: TASK-01\n- Test: pytest\n",
                    encoding="utf-8",
                )
                (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
                subprocess.run(
                    ["git", "-C", str(wt), "commit", "-m", "feat: 实现接口\n\nTask: 42-export-csv/TASK-01\nRefs: #42"],
                    check=True,
                    capture_output=True,
                )
                h.run_idd("pr", "42")

                dry_blocked = h.run_idd("land", "42", "--dry-run", check=False)
                self.assertEqual(dry_blocked.returncode, 2)
                self.assertIn("TASK-02", dry_blocked.stderr)
                self.assertIn(status_val, dry_blocked.stderr)
                self.assertIn("--force-unfinished-tasks", dry_blocked.stderr)

                land_blocked = h.run_idd("land", "42", check=False)
                self.assertEqual(land_blocked.returncode, 2)
                self.assertEqual(h.load_state()["issues"]["42"]["state"], "OPEN")

                if status_val == "in_progress":
                    # Auto-merge PR must also stop at the unfinished TASK guard
                    am_res = h.run_idd("pr", "42", "--auto-merge", check=False)
                    self.assertEqual(am_res.returncode, 2)
                    self.assertIn("--force-unfinished-tasks", am_res.stderr)
                    self.assertEqual(h.load_state()["issues"]["42"]["state"], "OPEN")

                    forced = h.run_idd("land", "42", "--force-unfinished-tasks")
                    self.assertIn("Squash Merge 直线合入", forced.stdout)
                    self.assertEqual(h.load_state()["issues"]["42"]["state"], "CLOSED")

        # 2. cancelled / deferred tasks are terminal decisions and should land without --force-unfinished-tasks
        for term_status in ("cancelled", "deferred"):
            with self.subTest(terminal_status=term_status), tempfile.TemporaryDirectory() as tmp:
                h = GitHubHarness(Path(tmp))
                wt = Path(json.loads(h.run_idd("start", "42", "--slug", "export-csv", "--json").stdout)["worktree"])
                subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
                subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
                tdir = wt / "TASK/42-export-csv"
                tdir.mkdir(parents=True)
                (tdir / "TASK-01-impl.md").write_text(
                    "# TASK-01：实现接口\n\n- Issue: #42\n- Status: done\n- Depends on: none\n- Test: pytest\n",
                    encoding="utf-8",
                )
                (tdir / "TASK-02-skip.md").write_text(
                    f"# TASK-02：可选项\n\n- Issue: #42\n- Status: {term_status}\n- Depends on: TASK-01\n- Test: pytest\n",
                    encoding="utf-8",
                )
                (wt / "export.py").write_text("ok = True\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
                subprocess.run(
                    ["git", "-C", str(wt), "commit", "-m", "feat: 实现接口\n\nTask: 42-export-csv/TASK-01\nRefs: #42"],
                    check=True,
                    capture_output=True,
                )
                h.run_idd("pr", "42")
                land_ok = h.run_idd("land", "42")
                self.assertIn("Squash Merge 直线合入", land_ok.stdout)
                self.assertEqual(h.load_state()["issues"]["42"]["state"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
