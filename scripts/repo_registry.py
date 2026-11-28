"""The on-disk registry of monitored Git repositories and their merge-policy metadata."""

from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Any

from git_worktrees import resolve_main_worktree
from local_state import (
    LocalStateError,
    atomic_write_json,
    config_file_lock,
    get_config_dir,
    read_json_file,
)


_REPOS_LOCK = threading.Lock()


def get_repos_path() -> Path:
    """Return path to the global active-repository registry JSON file."""
    return get_config_dir() / "repos.json"


def _save_repos_unlocked(entries: list[dict[str, Any]], *, required: bool = False) -> None:
    try:
        atomic_write_json(get_repos_path(), {"repos": entries})
    except OSError as exc:
        if required:
            raise LocalStateError(f"无法保存仓库索引 {get_repos_path()}：{exc}") from exc


def _read_raw_repos_unlocked(*, required: bool = False) -> list[dict[str, Any]] | None:
    path = get_repos_path()
    try:
        raw = read_json_file(path, [])
        items = raw.get("repos") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            raise ValueError("仓库索引必须包含 repos 列表")
    except (OSError, ValueError) as exc:
        if required:
            raise LocalStateError(f"无法读取仓库索引 {path}：{exc}") from exc
        return None
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"].strip():
            result.append(item)
    return result


def _copy_repo_init_fields(src: dict[str, Any], dst: dict[str, Any]) -> None:
    """Copy persisted `repo_init_*` metadata fields from `src` to `dst` when present."""
    existing_state = src.get("repo_init_state")
    if isinstance(existing_state, str) and existing_state:
        dst["repo_init_state"] = existing_state
    mismatches = src.get("repo_init_mismatches")
    if isinstance(mismatches, list):
        cleaned = [str(m) for m in mismatches if isinstance(m, str) and m]
        if cleaned:
            dst["repo_init_mismatches"] = cleaned
    err = src.get("repo_init_error")
    if isinstance(err, str) and err:
        dst["repo_init_error"] = err


def _recency_key(entry: dict[str, Any]) -> tuple[float, str]:
    return -float(entry.get("last_seen_at") or 0.0), str(entry.get("name", ""))


def load_registered_repos(*, prune_missing: bool = True, required: bool = False) -> list[dict[str, Any]]:
    """Load registered repository entries sorted by recency, optionally pruning stale paths."""
    with _REPOS_LOCK:
        with config_file_lock(get_config_dir() / ".repos.lock"):
            raw_items = _read_raw_repos_unlocked(required=required)
            if raw_items is None:
                return []
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
                entry_out: dict[str, Any] = {
                    "path": key,
                    "name": str(item.get("name") or resolved.name),
                    "last_seen_at": ts,
                }
                _copy_repo_init_fields(item, entry_out)
                seen[key] = entry_out

            entries = sorted(seen.values(), key=_recency_key)
            if dirty:
                _save_repos_unlocked(entries, required=required)
            return entries


def _active_entries(raw_items: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], bool]:
    """Normalize existing repositories before updating a registration or merge-policy record."""
    by_path: dict[str, dict[str, Any]] = {}
    needs_cleanup = False
    for item in raw_items:
        try:
            p = Path(item["path"]).expanduser().resolve()
        except OSError:
            needs_cleanup = True
            continue
        if p.is_dir() and (p / ".git").exists():
            p_str = str(p)
            if p_str != item["path"] or p_str in by_path:
                needs_cleanup = True
            rec: dict[str, Any] = {
                "path": p_str,
                "name": str(item.get("name") or p.name),
                "last_seen_at": float(item.get("last_seen_at") or 0.0),
            }
            _copy_repo_init_fields(item, rec)
            by_path[p_str] = rec
        else:
            needs_cleanup = True
    return by_path, needs_cleanup


