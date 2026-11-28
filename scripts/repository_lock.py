"""Serialize IDD operations across linked Git checkouts, processes and threads."""

from __future__ import annotations

from contextlib import contextmanager
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator

from command_runner import IddError, run_cmd


MAIN_GIT_LOCK = "idd-main-git.lock"
_OWNERS = threading.local()


def _resolve_git_common_dir(repo_dir: Path) -> Path:
    """Resolve the shared `.git` common directory for lock placement across worktrees."""
    proc = run_cmd(["git", "-C", str(repo_dir), "rev-parse", "--git-common-dir"])
    raw = proc.stdout.strip()
    if not raw:
        raise IddError(f"无法解析 Git 公共目录：{repo_dir}")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo_dir / candidate
    return candidate.resolve()


def _read_lock_owner_info(lock_path: Path) -> dict[str, Any]:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _format_lock_holder(owner: dict[str, Any]) -> str:
    parts: list[str] = []
    branch = str(owner.get("branch") or "").strip()
    cmd = str(owner.get("command") or "").strip()
    pid = owner.get("pid")
    if branch:
        parts.append(f"分支 `{branch}`")
    if cmd:
        parts.append(cmd)
    if pid:
        parts.append(f"PID {pid}")
    return "，".join(parts) if parts else "另一会话"


@contextmanager
def repo_file_lock(
    main_worktree: Path,
    lock_name: str,
    *,
    owner_info: dict[str, Any] | None = None,
    wait_prefix: str = "",
    timeout: float = 0.0,
) -> Iterator[Path]:
    """Acquire a reentrant cross-process exclusive repository lock under git-common-dir."""
    common_dir = _resolve_git_common_dir(main_worktree)
    lock_path = (common_dir / lock_name).resolve()
    # Threads open distinct descriptors. Only the same thread and process may reenter.
    owner = (os.getpid(), lock_path)
    held = getattr(_OWNERS, "held", ())
    if owner in held or fcntl is None:
        yield lock_path
        return

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    handle = os.fdopen(fd, "r+", encoding="utf-8")
    acquired = False
    try:
        waited = False
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            waited = True
            holder = _format_lock_holder(_read_lock_owner_info(lock_path))
            if wait_prefix:
                print(f"⏳ {wait_prefix}：当前正被 {holder} 占用，排队等待中...", flush=True)
            if timeout <= 0.0:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                acquired = True
            else:
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except BlockingIOError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0.0:
                            latest_holder = _format_lock_holder(_read_lock_owner_info(lock_path))
                            raise IddError(
                                f"等待 {wait_prefix or lock_name} 超时（{timeout:.1f}s），当前持锁者：{latest_holder}。",
                                exit_code=3,
                            )
                        time.sleep(min(0.05, remaining))
        if waited and wait_prefix:
            print(f"🔓 已获取 {wait_prefix} 锁，继续执行...", flush=True)

        payload = dict(owner_info or {})
        payload["pid"] = os.getpid()
        payload["started_at"] = round(time.time(), 3)
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.flush()

        _OWNERS.held = (*held, owner)
        try:
            yield lock_path
        finally:
            _OWNERS.held = held
    finally:
        if acquired:
            try:
                handle.seek(0)
                handle.truncate()
                handle.flush()
            except OSError:
                pass
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
