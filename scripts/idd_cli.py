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
import unicodedata

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from forge import (  # noqa: E402
    ForgeError,
    evaluate_repo_init_settings,
    get_config_dir,
    get_forge,
    get_hosts_path,
    load_hosts_config,
    normalize_host_input,
    save_hosts_config,
    verify_host_token,
)
import board_ui  # noqa: E402
import monitor  # noqa: E402
import preview_ui  # noqa: E402
import task_status  # noqa: E402
from version import get_version  # noqa: E402


__version__ = get_version()
AUTO_UPDATE_INTERVAL_SECONDS = 6 * 3600
LAND_SYNC_TIMEOUT_SECONDS = 30.0
LAND_SYNC_POLL_INTERVAL_SECONDS = 1.0
LAND_MERGE_MAX_RETRIES = 3
LAND_MERGE_RETRY_DELAY_SECONDS = 1.5
CI_WAIT_GRACE_SECONDS = 5.0
CI_WAIT_POLL_INTERVAL_SECONDS = 5.0
CI_WAIT_TIMEOUT_SECONDS = 1800.0

ALLOWED_TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "ci", "chore")
MAX_ISSUE_SCOPE_LEN = 16
ISSUE_SCOPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONVENTIONAL_TITLE_RE = re.compile(
    rf"^({'|'.join(ALLOWED_TYPES)})(\([^)\r\n]+\))?(!)?[:：]\s*(.+)$",
    re.IGNORECASE,
)
EMPTY_SCOPE_PREFIX_RE = re.compile(
    rf"^({'|'.join(ALLOWED_TYPES)})\(\s*\)(!)?[:：]\s*(.*)$",
    re.IGNORECASE,
)
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
    r"^[ \t]*" + re.escape(PROGRESS_START) + r"[ \t]*$.*?^[ \t]*" + re.escape(PROGRESS_END) + r"[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


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
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing UTF-8 output; raise IddError on failure when check=True."""
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            input=input_text,
            env=env,
        )
    except FileNotFoundError as exc:
        raise IddError(f"找不到可执行文件 `{args[0]}`，请确认已安装并在 PATH 中。") from exc
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}"
        raise IddError(f"命令 `{' '.join(args)}` 执行失败：{detail}")
    return proc


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
    """Parse an integer issue/PR/MR reference from '42', '#42', '!42', or a GitHub/GitLab URL."""
    cleaned = ref.strip()
    if not cleaned:
        return None
    match = re.fullmatch(r"[#! ]*(\d+)", cleaned)
    if match:
        return int(match.group(1))
    url_match = re.search(r"/(?:issues|merge_requests|pull)/(\d+)(?:[/?#].*)?$", cleaned)
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
    """Compute a valid `<type>/<issue#>-<slug>` or `<type>/<slug>` suggestion for an invalid branch."""
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


def get_repo_info(cwd: Path, *, register: bool = True) -> RepoInfo:
    """Resolve main/current worktrees, branches, origin presence, and managed worktree root."""
    try:
        worktrees = task_status.list_git_worktrees(cwd)
    except ValueError as exc:
        raise IddError(str(exc)) from exc
    if not worktrees:
        raise IddError(f"无法解析 Git 工作树信息：{cwd}")

    main_worktree = Path(worktrees[0]["path"]).resolve()
    if register:
        monitor.register_repo(main_worktree)
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
    """Locate an existing worktree matching an issue number or issue slug."""
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


def _infer_issue_dir_and_number(
    worktree: Path,
    branch: str,
    target: str | None = None,
) -> tuple[str | None, int | None]:
    """Determine (issue_dir, issue_number) for a given worktree and optional user target."""
    issue_num = parse_issue_ref(target) if target else None
    if issue_num is None:
        branch_match = re.search(r"(?:^|/)(\d+)(?:-|$)", branch)
        if branch_match:
            issue_num = int(branch_match.group(1))

    task_root = worktree / "TASK"
    issue_dir: str | None = None
    if task_root.is_dir():
        dirs = sorted(d.name for d in task_root.iterdir() if d.is_dir() and not d.name.startswith("."))
        if target and not parse_issue_ref(target) and target in dirs:
            issue_dir = target
        elif issue_num is not None:
            for d in dirs:
                if d == str(issue_num) or d.startswith(f"{issue_num}-"):
                    issue_dir = d
                    break
        if issue_dir is None:
            branch_tail = branch.split("/", 1)[-1] if "/" in branch else branch
            if branch_tail in dirs:
                issue_dir = branch_tail
            elif len(dirs) == 1:
                issue_dir = dirs[0]

    if issue_dir is None:
        if target and not parse_issue_ref(target):
            issue_dir = target
        elif "/" in branch and branch != "(detached)":
            issue_dir = branch.split("/", 1)[-1]
        else:
            issue_dir = worktree.name

    if issue_num is None and issue_dir:
        issue_num = task_status.parse_issue_number("", issue_dir)
    return issue_dir, issue_num


def _resolve_target_worktree(repo: RepoInfo, target: str | None) -> tuple[Path, str, str | None, int | None]:
    """Resolve (worktree_path, branch, issue_dir, issue_number) from target or current worktree."""
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
            raise IddError(f"当前位于主线工作树 `{branch}` 上；请指定 Issue 编号/目录，或切换到对应工作树执行。")

    issue_dir, issue_num = _infer_issue_dir_and_number(wt_path, branch, target)
    return wt_path, branch, issue_dir, issue_num


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


def _collect_commit_task_records(worktree: Path, issue_dir: str, base_ref: str) -> list[dict[str, str]]:
    """Read git commits since merge-base and extract Task/Test metadata."""
    check_ref = run_cmd(["git", "-C", str(worktree), "rev-parse", "--verify", base_ref], check=False)
    if check_ref.returncode != 0:
        return []

    mb = run_cmd(["git", "-C", str(worktree), "merge-base", base_ref, "HEAD"], check=False)
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
                if m and (issue_dir in val or val.startswith("TASK-")):
                    task_id = m.group(1)
            elif line.startswith("Test:"):
                test_line = line[len("Test:"):].strip()
            elif line.startswith(("Refs:", "Closes:", "Fixes:", "Co-authored-by:", "Signed-off-by:")):
                continue
            elif line:
                extra_lines.append(raw_line.rstrip())
            elif extra_lines and extra_lines[-1] != "":
                extra_lines.append("")
        while extra_lines and extra_lines[-1] == "":
            extra_lines.pop()

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


def _wrap_inline_code(text: str) -> str:
    """Wrap command text in a safe CommonMark inline code span."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    unwrapped = re.fullmatch(r"`([^`]+)`", cleaned)
    if unwrapped:
        cleaned = unwrapped.group(1).strip()
    if not cleaned:
        return ""
    runs = re.findall(r"`+", cleaned)
    max_ticks = max((len(r) for r in runs), default=0)
    fence = "`" * (max_ticks + 1)
    if cleaned.startswith("`") or cleaned.endswith("`"):
        return f"{fence} {cleaned} {fence}"
    return f"{fence}{cleaned}{fence}"


def _format_test_summary_line(test_text: str) -> str:
    """Format a Test summary bullet item with inline-coded command(s)."""
    cleaned = test_text.strip()
    if not cleaned:
        return "- **Test:** 未记录"

    def _fmt_segment(seg: str) -> str:
        if " — " not in seg:
            return seg.strip()
        cmd, result = seg.split(" — ", 1)
        cmd_s = cmd.strip()
        res_s = result.strip()
        if not cmd_s:
            return res_s or seg.strip()
        return f"{_wrap_inline_code(cmd_s)} — {res_s}" if res_s else _wrap_inline_code(cmd_s)

    segments = [s.strip() for s in cleaned.split("; ") if s.strip()]
    if len(segments) > 1 and all(" — " in seg for seg in segments):
        formatted = "; ".join(_fmt_segment(seg) for seg in segments)
    elif " — " in cleaned:
        formatted = _fmt_segment(cleaned)
    else:
        formatted = cleaned
    return f"- **Test:** {formatted}"


def _format_conventional_title(default_type: str, raw_title: str) -> str:
    """Ensure a PR / Squash commit title has a single normalized Conventional Commit prefix."""
    cleaned = raw_title.strip()
    match = CONVENTIONAL_TITLE_RE.match(cleaned)
    if match:
        prefix_type = match.group(1).lower()
        scope = match.group(2) or ""
        bang = match.group(3) or ""
        subject = match.group(4).strip()
        return f"{prefix_type}{scope}{bang}: {subject}"
    return f"{default_type}: {cleaned}"


def build_issue_summary(
    worktree: Path,
    issue_dir: str,
    issue_number: int | None,
    base_ref: str,
    issue_title: str | None = None,
    branch: str = "",
) -> tuple[str, str]:
    """Generate (suggested_title, markdown_body) from TASK files and branch commits."""
    task_dir = worktree / "TASK" / issue_dir
    tasks: list[dict[str, Any]] = []
    if task_dir.is_dir():
        for path in sorted(task_dir.glob("TASK-*.md")):
            if path.is_file() and re.match(r"^TASK-\d+(?:-|\.md)", path.name):
                parsed = task_status.read_task(path, worktree / "TASK")
                parsed["_details"] = _parse_task_markdown_details(path)
                tasks.append(parsed)

    commits = _collect_commit_task_records(worktree, issue_dir, base_ref)
    commit_by_task: dict[str, dict[str, str]] = {}
    for rec in commits:
        if rec["task_id"]:
            commit_by_task[rec["task_id"]] = rec

    commit_types = [c["type"] for c in commits if c["type"] and c["type"] != "chore"]
    dominant_type = commit_types[0] if commit_types else "feat"

    first_change = ""
    blocks: list[str] = []
    if tasks:
        for task in tasks:
            tid = task["id"]
            commit_rec = commit_by_task.get(tid, {})
            details = task["_details"]
            raw_title = re.sub(rf"^{re.escape(tid)}[：:\s]+", "", task["title"]).strip()
            change = commit_rec.get("change") or raw_title or task["title"]
            if not first_change:
                first_change = change
            test_text = (
                commit_rec.get("test")
                or details.get("latest_result")
                or (f"{details['command']} — {details['outcome']}" if details.get("command") else "")
                or (f"{task['test']} — {details['outcome'] or task['status']}" if task.get("test") else "未记录")
            )
            block_parts = [f"### {tid} {change}"]
            extra = commit_rec.get("extra", "")
            if extra:
                block_parts.append(extra)
            block_parts.append(_format_test_summary_line(test_text))
            blocks.append("\n\n".join(block_parts))
    elif commits:
        for idx, rec in enumerate(commits, start=1):
            if rec["subject"].startswith("chore: 清理已汇总的任务记录"):
                continue
            tid = rec["task_id"] or f"TASK-{idx:02d}"
            change = rec["change"]
            if not first_change:
                first_change = change
            block_parts = [f"### {tid} {change}"]
            if rec["extra"]:
                block_parts.append(rec["extra"])
            block_parts.append(_format_test_summary_line(rec["test"] or "未在提交中记录"))
            blocks.append("\n\n".join(block_parts))

    if issue_title:
        suggested_title = _format_conventional_title(dominant_type, issue_title)
    elif len(tasks) == 1:
        only_change = first_change or issue_dir
        suggested_title = _format_conventional_title(dominant_type, only_change)
    elif len(commits) == 1 and commits[0]["change"]:
        suggested_title = _format_conventional_title(dominant_type, commits[0]["change"])
    else:
        suggested_title = f"{dominant_type}: 完成 {issue_dir}"

    if issue_number is not None and f"(#{issue_number})" not in suggested_title:
        suggested_title = f"{suggested_title} (#{issue_number})"

    header_lines = [f"Closes #{issue_number}"] if issue_number is not None else [f"Branch: {branch or issue_dir}"]
    body_parts = ["\n".join(header_lines)]
    if blocks:
        body_parts.extend(blocks)
    return suggested_title, "\n\n".join(body_parts) + "\n"


def build_progress_block(tasks: list[dict[str, Any]]) -> str:
    """Render an idempotent Issue checklist block from parsed TASK items."""
    lines = [PROGRESS_START, "## 执行进度（IDD 自动同步）"]
    for task in tasks:
        checked = "x" if task["status"] == "done" else " "
        note = "" if task["status"] in ("done", "planned") else f" *({task['status']})*"
        lines.append(f"- [{checked}] {task['title']}{note}")
    lines.append(PROGRESS_END)
    return "\n".join(lines)


_FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")


def _update_fence_state(
    line_no_eol: str,
    fence_char: str | None,
    fence_len: int,
) -> tuple[bool, str | None, int]:
    """Track Markdown fenced code blocks; return (is_fence_line, next_char, next_len)."""
    if fence_char is not None:
        close_m = _FENCE_CLOSE_RE.match(line_no_eol)
        if close_m and close_m.group(1)[0] == fence_char and len(close_m.group(1)) >= fence_len:
            return True, None, 0
        return True, fence_char, fence_len

    open_m = _FENCE_OPEN_RE.match(line_no_eol)
    if open_m:
        seq = open_m.group(1)
        rest = open_m.group(2)
        # CommonMark: backtick info strings cannot contain backticks.
        if not (seq[0] == "`" and "`" in rest):
            return True, seq[0], len(seq)
    return False, None, 0


def _find_progress_block_span(body: str) -> tuple[int, int] | None:
    """Locate standalone non-fenced IDD progress block character span in `body`."""
    if not body:
        return None
    offset = 0
    start_offset: int | None = None
    fence_char: str | None = None
    fence_len = 0

    for raw_line in body.splitlines(keepends=True):
        line_no_eol = raw_line.rstrip("\r\n")
        in_fence, fence_char, fence_len = _update_fence_state(line_no_eol, fence_char, fence_len)
        if not in_fence:
            stripped = line_no_eol.strip()
            if stripped == PROGRESS_START:
                start_offset = offset
            elif start_offset is not None and stripped == PROGRESS_END:
                return start_offset, offset + len(line_no_eol)
        offset += len(raw_line)
    return None


def merge_progress_block(original_body: str, block: str) -> str:
    """Replace existing IDD progress block in Issue body, or append it cleanly."""
    span = _find_progress_block_span(original_body)
    if span is not None:
        start, end = span
        updated = original_body[:start] + block + original_body[end:]
        return updated.rstrip() + "\n"
    stripped = original_body.rstrip()
    if not stripped:
        return block + "\n"
    return f"{stripped}\n\n{block}\n"


_ACCEPTANCE_PREFIX_RE = re.compile(
    r"^\s*(?:[（(](?:\d+|[一二三四五六七八九十]+)[）)]|(?:\d+(?:\.\d+)*|[一二三四五六七八九十]+)\s*[.)、:：])\s*"
)
_ACCEPTANCE_ZH_START_RE = re.compile(r"^验收(?:$|[\s:：(\[（\-—·])")
_ACCEPTANCE_EN_START_RE = re.compile(r"^acceptance(?:$|[\s:：(\[\-])")
_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_UNCHECKED_TASK_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+\[) (\](?:\s+.*|\s*))$")


def _is_acceptance_heading(title: str) -> bool:
    """Return True when a Markdown heading represents an acceptance criteria section."""
    cleaned = _ACCEPTANCE_PREFIX_RE.sub("", title.strip()).strip().casefold()
    if not cleaned:
        return False
    if any(kw in cleaned for kw in ("验收标准", "验收条件", "验收清单", "需求验收")):
        return True
    if _ACCEPTANCE_ZH_START_RE.match(cleaned):
        return True
    if any(kw in cleaned for kw in ("acceptance criteria", "acceptance checklist")):
        return True
    return bool(_ACCEPTANCE_EN_START_RE.match(cleaned))


def check_acceptance_criteria(body: str) -> tuple[str, int]:
    """Check unchecked Markdown task boxes inside acceptance sections; return (new_body, checked_count)."""
    if not body:
        return body, 0

    out_lines: list[str] = []
    checked_count = 0
    active_level: int | None = None
    in_progress_block = False
    fence_char: str | None = None
    fence_len = 0

    for raw_line in body.splitlines(keepends=True):
        line_no_eol = raw_line.rstrip("\r\n")
        eol = raw_line[len(line_no_eol):]

        if in_progress_block:
            if line_no_eol.strip() == PROGRESS_END:
                in_progress_block = False
            out_lines.append(raw_line)
            continue

        in_fence, fence_char, fence_len = _update_fence_state(line_no_eol, fence_char, fence_len)
        if in_fence:
            out_lines.append(raw_line)
            continue

        if line_no_eol.strip() == PROGRESS_START:
            active_level = None
            in_progress_block = True
            out_lines.append(raw_line)
            continue

        heading_m = _ATX_HEADING_RE.match(line_no_eol)
        if heading_m:
            level = len(heading_m.group(1))
            heading_text = heading_m.group(2)
            if active_level is None:
                if _is_acceptance_heading(heading_text):
                    active_level = level
            elif level <= active_level:
                active_level = level if _is_acceptance_heading(heading_text) else None
            out_lines.append(raw_line)
            continue

        if active_level is not None:
            task_m = _UNCHECKED_TASK_RE.match(line_no_eol)
            if task_m:
                out_lines.append(f"{task_m.group(1)}x{task_m.group(2)}{eol}")
                checked_count += 1
                continue

        out_lines.append(raw_line)

    return "".join(out_lines), checked_count


def _require_clean_worktree(worktree: Path) -> None:
    st = run_cmd(["git", "-C", str(worktree), "status", "--porcelain"])
    if st.stdout.strip():
        raise IddError(f"工作树 `{worktree}` 存在未提交改动，请先提交或暂存：\n{st.stdout.strip()}")


