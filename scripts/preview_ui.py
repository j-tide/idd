#!/usr/bin/env python3
"""Local HTTP server and hot-reloading HTML prototype workbench for `idd preview`."""

from __future__ import annotations

from dataclasses import dataclass
import errno
from functools import partial
import hashlib
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
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


class PreviewError(RuntimeError):
    """Raised when `idd preview` receives invalid targets or cannot bind."""


def _is_client_disconnect(exc: BaseException) -> bool:
    """Return True when `exc` indicates the HTTP client closed the socket early."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in _CLIENT_DISCONNECT_ERRNOS


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


PREVIEW_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__PREVIEW_TITLE__</title>
  <style>
    :root {
      --bg-app: #111417;
      --bg-panel: #161a1e;
      --bg-card: #1c2025;
      --bg-well: #13161a;
      --bg-hover: rgba(255, 255, 255, 0.06);
      --border: rgba(255, 255, 255, 0.085);
      --border-strong: rgba(255, 255, 255, 0.16);
      --text: #f3f4f6;
      --text-dim: #9ca3af;
      --text-faint: #6b7280;
      --accent: #60a5fa;
      --accent-soft: rgba(96, 165, 250, 0.13);
      --accent-ring: rgba(96, 165, 250, 0.30);
      --green: #4ade80;
      --green-soft: rgba(74, 222, 128, 0.13);
      --amber: #fbbf24;
      --amber-soft: rgba(251, 191, 36, 0.13);
      --red: #f87171;
      --red-soft: rgba(248, 113, 113, 0.13);
      --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "PingFang SC", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
      --ease-spring: cubic-bezier(0.32, 0.72, 0, 1);
      --ease-in-out: cubic-bezier(0.42, 0, 0.2, 1);
      --ease-snap: cubic-bezier(0.2, 0, 0, 1);
      --dur-press: 90ms;
      --dur-micro: 150ms;
      --dur-state: 220ms;
      --dur-surface: 300ms;
      --dur-exit: 180ms;
      --dur-data: 360ms;
      --shadow-pill: 0 1px 4px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(255, 255, 255, 0.08);
    }
    html[data-theme="light"] {
      --bg-app: #eceef2;
      --bg-panel: #f6f7f9;
      --bg-card: #ffffff;
      --bg-well: #f1f3f6;
      --bg-hover: rgba(15, 23, 42, 0.055);
      --border: rgba(15, 23, 42, 0.09);
      --border-strong: rgba(15, 23, 42, 0.18);
      --text: #111827;
      --text-dim: #4b5563;
      --text-faint: #6b7280;
      --accent: #0284c7;
      --accent-soft: rgba(2, 132, 199, 0.10);
      --accent-ring: rgba(2, 132, 199, 0.28);
      --green: #059669;
      --green-soft: rgba(5, 150, 105, 0.10);
      --amber: #d97706;
      --amber-soft: rgba(217, 119, 6, 0.10);
      --red: #dc2626;
      --red-soft: rgba(220, 38, 38, 0.10);
      --shadow-pill: 0 1px 3px rgba(15, 23, 42, 0.10), 0 0 0 1px rgba(15, 23, 42, 0.06);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: var(--sans);
      background: var(--bg-app);
      color: var(--text);
      font-size: 13px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
    }
    html.theme-transitioning body,
    html.theme-transitioning .topbar,
    html.theme-transitioning .stage,
    html.theme-transitioning .pane,
    html.theme-transitioning .pane-head,
    html.theme-transitioning .badge,
    html.theme-transitioning .btn,
    html.theme-transitioning .tab-btn,
    html.theme-transitioning .seg,
    html.theme-transitioning .seg-indicator,
    html.theme-transitioning .toast {
      transition: background-color 240ms var(--ease-in-out), color 240ms var(--ease-in-out), border-color 240ms var(--ease-in-out) !important;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 14px;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      flex-shrink: 0;
    }
    .group {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 13.5px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 11.5px;
      font-weight: 500;
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-dim);
      transition: border-color var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), background-color var(--dur-micro) var(--ease-snap);
    }
    .dot {
      position: relative;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--green);
      color: var(--green);
      flex-shrink: 0;
      transition: background-color var(--dur-state) var(--ease-in-out);
    }
    .dot::after {
      content: "";
      position: absolute;
      inset: 0;
      border-radius: 50%;
      background: currentColor;
      opacity: 0;
      pointer-events: none;
    }
    .dot.is-live::after { animation: pulseRing 2.1s var(--ease-out) infinite; }
    .dot.warn { background: var(--amber); color: var(--amber); }
    .dot.err { background: var(--red); color: var(--red); }
    @keyframes pulseRing {
      0% { transform: scale(1); opacity: 0.55; }
      70%, 100% { transform: scale(2.25); opacity: 0; }
    }
    .tabs {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px;
      border-radius: 9px;
      background: var(--bg-well);
      border: 1px solid var(--border);
      flex-wrap: wrap;
    }
    .tabs:empty { display: none; }
    .tab-btn, .btn, select.picker {
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-dim);
      padding: 4px 10px;
      border-radius: 7px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-family: inherit;
      position: relative;
      z-index: 1;
      transition: background-color var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), opacity var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .tabs .tab-btn {
      border-color: transparent;
      background: transparent;
      padding: 3px 9px;
    }
    .tab-btn:hover:not(:disabled), .btn:hover:not(:disabled) {
      color: var(--text);
      border-color: var(--border-strong);
      background: var(--bg-hover);
    }
    .tabs .tab-btn:hover:not(:disabled) {
      border-color: transparent;
      background: rgba(255, 255, 255, 0.04);
    }
    html[data-theme="light"] .tabs .tab-btn:hover:not(:disabled) {
      background: rgba(15, 23, 42, 0.04);
    }
    .tab-btn:active:not(:disabled), .btn:active:not(:disabled), select.picker:active:not(:disabled) {
      transform: scale(0.97);
      transition-duration: var(--dur-press);
    }
    .tab-btn:focus-visible, .btn:focus-visible, select.picker:focus-visible {
      outline: 2px solid var(--accent-ring);
      outline-offset: 2px;
    }
    .tab-btn.active, .btn.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: var(--accent);
      font-weight: 600;
    }
    .tabs.has-indicator .tab-btn.active {
      background: transparent;
      border-color: transparent;
      color: var(--text);
    }
    .btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .btn svg, .tab-btn svg { flex-shrink: 0; }
    .btn.spin-once svg { animation: spinOnce 380ms var(--ease-out); }
    .btn.icon-pop svg { animation: iconPop 220ms var(--ease-spring) both; }
    @keyframes spinOnce { to { transform: rotate(360deg); } }
    @keyframes iconPop {
      0% { transform: scale(0.74); opacity: 0.55; }
      65% { transform: scale(1.12); opacity: 1; }
      100% { transform: scale(1); opacity: 1; }
    }
    .seg {
      position: relative;
      display: inline-flex;
      gap: 4px;
      padding: 2px;
      background: var(--bg-well);
      border: 1px solid var(--border);
      border-radius: 8px;
    }
    .seg .btn {
      border-color: transparent;
      background: transparent;
      padding: 3px 8px;
    }
    .seg .btn.active {
      background: var(--bg-card);
      color: var(--accent);
      border-color: var(--border-strong);
    }
    .seg.has-indicator .btn.active {
      background: transparent;
      border-color: transparent;
      color: var(--accent);
    }
    .seg-indicator {
      position: absolute;
      top: 0;
      left: 0;
      border-radius: 6px;
      background: var(--bg-card);
      box-shadow: var(--shadow-pill);
      pointer-events: none;
      z-index: 0;
      transition: transform var(--dur-state) var(--ease-spring), width var(--dur-state) var(--ease-spring), height var(--dur-state) var(--ease-spring), opacity var(--dur-micro) var(--ease-out);
    }
    .stage {
      flex: 1;
      min-height: 0;
      padding: 14px;
      background: var(--bg-well);
      display: flex;
      justify-content: center;
      align-items: stretch;
      gap: 14px;
      overflow: auto;
      position: relative;
    }
    .stage.is-compare { gap: 0; }
    .stage.is-dragging { user-select: none; cursor: col-resize; }
    .stage.is-dragging iframe.canvas { pointer-events: none; }
    .stage.is-dragging .pane { transition: none !important; }
    .pane {
      position: relative;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: 11px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      min-width: 280px;
      min-height: 0;
      width: 100%;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.22);
      transition: width var(--dur-surface) var(--ease-spring), opacity var(--dur-state) var(--ease-out);
    }
    .pane.pane-enter { animation: paneEnter var(--dur-state) var(--ease-out) both; }
    @keyframes paneEnter {
      from { opacity: 0; transform: translate3d(0, 8px, 0) scale(0.99); }
      to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
    }
    .pane-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 7px 11px;
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border);
      font-size: 11.5px;
      color: var(--text-dim);
      flex-shrink: 0;
    }
    .pane-title {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .pane-path {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-faint);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 44vw;
    }
    .pane-body {
      flex: 1;
      min-height: 0;
      position: relative;
      background: #ffffff;
    }
    .pane-load-bar {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
      z-index: 6;
      pointer-events: none;
      opacity: 0;
      background: linear-gradient(90deg, transparent, var(--accent), transparent);
      transform: translate3d(-100%, 0, 0);
      transition: opacity var(--dur-micro) var(--ease-out);
    }
    .pane-body.is-loading .pane-load-bar {
      opacity: 1;
      animation: paneLoadSlide 1.05s var(--ease-in-out) infinite;
    }
    @keyframes paneLoadSlide {
      0% { transform: translate3d(-100%, 0, 0); }
      100% { transform: translate3d(100%, 0, 0); }
    }
    iframe.canvas {
      border: 0;
      width: 100%;
      height: 100%;
      display: block;
      background: #ffffff;
      opacity: 1;
      transition: opacity var(--dur-micro) var(--ease-out);
    }
    .pane-body.is-loading iframe.canvas { opacity: 0.78; }
    .split-handle {
      width: 14px;
      flex-shrink: 0;
      cursor: col-resize;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: none;
      position: relative;
      z-index: 4;
    }
    .split-handle::after {
      content: "";
      width: 4px;
      height: 44px;
      border-radius: 999px;
      background: var(--border-strong);
      opacity: 0.55;
      transition: opacity var(--dur-micro) var(--ease-snap), background-color var(--dur-micro) var(--ease-snap), height var(--dur-micro) var(--ease-snap);
    }
    .split-handle:hover::after,
    .stage.is-dragging .split-handle::after {
      opacity: 1;
      height: 60px;
      background: var(--accent);
    }
    .pane-resize-handle {
      position: absolute;
      top: 44px;
      right: 0;
      bottom: 8px;
      width: 10px;
      cursor: ew-resize;
      z-index: 8;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: none;
    }
    .pane-resize-handle::after {
      content: "";
      width: 3px;
      height: 36px;
      border-radius: 999px;
      background: var(--border-strong);
      opacity: 0;
      transition: opacity var(--dur-micro) var(--ease-snap), background-color var(--dur-micro) var(--ease-snap), height var(--dur-micro) var(--ease-snap);
    }
    .pane-resize-handle:hover::after,
    .stage.is-dragging .pane-resize-handle::after {
      opacity: 1;
      height: 52px;
      background: var(--accent);
    }
    .drag-badge {
      position: fixed;
      top: 58px;
      left: 50%;
      transform: translate3d(-50%, -4px, 0) scale(0.96);
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      color: var(--text);
      font-family: var(--mono);
      font-size: 11.5px;
      font-weight: 600;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.32);
      opacity: 0;
      pointer-events: none;
      z-index: 60;
      transition: opacity var(--dur-micro) var(--ease-out), transform var(--dur-micro) var(--ease-spring);
    }
    .drag-badge.show {
      opacity: 1;
      transform: translate3d(-50%, 0, 0) scale(1);
    }
    .empty-box {
      width: 100%;
      height: 100%;
      min-height: 280px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 28px;
      background: var(--bg-card);
      color: var(--text-dim);
      gap: 8px;
      animation: fadeSlideIn var(--dur-state) var(--ease-out) both;
    }
    @keyframes fadeSlideIn {
      from { opacity: 0; transform: translate3d(0, 6px, 0); }
      to { opacity: 1; transform: translate3d(0, 0, 0); }
    }
    .empty-box code {
      font-family: var(--mono);
      font-size: 12px;
      padding: 4px 10px;
      border-radius: 6px;
      background: var(--bg-well);
      border: 1px solid var(--border);
      color: var(--text);
      word-break: break-all;
    }
    .toast {
      position: fixed;
      right: 16px;
      bottom: 16px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 8px 13px;
      border-radius: 10px;
      background: var(--bg-card);
      border: 1px solid var(--green);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
      opacity: 0;
      transform: translate3d(0, 12px, 0) scale(0.96);
      transition: opacity var(--dur-state) var(--ease-out), transform var(--dur-state) var(--ease-spring), border-color var(--dur-micro) var(--ease-snap);
      pointer-events: none;
      z-index: 40;
    }
    .toast.is-warn { border-color: var(--amber); }
    .toast.is-err { border-color: var(--red); }
    .toast.show { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
    .toast.is-bump { transform: translate3d(0, -2px, 0) scale(1.02); }
    .toast.is-leaving {
      opacity: 0;
      transform: translate3d(0, -4px, 0) scale(0.98);
      transition: opacity var(--dur-exit) var(--ease-out), transform var(--dur-exit) var(--ease-out);
    }
    @media (max-width: 768px) {
      .stage.is-compare { flex-direction: column; gap: 12px; }
      .split-handle, .pane-resize-handle { display: none; }
      .pane { min-width: 0; width: 100% !important; flex: 1 1 auto !important; min-height: 260px; }
      .pane-path { max-width: 50vw; }
      .toast { left: 12px; right: 12px; justify-content: center; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
      .dot::after,
      .pane-load-bar,
      .btn.spin-once svg {
        animation: none !important;
      }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="group">
      <div class="brand">
        <span id="appTitle">__PREVIEW_TITLE__</span>
        <span class="badge" style="font-family: var(--mono);">idd v__IDD_VERSION__</span>
      </div>
      <span class="badge" id="statusBadge">
        <span class="dot is-live" id="statusDot"></span>
        <span id="statusText">Live</span>
      </span>
      <nav class="tabs" id="tabBar"></nav>
    </div>

    <div class="group">
      <button class="btn" id="compareBtn" title="并排对比两个方案 (c)"></button>
      <div class="seg" id="viewportGroup">
        <button class="btn active" data-vp="100%">100%</button>
        <button class="btn" data-vp="1280px">桌面</button>
        <button class="btn" data-vp="768px">平板</button>
        <button class="btn" data-vp="390px">手机</button>
      </div>
      <button class="btn" id="reloadBtn" title="强制刷新当前画布 (r)"></button>
      <button class="btn" id="openRawBtn" title="在新标签页打开原始 HTML"></button>
      <button class="btn" id="themeBtn"></button>
    </div>
  </header>

  <main class="stage" id="stage"></main>
  <div class="drag-badge" id="dragBadge" aria-hidden="true"></div>
  <div class="toast" id="toast" aria-live="polite"></div>

  <script>
    (() => {
      const DEFAULT_COMPARE = __DEFAULT_COMPARE__;
      const THEME_KEY = "idd_preview_theme";

      const ICONS = {
        columns: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="12" y1="3" x2="12" y2="21"/>',
        refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
        externalLink: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
        sun: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
        moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
        checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
        alertTriangle: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
      };

      function icon(name, size) {
        const s = size || 13;
        return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || "") + "</svg>";
      }

      function prefersReducedMotion() {
        return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
      }

      const state = {
        items: [],
        activeId: null,
        compare: Boolean(DEFAULT_COMPARE),
        leftId: null,
        rightId: null,
        viewport: "100%",
        splitRatio: 50,
        lastById: new Map(),
        indicatorRects: new Map(),
        versionToken: "",
        offline: false,
        statusIdle: false,
        statusRevertTimer: null,
      };

      const el = {
        appTitle: document.getElementById("appTitle"),
        statusDot: document.getElementById("statusDot"),
        statusText: document.getElementById("statusText"),
        tabBar: document.getElementById("tabBar"),
        compareBtn: document.getElementById("compareBtn"),
        viewportGroup: document.getElementById("viewportGroup"),
        reloadBtn: document.getElementById("reloadBtn"),
        openRawBtn: document.getElementById("openRawBtn"),
        themeBtn: document.getElementById("themeBtn"),
        stage: document.getElementById("stage"),
        dragBadge: document.getElementById("dragBadge"),
        toast: document.getElementById("toast"),
      };

      el.compareBtn.innerHTML = icon("columns", 13) + "<span>A/B 并排对比</span>";
      el.reloadBtn.innerHTML = icon("refresh", 13) + "<span>刷新</span>";
      el.openRawBtn.innerHTML = icon("externalLink", 13) + "<span>新窗口</span>";

      function syncSlidingIndicator(container, activeSelector, key) {
        if (!container) return;
        const activeEl = container.querySelector(activeSelector);
        let ind = null;
        for (const ch of container.children) {
          if (ch.classList && ch.classList.contains("seg-indicator")) {
            ind = ch;
            break;
          }
        }
        if (!activeEl) {
          if (ind) ind.style.opacity = "0";
          return;
        }
        const target = {
          x: activeEl.offsetLeft,
          y: activeEl.offsetTop,
          w: activeEl.offsetWidth,
          h: activeEl.offsetHeight
        };
        if (target.w === 0 && target.h === 0) return;
        if (!ind) {
          ind = document.createElement("span");
          ind.className = "seg-indicator";
          ind.setAttribute("aria-hidden", "true");
          container.insertBefore(ind, container.firstChild);
        }
        container.classList.add("has-indicator");
        ind.style.opacity = "1";
        const applyRect = (r) => {
          ind.style.width = r.w + "px";
          ind.style.height = r.h + "px";
          ind.style.transform = "translate3d(" + r.x + "px," + r.y + "px,0)";
        };
        const prev = state.indicatorRects.get(key);
        const changed = prev && (prev.x !== target.x || prev.y !== target.y || prev.w !== target.w || prev.h !== target.h);
        if (prev && changed && !prefersReducedMotion()) {
          ind.style.transition = "none";
          applyRect(prev);
          void ind.offsetWidth;
          ind.style.transition = "";
          applyRect(target);
        } else {
          ind.style.transition = "none";
          applyRect(target);
          void ind.offsetWidth;
          ind.style.transition = "";
        }
        state.indicatorRects.set(key, target);
      }

      function syncAllIndicators() {
        syncSlidingIndicator(el.viewportGroup, "button.active", "viewport");
        syncSlidingIndicator(el.tabBar, ".tab-btn.active", "tabs");
      }

      function showToast(msg, kind) {
        const tone = kind === "err" ? "err" : (kind === "warn" ? "warn" : "ok");
        const ic = tone === "ok" ? icon("checkCircle", 13) : icon("alertTriangle", 13);
        const icColor = tone === "err" ? "var(--red)" : (tone === "warn" ? "var(--amber)" : "var(--green)");
        const wasVisible = el.toast.classList.contains("show");
        el.toast.className = "toast" + (tone === "err" ? " is-err" : (tone === "warn" ? " is-warn" : ""));
        el.toast.innerHTML = '<span style="color:' + icColor + ';display:inline-flex;">' + ic + "</span><span>" + msg.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</span>";
        if (wasVisible && !prefersReducedMotion()) {
          el.toast.classList.add("show", "is-bump");
          setTimeout(() => el.toast.classList.remove("is-bump"), 140);
        } else {
          requestAnimationFrame(() => el.toast.classList.add("show"));
        }
        clearTimeout(window.__iddPreviewToastTimer);
        window.__iddPreviewToastTimer = setTimeout(() => {
          el.toast.classList.remove("show", "is-bump");
          el.toast.classList.add("is-leaving");
        }, 2200);
      }

      function applyTheme(theme, animate) {
        const next = theme === "light" ? "light" : "dark";
        if (animate && !prefersReducedMotion()) {
          document.documentElement.classList.add("theme-transitioning");
          clearTimeout(window.__iddPreviewThemeTimer);
          window.__iddPreviewThemeTimer = setTimeout(() => {
            document.documentElement.classList.remove("theme-transitioning");
          }, 270);
        }
        document.documentElement.setAttribute("data-theme", next);
        el.themeBtn.innerHTML = icon(next === "dark" ? "sun" : "moon", 13) + "<span>" + (next === "dark" ? "浅色" : "深色") + "</span>";
        if (animate && !prefersReducedMotion()) {
          el.themeBtn.classList.remove("icon-pop");
          void el.themeBtn.offsetWidth;
          el.themeBtn.classList.add("icon-pop");
        }
        try { localStorage.setItem(THEME_KEY, next); } catch (_) {}
      }

      function setStatus(mode, text) {
        el.statusDot.className = "dot" + (mode === "warn" ? " warn" : mode === "err" ? " err" : " is-live");
        el.statusText.textContent = text;
      }

      function setDragBadge(text) {
        if (!text) {
          el.dragBadge.classList.remove("show");
          return;
        }
        el.dragBadge.textContent = text;
        el.dragBadge.classList.add("show");
      }

      function syncViewportButtons() {
        const buttons = el.viewportGroup.querySelectorAll("button[data-vp]");
        buttons.forEach((b) => {
          b.classList.toggle("active", !state.compare && b.dataset.vp === state.viewport);
        });
        syncSlidingIndicator(el.viewportGroup, "button.active", "viewport");
      }

      function findItem(id) {
        return state.items.find((it) => it.id === id) || null;
      }

      function reconcileSelection() {
        const ids = state.items.map((it) => it.id);
        if (!ids.length) {
          state.activeId = null;
          state.leftId = null;
          state.rightId = null;
          return;
        }
        if (!state.activeId || !ids.includes(state.activeId)) {
          state.activeId = ids[0];
        }
        if (!state.leftId || !ids.includes(state.leftId)) {
          state.leftId = ids[0];
        }
        if (!state.rightId || !ids.includes(state.rightId)) {
          state.rightId = ids.length > 1 ? ids[1] : ids[0];
        }
      }

      function renderTabs() {
        el.tabBar.innerHTML = "";
        if (!state.compare) {
          for (const item of state.items) {
            const btn = document.createElement("button");
            btn.className = "tab-btn" + (item.id === state.activeId ? " active" : "");
            btn.textContent = item.exists ? item.label : `${item.label} (缺失)`;
            btn.title = item.path;
            btn.addEventListener("click", () => {
              state.activeId = item.id;
              renderTabs();
              renderStage(false);
            });
            el.tabBar.appendChild(btn);
          }
          syncSlidingIndicator(el.tabBar, ".tab-btn.active", "tabs");
        } else {
          state.indicatorRects.delete("tabs");
        }
        const canCompare = state.items.length >= 2;
        el.compareBtn.disabled = !canCompare;
        el.compareBtn.classList.toggle("active", state.compare && canCompare);
        el.openRawBtn.disabled = !state.items.length || !findItem(state.activeId)?.exists;
        syncViewportButtons();
      }

      function makeFrameSrc(item) {
        return `${item.raw_url}?v=${encodeURIComponent(String(item.mtime_ns || 0))}_${encodeURIComponent(String(item.size || 0))}`;
      }

      function loadFrameSrc(body, iframe, src) {
        if (!body || !iframe) return;
        body.classList.add("is-loading");
        clearTimeout(Number(body.dataset.loadTimer || 0));
        const finish = () => {
          body.classList.remove("is-loading");
          clearTimeout(Number(body.dataset.loadTimer || 0));
        };
        iframe.onload = finish;
        iframe.onerror = finish;
        body.dataset.loadTimer = String(setTimeout(finish, 4000));
        iframe.src = src;
      }

      function attachSinglePaneResizer(pane) {
        if (!pane || pane.querySelector(".pane-resize-handle")) return;
        const handle = document.createElement("div");
        handle.className = "pane-resize-handle";
        handle.title = "拖拽调整画布宽度（双击复位 100%）";
        let dragging = false;
        let startX = 0;
        let startW = 0;
        const cleanup = () => {
          if (!dragging) return;
          dragging = false;
          el.stage.classList.remove("is-dragging");
          setDragBadge("");
        };
        handle.addEventListener("pointerdown", (ev) => {
          if (window.innerWidth <= 768) return;
          ev.preventDefault();
          dragging = true;
          startX = ev.clientX;
          startW = pane.getBoundingClientRect().width;
          el.stage.classList.add("is-dragging");
          if (handle.setPointerCapture) {
            try { handle.setPointerCapture(ev.pointerId); } catch (_) {}
          }
          setDragBadge(Math.round(startW) + " px");
        });
        handle.addEventListener("pointermove", (ev) => {
          if (!dragging) return;
          const maxW = Math.max(320, el.stage.clientWidth - 28);
          const nextW = Math.round(Math.max(320, Math.min(maxW, startW + (ev.clientX - startX) * 2)));
          state.viewport = nextW + "px";
          pane.style.width = state.viewport;
          syncViewportButtons();
          setDragBadge(nextW + " px");
        });
        handle.addEventListener("pointerup", cleanup);
        handle.addEventListener("pointercancel", cleanup);
        window.addEventListener("blur", cleanup);
        handle.addEventListener("dblclick", () => {
          state.viewport = "100%";
          pane.style.width = "100%";
          syncViewportButtons();
        });
        pane.appendChild(handle);
      }

      function createSplitHandle(leftPane) {
        const handle = document.createElement("div");
        handle.className = "split-handle";
        handle.title = "拖拽调整分栏比例（双击复位 50/50）";
        let dragging = false;
        const cleanup = () => {
          if (!dragging) return;
          dragging = false;
          el.stage.classList.remove("is-dragging");
          setDragBadge("");
        };
        handle.addEventListener("pointerdown", (ev) => {
          if (window.innerWidth <= 768) return;
          ev.preventDefault();
          dragging = true;
          el.stage.classList.add("is-dragging");
          if (handle.setPointerCapture) {
            try { handle.setPointerCapture(ev.pointerId); } catch (_) {}
          }
          setDragBadge(Math.round(state.splitRatio) + "% / " + Math.round(100 - state.splitRatio) + "%");
        });
        handle.addEventListener("pointermove", (ev) => {
          if (!dragging) return;
          const rect = el.stage.getBoundingClientRect();
          const usable = Math.max(200, rect.width - 28);
          const rawPct = ((ev.clientX - rect.left - 14) / usable) * 100;
          const ratio = Math.max(25, Math.min(75, Math.round(rawPct * 10) / 10));
          state.splitRatio = ratio;
          leftPane.style.width = `calc(${ratio}% - 7px)`;
          setDragBadge(Math.round(ratio) + "% / " + Math.round(100 - ratio) + "%");
        });
        handle.addEventListener("pointerup", cleanup);
        handle.addEventListener("pointercancel", cleanup);
        window.addEventListener("blur", cleanup);
        handle.addEventListener("dblclick", () => {
          state.splitRatio = 50;
          leftPane.style.width = "calc(50% - 7px)";
        });
        return handle;
      }

      function buildPane(slot, itemId, animateEnter) {
        const item = findItem(itemId);
        const pane = document.createElement("section");
        pane.className = "pane" + (animateEnter && !prefersReducedMotion() ? " pane-enter" : "");
        pane.dataset.slot = slot;
        if (slot === "left") {
          pane.style.width = `calc(${state.splitRatio}% - 7px)`;
          pane.style.flex = "0 0 auto";
        } else if (slot === "right") {
          pane.style.width = "auto";
          pane.style.flex = "1 1 0";
        } else {
          pane.style.width = state.viewport;
        }
        pane.style.maxWidth = "100%";

        const head = document.createElement("div");
        head.className = "pane-head";

        const left = document.createElement("div");
        left.className = "pane-title";

        if (state.compare && state.items.length >= 2) {
          const select = document.createElement("select");
          select.className = "picker";
          for (const optItem of state.items) {
            const opt = document.createElement("option");
            opt.value = optItem.id;
            opt.textContent = optItem.label;
            if (optItem.id === itemId) opt.selected = true;
            select.appendChild(opt);
          }
          select.addEventListener("change", (ev) => {
            if (slot === "left") state.leftId = ev.target.value;
            else state.rightId = ev.target.value;
            renderStage(false);
          });
          left.appendChild(select);
        } else {
          const strong = document.createElement("strong");
          strong.style.color = "var(--text)";
          strong.textContent = item ? item.label : "空";
          left.appendChild(strong);
        }

        const pathSpan = document.createElement("span");
        pathSpan.className = "pane-path";
        pathSpan.textContent = item ? item.path : "";
        pathSpan.title = item ? item.path : "";
        left.appendChild(pathSpan);

        const right = document.createElement("div");
        right.className = "group";
        if (item && item.exists) {
          const link = document.createElement("a");
          link.href = item.raw_url;
          link.target = "_blank";
          link.rel = "noopener";
          link.className = "btn";
          link.style.textDecoration = "none";
          link.innerHTML = icon("externalLink", 11) + "<span>原始页</span>";
          right.appendChild(link);
        }

        head.appendChild(left);
        head.appendChild(right);
        pane.appendChild(head);

        const body = document.createElement("div");
        body.className = "pane-body";

        if (!item || !item.exists) {
          const empty = document.createElement("div");
          empty.className = "empty-box";
          empty.innerHTML = `<div style="font-size:16px;font-weight:600;">⚠️ 预览文件暂不可用</div>
            <div>文件已被移除或正在重写，保存回原路径后会自动恢复渲染：</div>`;
          const code = document.createElement("code");
          code.textContent = item ? item.path : "";
          empty.appendChild(code);
          body.appendChild(empty);
        } else {
          const loadBar = document.createElement("div");
          loadBar.className = "pane-load-bar";
          body.appendChild(loadBar);
          const iframe = document.createElement("iframe");
          iframe.className = "canvas";
          iframe.dataset.itemId = item.id;
          iframe.dataset.mtime = String(item.mtime_ns);
          body.appendChild(iframe);
          loadFrameSrc(body, iframe, makeFrameSrc(item));
        }

        pane.appendChild(body);
        if (slot === "single") attachSinglePaneResizer(pane);
        return pane;
      }

      function renderStage(forceRebuild) {
        if (!state.items.length) {
          el.stage.classList.remove("is-compare");
          el.stage.innerHTML = `<div class="pane"><div class="empty-box">
            <div style="font-size:16px;font-weight:600;">暂无可预览的 HTML 文件</div>
            <div>向监听目录写入 <code>.html</code> 文件后会自动出现在此工作台。</div>
          </div></div>`;
          return;
        }

        const isCompare = state.compare && state.items.length >= 2;
        el.stage.classList.toggle("is-compare", isCompare);
        const wanted = isCompare
          ? [
              { slot: "left", id: state.leftId },
              { slot: "right", id: state.rightId },
            ]
          : [{ slot: "single", id: state.activeId }];

        if (!forceRebuild) {
          const existingPanes = Array.from(el.stage.querySelectorAll(".pane"));
          if (existingPanes.length === wanted.length) {
            let canPatchInPlace = true;
            for (let i = 0; i < wanted.length; i++) {
              const pane = existingPanes[i];
              const target = wanted[i];
              const item = findItem(target.id);
              if (pane.dataset.slot !== target.slot) {
                canPatchInPlace = false;
                break;
              }
              const body = pane.querySelector(".pane-body");
              const iframe = pane.querySelector("iframe.canvas");
              if (!item || !item.exists) {
                if (iframe) {
                  canPatchInPlace = false;
                  break;
                }
              } else {
                if (!iframe) {
                  canPatchInPlace = false;
                  break;
                }
                if (target.slot === "left") {
                  pane.style.width = `calc(${state.splitRatio}% - 7px)`;
                } else if (target.slot === "single") {
                  pane.style.width = state.viewport;
                }
                if (iframe.dataset.itemId !== item.id) {
                  iframe.dataset.itemId = item.id;
                  iframe.dataset.mtime = String(item.mtime_ns);
                  const strong = pane.querySelector(".pane-title > strong");
                  if (strong) strong.textContent = item.label;
                  const pathSpan = pane.querySelector(".pane-path");
                  if (pathSpan) {
                    pathSpan.textContent = item.path;
                    pathSpan.title = item.path;
                  }
                  const rawLink = pane.querySelector(".pane-head a.btn");
                  if (rawLink) rawLink.href = item.raw_url;
                  loadFrameSrc(body, iframe, makeFrameSrc(item));
                } else if (iframe.dataset.mtime !== String(item.mtime_ns)) {
                  iframe.dataset.mtime = String(item.mtime_ns);
                  loadFrameSrc(body, iframe, makeFrameSrc(item));
                }
              }
            }
            if (canPatchInPlace) return;
          }
        }

        el.stage.innerHTML = "";
        const built = wanted.map((w) => buildPane(w.slot, w.id, forceRebuild));
        el.stage.appendChild(built[0]);
        if (isCompare && built.length === 2) {
          el.stage.appendChild(createSplitHandle(built[0]));
          el.stage.appendChild(built[1]);
        }
      }

      async function pollMeta(initial) {
        try {
          const res = await fetch("/api/meta", { cache: "no-store" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          state.offline = false;
          if (data.title) {
            el.appTitle.textContent = data.title;
            document.title = data.title;
          }
          const nextItems = Array.isArray(data.items) ? data.items : [];
          const changedLabels = [];
          let missingAny = false;

          for (const it of nextItems) {
            if (!it.exists) missingAny = true;
            const prev = state.lastById.get(it.id);
            if (!initial && prev && (prev.mtime_ns !== it.mtime_ns || prev.size !== it.size || prev.exists !== it.exists)) {
              changedLabels.push(it.label);
            }
            state.lastById.set(it.id, { mtime_ns: it.mtime_ns, size: it.size, exists: it.exists });
          }

          const structureChanged =
            state.items.length !== nextItems.length ||
            state.items.some((oldIt, idx) => oldIt.id !== nextItems[idx]?.id || oldIt.label !== nextItems[idx]?.label);

          state.items = nextItems;
          reconcileSelection();

          if (missingAny) {
            clearTimeout(state.statusRevertTimer);
            setStatus("warn", "部分文件缺失");
            state.statusIdle = false;
          } else if (changedLabels.length) {
            setStatus("ok", "Live · 已热更新");
            state.statusIdle = false;
            clearTimeout(state.statusRevertTimer);
            state.statusRevertTimer = setTimeout(() => {
              if (!state.offline) {
                setStatus("ok", "Live");
                state.statusIdle = true;
              }
            }, 2600);
          } else if (initial || (!state.statusIdle && !state.statusRevertTimer)) {
            setStatus("ok", "Live");
            state.statusIdle = true;
          }

          if (initial || structureChanged || data.version_token !== state.versionToken) {
            state.versionToken = data.version_token || "";
            renderTabs();
            renderStage(initial || structureChanged);
            if (!initial && changedLabels.length) {
              showToast("已热更新：" + changedLabels.join("、"));
            }
          }
        } catch (_) {
          state.offline = true;
          clearTimeout(state.statusRevertTimer);
          state.statusRevertTimer = null;
          setStatus("err", "连接已断开");
        }
      }

      // Wire controls
      try {
        applyTheme(localStorage.getItem(THEME_KEY) || "dark", false);
      } catch (_) {
        applyTheme("dark", false);
      }

      el.themeBtn.addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme");
        applyTheme(cur === "dark" ? "light" : "dark", true);
      });

      function toggleCompare() {
        if (state.items.length < 2) return;
        state.compare = !state.compare;
        renderTabs();
        renderStage(true);
      }

      function selectViewport(vp) {
        state.viewport = vp || "100%";
        if (state.compare) {
          state.compare = false;
          renderTabs();
          renderStage(true);
        } else {
          syncViewportButtons();
          renderStage(false);
        }
      }

      function triggerManualReload() {
        if (!prefersReducedMotion()) {
          el.reloadBtn.classList.remove("spin-once");
          void el.reloadBtn.offsetWidth;
          el.reloadBtn.classList.add("spin-once");
        }
        el.stage.querySelectorAll("iframe.canvas").forEach((iframe) => {
          const item = findItem(iframe.dataset.itemId);
          if (item && item.exists) {
            loadFrameSrc(iframe.parentElement, iframe, `${item.raw_url}?manual=${Date.now()}`);
          }
        });
        showToast("已手动刷新画布");
      }

      el.compareBtn.addEventListener("click", toggleCompare);

      el.viewportGroup.querySelectorAll("button[data-vp]").forEach((btn) => {
        btn.addEventListener("click", () => selectViewport(btn.dataset.vp || "100%"));
      });

      el.reloadBtn.addEventListener("click", triggerManualReload);

      el.openRawBtn.addEventListener("click", () => {
        const item = findItem(state.activeId);
        if (item && item.exists) {
          window.open(item.raw_url, "_blank", "noopener");
        }
      });

      document.addEventListener("keydown", (ev) => {
        const tag = (ev.target && ev.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (ev.target && ev.target.isContentEditable)) return;
        if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
        if (ev.key === "r" || ev.key === "R") {
          ev.preventDefault();
          triggerManualReload();
        } else if (ev.key === "c" || ev.key === "C") {
          ev.preventDefault();
          toggleCompare();
        } else if (ev.key === "1") {
          selectViewport("100%");
        } else if (ev.key === "2") {
          selectViewport("1280px");
        } else if (ev.key === "3") {
          selectViewport("768px");
        } else if (ev.key === "4") {
          selectViewport("390px");
        }
      });

      window.addEventListener("resize", () => {
        clearTimeout(window.__iddPreviewResizeTimer);
        window.__iddPreviewResizeTimer = setTimeout(syncAllIndicators, 80);
      });

      syncViewportButtons();
      pollMeta(true);
      setInterval(() => pollMeta(false), 800);
    })();
  </script>
</body>
</html>
"""


class PreviewHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server configured for clean local port reuse and shutdown."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: object, client_address: object) -> None:
        _, exc, _ = sys.exc_info()
        if exc is not None and _is_client_disconnect(exc):
            return
        super().handle_error(request, client_address)


class PreviewRequestHandler(BaseHTTPRequestHandler):
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

    def _send_json(self, status: HTTPStatus, data: object) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", raw)

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
) -> PreviewHTTPServer:
    if port is None:
        try:
            return PreviewHTTPServer((host, DEFAULT_PREVIEW_PORT), handler_cls)
        except OSError:
            return PreviewHTTPServer((host, 0), handler_cls)
    try:
        return PreviewHTTPServer((host, port), handler_cls)
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
