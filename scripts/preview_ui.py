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
      --green: #4ade80;
      --green-soft: rgba(74, 222, 128, 0.13);
      --amber: #fbbf24;
      --amber-soft: rgba(251, 191, 36, 0.13);
      --red: #f87171;
      --red-soft: rgba(248, 113, 113, 0.13);
      --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "PingFang SC", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
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
      --green: #059669;
      --green-soft: rgba(5, 150, 105, 0.10);
      --amber: #d97706;
      --amber-soft: rgba(217, 119, 6, 0.10);
      --red: #dc2626;
      --red-soft: rgba(220, 38, 38, 0.10);
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
    }
    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 0 3px var(--green-soft);
    }
    .dot.warn { background: var(--amber); box-shadow: 0 0 0 3px var(--amber-soft); }
    .dot.err { background: var(--red); box-shadow: 0 0 0 3px var(--red-soft); }
    .tabs {
      display: flex;
      align-items: center;
      gap: 4px;
      flex-wrap: wrap;
    }
    .tab-btn, .btn, select.picker {
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-dim);
      padding: 4px 10px;
      border-radius: 7px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.12s;
      font-family: inherit;
    }
    .tab-btn:hover, .btn:hover {
      color: var(--text);
      border-color: var(--border-strong);
      background: var(--bg-hover);
    }
    .tab-btn.active, .btn.active {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: var(--accent);
      font-weight: 600;
    }
    .btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .seg {
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
    }
    .pane {
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
      transition: width 0.16s ease;
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
    iframe.canvas {
      border: 0;
      width: 100%;
      height: 100%;
      display: block;
      background: #ffffff;
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
      padding: 8px 13px;
      border-radius: 8px;
      background: var(--bg-card);
      border: 1px solid var(--green);
      color: var(--text);
      font-size: 12px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
      opacity: 0;
      transform: translateY(6px);
      transition: all 0.18s ease;
      pointer-events: none;
      z-index: 40;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
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
        <span class="dot" id="statusDot"></span>
        <span id="statusText">Live</span>
      </span>
      <nav class="tabs" id="tabBar"></nav>
    </div>

    <div class="group">
      <button class="btn" id="compareBtn" title="并排对比两个方案">A/B 并排对比</button>
      <div class="seg" id="viewportGroup">
        <button class="btn active" data-vp="100%">100%</button>
        <button class="btn" data-vp="1280px">桌面</button>
        <button class="btn" data-vp="768px">平板</button>
        <button class="btn" data-vp="390px">手机</button>
      </div>
      <button class="btn" id="reloadBtn" title="强制刷新当前画布">刷新</button>
      <button class="btn" id="openRawBtn" title="在新标签页打开原始 HTML">新窗口</button>
      <button class="btn" id="themeBtn">浅色</button>
    </div>
  </header>

  <main class="stage" id="stage"></main>
  <div class="toast" id="toast"></div>

  <script>
    (() => {
      const DEFAULT_COMPARE = __DEFAULT_COMPARE__;
      const THEME_KEY = "idd_preview_theme";

      const state = {
        items: [],
        activeId: null,
        compare: Boolean(DEFAULT_COMPARE),
        leftId: null,
        rightId: null,
        viewport: "100%",
        lastById: new Map(),
        versionToken: "",
        offline: false,
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
        toast: document.getElementById("toast"),
      };

      function showToast(msg) {
        el.toast.textContent = msg;
        el.toast.classList.add("show");
        clearTimeout(window.__iddPreviewToastTimer);
        window.__iddPreviewToastTimer = setTimeout(() => {
          el.toast.classList.remove("show");
        }, 2200);
      }

      function applyTheme(theme) {
        const next = theme === "light" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        el.themeBtn.textContent = next === "dark" ? "浅色" : "深色";
        try { localStorage.setItem(THEME_KEY, next); } catch (_) {}
      }

      function setStatus(mode, text) {
        el.statusDot.className = "dot" + (mode === "warn" ? " warn" : mode === "err" ? " err" : "");
        el.statusText.textContent = text;
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
              renderStage(true);
            });
            el.tabBar.appendChild(btn);
          }
        }
        const canCompare = state.items.length >= 2;
        el.compareBtn.disabled = !canCompare;
        el.compareBtn.classList.toggle("active", state.compare && canCompare);
        el.openRawBtn.disabled = !state.items.length || !findItem(state.activeId)?.exists;
      }

      function makeFrameSrc(item) {
        return `${item.raw_url}?v=${encodeURIComponent(String(item.mtime_ns || 0))}_${encodeURIComponent(String(item.size || 0))}`;
      }

      function buildPane(slot, itemId) {
        const item = findItem(itemId);
        const pane = document.createElement("section");
        pane.className = "pane";
        pane.dataset.slot = slot;
        pane.style.width = state.compare && state.items.length >= 2 ? "50%" : state.viewport;
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
            renderStage(true);
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
          link.textContent = "原始页";
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
          const iframe = document.createElement("iframe");
          iframe.className = "canvas";
          iframe.dataset.itemId = item.id;
          iframe.dataset.mtime = String(item.mtime_ns);
          iframe.src = makeFrameSrc(item);
          body.appendChild(iframe);
        }

        pane.appendChild(body);
        return pane;
      }

      function renderStage(forceRebuild) {
        if (!state.items.length) {
          el.stage.innerHTML = `<div class="pane"><div class="empty-box">
            <div style="font-size:16px;font-weight:600;">暂无可预览的 HTML 文件</div>
            <div>向监听目录写入 <code>.html</code> 文件后会自动出现在此工作台。</div>
          </div></div>`;
          return;
        }

        const isCompare = state.compare && state.items.length >= 2;
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
              const iframe = pane.querySelector("iframe.canvas");
              if (!item || !item.exists) {
                if (iframe) {
                  canPatchInPlace = false;
                  break;
                }
              } else {
                if (!iframe || iframe.dataset.itemId !== item.id) {
                  canPatchInPlace = false;
                  break;
                }
                pane.style.width = isCompare ? "50%" : state.viewport;
                if (iframe.dataset.mtime !== String(item.mtime_ns)) {
                  iframe.dataset.mtime = String(item.mtime_ns);
                  iframe.src = makeFrameSrc(item);
                }
              }
            }
            if (canPatchInPlace) return;
          }
        }

        el.stage.innerHTML = "";
        for (const w of wanted) {
          el.stage.appendChild(buildPane(w.slot, w.id));
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
            setStatus("warn", "部分文件缺失");
          } else if (changedLabels.length) {
            setStatus("ok", "Live · 已热更新");
          } else if (initial || state.statusIdle !== true) {
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
          setStatus("err", "连接已断开");
        }
      }

      // Wire controls
      try {
        applyTheme(localStorage.getItem(THEME_KEY) || "dark");
      } catch (_) {
        applyTheme("dark");
      }

      el.themeBtn.addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme");
        applyTheme(cur === "dark" ? "light" : "dark");
      });

      el.compareBtn.addEventListener("click", () => {
        if (state.items.length < 2) return;
        state.compare = !state.compare;
        renderTabs();
        renderStage(true);
      });

      el.viewportGroup.querySelectorAll("button[data-vp]").forEach((btn) => {
        btn.addEventListener("click", () => {
          el.viewportGroup.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          state.viewport = btn.dataset.vp || "100%";
          if (state.compare) {
            state.compare = false;
            renderTabs();
            renderStage(true);
          } else {
            renderStage(false);
          }
        });
      });

      el.reloadBtn.addEventListener("click", () => {
        el.stage.querySelectorAll("iframe.canvas").forEach((iframe) => {
          const item = findItem(iframe.dataset.itemId);
          if (item && item.exists) {
            iframe.src = `${item.raw_url}?manual=${Date.now()}`;
          }
        });
        showToast("已手动刷新画布");
      });

      el.openRawBtn.addEventListener("click", () => {
        const item = findItem(state.activeId);
        if (item && item.exists) {
          window.open(item.raw_url, "_blank", "noopener");
        }
      });

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
