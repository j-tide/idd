#!/usr/bin/env python3
"""Global repository registry, non-locking worktree live pulse, snapshot aggregator, and terminal monitor."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from forge import (
    ForgeAuthError,
    ForgeError,
    build_issue_web_url,
    build_repo_web_url,
    evaluate_repo_init_settings,
    get_config_dir,
    get_forge,
    get_hosts_path,
    inspect_remote_origin,
    load_hosts_config,
)
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
            entry_out: dict[str, Any] = {
                "path": key,
                "name": str(item.get("name") or resolved.name),
                "last_seen_at": ts,
            }
            _copy_repo_init_fields(item, entry_out)
            seen[key] = entry_out

        entries = sorted(seen.values(), key=lambda r: (-float(r.get("last_seen_at") or 0.0), r["name"]))
        if dirty:
            _save_repos_unlocked(entries)
        return entries


def register_repo(main_worktree: Path) -> dict[str, Any]:
    """Register or touch a repository main worktree in `repos.json`."""
    resolved = main_worktree.expanduser().resolve()
    key = str(resolved)
    now = time.time()
    entry: dict[str, Any] = {"path": key, "name": resolved.name, "last_seen_at": now}

    with _REPOS_LOCK:
        raw_items = _read_raw_repos_unlocked()
        by_path: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            try:
                p = Path(item["path"]).expanduser().resolve()
            except OSError:
                continue
            if p.is_dir() and (p / ".git").exists():
                rec: dict[str, Any] = {
                    "path": str(p),
                    "name": str(item.get("name") or p.name),
                    "last_seen_at": float(item.get("last_seen_at") or 0.0),
                }
                _copy_repo_init_fields(item, rec)
                by_path[str(p)] = rec
        prev_entry = by_path.get(key)
        if prev_entry:
            _copy_repo_init_fields(prev_entry, entry)
        by_path[key] = entry
        entries = sorted(by_path.values(), key=lambda r: (-float(r.get("last_seen_at") or 0.0), r["name"]))
        _save_repos_unlocked(entries)
    return entry


def get_repo_init_meta(main_worktree: Path) -> dict[str, Any]:
    """Return persisted repo merge-policy status `{'state', 'mismatches', 'error'}`."""
    key = str(main_worktree.expanduser().resolve())
    with _REPOS_LOCK:
        for item in _read_raw_repos_unlocked():
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
        raw_items = _read_raw_repos_unlocked()
        by_path: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            try:
                p = Path(item["path"]).expanduser().resolve()
            except OSError:
                continue
            if p.is_dir() and (p / ".git").exists():
                rec: dict[str, Any] = {
                    "path": str(p),
                    "name": str(item.get("name") or p.name),
                    "last_seen_at": float(item.get("last_seen_at") or 0.0),
                }
                _copy_repo_init_fields(item, rec)
                by_path[str(p)] = rec
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
        entries = sorted(by_path.values(), key=lambda r: (-float(r.get("last_seen_at") or 0.0), r["name"]))
        _save_repos_unlocked(entries)


def get_repo_init_state(main_worktree: Path) -> str:
    """Return persisted `repo_init_state` ('aligned', 'pending', or '') for a repository."""
    return str(get_repo_init_meta(main_worktree)["state"])


def set_repo_init_state(main_worktree: Path, state: str) -> None:
    """Persist `repo_init_state` for a repository main worktree in `repos.json`."""
    set_repo_init_meta(main_worktree, state)


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


_GH_CLI_CACHE: dict[str, Any] = {"checked_at": 0.0, "logged_in": False}


def _check_gh_cli_logged_in(ttl: float = 30.0) -> bool:
    now = time.time()
    if (now - float(_GH_CLI_CACHE.get("checked_at") or 0.0)) < ttl:
        return bool(_GH_CLI_CACHE.get("logged_in"))
    if not shutil.which("gh"):
        _GH_CLI_CACHE["checked_at"] = now
        _GH_CLI_CACHE["logged_in"] = False
        return False
    try:
        proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=4.0)
        ok = proc.returncode == 0
    except _IGNORED_GIT_ERROR:
        ok = False
    _GH_CLI_CACHE["checked_at"] = now
    _GH_CLI_CACHE["logged_in"] = ok
    return ok


def _mask_token(tok: str) -> str:
    cleaned = tok.strip()
    if not cleaned:
        return ""
    if len(cleaned) > 10:
        return f"{cleaned[:6]}...{cleaned[-2:]}"
    return "****"


def collect_auth_hosts_status(*, root: Path | None = None, global_mode: bool = True) -> dict[str, Any]:
    """Return all detected GitHub/GitLab hosts, their bound repos, and live credential status."""
    saved_hosts = load_hosts_config()
    repo_paths: list[Path] = []
    if not global_mode and root is not None:
        m = resolve_main_worktree_ro(root)
        if m is not None:
            repo_paths.append(m)
    else:
        if root is not None:
            m = resolve_main_worktree_ro(root)
            if m is not None:
                register_repo(m)
        repo_paths = [Path(rec["path"]) for rec in load_registered_repos(prune_missing=True)]

    hosts_map: dict[str, dict[str, Any]] = {}

    for repo_path in repo_paths:
        spec, forge_type = inspect_remote_origin(repo_path)
        if spec is None or forge_type not in ("github", "gitlab"):
            continue
        host_key = spec.host
        saved = saved_hosts.get(spec.host) or saved_hosts.get(spec.hostname)
        matched_saved_key = spec.host if spec.host in saved_hosts else (spec.hostname if spec.hostname in saved_hosts else "")
        api_base = (saved.get("api_url") if saved and saved.get("api_url") else spec.api_base).rstrip("/")
        repo_url = build_repo_web_url(spec, forge_type)

        bucket = hosts_map.get(host_key)
        if bucket is None:
            bucket = {
                "host": host_key,
                "saved_key": matched_saved_key,
                "api_base": api_base,
                "forge": forge_type,
                "repos": [],
                "saved_entry": saved,
            }
            hosts_map[host_key] = bucket
        if not any(r["name"] == repo_path.name and r["url"] == repo_url for r in bucket["repos"]):
            bucket["repos"].append({"name": repo_path.name, "url": repo_url, "path": str(repo_path)})

    for saved_key, entry in sorted(saved_hosts.items()):
        if saved_key in hosts_map or any(b.get("saved_key") == saved_key for b in hosts_map.values()):
            continue
        fg = str(entry.get("forge") or ("github" if "github.com" in saved_key else "gitlab"))
        api_base = str(entry.get("api_url") or f"https://{saved_key}").rstrip("/")
        hosts_map[saved_key] = {
            "host": saved_key,
            "saved_key": saved_key,
            "api_base": api_base,
            "forge": fg,
            "repos": [],
            "saved_entry": entry,
        }

    has_gitlab_env = bool(os.environ.get("GITLAB_TOKEN", "").strip() or os.environ.get("GITLAB_PRIVATE_TOKEN", "").strip())
    has_github_env = bool(os.environ.get("GH_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip())
    has_glab_cli = bool(shutil.which("glab"))
    gh_logged_in: bool | None = None

    items: list[dict[str, Any]] = []
    for bucket in hosts_map.values():
        fg = bucket["forge"]
        api_base = bucket["api_base"]
        host_key = bucket["host"]
        saved = bucket["saved_entry"] or {}
        saved_tok = str(saved.get("token") or "").strip()
        username = str(saved.get("username") or "").strip()
        configured = False
        auth_source = "missing"

        if saved_tok:
            configured = True
            auth_source = "hosts.json"
        elif fg == "gitlab":
            if has_gitlab_env:
                configured = True
                auth_source = "env"
            elif has_glab_cli:
                configured = False
                auth_source = "missing"
        elif fg == "github":
            if has_github_env:
                configured = True
                auth_source = "env"
            else:
                if gh_logged_in is None:
                    gh_logged_in = _check_gh_cli_logged_in()
                if gh_logged_in and (host_key == "github.com" or host_key.endswith(".github.com")):
                    configured = True
                    auth_source = "gh_cli"

        if fg == "gitlab":
            token_url = (
                f"{api_base}/-/user_settings/personal_access_tokens?name=IDD+Board&scopes=api"
                if api_base
                else ""
            )
        else:
            token_url = (
                "https://github.com/settings/tokens/new?description=IDD+Board&scopes=repo"
                if host_key == "github.com"
                else (f"{api_base}/settings/tokens/new?description=IDD+Board&scopes=repo" if api_base else "")
            )

        items.append(
            {
                "host": host_key,
                "api_base": api_base,
                "forge": fg,
                "repos": bucket["repos"],
                "configured": configured,
                "auth_source": auth_source,
                "masked_token": _mask_token(saved_tok),
                "username": username,
                "token_url": token_url,
                "can_remove": bool(bucket.get("saved_key")),
            }
        )

    items.sort(key=lambda h: (1 if h["configured"] else 0, 0 if h["forge"] == "gitlab" else 1, h["host"]))
    return {
        "hosts": items,
        "hosts_config_path": str(get_hosts_path()),
        "unconfigured_count": sum(1 for h in items if not h["configured"]),
    }


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
    *,
    remote_state: str = "",
    unpushed_commits: int = 0,
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

    if remote_state == "unpushed_branch":
        parts.append("⚠️ 未推远端")
    elif unpushed_commits > 0:
        parts.append(f"↑{unpushed_commits}待推送")
    return " · ".join(parts)


def _inspect_remote_sync_ro(
    wt_path: Path,
    *,
    branch: str = "",
    has_origin: bool | None = None,
    default_branch: str = "main",
) -> dict[str, Any]:
    """Inspect local-only remote-tracking & unpushed commit status without network calls."""
    result: dict[str, Any] = {
        "remote_state": "local_only",
        "remote_branch_exists": False,
        "unpushed_commits": 0,
        "behind_commits": 0,
        "upstream": "",
        "upstream_misbound": False,
    }
    if not wt_path.is_dir():
        return result

    if has_origin is None:
        rem = _run_git_ro(wt_path, ["remote"])
        remotes = {line.strip() for line in rem.stdout.splitlines() if line.strip()} if rem and rem.returncode == 0 else set()
        has_origin = "origin" in remotes
    if not has_origin:
        return result

    if not branch:
        br_proc = _run_git_ro(wt_path, ["branch", "--show-current"])
        branch = br_proc.stdout.strip() if br_proc and br_proc.returncode == 0 else ""
    if not branch or branch == "(detached)":
        return result

    up_proc = _run_git_ro(wt_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    upstream = up_proc.stdout.strip() if up_proc and up_proc.returncode == 0 else ""
    result["upstream"] = upstream
    if branch != default_branch and upstream == f"origin/{default_branch}":
        result["upstream_misbound"] = True

    rem_ref_proc = _run_git_ro(wt_path, ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"])
    if rem_ref_proc and rem_ref_proc.returncode == 0:
        result["remote_branch_exists"] = True
        lr_proc = _run_git_ro(wt_path, ["rev-list", "--left-right", "--count", f"refs/remotes/origin/{branch}...HEAD"])
        if lr_proc and lr_proc.returncode == 0 and lr_proc.stdout.strip():
            counts = lr_proc.stdout.strip().split()
            if len(counts) == 2 and counts[0].isdigit() and counts[1].isdigit():
                result["behind_commits"] = int(counts[0])
                result["unpushed_commits"] = int(counts[1])
        result["remote_state"] = "ahead" if result["unpushed_commits"] > 0 else "synced"
    else:
        result["remote_branch_exists"] = False
        result["remote_state"] = "unpushed_branch"
        base_ref_proc = _run_git_ro(wt_path, ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{default_branch}"])
        if base_ref_proc and base_ref_proc.returncode == 0:
            ahead_proc = _run_git_ro(wt_path, ["rev-list", "--count", f"refs/remotes/origin/{default_branch}..HEAD"])
            if ahead_proc and ahead_proc.returncode == 0 and ahead_proc.stdout.strip().isdigit():
                result["unpushed_commits"] = int(ahead_proc.stdout.strip())

    return result


def inspect_worktree_pulse(
    wt_path: Path,
    *,
    in_progress_count: int = 0,
    branch: str = "",
    has_origin: bool | None = None,
    default_branch: str = "main",
) -> dict[str, Any]:
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
            for md in task_dir.glob("*/TASK-*.md"):
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
    remote_sync = _inspect_remote_sync_ro(
        wt_path,
        branch=branch,
        has_origin=has_origin,
        default_branch=default_branch,
    )
    pulse_summary = _format_pulse_summary(
        activity_state,
        last_active_ago,
        dirty_count,
        insertions,
        deletions,
        git_op,
        remote_state=remote_sync["remote_state"],
        unpushed_commits=remote_sync["unpushed_commits"],
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
        "remote_state": remote_sync["remote_state"],
        "remote_branch_exists": remote_sync["remote_branch_exists"],
        "unpushed_commits": remote_sync["unpushed_commits"],
        "behind_commits": remote_sync["behind_commits"],
        "upstream": remote_sync["upstream"],
        "upstream_misbound": remote_sync["upstream_misbound"],
        "pulse_summary": pulse_summary,
    }


# ---------------------------------------------------------------------------
# Thread-Safe Remote Forge Snapshot Cache
# ---------------------------------------------------------------------------


class ForgeSnapshotCache:
    """Thread-safe Stale-While-Revalidate TTL cache for GitHub/GitLab open issues & PRs/MRs."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._inflight: set[str] = set()
        self._epoch: int = 0

    def invalidate_all(self) -> None:
        """Drop all cached forge entries and advance epoch so stale in-flight fetches cannot overwrite."""
        with self._lock:
            self._epoch += 1
            self._entries.clear()
            self._inflight.clear()

    def refresh_now(self, repo_paths: list[Path], *, timeout: float = 2.0) -> None:
        """Invalidate cache, kick off parallel refreshes, and wait up to `timeout` seconds."""
        self.invalidate_all()
        self.warm_async(repo_paths, force_refresh=True)
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if not self.is_syncing():
                break
            time.sleep(0.03)

    @staticmethod
    def _build_local_placeholder(main_worktree: Path, *, has_origin: bool, syncing: bool) -> dict[str, Any]:
        if not has_origin:
            return {
                "forge_type": "local",
                "mr_label": "PR/MR",
                "mr_prefix": "#",
                "forge_connected": False,
                "open_issues": [],
                "open_changes": [],
                "warnings": [],
                "auth_alert": None,
                "fetched_at": 0.0,
                "syncing": False,
            }
        _, inferred = inspect_remote_origin(main_worktree)
        mr_label = "MR" if inferred == "gitlab" else ("PR" if inferred == "github" else "PR/MR")
        mr_prefix = "!" if inferred == "gitlab" else "#"
        return {
            "forge_type": inferred,
            "mr_label": mr_label,
            "mr_prefix": mr_prefix,
            "forge_connected": False,
            "open_issues": [],
            "open_changes": [],
            "warnings": [],
            "auth_alert": None,
            "fetched_at": 0.0,
            "syncing": syncing,
        }

    def _query_and_store(self, main_worktree: Path, key: str, *, epoch: int | None = None) -> dict[str, Any]:
        with self._lock:
            start_epoch = self._epoch if epoch is None else epoch
        forge = get_forge(main_worktree)
        forge_type = forge.forge_type
        mr_label = forge.mr_label
        mr_prefix = forge.mr_prefix
        open_issues: list[dict[str, Any]] = []
        open_changes: list[dict[str, Any]] = []
        forge_connected = False
        warnings: list[str] = []
        auth_alert: dict[str, Any] | None = None

        try:
            issues_res = forge.list_open_issues(limit=100)
            changes_res = forge.list_changes(state="open", limit=100)
            if isinstance(issues_res, list) and isinstance(changes_res, list):
                open_issues = issues_res
                open_changes = changes_res
                forge_connected = True
                prev_meta = get_repo_init_meta(main_worktree)
                if prev_meta["state"] != "aligned":
                    try:
                        policy_res = forge.repo_init(apply=False)
                        aligned, mismatches = evaluate_repo_init_settings(policy_res)
                        if aligned:
                            set_repo_init_meta(main_worktree, "aligned")
                        else:
                            set_repo_init_meta(
                                main_worktree,
                                "pending",
                                mismatches=mismatches,
                                error=str(prev_meta.get("error") or ""),
                            )
                    except Exception:
                        pass
            else:
                warnings.append("远端仓库查询不可用，已降级为本地工作树视图。")
        except ForgeAuthError as exc:
            auth_alert = {
                "host": exc.host,
                "api_base": exc.api_base,
                "forge": exc.forge_type,
                "login_cmd": exc.login_cmd,
                "token_url": exc.token_url,
            }
            warnings.append(f"{exc}（已降级为本地工作树视图）")
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
            "auth_alert": auth_alert,
            "fetched_at": time.time(),
            "syncing": False,
        }
        if self.ttl_seconds > 0:
            with self._lock:
                if self._epoch == start_epoch:
                    self._entries[key] = entry
        return dict(entry)

    def _refresh_in_background(self, main_worktree: Path, key: str, epoch: int) -> None:
        try:
            self._query_and_store(main_worktree, key, epoch=epoch)
        except Exception:
            pass
        finally:
            with self._lock:
                if self._epoch == epoch:
                    self._inflight.discard(key)

    def _schedule_refresh(self, main_worktree: Path, key: str) -> None:
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
            epoch = self._epoch
        threading.Thread(
            target=self._refresh_in_background,
            args=(main_worktree, key, epoch),
            daemon=True,
        ).start()

    def is_syncing(self) -> bool:
        with self._lock:
            return bool(self._inflight)

    def warm_async(self, repo_paths: list[Path], *, force_refresh: bool = False) -> None:
        """Start parallel non-blocking background forge refreshes for valid origin repos."""
        now = time.time()
        for raw_path in repo_paths:
            main_wt = resolve_main_worktree_ro(raw_path)
            if main_wt is None:
                continue
            has_origin, _ = _detect_repo_meta_ro(main_wt)
            if not has_origin:
                continue
            key = str(main_wt.resolve())
            with self._lock:
                cached = self._entries.get(key)
                fresh = (
                    cached is not None
                    and not force_refresh
                    and self.ttl_seconds > 0
                    and (now - cached["fetched_at"]) < self.ttl_seconds
                )
            if not fresh:
                self._schedule_refresh(main_wt, key)

    def get(
        self,
        main_worktree: Path,
        *,
        has_origin: bool,
        force_refresh: bool = False,
        allow_stale_async: bool = False,
    ) -> dict[str, Any]:
        """Return cached or freshly queried forge snapshot for `main_worktree`."""
        if not has_origin:
            return self._build_local_placeholder(main_worktree, has_origin=False, syncing=False)

        key = str(main_worktree.resolve())
        now = time.time()
        with self._lock:
            cached = self._entries.get(key)
            inflight = key in self._inflight
            if (
                cached is not None
                and not force_refresh
                and self.ttl_seconds > 0
                and (now - cached["fetched_at"]) < self.ttl_seconds
            ):
                res = dict(cached)
                res["syncing"] = inflight
                return res

        if allow_stale_async:
            self._schedule_refresh(main_worktree, key)
            if cached is not None:
                res = dict(cached)
                res["syncing"] = True
                return res
            return self._build_local_placeholder(main_worktree, has_origin=True, syncing=True)

        return self._query_and_store(main_worktree, key)


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
    repo_url: str,
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
        "repo_url": repo_url,
        "forge_type": forge_type,
        "forge_connected": forge_connected,
        "issue_dir": item.get("issue", "") if item else "",
        "counts": item.get("counts", {s: 0 for s in task_status.STATUSES}) if item else {s: 0 for s in task_status.STATUSES},
        "tasks": item.get("tasks", []) if item else [],
        "current_task": item.get("current_task", "") if item else "",
        "current_task_status": item.get("current_task_status", "") if item else "",
        "pulse": item.get("pulse") if item else None,
    }


