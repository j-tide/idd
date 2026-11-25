#!/usr/bin/env python3
"""Issue-Driven Development (IDD) shared CLI across Claude Code, Codex, and Antigravity."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import task_status  # noqa: E402


__version__ = "0.3.0"
AUTO_UPDATE_INTERVAL_SECONDS = 6 * 3600

ALLOWED_TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "ci", "chore")
ISSUE_BRANCH_RE = re.compile(r"^(feat|fix|refactor|perf|docs|test|ci|chore)/(\d+)-[a-z0-9]+(?:-[a-z0-9]+)*$")
LOCAL_BRANCH_RE = re.compile(r"^(feat|fix|refactor|perf|docs|test|ci|chore)/[a-z0-9]+(?:-[a-z0-9]+)*$")
FORBIDDEN_PREFIXES = {
    "codex",
    "claude",
    "agy",
    "antigravity",
    "cursor",
    "copilot",
    "ai",
    "feature",
    "bugfix",
    "hotfix",
    "tmp",
    "temp",
    "wip",
    "dev",
}

PROGRESS_START = "<!-- idd:progress:start -->"
PROGRESS_END = "<!-- idd:progress:end -->"
PROGRESS_RE = re.compile(
    re.escape(PROGRESS_START) + r".*?" + re.escape(PROGRESS_END),
    re.DOTALL,
)
FAIL_CONCLUSIONS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
PASS_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}


class IddError(Exception):
    """Expected CLI error carrying an explicit exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class RepoInfo:
    """Resolved Git repository and worktree layout."""

    main_worktree: Path
    current_worktree: Path
    current_branch: str
    default_branch: str
    worktree_root: Path
    has_origin: bool


def run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing UTF-8 output; raise IddError on failure when check=True."""
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            input=input_text,
        )
    except FileNotFoundError as exc:
        raise IddError(f"找不到可执行文件 `{args[0]}`，请确认已安装并在 PATH 中。") from exc
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}"
        raise IddError(f"命令 `{' '.join(args)}` 执行失败：{detail}")
    return proc


def run_gh_json(args: list[str], *, cwd: Path, check: bool = True) -> Any:
    """Invoke `gh` returning parsed JSON."""
    proc = run_cmd(["gh", *args], cwd=cwd, check=check)
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IddError(f"无法解析 gh 输出的 JSON：{exc}") from exc


@contextmanager
def temp_markdown_file(content: str) -> Iterator[Path]:
    """Write content to a temporary UTF-8 file and remove it on exit."""
    fd, raw_path = tempfile.mkstemp(prefix="idd-", suffix=".md")
    path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        yield path
    finally:
        path.unlink(missing_ok=True)


def parse_issue_ref(ref: str) -> int | None:
    """Parse an integer issue or PR reference from '42', '#42', or a GitHub URL."""
    cleaned = ref.strip()
    if not cleaned:
        return None
    match = re.fullmatch(r"#?(\d+)", cleaned)
    if match:
        return int(match.group(1))
    url_match = re.search(r"/(?:issues|pull)/(\d+)(?:[/?#].*)?$", cleaned)
    if url_match:
        return int(url_match.group(1))
    return None


def slugify(text: str, fallback: str) -> str:
    """Convert text to lowercase ASCII kebab-case (max 40 chars), returning fallback if empty."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > 40:
        slug = slug[:40].strip("-")
    return slug or fallback


def _suggest_branch_name(branch: str, issue_number: int | None = None) -> str:
    """Compute a valid `<type>/<issue#>-<slug>` or `<type>/<slug>` suggestion for a bad branch name."""
    prefix_map = {
        "feature": "feat",
        "bugfix": "fix",
        "hotfix": "fix",
        "bug": "fix",
    }
    if "/" in branch:
        raw_prefix, raw_tail = branch.split("/", 1)
        raw_prefix_l = raw_prefix.lower()
        suggested_type = prefix_map.get(raw_prefix_l, raw_prefix_l if raw_prefix_l in ALLOWED_TYPES else "feat")
    else:
        raw_tail = branch
        suggested_type = "feat"

    if issue_number is not None:
        tail_no_num = re.sub(rf"^{issue_number}(?:-|$)", "", raw_tail)
        clean_slug = slugify(tail_no_num, "task")
        return f"{suggested_type}/{issue_number}-{clean_slug}"
    clean_slug = slugify(raw_tail, "task")
    return f"{suggested_type}/{clean_slug}"


def validate_branch_name(
    branch: str,
    issue_number: int | None = None,
    worktree: Path | None = None,
) -> None:
    """Enforce 8-type branch naming and reject tool/alias prefixes without modifying Git hooks."""
    if not branch or branch == "(detached)":
        raise IddError("当前处于游离 HEAD（detached），请先切换到规范分支（如 `feat/<issue#>-<slug>`）。")

    prefix_part = branch.split("/", 1)[0].lower() if "/" in branch else ""
    if prefix_part in FORBIDDEN_PREFIXES:
        reason = f"禁止使用 `{prefix_part}/` 前缀"
    elif issue_number is not None:
        m = ISSUE_BRANCH_RE.fullmatch(branch)
        if m and int(m.group(2)) == issue_number:
            return
        reason = f"绑定 Issue #{issue_number} 的分支须匹配 `<type>/{issue_number}-<slug>`"
    else:
        if LOCAL_BRANCH_RE.fullmatch(branch):
            return
        reason = "分支须匹配 `<type>/<slug>`（kebab-case 小写字母数字）"

    suggested = _suggest_branch_name(branch, issue_number)
    rename_cmd = f"git -C {worktree} branch -m {branch} {suggested}" if worktree else f"git branch -m {branch} {suggested}"
    allowed_str = " | ".join(ALLOWED_TYPES)
    raise IddError(
        f"分支名 `{branch}` 不符合 IDD 规范（{reason}）。\n"
        f"允许的分支前缀：{allowed_str}\n"
        f"请先重命名分支再继续：{rename_cmd}"
    )


def get_repo_info(cwd: Path) -> RepoInfo:
    """Resolve main/current worktrees, branches, origin presence, and managed worktree root."""
    try:
        worktrees = task_status.list_git_worktrees(cwd)
    except ValueError as exc:
        raise IddError(str(exc)) from exc
    if not worktrees:
        raise IddError(f"无法解析 Git 工作树信息：{cwd}")

    main_worktree = Path(worktrees[0]["path"]).resolve()
    top_proc = run_cmd(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"])
    current_worktree = Path(top_proc.stdout.strip()).resolve()

    branch_proc = run_cmd(["git", "-C", str(current_worktree), "branch", "--show-current"], check=False)
    current_branch = branch_proc.stdout.strip() or "(detached)"

    remotes_proc = run_cmd(["git", "-C", str(main_worktree), "remote"])
    remotes = {line.strip() for line in remotes_proc.stdout.splitlines() if line.strip()}
    has_origin = "origin" in remotes

    default_branch = _detect_default_branch(main_worktree, has_origin)
    env_root = os.environ.get("IDD_WORKTREE_ROOT", "").strip()
    if env_root:
        worktree_root = Path(env_root).expanduser().resolve()
    else:
        worktree_root = main_worktree.parent / f"{main_worktree.name}-worktrees"

    return RepoInfo(
        main_worktree=main_worktree,
        current_worktree=current_worktree,
        current_branch=current_branch,
        default_branch=default_branch,
        worktree_root=worktree_root,
        has_origin=has_origin,
    )


def _detect_default_branch(main_worktree: Path, has_origin: bool) -> str:
    if has_origin:
        sym = run_cmd(
            ["git", "-C", str(main_worktree), "symbolic-ref", "refs/remotes/origin/HEAD"],
            check=False,
        )
        if sym.returncode == 0 and sym.stdout.strip():
            ref = sym.stdout.strip()
            if ref.startswith("refs/remotes/origin/"):
                return ref[len("refs/remotes/origin/"):]
    for candidate in ("main", "master"):
        if _ref_exists(main_worktree, f"refs/heads/{candidate}") or (
            has_origin and _ref_exists(main_worktree, f"refs/remotes/origin/{candidate}")
        ):
            return candidate
    return "main"


def _ref_exists(repo_dir: Path, ref: str) -> bool:
    proc = run_cmd(["git", "-C", str(repo_dir), "show-ref", "--verify", "--quiet", ref], check=False)
    return proc.returncode == 0


def _resolve_base_ref(repo: RepoInfo, base_branch: str | None = None) -> str:
    branch = base_branch or repo.default_branch
    if repo.has_origin and _ref_exists(repo.main_worktree, f"refs/remotes/origin/{branch}"):
        return f"origin/{branch}"
    return branch


def find_worktree_for_target(main_worktree: Path, target: str) -> dict[str, str] | None:
    """Locate an existing worktree matching an issue number or goal slug."""
    worktrees = task_status.list_git_worktrees(main_worktree)
    issue_num = parse_issue_ref(target)
    main_resolved = main_worktree.resolve()

    for wt in worktrees:
        wt_path = Path(wt["path"]).resolve()
        branch = wt.get("branch", "")
        task_dir = wt_path / "TASK"
        is_main = wt_path == main_resolved

        if issue_num is not None:
            num_str = str(issue_num)
            branch_hit = bool(re.search(rf"(?:^|/){num_str}(?:-|$)", branch))
            dir_hit = (not is_main) and (wt_path.name == num_str or wt_path.name.startswith(f"{num_str}-"))
            task_hit = task_dir.is_dir() and any(
                d.is_dir() and (d.name == num_str or d.name.startswith(f"{num_str}-"))
                for d in task_dir.iterdir()
            )
            if branch_hit or dir_hit or task_hit:
                return {"path": str(wt_path), "branch": branch}
        else:
            slug = target.strip()
            branch_hit = branch == slug or branch.endswith(f"/{slug}")
            dir_hit = (not is_main) and wt_path.name == slug
            task_hit = (task_dir / slug).is_dir()
            if branch_hit or dir_hit or task_hit:
                return {"path": str(wt_path), "branch": branch}
    return None


def sync_worktree_includes(main_worktree: Path, target_worktree: Path) -> list[str]:
    """Copy gitignored files listed in `.worktreeinclude` from main_worktree to target_worktree."""
    include_file = main_worktree / ".worktreeinclude"
    if not include_file.is_file():
        return []

    copied: list[str] = []
    seen: set[str] = set()
    for raw_line in include_file.read_text(encoding="utf-8").splitlines():
        pattern = raw_line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        pattern = pattern.lstrip("/")
        for match in sorted(main_worktree.glob(pattern)):
            rel = match.relative_to(main_worktree)
            if ".git" in rel.parts:
                continue
            if match.is_file():
                _copy_relative_file(main_worktree, target_worktree, rel, copied, seen)
            elif match.is_dir():
                for child in sorted(match.rglob("*")):
                    if not child.is_file():
                        continue
                    child_rel = child.relative_to(main_worktree)
                    if ".git" in child_rel.parts:
                        continue
                    _copy_relative_file(main_worktree, target_worktree, child_rel, copied, seen)
    return copied


def _copy_relative_file(
    src_root: Path,
    dst_root: Path,
    rel: Path,
    copied: list[str],
    seen: set[str],
) -> None:
    rel_str = rel.as_posix()
    if rel_str in seen:
        return
    dst = dst_root / rel
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / rel, dst)
    seen.add(rel_str)
    copied.append(rel_str)


