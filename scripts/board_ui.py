#!/usr/bin/env python3
"""Local HTTP server and offline single-page Web Dashboard for `idd board`."""

from __future__ import annotations

from functools import partial
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Callable
import urllib.parse
import webbrowser

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from forge import (  # noqa: E402
    ForgeError,
    evaluate_repo_init_settings,
    get_forge,
    inspect_remote_origin,
    normalize_host_input,
    verify_host_token,
)
from local_state import remove_hosts, set_host
from git_worktrees import default_worktree_root, has_remote_origin
from worktree_cleanup import CleanupResult, inspect_worktree, remove_merged_worktree
import monitor  # noqa: E402
from local_http import LocalHTTPServer, LocalRequestHandler
from version import get_version  # noqa: E402


BOARD_HTML = (SCRIPT_DIR / "web" / "board.html").read_text(encoding="utf-8")


def _apply_repo_init_for_path(repo_path: Path, *, apply: bool = True) -> dict[str, object]:
    """Run or probe `repo_init` for `repo_path` and persist its status in `repos.json`."""
    resolved = repo_path.expanduser().resolve()
    try:
        forge = get_forge(resolved)
        result = forge.repo_init(apply=apply)
        aligned, mismatches = evaluate_repo_init_settings(result)
        if aligned:
            monitor.set_repo_init_meta(resolved, "aligned")
            state = "aligned"
        else:
            monitor.set_repo_init_meta(resolved, "pending", mismatches=mismatches, error="")
            state = "pending"
        return {
            "repo_path": str(resolved),
            "repo_name": resolved.name,
            "forge": str(result.get("forge") or ""),
            "repo": str(result.get("repo") or ""),
            "ok": True,
            "aligned": aligned,
            "state": state,
            "mismatches": mismatches,
            "error": "",
        }
    except Exception as exc:
        err_msg = str(exc)
        prev_meta = monitor.get_repo_init_meta(resolved)
        monitor.set_repo_init_meta(
            resolved,
            "pending",
            mismatches=list(prev_meta.get("mismatches") or []),
            error=err_msg,
        )
        return {
            "repo_path": str(resolved),
            "repo_name": resolved.name,
            "ok": False,
            "aligned": False,
            "state": "pending",
            "mismatches": list(prev_meta.get("mismatches") or []),
            "error": err_msg,
        }


def _repo_matches_host(repo_path: Path, host_key: str) -> bool:
    """Return True when `repo_path`'s origin remote points at `host_key`."""
    spec, _ = inspect_remote_origin(repo_path)
    if spec is None:
        return False
    target = host_key.strip().lower()
    return spec.host.lower() == target or spec.hostname.lower() == target


