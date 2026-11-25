#!/usr/bin/env python3
"""Global repository registry, non-locking worktree live pulse, snapshot aggregator, and terminal monitor."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from forge import ForgeError, get_config_dir, get_forge
import task_status


_REPOS_LOCK = threading.Lock()
_IGNORED_GIT_ERROR = (OSError, subprocess.SubprocessError)


def get_repos_path() -> Path:
    """Return path to the global active-repository registry JSON file."""
    return get_config_dir() / "repos.json"


def _run_git_ro(cwd: Path, args: list[str], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command with `--no-optional-locks` to avoid index lock contention."""
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.quotePath=false", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except _IGNORED_GIT_ERROR:
        return None


def list_git_worktrees_ro(repo_root: Path) -> list[dict[str, str]]:
    """List git worktrees using `--no-optional-locks`."""
    proc = _run_git_ro(repo_root, ["worktree", "list", "--porcelain"])
    if proc is None or proc.returncode != 0:
        detail = proc.stderr.strip() if proc else ""
        raise ValueError(detail or f"无法列出 Git 工作树：{repo_root}")
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            if current.get("path"):
                worktrees.append(current)
            current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/"):]
            current["branch"] = ref
        elif line == "detached":
            current.setdefault("branch", "(detached)")
    if current.get("path"):
        worktrees.append(current)
    return worktrees


def resolve_main_worktree_ro(path: Path) -> Path | None:
    """Return canonical main worktree path if `path` resides inside a Git repository, else None."""
    target = path.expanduser()
    if not target.is_dir():
        return None
    try:
        worktrees = list_git_worktrees_ro(target)
    except ValueError:
        return None
    if not worktrees:
        return None
    return Path(worktrees[0]["path"]).resolve()


def _detect_repo_meta_ro(main_worktree: Path) -> tuple[bool, str]:
    """Return (has_origin, default_branch) using read-only git commands."""
    rem = _run_git_ro(main_worktree, ["remote"])
    remotes = {line.strip() for line in rem.stdout.splitlines() if line.strip()} if rem and rem.returncode == 0 else set()
    has_origin = "origin" in remotes
    if has_origin:
        sym = _run_git_ro(main_worktree, ["symbolic-ref", "refs/remotes/origin/HEAD"])
        if sym and sym.returncode == 0 and sym.stdout.strip().startswith("refs/remotes/origin/"):
            return True, sym.stdout.strip()[len("refs/remotes/origin/"):]
    for candidate in ("main", "master"):
        p1 = _run_git_ro(main_worktree, ["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"])
        if p1 and p1.returncode == 0:
            return has_origin, candidate
        if has_origin:
            p2 = _run_git_ro(main_worktree, ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{candidate}"])
            if p2 and p2.returncode == 0:
                return has_origin, candidate
    return has_origin, "main"


# ---------------------------------------------------------------------------
# Global repository registry (`~/.config/idd/repos.json`)
# ---------------------------------------------------------------------------


def _save_repos_unlocked(entries: list[dict[str, Any]]) -> None:
    path = get_repos_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="repos-", suffix=".tmp", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"repos": entries}, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_raw_repos_unlocked() -> list[dict[str, Any]]:
    path = get_repos_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("repos") if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"].strip():
            result.append(item)
    return result


def load_registered_repos(*, prune_missing: bool = True) -> list[dict[str, Any]]:
    """Load registered repository entries sorted by recency, optionally pruning stale paths."""
    with _REPOS_LOCK:
        raw_items = _read_raw_repos_unlocked()
        seen: dict[str, dict[str, Any]] = {}
        dirty = False

        for item in raw_items:
            raw_path = item["path"].strip()
            try:
                resolved = Path(raw_path).expanduser().resolve()
            except OSError:
                dirty = True
                continue
            key = str(resolved)
            exists_git = resolved.is_dir() and (resolved / ".git").exists()
            if prune_missing and not exists_git:
                dirty = True
                continue
            ts = float(item.get("last_seen_at") or 0.0)
            prev = seen.get(key)
            if prev is not None:
                dirty = True
                if ts <= float(prev.get("last_seen_at") or 0.0):
                    continue
            elif key != raw_path:
                dirty = True
            seen[key] = {
                "path": key,
                "name": str(item.get("name") or resolved.name),
                "last_seen_at": ts,
            }

        entries = sorted(seen.values(), key=lambda r: (-float(r.get("last_seen_at") or 0.0), r["name"]))
        if dirty:
            _save_repos_unlocked(entries)
        return entries


def register_repo(main_worktree: Path) -> dict[str, Any]:
    """Register or touch a repository main worktree in `repos.json`."""
    resolved = main_worktree.expanduser().resolve()
    key = str(resolved)
    now = time.time()
    entry = {"path": key, "name": resolved.name, "last_seen_at": now}

    with _REPOS_LOCK:
        raw_items = _read_raw_repos_unlocked()
        by_path: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            try:
                p = Path(item["path"]).expanduser().resolve()
            except OSError:
                continue
            if p.is_dir() and (p / ".git").exists():
                by_path[str(p)] = {
                    "path": str(p),
                    "name": str(item.get("name") or p.name),
                    "last_seen_at": float(item.get("last_seen_at") or 0.0),
                }
        by_path[key] = entry
        entries = sorted(by_path.values(), key=lambda r: (-float(r.get("last_seen_at") or 0.0), r["name"]))
        _save_repos_unlocked(entries)
    return entry