def register_repo(main_worktree: Path, *, min_touch_interval: float = 0.0, required: bool = False) -> dict[str, Any]:
    """Register or touch a repository main worktree in `repos.json`."""
    resolved = main_worktree.expanduser().resolve()
    key = str(resolved)
    now = time.time()
    entry: dict[str, Any] = {"path": key, "name": resolved.name, "last_seen_at": now}

    with _REPOS_LOCK:
        with config_file_lock(get_config_dir() / ".repos.lock"):
            raw_items = _read_raw_repos_unlocked(required=required)
            if raw_items is None:
                return entry
            by_path, needs_cleanup = _active_entries(raw_items)
            prev_entry = by_path.get(key)
            if (
                prev_entry is not None
                and not needs_cleanup
                and min_touch_interval > 0.0
                and (now - float(prev_entry.get("last_seen_at") or 0.0)) < min_touch_interval
            ):
                return dict(prev_entry)
            if prev_entry:
                _copy_repo_init_fields(prev_entry, entry)
            by_path[key] = entry
            entries = sorted(by_path.values(), key=_recency_key)
            _save_repos_unlocked(entries, required=required)
    return entry


def get_repo_init_meta(main_worktree: Path) -> dict[str, Any]:
    """Return persisted repo merge-policy status `{'state', 'mismatches', 'error'}`."""
    key = str(main_worktree.expanduser().resolve())
    with _REPOS_LOCK:
        with config_file_lock(get_config_dir() / ".repos.lock"):
            raw_items = _read_raw_repos_unlocked()
        for item in raw_items or ():
            try:
                p = str(Path(item["path"]).expanduser().resolve())
            except OSError:
                continue
            if p == key:
                raw_state = item.get("repo_init_state")
                state = raw_state if isinstance(raw_state, str) else ""
                if state == "prompted":
                    state = "pending"
                raw_mismatches = item.get("repo_init_mismatches")
                mismatches = (
                    [str(m) for m in raw_mismatches if isinstance(m, str) and m]
                    if isinstance(raw_mismatches, list)
                    else []
                )
                raw_err = item.get("repo_init_error")
                error = raw_err if isinstance(raw_err, str) else ""
                return {"state": state, "mismatches": mismatches, "error": error}
    return {"state": "", "mismatches": [], "error": ""}


def set_repo_init_meta(
    main_worktree: Path,
    state: str,
    *,
    mismatches: list[str] | None = None,
    error: str = "",
) -> None:
    """Persist `repo_init_state`, `repo_init_mismatches`, and `repo_init_error` in `repos.json`."""
    resolved = main_worktree.expanduser().resolve()
    key = str(resolved)
    now = time.time()
    normalized = "pending" if state == "prompted" else state
    with _REPOS_LOCK:
        with config_file_lock(get_config_dir() / ".repos.lock"):
            raw_items = _read_raw_repos_unlocked()
            if raw_items is None:
                return
            by_path, _ = _active_entries(raw_items)
            target = by_path.get(key) or {"path": key, "name": resolved.name, "last_seen_at": now}
            if normalized:
                target["repo_init_state"] = normalized
            else:
                target.pop("repo_init_state", None)
            if normalized == "aligned" or not normalized:
                target.pop("repo_init_mismatches", None)
                target.pop("repo_init_error", None)
            else:
                cleaned_mm = [str(m) for m in (mismatches or []) if isinstance(m, str) and m]
                if cleaned_mm:
                    target["repo_init_mismatches"] = cleaned_mm
                else:
                    target.pop("repo_init_mismatches", None)
                if error:
                    target["repo_init_error"] = error
                else:
                    target.pop("repo_init_error", None)
            by_path[key] = target
            entries = sorted(by_path.values(), key=_recency_key)
            _save_repos_unlocked(entries)


def unregister_repo(target: Path) -> bool:
    """Remove a repository (matched by path or containing main worktree) from `repos.json`."""
    resolved = target.expanduser().resolve()
    candidates = {str(resolved)}
    main_wt = resolve_main_worktree(resolved)
    if main_wt is not None:
        candidates.add(str(main_wt))

    with _REPOS_LOCK:
        with config_file_lock(get_config_dir() / ".repos.lock"):
            raw_items = _read_raw_repos_unlocked(required=True) or ()
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
                kept.sort(key=_recency_key)
                _save_repos_unlocked(kept, required=True)
            return removed