class _MergedChangesCache:
    """Short-TTL per-repo cache of merged PR/MR records for batch worktree cleanup."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, list[dict[str, object]]]] = {}

    def get_merged_for_branch(
        self,
        repo_path: Path,
        forge: object,
        branch: str,
    ) -> list[dict[str, object]] | None:
        key = str(repo_path.expanduser().resolve())
        now = time.monotonic()
        cached_list: list[dict[str, object]] | None = None
        if self.ttl_seconds > 0:
            with self._lock:
                rec = self._entries.get(key)
                if rec is not None and (now - rec[0]) < self.ttl_seconds:
                    cached_list = rec[1]

        if cached_list is None:
            bulk = forge.list_changes(state="merged", limit=100)  # type: ignore[attr-defined]
            if isinstance(bulk, list):
                cached_list = bulk
                if self.ttl_seconds > 0:
                    with self._lock:
                        self._entries[key] = (time.monotonic(), bulk)

        if cached_list is not None:
            matched = [c for c in cached_list if str(c.get("headRefName") or "") == branch]
            if matched:
                return matched

        return forge.list_changes(state="merged", head_branch=branch, limit=10)  # type: ignore[attr-defined]


def _cleanup_single_worktree(
    repo_path: Path,
    worktree_path: Path,
    *,
    merged_cache: _MergedChangesCache | None = None,
) -> dict[str, object]:
    """Safely remove a single clean, merged worktree directory while preserving its branch."""
    main = monitor.resolve_main_worktree_ro(repo_path)
    if main is None:
        return {"ok": False, "status": "error", "error": f"无效的 Git 仓库路径：{repo_path}"}
    target = worktree_path.expanduser().resolve()
    managed_root = default_worktree_root(main)
    candidate = inspect_worktree(main, target, managed_root)
    if isinstance(candidate, CleanupResult):
        return _cleanup_payload(candidate)
    try:
        forge = get_forge(main)
        merged = (
            merged_cache.get_merged_for_branch(main, forge, candidate.branch)
            if merged_cache is not None
            else forge.list_changes(state="merged", head_branch=candidate.branch, limit=10)
        )
    except ForgeError as exc:
        return _cleanup_payload(CleanupResult("error", target, str(exc), candidate.branch))
    if not isinstance(merged, list):
        return _cleanup_payload(CleanupResult("error", target, "远端已合入 PR/MR 查询失败，已跳过清理", candidate.branch))
    result = remove_merged_worktree(
        main, target, candidate.branch, managed_root, merged, ref_prefix=f"{forge.mr_label} {forge.mr_prefix}",
    )
    return _cleanup_payload(result)


def _cleanup_payload(result: CleanupResult) -> dict[str, object]:
    ok = result.status in ("removed", "already_removed")
    payload: dict[str, object] = {"ok": ok, "status": result.status, "worktree": str(result.path)}
    if result.branch:
        payload["branch"] = result.branch
    if result.status == "removed":
        payload["ref"] = result.ref
        payload["message"] = f"已移除工作树目录（保留分支 {result.branch}）— {result.ref}"
    else:
        payload["message" if ok else "error"] = result.message
    return payload


class _InflightSlot:
    """Per-flight synchronization slot for `_SnapshotCoalescer`."""

    __slots__ = ("event", "payload", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: bytes | None = None
        self.error: BaseException | None = None


def _extract_active_worktrees_from_snapshot(snapshot: object) -> tuple[Path, ...]:
    if not isinstance(snapshot, dict):
        return ()
    seen: list[Path] = []
    seen_str: set[str] = set()
    for bucket_key in ("issues", "local_only_items"):
        entries = snapshot.get(bucket_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_wt = str(entry.get("worktree") or "").strip()
            if raw_wt and raw_wt not in seen_str:
                seen_str.add(raw_wt)
                seen.append(Path(raw_wt))
    return tuple(seen)


class _SnapshotCoalescer:
    """Thread-safe short-TTL JSON snapshot cache with singleflight request coalescing."""

    def __init__(self, ttl_seconds: float = 1.5) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._payload: bytes | None = None
        self._stored_at: float = 0.0
        self._watched_paths: tuple[Path, ...] = ()
        self._watched_fp: tuple[object, ...] = ()
        self._epoch: int = 0
        self._inflight: _InflightSlot | None = None

    def invalidate(self) -> None:
        """Clear cached snapshot bytes and bump epoch so stale in-flight runs cannot repopulate."""
        with self._lock:
            self._epoch += 1
            self._payload = None
            self._stored_at = 0.0
            self._watched_paths = ()
            self._watched_fp = ()

    def get_bytes(self, producer: Callable[[], object], *, bypass_cache: bool = False) -> bytes:
        now = time.monotonic()
        wait_slot: _InflightSlot | None = None
        own_slot: _InflightSlot | None = None
        my_epoch = 0

        with self._lock:
            if (
                not bypass_cache
                and self.ttl_seconds > 0.0
                and self._payload is not None
                and (now - self._stored_at) < self.ttl_seconds
            ):
                watched = self._watched_paths
                expected_fp = self._watched_fp
                cached_payload = self._payload
            else:
                watched = ()
                expected_fp = ()
                cached_payload = None

        if cached_payload is not None:
            if not watched or monitor.active_worktree_fingerprint(watched) == expected_fp:
                return cached_payload

        with self._lock:
            if not bypass_cache and self._inflight is not None:
                wait_slot = self._inflight
            else:
                if bypass_cache:
                    self._epoch += 1
                    self._payload = None
                    self._stored_at = 0.0
                    self._watched_paths = ()
                    self._watched_fp = ()
                my_epoch = self._epoch
                if self._inflight is None:
                    own_slot = _InflightSlot()
                    self._inflight = own_slot

        if wait_slot is not None:
            wait_slot.event.wait(timeout=30.0)
            if wait_slot.error is not None:
                raise wait_slot.error
            if wait_slot.payload is not None:
                return wait_slot.payload
            return json.dumps(producer(), ensure_ascii=False).encode("utf-8")

        try:
            snap_obj = producer()
            body = json.dumps(snap_obj, ensure_ascii=False).encode("utf-8")
            watched_paths = _extract_active_worktrees_from_snapshot(snap_obj)
            watched_fp = monitor.active_worktree_fingerprint(watched_paths) if watched_paths else ()
        except BaseException as exc:
            if own_slot is not None:
                own_slot.error = exc
                with self._lock:
                    if self._inflight is own_slot:
                        self._inflight = None
                own_slot.event.set()
            raise

        with self._lock:
            if self._epoch == my_epoch and self.ttl_seconds > 0.0:
                self._payload = body
                self._stored_at = time.monotonic()
                self._watched_paths = watched_paths
                self._watched_fp = watched_fp
            if own_slot is not None:
                own_slot.payload = body
                if self._inflight is own_slot:
                    self._inflight = None
                own_slot.event.set()
        return body


class BoardRequestHandler(LocalRequestHandler):
    """Serve the IDD Web Dashboard HTML and JSON snapshot endpoints."""

    snapshot_cache: _SnapshotCoalescer | None = None

    def __init__(
        self,
        *args: object,
        cache: monitor.ForgeSnapshotCache,
        root: Path | None,
        global_mode: bool,
        local_only: bool,
        version: str,
        merged_cache: _MergedChangesCache | None = None,
        snapshot_cache: _SnapshotCoalescer | None = None,
        **kwargs: object,
    ) -> None:
        self.cache = cache
        self.root = root
        self.global_mode = global_mode
        self.local_only = local_only
        self.version = version
        self.merged_cache = merged_cache
        self.snapshot_cache = snapshot_cache
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def _require_local_csrf(self) -> bool:
        if self.headers.get("X-IDD-Request") != "1":
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Missing X-IDD-Request header"})
            return False
        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            parsed_origin = urllib.parse.urlparse(origin)
            if parsed_origin.hostname not in ("127.0.0.1", "localhost", "::1"):
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Cross-origin request rejected"})
                return False
        return True

    def _read_json_body(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > 65536:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _target_repos(self) -> list[Path]:
        if not self.global_mode and self.root is not None:
            return [self.root]
        return [Path(r["path"]) for r in monitor.load_registered_repos(prune_missing=True)]

    def _invalidate_snapshot_cache(self) -> None:
        if self.snapshot_cache is not None:
            self.snapshot_cache.invalidate()

    def _refresh_cached_repos(self, *, timeout: float = 2.0) -> None:
        monitor.github_cli_auth.invalidate()
        monitor.invalidate_monitor_caches()
        self._invalidate_snapshot_cache()
        if self.local_only:
            self.cache.invalidate_all()
            return
        self.cache.refresh_now(self._target_repos(), timeout=timeout)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            rendered = BOARD_HTML.replace("__IDD_VERSION__", html.escape(self.version))
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", rendered.encode("utf-8"))
            return

        if parsed.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "version": self.version})
            return

        if parsed.path == "/api/config":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "auto_merge": monitor.get_global_auto_merge(),
                    "config_path": str(monitor.get_config_path()),
                },
            )
            return

        if parsed.path == "/api/auth/status":
            try:
                auth_status = monitor.collect_auth_hosts_status(root=self.root, global_mode=self.global_mode)
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, auth_status)
            return

        if parsed.path == "/api/snapshot":
            params = urllib.parse.parse_qs(parsed.query)
            force_refresh = params.get("refresh", ["0"])[0] in ("1", "true", "yes")
            if force_refresh:
                monitor.invalidate_monitor_caches()
                if not self.local_only:
                    self.cache.warm_async(self._target_repos(), force_refresh=True)

            def _produce_snapshot() -> dict[str, object]:
                return monitor.collect_scope_snapshot(
                    root=self.root,
                    global_mode=self.global_mode,
                    open_only=False,
                    local_only=self.local_only,
                    forge_cache=self.cache,
                    force_refresh=False,
                    allow_stale_async=True,
                )

            try:
                if self.snapshot_cache is not None:
                    body = self.snapshot_cache.get_bytes(_produce_snapshot, bypass_cache=force_refresh)
                    self._send_bytes(HTTPStatus.OK, "application/json; charset=utf-8", body)
                    return
                snapshot = _produce_snapshot()
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, snapshot)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if not self._require_local_csrf():
            return

        if parsed.path == "/api/auth/save":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请求格式无效"})
                return
            raw_host = str(payload.get("host") or "").strip()
            token = str(payload.get("token") or "").strip()
            explicit_forge = str(payload.get("forge") or "").strip().lower()
            no_verify = bool(payload.get("no_verify"))

            if not raw_host or not token:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请同时提供主机地址与个人访问令牌"})
                return

            try:
                explicit_scheme = raw_host.lower().startswith(("http://", "https://"))
                use_http = raw_host.lower().startswith("http://")
                host_key, api_base = normalize_host_input(raw_host, use_http=use_http)
                forge_type = (
                    explicit_forge
                    if explicit_forge in ("github", "gitlab")
                    else ("github" if (host_key == "github.com" or host_key.endswith(".github.com")) else "gitlab")
                )
                username = "unverified"
                if not no_verify:
                    try:
                        username = verify_host_token(forge_type, api_base, token)
                    except ForgeError:
                        if not explicit_scheme and forge_type == "gitlab" and api_base.startswith("https://"):
                            http_base = f"http://{host_key}"
                            username = verify_host_token(forge_type, http_base, token)
                            api_base = http_base
                        else:
                            raise
            except ForgeError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return

            set_host(host_key, {
                "forge": forge_type,
                "api_url": api_base,
                "token": token,
                "username": username,
            })
            auto_repo_init = payload.get("auto_repo_init", True)
            if isinstance(auto_repo_init, str):
                auto_repo_init = auto_repo_init.strip().lower() not in ("0", "false", "no")
            else:
                auto_repo_init = bool(auto_repo_init)
            repo_init_results: list[dict[str, object]] = []
            for repo_path in self._target_repos():
                resolved_repo = repo_path.expanduser().resolve()
                has_origin = has_remote_origin(resolved_repo)
                if not has_origin or not _repo_matches_host(resolved_repo, host_key):
                    continue
                if monitor.get_repo_init_meta(resolved_repo)["state"] == "aligned":
                    continue
                repo_init_results.append(
                    _apply_repo_init_for_path(resolved_repo, apply=auto_repo_init)
                )
            self._refresh_cached_repos(timeout=2.0)
            auth_status = monitor.collect_auth_hosts_status(root=self.root, global_mode=self.global_mode)
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "host": host_key,
                    "api_base": api_base,
                    "forge": forge_type,
                    "username": username,
                    "repo_init_results": repo_init_results,
                    "auth": auth_status,
                },
            )
            return

        if parsed.path == "/api/repo/init":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请求格式无效"})
                return
            apply_all = bool(payload.get("all"))
            raw_repo_path = str(payload.get("repo_path") or "").strip()
            target_repos = [p.expanduser().resolve() for p in self._target_repos()]
            results: list[dict[str, object]] = []
            if apply_all:
                for rp in target_repos:
                    has_origin = has_remote_origin(rp)
                    if not has_origin:
                        continue
                    if monitor.get_repo_init_meta(rp)["state"] == "aligned":
                        continue
                    results.append(_apply_repo_init_for_path(rp, apply=True))
            else:
                if not raw_repo_path:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "缺少 repo_path 参数"})
                    return
                try:
                    req_path = Path(raw_repo_path).expanduser().resolve()
                except OSError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "无效的仓库路径"})
                    return
                if req_path not in target_repos:
                    self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "仓库不在当前监控白名单内"})
                    return
                results.append(_apply_repo_init_for_path(req_path, apply=True))

            self._refresh_cached_repos(timeout=1.5)
            applied_count = sum(1 for r in results if r.get("ok") and r.get("aligned"))
            failed = [r for r in results if not r.get("ok")]
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": len(failed) == 0,
                    "results": results,
                    "applied_count": applied_count,
                    "failed_count": len(failed),
                    "error": str(failed[0].get("error") or "") if failed else "",
                },
            )
            return

        if parsed.path == "/api/auth/logout":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请求格式无效"})
                return
            raw_host = str(payload.get("host") or "").strip()
            removed = False
            if raw_host:
                candidates = {raw_host}
                try:
                    hk, _ = normalize_host_input(raw_host)
                    candidates.add(hk)
                except ForgeError:
                    pass
                removed = remove_hosts(candidates)
                if removed:
                    self._refresh_cached_repos(timeout=1.5)
            auth_status = monitor.collect_auth_hosts_status(root=self.root, global_mode=self.global_mode)
            self._send_json(HTTPStatus.OK, {"ok": True, "removed": removed, "auth": auth_status})
            return

        if parsed.path == "/api/config/auto-merge":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请求格式无效"})
                return
            scope = str(payload.get("scope") or "").strip().lower()
            if scope == "repo":
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "auto_merge 仅支持全局开关，不支持仓库级设置"})
                return
            if scope not in ("", "global"):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "scope 必须为 global"})
                return
            raw_enabled = payload.get("enabled")
            if not isinstance(raw_enabled, bool):
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "enabled 必须为布尔值"})
                return
            cfg = monitor.set_global_auto_merge(raw_enabled)
            self._invalidate_snapshot_cache()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "scope": "global",
                    "auto_merge": bool(cfg["auto_merge"]),
                    "config_path": str(monitor.get_config_path()),
                },
            )
            return

        if parsed.path == "/api/cleanup":
            payload = self._read_json_body()
            if payload is None:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "请求格式无效"})
                return
            raw_repo_path = str(payload.get("repo_path") or "").strip()
            raw_worktree = str(payload.get("worktree") or "").strip()
            if not raw_repo_path or not raw_worktree:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "缺少 repo_path 或 worktree 参数"})
                return
            try:
                req_path = Path(raw_repo_path).expanduser().resolve()
                wt_path = Path(raw_worktree).expanduser().resolve()
            except OSError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "无效的路径参数"})
                return
            target_repos = [p.expanduser().resolve() for p in self._target_repos()]
            if req_path not in target_repos:
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "仓库不在当前监控白名单内"})
                return
            result = _cleanup_single_worktree(
                req_path,
                wt_path,
                merged_cache=getattr(self, "merged_cache", None),
            )
            if result.get("ok"):
                monitor.invalidate_monitor_caches()
                self._invalidate_snapshot_cache()
            self._send_json(HTTPStatus.OK, result)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})


def _bind_server(host: str, port: int | None, handler_cls: type[BaseHTTPRequestHandler]) -> LocalHTTPServer:
    if port is None:
        try:
            return LocalHTTPServer((host, 17890), handler_cls)
        except OSError:
            return LocalHTTPServer((host, 0), handler_cls)
    return LocalHTTPServer((host, port), handler_cls)


def run_board_server(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    root: Path | None = None,
    global_mode: bool = True,
    local_only: bool = False,
    forge_ttl: float = 30.0,
    no_open: bool = False,
    version: str | None = None,
) -> int:
    """Start the local IDD Web Dashboard server and open the browser unless disabled."""
    resolved_version = version if version is not None else get_version()
    cache = monitor.ForgeSnapshotCache(ttl_seconds=forge_ttl)
    snapshot_cache = _SnapshotCoalescer(ttl_seconds=1.5)
    if not local_only:
        def _warm_on_boot() -> None:
            if not global_mode and root is not None:
                cache.warm_async([root], force_refresh=False)
            else:
                repos = [Path(r["path"]) for r in monitor.load_registered_repos(prune_missing=True)]
                cache.warm_async(repos, force_refresh=False)
        threading.Thread(target=_warm_on_boot, daemon=True).start()
    merged_cache = _MergedChangesCache(ttl_seconds=60.0)
    handler_cls = partial(
        BoardRequestHandler,
        cache=cache,
        root=root,
        global_mode=global_mode,
        local_only=local_only,
        version=resolved_version,
        merged_cache=merged_cache,
        snapshot_cache=snapshot_cache,
    )
    server = _bind_server(host, port, handler_cls)  # type: ignore[arg-type]
    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in ("0.0.0.0", "") else str(actual_host)
    url = f"http://{display_host}:{actual_port}"

    print(f"IDD Web 看板已启动: http://{actual_host}:{actual_port} （按 Ctrl+C 停止）", flush=True)
    if not no_open and os.environ.get("IDD_NO_BROWSER") != "1":
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
