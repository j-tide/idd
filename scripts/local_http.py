"""Response writing and disconnect handling for the local IDD HTTP servers."""

from __future__ import annotations

import errno
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys


def load_page_template(filename: str) -> str:
    """Inline the shared CSS declarations so each HTTP response remains self-contained."""
    web = Path(__file__).with_name("web")
    template = (web / filename).read_text(encoding="utf-8")
    motion = (web / "motion-properties.css.inc").read_text(encoding="utf-8")
    return template.replace("/* IDD shared motion properties */\n", motion)


_CLIENT_DISCONNECT_ERRNOS = frozenset(
    code
    for code in (
        errno.EPIPE,
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.ESHUTDOWN,
        getattr(errno, "EPROTOTYPE", None),
    )
    if code is not None
)


def _is_client_disconnect(exc: BaseException) -> bool:
    """Return True when `exc` indicates the HTTP client closed the socket early."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in _CLIENT_DISCONNECT_ERRNOS


class LocalHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server configured for clean local port reuse and shutdown."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: object, client_address: object) -> None:
        _, exc, _ = sys.exc_info()
        if exc is not None and _is_client_disconnect(exc):
            return
        super().handle_error(request, client_address)


class LocalRequestHandler(BaseHTTPRequestHandler):
    """Write no-store responses and close quietly when the client disconnects."""

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_bytes(self, status: HTTPStatus, content_type: str, payload: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except OSError as exc:
            if _is_client_disconnect(exc):
                self.close_connection = True
                return
            raise

    def _send_json(self, status: HTTPStatus, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)
