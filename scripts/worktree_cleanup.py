"""Eligibility and locked removal of already-merged Git worktrees."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from command_runner import IddError, run_cmd
from git_worktrees import list_worktrees
from naming import BRANCH_PREFIXES
from repository_lock import MAIN_GIT_LOCK, repo_file_lock


@dataclass(frozen=True)
class CleanupResult:
    status: str
    path: Path
    message: str = ""
    branch: str = ""
    ref: str = ""
    head: str = ""


@dataclass(frozen=True)
class CleanWorktree:
    branch: str
    head: str


def cleanup_scope_error(main: Path, path: Path, branch: str, managed_root: Path) -> str:
    if path == main:
        return "禁止清理主工作树目录"
    if not branch or branch == "(detached)":
        return "工作树处于游离 HEAD 状态，已跳过清理"
    if path.parent != managed_root and not branch.startswith(BRANCH_PREFIXES):
        return "工作树不在受管目录或规范分支前缀下，已跳过清理"
    return ""


def inspect_worktree(main: Path, path: Path, managed_root: Path) -> CleanWorktree | CleanupResult:
    """Inspect current Git membership, branch, local changes and commit identity."""
    try:
        entries = list_worktrees(main, timeout=10.0)
    except ValueError as exc:
        return CleanupResult("error", path, str(exc))
    entry = next((wt for wt in entries if Path(wt["path"]).resolve() == path), None)
    if entry is None:
        if not path.exists():
            return CleanupResult("already_removed", path, "工作树目录已不存在")
        return CleanupResult("rejected", path, "目标目录不属于该仓库的活动工作树")

    branch = entry.get("branch", "")
    error = cleanup_scope_error(main, path, branch, managed_root)
    if error:
        return CleanupResult("rejected", path, error, branch if path != main else "")

    status = run_cmd(["git", "-C", str(path), "status", "--porcelain"], check=False)
    if status.returncode:
        return CleanupResult("error", path, status.stderr.strip() or "读取工作区状态失败", branch)
    dirty = len(status.stdout.splitlines())
    if dirty:
        return CleanupResult("skipped_dirty", path, f"工作区存在 {dirty} 处未提交改动，已跳过清理", branch)
    head = run_cmd(["git", "-C", str(path), "rev-parse", "HEAD"], check=False)
    if head.returncode or not head.stdout.strip():
        return CleanupResult("error", path, head.stderr.strip() or "读取本地 HEAD 失败", branch)
    return CleanWorktree(branch, head.stdout.strip())


def remove_merged_worktree(
    main: Path,
    path: Path,
    expected_branch: str,
    managed_root: Path,
    merged: list[dict[str, Any]],
    *,
    ref_prefix: str,
    dry_run: bool = False,
) -> CleanupResult:
    """Revalidate local facts under the repository lock after the remote lookup."""
    if not merged:
        return CleanupResult("skipped_unmerged", path, f"未查询到分支 {expected_branch} 的已合入 PR/MR，已跳过清理", expected_branch)

    try:
        with repo_file_lock(main, MAIN_GIT_LOCK, owner_info={"command": "cleanup", "branch": expected_branch}):
            current = inspect_worktree(main, path, managed_root)
            if isinstance(current, CleanupResult):
                return current
            if current.branch != expected_branch:
                return CleanupResult("rejected", path, "工作树分支已变更，已跳过清理", current.branch)
            match = next((change for change in merged if change.get("headRefOid") == current.head), None)
            if match is None:
                return CleanupResult(
                    "skipped_unmerged", path,
                    f"本地 HEAD ({current.head[:7]}) 与已合入 PR/MR 不一致，可能存在合入后新增提交，已跳过清理",
                    current.branch, head=current.head,
                )
            ref = f"{ref_prefix}{match['number']}"
            if dry_run:
                return CleanupResult("dry_run", path, branch=current.branch, ref=ref)
            proc = run_cmd(["git", "-C", str(main), "worktree", "remove", str(path)], check=False)
            if proc.returncode:
                return CleanupResult("error", path, (proc.stderr or proc.stdout).strip() or "移除工作树失败", current.branch)
            return CleanupResult("removed", path, branch=current.branch, ref=ref)
    except (IddError, OSError) as exc:
        return CleanupResult("error", path, str(exc), expected_branch)
