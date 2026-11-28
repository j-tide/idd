#!/usr/bin/env python3
"""Global repository registry, non-locking worktree live pulse, snapshot aggregator, and terminal monitor."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.parse

from forge import (
    ForgeAuthError,
    ForgeError,
    build_issue_web_url,
    build_repo_web_url,
    evaluate_repo_init_settings,
    get_forge,
    inspect_remote_origin,
)
from local_state import (
    get_config_path,
    get_global_auto_merge,
    get_hosts_path,
    load_hosts_config,
)
from repo_registry import (
    get_repo_init_meta,
    get_repos_path,
    load_registered_repos,
    register_repo,
    set_repo_init_meta,
)
from git_worktrees import (
    detect_default_branch,
    has_remote_origin,
    list_worktrees,
    main_worktree_and_inventory,
    read_git,
    resolve_main_worktree,
)
import task_status


_IGNORED_GIT_ERROR = (OSError, subprocess.SubprocessError)
_CACHE_LOCK = threading.Lock()
_PACKED_REFS_CACHE: dict[str, tuple[tuple[int, int, int] | None, dict[str, str]]] = {}
_COMMIT_INFO_CACHE: dict[tuple[str, str], tuple[str, float, str]] = {}
_REPO_META_CACHE: dict[str, tuple[tuple[Any, ...], tuple[bool, str, Any, str]]] = {}
_WORKTREE_PULSE_CACHE: dict[str, dict[str, Any]] = {}
_TASK_GIT_META_CACHE: dict[tuple[str, str, str, str], set[str]] = {}
_IDLE_PULSE_CACHE_TTL = 30.0
_HEX_OID_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


def invalidate_monitor_caches() -> None:
    """Clear in-process git metadata and worktree pulse caches."""
    with _CACHE_LOCK:
        _PACKED_REFS_CACHE.clear()
        _COMMIT_INFO_CACHE.clear()
        _REPO_META_CACHE.clear()
        _WORKTREE_PULSE_CACHE.clear()
        _TASK_GIT_META_CACHE.clear()


def _stat_sig(path: Path) -> tuple[int, int, int] | None:
    """Return lightweight `(mtime_ns, size, ino)` signature for cache invalidation."""
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return None


def _resolve_git_dirs_fast(wt_path: Path) -> tuple[Path | None, Path | None]:
    """Resolve `(git_dir, common_dir)` directly from `.git` without spawning git when possible."""
    dot_git = wt_path / ".git"
    git_dir: Path | None = None
    try:
        if dot_git.is_dir():
            git_dir = dot_git.resolve()
        elif dot_git.is_file():
            raw = dot_git.read_text(encoding="utf-8", errors="replace").splitlines()
            if raw and raw[0].startswith("gitdir:"):
                raw_target = raw[0][len("gitdir:"):].strip()
                if raw_target:
                    p = Path(raw_target)
                    git_dir = p.resolve() if p.is_absolute() else (wt_path / p).resolve()
    except OSError:
        git_dir = None

    if git_dir is None:
        proc = read_git(wt_path, ["rev-parse", "--git-dir", "--git-common-dir"])
        if proc is None or proc.returncode != 0:
            return None, None
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return None, None
        gd_p = Path(lines[0])
        git_dir = gd_p.resolve() if gd_p.is_absolute() else (wt_path / gd_p).resolve()
        if len(lines) >= 2:
            cd_p = Path(lines[1])
            common_dir = cd_p.resolve() if cd_p.is_absolute() else (wt_path / cd_p).resolve()
            return git_dir, common_dir
        return git_dir, git_dir

    commondir_file = git_dir / "commondir"
    try:
        if commondir_file.is_file():
            rel_common = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
            if rel_common:
                cd_p = Path(rel_common)
                common_dir = cd_p.resolve() if cd_p.is_absolute() else (git_dir / cd_p).resolve()
                return git_dir, common_dir
    except OSError:
        pass
    return git_dir, git_dir


def active_worktree_fingerprint(paths: tuple[Path, ...]) -> tuple[object, ...]:
    sigs: list[object] = []
    for wt in paths:
        git_dir, _ = _resolve_git_dirs_fast(wt)
        sigs.append(
            (
                _stat_sig(wt),
                _stat_sig(wt / "TASK"),
                _stat_sig(git_dir / "index") if git_dir is not None else None,
                _stat_sig(git_dir / "HEAD") if git_dir is not None else None,
            )
        )
    return tuple(sigs)


def _load_packed_refs_fast(common_dir: Path) -> dict[str, str]:
    packed = common_dir / "packed-refs"
    sig = _stat_sig(packed)
    if sig is None:
        return {}
    key = str(packed)
    with _CACHE_LOCK:
        cached = _PACKED_REFS_CACHE.get(key)
        if cached is not None and cached[0] == sig:
            return cached[1]
    refs: dict[str, str] = {}
    try:
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and _HEX_OID_RE.match(parts[0]):
                refs[parts[1].strip()] = parts[0]
    except OSError:
        return {}
    with _CACHE_LOCK:
        if len(_PACKED_REFS_CACHE) > 128:
            _PACKED_REFS_CACHE.clear()
        _PACKED_REFS_CACHE[key] = (sig, refs)
    return refs


def _read_ref_oid_fast(common_dir: Path | None, ref_name: str, _depth: int = 0) -> tuple[bool | None, str]:
    """Return `(exists, oid)` for `ref_name` from loose/packed refs, or `(None, '')` if fallback is needed."""
    if common_dir is None or _depth > 4:
        return None, ""
    if (common_dir / "reftable").is_dir():
        return None, ""
    loose = common_dir / ref_name
    try:
        if loose.is_file():
            content = loose.read_text(encoding="utf-8", errors="replace").strip()
            if content.startswith("ref:"):
                target = content[len("ref:"):].strip()
                if target:
                    return _read_ref_oid_fast(common_dir, target, _depth + 1)
                return True, ""
            return True, content if _HEX_OID_RE.match(content) else ""
    except OSError:
        return None, ""
    packed_map = _load_packed_refs_fast(common_dir)
    if ref_name in packed_map:
        return True, packed_map[ref_name]
    return False, ""


def _detect_repo_meta_and_origin_cached(main_worktree: Path) -> tuple[bool, str, Any, str]:
    """Return `(has_origin, default_branch, remote_spec, inferred_forge)` cached by git config/ref signatures."""
    _, common_dir = _resolve_git_dirs_fast(main_worktree)
    hosts_path = get_hosts_path()
    env_forge = os.environ.get("IDD_FORGE", "").strip().lower()
    if common_dir is not None:
        sig: tuple[Any, ...] = (
            _stat_sig(common_dir / "config"),
            _stat_sig(common_dir / "refs" / "remotes" / "origin" / "HEAD"),
            _stat_sig(common_dir / "packed-refs"),
            _stat_sig(common_dir / "refs" / "heads" / "main"),
            _stat_sig(common_dir / "refs" / "heads" / "master"),
            _stat_sig(hosts_path),
            str(hosts_path),
            env_forge,
        )
        key = str(main_worktree.resolve())
        with _CACHE_LOCK:
            cached = _REPO_META_CACHE.get(key)
            if cached is not None and cached[0] == sig:
                return cached[1]
    else:
        sig = ()
        key = ""

    has_origin = has_remote_origin(main_worktree)
    default_branch = detect_default_branch(main_worktree, has_origin, timeout=10.0)
    remote_spec = None
    inferred_forge = "local"
    if has_origin:
        remote_spec, inferred_forge = inspect_remote_origin(main_worktree)
    val = (has_origin, default_branch, remote_spec, inferred_forge)
    if key:
        with _CACHE_LOCK:
            if len(_REPO_META_CACHE) > 128:
                _REPO_META_CACHE.clear()
            _REPO_META_CACHE[key] = (sig, val)
    return val


def _probe_gh_cli_status() -> tuple[bool, str]:
    ok = False
    username = ""
    if shutil.which("gh"):
        try:
            proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=4.0)
            ok = proc.returncode == 0
            if ok:
                combined = f"{proc.stdout or ''}\n{proc.stderr or ''}"
                m = re.search(r"Logged in to [^\s]+ (?:account|as) ([^\s(]+)", combined)
                if m:
                    username = m.group(1).strip()
        except _IGNORED_GIT_ERROR:
            ok = False
    return ok, username


class GitHubCliAuthStatus:
    """Share one platform identity probe between synchronous and polling callers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = (False, "")
        self._checked_at: float | None = None
        self._inflight: Future[tuple[bool, str]] | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._checked_at = None
            self._inflight = None

    def get(self, *, background: bool = False, ttl: float = 30.0) -> tuple[bool, str]:
        with self._lock:
            cached = self._value
            if self._checked_at is not None and time.monotonic() - self._checked_at < ttl:
                return cached
            probe = self._inflight
            run_here = probe is None and not background
            if probe is None:
                probe = Future()
                if background:
                    # Publish this probe only after its worker has actually started.
                    threading.Thread(target=self._refresh, args=(probe,), daemon=True).start()
                self._inflight = probe

        if run_here:
            self._refresh(probe)
        return cached if background else probe.result()

    def _refresh(self, probe: Future[tuple[bool, str]]) -> None:
        try:
            value = _probe_gh_cli_status()
        except BaseException as exc:
            # A synchronous interruption must also release other callers of this Future.
            with self._lock:
                if self._inflight is probe:
                    self._inflight = None
            probe.set_exception(exc)
            return
        with self._lock:
            if self._inflight is probe:
                self._value = value
                self._checked_at = time.monotonic()
                self._inflight = None
        probe.set_result(value)