def _infer_goal_and_issue(
    worktree: Path,
    branch: str,
    target: str | None = None,
) -> tuple[str | None, int | None]:
    """Determine (goal_name, issue_number) for a given worktree and optional user target."""
    issue_num = parse_issue_ref(target) if target else None
    if issue_num is None:
        branch_match = re.search(r"(?:^|/)(\d+)(?:-|$)", branch)
        if branch_match:
            issue_num = int(branch_match.group(1))

    task_root = worktree / "TASK"
    goal_name: str | None = None
    if task_root.is_dir():
        dirs = sorted(d.name for d in task_root.iterdir() if d.is_dir() and not d.name.startswith("."))
        if target and not parse_issue_ref(target) and target in dirs:
            goal_name = target
        elif issue_num is not None:
            for d in dirs:
                if d == str(issue_num) or d.startswith(f"{issue_num}-"):
                    goal_name = d
                    break
        if goal_name is None:
            branch_tail = branch.split("/", 1)[-1] if "/" in branch else branch
            if branch_tail in dirs:
                goal_name = branch_tail
            elif len(dirs) == 1:
                goal_name = dirs[0]

    if goal_name is None:
        if target and not parse_issue_ref(target):
            goal_name = target
        elif "/" in branch and branch != "(detached)":
            goal_name = branch.split("/", 1)[-1]
        else:
            goal_name = worktree.name

    if issue_num is None and goal_name:
        issue_num = task_status.parse_issue_number("", goal_name)
    return goal_name, issue_num


def _resolve_target_worktree(repo: RepoInfo, target: str | None) -> tuple[Path, str, str | None, int | None]:
    """Resolve (worktree_path, branch, goal_name, issue_number) from target or current worktree."""
    if target:
        found = find_worktree_for_target(repo.main_worktree, target)
        if not found:
            raise IddError(f"找不到匹配 `{target}` 的本地工作树，请先执行 `idd start {target}`。")
        wt_path = Path(found["path"]).resolve()
        branch = found.get("branch", "")
    else:
        wt_path = repo.current_worktree
        branch = repo.current_branch
        if wt_path == repo.main_worktree and branch == repo.default_branch:
            raise IddError(f"当前位于主线工作树 `{branch}` 上；请指定 Issue/目标名，或切换到对应工作树执行。")

    goal_name, issue_num = _infer_goal_and_issue(wt_path, branch, target)
    return wt_path, branch, goal_name, issue_num


def _parse_task_markdown_details(path: Path) -> dict[str, str]:
    """Extract fallback Test command/outcome info from a TASK markdown body."""
    info = {"command": "", "outcome": "", "notes": "", "latest_result": ""}
    if not path.is_file():
        return info
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- Command:") and not info["command"]:
            info["command"] = stripped[len("- Command:"):].strip()
        elif stripped.startswith("- Outcome:") and not info["outcome"]:
            info["outcome"] = stripped[len("- Outcome:"):].strip()
        elif stripped.startswith("- Notes:") and not info["notes"]:
            info["notes"] = stripped[len("- Notes:"):].strip()
        elif stripped.startswith("|") and "---" not in stripped and "日期 / 修订" not in stripped:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 3 and cells[1]:
                info["latest_result"] = f"{cells[1]} — {cells[2]}"
    return info


def _collect_commit_task_records(worktree: Path, goal_name: str, base_ref: str) -> list[dict[str, str]]:
    """Read git commits since merge-base and extract Task/Test metadata."""
    target_base = base_ref
    if not _ref_exists(worktree, base_ref if base_ref.startswith("refs/") else f"refs/remotes/{base_ref}") and not _ref_exists(worktree, f"refs/heads/{base_ref}"):
        # Fallback if exact ref string wasn't resolved above; try git rev-parse
        check_ref = run_cmd(["git", "-C", str(worktree), "rev-parse", "--verify", base_ref], check=False)
        if check_ref.returncode != 0:
            return []

    mb = run_cmd(["git", "-C", str(worktree), "merge-base", target_base, "HEAD"], check=False)
    if mb.returncode != 0 or not mb.stdout.strip():
        return []
    base_sha = mb.stdout.strip()
    log_proc = run_cmd(
        ["git", "-C", str(worktree), "log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{base_sha}..HEAD"],
        check=False,
    )
    if log_proc.returncode != 0:
        return []

    records: list[dict[str, str]] = []
    for raw_entry in log_proc.stdout.split("\x1e"):
        entry = raw_entry.strip("\n")
        if not entry.strip():
            continue
        parts = entry.split("\x1f")
        if len(parts) < 3:
            continue
        sha, subject, body = parts[0].strip(), parts[1].strip(), parts[2]
        commit_type = ""
        change_desc = subject
        type_match = re.match(r"^([a-z]+)(?:\([^)]+\))?:\s*(.+)$", subject)
        if type_match:
            commit_type, change_desc = type_match.group(1), type_match.group(2).strip()

        task_id = ""
        test_line = ""
        extra_lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if line.startswith("Task:"):
                val = line[len("Task:"):].strip()
                m = re.search(r"(TASK-\d+)", val)
                if m and (goal_name in val or val.startswith("TASK-")):
                    task_id = m.group(1)
            elif line.startswith("Test:"):
                test_line = line[len("Test:"):].strip()
            elif line.startswith(("Refs:", "Closes:", "Fixes:", "Co-authored-by:", "Signed-off-by:")):
                continue
            elif line:
                extra_lines.append(raw_line.rstrip())

        records.append(
            {
                "sha": sha,
                "type": commit_type,
                "subject": subject,
                "change": change_desc,
                "task_id": task_id,
                "test": test_line,
                "extra": "\n".join(extra_lines).strip(),
            }
        )
    return records