def unregister_repo(target: Path) -> bool:
    """Remove a repository (matched by path or containing main worktree) from `repos.json`."""
    resolved = target.expanduser().resolve()
    candidates = {str(resolved)}
    main_wt = resolve_main_worktree_ro(resolved)
    if main_wt is not None:
        candidates.add(str(main_wt))

    with _REPOS_LOCK:
        raw_items = _read_raw_repos_unlocked()
        kept: list[dict[str, Any]] = []
        removed = False
        for item in raw_items:
            try:
                p_str = str(Path(item["path"]).expanduser().resolve())
            except OSError:
                p_str = item["path"].strip()
            if p_str in candidates:
                removed = True
            else:
                kept.append(item)
        if removed:
            kept.sort(key=lambda r: (-float(r.get("last_seen_at") or 0.0), str(r.get("name", ""))))
            _save_repos_unlocked(kept)
        return removed


# ---------------------------------------------------------------------------
# Worktree Live Pulse Probe
# ---------------------------------------------------------------------------


def format_relative_time(seconds: float) -> str:
    """Format elapsed seconds into concise human-readable Chinese relative time."""
    if seconds < 0:
        return "无记录"
    secs = int(seconds)
    if secs < 5:
        return "刚刚"
    if secs < 60:
        return f"{secs}秒前"
    if secs < 3600:
        return f"{secs // 60}分钟前"
    if secs < 86400:
        return f"{secs // 3600}小时前"
    return f"{secs // 86400}天前"


def _classify_activity(idle_seconds: float, has_active_work: bool) -> str:
    if idle_seconds < 0:
        return "quiet"
    if idle_seconds < 60:
        return "active"
    if idle_seconds < 600:
        return "warm"
    if idle_seconds < 1800:
        return "idle" if has_active_work else "quiet"
    return "stalled" if has_active_work else "quiet"


def _format_pulse_summary(
    activity_state: str,
    last_active_ago: str,
    dirty_count: int,
    insertions: int,
    deletions: int,
    git_op: str,
) -> str:
    if activity_state == "active":
        time_part = "🟢 刚刚活跃" if last_active_ago == "刚刚" else f"🟢 {last_active_ago}"
    elif activity_state == "warm":
        time_part = f"🟡 {last_active_ago}"
    elif activity_state == "stalled":
        short_ago = last_active_ago[:-1] if last_active_ago.endswith("前") else last_active_ago
        time_part = f"🟠 {short_ago}无动静"
    else:
        time_part = f"⚪ {last_active_ago}"

    parts = [time_part]
    if git_op == "rebasing":
        parts.append("Rebasing")
    elif git_op == "merging":
        parts.append("Merging")

    if dirty_count > 0:
        diff_suffix = f" (+{insertions}/-{deletions})" if (insertions > 0 or deletions > 0) else ""
        parts.append(f"✏️ {dirty_count}文件{diff_suffix}")
    else:
        parts.append("干净")
    return " · ".join(parts)


