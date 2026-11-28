#!/usr/bin/env python3
"""Local HTTP server and hot-reloading HTML prototype workbench for `idd preview`."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import hashlib
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import mimetypes
import os
from pathlib import Path
import re
import sys
import threading
import urllib.parse
import webbrowser

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from local_http import LocalHTTPServer, LocalRequestHandler
from version import get_version  # noqa: E402


DEFAULT_PREVIEW_PORT = 17891
HTML_EXTENSIONS = (".html", ".htm")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

EXTRA_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
}

class PreviewError(RuntimeError):
    """Raised when `idd preview` receives invalid targets or cannot bind."""


def _extract_html_title(path: Path) -> str | None:
    """Extract and sanitize `<title>` from the first 16 KiB of an HTML file."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(16384).decode("utf-8", errors="replace")
    except OSError:
        return None
    match = TITLE_RE.search(chunk)
    if not match:
        return None
    cleaned = " ".join(html.unescape(match.group(1)).split())
    return cleaned or None


def _guess_content_type(path: Path) -> str:
    """Resolve Content-Type for static preview assets."""
    ext = path.suffix.lower()
    if ext in EXTRA_MIME_TYPES:
        return EXTRA_MIME_TYPES[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def parse_target_spec(raw: str) -> tuple[str | None, Path]:
    """Parse `<path>` or `<label>=<path>` and verify the initial target exists."""
    text = raw.strip()
    if not text:
        raise PreviewError("预览目标路径不能为空。")

    direct_path = Path(text).expanduser()
    if "=" in text and not direct_path.exists():
        left, right = text.split("=", 1)
        label = left.strip()
        right_str = right.strip()
        if label and right_str and "/" not in label and "\\" not in label and ":" not in label:
            candidate = Path(right_str).expanduser()
            if not candidate.exists():
                raise PreviewError(f"找不到预览目标文件或目录：{right_str}")
            resolved = candidate.resolve()
            if not resolved.is_file() and not resolved.is_dir():
                raise PreviewError(f"不支持的预览目标类型：{right_str}")
            return label, resolved

    if not direct_path.exists():
        raise PreviewError(f"找不到预览目标文件或目录：{text}")
    resolved = direct_path.resolve()
    if not resolved.is_file() and not resolved.is_dir():
        raise PreviewError(f"不支持的预览目标类型：{text}")
    return None, resolved


@dataclass(frozen=True)
class _TargetSource:
    """Normalized source entry registered in `PreviewRegistry`."""

    source_id: str
    kind: str  # "file" or "dir"
    path: Path
    explicit_label: str | None = None


class PreviewRegistry:
    """Track explicit HTML files and watched directories for live preview."""

    def __init__(
        self,
        targets: list[str],
        *,
        title: str | None = None,
        compare_default: bool = False,
    ) -> None:
        if not targets:
            raise PreviewError("请至少提供一个 HTML 文件或目录作为预览目标。")

        self.sources: list[_TargetSource] = []
        seen_file_paths: set[Path] = set()
        seen_dir_paths: set[Path] = set()
        file_idx = 0
        dir_idx = 0

        for raw in targets:
            explicit_label, resolved = parse_target_spec(raw)
            if resolved.is_dir():
                if resolved in seen_dir_paths:
                    continue
                seen_dir_paths.add(resolved)
                dir_idx += 1
                self.sources.append(
                    _TargetSource(
                        source_id=f"d{dir_idx}",
                        kind="dir",
                        path=resolved,
                        explicit_label=explicit_label,
                    )
                )
            else:
                if resolved in seen_file_paths:
                    continue
                seen_file_paths.add(resolved)
                file_idx += 1
                self.sources.append(
                    _TargetSource(
                        source_id=f"f{file_idx}",
                        kind="file",
                        path=resolved,
                        explicit_label=explicit_label,
                    )
                )

        self.title = (title or "").strip() or "IDD 原型预览"
        self.compare_default = compare_default
        self._lock = threading.Lock()
        self._id_to_path: dict[str, Path] = {}

    def _build_item(self, item_id: str, path: Path, explicit_label: str | None = None) -> dict[str, object]:
        exists = path.is_file()
        mtime_ns = 0
        size = 0
        extracted_title: str | None = None
        if exists:
            try:
                st = path.stat()
                mtime_ns = st.st_mtime_ns
                size = st.st_size
            except OSError:
                exists = False
        if exists and explicit_label is None:
            extracted_title = _extract_html_title(path)

        label = explicit_label or extracted_title or path.stem or path.name
        return {
            "id": item_id,
            "label": label,
            "filename": path.name,
            "path": str(path),
            "exists": exists,
            "mtime_ns": mtime_ns,
            "size": size,
            "raw_url": f"/raw/{item_id}/",
        }

    def snapshot(self) -> dict[str, object]:
        """Collect current metadata for all registered files and watched directories."""
        items: list[dict[str, object]] = []
        id_map: dict[str, Path] = {}
        seen_paths: set[Path] = set()

        for src in self.sources:
            if src.kind == "file":
                seen_paths.add(src.path)
                id_map[src.source_id] = src.path
                items.append(self._build_item(src.source_id, src.path, src.explicit_label))
                continue

            if not src.path.is_dir():
                continue
            try:
                entries = sorted(src.path.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                entries = []
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.suffix.lower() not in HTML_EXTENSIONS:
                    continue
                try:
                    resolved_entry = entry.resolve()
                except OSError:
                    continue
                if not resolved_entry.is_file():
                    continue
                if not resolved_entry.is_relative_to(src.path):
                    continue
                if resolved_entry in seen_paths:
                    continue
                seen_paths.add(resolved_entry)
                digest = hashlib.sha1(entry.name.encode("utf-8")).hexdigest()[:10]
                item_id = f"{src.source_id}_{digest}"
                id_map[item_id] = resolved_entry
                items.append(self._build_item(item_id, resolved_entry, None))

        with self._lock:
            self._id_to_path = id_map

        sig_parts = [
            f"{it['id']}:{it['exists']}:{it['mtime_ns']}:{it['size']}:{it['label']}"
            for it in items
        ]
        version_token = hashlib.sha1("|".join(sig_parts).encode("utf-8")).hexdigest()[:12]

        return {
            "title": self.title,
            "compare_default": self.compare_default,
            "version_token": version_token,
            "items": items,
            "watched_dirs": [str(s.path) for s in self.sources if s.kind == "dir"],
        }

    def resolve_item(self, item_id: str) -> Path | None:
        """Return the registered file path for `item_id`, refreshing snapshot if needed."""
        with self._lock:
            found = self._id_to_path.get(item_id)
        if found is not None:
            return found
        self.snapshot()
        with self._lock:
            return self._id_to_path.get(item_id)

    def resolve_asset(self, item_id: str, relpath: str) -> tuple[Path | None, bool]:
        """Resolve a relative static asset next to `item_id`, blocking directory escape.

        Returns `(resolved_path, forbidden)`.
        """
        html_path = self.resolve_item(item_id)
        if html_path is None:
            return None, False

        decoded = urllib.parse.unquote(relpath).replace("\\", "/")
        if not decoded or decoded.startswith("/") or "\x00" in decoded:
            return None, True

        parts = [p for p in decoded.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            return None, True

        base_dir = html_path.parent.resolve()
        try:
            candidate = (base_dir / "/".join(parts)).resolve()
        except OSError:
            return None, True

        if not candidate.is_relative_to(base_dir):
            return None, True
        if not candidate.is_file():
            return None, False
        return candidate, False


PREVIEW_HTML = (SCRIPT_DIR / "web" / "preview.html").read_text(encoding="utf-8")


class PreviewRequestHandler(LocalRequestHandler):
    """Serve the IDD prototype workbench, metadata API, and sandboxed raw HTML files."""

    def __init__(
        self,
        *args: object,
        registry: PreviewRegistry,
        version: str,
        **kwargs: object,
    ) -> None:
        self.registry = registry
        self.version = version
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            rendered = (
                PREVIEW_HTML.replace("__IDD_VERSION__", html.escape(self.version))
                .replace("__PREVIEW_TITLE__", html.escape(self.registry.title))
                .replace("__DEFAULT_COMPARE__", "true" if self.registry.compare_default else "false")
            )
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", rendered.encode("utf-8"))
            return

        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "version": self.version})
            return

        if path == "/api/meta":
            self._send_json(HTTPStatus.OK, self.registry.snapshot())
            return

        if path.startswith("/raw/"):
            rest = path[len("/raw/") :]
            if not rest:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            if "/" in rest:
                item_id, relpath = rest.split("/", 1)
            else:
                item_id, relpath = rest, ""

            if not item_id:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            if not relpath:
                target = self.registry.resolve_item(item_id)
                if target is None or not target.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "preview file missing", "id": item_id})
                    return
                try:
                    data = target.read_bytes()
                except OSError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "preview file unreadable", "id": item_id})
                    return
                self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", data)
                return

            asset_path, forbidden = self.registry.resolve_asset(item_id, relpath)
            if forbidden:
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden path"})
                return
            if asset_path is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "asset not found"})
                return
            try:
                data = asset_path.read_bytes()
            except OSError:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "asset unreadable"})
                return
            self._send_bytes(HTTPStatus.OK, _guess_content_type(asset_path), data)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