github_cli_auth = GitHubCliAuthStatus()


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
        m = resolve_main_worktree(root)
        if m is not None:
            repo_paths.append(m)
    else:
        if root is not None:
            m = resolve_main_worktree(root)
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
    gh_status: tuple[bool, str] | None = None

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
                if gh_status is None:
                    gh_status = github_cli_auth.get()
                gh_logged_in, gh_username = gh_status
                if gh_logged_in and (host_key == "github.com" or host_key.endswith(".github.com")):
                    configured = True
                    auth_source = "gh_cli"
                    if not username and gh_username:
                        username = gh_username

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


def _unquote_git_path(raw_path: str) -> str:
    p = raw_path.strip()
    if p.startswith('"') and p.endswith('"') and len(p) >= 2:
        p = p[1:-1]
    return p


def _parse_porcelain_v2_status(
    stdout: str,
) -> tuple[str, str, str, tuple[int, int] | None, int, int, list[dict[str, str]]]:
    """Parse `git status --porcelain=v2 --branch -uall` output in a single pass."""
    head_oid = ""
    head_branch = ""
    upstream = ""
    ab: tuple[int, int] | None = None
    modified_count = 0
    untracked_count = 0
    changed_files: list[dict[str, str]] = []

    for line in stdout.splitlines():
        if not line:
            continue
        if line.startswith("# "):
            if line.startswith("# branch.oid "):
                head_oid = line[len("# branch.oid "):].strip()
            elif line.startswith("# branch.head "):
                head_branch = line[len("# branch.head "):].strip()
            elif line.startswith("# branch.upstream "):
                upstream = line[len("# branch.upstream "):].strip()
            elif line.startswith("# branch.ab "):
                ab_parts = line[len("# branch.ab "):].strip().split()
                if len(ab_parts) == 2 and ab_parts[0].startswith("+") and ab_parts[1].startswith("-"):
                    a_str, b_str = ab_parts[0][1:], ab_parts[1][1:]
                    if a_str.isdigit() and b_str.isdigit():
                        ab = (int(a_str), int(b_str))
            continue

        kind = line[0]
        if kind == "?":
            untracked_count += 1
            rel_path = _unquote_git_path(line[2:])
            if len(changed_files) < 20:
                changed_files.append({"code": "??", "path": rel_path})
        elif kind == "1":
            parts = line.split(" ", 8)
            if len(parts) < 9:
                continue
            modified_count += 1
            xy = parts[1].replace(".", " ")
            code = xy.strip() or xy
            rel_path = _unquote_git_path(parts[8])
            if len(changed_files) < 20:
                changed_files.append({"code": code, "path": rel_path})
        elif kind == "2":
            parts = line.split(" ", 9)
            if len(parts) < 10:
                continue
            modified_count += 1
            xy = parts[1].replace(".", " ")
            code = xy.strip() or xy
            rel_path = _unquote_git_path(parts[9].split("\t", 1)[0])
            if len(changed_files) < 20:
                changed_files.append({"code": code, "path": rel_path})
        elif kind == "u":
            parts = line.split(" ", 10)
            if len(parts) < 11:
                continue
            modified_count += 1
            xy = parts[1].replace(".", " ")
            code = xy.strip() or xy
            rel_path = _unquote_git_path(parts[10])
            if len(changed_files) < 20:
                changed_files.append({"code": code, "path": rel_path})

    return head_oid, head_branch, upstream, ab, modified_count, untracked_count, changed_files