def inspect_worktree_pulse(wt_path: Path, *, in_progress_count: int = 0) -> dict[str, Any]:
    """Collect pure-local, non-locking live activity signals for a single git worktree."""
    mtimes: list[float] = []
    changed_files: list[dict[str, str]] = []
    modified_count = 0
    untracked_count = 0

    if wt_path.is_dir():
        st_proc = _run_git_ro(wt_path, ["status", "--porcelain=v1", "-uall"])
        if st_proc and st_proc.returncode == 0:
            for line in st_proc.stdout.splitlines():
                if len(line) < 4:
                    continue
                code = line[:2]
                raw_path = line[3:].strip()
                if raw_path.startswith('"') and raw_path.endswith('"') and len(raw_path) >= 2:
                    raw_path = raw_path[1:-1]
                rel_path = raw_path.split(" -> ", 1)[1].strip() if " -> " in raw_path else raw_path
                if code == "??":
                    untracked_count += 1
                else:
                    modified_count += 1
                if len(changed_files) < 20:
                    changed_files.append({"code": code.strip() or code, "path": rel_path})
                try:
                    mtimes.append((wt_path / rel_path).lstat().st_mtime)
                except OSError:
                    pass

    dirty_count = modified_count + untracked_count
    has_more_files = dirty_count > len(changed_files)

    insertions = 0
    deletions = 0
    if wt_path.is_dir() and modified_count > 0:
        diff_proc = _run_git_ro(wt_path, ["diff", "HEAD", "--shortstat"])
        if diff_proc is None or diff_proc.returncode != 0:
            diff_proc = _run_git_ro(wt_path, ["diff", "--shortstat"])
        if diff_proc and diff_proc.returncode == 0:
            ins_m = re.search(r"(\d+)\s+insertion", diff_proc.stdout)
            del_m = re.search(r"(\d+)\s+deletion", diff_proc.stdout)
            if ins_m:
                insertions = int(ins_m.group(1))
            if del_m:
                deletions = int(del_m.group(1))

    last_commit_sha = ""
    last_commit_ts = 0.0
    last_commit_subject = ""
    if wt_path.is_dir():
        log_proc = _run_git_ro(wt_path, ["log", "-1", "--format=%h%x1f%ct%x1f%s"])
        if log_proc and log_proc.returncode == 0 and log_proc.stdout.strip():
            parts = log_proc.stdout.strip().split("\x1f", 2)
            if len(parts) >= 2:
                last_commit_sha = parts[0].strip()
                try:
                    last_commit_ts = float(parts[1].strip())
                    mtimes.append(last_commit_ts)
                except ValueError:
                    pass
            if len(parts) == 3:
                last_commit_subject = parts[2].strip()

    git_op = ""
    if wt_path.is_dir():
        gd_proc = _run_git_ro(wt_path, ["rev-parse", "--git-dir"])
        if gd_proc and gd_proc.returncode == 0 and gd_proc.stdout.strip():
            raw_gd = Path(gd_proc.stdout.strip())
            git_dir = raw_gd if raw_gd.is_absolute() else (wt_path / raw_gd).resolve()
            for fname in ("index", "HEAD"):
                try:
                    mtimes.append((git_dir / fname).stat().st_mtime)
                except OSError:
                    pass
            if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
                git_op = "rebasing"
            elif (git_dir / "MERGE_HEAD").exists():
                git_op = "merging"

    task_dir = wt_path / "TASK"
    if task_dir.is_dir():
        try:
            for md in task_dir.rglob("*.md"):
                try:
                    mtimes.append(md.stat().st_mtime)
                except OSError:
                    pass
        except OSError:
            pass

    last_active_ts = max(mtimes, default=0.0)
    idle_seconds = max(0.0, time.time() - last_active_ts) if last_active_ts > 0 else -1.0
    last_active_ago = format_relative_time(idle_seconds)
    has_active_work = bool(dirty_count > 0 or in_progress_count > 0 or git_op)
    activity_state = _classify_activity(idle_seconds, has_active_work)
    pulse_summary = _format_pulse_summary(
        activity_state,
        last_active_ago,
        dirty_count,
        insertions,
        deletions,
        git_op,
    )

    return {
        "dirty_count": dirty_count,
        "modified_count": modified_count,
        "untracked_count": untracked_count,
        "insertions": insertions,
        "deletions": deletions,
        "changed_files": changed_files,
        "has_more_files": has_more_files,
        "last_commit_sha": last_commit_sha,
        "last_commit_ts": last_commit_ts,
        "last_commit_subject": last_commit_subject,
        "last_active_ts": last_active_ts,
        "idle_seconds": round(idle_seconds, 1) if idle_seconds >= 0 else -1.0,
        "last_active_ago": last_active_ago,
        "activity_state": activity_state,
        "git_op": git_op,
        "pulse_summary": pulse_summary,
    }


# ---------------------------------------------------------------------------
# Thread-Safe Remote Forge Snapshot Cache
# ---------------------------------------------------------------------------


class ForgeSnapshotCache:
    """Thread-safe TTL cache for GitHub/GitLab open issues and open PRs/MRs per repo."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}

    def get(
        self,
        main_worktree: Path,
        *,
        has_origin: bool,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return cached or freshly queried forge snapshot for `main_worktree`."""
        if not has_origin:
            return {
                "forge_type": "local",
                "mr_label": "PR/MR",
                "mr_prefix": "#",
                "forge_connected": False,
                "open_issues": [],
                "open_changes": [],
                "warnings": [],
                "fetched_at": 0.0,
            }

        key = str(main_worktree.resolve())
        now = time.time()
        with self._lock:
            cached = self._entries.get(key)
            if (
                cached is not None
                and not force_refresh
                and self.ttl_seconds > 0
                and (now - cached["fetched_at"]) < self.ttl_seconds
            ):
                return dict(cached)

        forge = get_forge(main_worktree)
        forge_type = forge.forge_type
        mr_label = forge.mr_label
        mr_prefix = forge.mr_prefix
        open_issues: list[dict[str, Any]] = []
        open_changes: list[dict[str, Any]] = []
        forge_connected = False
        warnings: list[str] = []

        try:
            issues_res = forge.list_open_issues(limit=100)
            changes_res = forge.list_changes(state="open", limit=100)
            if isinstance(issues_res, list) and isinstance(changes_res, list):
                open_issues = issues_res
                open_changes = changes_res
                forge_connected = True
            else:
                warnings.append("远端仓库查询不可用，已降级为本地工作树视图。")
        except ForgeError as exc:
            warnings.append(f"{exc}（已降级为本地工作树视图）")

        entry = {
            "forge_type": forge_type,
            "mr_label": mr_label,
            "mr_prefix": mr_prefix,
            "forge_connected": forge_connected,
            "open_issues": open_issues,
            "open_changes": open_changes,
            "warnings": warnings,
            "fetched_at": time.time(),
        }
        if self.ttl_seconds > 0:
            with self._lock:
                self._entries[key] = entry
        return dict(entry)