def build_goal_summary(
    worktree: Path,
    goal_name: str,
    issue_number: int | None,
    base_ref: str,
    issue_title: str | None = None,
) -> tuple[str, str]:
    """Generate (suggested_title, markdown_body) from TASK files and branch commits."""
    task_dir = worktree / "TASK" / goal_name
    tasks: list[dict[str, Any]] = []
    if task_dir.is_dir():
        for path in sorted(task_dir.glob("TASK-*.md")):
            if path.is_file() and re.match(r"^TASK-\d+(?:-|\.md)", path.name):
                parsed = task_status.read_task(path, worktree / "TASK")
                parsed["_details"] = _parse_task_markdown_details(path)
                tasks.append(parsed)

    commits = _collect_commit_task_records(worktree, goal_name, base_ref)
    commit_by_task: dict[str, dict[str, str]] = {}
    for rec in commits:
        if rec["task_id"]:
            commit_by_task[rec["task_id"]] = rec

    commit_types = [c["type"] for c in commits if c["type"] and c["type"] != "chore"]
    dominant_type = commit_types[0] if commit_types else "feat"

    blocks: list[str] = []
    if tasks:
        for task in tasks:
            tid = task["id"]
            commit_rec = commit_by_task.get(tid, {})
            details = task["_details"]
            raw_title = re.sub(rf"^{re.escape(tid)}[：:\s]+", "", task["title"]).strip()
            change = commit_rec.get("change") or raw_title or task["title"]
            test_text = (
                commit_rec.get("test")
                or details.get("latest_result")
                or (f"{details['command']} — {details['outcome']}" if details.get("command") else "")
                or (f"{task['test']} — {details['outcome'] or task['status']}" if task.get("test") else "未记录")
            )
            block_lines = [f"{tid} {change}"]
            if commit_rec.get("extra"):
                block_lines.append(commit_rec["extra"])
            block_lines.append(f"Test: {test_text}")
            blocks.append("\n".join(block_lines))
    elif commits:
        for idx, rec in enumerate(commits, start=1):
            if rec["subject"].startswith("chore: 清理已汇总的任务记录"):
                continue
            tid = rec["task_id"] or f"TASK-{idx:02d}"
            block_lines = [f"{tid} {rec['change']}"]
            if rec["extra"]:
                block_lines.append(rec["extra"])
            block_lines.append(f"Test: {rec['test'] or '未在提交中记录'}")
            blocks.append("\n".join(block_lines))

    if issue_title:
        suggested_title = f"{dominant_type}: {issue_title}"
    elif len(tasks) == 1:
        only_change = blocks[0].splitlines()[0].split(" ", 1)[1] if blocks else goal_name
        suggested_title = f"{dominant_type}: {only_change}"
    elif len(commits) == 1 and commits[0]["change"]:
        suggested_title = f"{dominant_type}: {commits[0]['change']}"
    else:
        suggested_title = f"{dominant_type}: 完成 {goal_name}"

    if issue_number is not None and f"(#{issue_number})" not in suggested_title:
        suggested_title = f"{suggested_title} (#{issue_number})"

    header_lines = [f"Goal: {goal_name}"]
    if issue_number is not None:
        header_lines.append(f"Closes #{issue_number}")

    body_parts = ["\n".join(header_lines)]
    if blocks:
        body_parts.extend(blocks)
    return suggested_title, "\n\n".join(body_parts) + "\n"


def build_progress_block(tasks: list[dict[str, Any]]) -> str:
    """Render an idempotent GitHub Issue checklist block from parsed TASK items."""
    lines = [PROGRESS_START, "## 执行进度（IDD 自动同步）"]
    for task in tasks:
        checked = "x" if task["status"] == "done" else " "
        note = "" if task["status"] in ("done", "planned") else f" *({task['status']})*"
        lines.append(f"- [{checked}] {task['title']}{note}")
    lines.append(PROGRESS_END)
    return "\n".join(lines)


def merge_progress_block(original_body: str, block: str) -> str:
    """Replace existing IDD progress block in Issue body, or append it cleanly."""
    if PROGRESS_START in original_body and PROGRESS_END in original_body:
        updated = PROGRESS_RE.sub(lambda _: block, original_body, count=1)
        return updated.rstrip() + "\n"
    stripped = original_body.rstrip()
    if not stripped:
        return block + "\n"
    return f"{stripped}\n\n{block}\n"


def _classify_pr_checks(pr: dict[str, Any]) -> tuple[str, list[dict[str, str]], list[str]]:
    """Classify statusCheckRollup into overall state, normalized check rows, and failed run IDs."""
    rollup = pr.get("statusCheckRollup") or []
    if not rollup:
        return "NONE", [], []

    checks: list[dict[str, str]] = []
    failed_runs: list[str] = []
    has_fail = False
    has_pending = False

    for item in rollup:
        name = item.get("name") or item.get("context") or "check"
        status = (item.get("status") or "").upper()
        conclusion = (item.get("conclusion") or item.get("state") or "").upper()
        url = item.get("detailsUrl") or item.get("targetUrl") or ""

        if conclusion in FAIL_CONCLUSIONS or conclusion == "ERROR":
            verdict = "FAIL"
            has_fail = True
            run_match = re.search(r"/actions/runs/(\d+)", url)
            if run_match and run_match.group(1) not in failed_runs:
                failed_runs.append(run_match.group(1))
        elif status and status != "COMPLETED" and not conclusion:
            verdict = "PENDING"
            has_pending = True
        elif conclusion in PASS_CONCLUSIONS or status == "COMPLETED":
            verdict = "PASS"
        elif conclusion == "PENDING" or not conclusion:
            verdict = "PENDING"
            has_pending = True
        else:
            verdict = conclusion

        checks.append({"name": name, "verdict": verdict, "url": url})

    if has_fail:
        overall = "FAIL"
    elif has_pending:
        overall = "PENDING"
    else:
        overall = "PASS"
    return overall, checks, failed_runs


def _format_ci_badge(overall: str, pr: dict[str, Any]) -> str:
    num = pr.get("number")
    prefix = f"PR #{num}" if num else "PR"
    if pr.get("isDraft"):
        prefix += " (Draft)"
    badges = {
        "PASS": "✅ CI 全绿",
        "FAIL": "❌ CI 失败",
        "PENDING": "⏳ CI 运行中",
        "NONE": "⚪ 无 CI",
    }
    state = pr.get("mergeStateStatus") or ""
    extra = " (落后/冲突)" if state in {"BEHIND", "DIRTY"} else ""
    return f"{prefix} · {badges.get(overall, overall)}{extra}"


def _resolve_pr_for_branch(cwd: Path, branch: str) -> dict[str, Any] | None:
    prs = run_gh_json(
        [
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--limit",
            "1",
            "--json",
            "number,title,url,state,baseRefName,headRefName,mergeStateStatus,isDraft,statusCheckRollup",
        ],
        cwd=cwd,
        check=False,
    )
    if isinstance(prs, list) and prs:
        return prs[0]
    return None


def _require_clean_worktree(worktree: Path) -> None:
    st = run_cmd(["git", "-C", str(worktree), "status", "--porcelain"])
    if st.stdout.strip():
        raise IddError(f"工作树 `{worktree}` 存在未提交改动，请先提交或暂存：\n{st.stdout.strip()}")


