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
from typing import Any
import stat
import tempfile
import threading

from command_runner import IddError


def get_config_dir() -> Path:
    override = os.environ.get("IDD_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".config" / "idd").resolve()


def get_hosts_path() -> Path:
    return get_config_dir() / "hosts.json"


class LocalStateError(IddError):
    """A persistent state change could not be completed."""


def read_json_file(path: Path, missing: Any) -> Any:
    """Use the missing value only when the file does not exist."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return missing


def _read_hosts(path: Path) -> dict[str, dict[str, str]]:
    data = read_json_file(path, {})
    if not isinstance(data, dict):
        raise ValueError("主机配置的顶层必须是 JSON 对象")
    return data


def load_hosts_config() -> dict[str, dict[str, str]]:
    try:
        return _read_hosts(get_hosts_path())
    except (OSError, ValueError):
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


@contextmanager
def _host_transaction() -> Iterator[dict[str, dict[str, str]]]:
    path = get_hosts_path()
    try:
        with _HOSTS_LOCK, config_file_lock(path.with_name(".hosts.lock")):
            yield _read_hosts(path)
    except (OSError, ValueError) as exc:
        raise LocalStateError(f"无法更新主机配置 {path}：{exc}") from exc


def _write_hosts(hosts: dict[str, dict[str, str]]) -> None:
    path = get_hosts_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass
    atomic_write_json(path, hosts, mode=stat.S_IRUSR | stat.S_IWUSR)


def set_host(host: str, record: dict[str, str]) -> None:
    with _host_transaction() as hosts:
        hosts[host] = record
        _write_hosts(hosts)


def remove_hosts(candidates: Iterable[str], *, first_only: bool = False) -> bool:
    with _host_transaction() as hosts:
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

_CONFIG_LOCK = threading.Lock()


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def _read_global_config() -> dict[str, Any]:
    data = read_json_file(get_config_path(), {})
    if not isinstance(data, dict):
        raise ValueError("全局配置的顶层必须是 JSON 对象")
    return data


def get_global_auto_merge() -> bool:
    with _CONFIG_LOCK, config_file_lock(get_config_dir() / ".config.lock"):
        try:
            return bool(_read_global_config().get("auto_merge", False))
        except (OSError, ValueError):
            return False


def set_global_auto_merge(enabled: bool) -> dict[str, Any]:
    try:
        with _CONFIG_LOCK, config_file_lock(get_config_dir() / ".config.lock"):
            config = _read_global_config()
            config["auto_merge"] = bool(enabled)
            atomic_write_json(get_config_path(), config)
    except (OSError, ValueError) as exc:
        raise LocalStateError(f"无法更新全局配置 {get_config_path()}：{exc}") from exc
    return config