# ---------------------------------------------------------------------------
# Snapshot Aggregation
# ---------------------------------------------------------------------------


def format_change_badge(change: dict[str, Any], mr_label: str, mr_prefix: str) -> str:
    """Format compact PR/MR + CI status string."""
    num = change.get("number")
    prefix = f"{mr_label} {mr_prefix}{num}" if num else mr_label
    if change.get("isDraft"):
        prefix += " (Draft)"
    overall = change.get("checks_overall") or "NONE"
    badges = {
        "PASS": "✅ CI 全绿",
        "FAIL": "❌ CI 失败",
        "PENDING": "⏳ CI 运行中",
        "NONE": "⚪ 无 CI",
    }
    state = change.get("mergeStateStatus") or ""
    extra = " (落后/冲突)" if state in {"BEHIND", "DIRTY"} else ""
    return f"{prefix} · {badges.get(overall, overall)}{extra}"


def _pick_current_task(tasks: list[dict[str, Any]]) -> tuple[str, str]:
    for wanted in ("in_progress", "blocked", "planned"):
        for task in tasks:
            if task.get("status") == wanted:
                tid = str(task.get("id") or "")
                title = str(task.get("title") or "").strip()
                label = title if (not tid or title.startswith(tid)) else f"{tid} {title}"
                return label, wanted
    return "", ""


def _infer_worktree_issue_num(branch: str, wt_path: Path) -> int | None:
    m = re.search(r"(?:^|/)(\d+)(?:-|$)", branch or "")
    if m:
        return int(m.group(1))
    d = re.match(r"^(\d+)(?:-|$)", wt_path.name)
    return int(d.group(1)) if d else None


def _build_status_row(
    *,
    issue_number: int,
    title: str,
    url: str,
    item: dict[str, Any] | None,
    change: dict[str, Any] | None,
    mr_label: str,
    mr_prefix: str,
    repo_name: str,
    repo_path: str,
    forge_type: str,
    forge_connected: bool,
) -> dict[str, Any]:
    task_progress = f"{item['done']} / {item['total']}" if item else "—"
    wt_path = item.get("worktree", "") if item else ""
    branch = item.get("branch", "") if item else (change.get("headRefName", "") if change else "")

    if change:
        overall = change.get("checks_overall") or "NONE"
        if overall == "FAIL":
            stage = "🛠️ 修 CI"
        elif overall == "PENDING":
            stage = "⏳ CI 运行中"
        elif change.get("isDraft"):
            stage = f"📝 草稿 {mr_label}"
        else:
            stage = "🔵 待合入"
    elif item:
        counts = item["counts"]
        if counts.get("blocked", 0) > 0:
            stage = "⛔ 受阻"
        elif item["total"] > 0 and item["done"] == item["total"]:
            stage = f"🟢 待提 {mr_label}"
        else:
            stage = "🟡 开发中"
    else:
        stage = "⚪ 待认领"

    change_summary = format_change_badge(change, mr_label, mr_prefix) if change else "—"
    return {
        "issue_number": issue_number,
        "title": title,
        "url": url,
        "stage": stage,
        "task_progress": task_progress,
        "worktree": wt_path,
        "branch": branch,
        "change": change,
        "change_summary": change_summary,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "forge_type": forge_type,
        "forge_connected": forge_connected,
        "issue_dir": item.get("issue", "") if item else "",
        "counts": item.get("counts", {s: 0 for s in task_status.STATUSES}) if item else {s: 0 for s in task_status.STATUSES},
        "tasks": item.get("tasks", []) if item else [],
        "current_task": item.get("current_task", "") if item else "",
        "current_task_status": item.get("current_task_status", "") if item else "",
        "pulse": item.get("pulse") if item else None,
    }


def _collect_all_worktrees_ro(main_worktree: Path, issue_filter: str | None, open_only: bool) -> dict[str, Any]:
    worktrees = list_git_worktrees_ro(main_worktree)
    all_entries: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    matched_any = issue_filter is None

    for wt in worktrees:
        wt_path = Path(wt["path"]).resolve()
        task_root = wt_path / "TASK"
        if not task_root.is_dir():
            continue
        entries, warnings, matched = task_status._collect_from_task_root(  # noqa: SLF001
            task_root,
            issue_filter,
            open_only,
            worktree=wt_path,
            branch=wt.get("branch", ""),
        )
        if matched:
            matched_any = True
        for entry in entries:
            dedup_key = (entry["issue"], str(wt_path))
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            all_entries.append(entry)
        all_warnings.extend(warnings)

    if issue_filter is not None and not matched_any:
        raise ValueError(f"没有匹配的 Issue 目录：{issue_filter}")

    all_entries.sort(key=lambda item: (item.get("issue_number") or 10**9, item["issue"], item.get("worktree", "")))
    return {"issues": all_entries, "warnings": all_warnings}