def _fetch_issue_optional(cwd: Path, issue_num: int | None) -> dict[str, Any] | None:
    if issue_num is None:
        return None
    data = run_gh_json(
        ["issue", "view", str(issue_num), "--json", "number,title,body,labels,state,url"],
        cwd=cwd,
        check=False,
    )
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    try:
        repo = get_repo_info(root)
        wt_data = task_status.collect_all_worktrees(repo.main_worktree, args.goal, args.open_only)
        scan_root = repo.main_worktree
    except IddError:
        task_root = root / "TASK"
        if not task_root.is_dir():
            raise IddError(f"当前路径既不是 Git 仓库，也不存在 TASK/ 目录：{root}")
        wt_data = task_status.collect(task_root, args.goal, args.open_only)
        repo = None
        scan_root = root

    warnings = list(wt_data.get("warnings", []))
    goals = wt_data.get("goals", [])

    open_issues: list[dict[str, Any]] = []
    open_prs: list[dict[str, Any]] = []
    gh_used = False

    if repo is not None and not args.local_only and not args.goal:
        if repo.has_origin and shutil.which("gh"):
            issues_res = run_gh_json(
                ["issue", "list", "--state", "open", "--limit", "100", "--json", "number,title,labels,url"],
                cwd=scan_root,
                check=False,
            )
            prs_res = run_gh_json(
                [
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--limit",
                    "100",
                    "--json",
                    "number,title,headRefName,url,statusCheckRollup,mergeStateStatus,isDraft",
                ],
                cwd=scan_root,
                check=False,
            )
            if isinstance(issues_res, list) and isinstance(prs_res, list):
                open_issues = issues_res
                open_prs = prs_res
                gh_used = True
            else:
                warnings.append("gh 查询不可用或当前仓库未配置 GitHub 远端，已降级为本地工作树视图。")

    goals_by_issue: dict[int, dict[str, Any]] = {}
    local_only_goals: list[dict[str, Any]] = []
    for g in goals:
        inum = g.get("issue_number")
        if inum is not None:
            goals_by_issue[inum] = g
        else:
            local_only_goals.append(g)

    prs_by_branch = {pr.get("headRefName", ""): pr for pr in open_prs}
    prs_by_issue: dict[int, dict[str, Any]] = {}
    for pr in open_prs:
        m = re.search(r"(?:^|/)(\d+)(?:-|$)", pr.get("headRefName", ""))
        if m:
            prs_by_issue[int(m.group(1))] = pr

    rows: list[dict[str, Any]] = []
    seen_issues: set[int] = set()

    for issue in open_issues:
        inum = issue["number"]
        seen_issues.add(inum)
        goal = goals_by_issue.get(inum)
        branch = goal.get("branch", "") if goal else ""
        pr = (prs_by_branch.get(branch) if branch else None) or prs_by_issue.get(inum)
        rows.append(_build_status_row(inum, issue.get("title", ""), issue.get("url", ""), goal, pr))

    for inum, goal in sorted(goals_by_issue.items()):
        if inum not in seen_issues:
            pr = prs_by_branch.get(goal.get("branch", "")) or prs_by_issue.get(inum)
            rows.append(_build_status_row(inum, goal["goal"], "", goal, pr))

    used_pr_numbers = {r["pr"]["number"] for r in rows if r.get("pr")}
    orphan_prs = [pr for pr in open_prs if pr.get("number") not in used_pr_numbers]

    payload = {
        "gh_connected": gh_used,
        "issues": rows,
        "local_only_goals": local_only_goals,
        "orphan_prs": orphan_prs,
        "goals": goals,
        "warnings": warnings,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines: list[str] = []
    if rows:
        lines.extend([
            "| Issue | 标题 | 阶段 | TASK 进度 | Worktree / 分支 | PR & CI 状态 |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for row in rows:
            wt_label = f"`{Path(row['worktree']).name}` ({row['branch']})" if row["worktree"] else "—"
            lines.append(
                f"| #{row['issue_number']} | {task_status.cell(row['title'])} | {row['stage']} | "
                f"{row['task_progress']} | {task_status.cell(wt_label)} | {task_status.cell(row['pr_summary'])} |"
            )

    if local_only_goals:
        if lines:
            lines.append("")
        lines.append("本地纯目标（未绑定 Issue）：")
        lines.append("")
        lines.append(task_status.render({"goals": local_only_goals, "warnings": []}))

    if orphan_prs:
        if lines:
            lines.append("")
        lines.append("其他未关联本地工作树的 Open PR：")
        for pr in orphan_prs:
            overall, _, _ = _classify_pr_checks(pr)
            lines.append(f"- PR #{pr['number']} `{pr.get('headRefName', '')}`: {pr.get('title', '')} — {_format_ci_badge(overall, pr)}")

    remaining = [(g, t) for g in goals for t in g.get("tasks", []) if t["status"] != "done"]
    if remaining:
        if lines:
            lines.append("")
        lines.append("未完成 TASK 明细：")
        for g, t in remaining:
            prefix = f"#{g['issue_number']} " if g.get("issue_number") is not None else ""
            lines.append(f"- {prefix}{g['goal']}/{t['id']} [{t['status']}] {t['title']}；依赖：{t['depends_on'] or '未记录'}")

    if not lines:
        lines.append("当前没有活跃的 Issue、本地 Worktree 任务或 Open PR。")

    if warnings:
        lines.extend(["", "提示 / 记录问题："])
        lines.extend(f"- {w}" for w in warnings)

    print("\n".join(lines))
    return 0


def _build_status_row(
    issue_number: int,
    title: str,
    url: str,
    goal: dict[str, Any] | None,
    pr: dict[str, Any] | None,
) -> dict[str, Any]:
    task_progress = f"{goal['done']} / {goal['total']}" if goal else "—"
    wt_path = goal.get("worktree", "") if goal else ""
    branch = goal.get("branch", "") if goal else (pr.get("headRefName", "") if pr else "")
    overall = "NONE"
    if pr:
        overall, _, _ = _classify_pr_checks(pr)

    if pr:
        if overall == "FAIL":
            stage = "🛠️ 修 CI"
        elif overall == "PENDING":
            stage = "⏳ CI 运行中"
        elif pr.get("isDraft"):
            stage = "📝 草稿 PR"
        else:
            stage = "🔵 待合入"
    elif goal:
        counts = goal["counts"]
        if counts.get("blocked", 0) > 0:
            stage = "⛔ 受阻"
        elif goal["total"] > 0 and goal["done"] == goal["total"]:
            stage = "🟢 待提 PR"
        else:
            stage = "🟡 开发中"
    else:
        stage = "⚪ 待认领"

    pr_summary = _format_ci_badge(overall, pr) if pr else "—"
    return {
        "issue_number": issue_number,
        "title": title,
        "url": url,
        "stage": stage,
        "task_progress": task_progress,
        "worktree": wt_path,
        "branch": branch,
        "pr": pr,
        "pr_summary": pr_summary,
    }


def cmd_issue_create(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    gh_args = ["gh", "issue", "create", "--title", args.title]
    if args.body_file:
        gh_args.extend(["--body-file", str(args.body_file)])
    elif args.body is not None:
        gh_args.extend(["--body", args.body])
    for label in args.label or []:
        gh_args.extend(["--label", label])
    for assignee in args.assignee or []:
        gh_args.extend(["--assignee", assignee])

    proc = run_cmd(gh_args, cwd=repo.main_worktree)
    url = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    number = parse_issue_ref(url)
    if args.json:
        print(json.dumps({"number": number, "url": url, "title": args.title}, ensure_ascii=False, indent=2))
    else:
        num_str = f"#{number} " if number is not None else ""
        print(f"已创建 Issue {num_str}: {url}")
    return 0


def _infer_prefix_from_labels(labels: set[str]) -> str:
    """Map GitHub issue labels to one of the 8 standard branch/commit types."""
    if labels & {"bug", "fix", "bugfix"}:
        return "fix"
    if "refactor" in labels:
        return "refactor"
    if labels & {"perf", "performance"}:
        return "perf"
    if labels & {"docs", "documentation"}:
        return "docs"
    if labels & {"test", "testing"}:
        return "test"
    if "ci" in labels:
        return "ci"
    if labels & {"chore", "dependencies"}:
        return "chore"
    return "feat"


def cmd_start(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    existing = find_worktree_for_target(repo.main_worktree, args.target)
    if existing:
        wt_path = Path(existing["path"])
        branch = existing.get("branch", "")
        goal_name, issue_num = _infer_goal_and_issue(wt_path, branch, args.target)
        validate_branch_name(branch, issue_num, wt_path)
        st = run_cmd(["git", "-C", str(wt_path), "status", "--short"], check=False).stdout.strip()
        log_out = run_cmd(["git", "-C", str(wt_path), "log", "-5", "--oneline"], check=False).stdout.strip()
        task_summary = None
        if (wt_path / "TASK").is_dir() and goal_name and (wt_path / "TASK" / goal_name).is_dir():
            task_summary = task_status.collect(wt_path / "TASK", goal_name, open_only=False)
        payload = {
            "reused": True,
            "worktree": str(wt_path),
            "branch": branch,
            "goal": goal_name,
            "issue_number": issue_num,
            "git_status": st,
            "recent_commits": log_out.splitlines() if log_out else [],
            "tasks": task_summary,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            lines = [
                f"复用已有工作树（支持跨工具无缝接手）：{wt_path}",
                f"分支：{branch}",
                f"目标目录：TASK/{goal_name}",
                f"工作区状态：{st or '干净'}",
            ]
            if log_out:
                lines.append("最近提交：")
                lines.extend(f"  {line}" for line in log_out.splitlines())
            if task_summary and task_summary["goals"]:
                lines.append("")
                lines.append(task_status.render(task_summary))
            print("\n".join(lines))
        return 0

    issue_num = parse_issue_ref(args.target)
    issue_data: dict[str, Any] | None = None
    if issue_num is not None:
        issue_data = run_gh_json(
            ["issue", "view", str(issue_num), "--json", "number,title,body,labels,state,url"],
            cwd=repo.main_worktree,
        )
        slug = slugify(args.slug, "") if args.slug else slugify(issue_data.get("title", ""), "task")
        goal_name = f"{issue_num}-{slug}"
        labels = {str(lbl.get("name", "")).lower() for lbl in issue_data.get("labels", [])}
        prefix = args.prefix or _infer_prefix_from_labels(labels)
        branch = f"{prefix}/{goal_name}"
    else:
        raw_target = args.target.strip()
        inferred_prefix: str | None = None
        if "/" in raw_target:
            raw_prefix, raw_rest = raw_target.split("/", 1)
            if raw_prefix.lower() not in ALLOWED_TYPES:
                validate_branch_name(raw_target)
            inferred_prefix = raw_prefix.lower()
            raw_target = raw_rest
        goal_name = slugify(args.slug or raw_target, "task")
        prefix = args.prefix or inferred_prefix or "feat"
        branch = f"{prefix}/{goal_name}"

    validate_branch_name(branch, issue_num)

    if repo.has_origin:
        run_cmd(["git", "-C", str(repo.main_worktree), "fetch", "origin", repo.default_branch], check=False)

    base_ref = _resolve_base_ref(repo, args.base)
    repo.worktree_root.mkdir(parents=True, exist_ok=True)
    wt_path = repo.worktree_root / goal_name

    if wt_path.exists():
        raise IddError(f"目标目录已存在但未注册为 Git 工作树：{wt_path}")

    if _ref_exists(repo.main_worktree, f"refs/heads/{branch}"):
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "add", str(wt_path), branch])
    elif repo.has_origin and _ref_exists(repo.main_worktree, f"refs/remotes/origin/{branch}"):
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "add", "-b", branch, str(wt_path), f"origin/{branch}"])
    else:
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "add", "-b", branch, str(wt_path), base_ref])

    copied = sync_worktree_includes(repo.main_worktree, wt_path)
    payload = {
        "reused": False,
        "worktree": str(wt_path),
        "branch": branch,
        "goal": goal_name,
        "issue_number": issue_num,
        "base_ref": base_ref,
        "copied_includes": copied,
        "issue": issue_data,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"已创建独立工作树：{wt_path}",
            f"分支：{branch} (基于 {base_ref})",
            f"TASK 目录建议：TASK/{goal_name}/",
        ]
        if copied:
            lines.append(f"已同步 .worktreeinclude 文件：{', '.join(copied)}")
        if issue_data:
            lines.append(f"关联 Issue：#{issue_data['number']} {issue_data.get('title', '')}")
            if issue_data.get("url"):
                lines.append(f"链接：{issue_data['url']}")
        print("\n".join(lines))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    repo = get_repo_info(root)

    if args.issue_number:
        issue_num = parse_issue_ref(args.issue_number)
        if issue_num is None:
            raise IddError(f"无效的 Issue 编号：{args.issue_number}")
        found = find_worktree_for_target(repo.main_worktree, str(issue_num))
        if found:
            wt_path = Path(found["path"]).resolve()
            branch = found.get("branch", "")
        else:
            wt_path = repo.current_worktree
            branch = repo.current_branch
        goal_name, _ = _infer_goal_and_issue(wt_path, branch, str(issue_num))
    else:
        wt_path = repo.current_worktree
        branch = repo.current_branch
        goal_name, issue_num = _infer_goal_and_issue(wt_path, branch)
        if issue_num is None:
            raise IddError("无法从当前工作树或分支推断 Issue 编号，请显式传入 Issue 编号。")

    validate_branch_name(branch, issue_num, wt_path)

    task_root = wt_path / "TASK"
    if not task_root.is_dir() or not goal_name or not (task_root / goal_name).is_dir():
        raise IddError(f"在工作树 `{wt_path}` 中找不到任务目录 `TASK/{goal_name}`。")

    collected = task_status.collect(task_root, goal_name, open_only=False)
    tasks = collected["goals"][0]["tasks"]
    block = build_progress_block(tasks)

    issue_data = run_gh_json(["issue", "view", str(issue_num), "--json", "body,title,url"], cwd=repo.main_worktree)
    merged_body = merge_progress_block(issue_data.get("body", ""), block)

    if args.dry_run:
        print(merged_body, end="")
        return 0

    with temp_markdown_file(merged_body) as body_file:
        run_cmd(["gh", "issue", "edit", str(issue_num), "--body-file", str(body_file)], cwd=repo.main_worktree)

    done_count = collected["goals"][0]["done"]
    total_count = collected["goals"][0]["total"]
    print(f"已同步 Issue #{issue_num} 进度（{done_count}/{total_count}）：{issue_data.get('url', '')}")
    return 0