def _fix_misbound_upstream(wt_path: Path, branch: str, default_branch: str) -> None:
    """Unset branch upstream if it was accidentally bound to `origin/<default_branch>`."""
    if not branch or branch == "(detached)" or branch == default_branch:
        return
    up_proc = run_cmd(
        ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        check=False,
    )
    if up_proc.returncode == 0 and up_proc.stdout.strip() == f"origin/{default_branch}":
        run_cmd(["git", "-C", str(wt_path), "branch", "--unset-upstream"], check=False)


def _push_feature_branch(wt_path: Path, branch: str, *, default_branch: str) -> tuple[bool, str]:
    """Fix misbound upstream if needed and push current branch to `origin` with tracking."""
    _fix_misbound_upstream(wt_path, branch, default_branch)
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    proc = run_cmd(
        ["git", "-C", str(wt_path), "push", "-u", "origin", "HEAD"],
        check=False,
        env=env,
    )
    if proc.returncode == 0:
        return True, ""
    detail = proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}"
    return False, detail


# ---------------------------------------------------------------------------
# Subcommand handlers & rich terminal status renderer
# ---------------------------------------------------------------------------


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _display_width(text: str) -> int:
    """Return terminal column width of `text`, ignoring ANSI SGR escapes and accounting for CJK wide chars."""
    plain = _ANSI_RE.sub("", text)
    width = 0
    for ch in plain:
        if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _truncate_display(text: str, max_width: int) -> str:
    """Truncate plain `text` to at most `max_width` terminal columns with an ellipsis."""
    if max_width <= 0:
        return ""
    if _display_width(text) <= max_width:
        return text
    if max_width == 1:
        return "…"
    out: list[str] = []
    used = 0
    limit = max_width - 1
    for ch in text:
        cw = 0 if (unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf")) else (
            2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        )
        if used + cw > limit:
            break
        out.append(ch)
        used += cw
    return "".join(out).rstrip() + "…"


def _pad_display(text: str, width: int) -> str:
    """Right-pad `text` (which may contain ANSI codes) to `width` terminal columns."""
    pad = max(0, width - _display_width(text))
    return text + (" " * pad)


def _status_line_width() -> int:
    """Determine inner content width for `idd status` layout."""
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        cols = shutil.get_terminal_size((92, 24)).columns
        return max(72, min(104, cols)) - 4
    return 84


def _join_lr(left: str, right: str, total_width: int, min_gap: int = 2) -> str:
    """Join `left` and right-aligned `right` within `total_width` columns."""
    gap = max(min_gap, total_width - _display_width(left) - _display_width(right))
    return f"{left}{' ' * gap}{right}"


def _clean_stage_label(stage: str) -> str:
    """Strip leading emoji / variation selectors from a stage string."""
    idx = 0
    while idx < len(stage):
        ch = stage[idx]
        if ch.isspace() or unicodedata.category(ch) in ("So", "Mn", "Cf", "Sk"):
            idx += 1
        else:
            break
    return stage[idx:].strip() or stage.strip()


def _style_stage_badge(stage: str, use_color: bool) -> str:
    """Render a semantic `[stage]` badge using 16-color ANSI SGR."""
    raw_label = _clean_stage_label(stage) or "—"
    label = "待处理" if raw_label == "待认领" else raw_label
    badge = f"[{label}]"
    if label in {"修 CI", "受阻"}:
        return _ansi("1;31", badge, use_color)
    if label == "待合入" or label.startswith("待提"):
        return _ansi("1;32", badge, use_color)
    if label == "CI 运行中":
        return _ansi("1;33", badge, use_color)
    if label.startswith("草稿"):
        return _ansi("35", badge, use_color)
    if label == "待处理":
        return _ansi("2", badge, use_color)
    return _ansi("36", badge, use_color)


def _style_forge_badge(forge: str, use_color: bool) -> str:
    """Render a platform badge (`[GitHub]` / `[GitLab]` / `[Local]`)."""
    if forge == "github":
        return _ansi("36", "[GitHub]", use_color)
    if forge == "gitlab":
        return _ansi("33", "[GitLab]", use_color)
    return _ansi("2", "[Local]", use_color)


def _render_progress_bar(done: int, total: int, use_color: bool, width: int = 8) -> str:
    """Render a compact Unicode block progress bar with done/total and percentage."""
    if total <= 0:
        return _ansi("2", f"{'░' * width}  待拆解步骤", use_color)
    pct = round((done / total) * 100)
    filled = min(width, max(0, round((done / total) * width)))
    empty = width - filled
    bar_color = "32" if done == total else "36"
    bar_filled = _ansi(bar_color, "█" * filled, use_color) if filled else ""
    bar_empty = _ansi("2", "░" * empty, use_color) if empty else ""
    return f"{bar_filled}{bar_empty}  {done}/{total} {_ansi('2', f'({pct}%)', use_color)}"


def _style_pulse(pulse: dict[str, Any] | None, use_color: bool) -> tuple[str, str, bool]:
    """Return `(status_dot, formatted_pulse_text, is_stalled)` for a worktree pulse."""
    if not pulse:
        return _ansi("2", "○", use_color), _ansi("2", "—", use_color), False

    activity_state = str(pulse.get("activity_state") or "quiet")
    last_active_ago = str(pulse.get("last_active_ago") or "无记录")
    dirty_count = int(pulse.get("dirty_count") or 0)
    insertions = int(pulse.get("insertions") or 0)
    deletions = int(pulse.get("deletions") or 0)
    git_op = str(pulse.get("git_op") or "")
    is_stalled = activity_state == "stalled"

    if activity_state == "active":
        dot = _ansi("1;32", "●", use_color)
        time_label = "刚刚活跃" if last_active_ago == "刚刚" else last_active_ago
        time_txt = _ansi("32", time_label, use_color)
    elif activity_state == "warm":
        dot = _ansi("33", "●", use_color)
        time_txt = _ansi("33", last_active_ago, use_color)
    elif is_stalled:
        dot = _ansi("1;33", "▲", use_color)
        short_ago = last_active_ago[:-1] if last_active_ago.endswith("前") else last_active_ago
        time_txt = _ansi("1;33", f"{short_ago}无动静", use_color)
    else:
        dot = _ansi("2", "○", use_color)
        time_txt = _ansi("2", last_active_ago, use_color)

    parts = [time_txt]
    if git_op in ("rebasing", "merging"):
        parts.append(_ansi("1;35", git_op.upper(), use_color))

    if dirty_count > 0:
        dirty_txt = f"{dirty_count} 文件"
        if insertions > 0 or deletions > 0:
            ins_txt = _ansi("32", f"+{insertions}", use_color)
            del_txt = _ansi("31", f"-{deletions}", use_color)
            dirty_txt += f" ({ins_txt}/{del_txt})"
        parts.append(dirty_txt)
    else:
        parts.append(_ansi("2", "工作区干净", use_color))

    remote_state = str(pulse.get("remote_state") or "")
    unpushed = int(pulse.get("unpushed_commits") or 0)
    if remote_state == "unpushed_branch":
        parts.append(_ansi("1;33", "未推远端", use_color))
    elif unpushed > 0:
        parts.append(_ansi("1;33", f"↑{unpushed} 待推送", use_color))

    sep = _ansi("2", " · ", use_color)
    return dot, sep.join(parts), is_stalled


def _style_ci_badge(change: dict[str, Any], use_color: bool, *, stale: bool = False) -> str:
    """Format CI rollup status and mergeability conflict indicator."""
    overall = change.get("checks_overall") or "NONE"
    if stale:
        ci_badges = {
            "PASS": _ansi("33", "✓ CI 全绿 (待同步)", use_color),
            "FAIL": _ansi("1;31", "✗ CI 失败", use_color),
            "PENDING": _ansi("33", "◔ CI 运行中", use_color),
            "NONE": _ansi("33", "○ 无 CI (待同步)", use_color),
        }
    else:
        ci_badges = {
            "PASS": _ansi("32", "✓ CI 全绿", use_color),
            "FAIL": _ansi("1;31", "✗ CI 失败", use_color),
            "PENDING": _ansi("33", "◔ CI 运行中", use_color),
            "NONE": _ansi("2", "○ 无 CI", use_color),
        }
    ci_txt = ci_badges.get(overall, str(overall))
    mstate = change.get("mergeStateStatus") or ""
    extra = _ansi("1;31", " (落后/冲突)", use_color) if mstate in {"BEHIND", "DIRTY"} else ""
    return f"{ci_txt}{extra}"


def _style_change(change: dict[str, Any], mr_label: str, mr_prefix: str, use_color: bool, *, stale: bool = False) -> str:
    """Format PR/MR reference, Draft tag, CI status, and mergeability state."""
    num = change.get("number")
    ref_raw = f"{mr_label} {mr_prefix}{num}" if num else mr_label
    ref = _ansi("1", ref_raw, use_color)
    if change.get("isDraft"):
        ref += _ansi("35", " (Draft)", use_color)
    ci_txt = _style_ci_badge(change, use_color, stale=stale)
    sep = _ansi("2", " · ", use_color)
    return f"{ref}{sep}{ci_txt}"


def _render_kpi_strip(summary: dict[str, Any], *, include_repos: bool, use_color: bool) -> str:
    """Render a compact single-line telemetry summary strip."""
    parts: list[str] = []
    if include_repos:
        rc = int(summary.get("repo_count") or 0)
        rc_val = _ansi("1", str(rc), use_color) if rc > 0 else _ansi("2", "0", use_color)
        parts.append(f"{_ansi('2', '仓库', use_color)} {rc_val}")

    wt = int(summary.get("active_worktrees") or 0)
    coding = int(summary.get("coding_now_count") or 0)
    wt_val = _ansi("1", str(wt), use_color) if wt > 0 else _ansi("2", "0", use_color)
    wt_str = f"{_ansi('2', '已开工', use_color)} {wt_val}"
    if coding > 0:
        wt_str += f" {_ansi('32', f'(活跃 {coding})', use_color)}"
    parts.append(wt_str)

    in_prog = int(summary.get("in_progress_tasks") or 0)
    in_prog_val = _ansi("1;36", str(in_prog), use_color) if in_prog > 0 else _ansi("2", "0", use_color)
    parts.append(f"{_ansi('2', '进行中步骤', use_color)} {in_prog_val}")

    ready = int(summary.get("ready_to_land_count") or 0)
    ready_val = _ansi("1;32", str(ready), use_color) if ready > 0 else _ansi("2", "0", use_color)
    parts.append(f"{_ansi('2', '待合入', use_color)} {ready_val}")

    anomalies = int(summary.get("stalled_worktrees") or 0) + int(summary.get("ci_failed_count") or 0)
    anom_val = _ansi("1;31", str(anomalies), use_color) if anomalies > 0 else _ansi("2", "0", use_color)
    parts.append(f"{_ansi('2', '异常', use_color)} {anom_val}")

    return _ansi("2", "  ·  ", use_color).join(parts)


def _task_status_glyph(status: str, use_color: bool) -> str:
    """Return a colored single-cell status symbol for a TASK item."""
    mapping = {
        "in_progress": ("1;36", "◐"),
        "blocked": ("1;31", "✗"),
        "planned": ("2", "○"),
        "deferred": ("33", "◌"),
        "cancelled": ("2", "⊘"),
    }
    code, glyph = mapping.get(status, ("1;33", "?"))
    return _ansi(code, glyph, use_color)


def _render_status_card(
    *,
    ident: str,
    ident_style: str,
    title: str,
    stage: str,
    branch: str,
    worktree: str,
    tasks: list[dict[str, Any]],
    counts: dict[str, int],
    done: int | None,
    total: int | None,
    current_task: str,
    pulse: dict[str, Any] | None,
    change: dict[str, Any] | None,
    change_stale: bool = False,
    mr_label: str,
    mr_prefix: str,
    width: int,
    use_color: bool,
) -> list[str]:
    """Render one clean, lightweight Issue or local-worktree block."""
    dot, pulse_text, is_stalled = _style_pulse(pulse, use_color)
    stage_badge = _style_stage_badge(stage, use_color)
    ident_styled = _ansi(ident_style, ident, use_color)
    left_prefix = f"  {dot} {ident_styled}  "
    title_budget = max(16, width - _display_width(left_prefix) - _display_width(stage_badge) - 2)
    single_title = " ".join((title or "未命名任务").split())
    title_styled = _ansi("1", _truncate_display(single_title, title_budget), use_color)

    lines = [_join_lr(f"{left_prefix}{title_styled}", stage_badge, width + 2)]
    indent = "    "
    inner_budget = max(24, width - 2)
    sep = _ansi("2", "  ·  ", use_color)

    meta_parts: list[str] = []
    if branch or worktree:
        br_txt = branch or Path(worktree).name
        meta_parts.append(_ansi("36", _truncate_display(br_txt, 42), use_color))
    if change:
        meta_parts.append(_style_change(change, mr_label, mr_prefix, use_color, stale=change_stale))
    if meta_parts:
        lines.append(f"{indent}{sep.join(meta_parts)}")

    has_tasks_section = bool(tasks or worktree or (total is not None and total > 0))
    if has_tasks_section:
        t_total = total if total is not None else (sum(int(v) for v in counts.values()) or len(tasks))
        t_done = done if done is not None else int(counts.get("done") or 0)
        bar = _render_progress_bar(t_done, t_total, use_color)
        if current_task:
            cur_budget = max(12, inner_budget - _display_width(bar) - 7)
            cur_trunc = _truncate_display(current_task, cur_budget)
            progress_val = f"{bar}{sep}{_ansi('36', '▶', use_color)} {cur_trunc}"
        else:
            progress_val = bar
        lines.append(f"{indent}{progress_val}")

    if pulse:
        pulse_line = f"{_ansi('2', '实时脉搏:', use_color)} {pulse_text}"
        if pulse.get("last_commit_sha"):
            sha_raw = str(pulse["last_commit_sha"])
            subj_raw = " ".join(str(pulse.get("last_commit_subject") or "").split())
            sha_styled = _ansi("36", sha_raw, use_color)
            rem = inner_budget - _display_width(pulse_line) - 5 - _display_width(sha_raw) - 1
            if subj_raw and rem >= 10:
                commit_part = f"{sha_styled} {_ansi('2', _truncate_display(subj_raw, rem), use_color)}"
            else:
                commit_part = sha_styled
            pulse_line = f"{pulse_line}{sep}{commit_part}"
        lines.append(f"{indent}{pulse_line}")
        if is_stalled:
            lines.append(f"{indent}{_ansi('1;33', '!', use_color)} {_ansi('33', '超过 30 分钟无动静，可能在等待确认或卡住了', use_color)}")

    return lines


def _render_repo_status_body(snap: dict[str, Any], *, width: int, use_color: bool) -> list[str]:
    """Render one repository's active cards, orphan PR/MRs, backlog, and remaining TASK list."""
    rows = snap.get("issues") or []
    local_only_items = snap.get("local_only_items") or []
    orphan_changes = snap.get("orphan_changes") or []
    local_entries = snap.get("tasks") or []
    retained = snap.get("retained_idle_worktrees") or []
    mr_label = snap.get("mr_label", "PR/MR")
    mr_prefix = snap.get("mr_prefix", "#")

    active_rows = [r for r in rows if r.get("worktree") or r.get("change") or r.get("tasks")]
    backlog_rows = [r for r in rows if not (r.get("worktree") or r.get("change") or r.get("tasks"))]

    lines: list[str] = []

    for idx, row in enumerate(active_rows):
        if idx > 0:
            lines.append("")
        lines.extend(
            _render_status_card(
                ident=f"#{row['issue_number']}",
                ident_style="1;36",
                title=str(row.get("title") or ""),
                stage=str(row.get("stage") or ""),
                branch=str(row.get("branch") or ""),
                worktree=str(row.get("worktree") or ""),
                tasks=row.get("tasks") or [],
                counts=row.get("counts") or {},
                done=None,
                total=None,
                current_task=str(row.get("current_task") or ""),
                pulse=row.get("pulse"),
                change=row.get("change"),
                change_stale=bool(row.get("change_stale")),
                mr_label=mr_label,
                mr_prefix=mr_prefix,
                width=width,
                use_color=use_color,
            )
        )

    for loc in local_only_items:
        if lines:
            lines.append("")
        loc_counts = loc.get("counts") or {}
        loc_stage = "⛔ 受阻" if loc_counts.get("blocked", 0) > 0 else "🟡 本地开发"
        lines.extend(
            _render_status_card(
                ident="[本地]",
                ident_style="35",
                title=str(loc.get("issue") or "本地工作项"),
                stage=loc_stage,
                branch=str(loc.get("branch") or ""),
                worktree=str(loc.get("worktree") or ""),
                tasks=loc.get("tasks") or [],
                counts=loc_counts,
                done=int(loc.get("done") or 0),
                total=int(loc.get("total") or 0),
                current_task=str(loc.get("current_task") or ""),
                pulse=loc.get("pulse"),
                change=None,
                mr_label=mr_label,
                mr_prefix=mr_prefix,
                width=width,
                use_color=use_color,
            )
        )

    if orphan_changes:
        if lines:
            lines.append("")
        lines.append(f"  {_ansi('2', f'未关联本地目录的 {mr_label} ({len(orphan_changes)})', use_color)}")
        for ch in orphan_changes:
            num_txt = _ansi("1", f"{mr_label} {mr_prefix}{ch['number']}", use_color)
            if ch.get("isDraft"):
                num_txt += _ansi("35", " (Draft)", use_color)
            ch_title = _truncate_display(" ".join(str(ch.get("title") or "").split()), max(16, width - 38))
            br = ch.get("headRefName") or ""
            br_part = f"  {_ansi('2', f'({br})', use_color)}" if br else ""
            ci_part = _style_ci_badge(ch, use_color)
            lines.append(f"    {_ansi('36', '▸', use_color)} {num_txt}  {ch_title}{br_part}{_ansi('2', '  ·  ', use_color)}{ci_part}")

    if backlog_rows:
        if lines:
            lines.append("")
        lines.append(f"  {_ansi('2', f'待处理 Issue ({len(backlog_rows)})', use_color)}")
        for row in backlog_rows:
            num_txt = _ansi("2", f"#{row['issue_number']}", use_color)
            title_txt = _truncate_display(" ".join(str(row.get("title") or "").split()), max(20, width - 14))
            lines.append(f"    {_ansi('2', '○', use_color)} {num_txt}  {title_txt}")

    remaining = [(item, t) for item in local_entries for t in item.get("tasks", []) if t["status"] != "done"]
    if remaining:
        if lines:
            lines.append("")
        lines.append(f"  {_ansi('2', f'未完成步骤 ({len(remaining)})', use_color)}")
        for item, t in remaining:
            glyph = _task_status_glyph(t["status"], use_color)
            issue_prefix = f"#{item['issue_number']} " if item.get("issue_number") is not None else ""
            ref_txt = _ansi("2", f"{issue_prefix}{item['issue']}/{t['id']}", use_color)
            clean_title = re.sub(rf"^{re.escape(t['id'])}[：:\s]+", "", str(t.get("title") or "")).strip()
            title_txt = _truncate_display(clean_title or str(t.get("title") or ""), max(16, width - 36))
            st_label = t["status"]
            if st_label == "unknown":
                st_label += f" ({t.get('raw_status') or '缺失'})"
            dep = t.get("depends_on") or ""
            dep_part = _ansi("2", f" · 依赖: {dep}", use_color) if dep and dep.lower() != "none" else ""
            lines.append(f"    {glyph} {ref_txt}  {title_txt}  {_ansi('2', f'[{st_label}]', use_color)}{dep_part}")

    if retained:
        if lines:
            lines.append("")
        lines.append(
            f"  {_ansi('36', 'ℹ', use_color)}  "
            f"{_ansi('2', f'已合入保留的干净工作树：{len(retained)} 个（按需运行 idd cleanup 清理）', use_color)}"
        )

    if not lines:
        lines.append(f"  {_ansi('2', '○  当前没有活跃的 Issue、本地 Worktree 任务或 Open PR/MR。', use_color)}")

    return lines