def collect_repo_snapshot(
    root: Path,
    *,
    issue_filter: str | None = None,
    open_only: bool = False,
    local_only: bool = False,
    forge_cache: ForgeSnapshotCache | None = None,
    force_refresh: bool = False,
    register: bool = True,
) -> dict[str, Any]:
    """Collect unified task + worktree pulse + remote PR/MR/Issue snapshot for a repo or TASK/ dir."""
    resolved = root.expanduser().resolve()
    main_wt = resolve_main_worktree_ro(resolved)

    if main_wt is not None:
        if register:
            register_repo(main_wt)
        has_origin, default_branch = _detect_repo_meta_ro(main_wt)
        wt_data = _collect_all_worktrees_ro(main_wt, issue_filter, open_only)
        scan_root = main_wt
        all_worktrees = list_git_worktrees_ro(main_wt)
        repo_name = main_wt.name
        repo_path_str = str(main_wt)
    else:
        task_root = resolved / "TASK"
        if not task_root.is_dir():
            raise ValueError(f"当前路径既不是 Git 仓库，也不存在 TASK/ 目录：{resolved}")
        wt_data = task_status.collect(task_root, issue_filter, open_only)
        has_origin = False
        default_branch = "main"
        scan_root = resolved
        all_worktrees = []
        repo_name = resolved.name
        repo_path_str = str(resolved)

    warnings = list(wt_data.get("warnings", []))
    local_entries: list[dict[str, Any]] = wt_data.get("issues", [])

    forge_info = {
        "forge_type": "local",
        "mr_label": "PR/MR",
        "mr_prefix": "#",
        "forge_connected": False,
        "open_issues": [],
        "open_changes": [],
        "warnings": [],
        "fetched_at": 0.0,
    }
    if main_wt is not None and not local_only and not issue_filter and has_origin:
        cache = forge_cache if forge_cache is not None else ForgeSnapshotCache(ttl_seconds=0.0)
        forge_info = cache.get(scan_root, has_origin=has_origin, force_refresh=force_refresh)
        warnings.extend(forge_info["warnings"])

    forge_type = forge_info["forge_type"]
    mr_label = forge_info["mr_label"]
    mr_prefix = forge_info["mr_prefix"]
    forge_connected = bool(forge_info["forge_connected"])
    open_issues: list[dict[str, Any]] = forge_info["open_issues"]
    open_changes: list[dict[str, Any]] = forge_info["open_changes"]
    open_issue_numbers = {int(i["number"]) for i in open_issues if i.get("number") is not None}

    worktrees_with_tasks: set[str] = set()
    for entry in local_entries:
        wt_str = entry.get("worktree", "")
        if wt_str:
            worktrees_with_tasks.add(str(Path(wt_str).resolve()))
            pulse = inspect_worktree_pulse(
                Path(wt_str),
                in_progress_count=int(entry["counts"].get("in_progress", 0)),
            )
            entry["pulse"] = pulse
        else:
            entry["pulse"] = None
        cur_label, cur_status = _pick_current_task(entry.get("tasks", []))
        entry["current_task"] = cur_label
        entry["current_task_status"] = cur_status
        entry["repo_name"] = repo_name
        entry["repo_path"] = repo_path_str

    retained_idle_worktrees: list[dict[str, Any]] = []
    if main_wt is not None and not issue_filter:
        main_resolved_str = str(main_wt.resolve())
        for wt in all_worktrees:
            wt_p = Path(wt["path"]).resolve()
            wt_str = str(wt_p)
            if wt_str == main_resolved_str or wt_str in worktrees_with_tasks:
                continue
            if not wt_p.is_dir():
                continue
            branch = wt.get("branch", "")
            inum = _infer_worktree_issue_num(branch, wt_p)
            pulse = inspect_worktree_pulse(wt_p, in_progress_count=0)
            is_open_issue = inum is not None and inum in open_issue_numbers
            is_dirty = pulse["dirty_count"] > 0
            looks_post_land = pulse.get("last_commit_subject", "").startswith("chore: 清理已汇总的任务记录")
            is_local_active = (not forge_connected) and (not looks_post_land)

            if is_open_issue or is_dirty or is_local_active:
                synthetic_entry = {
                    "issue": wt_p.name,
                    "issue_number": inum,
                    "total": 0,
                    "done": 0,
                    "counts": {s: 0 for s in task_status.STATUSES},
                    "tasks": [],
                    "worktree": wt_str,
                    "branch": branch,
                    "pulse": pulse,
                    "current_task": "",
                    "current_task_status": "",
                    "repo_name": repo_name,
                    "repo_path": repo_path_str,
                }
                local_entries.append(synthetic_entry)
            else:
                retained_idle_worktrees.append(
                    {
                        "worktree": wt_str,
                        "name": wt_p.name,
                        "branch": branch,
                        "issue_number": inum,
                        "last_active_ago": pulse["last_active_ago"],
                        "last_commit_sha": pulse["last_commit_sha"],
                    }
                )

    items_by_issue: dict[int, dict[str, Any]] = {}
    local_only_items: list[dict[str, Any]] = []
    for item in local_entries:
        inum = item.get("issue_number")
        if inum is not None:
            items_by_issue[int(inum)] = item
        else:
            local_only_items.append(item)

    changes_by_branch = {c.get("headRefName", ""): c for c in open_changes}
    changes_by_issue: dict[int, dict[str, Any]] = {}
    for ch in open_changes:
        m = re.search(r"(?:^|/)(\d+)(?:-|$)", ch.get("headRefName", ""))
        if m:
            changes_by_issue[int(m.group(1))] = ch

    rows: list[dict[str, Any]] = []
    seen_issues: set[int] = set()

    for issue in open_issues:
        inum = int(issue["number"])
        seen_issues.add(inum)
        item = items_by_issue.get(inum)
        branch = item.get("branch", "") if item else ""
        change = (changes_by_branch.get(branch) if branch else None) or changes_by_issue.get(inum)
        rows.append(
            _build_status_row(
                issue_number=inum,
                title=issue.get("title", ""),
                url=issue.get("url", ""),
                item=item,
                change=change,
                mr_label=mr_label,
                mr_prefix=mr_prefix,
                repo_name=repo_name,
                repo_path=repo_path_str,
                forge_type=forge_type,
                forge_connected=forge_connected,
            )
        )

    for inum, item in sorted(items_by_issue.items()):
        if inum not in seen_issues:
            change = changes_by_branch.get(item.get("branch", "")) or changes_by_issue.get(inum)
            rows.append(
                _build_status_row(
                    issue_number=inum,
                    title=item["issue"],
                    url="",
                    item=item,
                    change=change,
                    mr_label=mr_label,
                    mr_prefix=mr_prefix,
                    repo_name=repo_name,
                    repo_path=repo_path_str,
                    forge_type=forge_type,
                    forge_connected=forge_connected,
                )
            )

    used_change_numbers = {r["change"]["number"] for r in rows if r.get("change")}
    orphan_changes = []
    for ch in open_changes:
        if ch.get("number") not in used_change_numbers:
            ch_copy = dict(ch)
            ch_copy["repo_name"] = repo_name
            ch_copy["repo_path"] = repo_path_str
            ch_copy["mr_label"] = mr_label
            ch_copy["mr_prefix"] = mr_prefix
            ch_copy["change_summary"] = format_change_badge(ch, mr_label, mr_prefix)
            orphan_changes.append(ch_copy)

    return {
        "repo_name": repo_name,
        "repo_path": repo_path_str,
        "default_branch": default_branch,
        "forge": forge_type,
        "forge_connected": forge_connected,
        "mr_label": mr_label,
        "mr_prefix": mr_prefix,
        "issues": rows,
        "local_only_items": local_only_items,
        "orphan_changes": orphan_changes,
        "tasks": local_entries,
        "retained_idle_worktrees": retained_idle_worktrees,
        "warnings": warnings,
        "forge_fetched_at": forge_info["fetched_at"],
        "generated_at": time.time(),
    }


