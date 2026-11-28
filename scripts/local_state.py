"""Local JSON storage. Mutations of host records hold the lock across read, edit and replace."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
import json
import os
from pathlib import Path
import stat
import tempfile
import threading


def get_config_dir() -> Path:
    override = os.environ.get("IDD_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".config" / "idd").resolve()


def get_hosts_path() -> Path:
    return get_config_dir() / "hosts.json"


def load_hosts_config() -> dict[str, dict[str, str]]:
    path = get_hosts_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@contextmanager
def config_file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an advisory cross-process exclusive file lock when supported by the OS."""
    if fcntl is None:
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def atomic_write_json(path: Path, data: object, *, mode: int | None = None) -> None:
    """Publish a complete UTF-8 JSON document by replacing a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        if mode is not None:
            tmp.chmod(mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


_HOSTS_LOCK = threading.Lock()


def _write_hosts(hosts: dict[str, dict[str, str]]) -> None:
    path = get_hosts_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass
    atomic_write_json(path, hosts, mode=stat.S_IRUSR | stat.S_IWUSR)


def set_host(host: str, record: dict[str, str]) -> None:
    with _HOSTS_LOCK, config_file_lock(get_config_dir() / ".hosts.lock"):
        hosts = load_hosts_config()
        hosts[host] = record
        _write_hosts(hosts)


def remove_hosts(candidates: Iterable[str], *, first_only: bool = False) -> bool:
    with _HOSTS_LOCK, config_file_lock(get_config_dir() / ".hosts.lock"):
        hosts = load_hosts_config()
        removed = False
        for host in candidates:
            if host in hosts:
                del hosts[host]
                removed = True
                if first_only:
                    break
        if removed:
            _write_hosts(hosts)
        return removed