def _get_commit_info_cached(
    wt_path: Path,
    common_dir: Path | None,
    head_oid: str,
) -> tuple[str, float, str]:
    """Return `(short_sha, commit_ts, subject)` for HEAD, cached by immutable `(common_dir, head_oid)`."""
    if head_oid == "(initial)":
        return "", 0.0, ""
    cache_key: tuple[str, str] | None = None
    if common_dir is not None and head_oid and _HEX_OID_RE.match(head_oid):
        cache_key = (str(common_dir), head_oid)
        with _CACHE_LOCK:
            cached = _COMMIT_INFO_CACHE.get(cache_key)
            if cached is not None:
                return cached

    last_commit_sha = ""
    last_commit_ts = 0.0
    last_commit_subject = ""
    log_proc = read_git(wt_path, ["log", "-1", "--format=%h%x1f%ct%x1f%s"])
    if log_proc and log_proc.returncode == 0 and log_proc.stdout.strip():
        parts = log_proc.stdout.strip().split("\x1f", 2)
        if len(parts) >= 2:
            last_commit_sha = parts[0].strip()
            try:
                last_commit_ts = float(parts[1].strip())
            except ValueError:
                pass
        if len(parts) == 3:
            last_commit_subject = parts[2].strip()
        if cache_key is not None and last_commit_sha:
            with _CACHE_LOCK:
                if len(_COMMIT_INFO_CACHE) > 1024:
                    _COMMIT_INFO_CACHE.clear()
                _COMMIT_INFO_CACHE[cache_key] = (last_commit_sha, last_commit_ts, last_commit_subject)
    return last_commit_sha, last_commit_ts, last_commit_subject