def _extract_task_dirs_from_paths(lines: list[str], *, strip_porcelain: bool) -> set[str]:
    dirs: set[str] = set()
    for raw in lines:
        if not raw.strip():
            continue
        path_str = raw[3:].strip() if strip_porcelain and len(raw) >= 4 else raw.strip()
        if strip_porcelain and " -> " in path_str:
            path_str = path_str.split(" -> ", 1)[1].strip()
        path_str = path_str.strip('"')
        parts = Path(path_str).parts
        if len(parts) >= 2 and parts[0] == "TASK":
            dirs.add(parts[1])
    return dirs


def _get_worktree_dirty_task_dirs(wt_path: Path) -> set[str]:
    st_proc = _run_git_ro(wt_path, ["status", "--porcelain=v1", "--", "TASK"])
    if st_proc and st_proc.returncode == 0 and st_proc.stdout.strip():
        return _extract_task_dirs_from_paths(st_proc.stdout.splitlines(), strip_porcelain=True)
    return set()


def _get_worktree_base_task_dirs(wt_path: Path, default_branch: str) -> set[str]:
    """List TASK/<dir> entries present at merge-base(default_branch, HEAD) so older branches ignore cleaned legacy dirs."""
    for base_ref in (default_branch, f"origin/{default_branch}"):
        mb_proc = _run_git_ro(wt_path, ["merge-base", base_ref, "HEAD"])
        if mb_proc and mb_proc.returncode == 0 and mb_proc.stdout.strip():
            mb_sha = mb_proc.stdout.strip()
            tree_proc = _run_git_ro(wt_path, ["ls-tree", "-d", "--name-only", f"{mb_sha}:TASK"])
            if tree_proc and tree_proc.returncode == 0 and tree_proc.stdout.strip():
                return {line.strip() for line in tree_proc.stdout.splitlines() if line.strip()}
            return set()
    return set()