def cmd_pr(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    wt_path, branch, goal_name, issue_num = _resolve_target_worktree(repo, args.target)
    validate_branch_name(branch, issue_num, wt_path)
    _require_clean_worktree(wt_path)

    base_branch = args.base or repo.default_branch
    base_ref = _resolve_base_ref(repo, base_branch)
    issue_data = _fetch_issue_optional(repo.main_worktree, issue_num)
    issue_title = issue_data.get("title") if issue_data else None

    suggested_title, body = build_goal_summary(wt_path, goal_name or branch, issue_num, base_ref, issue_title=issue_title)
    final_title = args.title or suggested_title

    if args.dry_run:
        print(f"Title: {final_title}\nBase: {base_branch}\nHead: {branch}\n\n{body}", end="")
        return 0

    push_cmd = ["git", "-C", str(wt_path), "push", "-u", "origin", "HEAD"]
    if args.force_with_lease:
        push_cmd.append("--force-with-lease")
    run_cmd(push_cmd)

    existing_pr = _resolve_pr_for_branch(wt_path, branch)
    with temp_markdown_file(body) as body_file:
        if existing_pr:
            pr_num = existing_pr["number"]
            run_cmd(
                ["gh", "pr", "edit", str(pr_num), "--title", final_title, "--body-file", str(body_file)],
                cwd=wt_path,
            )
            print(f"已更新 PR #{pr_num}: {existing_pr.get('url', '')}")
        else:
            create_cmd = [
                "gh",
                "pr",
                "create",
                "--base",
                base_branch,
                "--head",
                branch,
                "--title",
                final_title,
                "--body-file",
                str(body_file),
            ]
            if args.draft:
                create_cmd.append("--draft")
            proc = run_cmd(create_cmd, cwd=wt_path)
            pr_url = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
            print(f"已创建 PR: {pr_url}")
    return 0


def _resolve_pr_target(repo: RepoInfo, target: str | None) -> tuple[Path, str]:
    """Resolve (cwd, pr_ref_or_empty) for `idd ci`."""
    if not target:
        return repo.current_worktree, ""

    found = find_worktree_for_target(repo.main_worktree, target)
    if found:
        wt_path = Path(found["path"]).resolve()
        pr = _resolve_pr_for_branch(wt_path, found.get("branch", ""))
        if pr:
            return wt_path, str(pr["number"])

    num = parse_issue_ref(target)
    if num is not None:
        # Check whether target is directly a PR number or an Issue number
        if "/pull/" in target:
            return repo.main_worktree, str(num)
        direct_pr = run_gh_json(["pr", "view", str(num), "--json", "number,headRefName"], cwd=repo.main_worktree, check=False)
        if isinstance(direct_pr, dict) and direct_pr.get("number"):
            head_ref = direct_pr.get("headRefName", "")
            # Prefer matching open PR for Issue #num if this PR belongs to another branch and an Issue branch PR exists
            if not re.search(rf"(?:^|/){num}(?:-|$)", head_ref):
                matched = _find_pr_for_issue(repo.main_worktree, num)
                if matched:
                    return repo.main_worktree, str(matched["number"])
            return repo.main_worktree, str(direct_pr["number"])
        matched = _find_pr_for_issue(repo.main_worktree, num)
        if matched:
            return repo.main_worktree, str(matched["number"])
        raise IddError(f"找不到与 `{target}` 关联的 PR。")

    pr = _resolve_pr_for_branch(repo.main_worktree, target) or _resolve_pr_for_branch(repo.main_worktree, f"feat/{target}")
    if pr:
        return repo.main_worktree, str(pr["number"])
    raise IddError(f"找不到与 `{target}` 关联的 PR。")


def _find_pr_for_issue(cwd: Path, issue_num: int) -> dict[str, Any] | None:
    prs = run_gh_json(
        ["pr", "list", "--state", "open", "--limit", "100", "--json", "number,headRefName,body"],
        cwd=cwd,
        check=False,
    )
    if not isinstance(prs, list):
        return None
    for pr in prs:
        if re.search(rf"(?:^|/){issue_num}(?:-|$)", pr.get("headRefName", "")):
            return pr
    pattern = re.compile(rf"(?:Closes|Fixes|Resolves)\s+#{issue_num}\b", re.IGNORECASE)
    for pr in prs:
        if pattern.search(pr.get("body", "")):
            return pr
    return None


def cmd_ci(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    cwd, pr_ref = _resolve_pr_target(repo, args.target)

    if args.watch:
        watch_cmd = ["gh", "pr", "checks"]
        if pr_ref:
            watch_cmd.append(pr_ref)
        watch_cmd.append("--watch")
        subprocess.run(watch_cmd, cwd=str(cwd))

    view_cmd = ["pr", "view"]
    if pr_ref:
        view_cmd.append(pr_ref)
    view_cmd.extend(["--json", "number,title,url,state,mergeStateStatus,headRefName,statusCheckRollup"])
    pr = run_gh_json(view_cmd, cwd=cwd)

    overall, checks, failed_runs = _classify_pr_checks(pr)
    failed_logs: dict[str, str] = {}
    if args.logs or (overall == "FAIL" and not args.json):
        for run_id in failed_runs:
            log_proc = run_cmd(["gh", "run", "view", run_id, "--log-failed"], cwd=cwd, check=False)
            if log_proc.returncode == 0 and log_proc.stdout:
                tail = log_proc.stdout.splitlines()[-150:]
                failed_logs[run_id] = "\n".join(tail)

    payload = {
        "pr": {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "url": pr.get("url"),
            "state": pr.get("state"),
            "headRefName": pr.get("headRefName"),
            "mergeStateStatus": pr.get("mergeStateStatus"),
        },
        "overall": overall,
        "checks": checks,
        "failed_logs": failed_logs,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines = [
        f"PR #{pr['number']}: {pr.get('title', '')}",
        f"链接：{pr.get('url', '')}",
        f"总体 CI：{overall} | 合并状态：{pr.get('mergeStateStatus', 'UNKNOWN')} | 分支：{pr.get('headRefName', '')}",
    ]
    if checks:
        lines.append("")
        lines.append("检查明细：")
        for c in checks:
            lines.append(f"- [{c['verdict']}] {c['name']}")
    else:
        lines.append("暂无 CI 检查记录。")

    for run_id, text in failed_logs.items():
        lines.append(f"\n--- 失败日志 (Run {run_id} 末尾 150 行) ---")
        lines.append(text)
    print("\n".join(lines))
    return 0


def cmd_land(args: argparse.Namespace) -> int:
    caller_cwd = Path.cwd().resolve()
    repo = get_repo_info(caller_cwd)
    wt_path, branch, goal_name, issue_num = _resolve_target_worktree(repo, args.target)
    validate_branch_name(branch, issue_num, wt_path)
    _require_clean_worktree(wt_path)

    pr = _resolve_pr_for_branch(wt_path, branch)
    if not pr:
        raise IddError(f"分支 `{branch}` 尚无 Open PR，请先运行 `idd pr` 创建 PR。")

    pr_num = pr["number"]
    base_branch = pr.get("baseRefName") or repo.default_branch

    if repo.has_origin:
        run_cmd(["git", "-C", str(wt_path), "fetch", "origin", base_branch])
    base_ref = _resolve_base_ref(repo, base_branch)

    # Step A: Rebase if behind target base
    needs_rebase = False
    if not args.no_rebase:
        anc = run_cmd(["git", "-C", str(wt_path), "merge-base", "--is-ancestor", base_ref, "HEAD"], check=False)
        if anc.returncode != 0:
            needs_rebase = True
            if not args.dry_run:
                reb = run_cmd(["git", "-C", str(wt_path), "rebase", base_ref], check=False)
                if reb.returncode != 0:
                    conflicts = run_cmd(
                        ["git", "-C", str(wt_path), "diff", "--name-only", "--diff-filter=U"],
                        check=False,
                    ).stdout.strip()
                    raise IddError(
                        "Rebase 到最新主线时发生冲突，请解决冲突后执行 `git rebase --continue`（或 `git rebase --abort` 放弃）：\n"
                        f"{conflicts or reb.stderr.strip()}",
                        exit_code=2,
                    )

    # Step B: Build summary BEFORE removing TASK/<goal>/
    issue_data = _fetch_issue_optional(repo.main_worktree, issue_num)
    issue_title = issue_data.get("title") if issue_data else None
    suggested_title, summary = build_goal_summary(wt_path, goal_name or branch, issue_num, base_ref, issue_title=issue_title)
    final_title = args.title or suggested_title

    # Step C: Clean TASK/<goal>/ before merging into main (unless --keep-tasks)
    task_goal_dir = wt_path / "TASK" / (goal_name or "")
    will_clean_tasks = False
    if not args.keep_tasks and goal_name and task_goal_dir.is_dir():
        evidence_dir = task_goal_dir / "evidence"
        evidence_files = [
            p.relative_to(wt_path).as_posix()
            for p in sorted(evidence_dir.rglob("*"))
            if p.is_file()
        ] if evidence_dir.is_dir() else []
        if evidence_files and not args.force_clean_evidence:
            listed = "\n".join(f"  - {item}" for item in evidence_files)
            raise IddError(
                f"检测到 `TASK/{goal_name}/evidence/` 含附件文件，为防误删已暂停合入：\n{listed}\n"
                "请确认后传 `--force-clean-evidence` 一并清理，或传 `--keep-tasks` 保留任务目录。",
                exit_code=2,
            )
        will_clean_tasks = True
        if not args.dry_run:
            run_cmd(["git", "-C", str(wt_path), "rm", "-rf", f"TASK/{goal_name}"])
            run_cmd(["git", "-C", str(wt_path), "commit", "-m", f"chore: 清理已汇总的任务记录 ({goal_name})"])

    # Step D: Dry-run short-circuit
    if args.dry_run:
        lines = [
            "=== IDD Land Dry-Run 预览 ===",
            f"PR: #{pr_num} ({pr.get('url', '')})",
            f"工作树: {wt_path}",
            f"分支: {branch} -> {base_branch} (基于 {base_ref})",
            f"是否需要 Rebase: {'是' if needs_rebase else '否'}",
            f"合入前清理 TASK/{goal_name}/: {'是' if will_clean_tasks else '否'}",
            f"Squash 提交标题: {final_title}",
            "Squash 提交正文:",
            summary.rstrip(),
            f"合入命令: gh pr merge {pr_num} --squash{' --auto' if args.auto else ''}",
            f"分支策略: 默认保留本地与远端需求分支 `{branch}`",
            f"工作树策略: {'合入后移除本地工作树（--rm-worktree）' if (args.rm_worktree and not args.auto) else '默认保留本地工作树（如需释放空间可手动执行 idd cleanup）'}",
        ]
        print("\n".join(lines))
        return 0

    # Step E: Update PR body and push if local HEAD differs from origin/<branch>
    with temp_markdown_file(summary) as body_file:
        run_cmd(["gh", "pr", "edit", str(pr_num), "--title", final_title, "--body-file", str(body_file)], cwd=wt_path)

        local_head = run_cmd(["git", "-C", str(wt_path), "rev-parse", "HEAD"]).stdout.strip()
        remote_proc = run_cmd(
            ["git", "-C", str(wt_path), "rev-parse", f"origin/{branch}"],
            check=False,
        )
        remote_head = remote_proc.stdout.strip() if remote_proc.returncode == 0 else ""
        if local_head != remote_head:
            run_cmd(["git", "-C", str(wt_path), "push", "--force-with-lease", "origin", "HEAD"])

        # Step F: Squash Merge (Zero Merge Commits!) — keep remote feature branch
        fresh_pr = run_gh_json(
            ["pr", "view", str(pr_num), "--json", "number,url,statusCheckRollup,mergeStateStatus"],
            cwd=wt_path,
        )
        overall, _, _ = _classify_pr_checks(fresh_pr)

        if args.auto:
            run_cmd(
                [
                    "gh",
                    "pr",
                    "merge",
                    str(pr_num),
                    "--squash",
                    "--auto",
                    "--subject",
                    final_title,
                    "--body-file",
                    str(body_file),
                ],
                cwd=wt_path,
            )
            print(
                f"已为 PR #{pr_num} 开启自动 Squash 合并（CI 通过后将直线合入 {base_branch}，保留需求分支）：{pr.get('url', '')}\n"
                "本地工作树与需求分支已保留；合并完成后如需释放工作树目录可执行 `idd cleanup`。"
            )
            return 0

        if overall in ("FAIL", "PENDING"):
            raise IddError(
                f"PR #{pr_num} 当前 CI 状态为 `{overall}`，暂不执行合入。\n"
                f"请运行 `idd ci {issue_num or pr_num} --watch` 等待/排查 CI，或传 `--auto` 启用自动合入。",
                exit_code=3,
            )

        run_cmd(
            [
                "gh",
                "pr",
                "merge",
                str(pr_num),
                "--squash",
                "--subject",
                final_title,
                "--body-file",
                str(body_file),
            ],
            cwd=wt_path,
        )

    # Step G: Retain branches & worktree by default; optionally remove worktree; fast-forward main
    in_removed_wt = False
    if args.rm_worktree:
        in_removed_wt = caller_cwd == wt_path or wt_path in caller_cwd.parents
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "remove", str(wt_path)])

    main_sha = ""
    if repo.has_origin:
        run_cmd(["git", "-C", str(repo.main_worktree), "fetch", "origin", base_branch], check=False)
        main_st = run_cmd(["git", "-C", str(repo.main_worktree), "status", "--porcelain"], check=False).stdout.strip()
        main_br = run_cmd(["git", "-C", str(repo.main_worktree), "branch", "--show-current"], check=False).stdout.strip()
        if not main_st and main_br == base_branch:
            run_cmd(["git", "-C", str(repo.main_worktree), "merge", "--ff-only", f"origin/{base_branch}"], check=False)
            main_sha = run_cmd(["git", "-C", str(repo.main_worktree), "rev-parse", "--short", "HEAD"], check=False).stdout.strip()

    lines = [
        f"已通过 Squash Merge 直线合入 PR #{pr_num}（无 Merge 节点）：{pr.get('url', '')}",
        f"已保留本地与远端分支：{branch}",
    ]
    if args.rm_worktree:
        lines.append(f"已移除本地工作树：{wt_path}")
    else:
        lines.append(f"已保留本地工作树：{wt_path}（如需释放磁盘空间可运行 `idd cleanup`）")
    if main_sha:
        lines.append(f"本地 `{base_branch}` 已快进至：{main_sha}")
    if in_removed_wt:
        lines.append(f"当前终端位于已清理目录，请切换回主工作树：cd {repo.main_worktree}")
    print("\n".join(lines))
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    worktrees = task_status.list_git_worktrees(repo.main_worktree)
    main_resolved = repo.main_worktree.resolve()
    allowed_prefixes = tuple(f"{t}/" for t in ALLOWED_TYPES)

    removed: list[str] = []
    skipped_dirty: list[str] = []
    skipped_unmerged: list[str] = []

    for wt in worktrees:
        wt_path = Path(wt["path"]).resolve()
        branch = wt.get("branch", "")
        if wt_path == main_resolved or not branch or branch == "(detached)":
            continue
        under_managed_root = repo.worktree_root == wt_path.parent
        feature_branch = branch.startswith(allowed_prefixes)
        if not (under_managed_root or feature_branch):
            continue

        merged_prs = run_gh_json(
            ["pr", "list", "--state", "merged", "--head", branch, "--limit", "10", "--json", "number,url,headRefOid"],
            cwd=repo.main_worktree,
            check=False,
        )
        if not isinstance(merged_prs, list) or not merged_prs:
            continue

        dirty = run_cmd(["git", "-C", str(wt_path), "status", "--porcelain"], check=False).stdout.strip()
        if dirty:
            skipped_dirty.append(f"{wt_path} ({branch})")
            continue

        local_head = run_cmd(["git", "-C", str(wt_path), "rev-parse", "HEAD"]).stdout.strip()
        matching_pr = next(
            (pr for pr in merged_prs if pr.get("headRefOid") and pr.get("headRefOid") == local_head),
            None,
        )
        if not matching_pr:
            skipped_unmerged.append(f"{wt_path} ({branch} @ {local_head[:7]})")
            continue

        if args.dry_run:
            removed.append(f"[dry-run] 将仅移除工作树目录 {wt_path}（保留分支 {branch}）— PR #{matching_pr['number']}")
        else:
            run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "remove", str(wt_path)])
            removed.append(f"已移除工作树目录 {wt_path}（保留分支 {branch}）— PR #{matching_pr['number']}")

    lines = list(removed)
    if skipped_dirty:
        lines.append("以下工作树存在未提交改动，已跳过清理：")
        lines.extend(f"- {item}" for item in skipped_dirty)
    if skipped_unmerged:
        lines.append("以下工作树本地最新提交与已合入 PR 的 headRefOid 不一致（可能存在合入后新增本地提交），已跳过清理：")
        lines.extend(f"- {item}" for item in skipped_unmerged)
    if not lines:
        lines.append("没有发现可安全清理的已合入工作树。")
    print("\n".join(lines))
    return 0