def _inspect_remote_sync_ro(
    wt_path: Path,
    *,
    branch: str = "",
    has_origin: bool | None = None,
    default_branch: str = "main",
    common_dir: Path | None = None,
    head_oid: str = "",
    upstream_hint: str | None = None,
    ab_hint: tuple[int, int] | None = None,
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
        rem = read_git(wt_path, ["remote"])
        remotes = {line.strip() for line in rem.stdout.splitlines() if line.strip()} if rem and rem.returncode == 0 else set()
        has_origin = "origin" in remotes
    if not has_origin:
        return result

    if not branch:
        br_proc = read_git(wt_path, ["branch", "--show-current"])
        branch = br_proc.stdout.strip() if br_proc and br_proc.returncode == 0 else ""
    if not branch or branch == "(detached)":
        return result

    if upstream_hint is not None:
        upstream = upstream_hint
    else:
        up_proc = read_git(wt_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        upstream = up_proc.stdout.strip() if up_proc and up_proc.returncode == 0 else ""
    result["upstream"] = upstream
    if branch != default_branch and upstream == f"origin/{default_branch}":
        result["upstream_misbound"] = True

    expected_upstream = f"origin/{branch}"
    if upstream == expected_upstream and ab_hint is not None:
        result["remote_branch_exists"] = True
        result["unpushed_commits"] = ab_hint[0]
        result["behind_commits"] = ab_hint[1]
        result["remote_state"] = "ahead" if ab_hint[0] > 0 else "synced"
        return result

    if common_dir is None:
        _, common_dir = _resolve_git_dirs_fast(wt_path)

    origin_ref = f"refs/remotes/origin/{branch}"
    rem_exists, rem_oid = _read_ref_oid_fast(common_dir, origin_ref)
    if rem_exists is None:
        rem_ref_proc = read_git(wt_path, ["show-ref", "--verify", "--quiet", origin_ref])
        rem_exists = bool(rem_ref_proc and rem_ref_proc.returncode == 0)

    if rem_exists:
        result["remote_branch_exists"] = True
        if head_oid and rem_oid and head_oid == rem_oid:
            result["behind_commits"] = 0
            result["unpushed_commits"] = 0
            result["remote_state"] = "synced"
            return result
        lr_proc = read_git(wt_path, ["rev-list", "--left-right", "--count", f"{origin_ref}...HEAD"])
        if lr_proc and lr_proc.returncode == 0 and lr_proc.stdout.strip():
            counts = lr_proc.stdout.strip().split()
            if len(counts) == 2 and counts[0].isdigit() and counts[1].isdigit():
                result["behind_commits"] = int(counts[0])
                result["unpushed_commits"] = int(counts[1])
        result["remote_state"] = "ahead" if result["unpushed_commits"] > 0 else "synced"
    else:
        result["remote_branch_exists"] = False
        result["remote_state"] = "unpushed_branch"
        base_ref = f"refs/remotes/origin/{default_branch}"
        base_exists, base_oid = _read_ref_oid_fast(common_dir, base_ref)
        if base_exists is None:
            base_ref_proc = read_git(wt_path, ["show-ref", "--verify", "--quiet", base_ref])
            base_exists = bool(base_ref_proc and base_ref_proc.returncode == 0)
        if base_exists:
            if head_oid and base_oid and head_oid == base_oid:
                result["unpushed_commits"] = 0
            elif head_oid != "(initial)":
                ahead_proc = read_git(wt_path, ["rev-list", "--count", f"{base_ref}..HEAD"])
                if ahead_proc and ahead_proc.returncode == 0 and ahead_proc.stdout.strip().isdigit():
                    result["unpushed_commits"] = int(ahead_proc.stdout.strip())

    return result


def _worktree_fast_fingerprint(
    wt_path: Path,
    *,
    branch: str,
    default_branch: str,
    has_origin: bool,
) -> tuple[Any, ...] | None:
    """Compute a zero-subprocess filesystem fingerprint for a git worktree."""
    git_dir, common_dir = _resolve_git_dirs_fast(wt_path)
    if git_dir is None or common_dir is None:
        return None
    head_sig = _stat_sig(git_dir / "HEAD")
    index_sig = _stat_sig(git_dir / "index")
    wt_sig = _stat_sig(wt_path)
    task_sig = _stat_sig(wt_path / "TASK")
    git_op_flags = (
        (git_dir / "rebase-merge").exists(),
        (git_dir / "rebase-apply").exists(),
        (git_dir / "MERGE_HEAD").exists(),
    )
    remote_ref_state: tuple[bool | None, str] = (False, "")
    base_ref_state: tuple[bool | None, str] = (False, "")
    if has_origin:
        if branch and branch != "(detached)":
            remote_ref_state = _read_ref_oid_fast(common_dir, f"refs/remotes/origin/{branch}")
        base_ref_state = _read_ref_oid_fast(common_dir, f"refs/remotes/origin/{default_branch}")
    return (
        head_sig,
        index_sig,
        wt_sig,
        task_sig,
        git_op_flags,
        branch,
        default_branch,
        has_origin,
        remote_ref_state,
        base_ref_state,
    )


def _refresh_cached_pulse_timestamps(cached_pulse: dict[str, Any], *, in_progress_count: int) -> dict[str, Any]:
    """Recompute live relative timestamps on a cached pulse dict without running git."""
    pulse = dict(cached_pulse)
    last_active_ts = float(pulse.get("last_active_ts") or 0.0)
    idle_seconds = max(0.0, time.time() - last_active_ts) if last_active_ts > 0 else -1.0
    last_active_ago = format_relative_time(idle_seconds)
    has_active_work = bool(
        int(pulse.get("dirty_count") or 0) > 0
        or in_progress_count > 0
        or str(pulse.get("git_op") or "")
    )
    activity_state = _classify_activity(idle_seconds, has_active_work)
    pulse["idle_seconds"] = round(idle_seconds, 1) if idle_seconds >= 0 else -1.0
    pulse["last_active_ago"] = last_active_ago
    pulse["activity_state"] = activity_state
    pulse["pulse_summary"] = _format_pulse_summary(
        activity_state,
        last_active_ago,
        int(pulse.get("dirty_count") or 0),
        int(pulse.get("insertions") or 0),
        int(pulse.get("deletions") or 0),
        str(pulse.get("git_op") or ""),
        remote_state=str(pulse.get("remote_state") or ""),
        unpushed_commits=int(pulse.get("unpushed_commits") or 0),
    )
    return pulse


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
    head_oid = ""
    head_branch = ""
    upstream_hint: str | None = None
    ab_hint: tuple[int, int] | None = None
    git_dir: Path | None = None
    common_dir: Path | None = None

    if wt_path.is_dir():
        git_dir, common_dir = _resolve_git_dirs_fast(wt_path)
        st_proc = read_git(wt_path, ["status", "--porcelain=v2", "--branch", "-uall"])
        if st_proc and st_proc.returncode == 0:
            (
                head_oid,
                head_branch,
                upstream_str,
                ab_hint,
                modified_count,
                untracked_count,
                changed_files,
            ) = _parse_porcelain_v2_status(st_proc.stdout)
            upstream_hint = upstream_str
            for item in changed_files:
                try:
                    mtimes.append((wt_path / item["path"]).lstat().st_mtime)
                except OSError:
                    pass

    dirty_count = modified_count + untracked_count
    has_more_files = dirty_count > len(changed_files)

    insertions = 0
    deletions = 0
    if wt_path.is_dir() and modified_count > 0:
        diff_proc = read_git(wt_path, ["diff", "HEAD", "--shortstat"])
        if diff_proc is None or diff_proc.returncode != 0:
            diff_proc = read_git(wt_path, ["diff", "--shortstat"])
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
        last_commit_sha, last_commit_ts, last_commit_subject = _get_commit_info_cached(
            wt_path,
            common_dir,
            head_oid,
        )
        if last_commit_ts > 0:
            mtimes.append(last_commit_ts)

    git_op = ""
    if wt_path.is_dir() and git_dir is not None:
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
    effective_branch = branch or head_branch
    remote_sync = _inspect_remote_sync_ro(
        wt_path,
        branch=effective_branch,
        has_origin=has_origin,
        default_branch=default_branch,
        common_dir=common_dir,
        head_oid=head_oid,
        upstream_hint=upstream_hint,
        ab_hint=ab_hint,
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


def _probe_worktree_pulse_cached(
    wt_path: Path,
    *,
    in_progress_count: int = 0,
    branch: str = "",
    has_origin: bool = False,
    default_branch: str = "main",
    allow_idle_cache: bool = False,
    idle_ttl: float = _IDLE_PULSE_CACHE_TTL,
) -> dict[str, Any]:
    """Return cached pulse for unchanged clean idle worktrees, or run `inspect_worktree_pulse`."""
    wt_key = str(wt_path)
    fp: tuple[Any, ...] | None = None
    if allow_idle_cache and idle_ttl > 0:
        fp = _worktree_fast_fingerprint(
            wt_path,
            branch=branch,
            default_branch=default_branch,
            has_origin=has_origin,
        )
        if fp is not None:
            now_mono = time.monotonic()
            with _CACHE_LOCK:
                entry = _WORKTREE_PULSE_CACHE.get(wt_key)
                if (
                    entry is not None
                    and entry.get("fp") == fp
                    and (now_mono - float(entry.get("checked_at") or 0.0)) < idle_ttl
                ):
                    return _refresh_cached_pulse_timestamps(entry["pulse"], in_progress_count=in_progress_count)

    pulse = inspect_worktree_pulse(
        wt_path,
        in_progress_count=in_progress_count,
        branch=branch,
        has_origin=has_origin,
        default_branch=default_branch,
    )

    if allow_idle_cache and idle_ttl > 0:
        looks_post_land = str(pulse.get("last_commit_subject") or "").startswith("chore: 清理已汇总的任务记录")
        is_clean_idle = (
            int(pulse.get("dirty_count") or 0) == 0
            and not str(pulse.get("git_op") or "")
            and in_progress_count == 0
            and (looks_post_land or float(pulse.get("idle_seconds") or 0.0) >= 300.0)
        )
        if is_clean_idle and fp is not None:
            with _CACHE_LOCK:
                if len(_WORKTREE_PULSE_CACHE) > 512:
                    _WORKTREE_PULSE_CACHE.clear()
                _WORKTREE_PULSE_CACHE[wt_key] = {
                    "fp": fp,
                    "checked_at": time.monotonic(),
                    "pulse": dict(pulse),
                }
        else:
            with _CACHE_LOCK:
                _WORKTREE_PULSE_CACHE.pop(wt_key, None)
    return pulse


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
                "forge_host": "",
                "forge_api_base": "",
                "forge_error": "",
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
        spec, inferred = inspect_remote_origin(main_worktree)
        mr_label = "MR" if inferred == "gitlab" else ("PR" if inferred == "github" else "PR/MR")
        mr_prefix = "!" if inferred == "gitlab" else "#"
        return {
            "forge_type": inferred,
            "forge_host": spec.host if spec else "",
            "forge_api_base": spec.api_base.rstrip("/") if spec else "",
            "forge_error": "",
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
        forge_host = forge.spec.host if forge.spec else ""
        forge_api_base = (
            getattr(forge, "api_base", "") or (forge.spec.api_base if forge.spec else "")
        ).rstrip("/")
        forge_error = ""
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
                forge_error = "远端仓库查询不可用"
                warnings.append("远端仓库查询不可用，已降级为本地工作树视图。")
        except ForgeAuthError as exc:
            forge_error = str(exc).splitlines()[0].strip()
            auth_alert = {
                "host": exc.host,
                "api_base": exc.api_base,
                "forge": exc.forge_type,
                "login_cmd": exc.login_cmd,
                "token_url": exc.token_url,
            }
            warnings.append(f"{exc}（已降级为本地工作树视图）")
        except ForgeError as exc:
            forge_error = str(exc).splitlines()[0].strip()
            warnings.append(f"{exc}（已降级为本地工作树视图）")

        entry = {
            "forge_type": forge_type,
            "forge_host": forge_host,
            "forge_api_base": forge_api_base,
            "forge_error": forge_error,
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
            main_wt = resolve_main_worktree(raw_path)
            if main_wt is None:
                continue
            has_origin = has_remote_origin(main_wt)
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


def format_change_badge(
    change: dict[str, Any],
    mr_label: str,
    mr_prefix: str,
    *,
    local_unsynced: bool = False,
) -> str:
    """Format compact PR/MR + CI status string."""
    num = change.get("number")
    prefix = f"{mr_label} {mr_prefix}{num}" if num else mr_label
    if change.get("isDraft"):
        prefix += " (Draft)"
    overall = change.get("checks_overall") or "NONE"
    if local_unsynced:
        badges = {
            "PASS": "🟡 CI 全绿 (待同步)",
            "FAIL": "❌ CI 失败 (待同步)",
            "PENDING": "⏳ CI 运行中 (待同步)",
            "NONE": "⚪ 无 CI (待同步)",
        }
    else:
        badges = {
            "PASS": "✅ CI 全绿",
            "FAIL": "❌ CI 失败",
            "PENDING": "⏳ CI 运行中",
            "NONE": "⚪ 无 CI",
        }
    state = change.get("mergeStateStatus") or ""
    extra = " (落后/冲突)" if state in {"BEHIND", "DIRTY"} else ""
    return f"{prefix} · {badges.get(overall, overall)}{extra}"


UNFINISHED_TASK_STATUSES = ("planned", "in_progress", "unknown")


def _task_progress_flags(item: dict[str, Any] | None) -> tuple[bool, bool]:
    """Return `(has_blocked, has_unfinished_tasks)` from a local worktree item."""
    if not item:
        return False, False
    counts = item.get("counts") or {}
    has_blocked = int(counts.get("blocked") or 0) > 0
    unfinished_cnt = sum(int(counts.get(st) or 0) for st in UNFINISHED_TASK_STATUSES)
    if unfinished_cnt == 0 and not any(int(counts.get(s) or 0) > 0 for s in task_status.STATUSES):
        total = int(item.get("total") or 0)
        done = int(item.get("done") or 0)
        unfinished_cnt = max(0, total - done)
    return has_blocked, unfinished_cnt > 0


def _has_local_dirty_changes(item: dict[str, Any] | None) -> bool:
    """Return True when the local worktree has uncommitted files or an active git op."""
    if not item:
        return False
    pulse = item.get("pulse") or {}
    return bool(int(pulse.get("dirty_count") or 0) > 0 or str(pulse.get("git_op") or "").strip())


def _has_local_unsynced_changes(item: dict[str, Any] | None) -> bool:
    """Return True when the local worktree has uncommitted files, unpushed commits, or an active git op."""
    if not item:
        return False
    pulse = item.get("pulse") or {}
    return bool(_has_local_dirty_changes(item) or int(pulse.get("unpushed_commits") or 0) > 0)


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

    has_blocked, has_unfinished_tasks = _task_progress_flags(item)
    has_local_dirty = _has_local_dirty_changes(item)
    has_local_unsynced = _has_local_unsynced_changes(item)
    change_stale = bool(change and has_local_unsynced)

    if has_blocked:
        stage = "⛔ 受阻"
    elif change and (change.get("checks_overall") or "NONE") == "FAIL":
        stage = "🛠️ 修 CI"
    elif change:
        overall = change.get("checks_overall") or "NONE"
        if has_unfinished_tasks or has_local_unsynced:
            stage = "🟡 开发中"
        elif overall == "PENDING":
            stage = "⏳ CI 运行中"
        elif change.get("isDraft"):
            stage = f"📝 草稿 {mr_label}"
        else:
            stage = "🔵 待合入"
    elif item:
        total = int(item.get("total") or 0)
        done = int(item.get("done") or 0)
        if total > 0 and done > 0 and not has_unfinished_tasks and not has_local_dirty:
            stage = f"🟢 待提 {mr_label}"
        else:
            stage = "🟡 开发中"
    else:
        stage = "⚪ 待认领"

    change_summary = (
        format_change_badge(change, mr_label, mr_prefix, local_unsynced=change_stale)
        if change
        else "—"
    )
    return {
        "issue_number": issue_number,
        "title": title,
        "url": url,
        "stage": stage,
        "task_progress": task_progress,
        "worktree": wt_path,
        "branch": branch,
        "change": change,
        "change_stale": change_stale,
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
    st_proc = read_git(wt_path, ["status", "--porcelain=v1", "--", "TASK"])
    if st_proc and st_proc.returncode == 0 and st_proc.stdout.strip():
        return _extract_task_dirs_from_paths(st_proc.stdout.splitlines(), strip_porcelain=True)
    return set()


def _read_head_and_base_oids_fast(wt_path: Path, default_branch: str) -> tuple[Path | None, str, str]:
    """Resolve `(common_dir, head_oid, base_oid)` without git subprocesses when possible."""
    git_dir, common_dir = _resolve_git_dirs_fast(wt_path)
    if git_dir is None or common_dir is None:
        return None, "", ""
    head_oid = ""
    try:
        head_txt = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if head_txt.startswith("ref:"):
            _, head_oid = _read_ref_oid_fast(common_dir, head_txt[len("ref:"):].strip())
        elif _HEX_OID_RE.match(head_txt):
            head_oid = head_txt
    except OSError:
        head_oid = ""
    base_oid = ""
    for ref_name in (f"refs/heads/{default_branch}", f"refs/remotes/origin/{default_branch}"):
        exists, oid = _read_ref_oid_fast(common_dir, ref_name)
        if exists and oid:
            base_oid = oid
            break
    return common_dir, head_oid, base_oid


def _get_worktree_base_task_dirs(wt_path: Path, default_branch: str) -> set[str]:
    """List TASK/<dir> entries present at merge-base(default_branch, HEAD) so older branches ignore cleaned legacy dirs."""
    common_dir, head_oid, base_oid = _read_head_and_base_oids_fast(wt_path, default_branch)
    cache_key = ("base", str(common_dir), base_oid, head_oid) if (common_dir and head_oid and base_oid) else None
    if cache_key is not None:
        with _CACHE_LOCK:
            cached = _TASK_GIT_META_CACHE.get(cache_key)
            if cached is not None:
                return set(cached)
    result: set[str] = set()
    for base_ref in (default_branch, f"origin/{default_branch}"):
        mb_proc = read_git(wt_path, ["merge-base", base_ref, "HEAD"])
        if mb_proc and mb_proc.returncode == 0 and mb_proc.stdout.strip():
            mb_sha = mb_proc.stdout.strip()
            tree_proc = read_git(wt_path, ["ls-tree", "-d", "--name-only", f"{mb_sha}:TASK"])
            if tree_proc and tree_proc.returncode == 0 and tree_proc.stdout.strip():
                result = {line.strip() for line in tree_proc.stdout.splitlines() if line.strip()}
            break
    if cache_key is not None:
        with _CACHE_LOCK:
            if len(_TASK_GIT_META_CACHE) > 512:
                _TASK_GIT_META_CACHE.clear()
            _TASK_GIT_META_CACHE[cache_key] = set(result)
    return result


def _get_worktree_touched_task_dirs(
    wt_path: Path,
    default_branch: str,
    *,
    is_main: bool,
    dirty_dirs: set[str] | None = None,
) -> set[str]:
    touched: set[str] = set(dirty_dirs) if dirty_dirs is not None else _get_worktree_dirty_task_dirs(wt_path)
    if not is_main:
        common_dir, head_oid, base_oid = _read_head_and_base_oids_fast(wt_path, default_branch)
        cache_key = ("diff", str(common_dir), base_oid, head_oid) if (common_dir and head_oid and base_oid) else None
        if cache_key is not None:
            with _CACHE_LOCK:
                cached = _TASK_GIT_META_CACHE.get(cache_key)
                if cached is not None:
                    return touched | cached
        committed: set[str] = set()
        for base_ref in (default_branch, f"origin/{default_branch}"):
            diff_proc = read_git(wt_path, ["diff", "--name-only", f"{base_ref}...HEAD", "--", "TASK"])
            if diff_proc and diff_proc.returncode == 0:
                committed = _extract_task_dirs_from_paths(diff_proc.stdout.splitlines(), strip_porcelain=False)
                break
        if cache_key is not None:
            with _CACHE_LOCK:
                if len(_TASK_GIT_META_CACHE) > 512:
                    _TASK_GIT_META_CACHE.clear()
                _TASK_GIT_META_CACHE[cache_key] = set(committed)
        touched |= committed
    return touched


def _collect_all_worktrees_ro(
    main_worktree: Path,
    issue_filter: str | None,
    open_only: bool,
    *,
    default_branch: str = "main",
    all_worktrees: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    worktrees = all_worktrees if all_worktrees is not None else list_worktrees(main_worktree, timeout=10.0)
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
        entries, warnings, matched = task_status.collect_task_entries(
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
    _prelisted_worktrees: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Collect unified task + worktree pulse + remote PR/MR/Issue snapshot for a repo or TASK/ dir."""
    resolved = root.expanduser().resolve()
    if _prelisted_worktrees:
        main_wt = Path(_prelisted_worktrees[0]["path"]).resolve()
        all_worktrees = _prelisted_worktrees
    else:
        main_wt, all_worktrees = main_worktree_and_inventory(resolved)

    remote_spec = None
    inferred_forge = "local"
    if main_wt is not None:
        if register:
            register_repo(main_wt, min_touch_interval=60.0 if allow_stale_async else 0.0)
        has_origin, default_branch, remote_spec, inferred_forge = _detect_repo_meta_and_origin_cached(main_wt)
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
        "forge_host": remote_spec.host if remote_spec else "",
        "forge_api_base": remote_spec.api_base.rstrip("/") if remote_spec else "",
        "forge_error": "",
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

    extra_wt_by_str = {wt_str: (wt, wt_p) for wt, wt_p, wt_str in extra_worktrees}
    use_idle_cache = bool(not force_refresh and (allow_stale_async or forge_cache is not None))

    def probe_wt(wt_str: str) -> tuple[str, dict[str, Any]]:
        wt_p = Path(wt_str)
        br = branch_by_wt.get(wt_str, "")
        candidate_idle = False
        if use_idle_cache and wt_str in extra_wt_by_str:
            inum = _infer_worktree_issue_num(br, wt_p)
            candidate_idle = not (inum is not None and inum in open_issue_numbers)
        return wt_str, _probe_worktree_pulse_cached(
            wt_p,
            in_progress_count=in_progress_by_wt.get(wt_str, 0),
            branch=br,
            has_origin=has_origin,
            default_branch=default_branch,
            allow_idle_cache=candidate_idle,
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
    auto_merge_meta = {"enabled": get_global_auto_merge(), "source": "global"}

    return {
        "repo_name": repo_name,
        "repo_path": repo_path_str,
        "repo_url": repo_web_url,
        "default_branch": default_branch,
        "forge": effective_forge,
        "forge_host": str(forge_info.get("forge_host") or (remote_spec.host if remote_spec else "")),
        "forge_api_base": str(forge_info.get("forge_api_base") or (remote_spec.api_base.rstrip("/") if remote_spec else "")),
        "forge_error": str(forge_info.get("forge_error") or ""),
        "forge_connected": forge_connected,
        "forge_syncing": bool(forge_info.get("syncing")),
        "auth_alert": forge_info.get("auth_alert"),
        "repo_init": repo_init_meta,
        "auto_merge": auto_merge_meta,
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


def summarize_repo(snap: dict[str, Any]) -> dict[str, Any]:
    """Compute the same counters for one repository in either terminal or browser views."""
    return _compute_global_summary(
        [snap], snap.get("issues") or [], snap.get("local_only_items") or [], snap.get("orphan_changes") or [],
    )


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


def _resolve_forge_status(
    *,
    local_only: bool,
    configured: bool,
    total_repos: int,
    connected_repos: int,
    syncing_repos: int,
    error_repos: int,
    auth_error_repos: int,
) -> str:
    if local_only:
        return "local_only" if (total_repos > 0 or configured) else "unconfigured"
    if total_repos > 0:
        if connected_repos == total_repos:
            return "connected"
        if connected_repos > 0:
            return "partial"
        if auth_error_repos > 0:
            return "auth_required"
        if error_repos > 0:
            return "error"
        if syncing_repos > 0:
            return "syncing"
        return "auth_required" if not configured else "syncing"
    return "connected" if configured else "unconfigured"


def _build_forge_connections(
    repo_snaps: list[dict[str, Any]],
    *,
    local_only: bool = False,
    allow_stale_async: bool = False,
) -> dict[str, Any]:
    """Summarize live connection status for GitHub and GitLab from repo snapshots and cached auth state."""
    saved_hosts = load_hosts_config()
    has_gitlab_env = bool(os.environ.get("GITLAB_TOKEN", "").strip() or os.environ.get("GITLAB_PRIVATE_TOKEN", "").strip())
    has_github_env = bool(os.environ.get("GH_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip())
    gh_ok, gh_user = github_cli_auth.get(background=allow_stale_async)

    def _resolve_host_auth(fg: str, host_key: str, saved_entry: dict[str, str] | None) -> tuple[bool, str, str]:
        saved_tok = str((saved_entry or {}).get("token") or "").strip()
        saved_user = str((saved_entry or {}).get("username") or "").strip()
        if saved_tok:
            return True, "hosts.json", saved_user
        if fg == "gitlab" and has_gitlab_env:
            return True, "env", saved_user
        if fg == "github":
            if has_github_env:
                return True, "env", saved_user
            if gh_ok and (not host_key or host_key == "github.com" or host_key.endswith(".github.com")):
                return True, "gh_cli", saved_user or gh_user
        return False, "missing", saved_user

    def _new_bucket(fg: str, host_key: str, api_base: str, saved_entry: dict[str, str] | None) -> dict[str, Any]:
        configured, auth_source, username = _resolve_host_auth(fg, host_key, saved_entry)
        return {
            "host": host_key,
            "api_base": api_base.rstrip("/"),
            "configured": configured,
            "auth_source": auth_source,
            "username": username,
            "repo_count": 0,
            "connected_repos": 0,
            "syncing_repos": 0,
            "error_repos": 0,
            "auth_error_repos": 0,
            "repos": [],
            "last_synced_at": 0.0,
            "error": "",
            "_matched_saved_keys": set(),
        }

    buckets_by_forge: dict[str, dict[str, dict[str, Any]]] = {"github": {}, "gitlab": {}}

    for snap in repo_snaps:
        fg = str(snap.get("forge") or "local")
        if fg not in ("github", "gitlab"):
            continue
        host_key = str(snap.get("forge_host") or "").strip()
        api_base = str(snap.get("forge_api_base") or "").strip().rstrip("/")
        repo_url = str(snap.get("repo_url") or "").strip()
        if (not host_key or not api_base) and repo_url:
            parsed = urllib.parse.urlparse(repo_url)
            if parsed.netloc and not host_key:
                host_key = parsed.netloc.lower()
            if parsed.scheme and parsed.netloc and not api_base:
                api_base = f"{parsed.scheme}://{parsed.netloc}".lower()
        if not host_key and fg == "github":
            host_key = "github.com"
        if not api_base and host_key:
            api_base = f"https://{host_key}"

        hostname = host_key.split(":", 1)[0].lower() if host_key else ""
        matched_key = ""
        saved_entry: dict[str, str] | None = None
        for candidate in (host_key, hostname):
            if candidate and candidate in saved_hosts:
                matched_key = candidate
                saved_entry = saved_hosts[candidate]
                break
        if saved_entry and saved_entry.get("api_url") and not api_base:
            api_base = str(saved_entry["api_url"]).rstrip("/")

        bucket_key = host_key or api_base or fg
        forge_buckets = buckets_by_forge[fg]
        bucket = forge_buckets.get(bucket_key)
        if bucket is None:
            bucket = _new_bucket(fg, host_key or api_base, api_base, saved_entry)
            forge_buckets[bucket_key] = bucket
        if matched_key:
            bucket["_matched_saved_keys"].add(matched_key)

        repo_name = str(snap.get("repo_name") or "").strip()
        if repo_name and repo_name not in bucket["repos"]:
            bucket["repos"].append(repo_name)
        bucket["repo_count"] += 1
        if snap.get("forge_connected"):
            bucket["connected_repos"] += 1
        if snap.get("forge_syncing"):
            bucket["syncing_repos"] += 1
        has_auth_alert = isinstance(snap.get("auth_alert"), dict)
        forge_err = str(snap.get("forge_error") or "").strip()
        if has_auth_alert:
            bucket["auth_error_repos"] += 1
        elif forge_err:
            bucket["error_repos"] += 1
        if not snap.get("forge_connected") and not bucket["error"]:
            if forge_err:
                bucket["error"] = forge_err
            elif has_auth_alert:
                bucket["error"] = f"访问 {host_key or api_base} 需要鉴权令牌"

        fetched_at = float(snap.get("forge_fetched_at") or 0.0)
        if fetched_at > bucket["last_synced_at"]:
            bucket["last_synced_at"] = fetched_at

    for saved_key, entry in sorted(saved_hosts.items()):
        entry_fg = str(entry.get("forge") or ("github" if "github.com" in saved_key else "gitlab"))
        if entry_fg not in ("github", "gitlab"):
            continue
        forge_buckets = buckets_by_forge[entry_fg]
        already = any(
            saved_key in b["_matched_saved_keys"] or b["host"] == saved_key
            for b in forge_buckets.values()
        )
        if already:
            continue
        api_base = str(entry.get("api_url") or f"https://{saved_key}").rstrip("/")
        forge_buckets[saved_key] = _new_bucket(entry_fg, saved_key, api_base, entry)

    if not buckets_by_forge["github"] and (has_github_env or gh_ok):
        buckets_by_forge["github"]["github.com"] = _new_bucket("github", "github.com", "https://github.com", None)

    if not buckets_by_forge["gitlab"] and has_gitlab_env:
        env_url = os.environ.get("IDD_GITLAB_URL", "").strip().rstrip("/")
        gl_host = urllib.parse.urlparse(env_url).netloc.lower() if env_url else "gitlab"
        buckets_by_forge["gitlab"][gl_host or "gitlab"] = _new_bucket("gitlab", gl_host or "gitlab", env_url, None)

    connections: dict[str, Any] = {}
    for fg, label in (("github", "GitHub"), ("gitlab", "GitLab")):
        raw_buckets = list(buckets_by_forge[fg].values())
        hosts_out: list[dict[str, Any]] = []
        total_repos = 0
        connected_repos = 0
        syncing_repos = 0
        error_repos = 0
        auth_error_repos = 0
        last_synced_at = 0.0
        first_error = ""

        for b in raw_buckets:
            h_status = _resolve_forge_status(
                local_only=local_only,
                configured=bool(b["configured"]),
                total_repos=int(b["repo_count"]),
                connected_repos=int(b["connected_repos"]),
                syncing_repos=int(b["syncing_repos"]),
                error_repos=int(b["error_repos"]),
                auth_error_repos=int(b["auth_error_repos"]),
            )
            h_err = "" if h_status in ("connected", "local_only") else str(b["error"] or "")
            hosts_out.append(
                {
                    "host": b["host"],
                    "api_base": b["api_base"],
                    "status": h_status,
                    "configured": bool(b["configured"]),
                    "auth_source": b["auth_source"],
                    "username": b["username"],
                    "repo_count": int(b["repo_count"]),
                    "connected_repos": int(b["connected_repos"]),
                    "repos": list(b["repos"]),
                    "last_synced_at": float(b["last_synced_at"]),
                    "error": h_err,
                }
            )
            total_repos += int(b["repo_count"])
            connected_repos += int(b["connected_repos"])
            syncing_repos += int(b["syncing_repos"])
            error_repos += int(b["error_repos"])
            auth_error_repos += int(b["auth_error_repos"])
            if float(b["last_synced_at"]) > last_synced_at:
                last_synced_at = float(b["last_synced_at"])
            if h_err and not first_error:
                first_error = h_err

        configured = any(h["configured"] for h in hosts_out)
        overall_status = _resolve_forge_status(
            local_only=local_only,
            configured=configured,
            total_repos=total_repos,
            connected_repos=connected_repos,
            syncing_repos=syncing_repos,
            error_repos=error_repos,
            auth_error_repos=auth_error_repos,
        )
        if overall_status in ("connected", "local_only", "unconfigured"):
            first_error = ""
        connections[fg] = {
            "forge": fg,
            "label": label,
            "status": overall_status,
            "configured": configured,
            "connected_repos": connected_repos,
            "total_repos": total_repos,
            "syncing_repos": syncing_repos,
            "error_repos": error_repos,
            "auth_error_repos": auth_error_repos,
            "last_synced_at": last_synced_at,
            "error": first_error,
            "hosts": hosts_out,
        }

    return connections


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
    prelisted_worktrees: dict[str, list[dict[str, str]]] = {}
    if current_cwd is not None:
        cur_main, cur_wts = main_worktree_and_inventory(current_cwd)
        if cur_main is not None:
            prelisted_worktrees[str(cur_main)] = cur_wts
            register_repo(cur_main, min_touch_interval=60.0 if allow_stale_async else 0.0)

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
                _prelisted_worktrees=prelisted_worktrees.get(str(repo_path.resolve())),
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
        "local_only": bool(local_only),
        "generated_at": time.time(),
        "repos_config_path": str(get_repos_path()),
        "config": {
            "auto_merge": get_global_auto_merge(),
            "config_path": str(get_config_path()),
        },
        "forge_syncing": any(bool(r.get("forge_syncing")) for r in repos_out),
        "forge_connections": _build_forge_connections(
            repos_out,
            local_only=local_only,
            allow_stale_async=allow_stale_async,
        ),
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
        summary = summarize_repo(snap)
        auth_alerts, warnings = _dedupe_auth_alerts([snap])
        return {
            "global": False,
            "local_only": bool(local_only),
            "generated_at": snap["generated_at"],
            "repos_config_path": str(get_repos_path()),
            "config": {
                "auto_merge": get_global_auto_merge(),
                "config_path": str(get_config_path()),
            },
            "forge_syncing": bool(snap.get("forge_syncing")),
            "forge_connections": _build_forge_connections(
                [snap],
                local_only=local_only,
                allow_stale_async=allow_stale_async,
            ),
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


def _format_tty_watch_frame(frame: str) -> str:
    """Format a flicker-free TTY frame using synchronized output and line-wise erase."""
    lines = frame.split("\n")
    body = "\x1b[K\n".join(lines)
    return f"\x1b[?2026h\x1b[H{body}\x1b[K\x1b[J\x1b[?2026l"


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
                sys.stdout.write(_format_tty_watch_frame(frame))
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