def _render_warnings_block(warnings: list[str], *, use_color: bool) -> list[str]:
    if not warnings:
        return []
    out = ["", f"  {_ansi('1;33', '!', use_color)}  {_ansi('33', '提示 / 记录问题', use_color)}"]
    for w in warnings:
        out.append(f"    {_ansi('33', '-', use_color)} {_ansi('2', w, use_color)}")
    return out


def _render_status_footer(width: int, *, use_color: bool) -> list[str]:
    return [
        "",
        f"  {_ansi('2', '─' * width, use_color)}",
        (
            f"  {_ansi('36', 'ℹ', use_color)}  "
            f"{_ansi('2', '网页实时看板: ', use_color)}{_ansi('36', 'idd board', use_color)}"
            f"{_ansi('2', '  ·  终端盯盘: ', use_color)}{_ansi('36', 'idd watch', use_color)}"
        ),
        "",
    ]


def _render_global_status(snapshot: dict[str, Any], *, use_color: bool) -> str:
    width = _status_line_width()
    s = snapshot.get("summary") or {}
    auto_merge_on = bool((snapshot.get("config") or {}).get("auto_merge"))
    am_badge = f"  {_ansi('2', '·', use_color)}  {_ansi('32', '自动合入: 开', use_color)}" if auto_merge_on else ""
    lines = [
        "",
        (
            f"  {_ansi('1;36', '◆', use_color)} {_ansi('1', 'IDD', use_color)}  "
            f"{_ansi('36', '全局 IDD 进度总览', use_color)}  "
            f"{_ansi('2', f'·  v{__version__}', use_color)}{am_badge}"
        ),
        f"  {_ansi('2', '─' * width, use_color)}",
        f"  {_render_kpi_strip(s, include_repos=True, use_color=use_color)}",
    ]

    repos = snapshot.get("repos") or []
    if not repos:
        lines.extend([
            "",
            f"  {_ansi('2', '○  暂无已注册仓库。可在任意 Git 项目目录运行以下命令自动纳入监控：', use_color)}",
            f"     {_ansi('36', 'idd start <issue#>', use_color)}  {_ansi('2', '·', use_color)}  "
            f"{_ansi('36', 'idd status', use_color)}  {_ansi('2', '·', use_color)}  "
            f"{_ansi('36', 'idd repos add .', use_color)}",
        ])
    else:
        for repo in repos:
            forge_badge = _style_forge_badge(str(repo.get("forge") or "local"), use_color)
            pretty_repo_path = _pretty_path(Path(str(repo.get("repo_path") or "")))
            lines.extend([
                "",
                (
                    f"  {_ansi('1;34', '▸', use_color)} {_ansi('1', str(repo.get('repo_name') or ''), use_color)}  "
                    f"{forge_badge}  {_ansi('2', pretty_repo_path, use_color)}"
                ),
                f"  {_ansi('2', '─' * width, use_color)}",
                *_render_repo_status_body(repo, width=width, use_color=use_color),
            ])

    lines.extend(_render_warnings_block(snapshot.get("warnings") or [], use_color=use_color))
    lines.extend(_render_status_footer(width, use_color=use_color))
    return "\n".join(lines)


def _render_single_repo_status(snap: dict[str, Any], *, use_color: bool) -> str:
    width = _status_line_width()
    summary = monitor._compute_global_summary(  # noqa: SLF001
        [snap],
        snap.get("issues") or [],
        snap.get("local_only_items") or [],
        snap.get("orphan_changes") or [],
    )
    forge_badge = _style_forge_badge(str(snap.get("forge") or "local"), use_color)
    pretty_repo_path = _pretty_path(Path(str(snap.get("repo_path") or "")))
    default_branch = str(snap.get("default_branch") or "main")
    am_info = snap.get("auto_merge") or {}
    am_suffix = (
        f"  ·  {_ansi('32', '自动合入: 开' + (' (仓库)' if am_info.get('source') == 'repo' else ' (全局)'), use_color)}"
        if am_info.get("enabled")
        else ""
    )

    lines = [
        "",
        (
            f"  {_ansi('1;36', '◆', use_color)} {_ansi('1', 'IDD', use_color)}  "
            f"{_ansi('36', '仓库状态总览', use_color)}  "
            f"{_ansi('2', '·', use_color)}  {_ansi('1', str(snap.get('repo_name') or ''), use_color)}  "
            f"{forge_badge}"
        ),
        f"  {_ansi('2', f'{pretty_repo_path}  ·  {default_branch}', use_color)}{am_suffix}",
        f"  {_ansi('2', '─' * width, use_color)}",
        f"  {_render_kpi_strip(summary, include_repos=False, use_color=use_color)}",
        "",
        *_render_repo_status_body(snap, width=width, use_color=use_color),
    ]
    lines.extend(_render_warnings_block(snap.get("warnings") or [], use_color=use_color))
    lines.extend(_render_status_footer(width, use_color=use_color))
    return "\n".join(lines)


def cmd_status(args: argparse.Namespace) -> int:
    explicit_root = args.root is not None
    root = (args.root or Path.cwd()).resolve()

    use_global = bool(args.global_mode)
    if not use_global and not explicit_root:
        if monitor.resolve_main_worktree_ro(root) is None and not (root / "TASK").is_dir():
            use_global = True

    if use_global:
        snapshot = monitor.collect_global_snapshot(
            current_cwd=root if explicit_root else Path.cwd(),
            open_only=args.open_only,
            local_only=args.local_only,
        )
        if args.json:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            print(_render_global_status(snapshot, use_color=_should_use_color(sys.stdout)))
        return 0

    try:
        snap = monitor.collect_repo_snapshot(
            root,
            issue_filter=args.issue,
            open_only=args.open_only,
            local_only=args.local_only,
            register=True,
        )
    except ValueError as exc:
        raise IddError(str(exc)) from exc

    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        return 0

    print(_render_single_repo_status(snap, use_color=_should_use_color(sys.stdout)))
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    global_mode = not args.current_only and args.root is None
    root: Path | None = None
    if not global_mode:
        root = (args.root or Path.cwd()).resolve()
        if monitor.resolve_main_worktree_ro(root) is None and not (root / "TASK").is_dir():
            raise IddError(f"当前路径既不是 Git 仓库，也不存在 TASK/ 目录：{root}")
    return board_ui.run_board_server(
        host=args.host,
        port=args.port,
        root=root,
        global_mode=global_mode,
        local_only=args.local_only,
        forge_ttl=args.forge_ttl,
        no_open=args.no_open,
        version=__version__,
    )


def cmd_preview(args: argparse.Namespace) -> int:
    try:
        return preview_ui.run_preview_server(
            targets=list(args.targets),
            title=args.title,
            compare=bool(args.compare),
            host=args.host,
            port=args.port,
            no_open=bool(args.no_open),
            version=__version__,
        )
    except preview_ui.PreviewError as exc:
        raise IddError(str(exc)) from exc


def cmd_watch(args: argparse.Namespace) -> int:
    global_mode = False if (args.current_only or (args.root is not None and not args.global_mode)) else True
    root: Path | None = None
    if not global_mode:
        root = (args.root or Path.cwd()).resolve()
        if monitor.resolve_main_worktree_ro(root) is None and not (root / "TASK").is_dir():
            raise IddError(f"当前路径既不是 Git 仓库，也不存在 TASK/ 目录：{root}")
    return monitor.run_watch_loop(
        root=root,
        global_mode=global_mode,
        interval=args.interval,
        forge_ttl=args.forge_ttl,
        local_only=args.local_only,
        open_only=args.open_only,
        once=args.once,
    )


def cmd_repos(args: argparse.Namespace) -> int:
    subcmd = args.repos_command or "list"
    now = time.time()

    if subcmd == "list":
        entries = monitor.load_registered_repos(prune_missing=True)
        payload = {"repos_config_path": str(monitor.get_repos_path()), "repos": entries}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        lines = [f"全局仓库索引：{monitor.get_repos_path()}"]
        if not entries:
            lines.append("- 暂无已注册仓库（可在仓库内运行 `idd start`、`idd status` 或 `idd repos add .`）。")
        else:
            for item in entries:
                ts = float(item.get("last_seen_at") or 0.0)
                ago = monitor.format_relative_time(max(0.0, now - ts)) if ts > 0 else "无记录"
                init_state = item.get("repo_init_state")
                init_tag = " [待初始化策略: idd repo-init --apply]" if init_state in ("pending", "prompted") else ""
                am_val = item.get("auto_merge")
                am_tag = f" [auto-merge: {'on' if am_val else 'off'}]" if isinstance(am_val, bool) else ""
                lines.append(f"- {item['name']} ({ago}): {item['path']}{init_tag}{am_tag}")
        print("\n".join(lines))
        return 0

    if subcmd == "add":
        added: list[dict[str, Any]] = []
        hints: list[str] = []
        auto_apply = not bool(getattr(args, "no_repo_init", False))
        for raw in args.paths:
            main_wt = monitor.resolve_main_worktree_ro(Path(raw))
            if main_wt is None:
                raise IddError(f"路径不是有效的 Git 仓库：{raw}")
            entry = monitor.register_repo(main_wt)
            has_origin = run_cmd(["git", "-C", str(main_wt), "remote", "get-url", "origin"], check=False).returncode == 0
            hint = _maybe_check_first_time_repo_init(main_wt, has_origin=has_origin, auto_apply=auto_apply)
            if hint:
                entry = dict(entry)
                entry["repo_init_hint"] = hint
                hints.append(hint["message"])
            added.append(entry)
        if args.json:
            print(json.dumps({"added": added}, ensure_ascii=False, indent=2))
        else:
            for entry in added:
                print(f"已注册仓库：{entry['name']} ({entry['path']})")
            for msg in hints:
                print(msg)
        return 0

    if subcmd == "remove":
        target = Path(args.path)
        removed = monitor.unregister_repo(target)
        if not removed:
            raise IddError(f"未在全局索引中找到仓库：{args.path}")
        if args.json:
            print(json.dumps({"removed": str(target.expanduser().resolve())}, ensure_ascii=False, indent=2))
        else:
            print(f"已移除仓库索引：{target.expanduser().resolve()}")
        return 0

    if subcmd == "prune":
        before = monitor.load_registered_repos(prune_missing=False)
        after = monitor.load_registered_repos(prune_missing=True)
        removed_count = max(0, len(before) - len(after))
        if args.json:
            print(json.dumps({"removed_count": removed_count, "remaining": len(after)}, ensure_ascii=False, indent=2))
        else:
            print(f"已清理 {removed_count} 个失效仓库记录，当前保留 {len(after)} 个活跃仓库。")
        return 0

    raise IddError(f"未知 repos 子命令：{subcmd}")


def _maybe_check_first_time_repo_init(
    main_worktree: Path,
    *,
    has_origin: bool,
    forge: Any | None = None,
    auto_apply: bool = True,
) -> dict[str, Any] | None:
    """Probe remote merge policy once per repository and auto-apply or mark pending."""
    if not has_origin:
        return None
    prev_meta = monitor.get_repo_init_meta(main_worktree)
    if prev_meta["state"] in ("aligned", "pending"):
        return None
    try:
        active_forge = forge if forge is not None else get_forge(main_worktree)
        result = active_forge.repo_init(apply=False)
    except Exception:
        return None

    aligned, mismatches = evaluate_repo_init_settings(result)
    if aligned:
        monitor.set_repo_init_meta(main_worktree, "aligned")
        return None

    forge_type = str(result.get("forge") or "github")
    forge_name = "GitLab" if forge_type == "gitlab" else "GitHub"
    repo_slug = str(result.get("repo") or "")
    policy_desc = (
        "「仅 Fast-Forward + Squash 且保留分支」与默认压缩提交模板"
        if forge_type == "gitlab"
        else "「仅 Squash 直线合入且保留分支」与默认 PR 提交模板"
    )

    if not auto_apply:
        monitor.set_repo_init_meta(main_worktree, "pending", mismatches=mismatches)
        message = (
            f"💡 首次接管提示：已跳过自动初始化 {forge_name} 仓库线性 Squash 策略（{'、'.join(mismatches)}）。\n"
            f"   已标记为待初始化，可在 `idd ui` 一键执行或稍后运行 `idd repo-init --apply` 锁定{policy_desc}。"
        )
        return {
            "status": "skipped",
            "forge": forge_type,
            "repo": repo_slug,
            "mismatches": mismatches,
            "command": "idd repo-init --apply",
            "message": message,
        }

    try:
        applied_result = active_forge.repo_init(apply=True)
    except Exception as exc:
        err_msg = str(exc)
        monitor.set_repo_init_meta(main_worktree, "pending", mismatches=mismatches, error=err_msg)
        message = (
            f"⚠️ 首次接管自动执行 `idd repo-init --apply` 未完成（{err_msg}）；"
            f"已标记为待初始化，可在 `idd ui` 点击重试或稍后手动运行 `idd repo-init --apply`。"
        )
        return {
            "status": "failed",
            "forge": forge_type,
            "repo": repo_slug,
            "mismatches": mismatches,
            "error": err_msg,
            "command": "idd repo-init --apply",
            "message": message,
        }

    aligned_after, remaining = evaluate_repo_init_settings(applied_result)
    if aligned_after:
        monitor.set_repo_init_meta(main_worktree, "aligned")
        return {
            "status": "applied",
            "forge": forge_type,
            "repo": repo_slug,
            "mismatches": [],
            "command": "idd repo-init --apply",
            "message": f"✅ 首次接管已自动初始化 {forge_name} 仓库线性 Squash 策略与提交模板。",
        }

    monitor.set_repo_init_meta(main_worktree, "pending", mismatches=remaining)
    message = (
        f"⚠️ 首次接管已尝试执行 `idd repo-init --apply`，但仍有未对齐项（{'、'.join(remaining)}）；"
        f"已在 `idd ui` 保留待初始化提示，可随时点击重试。"
    )
    return {
        "status": "pending",
        "forge": forge_type,
        "repo": repo_slug,
        "mismatches": remaining,
        "command": "idd repo-init --apply",
        "message": message,
    }


def _validate_issue_scope(raw_scope: str) -> str:
    """Validate and normalize an optional short Issue scope token (<= 16 chars, kebab-case)."""
    cleaned = raw_scope.strip().lower()
    if not cleaned:
        raise IddError("Issue 标题括号中的 scope 不能为空；不需要作用域时请省略括号。")
    if len(cleaned) > MAX_ISSUE_SCOPE_LEN or not ISSUE_SCOPE_RE.fullmatch(cleaned):
        raise IddError(
            f"Issue 标题括号中的 scope `{raw_scope.strip()}` 不符合规范。\n"
            f"括号内容必须简短：仅允许单个小写英文/数字/连字符标识（`a-z0-9-`，最多 {MAX_ISSUE_SCOPE_LEN} 字符），"
            "不含空格、逗号、斜杠或中文（如 `sync`、`land`、`repo-init`）；跨模块改动请直接省略括号。"
        )
    return cleaned


