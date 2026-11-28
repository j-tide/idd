"""Read Git's worktree inventory in its native order, with the main checkout first."""

from __future__ import annotations

from pathlib import Path
import subprocess


def default_worktree_root(main_worktree: Path) -> Path:
    return main_worktree.parent / f"{main_worktree.name}-worktrees"


def list_worktrees(repo_root: Path, *, timeout: float | None = None) -> list[dict[str, str]]:
    """Return Git worktrees without refreshing the index. Polling callers bound their wait."""
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.quotePath=false", "-C", str(repo_root),
             "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"无法列出 Git 工作树：{repo_root}") from exc
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or f"无法列出 Git 工作树：{repo_root}")

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