def _compute_global_summary(
    repos: list[dict[str, Any]],
    all_issues: list[dict[str, Any]],
    all_local: list[dict[str, Any]],
    all_orphans: list[dict[str, Any]],
) -> dict[str, int]:
    active_worktrees: list[dict[str, Any]] = []
    seen_wts: set[str] = set()

    for entry in [*all_issues, *all_local]:
        wt = entry.get("worktree") or ""
        if wt and wt not in seen_wts:
            seen_wts.add(wt)
            active_worktrees.append(entry)

    coding_now = 0
    dirty_wt = 0
    stalled_wt = 0
    in_prog_tasks = 0

    for entry in active_worktrees:
        pulse = entry.get("pulse") or {}
        state = pulse.get("activity_state", "")
        if state == "active":
            coding_now += 1
        elif state == "stalled":
            stalled_wt += 1
        if (pulse.get("dirty_count") or 0) > 0:
            dirty_wt += 1
        counts = entry.get("counts") or {}
        in_prog_tasks += int(counts.get("in_progress") or 0)

    ci_failed = 0
    ready_to_land = 0
    open_changes = len(all_orphans)
    for row in all_issues:
        stage = row.get("stage", "")
        if row.get("change"):
            open_changes += 1
        if stage == "🛠️ 修 CI":
            ci_failed += 1
        elif stage == "🔵 待合入":
            ready_to_land += 1

    for ch in all_orphans:
        if (ch.get("checks_overall") or "") == "FAIL":
            ci_failed += 1

    return {
        "repo_count": len(repos),
        "active_worktrees": len(active_worktrees),
        "coding_now_count": coding_now,
        "in_progress_tasks": in_prog_tasks,
        "dirty_worktrees": dirty_wt,
        "stalled_worktrees": stalled_wt,
        "open_issues": len(all_issues),
        "open_changes": open_changes,
        "ci_failed_count": ci_failed,
        "ready_to_land_count": ready_to_land,
    }