def validate_and_format_issue_title(
    raw_title: str,
    *,
    issue_type: str | None = None,
    scope: str | None = None,
    raw: bool = False,
) -> str:
    """Validate and normalize an Issue title against `<type>(<scope>): <subject>` rules."""
    cleaned = raw_title.strip()
    if not cleaned:
        raise IddError("Issue 标题不能为空。")
    if "\n" in cleaned or "\r" in cleaned:
        raise IddError("Issue 标题必须为单行文本。")

    if raw:
        if issue_type is not None or scope is not None:
            raise IddError("`--raw` 不能与 `--type` 或 `--scope` 同时使用。")
        return cleaned

    norm_type: str | None = None
    if issue_type is not None:
        norm_type = issue_type.strip().lower()
        if norm_type not in ALLOWED_TYPES:
            raise IddError(f"非法的 Issue 类型 `{issue_type}`，允许值：{' | '.join(ALLOWED_TYPES)}")

    norm_scope: str | None = _validate_issue_scope(scope) if scope is not None else None

    if EMPTY_SCOPE_PREFIX_RE.match(cleaned):
        _validate_issue_scope("")

    match = CONVENTIONAL_TITLE_RE.match(cleaned)
    if match:
        parsed_type = match.group(1).lower()
        raw_scope_group = match.group(2)
        parsed_scope = _validate_issue_scope(raw_scope_group[1:-1]) if raw_scope_group else None
        bang = match.group(3) or ""
        subject = match.group(4).strip()
        if not subject:
            raise IddError("Issue 标题冒号后的描述不能为空。")
        if norm_type is not None and norm_type != parsed_type:
            raise IddError(f"传入的 `--type {norm_type}` 与标题前缀 `{parsed_type}` 冲突。")
        if norm_scope is not None and parsed_scope is not None and norm_scope != parsed_scope:
            raise IddError(f"传入的 `--scope {norm_scope}` 与标题括号中的 `{parsed_scope}` 冲突。")
        final_type = norm_type or parsed_type
        final_scope = norm_scope or parsed_scope
        scope_part = f"({final_scope})" if final_scope else ""
        return f"{final_type}{scope_part}{bang}: {subject}"

    if norm_type is not None:
        scope_part = f"({norm_scope})" if norm_scope else ""
        return f"{norm_type}{scope_part}: {cleaned}"

    allowed_str = " | ".join(ALLOWED_TYPES)
    raise IddError(
        f"Issue 标题 `{cleaned}` 不符合 IDD 命名规范。\n"
        "请使用 `<type>: <简明描述>` 或 `<type>(<scope>): <简明描述>`（建议 ≤ 50 字符，不重复类型动词）。\n"
        f"允许的 `<type>`：{allowed_str}\n"
        f"可选 `(<scope>)` 须简短：单个小写英文/数字/连字符标识（≤ {MAX_ISSUE_SCOPE_LEN} 字符，如 `sync`、`land`）。\n"
        "示例：`idd issue create --title \"fix(sync): 避免误匹配行内标记\"`\n"
        "或自动拼接：`idd issue create --type fix --scope sync --title \"避免误匹配行内标记\"`\n"
        "若确需使用非规范标题，请显式传入 `--raw`。"
    )


def _infer_prefix_from_title(title: str) -> str | None:
    """Extract standard `<type>` prefix from a Conventional-style Issue title."""
    match = CONVENTIONAL_TITLE_RE.match(title.strip())
    if not match:
        return None
    return match.group(1).lower()


def _slug_source_from_issue_title(title: str) -> str:
    """Strip Conventional `<type>:` prefix when deriving a worktree/branch slug."""
    cleaned = title.strip()
    match = CONVENTIONAL_TITLE_RE.match(cleaned)
    if not match:
        return cleaned
    scope = (match.group(2) or "").strip("()").strip()
    subject = match.group(4).strip()
    return f"{scope} {subject}".strip() if scope else subject


def cmd_issue_create(args: argparse.Namespace) -> int:
    title = validate_and_format_issue_title(
        args.title,
        issue_type=getattr(args, "issue_type", None),
        scope=getattr(args, "scope", None),
        raw=getattr(args, "raw", False),
    )
    repo = get_repo_info(Path.cwd())
    forge = get_forge(repo.main_worktree)
    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    created = forge.create_issue(title, body=body, labels=args.label, assignees=args.assignee)
    hint = _maybe_check_first_time_repo_init(
        repo.main_worktree,
        has_origin=repo.has_origin,
        forge=forge,
        auto_apply=not bool(getattr(args, "no_repo_init", False)),
    )
    if args.json:
        if hint:
            created = dict(created)
            created["repo_init_hint"] = hint
        print(json.dumps(created, ensure_ascii=False, indent=2))
    else:
        num = created.get("number")
        num_str = f"#{num} " if num is not None else ""
        print(f"已创建 Issue {num_str}: {created.get('url', '')}")
        if hint:
            print(hint["message"])
    return 0


def _infer_prefix_from_labels(labels: set[str]) -> str:
    """Map Issue labels to one of the 8 standard branch/commit types."""
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
        issue_dir, issue_num = _infer_issue_dir_and_number(wt_path, branch, args.target)
        validate_branch_name(branch, issue_num, wt_path)
        _fix_misbound_upstream(wt_path, branch, repo.default_branch)

        pushed = False
        newly_pushed = False
        push_warning = ""
        if repo.has_origin:
            remote_exists = _ref_exists(repo.main_worktree, f"refs/remotes/origin/{branch}")
            if not remote_exists and not args.no_push:
                pushed, push_warning = _push_feature_branch(wt_path, branch, default_branch=repo.default_branch)
                if pushed:
                    newly_pushed = True
                else:
                    print(
                        f"⚠️ 自动推送分支 `{branch}` 至远端失败（已保留本地工作树）：{push_warning}\n"
                        f"请稍后在工作树中执行：git -C {wt_path} push -u origin HEAD",
                        file=sys.stderr,
                    )
            elif remote_exists:
                up_proc = run_cmd(
                    ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                    check=False,
                )
                if up_proc.returncode != 0 or not up_proc.stdout.strip():
                    run_cmd(["git", "-C", str(wt_path), "branch", f"--set-upstream-to=origin/{branch}"], check=False)
                pushed = True

        st = run_cmd(["git", "-C", str(wt_path), "status", "--short"], check=False).stdout.strip()
        log_out = run_cmd(["git", "-C", str(wt_path), "log", "-5", "--oneline"], check=False).stdout.strip()
        task_summary = None
        if (wt_path / "TASK").is_dir() and issue_dir and (wt_path / "TASK" / issue_dir).is_dir():
            task_summary = task_status.collect(wt_path / "TASK", issue_dir, open_only=False)
        payload: dict[str, Any] = {
            "reused": True,
            "worktree": str(wt_path),
            "branch": branch,
            "issue": issue_dir,
            "issue_number": issue_num,
            "pushed": pushed,
            "git_status": st,
            "recent_commits": log_out.splitlines() if log_out else [],
            "tasks": task_summary,
        }
        if push_warning:
            payload["push_warning"] = push_warning
        hint = _maybe_check_first_time_repo_init(
            repo.main_worktree,
            has_origin=repo.has_origin,
            auto_apply=not bool(getattr(args, "no_repo_init", False)),
        )
        if hint:
            payload["repo_init_hint"] = hint
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            lines = [
                f"复用已有工作树（支持跨工具无缝接手）：{wt_path}",
                f"分支：{branch}",
                f"任务目录：TASK/{issue_dir}/",
                f"工作区状态：{st or '干净'}",
            ]
            if newly_pushed:
                lines.append(f"已补推分支至远端：origin/{branch}")
            if log_out:
                lines.append("最近提交：")
                lines.extend(f"  {line}" for line in log_out.splitlines())
            if task_summary and task_summary["issues"]:
                lines.append("")
                lines.append(task_status.render(task_summary))
            if hint:
                lines.append(hint["message"])
            print("\n".join(lines))
        return 0

    issue_num = parse_issue_ref(args.target)
    issue_data: dict[str, Any] | None = None
    forge_for_hint: Any | None = None
    if issue_num is not None:
        forge = get_forge(repo.main_worktree)
        forge_for_hint = forge
        issue_data = forge.get_issue(issue_num)
        issue_title = str(issue_data.get("title", ""))
        slug = slugify(args.slug, "") if args.slug else slugify(_slug_source_from_issue_title(issue_title), "task")
        issue_dir = f"{issue_num}-{slug}"
        labels = {str(lbl).lower() for lbl in issue_data.get("labels", [])}
        prefix = args.prefix or _infer_prefix_from_title(issue_title) or _infer_prefix_from_labels(labels)
        branch = f"{prefix}/{issue_dir}"
    else:
        raw_target = args.target.strip()
        inferred_prefix: str | None = None
        if "/" in raw_target:
            raw_prefix, raw_rest = raw_target.split("/", 1)
            if raw_prefix.lower() not in ALLOWED_TYPES:
                validate_branch_name(raw_target)
            inferred_prefix = raw_prefix.lower()
            raw_target = raw_rest
        issue_dir = slugify(args.slug or raw_target, "task")
        prefix = args.prefix or inferred_prefix or "feat"
        branch = f"{prefix}/{issue_dir}"

    validate_branch_name(branch, issue_num)

    if repo.has_origin:
        run_cmd(["git", "-C", str(repo.main_worktree), "fetch", "origin", repo.default_branch], check=False)

    base_ref = _resolve_base_ref(repo, args.base)
    repo.worktree_root.mkdir(parents=True, exist_ok=True)
    wt_path = repo.worktree_root / issue_dir

    if wt_path.exists():
        raise IddError(f"目标目录已存在但未注册为 Git 工作树：{wt_path}")

    if _ref_exists(repo.main_worktree, f"refs/heads/{branch}"):
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "add", str(wt_path), branch])
    elif repo.has_origin and _ref_exists(repo.main_worktree, f"refs/remotes/origin/{branch}"):
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "add", "-b", branch, str(wt_path), f"origin/{branch}"])
    else:
        run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "add", "--no-track", "-b", branch, str(wt_path), base_ref])

    copied = sync_worktree_includes(repo.main_worktree, wt_path)
    _fix_misbound_upstream(wt_path, branch, repo.default_branch)

    pushed = False
    push_warning = ""
    if repo.has_origin and not args.no_push:
        pushed, push_warning = _push_feature_branch(wt_path, branch, default_branch=repo.default_branch)
        if not pushed:
            print(
                f"⚠️ 自动推送分支 `{branch}` 至远端失败（已保留本地工作树）：{push_warning}\n"
                f"请稍后在工作树中执行：git -C {wt_path} push -u origin HEAD",
                file=sys.stderr,
            )

    payload: dict[str, Any] = {
        "reused": False,
        "worktree": str(wt_path),
        "branch": branch,
        "issue": issue_dir,
        "issue_number": issue_num,
        "base_ref": base_ref,
        "copied_includes": copied,
        "pushed": pushed,
        "issue_detail": issue_data,
    }
    if push_warning:
        payload["push_warning"] = push_warning
    hint = _maybe_check_first_time_repo_init(
        repo.main_worktree,
        has_origin=repo.has_origin,
        forge=forge_for_hint,
        auto_apply=not bool(getattr(args, "no_repo_init", False)),
    )
    if hint:
        payload["repo_init_hint"] = hint
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        lines = [
            f"已创建独立工作树：{wt_path}",
            f"分支：{branch} (基于 {base_ref})",
            f"TASK 目录建议：TASK/{issue_dir}/",
        ]
        if pushed:
            lines.append(f"已推送分支至远端：origin/{branch}")
        if copied:
            lines.append(f"已同步 .worktreeinclude 文件：{', '.join(copied)}")
        if issue_data:
            lines.append(f"关联 Issue：#{issue_data['number']} {issue_data.get('title', '')}")
            if issue_data.get("url"):
                lines.append(f"链接：{issue_data['url']}")
        if hint:
            lines.append(hint["message"])
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
        issue_dir, _ = _infer_issue_dir_and_number(wt_path, branch, str(issue_num))
    else:
        wt_path = repo.current_worktree
        branch = repo.current_branch
        issue_dir, issue_num = _infer_issue_dir_and_number(wt_path, branch)
        if issue_num is None:
            raise IddError("无法从当前工作树或分支推断 Issue 编号，请显式传入 Issue 编号。")

    validate_branch_name(branch, issue_num, wt_path)

    task_root = wt_path / "TASK"
    if not task_root.is_dir() or not issue_dir or not (task_root / issue_dir).is_dir():
        raise IddError(f"在工作树 `{wt_path}` 中找不到任务目录 `TASK/{issue_dir}`。")

    collected = task_status.collect(task_root, issue_dir, open_only=False)
    tasks = collected["issues"][0]["tasks"]
    block = build_progress_block(tasks)

    forge = get_forge(repo.main_worktree)
    issue_data = forge.get_issue(issue_num)
    merged_body = merge_progress_block(issue_data.get("body", ""), block)

    if args.dry_run:
        print(merged_body, end="")
        return 0

    forge.update_issue_body(issue_num, merged_body)
    done_count = collected["issues"][0]["done"]
    total_count = collected["issues"][0]["total"]
    print(f"已同步 Issue #{issue_num} 进度（{done_count}/{total_count}）：{issue_data.get('url', '')}")

    if repo.has_origin and not args.no_push and branch != repo.default_branch:
        _fix_misbound_upstream(wt_path, branch, repo.default_branch)
        local_head = run_cmd(["git", "-C", str(wt_path), "rev-parse", "HEAD"], check=False).stdout.strip()
        remote_proc = run_cmd(
            ["git", "-C", str(wt_path), "rev-parse", f"refs/remotes/origin/{branch}"],
            check=False,
        )
        remote_head = remote_proc.stdout.strip() if remote_proc.returncode == 0 else ""
        up_proc = run_cmd(
            ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            check=False,
        )
        upstream = up_proc.stdout.strip() if up_proc.returncode == 0 else ""
        if (not remote_head) or (local_head != remote_head) or (upstream != f"origin/{branch}"):
            ok, detail = _push_feature_branch(wt_path, branch, default_branch=repo.default_branch)
            if ok:
                print(f"已同步推送分支至远端：origin/{branch}")
            else:
                print(
                    f"⚠️ Issue 进度已更新，但自动推送分支 `{branch}` 失败：{detail}\n"
                    f"若刚执行过 rebase，请核对后运行：git -C {wt_path} push --force-with-lease -u origin HEAD",
                    file=sys.stderr,
                )
    return 0


def cmd_pr(args: argparse.Namespace) -> int:
    caller_cwd = Path.cwd().resolve()
    repo = get_repo_info(caller_cwd)
    wt_path, branch, issue_dir, issue_num = _resolve_target_worktree(repo, args.target)
    validate_branch_name(branch, issue_num, wt_path)
    _require_clean_worktree(wt_path)

    if getattr(args, "draft", False) and getattr(args, "auto_merge", False):
        raise IddError("不能同时使用 `--draft` 与 `--auto-merge`。")

    am_cfg = monitor.resolve_auto_merge(repo.main_worktree)
    if getattr(args, "no_auto_merge", False):
        effective_auto_merge = False
        am_source = "cli"
    elif getattr(args, "auto_merge", False):
        effective_auto_merge = True
        am_source = "cli"
    else:
        effective_auto_merge = bool(am_cfg["enabled"])
        am_source = str(am_cfg["source"])

    forge = get_forge(repo.main_worktree)
    base_branch = args.base or repo.default_branch
    base_ref = _resolve_base_ref(repo, base_branch)
    issue_data = forge.get_issue(issue_num, check=False) if issue_num is not None else None
    issue_title = issue_data.get("title") if issue_data else None

    suggested_title, body = build_issue_summary(
        wt_path,
        issue_dir or branch,
        issue_num,
        base_ref,
        issue_title=issue_title,
        branch=branch,
    )
    final_title = args.title or suggested_title

    if args.dry_run:
        if args.draft:
            am_preview = "关闭（Draft PR/MR 不自动合入）"
        elif effective_auto_merge:
            src_label = "命令行 --auto-merge" if am_source == "cli" else ("仓库配置" if am_source == "repo" else "全局配置")
            am_preview = f"开启（来源：{src_label}）"
        else:
            am_preview = "关闭"
        print(
            f"Forge: {forge.forge_type} ({forge.mr_label})\n"
            f"Title: {final_title}\nBase: {base_branch}\nHead: {branch}\n"
            f"Auto-Merge: {am_preview}\n\n{body}",
            end="",
        )
        return 0

    push_cmd = ["git", "-C", str(wt_path), "push", "-u", "origin", "HEAD"]
    if args.force_with_lease:
        push_cmd.append("--force-with-lease")
    run_cmd(push_cmd)

    existing_items = forge.list_changes(state="open", head_branch=branch, limit=1)
    existing = existing_items[0] if existing_items else None
    if existing:
        updated = forge.update_change(existing["number"], final_title, body)
        url = updated.get("url") or existing.get("url", "")
        change_num: int | None = int(existing["number"])
        change_obj: dict[str, Any] = dict(existing)
        change_obj["title"] = final_title
        change_obj["body"] = body
        if url:
            change_obj["url"] = url
        print(f"已更新 {forge.mr_label} {forge.mr_prefix}{change_num}: {url}")
    else:
        created = forge.create_change(base_branch, branch, final_title, body, draft=args.draft)
        num = created.get("number")
        num_str = f" {forge.mr_prefix}{num}" if num is not None else ""
        print(f"已创建 {forge.mr_label}{num_str}: {created.get('url', '')}")
        change_num = int(num) if num is not None else None
        change_obj = dict(created)

    if not effective_auto_merge:
        return 0
    if args.draft:
        print(f"提示：当前为 Draft {forge.mr_label}，本次跳过自动准入与合入。")
        return 0

    if change_num is None:
        looked_up = forge.get_change(branch=branch, check=False)
        if looked_up and looked_up.get("number") is not None:
            change_num = int(looked_up["number"])
            change_obj = looked_up
    if change_num is None:
        raise IddError(f"已提交 {forge.mr_label} 但无法解析编号，已停止自动准入与合入。")

    initial_head = run_cmd(["git", "-C", str(wt_path), "rev-parse", "HEAD"]).stdout.strip()
    src_desc = "命令行 --auto-merge" if am_source == "cli" else ("仓库配置" if am_source == "repo" else "全局配置")
    print(f"已开启自动准入合入（来源：{src_desc}），开始等待 {forge.mr_label} {forge.mr_prefix}{change_num} CI 结算...")

    settled, overall = _wait_for_ci_settlement(forge, change_num, initial_head, change_obj)
    settled_state = str(settled.get("state") or "OPEN")
    if settled_state == "MERGED":
        print(f"{forge.mr_label} {forge.mr_prefix}{change_num} 已处于已合并状态：{settled.get('url', '')}")
        return 0
    if settled_state != "OPEN":
        raise IddError(f"{forge.mr_label} {forge.mr_prefix}{change_num} 状态已变为 {settled_state}，已取消自动合入。")

    remote_head_oid = str(settled.get("headRefOid") or "")
    if remote_head_oid and remote_head_oid != initial_head:
        raise IddError(
            f"{forge.mr_label} {forge.mr_prefix}{change_num} 远端最新提交已变更为 `{remote_head_oid[:12]}`（本地 `{initial_head[:12]}`），"
            "为防止合入未校验提交已暂停自动合入。"
        )
    if overall == "FAIL":
        raise _format_ci_failure_error(forge, settled, context="自动准入 CI 检查")
    if overall == "PENDING":
        raise IddError(
            f"等待 {forge.mr_label} {forge.mr_prefix}{change_num} CI 结算超时（当前仍为 PENDING），"
            "已暂停自动合入（TASK 目录已保留）。",
            exit_code=3,
        )
    if settled.get("mergeStateStatus") == "DIRTY":
        raise IddError(
            f"{forge.mr_label} {forge.mr_prefix}{change_num} 存在合并冲突（DIRTY），请先解决冲突并复测。",
            exit_code=2,
        )

    ci_note = "CI 检查通过（PASS）" if overall == "PASS" else "仓库未配置远端 CI（NONE），按本地测试通过放行"
    print(f"{ci_note}，自动执行 Squash 直线合入...")

    return _execute_land(
        caller_cwd=caller_cwd,
        repo=repo,
        target=args.target or branch,
        title_override=args.title,
        wait_ci=True,
        pre_checked_head=initial_head,
    )