def _get_worktree_touched_task_dirs(
    wt_path: Path,
    default_branch: str,
    *,
    is_main: bool,
    dirty_dirs: set[str] | None = None,
) -> set[str]:
    touched: set[str] = set(dirty_dirs) if dirty_dirs is not None else _get_worktree_dirty_task_dirs(wt_path)
    if not is_main:
        for base_ref in (default_branch, f"origin/{default_branch}"):
            diff_proc = _run_git_ro(wt_path, ["diff", "--name-only", f"{base_ref}...HEAD", "--", "TASK"])
            if diff_proc and diff_proc.returncode == 0:
                touched |= _extract_task_dirs_from_paths(diff_proc.stdout.splitlines(), strip_porcelain=False)
                break
    return touched


def _collect_all_worktrees_ro(
    main_worktree: Path,
    issue_filter: str | None,
    open_only: bool,
    *,
    default_branch: str = "main",
    all_worktrees: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    worktrees = all_worktrees if all_worktrees is not None else list_git_worktrees_ro(main_worktree)
    main_resolved = main_worktree.resolve()
    main_task_root = main_resolved / "TASK"
    main_task_dirs: set[str] = set()
    if main_task_root.is_dir():
        try:
            main_task_dirs = {p.name for p in main_task_root.iterdir() if p.is_dir()}
        except OSError:
            main_task_dirs = set()

    def scan_one(wt: dict[str, str]) -> tuple[list[dict[str, Any]], list[str], bool, str]:
        wt_path = Path(wt["path"]).resolve()
        task_root = wt_path / "TASK"
        if not task_root.is_dir():
            return [], [], False, ""
        branch = wt.get("branch", "")
        is_main = wt_path == main_resolved
        entries, warnings, matched = task_status._collect_from_task_root(  # noqa: SLF001
            task_root,
            issue_filter,
            open_only,
            worktree=wt_path,
            branch=branch,
        )
        if issue_filter is not None or not entries:
            return entries, warnings, matched, ""

        suppressed_wt = ""
        dirty_task_dirs = _get_worktree_dirty_task_dirs(wt_path)
        touched_dirs = _get_worktree_touched_task_dirs(
            wt_path,
            default_branch,
            is_main=is_main,
            dirty_dirs=dirty_task_dirs,
        )
        base_task_dirs = _get_worktree_base_task_dirs(wt_path, default_branch) if not is_main else set()
        inherited_dirs = main_task_dirs | base_task_dirs
        if is_main:
            kept = [
                e for e in entries
                if e.get("issue_number") is not None or e["issue"] in touched_dirs
            ]
        elif not inherited_dirs:
            kept = entries
        else:
            wt_inum = _infer_worktree_issue_num(branch, wt_path)
            branch_slug = branch.split("/")[-1] if branch and branch != "(detached)" else ""
            dir_slug = wt_path.name
            kept = []
            saw_done_main_local = False
            for e in entries:
                in_main = e["issue"] in inherited_dirs
                is_done_main_local = (
                    in_main
                    and e.get("issue_number") is None
                    and e["issue"] not in dirty_task_dirs
                    and e.get("total", 0) > 0
                    and e.get("done", 0) == e.get("total", 0)
                )
                if is_done_main_local:
                    saw_done_main_local = True
                    continue
                if (
                    (not in_main)
                    or (e["issue"] in touched_dirs)
                    or (wt_inum is not None and e.get("issue_number") == wt_inum)
                    or (e["issue"] in {branch_slug, dir_slug})
                ):
                    kept.append(e)
            if saw_done_main_local and not kept:
                suppressed_wt = str(wt_path)
        kept_issues = {e["issue"] for e in kept}
        kept_warnings = [w for w in warnings if any(f"TASK/{issue_name}/" in w for issue_name in kept_issues)] if warnings else []
        return kept, kept_warnings, matched, suppressed_wt

    if len(worktrees) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(worktrees))) as pool:
            scan_results = list(pool.map(scan_one, worktrees))
    else:
        scan_results = [scan_one(wt) for wt in worktrees]

    all_entries: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    suppressed_worktrees: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    matched_any = issue_filter is None

    for entries, warnings, matched, sup_wt in scan_results:
        if matched:
            matched_any = True
        if sup_wt:
            suppressed_worktrees.add(sup_wt)
        for entry in entries:
            wt_str = entry.get("worktree", "")
            dedup_key = (entry["issue"], str(Path(wt_str).resolve()) if wt_str else "")
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            all_entries.append(entry)
        all_warnings.extend(warnings)

    if issue_filter is not None and not matched_any:
        raise ValueError(f"没有匹配的 Issue 目录：{issue_filter}")

    all_entries.sort(key=lambda item: (item.get("issue_number") or 10**9, item["issue"], item.get("worktree", "")))
    return {"issues": all_entries, "warnings": all_warnings, "suppressed_worktrees": suppressed_worktrees}