def collect_global_snapshot(
    *,
    current_cwd: Path | None = None,
    open_only: bool = False,
    local_only: bool = False,
    forge_cache: ForgeSnapshotCache | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Aggregate live status snapshots across all registered repositories on this machine."""
    if current_cwd is not None:
        cur_main = resolve_main_worktree_ro(current_cwd)
        if cur_main is not None:
            register_repo(cur_main)

    registered = load_registered_repos(prune_missing=True)
    cache = forge_cache if forge_cache is not None else ForgeSnapshotCache(ttl_seconds=0.0)

    repos_out: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_local: list[dict[str, Any]] = []
    all_orphans: list[dict[str, Any]] = []
    warnings: list[str] = []

    for rec in registered:
        repo_path = Path(rec["path"])
        try:
            snap = collect_repo_snapshot(
                repo_path,
                open_only=open_only,
                local_only=local_only,
                forge_cache=cache,
                force_refresh=force_refresh,
                register=False,
            )
        except Exception as exc:
            warnings.append(f"[{rec['name']}] 扫描失败：{exc}")
            continue

        snap["last_seen_at"] = rec.get("last_seen_at", 0.0)
        repos_out.append(snap)
        all_issues.extend(snap["issues"])
        all_local.extend(snap["local_only_items"])
        all_orphans.extend(snap["orphan_changes"])
        warnings.extend(f"[{snap['repo_name']}] {w}" for w in snap["warnings"])

    summary = _compute_global_summary(repos_out, all_issues, all_local, all_orphans)
    return {
        "global": True,
        "generated_at": time.time(),
        "repos_config_path": str(get_repos_path()),
        "summary": summary,
        "repos": repos_out,
        "issues": all_issues,
        "local_only_items": all_local,
        "orphan_changes": all_orphans,
        "warnings": warnings,
    }


def collect_scope_snapshot(
    *,
    root: Path | None = None,
    global_mode: bool = True,
    open_only: bool = False,
    local_only: bool = False,
    forge_cache: ForgeSnapshotCache | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Unified snapshot entrypoint for `watch` and `board`: wraps global or single-repo view."""
    if not global_mode and root is not None:
        snap = collect_repo_snapshot(
            root,
            open_only=open_only,
            local_only=local_only,
            forge_cache=forge_cache,
            force_refresh=force_refresh,
            register=True,
        )
        summary = _compute_global_summary(
            [snap],
            snap["issues"],
            snap["local_only_items"],
            snap["orphan_changes"],
        )
        return {
            "global": False,
            "generated_at": snap["generated_at"],
            "repos_config_path": str(get_repos_path()),
            "summary": summary,
            "repos": [snap],
            "issues": snap["issues"],
            "local_only_items": snap["local_only_items"],
            "orphan_changes": snap["orphan_changes"],
            "warnings": [f"[{snap['repo_name']}] {w}" for w in snap["warnings"]],
        }
    return collect_global_snapshot(
        current_cwd=root or Path.cwd(),
        open_only=open_only,
        local_only=local_only,
        forge_cache=forge_cache,
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# Terminal Watch Renderer & Loop (`idd watch`)
# ---------------------------------------------------------------------------


def _ansi(code: str, text: str, use_color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if use_color else text


def render_watch_frame(
    snapshot: dict[str, Any],
    *,
    use_color: bool,
    interval: float,
    forge_ttl: float,
    local_only: bool = False,
) -> str:
    """Render one crisp terminal frame for `idd watch`."""
    now_str = time.strftime("%H:%M:%S", time.localtime(snapshot.get("generated_at") or time.time()))
    scope_label = "全局仓库" if snapshot.get("global") else "当前仓库"
    remote_hint = "纯本地" if local_only else f"远端缓存 {int(forge_ttl)}s"
    s = snapshot.get("summary") or {}

    header = (
        f"IDD 实时监控（{scope_label}） · {now_str} · "
        f"本地脉搏 {interval:.0f}s · {remote_hint} · 按 Ctrl+C 退出"
    )
    lines = [_ansi("1;36", header, use_color)]
    kpi = (
        f"仓库 {s.get('repo_count', 0)} | "
        f"活跃 Worktree {s.get('active_worktrees', 0)} (刚刚活跃 {s.get('coding_now_count', 0)}) | "
        f"进行中 TASK {s.get('in_progress_tasks', 0)} | "
        f"待合入 {s.get('ready_to_land_count', 0)} | "
        f"异常/卡住 {s.get('ci_failed_count', 0) + s.get('stalled_worktrees', 0)}"
    )
    lines.append(_ansi("1", kpi, use_color))

    repos = snapshot.get("repos") or []
    if not repos:
        lines.extend([
            "",
            "暂无已注册仓库。可在任意 Git 项目目录运行 `idd start <issue#>`、`idd status` 或 `idd repos add .` 自动纳入全局监控。",
        ])
        return "\n".join(lines)

    for repo in repos:
        forge_tag = {"github": "GitHub", "gitlab": "GitLab", "local": "Local"}.get(repo.get("forge", "local"), "Local")
        wt_rows = [r for r in repo.get("issues", []) if r.get("worktree")]
        backlog_rows = [r for r in repo.get("issues", []) if not r.get("worktree")]
        local_items = repo.get("local_only_items") or []
        orphans = repo.get("orphan_changes") or []
        retained = repo.get("retained_idle_worktrees") or []

        lines.append("")
        repo_hdr = f"📦 {repo['repo_name']} [{forge_tag}] — {repo['repo_path']}"
        lines.append(_ansi("1;34", repo_hdr, use_color))

        if not wt_rows and not local_items and not orphans:
            backlog_note = f"（Open Backlog: {len(backlog_rows)} 个未认领）" if backlog_rows else "（暂无进行中工作树）"
            lines.append(f"  {backlog_note}")

        for row in wt_rows:
            pulse = row.get("pulse") or {}
            pulse_str = pulse.get("pulse_summary") or "—"
            branch = row.get("branch") or "—"
            cur = row.get("current_task")
            cur_part = f" | ▶ {cur}" if cur else ""
            change_part = f" | {row['change_summary']}" if row.get("change") else ""
            lines.append(
                f"  #{row['issue_number']} {row['title']}  [{row['stage']}]  TASK {row['task_progress']}{change_part}"
            )
            lines.append(f"     分支 `{branch}` | {pulse_str}{cur_part}")
            if pulse.get("last_commit_sha"):
                subj = pulse.get("last_commit_subject", "")[:60]
                lines.append(f"     最近提交 {pulse['last_commit_sha']}: {subj}")

        for item in local_items:
            pulse = item.get("pulse") or {}
            pulse_str = pulse.get("pulse_summary") or "—"
            branch = item.get("branch") or "—"
            cur = item.get("current_task")
            cur_part = f" | ▶ {cur}" if cur else ""
            lines.append(
                f"  [本地] {item['issue']}  分支 `{branch}`  TASK {item['done']} / {item['total']}"
            )
            lines.append(f"     {pulse_str}{cur_part}")

        if orphans:
            for ch in orphans:
                lines.append(
                    f"  [{ch.get('mr_label', 'PR')}] {ch.get('mr_prefix', '#')}{ch.get('number')} "
                    f"`{ch.get('headRefName', '')}` {ch.get('title', '')} — {ch.get('change_summary', '')}"
                )

        if backlog_rows:
            preview = ", ".join(f"#{r['issue_number']} {r['title']}" for r in backlog_rows[:4])
            extra = f" 等共 {len(backlog_rows)} 个" if len(backlog_rows) > 4 else ""
            lines.append(f"  待认领 Issue ({len(backlog_rows)}): {preview}{extra}")
        if retained:
            lines.append(f"  已合入保留的工作树: {len(retained)} 个（工作区干净）")

    warnings = snapshot.get("warnings") or []
    if warnings:
        lines.extend(["", _ansi("33", "提示 / 告警：", use_color)])
        lines.extend(f"- {w}" for w in warnings[:6])

    return "\n".join(lines)


def run_watch_loop(
    *,
    root: Path | None = None,
    global_mode: bool = True,
    interval: float = 2.0,
    forge_ttl: float = 30.0,
    local_only: bool = False,
    open_only: bool = False,
    once: bool = False,
) -> int:
    """Run terminal live dashboard (`idd watch`), refreshing cleanly every `interval` seconds."""
    cache = ForgeSnapshotCache(ttl_seconds=forge_ttl)
    is_tty = sys.stdout.isatty() and not once

    if once:
        snap = collect_scope_snapshot(
            root=root,
            global_mode=global_mode,
            open_only=open_only,
            local_only=local_only,
            forge_cache=cache,
            force_refresh=True,
        )
        print(render_watch_frame(snap, use_color=sys.stdout.isatty(), interval=interval, forge_ttl=forge_ttl, local_only=local_only))
        return 0

    sleep_interval = max(0.5, float(interval))
    if is_tty:
        sys.stdout.write("\x1b[?25l")
        sys.stdout.flush()
    try:
        while True:
            snap = collect_scope_snapshot(
                root=root,
                global_mode=global_mode,
                open_only=open_only,
                local_only=local_only,
                forge_cache=cache,
                force_refresh=False,
            )
            frame = render_watch_frame(
                snap,
                use_color=is_tty,
                interval=sleep_interval,
                forge_ttl=forge_ttl,
                local_only=local_only,
            )
            if is_tty:
                sys.stdout.write("\x1b[2J\x1b[H" + frame + "\n")
                sys.stdout.flush()
            else:
                print(frame, flush=True)
                print("-" * 60, flush=True)
            time.sleep(sleep_interval)
    except KeyboardInterrupt:
        return 0
    finally:
        if is_tty:
            sys.stdout.write("\x1b[?25h\n")
            sys.stdout.flush()