def _find_change_for_issue(forge: Any, issue_num: int) -> dict[str, Any] | None:
    changes = forge.list_changes(state="open", limit=100)
    if not isinstance(changes, list):
        return None
    for ch in changes:
        if re.search(rf"(?:^|/){issue_num}(?:-|$)", ch.get("headRefName", "")):
            return ch
    pattern = re.compile(rf"(?:Closes|Fixes|Resolves)\s+#{issue_num}\b", re.IGNORECASE)
    for ch in changes:
        if pattern.search(ch.get("body", "")):
            return ch
    return None


def _resolve_change_target(repo: RepoInfo, forge: Any, target: str | None) -> dict[str, Any]:
    if not target:
        change = forge.get_change(branch=repo.current_branch, check=False)
        if not change:
            raise IddError(f"当前分支 `{repo.current_branch}` 尚无关联的 {forge.mr_label}。")
        return change

    found = find_worktree_for_target(repo.main_worktree, target)
    if found:
        ch = forge.get_change(branch=found.get("branch", ""), check=False)
        if ch:
            return ch

    num = parse_issue_ref(target)
    if num is not None:
        is_explicit_change = "/pull/" in target or "/merge_requests/" in target or target.strip().startswith("!")
        if is_explicit_change:
            ch = forge.get_change(number=num, check=False)
            if ch:
                return ch
        else:
            matched = _find_change_for_issue(forge, num)
            if matched:
                return forge.get_change(number=matched["number"], check=False) or matched
            direct = forge.get_change(number=num, check=False)
            if direct:
                return direct
        raise IddError(f"找不到与 `{target}` 关联的 {forge.mr_label}。")

    for branch_cand in (target, f"feat/{target}"):
        ch = forge.get_change(branch=branch_cand, check=False)
        if ch:
            return ch
    raise IddError(f"找不到与 `{target}` 关联的 {forge.mr_label}。")