def _dedupe_auth_alerts(repo_snaps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge per-repo auth errors by host and build concise non-redundant warnings."""
    grouped: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for snap in repo_snaps:
        repo_name = snap.get("repo_name", "")
        alert = snap.get("auth_alert")
        if isinstance(alert, dict) and (alert.get("api_base") or alert.get("host")):
            key = str(alert.get("api_base") or alert.get("host"))
            bucket = grouped.get(key)
            if bucket is None:
                bucket = {
                    "host": alert.get("host", ""),
                    "api_base": alert.get("api_base", ""),
                    "forge": alert.get("forge", "gitlab"),
                    "repos": [],
                    "login_cmd": alert.get("login_cmd", ""),
                    "token_url": alert.get("token_url", ""),
                }
                grouped[key] = bucket
            if repo_name and repo_name not in bucket["repos"]:
                bucket["repos"].append(repo_name)
            for w in snap.get("warnings") or []:
                if "需要鉴权 Token" not in w and "鉴权失败" not in w:
                    warnings.append(f"[{repo_name}] {w}")
        else:
            for w in snap.get("warnings") or []:
                warnings.append(f"[{repo_name}] {w}")

    auth_alerts = list(grouped.values())
    for alert in auth_alerts:
        repo_list = ", ".join(alert["repos"])
        target = alert.get("api_base") or alert.get("host")
        fg_label = "GitHub" if alert.get("forge") == "github" else "自建 GitLab"
        cmd = alert.get("login_cmd") or f"idd auth login {target} --token <PAT>"
        warnings.append(f"[{repo_list}] 访问 {fg_label} ({target}) 需要鉴权，请执行：`{cmd}`")

    return auth_alerts, warnings


def collect_repo_snapshot(
    root: Path,
    *,
    issue_filter: str | None = None,
    open_only: bool = False,
    local_only: bool = False,
    forge_cache: ForgeSnapshotCache | None = None,
    force_refresh: bool = False,
    allow_stale_async: bool = False,
    register: bool = True,
) -> dict[str, Any]:
    """Collect unified task + worktree pulse + remote PR/MR/Issue snapshot for a repo or TASK/ dir."""
    resolved = root.expanduser().resolve()
    main_wt = resolve_main_worktree_ro(resolved)

    remote_spec = None
    inferred_forge = "local"
    if main_wt is not None:
        if register:
            register_repo(main_wt)
        has_origin, default_branch = _detect_repo_meta_ro(main_wt)
        all_worktrees = list_git_worktrees_ro(main_wt)
        if has_origin:
            remote_spec, inferred_forge = inspect_remote_origin(main_wt)
        wt_data = _collect_all_worktrees_ro(
            main_wt,
            issue_filter,
            open_only,
            default_branch=default_branch,
            all_worktrees=all_worktrees,
        )
        scan_root = main_wt
        repo_name = main_wt.name
        repo_path_str = str(main_wt)
    else:
        task_root = resolved / "TASK"
        if not task_root.is_dir():
            raise ValueError(f"当前路径既不是 Git 仓库，也不存在 TASK/ 目录：{resolved}")
        wt_data = task_status.collect(task_root, issue_filter, open_only)
        has_origin = False
        default_branch = "main"
        all_worktrees = []
        scan_root = resolved
        repo_name = resolved.name
        repo_path_str = str(resolved)

    warnings = list(wt_data.get("warnings", []))
    local_entries: list[dict[str, Any]] = wt_data.get("issues", [])

    forge_info: dict[str, Any] = {
        "forge_type": inferred_forge,
        "mr_label": "MR" if inferred_forge == "gitlab" else ("PR" if inferred_forge == "github" else "PR/MR"),
        "mr_prefix": "!" if inferred_forge == "gitlab" else "#",
        "forge_connected": False,
        "open_issues": [],
        "open_changes": [],
        "warnings": [],
        "auth_alert": None,
        "fetched_at": 0.0,
        "syncing": False,
    }
    if main_wt is not None and not local_only and not issue_filter and has_origin:
        cache = forge_cache if forge_cache is not None else ForgeSnapshotCache(ttl_seconds=0.0)
        forge_info = cache.get(
            scan_root,
            has_origin=has_origin,
            force_refresh=force_refresh,
            allow_stale_async=allow_stale_async,
        )
        warnings.extend(forge_info["warnings"])

    forge_type = forge_info["forge_type"]
    mr_label = forge_info["mr_label"]
    mr_prefix = forge_info["mr_prefix"]
    forge_connected = bool(forge_info["forge_connected"])
    open_issues: list[dict[str, Any]] = forge_info["open_issues"]
    open_changes: list[dict[str, Any]] = forge_info["open_changes"]
    open_issue_numbers = {int(i["number"]) for i in open_issues if i.get("number") is not None}

    in_progress_by_wt: dict[str, int] = {}
    worktrees_with_tasks: set[str] = set()
    for entry in local_entries:
        wt_str = entry.get("worktree", "")
        if wt_str:
            resolved_wt = str(Path(wt_str).resolve())
            worktrees_with_tasks.add(resolved_wt)
            in_progress_by_wt[resolved_wt] = in_progress_by_wt.get(resolved_wt, 0) + int(
                entry["counts"].get("in_progress", 0)
            )

    unique_wts_to_inspect: list[str] = list(worktrees_with_tasks)
    seen_wt_inspect = set(unique_wts_to_inspect)
    extra_worktrees: list[tuple[dict[str, str], Path, str]] = []
    if main_wt is not None and not issue_filter:
        main_resolved_str = str(main_wt.resolve())
        for wt in all_worktrees:
            wt_p = Path(wt["path"]).resolve()
            wt_str = str(wt_p)
            if wt_str == main_resolved_str or wt_str in worktrees_with_tasks or not wt_p.is_dir():
                continue
            extra_worktrees.append((wt, wt_p, wt_str))
            if wt_str not in seen_wt_inspect:
                seen_wt_inspect.add(wt_str)
                unique_wts_to_inspect.append(wt_str)

    branch_by_wt = {
        str(Path(w["path"]).resolve()): w.get("branch", "")
        for w in all_worktrees
        if w.get("path")
    }

    def probe_wt(wt_str: str) -> tuple[str, dict[str, Any]]:
        return wt_str, inspect_worktree_pulse(
            Path(wt_str),
            in_progress_count=in_progress_by_wt.get(wt_str, 0),
            branch=branch_by_wt.get(wt_str, ""),
            has_origin=has_origin,
            default_branch=default_branch,
        )

    pulse_by_wt: dict[str, dict[str, Any]] = {}
    if len(unique_wts_to_inspect) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(unique_wts_to_inspect))) as pool:
            for wt_str, pulse in pool.map(probe_wt, unique_wts_to_inspect):
                pulse_by_wt[wt_str] = pulse
    elif len(unique_wts_to_inspect) == 1:
        wt_str, pulse = probe_wt(unique_wts_to_inspect[0])
        pulse_by_wt[wt_str] = pulse

    for entry in local_entries:
        wt_str = entry.get("worktree", "")
        if wt_str:
            resolved_wt = str(Path(wt_str).resolve())
            entry["pulse"] = dict(pulse_by_wt[resolved_wt])
        else:
            entry["pulse"] = None
        cur_label, cur_status = _pick_current_task(entry.get("tasks", []))
        entry["current_task"] = cur_label
        entry["current_task_status"] = cur_status
        entry["repo_name"] = repo_name
        entry["repo_path"] = repo_path_str

    retained_idle_worktrees: list[dict[str, Any]] = []
    suppressed_wts: set[str] = set(wt_data.get("suppressed_worktrees", []))
    for wt, wt_p, wt_str in extra_worktrees:
        branch = wt.get("branch", "")
        inum = _infer_worktree_issue_num(branch, wt_p)
        pulse = dict(pulse_by_wt[wt_str])
        is_open_issue = inum is not None and inum in open_issue_numbers
        is_dirty = pulse["dirty_count"] > 0
        looks_post_land = pulse.get("last_commit_subject", "").startswith("chore: 清理已汇总的任务记录")
        is_local_active = (not forge_connected) and (not looks_post_land) and (wt_str not in suppressed_wts)

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

    effective_forge = forge_type if forge_type != "local" else inferred_forge
    repo_web_url = build_repo_web_url(remote_spec, effective_forge)

    items_by_issue: dict[int, dict[str, Any]] = {}
    local_only_items: list[dict[str, Any]] = []
    for item in local_entries:
        item["forge_type"] = effective_forge
        item["repo_url"] = repo_web_url
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
        issue_url = issue.get("url") or build_issue_web_url(remote_spec, effective_forge, inum)
        rows.append(
            _build_status_row(
                issue_number=inum,
                title=issue.get("title", ""),
                url=issue_url,
                item=item,
                change=change,
                mr_label=mr_label,
                mr_prefix=mr_prefix,
                repo_name=repo_name,
                repo_path=repo_path_str,
                repo_url=repo_web_url,
                forge_type=effective_forge,
                forge_connected=forge_connected,
            )
        )

    for inum, item in sorted(items_by_issue.items()):
        if inum not in seen_issues:
            change = changes_by_branch.get(item.get("branch", "")) or changes_by_issue.get(inum)
            issue_url = build_issue_web_url(remote_spec, effective_forge, inum)
            rows.append(
                _build_status_row(
                    issue_number=inum,
                    title=item["issue"],
                    url=issue_url,
                    item=item,
                    change=change,
                    mr_label=mr_label,
                    mr_prefix=mr_prefix,
                    repo_name=repo_name,
                    repo_path=repo_path_str,
                    repo_url=repo_web_url,
                    forge_type=effective_forge,
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
            ch_copy["repo_url"] = repo_web_url
            ch_copy["forge_type"] = effective_forge
            ch_copy["mr_label"] = mr_label
            ch_copy["mr_prefix"] = mr_prefix
            ch_copy["change_summary"] = format_change_badge(ch, mr_label, mr_prefix)
            orphan_changes.append(ch_copy)

    repo_init_meta = (
        get_repo_init_meta(main_wt)
        if (main_wt is not None and has_origin)
        else {"state": "local", "mismatches": [], "error": ""}
    )

    return {
        "repo_name": repo_name,
        "repo_path": repo_path_str,
        "repo_url": repo_web_url,
        "default_branch": default_branch,
        "forge": effective_forge,
        "forge_connected": forge_connected,
        "forge_syncing": bool(forge_info.get("syncing")),
        "auth_alert": forge_info.get("auth_alert"),
        "repo_init": repo_init_meta,
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
    issue_unclaimed = 0
    issue_in_progress = 0
    issue_review = 0
    issue_ready = 0

    for row in all_issues:
        stage = row.get("stage", "")
        if row.get("change"):
            open_changes += 1
        if stage == "🛠️ 修 CI":
            ci_failed += 1
            issue_review += 1
        elif stage == "⏳ CI 运行中" or "草稿" in stage:
            issue_review += 1
        elif stage == "🔵 待合入":
            ready_to_land += 1
            issue_ready += 1
        elif row.get("worktree") or stage.startswith("🟢 待提") or stage == "⛔ 受阻":
            issue_in_progress += 1
        else:
            issue_unclaimed += 1

    for ch in all_orphans:
        if (ch.get("checks_overall") or "") == "FAIL":
            ci_failed += 1

    task_done = 0
    task_in_progress = 0
    task_blocked = 0
    task_planned = 0
    task_deferred = 0
    task_cancelled = 0
    task_total = 0
    for entry in [*all_issues, *all_local]:
        c = entry.get("counts") or {}
        done_n = int(c.get("done") or 0)
        prog_n = int(c.get("in_progress") or 0)
        blk_n = int(c.get("blocked") or 0)
        plan_n = int(c.get("planned") or 0)
        def_n = int(c.get("deferred") or 0)
        can_n = int(c.get("cancelled") or 0)
        unk_n = int(c.get("unknown") or 0)
        task_done += done_n
        task_in_progress += prog_n
        task_blocked += blk_n
        task_planned += plan_n
        task_deferred += def_n
        task_cancelled += can_n
        task_total += done_n + prog_n + blk_n + plan_n + def_n + can_n + unk_n

    return {
        "repo_count": len(repos),
        "active_worktrees": len(active_worktrees),
        "coding_now_count": coding_now,
        "in_progress_tasks": in_prog_tasks,
        "dirty_worktrees": dirty_wt,
        "stalled_worktrees": stalled_wt,
        "open_issues": len(all_issues),
        "issue_total": len(all_issues),
        "issue_unclaimed": issue_unclaimed,
        "issue_in_progress": issue_in_progress,
        "issue_review": issue_review,
        "issue_ready": issue_ready,
        "task_total": task_total,
        "task_done": task_done,
        "task_in_progress": task_in_progress,
        "task_blocked": task_blocked,
        "task_planned": task_planned,
        "task_deferred": task_deferred,
        "task_cancelled": task_cancelled,
        "local_only_count": len(all_local),
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
    allow_stale_async: bool = False,
) -> dict[str, Any]:
    """Aggregate live status snapshots across all registered repositories on this machine."""
    if current_cwd is not None:
        cur_main = resolve_main_worktree_ro(current_cwd)
        if cur_main is not None:
            register_repo(cur_main)

    registered = load_registered_repos(prune_missing=True)
    cache = forge_cache if forge_cache is not None else ForgeSnapshotCache(ttl_seconds=0.0)

    def scan_rec(rec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
        repo_path = Path(rec["path"])
        try:
            snap = collect_repo_snapshot(
                repo_path,
                open_only=open_only,
                local_only=local_only,
                forge_cache=cache,
                force_refresh=force_refresh,
                allow_stale_async=allow_stale_async,
                register=False,
            )
            snap["last_seen_at"] = rec.get("last_seen_at", 0.0)
            return rec, snap, None
        except Exception as exc:
            return rec, None, f"[{rec['name']}] 扫描失败：{exc}"

    if len(registered) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(registered))) as pool:
            scanned = list(pool.map(scan_rec, registered))
    else:
        scanned = [scan_rec(rec) for rec in registered]

    repos_out: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_local: list[dict[str, Any]] = []
    all_orphans: list[dict[str, Any]] = []
    extra_warnings: list[str] = []

    for _, snap, err in scanned:
        if err:
            extra_warnings.append(err)
            continue
        assert snap is not None
        repos_out.append(snap)
        all_issues.extend(snap["issues"])
        all_local.extend(snap["local_only_items"])
        all_orphans.extend(snap["orphan_changes"])

    auth_alerts, merged_warnings = _dedupe_auth_alerts(repos_out)
    warnings = [*extra_warnings, *merged_warnings]
    summary = _compute_global_summary(repos_out, all_issues, all_local, all_orphans)
    return {
        "global": True,
        "generated_at": time.time(),
        "repos_config_path": str(get_repos_path()),
        "forge_syncing": any(bool(r.get("forge_syncing")) for r in repos_out),
        "auth_alerts": auth_alerts,
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
    allow_stale_async: bool = False,
) -> dict[str, Any]:
    """Unified snapshot entrypoint for `watch` and `board`: wraps global or single-repo view."""
    if not global_mode and root is not None:
        snap = collect_repo_snapshot(
            root,
            open_only=open_only,
            local_only=local_only,
            forge_cache=forge_cache,
            force_refresh=force_refresh,
            allow_stale_async=allow_stale_async,
            register=True,
        )
        summary = _compute_global_summary(
            [snap],
            snap["issues"],
            snap["local_only_items"],
            snap["orphan_changes"],
        )
        auth_alerts, warnings = _dedupe_auth_alerts([snap])
        return {
            "global": False,
            "generated_at": snap["generated_at"],
            "repos_config_path": str(get_repos_path()),
            "forge_syncing": bool(snap.get("forge_syncing")),
            "auth_alerts": auth_alerts,
            "summary": summary,
            "repos": [snap],
            "issues": snap["issues"],
            "local_only_items": snap["local_only_items"],
            "orphan_changes": snap["orphan_changes"],
            "warnings": warnings,
        }
    return collect_global_snapshot(
        current_cwd=root or Path.cwd(),
        open_only=open_only,
        local_only=local_only,
        forge_cache=forge_cache,
        force_refresh=force_refresh,
        allow_stale_async=allow_stale_async,
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
            backlog_note = f"（待处理 Issue: {len(backlog_rows)} 个）" if backlog_rows else "（暂无进行中工作树）"
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
            lines.append(f"  待处理 Issue ({len(backlog_rows)}): {preview}{extra}")
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
