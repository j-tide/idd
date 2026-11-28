"""Shared latest-snapshot feed for the board's Server-Sent Events subscribers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import json
import threading
from typing import Any


def sample_interval(snapshot: dict[str, Any]) -> float:
    if snapshot["forge_syncing"]:
        return 1.2
    summary = snapshot["summary"]
    if summary.get("coding_now_count") or summary.get("dirty_worktrees"):
        return 4.0
    return 8.0 if summary.get("active_worktrees") else 15.0


# These fields describe a scan or repeat information derived from the activity
# timestamp. The actual commit, last activity, activity class and errors count.
_SCAN_FIELDS = {
    "generated_at", "last_seen_at", "last_synced_at", "idle_seconds",
    "last_active_ago", "pulse_summary", "forge_syncing", "syncing_repos",
}


def _content(value: Any) -> Any:
    if isinstance(value, list):
        return [_content(item) for item in value]
    if isinstance(value, dict):
        return {
            # Finishing the first remote scan matters even for an empty repo.
            key: bool(item) if key == "forge_fetched_at" else _content(item)
            for key, item in value.items() if key not in _SCAN_FIELDS
        }
    return value


class BoardEvents:
    """One on-demand sampler; slow subscribers take the newest complete frame."""

    def __init__(self, collect: Callable[[], bytes], *, heartbeat: float = 10.0) -> None:
        self._collect = collect
        self._heartbeat = heartbeat
        self._changed = threading.Condition()
        self._subscribers = 0
        self._running = False
        self._closed = False
        self._request = 0
        self._version = 0
        self._frame = b""
        self._content: object = None

    def invalidate(self) -> None:
        with self._changed:
            self._request += 1
            self._changed.notify_all()

    def close(self) -> None:
        with self._changed:
            self._closed = True
            self._changed.notify_all()

    def _sample(self) -> None:
        while True:
            with self._changed:
                if self._closed or not self._subscribers:
                    self._running = False
                    return
                request = self._request
            try:
                body = self._collect()
                snapshot = json.loads(body)
                delay = sample_interval(snapshot)
                content = _content(snapshot)
                frame = b"event: snapshot\ndata: " + body + b"\n\n"
            except Exception as exc:
                content = str(exc)
                delay = 4.0
                error = json.dumps(content, ensure_ascii=False).encode("utf-8")
                frame = b"event: snapshot-error\ndata: " + error + b"\n\n"
            with self._changed:
                if request != self._request or not self._subscribers or self._closed:
                    continue
                self._frame = frame
                if self._content != content:
                    self._content = content
                    self._version += 1
                    self._changed.notify_all()
                self._changed.wait_for(
                    lambda: request != self._request or not self._subscribers or self._closed,
                    timeout=delay,
                )

    def frames(self) -> Iterator[bytes]:
        version = -1
        with self._changed:
            if self._closed:
                return
            self._subscribers += 1
            if not self._running:
                self._running = True
                threading.Thread(target=self._sample, name="idd-board-events", daemon=True).start()
        try:
            while True:
                with self._changed:
                    self._changed.wait_for(
                        lambda: self._closed or (self._frame and version != self._version),
                        timeout=self._heartbeat,
                    )
                    if self._closed:
                        return
                    if self._frame and version != self._version:
                        version = self._version
                        frame = self._frame
                    else:
                        frame = b": keep-alive\n\n"
                yield frame
        finally:
            with self._changed:
                self._subscribers -= 1
                if not self._subscribers:
                    self._frame = b""
                    self._content = None
                    self._request += 1
                    self._changed.notify_all()