def cmd_ci(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    forge = get_forge(repo.main_worktree)
    change = _resolve_change_target(repo, forge, args.target)

    if args.watch:
        forge.watch_checks(change.get("number"))
        refreshed = forge.get_change(number=change.get("number"), check=False)
        if refreshed:
            change = refreshed

    overall = change.get("checks_overall") or "NONE"
    checks = change.get("checks") or []
    failed_logs: dict[str, str] = {}
    if args.logs or (overall == "FAIL" and not args.json):
        failed_logs = forge.get_failed_logs(change.get("failed_log_ids") or [])

    payload = {
        "forge": forge.forge_type,
        "change": {
            "number": change.get("number"),
            "label": forge.mr_label,
            "title": change.get("title"),
            "url": change.get("url"),
            "state": change.get("state"),
            "headRefName": change.get("headRefName"),
            "mergeStateStatus": change.get("mergeStateStatus"),
        },
        "overall": overall,
        "checks": checks,
        "failed_logs": failed_logs,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    lines = [
        f"{forge.mr_label} {forge.mr_prefix}{change['number']}: {change.get('title', '')}",
        f"链接：{change.get('url', '')}",
        f"总体 CI：{overall} | 合并状态：{change.get('mergeStateStatus', 'UNKNOWN')} | 分支：{change.get('headRefName', '')}",
    ]
    if checks:
        lines.append("")
        lines.append("检查明细：")
        for c in checks:
            lines.append(f"- [{c['verdict']}] {c['name']}")
    else:
        lines.append("暂无 CI 检查记录。")

    for log_id, text in failed_logs.items():
        lines.append(f"\n--- 失败日志 (Job/Run {log_id} 末尾 150 行) ---")
        lines.append(text)
    print("\n".join(lines))
    return 0


def _get_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    if val < minimum:
        return default
    return val


def _is_change_synced_to_head(change: dict[str, Any] | None, expected_sha: str) -> bool:
    if not isinstance(change, dict):
        return False
    head_oid = str(change.get("headRefOid") or "")
    if head_oid != expected_sha:
        return False
    raw_sha = str(change.get("rawSha") or "")
    if raw_sha and raw_sha != expected_sha:
        return False
    if change.get("mergeStateStatus") == "CHECKING":
        return False
    return True


def _wait_for_change_head_sync(
    forge: Any,
    change_num: int,
    expected_sha: str,
    fallback_change: dict[str, Any],
) -> dict[str, Any]:
    """Wait until remote PR/MR headRefOid catches up with local HEAD and leaves CHECKING."""
    latest = forge.get_change(number=change_num, check=False)
    if _is_change_synced_to_head(latest, expected_sha):
        assert latest is not None
        return latest

    timeout = _get_float_env("IDD_LAND_SYNC_TIMEOUT", LAND_SYNC_TIMEOUT_SECONDS, minimum=0.05)
    interval = _get_float_env("IDD_LAND_SYNC_INTERVAL", LAND_SYNC_POLL_INTERVAL_SECONDS, minimum=0.0)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        sleep_for = min(interval, max(0.0, remaining))
        if sleep_for > 0:
            time.sleep(sleep_for)
        latest = forge.get_change(number=change_num, check=False)
        if _is_change_synced_to_head(latest, expected_sha):
            assert latest is not None
            return latest

    current = latest or fallback_change
    remote_oid = str(current.get("headRefOid") or "") or "unknown"
    mstate = str(current.get("mergeStateStatus") or "UNKNOWN")
    dstate = str(current.get("detailedMergeStatus") or "")
    state_detail = f"{mstate} ({dstate})" if dstate else mstate
    raise IddError(
        f"等待 {forge.mr_label} {forge.mr_prefix}{change_num} 同步最新提交 `{expected_sha[:12]}` 超时"
        f"（远端当前头提交：`{remote_oid[:12] if remote_oid != 'unknown' else 'unknown'}`，合并状态：`{state_detail}`）。\n"
        "远端可能仍在异步刷新 MR/PR diff 或合并状态，为避免误合旧提交已取消合并；"
        "请稍后重试 `idd land`（或调大环境变量 `IDD_LAND_SYNC_TIMEOUT`）。",
        exit_code=3,
    )


def _is_transient_gitlab_merge_error(forge: Any, exc: ForgeError) -> bool:
    if getattr(forge, "forge_type", "") != "gitlab":
        return False
    status = getattr(exc, "http_status", None)
    if status in {405, 406, 409, 422}:
        return True
    if status is None:
        msg = str(exc).lower()
        return any(tok in msg for tok in ("http 405", "http 406", "http 409", "http 422", "cannot be merged", "not mergeable", "sha"))
    return False


def _require_gitlab_squash(forge: Any) -> None:
    try:
        settings = forge.repo_init(apply=False).get("settings") or {}
    except ForgeError as exc:
        raise IddError(f"无法核对 GitLab 项目合入设置，已停止合入。请先执行 `idd repo-init` 检查。\n{exc}") from exc
    merge_method = settings.get("merge_method") or "未知"
    squash_option = settings.get("squash_option") or "未知"
    if merge_method != "ff" or squash_option != "always":
        raise IddError(
            f"GitLab 合入需要快进合并和强制 Squash，当前 merge_method={merge_method}、squash_option={squash_option}。\n"
            "请在 GitLab 项目设置中启用，或由有权限的维护者执行 `idd repo-init --apply` 后重试。"
        )


def _fetch_target_tip(worktree: Path, base_branch: str) -> str:
    run_cmd(["git", "fetch", "--no-tags", "origin", f"refs/heads/{base_branch}"], cwd=worktree)
    return run_cmd(["git", "rev-parse", "--verify", "FETCH_HEAD^{commit}"], cwd=worktree).stdout.strip()


def _gitlab_land_result(
    forge: Any, change_num: int, worktree: Path, base_branch: str, before: str, *, auto: bool
) -> str | None:
    """Return the verified new target tip, or None while automatic merge is pending."""
    try:
        merged = forge.get_change(number=change_num, check=False) or {}
        if auto and merged.get("state") == "OPEN":
            return None
        if merged.get("state") != "MERGED":
            raise IddError("GitLab 尚未确认 MR 已合入。")

        after = _fetch_target_tip(worktree, base_branch)
        merged_oid = merged.get("squashCommitOid") or merged.get("mergeCommitOid") or merged.get("headRefOid")
        parents = run_cmd(["git", "rev-list", "--parents", "-n", "1", after], cwd=worktree).stdout.split()
        if parents != [after, before] or after != merged_oid:
            count = run_cmd(["git", "rev-list", "--count", f"{before}..{after}"], cwd=worktree).stdout.strip()
            raise IddError(
                f"远端 `{base_branch}` 从 `{before[:12]}` 变为 `{after[:12]}`，区间有 {count} 条提交。"
                "未能确认本次 MR 只新增一条直接后继提交。"
            )
        return after
    except (ForgeError, IddError) as exc:
        raise IddError(
            f"未能验证 GitLab MR !{change_num} 的合入结果。GitLab 可能已经合入，请检查远端历史。\n{exc}"
        ) from exc


def _merge_squash_with_retry(
    forge: Any,
    change_num: int,
    title: str,
    body: str,
    *,
    auto: bool,
    expected_sha: str,
) -> None:
    """Execute squash merge with SHA lock and bounded retries on transient GitLab mergeability errors."""
    retry_delay = _get_float_env("IDD_LAND_MERGE_RETRY_DELAY", LAND_MERGE_RETRY_DELAY_SECONDS, minimum=0.0)
    for attempt in range(LAND_MERGE_MAX_RETRIES):
        if forge.forge_type == "gitlab":
            _require_gitlab_squash(forge)
        try:
            forge.merge_squash(change_num, title, body, auto=auto, expected_sha=expected_sha)
            return
        except ForgeError as exc:
            if attempt + 1 >= LAND_MERGE_MAX_RETRIES or not _is_transient_gitlab_merge_error(forge, exc):
                raise
            if retry_delay > 0:
                time.sleep(retry_delay)
            latest = forge.get_change(number=change_num, check=False)
            if isinstance(latest, dict):
                if latest.get("mergeStateStatus") == "DIRTY" or (not auto and latest.get("checks_overall") == "FAIL"):
                    raise
                if not _is_change_synced_to_head(latest, expected_sha):
                    _wait_for_change_head_sync(forge, change_num, expected_sha, latest)


def _wait_for_ci_settlement(
    forge: Any,
    change_num: int,
    expected_sha: str,
    fallback_change: dict[str, Any],
    *,
    skip_initial_grace: bool = False,
) -> tuple[dict[str, Any], str]:
    """Wait for remote headRefOid sync and CI checks to settle (`PASS`, `FAIL`, `NONE`, or `PENDING` on timeout)."""
    latest = _wait_for_change_head_sync(forge, change_num, expected_sha, fallback_change)
    overall = str(latest.get("checks_overall") or "NONE")

    grace = _get_float_env("IDD_CI_GRACE_SECONDS", CI_WAIT_GRACE_SECONDS, minimum=0.0)
    poll_interval = _get_float_env("IDD_CI_POLL_INTERVAL", CI_WAIT_POLL_INTERVAL_SECONDS, minimum=0.0)
    wait_timeout = _get_float_env("IDD_CI_WAIT_TIMEOUT", CI_WAIT_TIMEOUT_SECONDS, minimum=0.05)

    # Give GitHub/GitLab a brief grace window after push to register newly triggered checks/pipelines.
    if overall == "NONE" and not skip_initial_grace and grace > 0:
        grace_deadline = time.monotonic() + grace
        while time.monotonic() < grace_deadline:
            remaining = grace_deadline - time.monotonic()
            sleep_for = min(poll_interval if poll_interval > 0 else 1.0, 2.0, max(0.0, remaining))
            if sleep_for > 0:
                time.sleep(sleep_for)
            polled = forge.get_change(number=change_num, check=False)
            if isinstance(polled, dict):
                latest = polled
                if str(latest.get("state") or "OPEN") != "OPEN":
                    return latest, str(latest.get("checks_overall") or "NONE")
                remote_oid = str(latest.get("headRefOid") or "")
                if remote_oid and remote_oid != expected_sha:
                    return latest, str(latest.get("checks_overall") or "NONE")
                overall = str(latest.get("checks_overall") or "NONE")
                if overall != "NONE":
                    break

    if overall != "PENDING":
        return latest, overall

    deadline = time.monotonic() + wait_timeout
    while overall == "PENDING" and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        sleep_for = min(poll_interval, max(0.0, remaining))
        if sleep_for > 0:
            time.sleep(sleep_for)
        polled = forge.get_change(number=change_num, check=False)
        if not isinstance(polled, dict):
            continue
        latest = polled
        overall = str(latest.get("checks_overall") or "NONE")
        if str(latest.get("state") or "OPEN") != "OPEN":
            break
        remote_oid = str(latest.get("headRefOid") or "")
        if remote_oid and remote_oid != expected_sha:
            break

    return latest, overall


def _format_ci_failure_error(forge: Any, change: dict[str, Any], *, context: str) -> IddError:
    change_num = change.get("number")
    checks = change.get("checks") or []
    failed_checks = [c for c in checks if c.get("verdict") == "FAIL"]
    lines = [f"{forge.mr_label} {forge.mr_prefix}{change_num} {context}失败（CI 未通过）：{change.get('url', '')}"]
    if failed_checks:
        lines.append("失败检查项：")
        for chk in failed_checks:
            url_part = f" ({chk['url']})" if chk.get("url") else ""
            lines.append(f"- [FAIL] {chk.get('name', 'check')}{url_part}")
    failed_logs = forge.get_failed_logs(change.get("failed_log_ids") or [])
    for log_id, text in failed_logs.items():
        lines.append(f"\n--- 失败日志 (Job/Run {log_id} 末尾 150 行) ---")
        lines.append(text)
    lines.append("\n请修复问题、本地复测并提交后重试（TASK 目录已保留）。")
    return IddError("\n".join(lines), exit_code=3)


UNFINISHED_LAND_TASK_STATUSES = {"planned", "in_progress", "blocked", "unknown"}


def _find_unfinished_tasks(wt_path: Path, issue_dir: str | None) -> list[dict[str, Any]]:
    """Return unfinished TASK entries under `TASK/<issue_dir>/` that block `idd land`."""
    task_root = wt_path / "TASK"
    if not issue_dir or not task_root.is_dir() or not (task_root / issue_dir).is_dir():
        return []
    try:
        collected = task_status.collect(task_root, issue_dir, open_only=False)
    except Exception:
        return []
    issues = collected.get("issues") or []
    tasks = issues[0].get("tasks", []) if issues else []
    return [t for t in tasks if t.get("status") in UNFINISHED_LAND_TASK_STATUSES]


def _execute_land(
    *,
    caller_cwd: Path,
    repo: RepoInfo,
    target: str | None,
    title_override: str | None = None,
    keep_tasks: bool = False,
    force_clean_evidence: bool = False,
    force_unfinished_tasks: bool = False,
    rm_worktree: bool = False,
    auto: bool = False,
    wait_ci: bool = False,
    no_rebase: bool = False,
    no_check_acceptance: bool = False,
    dry_run: bool = False,
    pre_checked_head: str | None = None,
) -> int:
    wt_path, branch, issue_dir, issue_num = _resolve_target_worktree(repo, target)
    validate_branch_name(branch, issue_num, wt_path)
    _require_clean_worktree(wt_path)
    if not force_unfinished_tasks:
        unfinished_tasks = _find_unfinished_tasks(wt_path, issue_dir)
        if unfinished_tasks:
            listed = "\n".join(
                f"  - {t.get('id') or Path(t['path']).stem} [{t.get('status')}] {t.get('title') or ''} ({t.get('path')})"
                for t in unfinished_tasks
            )
            raise IddError(
                f"检测到 `TASK/{issue_dir}/` 含未完成任务，为防提前合入已暂停：\n{listed}\n"
                "请先完成并验证上述 TASK（更新状态为 `done` / `cancelled` / `deferred`）后再执行 `idd land`，"
                "或确认无误后传 `--force-unfinished-tasks` 强制继续。",
                exit_code=2,
            )

    forge = get_forge(repo.main_worktree)
    change = forge.get_change(branch=branch, check=False)
    if not change:
        raise IddError(f"分支 `{branch}` 尚无 Open {forge.mr_label}，请先运行 `idd pr` 创建。")

    change_num = change["number"]
    base_branch = change.get("baseRefName") or repo.default_branch
    is_gitlab = forge.forge_type == "gitlab"
    if is_gitlab:
        _require_gitlab_squash(forge)

    if repo.has_origin:
        run_cmd(["git", "-C", str(wt_path), "fetch", "origin", base_branch])
    base_ref = _resolve_base_ref(repo, base_branch)

    # Step A: Rebase if behind target base
    needs_rebase = False
    if not no_rebase:
        anc = run_cmd(["git", "-C", str(wt_path), "merge-base", "--is-ancestor", base_ref, "HEAD"], check=False)
        if anc.returncode != 0:
            needs_rebase = True
            if not dry_run:
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

    # Step B: Collect TASK snapshot & build summary BEFORE removing TASK/<issue_dir>/
    landed_tasks: list[dict[str, Any]] = []
    task_root = wt_path / "TASK"
    if issue_dir and task_root.is_dir() and (task_root / issue_dir).is_dir():
        try:
            collected = task_status.collect(task_root, issue_dir, open_only=False)
            if collected.get("issues"):
                landed_tasks = list(collected["issues"][0].get("tasks", []))
        except Exception:
            landed_tasks = []

    issue_data = forge.get_issue(issue_num, check=False) if issue_num is not None else None
    issue_title = issue_data.get("title") if issue_data else None
    pending_acceptance_count = 0
    if issue_num is not None and issue_data and not no_check_acceptance:
        _, pending_acceptance_count = check_acceptance_criteria(issue_data.get("body", ""))

    suggested_title, summary = build_issue_summary(
        wt_path,
        issue_dir or branch,
        issue_num,
        base_ref,
        issue_title=issue_title,
        branch=branch,
    )
    final_title = title_override or suggested_title

    # Step C: Clean TASK/<issue_dir>/ before merging into main (unless --keep-tasks)
    task_issue_dir = wt_path / "TASK" / (issue_dir or "")
    will_clean_tasks = False
    if not keep_tasks and issue_dir and task_issue_dir.is_dir():
        evidence_dir = task_issue_dir / "evidence"
        evidence_files = [
            p.relative_to(wt_path).as_posix()
            for p in sorted(evidence_dir.rglob("*"))
            if p.is_file()
        ] if evidence_dir.is_dir() else []
        if evidence_files and not force_clean_evidence:
            listed = "\n".join(f"  - {item}" for item in evidence_files)
            raise IddError(
                f"检测到 `TASK/{issue_dir}/evidence/` 含附件文件，为防误删已暂停合入：\n{listed}\n"
                "请确认后传 `--force-clean-evidence` 一并清理，或传 `--keep-tasks` 保留任务目录。",
                exit_code=2,
            )
        will_clean_tasks = True
        if not dry_run:
            run_cmd(["git", "-C", str(wt_path), "rm", "-rf", f"TASK/{issue_dir}"])
            run_cmd(["git", "-C", str(wt_path), "commit", "-m", f"chore: 清理已汇总的任务记录 ({issue_dir})"])

    # Step D: Dry-run short-circuit
    if dry_run:
        if issue_num is None:
            acceptance_preview = "无关联远端 Issue（跳过）"
        elif no_check_acceptance:
            acceptance_preview = "否（已传 --no-check-acceptance）"
        elif auto:
            acceptance_preview = "暂不勾选（--auto 等待 CI 期间不提前勾选）"
        elif pending_acceptance_count > 0:
            acceptance_preview = f"是（将勾选 {pending_acceptance_count} 项）"
        else:
            acceptance_preview = "无需更新（未发现未勾选的验收标准）"

        merge_mode_note = "（auto 等待 CI）" if auto else ("（阻塞等待 CI 结算）" if wait_ci else "")
        lines = [
            "=== IDD Land Dry-Run 预览 ===",
            f"Forge: {forge.forge_type} | {forge.mr_label}: {forge.mr_prefix}{change_num} ({change.get('url', '')})",
            f"工作树: {wt_path}",
            f"分支: {branch} -> {base_branch} (基于 {base_ref})",
            f"是否需要 Rebase: {'是' if needs_rebase else '否'}",
            f"合入前清理 TASK/{issue_dir}/: {'是' if will_clean_tasks else '否'}",
            f"合入后勾选 Issue 验收标准: {acceptance_preview}",
            f"Squash 提交标题: {final_title}",
            "Squash 提交正文:",
            summary.rstrip(),
            f"合入方式: Squash 直线合入{merge_mode_note}",
            f"分支策略: 默认保留本地与远端需求分支 `{branch}`",
            f"工作树策略: {'合入后移除本地工作树（--rm-worktree）' if (rm_worktree and not auto) else '默认保留本地工作树（如需释放空间可手动执行 idd cleanup）'}",
        ]
        print("\n".join(lines))
        return 0

    # Step E: Push local HEAD first (so remote starts async MR/PR refresh), then update PR/MR body
    local_head = run_cmd(["git", "-C", str(wt_path), "rev-parse", "HEAD"]).stdout.strip()
    remote_proc = run_cmd(["git", "-C", str(wt_path), "rev-parse", f"origin/{branch}"], check=False)
    remote_head = remote_proc.stdout.strip() if remote_proc.returncode == 0 else ""
    if local_head != remote_head:
        run_cmd(["git", "-C", str(wt_path), "push", "--force-with-lease", "origin", "HEAD"])
    forge.update_change(change_num, final_title, summary)

    # Step F: Wait for remote headRefOid sync, verify CI on new SHA, and Squash Merge with SHA lock
    fresh_change = _wait_for_change_head_sync(forge, change_num, local_head, change)
    overall = str(fresh_change.get("checks_overall") or "NONE")

    if wait_ci and not auto:
        skip_ci_grace = bool(pre_checked_head and pre_checked_head == local_head)
        if not skip_ci_grace and overall in ("PENDING", "NONE"):
            fresh_change, overall = _wait_for_ci_settlement(
                forge,
                change_num,
                local_head,
                fresh_change,
                skip_initial_grace=False,
            )
        elif skip_ci_grace and overall == "PENDING":
            fresh_change, overall = _wait_for_ci_settlement(
                forge,
                change_num,
                local_head,
                fresh_change,
                skip_initial_grace=True,
            )
        if overall == "FAIL":
            raise _format_ci_failure_error(forge, fresh_change, context="合入前 CI 检查")
        if overall == "PENDING":
            raise IddError(
                f"等待 {forge.mr_label} {forge.mr_prefix}{change_num} CI 结算超时（当前仍为 PENDING），暂不执行合入。",
                exit_code=3,
            )
        if fresh_change.get("mergeStateStatus") == "DIRTY":
            raise IddError(
                f"{forge.mr_label} {forge.mr_prefix}{change_num} 存在合并冲突（DIRTY），请先解决冲突并复测。",
                exit_code=2,
            )
    elif not auto and overall in ("FAIL", "PENDING"):
        raise IddError(
            f"{forge.mr_label} {forge.mr_prefix}{change_num} 当前 CI 状态为 `{overall}`，暂不执行合入。\n"
            f"请运行 `idd ci {issue_num or change_num} --watch` 等待/排查 CI，或传 `--wait-ci` / `--auto` 启用自动合入。",
            exit_code=3,
        )

    before = _fetch_target_tip(wt_path, base_branch) if is_gitlab else ""
    _merge_squash_with_retry(
        forge,
        change_num,
        final_title,
        summary,
        auto=auto,
        expected_sha=local_head,
    )
    verified_tip = _gitlab_land_result(forge, change_num, wt_path, base_branch, before, auto=auto) if is_gitlab else None
    if auto and verified_tip is None:
        if is_gitlab:
            print(f"已提交 MR !{change_num} 的自动 Squash 合入请求。合入结果待确认。{change.get('url', '')}")
        else:
            print(
                f"已为 {forge.mr_label} {forge.mr_prefix}{change_num} 开启自动 Squash 合并（CI 通过后将直线合入 {base_branch}，保留需求分支）：{change.get('url', '')}"
            )
        print("本地工作树与需求分支已保留；合并完成后如需释放工作树目录可执行 `idd cleanup`。")
        return 0

    acceptance_note = ""
    if issue_num is not None:
        try:
            fresh_issue = forge.get_issue(issue_num, check=False) or issue_data
            orig_body = (fresh_issue or {}).get("body", "")
            updated_body = orig_body
            checked_count = 0
            if not no_check_acceptance:
                updated_body, checked_count = check_acceptance_criteria(orig_body)
            if landed_tasks and _find_progress_block_span(updated_body) is not None:
                updated_body = merge_progress_block(updated_body, build_progress_block(landed_tasks))
            if updated_body != orig_body:
                forge.update_issue_body(issue_num, updated_body)
                if checked_count > 0:
                    acceptance_note = f"已自动勾选 Issue #{issue_num} 验收标准（{checked_count} 项）"
                else:
                    acceptance_note = f"已同步更新 Issue #{issue_num} 执行进度"
        except (IddError, ForgeError) as exc:
            acceptance_note = f"⚠️ 合入已成功，但自动更新 Issue #{issue_num} 验收标准失败：{exc}"

    # Step G: Retain branches & worktree by default; optionally remove worktree; fast-forward main
    in_removed_wt = False
    if rm_worktree:
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
        f"已通过 Squash Merge 直线合入 {forge.mr_label} {forge.mr_prefix}{change_num}（无 Merge 节点）：{change.get('url', '')}",
        f"已保留本地与远端分支：{branch}",
    ]
    if verified_tip:
        lines.append(f"已核对远端 `{base_branch}` 只新增一条提交 `{verified_tip[:12]}`。")
    if acceptance_note:
        lines.append(acceptance_note)
    if rm_worktree:
        lines.append(f"已移除本地工作树：{wt_path}")
    else:
        lines.append(f"已保留本地工作树：{wt_path}（如需释放磁盘空间可运行 `idd cleanup`）")
    if main_sha:
        lines.append(f"本地 `{base_branch}` 已快进至：{main_sha}")
    if in_removed_wt:
        lines.append(f"当前终端位于已清理目录，请切换回主工作树：cd {repo.main_worktree}")
    print("\n".join(lines))
    return 0


def cmd_land(args: argparse.Namespace) -> int:
    caller_cwd = Path.cwd().resolve()
    repo = get_repo_info(caller_cwd)
    return _execute_land(
        caller_cwd=caller_cwd,
        repo=repo,
        target=args.target,
        title_override=args.title,
        keep_tasks=args.keep_tasks,
        force_clean_evidence=args.force_clean_evidence,
        force_unfinished_tasks=bool(getattr(args, "force_unfinished_tasks", False)),
        rm_worktree=args.rm_worktree,
        auto=args.auto,
        wait_ci=bool(getattr(args, "wait_ci", False)),
        no_rebase=args.no_rebase,
        no_check_acceptance=args.no_check_acceptance,
        dry_run=args.dry_run,
    )


def cmd_cleanup(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    forge = get_forge(repo.main_worktree)
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

        merged_changes = forge.list_changes(state="merged", head_branch=branch, limit=10)
        if not isinstance(merged_changes, list) or not merged_changes:
            continue

        dirty = run_cmd(["git", "-C", str(wt_path), "status", "--porcelain"], check=False).stdout.strip()
        if dirty:
            skipped_dirty.append(f"{wt_path} ({branch})")
            continue

        local_head = run_cmd(["git", "-C", str(wt_path), "rev-parse", "HEAD"]).stdout.strip()
        matching = next(
            (c for c in merged_changes if c.get("headRefOid") and c.get("headRefOid") == local_head),
            None,
        )
        if not matching:
            skipped_unmerged.append(f"{wt_path} ({branch} @ {local_head[:7]})")
            continue

        ref = f"{forge.mr_label} {forge.mr_prefix}{matching['number']}"
        if args.dry_run:
            removed.append(f"[dry-run] 将仅移除工作树目录 {wt_path}（保留分支 {branch}）— {ref}")
        else:
            run_cmd(["git", "-C", str(repo.main_worktree), "worktree", "remove", str(wt_path)])
            removed.append(f"已移除工作树目录 {wt_path}（保留分支 {branch}）— {ref}")

    lines = list(removed)
    if skipped_dirty:
        lines.append("以下工作树存在未提交改动，已跳过清理：")
        lines.extend(f"- {item}" for item in skipped_dirty)
    if skipped_unmerged:
        lines.append("以下工作树本地最新提交与已合入 PR/MR 的 headRefOid 不一致（可能存在合入后新增本地提交），已跳过清理：")
        lines.extend(f"- {item}" for item in skipped_unmerged)
    if not lines:
        lines.append("没有发现可安全清理的已合入工作树。")
    print("\n".join(lines))
    return 0


def cmd_repo_init(args: argparse.Namespace) -> int:
    repo = get_repo_info(Path.cwd())
    forge = get_forge(repo.main_worktree)
    result = forge.repo_init(apply=args.apply)
    aligned, mismatches = evaluate_repo_init_settings(result)
    monitor.set_repo_init_meta(
        repo.main_worktree,
        "aligned" if aligned else "pending",
        mismatches=mismatches,
        error="",
    )
    settings = result.get("settings") or {}
    if result["forge"] == "gitlab":
        prefix = (
            "已应用 GitLab 线性合入配置（Fast-forward + 强制 Squash + 保留分支）："
            if args.apply
            else "当前 GitLab 项目合入策略（加 `--apply` 可设为 fast-forward + 强制 Squash 并保留分支）："
        )
    else:
        prefix = (
            "已应用 GitHub 线性合入配置（仅 Squash 合入并保留需求分支）："
            if args.apply
            else "当前 GitHub 仓库合入策略（加 `--apply` 可设为仅 Squash 并保留需求分支）："
        )
    lines = [prefix, f"- 仓库：{result.get('repo', '')}"]
    for key, val in settings.items():
        lines.append(f"- {key}: {val}")
    if result["forge"] == "github":
        lines.append("提示：如需连人工网页点击也强制直线历史，建议在 GitHub Branch Ruleset 中勾选 `Require linear history`。")
    print("\n".join(lines))
    return 0


def _resolve_config_repo(repo_arg: Path | None) -> Path | None:
    if repo_arg is not None:
        resolved = monitor.resolve_main_worktree_ro(repo_arg)
        if resolved is None:
            raise IddError(f"路径不是有效的 Git 仓库：{repo_arg}")
        return resolved
    return monitor.resolve_main_worktree_ro(Path.cwd())


def _parse_auto_merge_action(raw: str) -> str:
    val = raw.strip().lower()
    if val in ("status", "show", "get"):
        return "status"
    if val in ("on", "true", "1", "enable", "enabled"):
        return "on"
    if val in ("off", "false", "0", "disable", "disabled"):
        return "off"
    if val in ("inherit", "unset", "default", "reset"):
        return "inherit"
    raise IddError(f"不支持的 auto-merge 值 `{raw}`（请使用 on / off / inherit / status）。")


def _build_config_payload(main_wt: Path | None) -> dict[str, Any]:
    global_am = monitor.get_global_auto_merge()
    payload: dict[str, Any] = {
        "config_path": str(monitor.get_config_path()),
        "repos_config_path": str(monitor.get_repos_path()),
        "global": {
            "auto_merge": global_am,
        },
        "repo": None,
    }
    if main_wt is not None:
        resolved = monitor.resolve_auto_merge(main_wt)
        payload["repo"] = {
            "path": str(main_wt),
            "name": main_wt.name,
            "auto_merge": resolved,
        }
    return payload


def cmd_config(args: argparse.Namespace) -> int:
    subcmd = getattr(args, "config_command", None) or "show"
    repo_arg = getattr(args, "repo", None)
    use_json = bool(getattr(args, "json", False))
    global_mode = bool(getattr(args, "global_mode", False))

    if subcmd == "show":
        main_wt = _resolve_config_repo(repo_arg)
        payload = _build_config_payload(main_wt)
        if use_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        lines = [
            f"全局配置：{payload['config_path']}",
            f"- auto_merge（全局默认）：{'开 (on)' if payload['global']['auto_merge'] else '关 (off)'}",
        ]
        if payload["repo"] is not None:
            r = payload["repo"]
            am = r["auto_merge"]
            ovr = am["repo_override"]
            ovr_text = "跟随全局 (inherit)" if ovr is None else ("开 (on)" if ovr else "关 (off)")
            eff_text = "开 (on)" if am["enabled"] else "关 (off)"
            src_text = "仓库覆盖" if am["source"] == "repo" else "全局默认"
            lines.extend([
                f"当前仓库：{r['name']} ({r['path']})",
                f"- 仓库覆盖：{ovr_text}",
                f"- 最终生效：{eff_text}（来源：{src_text}）",
            ])
        else:
            lines.append("当前目录不在 Git 仓库内（可加 `-g/--global` 或 `--repo <路径>` 管理仓库配置）。")
        print("\n".join(lines))
        return 0

    if subcmd == "auto-merge":
        action = _parse_auto_merge_action(getattr(args, "value", "status"))
        main_wt = _resolve_config_repo(repo_arg)

        if action == "status":
            if global_mode:
                global_am = monitor.get_global_auto_merge()
                if use_json:
                    print(json.dumps({
                        "scope": "global",
                        "auto_merge": global_am,
                        "config_path": str(monitor.get_config_path()),
                    }, ensure_ascii=False, indent=2))
                else:
                    print(f"全局默认 auto_merge：{'开 (on)' if global_am else '关 (off)'}（{monitor.get_config_path()}）")
                return 0
            if main_wt is None:
                global_am = monitor.get_global_auto_merge()
                if use_json:
                    print(json.dumps(_build_config_payload(None), ensure_ascii=False, indent=2))
                else:
                    print(f"全局默认 auto_merge：{'开 (on)' if global_am else '关 (off)'}（当前不在 Git 仓库内）")
                return 0
            resolved = monitor.resolve_auto_merge(main_wt)
            if use_json:
                print(json.dumps({
                    "scope": "repo",
                    "repo_path": str(main_wt),
                    "auto_merge": resolved,
                }, ensure_ascii=False, indent=2))
            else:
                ovr = resolved["repo_override"]
                ovr_text = "跟随全局 (inherit)" if ovr is None else ("开 (on)" if ovr else "关 (off)")
                eff_text = "开 (on)" if resolved["enabled"] else "关 (off)"
                src_text = "仓库覆盖" if resolved["source"] == "repo" else "全局默认"
                print(
                    f"仓库 `{main_wt.name}` auto_merge：{eff_text}"
                    f"（仓库覆盖：{ovr_text}，全局默认：{'开' if resolved['global_default'] else '关'}，来源：{src_text}）"
                )
            return 0

        if global_mode:
            if action == "inherit":
                raise IddError("全局默认开关不支持 `inherit`，请使用 `on` 或 `off`。")
            enabled = action == "on"
            cfg = monitor.set_global_auto_merge(enabled)
            if use_json:
                print(json.dumps({
                    "scope": "global",
                    "auto_merge": bool(cfg["auto_merge"]),
                    "config_path": str(monitor.get_config_path()),
                }, ensure_ascii=False, indent=2))
            else:
                state_zh = "开启" if cfg["auto_merge"] else "关闭"
                print(f"已{state_zh}全局默认 PR/MR 自动准入与自动合入开关（{monitor.get_config_path()}）。")
            return 0

        if main_wt is None:
            raise IddError("当前目录不在 Git 仓库内，请加 `-g/--global` 设置全局开关，或通过 `--repo <路径>` 指定仓库。")

        override_val: bool | None = None if action == "inherit" else (action == "on")
        resolved = monitor.set_repo_auto_merge_override(main_wt, override_val)
        if use_json:
            print(json.dumps({
                "scope": "repo",
                "repo_path": str(main_wt),
                "auto_merge": resolved,
            }, ensure_ascii=False, indent=2))
        else:
            if override_val is None:
                eff_text = "开启" if resolved["enabled"] else "关闭"
                print(f"已清除仓库 `{main_wt.name}` 的独立覆盖，恢复跟随全局默认（当前生效：{eff_text}）。")
            else:
                state_zh = "开启" if override_val else "关闭"
                print(f"已为仓库 `{main_wt.name}` 独立{state_zh} PR/MR 自动准入与自动合入开关。")
        return 0

    raise IddError(f"未知 config 子命令：{subcmd}")


def cmd_auth(args: argparse.Namespace) -> int:
    subcmd = args.auth_command
    if subcmd == "login":
        host_key, api_base = normalize_host_input(args.host, use_http=args.http)
        forge_type = args.forge or ("github" if "github.com" in host_key else "gitlab")
        user_info = ""
        if not args.no_verify:
            username = verify_host_token(forge_type, api_base, args.token)
            user_info = f"（已校验用户：{username}）"
        hosts = load_hosts_config()
        hosts[host_key] = {"forge": forge_type, "api_url": api_base, "token": args.token}
        save_hosts_config(hosts)
        print(f"已保存 {forge_type} 主机凭据：{host_key} ({api_base}) {user_info}\n配置文件：{get_hosts_path()}")
        return 0

    if subcmd == "status":
        hosts = load_hosts_config()
        lines = [f"凭据配置文件：{get_hosts_path()}"]
        if hosts:
            for host, entry in sorted(hosts.items()):
                tok = entry.get("token", "")
                masked = f"{tok[:6]}...{tok[-2:]}" if len(tok) > 10 else "****"
                lines.append(f"- {host} [{entry.get('forge', 'gitlab')}] api={entry.get('api_url', '')} token={masked}")
        else:
            lines.append("- 暂无已保存的自建 GitLab/GitHub 主机凭据。")
        if os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_PRIVATE_TOKEN"):
            lines.append("- 环境变量 GITLAB_TOKEN: 已设置")
        if shutil.which("gh"):
            gh_st = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
            lines.append(f"- gh CLI: {'已登录' if gh_st.returncode == 0 else '未登录'}")
        print("\n".join(lines))
        return 0

    if subcmd == "logout":
        host_key, _ = normalize_host_input(args.host)
        hosts = load_hosts_config()
        removed = hosts.pop(host_key, None) or hosts.pop(host_key.split(":", 1)[0], None)
        if not removed:
            raise IddError(f"未找到主机 `{args.host}` 的保存凭据。")
        save_hosts_config(hosts)
        print(f"已移除主机 `{host_key}` 的凭据。")
        return 0

    raise IddError(f"未知 auth 子命令：{subcmd}")


# ---------------------------------------------------------------------------
# Safe background auto-update & `idd upgrade`
# ---------------------------------------------------------------------------


def get_skill_repo_dir() -> Path:
    """Return the local `idd` skill git repository root."""
    override = os.environ.get("IDD_SKILL_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return SCRIPT_DIR.parent.resolve()


def get_bin_dir() -> Path:
    """Return the directory containing the global `idd` CLI symlink."""
    override = os.environ.get("IDD_BIN_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".local" / "bin").resolve()


def get_cache_dir() -> Path:
    """Return the local `idd` cache directory."""
    cache_override = os.environ.get("IDD_CACHE_DIR", "").strip()
    if cache_override:
        return Path(cache_override).expanduser().resolve()
    return (Path.home() / ".cache" / "idd").resolve()


def get_update_state_path() -> Path:
    """Return path to the local auto-update state JSON file."""
    return get_cache_dir() / "update_state.json"


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
        old_ver = get_version(skill_dir / "SKILL.md", fallback="")
        merge_proc = subprocess.run(
            ["git", "-C", str(skill_dir), "merge", "--ff-only", "origin/main"],
            capture_output=True,
            text=True,
        )
        if merge_proc.returncode == 0:
            _ensure_scripts_executable(skill_dir)
            new_ver = get_version(skill_dir / "SKILL.md", fallback="")
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
            if old_ver and new_ver and old_ver != new_ver:
                notice = f"✨ idd 已自动同步至最新 (v{old_ver} → v{new_ver}, {old_sha} → {new_sha}): {subject}"
            else:
                notice = f"✨ idd 已自动同步至最新 ({old_sha} → {new_sha}): {subject}"
            _save_update_state({"last_checked_at": now, "pending_notice": notice, "behind_count": 0})
            return 0

    _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": behind})
    return 0


def maybe_notify_and_trigger_auto_update(current_command: str | None) -> None:
    """Print cached update notice to stderr and trigger detached background check if due."""
    try:
        if os.environ.get("IDD_NO_AUTO_UPDATE") == "1" or current_command in {"upgrade", "uninstall"}:
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
    skill_ver = get_version(skill_dir / "SKILL.md", fallback=__version__)
    now = time.time()

    if args.check:
        lines = [
            f"当前版本：idd {skill_ver}",
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
        print(f"idd 已是最新版本 (v{skill_ver}, {cur_sha})。")
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

    old_ver = get_version(skill_dir / "SKILL.md", fallback="")
    run_cmd(["git", "-C", str(skill_dir), "merge", "--ff-only", "origin/main"])
    _ensure_scripts_executable(skill_dir)
    new_ver = get_version(skill_dir / "SKILL.md", fallback="")
    new_sha = run_cmd(["git", "-C", str(skill_dir), "rev-parse", "--short", "HEAD"]).stdout.strip()
    changelog = run_cmd(
        ["git", "-C", str(skill_dir), "log", "--oneline", f"{cur_sha}..{new_sha}"],
        check=False,
    ).stdout.strip()
    _save_update_state({"last_checked_at": now, "pending_notice": "", "behind_count": 0})

    if old_ver and new_ver and old_ver != new_ver:
        lines = [f"已更新 idd：v{old_ver} → v{new_ver} ({cur_sha} → {new_sha})"]
    else:
        lines = [f"已更新 idd：{cur_sha} → {new_sha}"]
    if changelog:
        lines.append(changelog)
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# Safe complete uninstall (`idd uninstall`)
# ---------------------------------------------------------------------------


def _is_unsafe_delete_root(path: Path) -> bool:
    """Return True when `path` is filesystem root, $HOME, or an ancestor of $HOME."""
    candidate = path.resolve(strict=False)
    home = Path.home().resolve(strict=False)
    return candidate == candidate.parent or candidate == home or candidate in home.parents


def _looks_like_idd_skill_dir(skill_dir: Path) -> bool:
    """Verify `skill_dir` actually looks like an `idd` skill directory before deletion."""
    return any((skill_dir / marker).exists() for marker in ("SKILL.md", "scripts/idd", "scripts/idd_cli.py"))


def _symlink_points_to_idd(link: Path, skill_dir: Path, *, is_bin: bool) -> bool:
    """Return True if `link` is a symlink pointing to `skill_dir` (or its CLI entrypoint)."""
    if not link.is_symlink():
        return False
    try:
        raw = os.readlink(link)
    except OSError:
        return False
    raw_path = Path(raw)
    target = raw_path if raw_path.is_absolute() else (link.parent / raw_path)
    resolved_target = target.resolve(strict=False)
    resolved_skill = skill_dir.resolve(strict=False)
    if is_bin:
        return resolved_target in {
            resolved_skill / "scripts" / "idd",
            resolved_skill / "scripts" / "idd_cli.py",
        }
    return resolved_target == resolved_skill


def _check_skill_repo_uninstall_safety(skill_dir: Path) -> list[str]:
    """Return human-readable reasons if `skill_dir` has dirty edits or unpushed commits."""
    if not (skill_dir / ".git").exists():
        return []
    reasons: list[str] = []
    dirty_proc = subprocess.run(
        ["git", "-C", str(skill_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if dirty_proc.returncode == 0 and dirty_proc.stdout.strip():
        reasons.append("存在未提交改动")

    upstream_proc = subprocess.run(
        ["git", "-C", str(skill_dir), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        capture_output=True,
        text=True,
    )
    upstream = upstream_proc.stdout.strip() if upstream_proc.returncode == 0 else ""
    if not upstream and _ref_exists(skill_dir, "refs/remotes/origin/main"):
        upstream = "origin/main"

    if upstream:
        ahead_proc = subprocess.run(
            ["git", "-C", str(skill_dir), "rev-list", "--count", f"{upstream}..HEAD"],
            capture_output=True,
            text=True,
        )
        if ahead_proc.returncode == 0 and ahead_proc.stdout.strip().isdigit():
            ahead_count = int(ahead_proc.stdout.strip())
            if ahead_count > 0:
                reasons.append(f"本地存在 {ahead_count} 个未推送提交")
    return reasons


def _should_use_color(stream: Any) -> bool:
    """Return True when ANSI SGR styling should be emitted to `stream`."""
    if os.environ.get("NO_COLOR"):
        return False
    force = os.environ.get("FORCE_COLOR", "") or os.environ.get("CLICOLOR_FORCE", "")
    if force and force != "0":
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(hasattr(stream, "isatty") and stream.isatty())


def _ansi(code: str, text: str, use_color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if use_color else text


def _pretty_path(path: Path) -> str:
    """Format paths inside $HOME using a `~/` prefix for cleaner display."""
    raw = str(path)
    home_raw = str(Path.home()).rstrip("/")
    home_canon = str(Path.home().resolve(strict=False)).rstrip("/")
    for candidate in (raw, str(path.resolve(strict=False))):
        for prefix in (home_raw, home_canon):
            if not prefix:
                continue
            if candidate == prefix:
                return "~"
            if candidate.startswith(prefix + "/"):
                return "~/" + candidate[len(prefix) + 1 :]
    return raw


def cmd_uninstall(args: argparse.Namespace) -> int:
    use_color = _should_use_color(sys.stdout)
    use_err_color = _should_use_color(sys.stderr)
    skill_dir = get_skill_repo_dir()
    bin_dir = get_bin_dir()
    config_dir = get_config_dir()
    cache_dir = get_cache_dir()
    home_dir = Path.home()

    candidates: list[tuple[bool, Path]] = [
        (False, home_dir / ".claude" / "skills" / "idd"),
        (False, home_dir / ".codex" / "skills" / "idd"),
        (False, home_dir / ".gemini" / "config" / "skills" / "idd"),
        (True, bin_dir / "idd"),
    ]
    seen_links = {p.parent.resolve(strict=False) / p.name for _, p in candidates}
    if sys.argv and sys.argv[0]:
        argv0 = Path(sys.argv[0]).expanduser()
        argv0_key = argv0.parent.resolve(strict=False) / argv0.name
        if argv0.is_symlink() and argv0_key not in seen_links:
            if _symlink_points_to_idd(argv0, skill_dir, is_bin=True):
                candidates.append((True, argv0))
                seen_links.add(argv0_key)

    links_to_remove: list[Path] = []
    warnings: list[tuple[str, Path]] = []
    for is_bin, link_path in candidates:
        if link_path.is_symlink():
            if _symlink_points_to_idd(link_path, skill_dir, is_bin=is_bin):
                links_to_remove.append(link_path)
            else:
                warnings.append(("跳过无关软链  ", link_path))
        elif link_path.exists():
            warnings.append(("跳过非软链路径", link_path))

    dirs_to_remove: list[tuple[str, Path]] = []
    kept_items: list[Path] = []
    if cache_dir.exists() or cache_dir.is_symlink():
        dirs_to_remove.append(("缓存目录", cache_dir))
    if args.keep_config:
        if config_dir.exists() or config_dir.is_symlink():
            kept_items.append(config_dir)
    else:
        if config_dir.exists() or config_dir.is_symlink():
            dirs_to_remove.append(("配置目录", config_dir))
    if skill_dir.exists() or skill_dir.is_symlink():
        dirs_to_remove.append(("技能仓库", skill_dir))

    for _, d in dirs_to_remove:
        if _is_unsafe_delete_root(d):
            raise IddError(f"拒绝删除受保护路径：{d}")
        if d == skill_dir and not d.is_symlink() and not _looks_like_idd_skill_dir(d):
            raise IddError(f"目录 `{d}` 不像是 idd 技能目录（缺少 SKILL.md / scripts/idd），已中止卸载。")

    if not links_to_remove and not dirs_to_remove:
        for label, warn_path in warnings:
            print(
                f"  {_ansi('1;33', '!', use_err_color)}  {label}  {_ansi('2', _pretty_path(warn_path), use_err_color)}",
                file=sys.stderr,
            )
        for item_path in kept_items:
            print(f"  {_ansi('36', '○', use_color)}  {_ansi('2', '保留配置', use_color)}    {_pretty_path(item_path)}")
        print(f"  {_ansi('36', 'i', use_color)}  未检测到可卸载的 idd 安装文件。")
        return 0

    safety_reasons: list[str] = []
    if any(d == skill_dir for _, d in dirs_to_remove) and not skill_dir.is_symlink():
        safety_reasons = _check_skill_repo_uninstall_safety(skill_dir)

    print()
    print(
        f"  {_ansi('1;36', '◆', use_color)} {_ansi('1', 'IDD', use_color)}  "
        f"{_ansi('36', '卸载', use_color)}  {_ansi('2', '·  Issue-Driven Development', use_color)}"
    )
    print(f"  {_ansi('2', '─' * 46, use_color)}")
    print(f"  {_ansi('2', '待移除清单（不影响业务仓库、分支与 Worktree）：', use_color)}")
    print()
    for link in links_to_remove:
        print(f"  {_ansi('1;31', '×', use_color)}  软链        {_pretty_path(link)}")
    for label, d in dirs_to_remove:
        print(f"  {_ansi('1;31', '×', use_color)}  {label}    {_pretty_path(d)}")
    for item_path in kept_items:
        print(f"  {_ansi('36', '○', use_color)}  {_ansi('2', '保留配置', use_color)}    {_pretty_path(item_path)}")
    for label, warn_path in warnings:
        print(
            f"  {_ansi('1;33', '!', use_err_color)}  {label}  {_ansi('2', _pretty_path(warn_path), use_err_color)}",
            file=sys.stderr,
        )

    if args.dry_run:
        if safety_reasons and not args.force:
            reason_text = "、".join(safety_reasons)
            print(
                f"\n  {_ansi('1;33', '!', use_color)}  "
                f"{_ansi('33', f'技能仓库存在本地状态（{reason_text}），实际卸载需先清理或传入 `--force`。', use_color)}"
            )
        print(f"\n  {_ansi('36', 'i', use_color)}  [dry-run] 仅预览，未删除任何文件。\n")
        return 0

    if safety_reasons and not args.force:
        raise IddError(
            f"技能仓库 `{skill_dir}` {'、'.join(safety_reasons)}，已中止卸载。\n"
            "请先提交/清理改动，或传入 `idd uninstall --force` 强制移除。"
        )

    if not args.yes:
        if not sys.stdin.isatty():
            raise IddError("当前为非交互环境，请传入 `-y` / `--yes` 确认卸载，或先用 `--dry-run` 预览。")
        try:
            answer = input(f"\n  {_ansi('1;33', '?', use_color)}  确认完全卸载 idd？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {_ansi('2', 'i  已取消卸载。', use_color)}")
            return 1
        if answer not in {"y", "yes"}:
            print(f"  {_ansi('2', 'i  已取消卸载。', use_color)}")
            return 1

    cwd_inside_skill = False
    try:
        cwd_resolved = Path.cwd().resolve(strict=False)
        skill_resolved = skill_dir.resolve(strict=False)
        cwd_inside_skill = cwd_resolved == skill_resolved or skill_resolved in cwd_resolved.parents
    except OSError:
        cwd_inside_skill = False

    for link in links_to_remove:
        link.unlink(missing_ok=True)
    for _, d in dirs_to_remove:
        if d.is_symlink():
            d.unlink(missing_ok=True)
        elif d.exists():
            shutil.rmtree(d)

    summary = f"（共移除 {len(links_to_remove)} 条软链、{len(dirs_to_remove)} 个目录）"
    print(f"\n  {_ansi('1;32', '✓', use_color)}  {_ansi('1', '已完成 idd 卸载', use_color)} {_ansi('2', summary, use_color)}\n")
    if cwd_inside_skill:
        print(f"  {_ansi('36', 'i', use_color)}  当前终端所在目录已被移除，请执行 `cd ~` 返回主目录。\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="idd",
        description="Issue-Driven Development (IDD) 跨工具共享开发流水线工具（支持 GitHub 与自建 GitLab）",
    )
    parser.add_argument("-v", "--version", action="version", version=f"idd {__version__}")
    parser.add_argument("--_bg-auto-update", action="store_true", dest="bg_auto_update", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=False)

    # status
    p_status = sub.add_parser("status", help="聚合并展示 Issue、Worktree TASK 进度、实时脉搏与 PR/MR CI 状态")
    p_status.add_argument("-g", "--global", dest="global_mode", action="store_true", help="跨本机所有已注册仓库全局聚合")
    p_status.add_argument("--root", type=Path, default=None, help="仓库根目录或工作树路径（在非 Git 目录不传此项时自动全局聚合）")
    p_status.add_argument("--issue", dest="issue", help="只查看指定 Issue 目录（或 #编号）")
    p_status.add_argument("--goal", dest="issue", help=argparse.SUPPRESS)
    p_status.add_argument("--open-only", action="store_true", help="只保留存在非 done 任务的 Issue")
    p_status.add_argument("--local-only", action="store_true", help="仅检查本地工作树，不查询远端 Forge")
    p_status.add_argument("--json", action="store_true", help="输出 JSON")
    p_status.set_defaults(func=cmd_status)

    # board (web dashboard)
    p_board = sub.add_parser("board", aliases=["ui"], help="启动本地 Web 实时监控看板（浏览器零 Token 盯盘）")
    p_board.add_argument("--host", default="127.0.0.1", help="监听主机地址（默认 127.0.0.1）")
    p_board.add_argument("--port", type=int, default=None, help="监听端口（默认优先 17890，占用时自动分配）")
    p_board.add_argument("--root", type=Path, default=None, help="仅监控指定单仓库路径")
    p_board.add_argument("--current-only", action="store_true", help="仅监控当前工作目录所属单仓库")
    p_board.add_argument("--local-only", action="store_true", help="仅展示本地工作树与 TASK，不查询远端 Forge")
    p_board.add_argument("--forge-ttl", type=float, default=30.0, help="远端 Issue/PR/MR 缓存秒数（默认 30）")
    p_board.add_argument("--no-open", action="store_true", help="启动服务后不自动打开浏览器")
    p_board.set_defaults(func=cmd_board)

    # preview (local HTML prototype workbench)
    p_preview = sub.add_parser("preview", help="启动本地交互原型预览工作台（支持热更新、A/B 并排对比与视口切换）")
    p_preview.add_argument("targets", nargs="+", help="HTML 文件路径（支持 `标签=路径`）或目录路径")
    p_preview.add_argument("--title", default=None, help="自定义预览工作台标题")
    p_preview.add_argument("--compare", action="store_true", help="默认开启 A/B 并排对比（需至少 2 个目标）")
    p_preview.add_argument("--host", default="127.0.0.1", help="监听主机地址（默认 127.0.0.1）")
    p_preview.add_argument("--port", type=int, default=None, help="监听端口（默认优先 17891，占用时自动分配）")
    p_preview.add_argument("--no-open", action="store_true", help="启动服务后不自动打开浏览器")
    p_preview.set_defaults(func=cmd_preview)

    # watch (terminal live monitor)
    p_watch = sub.add_parser("watch", help="启动终端实时监控面板（默认跨全部已注册仓库，每 2 秒刷新）")
    p_watch.add_argument("-g", "--global", dest="global_mode", action="store_true", help="监控所有已注册仓库（默认）")
    p_watch.add_argument("--current-only", action="store_true", help="仅监控当前仓库")
    p_watch.add_argument("--root", type=Path, default=None, help="指定监控目录")
    p_watch.add_argument("--interval", type=float, default=2.0, help="本地脉搏刷新间隔秒数（默认 2）")
    p_watch.add_argument("--forge-ttl", type=float, default=30.0, help="远端 PR/MR 与 CI 缓存秒数（默认 30）")
    p_watch.add_argument("--local-only", action="store_true", help="仅监控本地工作树，不查询远端 Forge")
    p_watch.add_argument("--open-only", action="store_true", help="仅保留含未完成 TASK 的 Worktree")
    p_watch.add_argument("--once", action="store_true", help="仅输出一帧后退出")
    p_watch.set_defaults(func=cmd_watch)

    # repos (global repo registry management)
    p_repos = sub.add_parser("repos", help="查看或管理本机全局监控的活跃仓库索引（~/.config/idd/repos.json）")
    p_repos.add_argument("--json", action="store_true", help="输出 JSON")
    repos_sub = p_repos.add_subparsers(dest="repos_command", required=False)

    p_repos_list = repos_sub.add_parser("list", help="列出已注册的活跃仓库（默认）")
    p_repos_list.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    p_repos_list.set_defaults(func=cmd_repos)

    p_repos_add = repos_sub.add_parser("add", help="将指定 Git 仓库加入全局监控索引")
    p_repos_add.add_argument("paths", nargs="+", help="仓库或工作树路径（如 .）")
    p_repos_add.add_argument("--no-repo-init", action="store_true", help="首次接管仓库时跳过自动执行 idd repo-init --apply（仍保留待初始化状态提示）")
    p_repos_add.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    p_repos_add.set_defaults(func=cmd_repos)

    p_repos_rm = repos_sub.add_parser("remove", help="从全局监控索引中移除仓库")
    p_repos_rm.add_argument("path", help="仓库或工作树路径")
    p_repos_rm.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    p_repos_rm.set_defaults(func=cmd_repos)

    p_repos_prune = repos_sub.add_parser("prune", help="清理磁盘上已删除或失效的仓库条目")
    p_repos_prune.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    p_repos_prune.set_defaults(func=cmd_repos)

    p_repos.set_defaults(func=cmd_repos)

    # issue
    p_issue = sub.add_parser("issue", help="GitHub / GitLab Issue 辅助命令")
    issue_sub = p_issue.add_subparsers(dest="issue_command", required=True)
    p_issue_create = issue_sub.add_parser("create", help="创建 Issue")
    p_issue_create.add_argument("--title", required=True, help="Issue 标题（需符合 `<type>: <描述>` 或 `<type>(<scope>): <描述>`，或配合 `--type`/`--raw`）")
    p_issue_create.add_argument("--type", dest="issue_type", choices=list(ALLOWED_TYPES), help="Issue 类型前缀（8 类标准 type，传入后自动拼接到标题）")
    p_issue_create.add_argument("--scope", help=f"可选作用域模块名（简短小写英文标识，≤ {MAX_ISSUE_SCOPE_LEN} 字符，如 sync、land、repo-init）")
    p_issue_create.add_argument("--raw", action="store_true", help="跳过 Issue 标题规范校验，按原样提交标题")
    p_issue_create.add_argument("--body", help="Issue 正文")
    p_issue_create.add_argument("--body-file", type=Path, help="从文件读取 Issue 正文")
    p_issue_create.add_argument("--label", action="append", help="添加标签（可重复）")
    p_issue_create.add_argument("--assignee", action="append", help="指派负责人（可重复）")
    p_issue_create.add_argument("--no-repo-init", action="store_true", help="首次接管仓库时跳过自动执行 idd repo-init --apply（仍保留待初始化状态提示）")
    p_issue_create.add_argument("--json", action="store_true", help="输出 JSON")
    p_issue_create.set_defaults(func=cmd_issue_create)

    # start
    p_start = sub.add_parser("start", help="认领 Issue（或本地工作项）并创建/幂等复用独立 worktree")
    p_start.add_argument("target", help="Issue 编号（如 42 / #42 / URL）或纯本地目录 slug")
    p_start.add_argument("--slug", help="覆盖自动生成的英文短别名")
    p_start.add_argument("--prefix", choices=list(ALLOWED_TYPES), help="分支前缀（允许 8 类标准 type）")
    p_start.add_argument("--base", help="基准分支（默认 origin/<default_branch> 或本地主分支）")
    p_start.add_argument("--no-push", action="store_true", help="仅创建本地工作树与分支，跳过自动推送到远端 origin")
    p_start.add_argument("--no-repo-init", action="store_true", help="首次接管仓库时跳过自动执行 idd repo-init --apply（仍保留待初始化状态提示）")
    p_start.add_argument("--json", action="store_true", help="输出 JSON")
    p_start.set_defaults(func=cmd_start)

    # sync
    p_sync = sub.add_parser("sync", help="将本地 TASK 进度同步为 Issue 原生进度条")
    p_sync.add_argument("issue_number", nargs="?", help="Issue 编号（在对应工作树内可省略）")
    p_sync.add_argument("--root", type=Path, default=Path.cwd(), help="工作树或仓库路径")
    p_sync.add_argument("--no-push", action="store_true", help="仅同步 Issue 进度条，不自动推送当前分支")
    p_sync.add_argument("--dry-run", action="store_true", help="仅预览合并后的 Issue 正文")
    p_sync.set_defaults(func=cmd_sync)

    # pr (aliased as mr for GitLab users)
    p_pr = sub.add_parser("pr", aliases=["mr"], help="基于 TASK 汇总生成结构化描述并创建或更新 PR / MR")
    p_pr.add_argument("target", nargs="?", help="Issue 编号或目录名（在对应工作树内可省略）")
    p_pr.add_argument("--title", help="自定义 PR / MR 标题")
    p_pr.add_argument("--base", help="目标基础分支（默认仓库主分支）")
    p_pr.add_argument("--draft", action="store_true", help="创建为 Draft PR / MR")
    p_pr.add_argument("--force-with-lease", action="store_true", help="使用 --force-with-lease 推送")
    pr_am_group = p_pr.add_mutually_exclusive_group()
    pr_am_group.add_argument("--auto-merge", action="store_true", help="创建/更新后自动等待 CI 结算并直线 Squash 合入（覆盖开关配置）")
    pr_am_group.add_argument("--no-auto-merge", action="store_true", help="创建/更新后仅停在待验收状态，不触发自动合入（覆盖开关配置）")
    p_pr.add_argument("--dry-run", action="store_true", help="仅预览生成的标题与正文")
    p_pr.set_defaults(func=cmd_pr)

    # ci
    p_ci = sub.add_parser("ci", help="查看 PR / MR 的 CI 状态并拉取失败日志")
    p_ci.add_argument("target", nargs="?", help="Issue 编号、PR/MR 编号或分支名（在工作树内可省略）")
    p_ci.add_argument("--watch", action="store_true", help="阻塞监听 CI 检查直到结束")
    p_ci.add_argument("--logs", action="store_true", help="拉取失败 Job/Run 的日志")
    p_ci.add_argument("--json", action="store_true", help="输出 JSON")
    p_ci.set_defaults(func=cmd_ci)

    # land
    p_land = sub.add_parser("land", help="Rebase、清理 TASK 目录并 Squash 直线合入主分支（默认保留分支与工作树）")
    p_land.add_argument("target", nargs="?", help="Issue 编号或目录名（在工作树内可省略）")
    p_land.add_argument("--title", help="自定义 Squash 提交标题")
    p_land.add_argument("--keep-tasks", action="store_true", help="保留 TASK/<issue>/ 目录不清理")
    p_land.add_argument("--force-clean-evidence", action="store_true", help="强制一并清理 evidence/ 下附件")
    p_land.add_argument("--force-unfinished-tasks", action="store_true", help="跳过未完成 TASK 状态校验并强制继续合入")
    p_land.add_argument("--rm-worktree", action="store_true", help="合入后顺带移除本地工作树目录（仍保留本地与远端分支）")
    p_land.add_argument("--auto", action="store_true", help="开启平台 Auto-Merge 后立即返回")
    p_land.add_argument("--wait-ci", action="store_true", help="推送清理或变基提交后阻塞等待远端 CI 结算再执行 Squash 合入")
    p_land.add_argument("--no-rebase", action="store_true", help="跳过合入前自动 rebase")
    p_land.add_argument("--no-check-acceptance", action="store_true", help="合入后跳过自动勾选 Issue 正文中的验收标准复选框")
    p_land.add_argument("--dry-run", action="store_true", help="仅预览合入计划与清理清单")
    p_land.set_defaults(func=cmd_land)

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="按需清理已合入且 HEAD 一致的干净工作树目录（保留所有分支）")
    p_cleanup.add_argument("--dry-run", action="store_true", help="仅预览待清理工作树目录")
    p_cleanup.set_defaults(func=cmd_cleanup)

    # repo-init
    p_repo_init = sub.add_parser("repo-init", help="检查或配置 GitHub/GitLab 仓库的仅 Squash 线性合入策略（保留分支）")
    p_repo_init.add_argument("--apply", action="store_true", help="应用线性 Squash 合入策略且合并后保留远端分支")
    p_repo_init.set_defaults(func=cmd_repo_init)

    # config
    p_config = sub.add_parser("config", help="查看或配置全局与单仓库自动准入合入开关（auto_merge）")
    p_config.add_argument("--repo", type=Path, default=None, help="指定目标仓库路径（默认当前工作区所属仓库）")
    p_config.add_argument("--json", action="store_true", help="输出 JSON")
    config_sub = p_config.add_subparsers(dest="config_command", required=False)

    p_config_show = config_sub.add_parser("show", help="查看当前全局与仓库配置（默认）")
    p_config_show.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p_config_show.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    p_config_show.set_defaults(func=cmd_config)

    p_config_am = config_sub.add_parser("auto-merge", help="查看或设置 PR/MR 自动准入与自动合入开关")
    p_config_am.add_argument(
        "value",
        nargs="?",
        default="status",
        choices=["status", "on", "off", "inherit", "true", "false", "1", "0", "unset", "default", "reset"],
        help="目标状态：on / off / inherit（恢复跟随全局）/ status（查看）",
    )
    p_config_am.add_argument("-g", "--global", dest="global_mode", action="store_true", help="读取或修改全局默认开关（~/.config/idd/config.json）")
    p_config_am.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="指定目标仓库路径（默认当前工作区所属仓库）")
    p_config_am.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    p_config_am.set_defaults(func=cmd_config)
    p_config.set_defaults(func=cmd_config)

    # auth
    p_auth = sub.add_parser("auth", help="管理自建 GitLab / GitHub 主机凭据（~/.config/idd/hosts.json）")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True)
    p_auth_login = auth_sub.add_parser("login", help="保存并校验自建主机访问 Token")
    p_auth_login.add_argument("host", help="主机名或完整 URL（如 gitlab.company.com 或 http://10.0.0.5:8080）")
    p_auth_login.add_argument("--token", required=True, help="Personal Access Token")
    p_auth_login.add_argument("--forge", choices=["gitlab", "github"], help="平台类型（非 github.com 默认为 gitlab）")
    p_auth_login.add_argument("--http", action="store_true", help="裸主机名时使用 http:// 而非 https://")
    p_auth_login.add_argument("--no-verify", action="store_true", help="跳过在线 Token 校验直接保存")
    p_auth_login.set_defaults(func=cmd_auth)

    p_auth_status = auth_sub.add_parser("status", help="查看已配置的主机与登录状态")
    p_auth_status.set_defaults(func=cmd_auth)

    p_auth_logout = auth_sub.add_parser("logout", help="移除已保存的主机凭据")
    p_auth_logout.add_argument("host", help="主机名或 URL")
    p_auth_logout.set_defaults(func=cmd_auth)

    # upgrade
    p_upgrade = sub.add_parser("upgrade", help="检查或立即拉取远端更新并快进同步本地 idd")
    p_upgrade.add_argument("--check", action="store_true", help="仅检查远端是否有更新，不合并")
    p_upgrade.set_defaults(func=cmd_upgrade)

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="安全完全卸载 idd（移除软链、技能仓库、配置与缓存）")
    p_uninstall.add_argument("-y", "--yes", action="store_true", help="跳过交互确认直接卸载")
    p_uninstall.add_argument("--dry-run", action="store_true", help="仅预览待删除路径，不实际删除")
    p_uninstall.add_argument("--keep-config", action="store_true", help="保留 ~/.config/idd 配置目录（主机凭据与仓库索引）")
    p_uninstall.add_argument("--force", action="store_true", help="即使本地技能仓库有未提交改动或未推送提交也强制卸载")
    p_uninstall.set_defaults(func=cmd_uninstall)

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
    except (IddError, ForgeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
