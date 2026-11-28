"""Read Git's worktree inventory in its native order, with the main checkout first."""

from __future__ import annotations

from pathlib import Path
import subprocess


def default_worktree_root(main_worktree: Path) -> Path:
    return main_worktree.parent / f"{main_worktree.name}-worktrees"


def read_git(cwd: Path, args: list[str], *, timeout: float | None = 10.0) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command with `--no-optional-locks` to avoid index lock contention."""
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.quotePath=false", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def list_worktrees(repo_root: Path, *, timeout: float | None = None) -> list[dict[str, str]]:
    """Return Git worktrees without refreshing the index. Polling callers bound their wait."""
    proc = read_git(repo_root, ["worktree", "list", "--porcelain"], timeout=timeout)
    if proc is None or proc.returncode:
        detail = proc.stderr.strip() if proc is not None else ""
        raise ValueError(detail or f"无法列出 Git 工作树：{repo_root}")

    entries: list[dict[str, str]] = []
    for block in proc.stdout.split("\n\n"):
        entry: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith("worktree "):
                entry["path"] = line[len("worktree "):]
            elif line.startswith("branch "):
                entry["branch"] = line[len("branch "):].removeprefix("refs/heads/")
            elif line == "detached":
                entry["branch"] = "(detached)"
        if entry.get("path"):
            entries.append(entry)
    return entries

def has_remote_origin(repo: Path) -> bool:
    """Best-effort probe for monitor clients that also support offline repositories."""
    remotes = read_git(repo, ["remote"])
    return remotes is not None and remotes.returncode == 0 and "origin" in remotes.stdout.splitlines()


def ref_exists(repo: Path, ref: str, *, timeout: float | None = None) -> bool:
    result = read_git(repo, ["show-ref", "--verify", "--quiet", ref], timeout=timeout)
    return result is not None and result.returncode == 0


def detect_default_branch(repo: Path, has_origin: bool, *, timeout: float | None = None) -> str:
    if has_origin:
        sym = read_git(repo, ["symbolic-ref", "refs/remotes/origin/HEAD"], timeout=timeout)
        if sym is not None and sym.returncode == 0:
            ref = sym.stdout.strip()
            if ref.startswith("refs/remotes/origin/"):
                return ref.removeprefix("refs/remotes/origin/")
    for branch in ("main", "master"):
        if ref_exists(repo, f"refs/heads/{branch}", timeout=timeout):
            return branch
        if has_origin and ref_exists(repo, f"refs/remotes/origin/{branch}", timeout=timeout):
            return branch
    return "main"


def main_worktree_and_inventory(path: Path) -> tuple[Path | None, list[dict[str, str]]]:
    """Return `(canonical_main_worktree, all_worktrees)` using a single `git worktree list` call."""
    target = path.expanduser()
    if not target.is_dir():
        return None, []
    try:
        worktrees = list_worktrees(target, timeout=10.0)
    except ValueError:
        return None, []
    if not worktrees:
        return None, []
    return Path(worktrees[0]["path"]).resolve(), worktrees


def resolve_main_worktree(path: Path) -> Path | None:
    """Return canonical main worktree path if `path` resides inside a Git repository, else None."""
    main_wt, _ = main_worktree_and_inventory(path)
    return main_wt