def _bind_preview_server(
    host: str,
    port: int | None,
    handler_cls: type[BaseHTTPRequestHandler],
) -> LocalHTTPServer:
    if port is None:
        try:
            return LocalHTTPServer((host, DEFAULT_PREVIEW_PORT), handler_cls)
        except OSError:
            return LocalHTTPServer((host, 0), handler_cls)
    try:
        return LocalHTTPServer((host, port), handler_cls)
    except OSError as exc:
        raise PreviewError(f"无法监听 {host}:{port}（{exc}）") from exc


def run_preview_server(
    targets: list[str],
    *,
    title: str | None = None,
    compare: bool = False,
    host: str = "127.0.0.1",
    port: int | None = None,
    no_open: bool = False,
    version: str | None = None,
) -> int:
    """Start the local IDD prototype preview server and open the browser unless disabled."""
    registry = PreviewRegistry(targets, title=title, compare_default=compare)
    snap = registry.snapshot()
    resolved_version = version if version is not None else get_version()
    handler_cls = partial(PreviewRequestHandler, registry=registry, version=resolved_version)
    server = _bind_preview_server(host, port, handler_cls)  # type: ignore[arg-type]

    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in ("0.0.0.0", "") else str(actual_host)
    url = f"http://{display_host}:{actual_port}"

    mode_note = "（并排对比）" if compare else ""
    print(f"IDD 原型预览已启动{mode_note}：{url} （按 Ctrl+C 停止）", flush=True)
    for idx, item in enumerate(snap["items"], start=1):  # type: ignore[arg-type]
        print(f"  [{idx}] {item['label']}  {item['path']}", flush=True)
    for wdir in snap["watched_dirs"]:  # type: ignore[attr-defined]
        print(f"  [dir] 监听目录：{wdir}", flush=True)

    if not no_open and os.environ.get("IDD_NO_BROWSER") != "1":
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