def cmd_repo_init(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    if args.apply:
        data = run_gh_json(
            [
                "api",
                "-X",
                "PATCH",
                "repos/{owner}/{repo}",
                "-F",
                "allow_merge_commit=false",
                "-F",
                "allow_squash_merge=true",
                "-F",
                "delete_branch_on_merge=false",
            ],
            cwd=repo.main_worktree,
        )
        prefix = "已应用线性合入配置（仅 Squash 合入并保留需求分支）："
    else:
        data = run_gh_json(["api", "repos/{owner}/{repo}"], cwd=repo.main_worktree)
        prefix = "当前仓库合入策略（加 `--apply` 可自动设为仅允许 Squash 并保留需求分支）："

    lines = [
        prefix,
        f"- 仓库：{data.get('full_name', '')}",
        f"- allow_merge_commit: {data.get('allow_merge_commit')}",
        f"- allow_squash_merge: {data.get('allow_squash_merge')}",
        f"- allow_rebase_merge: {data.get('allow_rebase_merge')}",
        f"- delete_branch_on_merge: {data.get('delete_branch_on_merge')}",
        f"- allow_auto_merge: {data.get('allow_auto_merge')}",
        "提示：如需连人工网页点击也强制直线历史，建议在 GitHub Branch Ruleset 中勾选 `Require linear history`。",
    ]
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# Safe background auto-update & `idd upgrade`
# ---------------------------------------------------------------------------


def get_skill_repo_dir() -> Path:
    """Return the local `idd` skill git repository root."""
    override = os.environ.get("IDD_SKILL_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return SCRIPT_DIR.parent.resolve()


def get_update_state_path() -> Path:
    """Return path to the local auto-update state JSON file."""
    cache_override = os.environ.get("IDD_CACHE_DIR", "").strip()
    base = Path(cache_override).expanduser() if cache_override else (Path.home() / ".cache" / "idd")
    return base / "update_state.json"


def _get_update_interval() -> float:
    raw = os.environ.get("IDD_UPDATE_INTERVAL", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return float(AUTO_UPDATE_INTERVAL_SECONDS)


def _load_update_state() -> dict[str, Any]:
    path = get_update_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_update_state(state: dict[str, Any]) -> None:
    path = get_update_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)
    except OSError:
        pass


def _ensure_scripts_executable(skill_dir: Path) -> None:
    filemode = subprocess.run(
        ["git", "-C", str(skill_dir), "config", "--get", "core.filemode"],
        capture_output=True,
        text=True,
    ).stdout.strip().lower()
    for rel in ("scripts/idd", "scripts/task_status.py"):
        target = skill_dir / rel
        if not target.is_file():
            continue
        mode = target.stat().st_mode
        if mode & stat.S_IXUSR:
            continue
        if filemode != "false":
            ls_out = subprocess.run(
                ["git", "-C", str(skill_dir), "ls-files", "-s", "--", rel],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if ls_out.startswith("100644 "):
                continue
        try:
            target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass


def _inspect_skill_repo_sync(skill_dir: Path) -> tuple[str, str, int, int, str]:
    """Inspect (branch, dirty, behind, ahead, cur_sha) of the local skill git repo."""
    branch = subprocess.run(
        ["git", "-C", str(skill_dir), "branch", "--show-current"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(skill_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    behind_proc = subprocess.run(
        ["git", "-C", str(skill_dir), "rev-list", "--count", "HEAD..origin/main"],
        capture_output=True,
        text=True,
    )
    ahead_proc = subprocess.run(
        ["git", "-C", str(skill_dir), "rev-list", "--count", "origin/main..HEAD"],
        capture_output=True,
        text=True,
    )
    behind = int(behind_proc.stdout.strip()) if behind_proc.returncode == 0 and behind_proc.stdout.strip().isdigit() else 0
    ahead = int(ahead_proc.stdout.strip()) if ahead_proc.returncode == 0 and ahead_proc.stdout.strip().isdigit() else 0
    cur_sha = subprocess.run(
        ["git", "-C", str(skill_dir), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return branch, dirty, behind, ahead, cur_sha


def run_bg_auto_update() -> int:
    """Safely fetch origin/main and fast-forward when local skill repo is clean on main."""
    skill_dir = get_skill_repo_dir()
    if not (skill_dir / ".git").exists():
        return 0

    remotes_proc = subprocess.run(
        ["git", "-C", str(skill_dir), "remote"],
        capture_output=True,
        text=True,
    )
    if remotes_proc.returncode != 0 or "origin" not in {r.strip() for r in remotes_proc.stdout.splitlines()}:
        return 0

    now = time.time()
    try:
        fetch_proc = subprocess.run(
            ["git", "-C", str(skill_dir), "fetch", "origin", "main", "--quiet"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        state = _load_update_state()
        state["last_checked_at"] = now
        _save_update_state(state)
        return 0

    if fetch_proc.returncode != 0:
        state = _load_update_state()
        state["last_checked_at"] = now
        _save_update_state(state)
        return 0

    branch, dirty, behind, ahead, old_sha = _inspect_skill_repo_sync(skill_dir)
    if behind == 0:
        _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": 0})
        return 0

    if branch == "main" and not dirty and ahead == 0:
        merge_proc = subprocess.run(
            ["git", "-C", str(skill_dir), "merge", "--ff-only", "origin/main"],
            capture_output=True,
            text=True,
        )
        if merge_proc.returncode == 0:
            _ensure_scripts_executable(skill_dir)
            new_sha = subprocess.run(
                ["git", "-C", str(skill_dir), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            subject = subprocess.run(
                ["git", "-C", str(skill_dir), "log", "-1", "--format=%s", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            notice = f"✨ idd 已自动同步至最新 ({old_sha} → {new_sha}): {subject}"
            _save_update_state({"last_checked_at": now, "pending_notice": notice, "behind_count": 0})
            return 0

    _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": behind})
    return 0


def maybe_notify_and_trigger_auto_update(current_command: str | None) -> None:
    """Print cached update notice to stderr and trigger detached background check if due."""
    try:
        if os.environ.get("IDD_NO_AUTO_UPDATE") == "1" or current_command == "upgrade":
            return
        state = _load_update_state()
        pending_notice = state.get("pending_notice")
        behind_count = int(state.get("behind_count") or 0)

        if pending_notice:
            print(pending_notice, file=sys.stderr)
            state["pending_notice"] = ""
            _save_update_state(state)
        elif behind_count > 0:
            print(
                f"💡 idd 远端有 {behind_count} 个新提交（本地技能目录未处于干净的 main 分支，已跳过自动合并），可运行 `idd upgrade` 查看。",
                file=sys.stderr,
            )

        last_checked = float(state.get("last_checked_at", 0) or 0)
        if time.time() - last_checked >= _get_update_interval():
            state["last_checked_at"] = time.time()
            _save_update_state(state)
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--_bg-auto-update"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception:
        pass


def cmd_upgrade(args: argparse.Namespace) -> int:
    skill_dir = get_skill_repo_dir()
    git_check = run_cmd(["git", "-C", str(skill_dir), "rev-parse", "--git-dir"], check=False)
    if git_check.returncode != 0:
        raise IddError(f"技能目录 `{skill_dir}` 不是 Git 仓库，无法执行更新。")

    remotes_proc = run_cmd(["git", "-C", str(skill_dir), "remote"])
    if "origin" not in {r.strip() for r in remotes_proc.stdout.splitlines()}:
        raise IddError(f"技能目录 `{skill_dir}` 未配置 `origin` 远端。")

    run_cmd(["git", "-C", str(skill_dir), "fetch", "origin", "main"])
    branch, dirty, behind, ahead, cur_sha = _inspect_skill_repo_sync(skill_dir)
    now = time.time()

    if args.check:
        lines = [
            f"当前版本：idd {__version__}",
            f"技能目录：{skill_dir}",
            f"当前状态：{branch or '(detached)'} @ {cur_sha}{' (有未提交改动)' if dirty else ''}",
        ]
        if behind > 0:
            incoming = run_cmd(
                ["git", "-C", str(skill_dir), "log", "--oneline", "HEAD..origin/main"],
                check=False,
            ).stdout.strip()
            lines.append(f"远端有 {behind} 个新提交：")
            if incoming:
                lines.append(incoming)
        else:
            lines.append("已是最新，与 origin/main 一致。")
        _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": behind})
        print("\n".join(lines))
        return 0

    if behind == 0:
        _ensure_scripts_executable(skill_dir)
        _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": 0})
        print(f"idd 已是最新版本 (v{__version__}, {cur_sha})。")
        return 0

    reasons: list[str] = []
    if branch != "main":
        reasons.append(f"当前分支为 `{branch or '(detached)'}`（而非 `main`）")
    if dirty:
        reasons.append("存在未提交改动")
    if ahead > 0:
        reasons.append(f"本地存在 {ahead} 个未推送提交")

    if reasons:
        incoming = run_cmd(
            ["git", "-C", str(skill_dir), "log", "--oneline", "HEAD..origin/main"],
            check=False,
        ).stdout.strip()
        _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": behind})
        raise IddError(
            f"已跳过自动快进更新，原因：{'、'.join(reasons)}。\n"
            f"远端待合入提交：\n{incoming}\n"
            "请清理改动或切回干净的 `main` 后重试 `idd upgrade`。"
        )

    run_cmd(["git", "-C", str(skill_dir), "merge", "--ff-only", "origin/main"])
    _ensure_scripts_executable(skill_dir)
    new_sha = run_cmd(["git", "-C", str(skill_dir), "rev-parse", "--short", "HEAD"]).stdout.strip()
    changelog = run_cmd(
        ["git", "-C", str(skill_dir), "log", "--oneline", f"{cur_sha}..{new_sha}"],
        check=False,
    ).stdout.strip()
    _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": 0})

    lines = [f"已更新 idd：{cur_sha} → {new_sha}"]
    if changelog:
        lines.append(changelog)
    print("\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="idd",
        description="Issue-Driven Development (IDD) 跨工具共享开发流水线工具",
    )
    parser.add_argument("-v", "--version", action="version", version=f"idd {__version__}")
    parser.add_argument("--_bg-auto-update", action="store_true", dest="bg_auto_update", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=False)

    # status
    p_status = sub.add_parser("status", help="聚合并展示 GitHub Issue、Worktree TASK 进度与 PR/CI 状态")
    p_status.add_argument("--root", type=Path, default=Path.cwd(), help="仓库根目录或工作树路径")
    p_status.add_argument("--goal", help="只查看指定目标目录")
    p_status.add_argument("--open-only", action="store_true", help="只保留存在非 done 任务的目标")
    p_status.add_argument("--local-only", action="store_true", help="仅检查本地工作树，不调用 gh")
    p_status.add_argument("--json", action="store_true", help="输出 JSON")
    p_status.set_defaults(func=cmd_status)

    # issue
    p_issue = sub.add_parser("issue", help="GitHub Issue 辅助命令")
    issue_sub = p_issue.add_subparsers(dest="issue_command", required=True)
    p_issue_create = issue_sub.add_parser("create", help="创建 GitHub Issue")
    p_issue_create.add_argument("--title", required=True, help="Issue 标题")
    p_issue_create.add_argument("--body", help="Issue 正文")
    p_issue_create.add_argument("--body-file", type=Path, help="从文件读取 Issue 正文")
    p_issue_create.add_argument("--label", action="append", help="添加标签（可重复）")
    p_issue_create.add_argument("--assignee", action="append", help="指派负责人（可重复）")
    p_issue_create.add_argument("--json", action="store_true", help="输出 JSON")
    p_issue_create.set_defaults(func=cmd_issue_create)

    # start
    p_start = sub.add_parser("start", help="认领 Issue（或本地目标）并创建/幂等复用独立 worktree")
    p_start.add_argument("target", help="Issue 编号（如 42 / #42 / URL）或纯本地目标 slug")
    p_start.add_argument("--slug", help="覆盖自动生成的英文短别名")
    p_start.add_argument("--prefix", choices=list(ALLOWED_TYPES), help="分支前缀（允许 8 类标准 type）")
    p_start.add_argument("--base", help="基准分支（默认 origin/<default_branch> 或本地主分支）")
    p_start.add_argument("--json", action="store_true", help="输出 JSON")
    p_start.set_defaults(func=cmd_start)

    # sync
    p_sync = sub.add_parser("sync", help="将本地 TASK 进度同步为 GitHub Issue 原生进度条")
    p_sync.add_argument("issue_number", nargs="?", help="Issue 编号（在对应工作树内可省略）")
    p_sync.add_argument("--root", type=Path, default=Path.cwd(), help="工作树或仓库路径")
    p_sync.add_argument("--dry-run", action="store_true", help="仅预览合并后的 Issue 正文")
    p_sync.set_defaults(func=cmd_sync)

    # pr
    p_pr = sub.add_parser("pr", help="基于 TASK 汇总生成结构化描述并创建或更新 PR")
    p_pr.add_argument("target", nargs="?", help="Issue 编号或目标名（在对应工作树内可省略）")
    p_pr.add_argument("--title", help="自定义 PR 标题")
    p_pr.add_argument("--base", help="目标基础分支（默认仓库主分支）")
    p_pr.add_argument("--draft", action="store_true", help="创建为 Draft PR")
    p_pr.add_argument("--force-with-lease", action="store_true", help="使用 --force-with-lease 推送")
    p_pr.add_argument("--dry-run", action="store_true", help="仅预览生成的标题与正文")
    p_pr.set_defaults(func=cmd_pr)

    # ci
    p_ci = sub.add_parser("ci", help="查看 PR 的 CI 状态并拉取失败日志")
    p_ci.add_argument("target", nargs="?", help="Issue 编号、PR 编号或分支名（在工作树内可省略）")
    p_ci.add_argument("--watch", action="store_true", help="阻塞监听 CI 检查直到结束")
    p_ci.add_argument("--logs", action="store_true", help="拉取失败 CI Run 的日志")
    p_ci.add_argument("--json", action="store_true", help="输出 JSON")
    p_ci.set_defaults(func=cmd_ci)

    # land
    p_land = sub.add_parser("land", help="Rebase、清理 TASK 目录并 Squash 直线合入主分支（默认保留分支与工作树）")
    p_land.add_argument("target", nargs="?", help="Issue 编号或目标名（在工作树内可省略）")
    p_land.add_argument("--title", help="自定义 Squash 提交标题")
    p_land.add_argument("--keep-tasks", action="store_true", help="保留 TASK/<goal>/ 目录不清理")
    p_land.add_argument("--force-clean-evidence", action="store_true", help="强制一并清理 evidence/ 下附件")
    p_land.add_argument("--rm-worktree", action="store_true", help="合入后顺带移除本地工作树目录（仍保留本地与远端分支）")
    p_land.add_argument("--auto", action="store_true", help="启用 GitHub auto-squash-merge 等待 CI 后合并")
    p_land.add_argument("--no-rebase", action="store_true", help="跳过合入前自动 rebase")
    p_land.add_argument("--dry-run", action="store_true", help="仅预览合入计划与清理清单")
    p_land.set_defaults(func=cmd_land)

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="按需清理已合入且 HEAD 一致的干净工作树目录（保留所有分支）")
    p_cleanup.add_argument("--dry-run", action="store_true", help="仅预览待清理工作树目录")
    p_cleanup.set_defaults(func=cmd_cleanup)

    # repo-init
    p_repo_init = sub.add_parser("repo-init", help="检查或配置 GitHub 仓库的仅 Squash 线性合入策略（保留分支）")
    p_repo_init.add_argument("--apply", action="store_true", help="禁用 merge commit、仅启用 squash merge 且合并后保留远端分支")
    p_repo_init.set_defaults(func=cmd_repo_init)

    # upgrade
    p_upgrade = sub.add_parser("upgrade", help="检查或立即拉取远端更新并快进同步本地 idd")
    p_upgrade.add_argument("--check", action="store_true", help="仅检查远端是否有更新，不合并")
    p_upgrade.set_defaults(func=cmd_upgrade)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.bg_auto_update:
        return run_bg_auto_update()
    if not args.command:
        parser.error("需要提供子命令（使用 -h 查看帮助）")
    maybe_notify_and_trigger_auto_update(args.command)
    try:
        return args.func(args)
    except IddError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
