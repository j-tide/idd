#!/usr/bin/env python3
"""Local HTTP server and offline single-page Web Dashboard for `idd board`."""

from __future__ import annotations

import errno
from functools import partial
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
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
    load_hosts_config,
    normalize_host_input,
    save_hosts_config,
    verify_host_token,
)
import monitor  # noqa: E402
from version import get_version  # noqa: E402


BOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IDD 实时开发监控看板</title>
  <link rel="icon" href="data:," />
  <style>
    :root {
      --bg-app: #111417;
      --bg-sidebar: #161a1e;
      --bg-card: #1c2025;
      --bg-card-hover: #22272d;
      --bg-well: #14171b;
      --bg-input: rgba(255, 255, 255, 0.06);
      --bg-tile: rgba(255, 255, 255, 0.045);
      --bg-tile-active: rgba(255, 255, 255, 0.11);
      --bg-row-active: rgba(255, 255, 255, 0.068);
      --bg-inset: rgba(255, 255, 255, 0.04);
      --bg-col: rgba(255, 255, 255, 0.028);
      --border: rgba(255, 255, 255, 0.072);
      --border-subtle: rgba(255, 255, 255, 0.05);
      --border-strong: rgba(255, 255, 255, 0.15);
      --text: #f3f4f6;
      --text-dim: #9ca3af;
      --text-faint: #6b7280;
      --accent: #60a5fa;
      --accent-soft: rgba(96, 165, 250, 0.12);
      --accent-ring: rgba(96, 165, 250, 0.30);
      --green: #4ade80;
      --green-soft: rgba(74, 222, 128, 0.12);
      --amber: #fbbf24;
      --amber-soft: rgba(251, 191, 36, 0.12);
      --red: #f87171;
      --red-soft: rgba(248, 113, 113, 0.13);
      --purple: #a78bfa;
      --purple-soft: rgba(167, 139, 250, 0.13);
      --bar-empty: rgba(255, 255, 255, 0.08);
      --bar-fill: #f3f4f6;
      --bar-muted: rgba(255, 255, 255, 0.28);
      --skel-base: rgba(255, 255, 255, 0.06);
      --skel-shine: rgba(255, 255, 255, 0.12);
      --shadow-panel: 0 20px 50px rgba(0, 0, 0, 0.55);
      --radius-shell: 16px;
      --radius-card: 16px;
      --radius-row: 11px;
      --radius-sm: 8px;
      --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
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
      --bg-sidebar: #f6f7f9;
      --bg-card: #ffffff;
      --bg-card-hover: #f9fafb;
      --bg-well: #f4f5f7;
      --bg-input: rgba(15, 23, 42, 0.055);
      --bg-tile: rgba(15, 23, 42, 0.04);
      --bg-tile-active: rgba(15, 23, 42, 0.09);
      --bg-row-active: rgba(15, 23, 42, 0.055);
      --bg-inset: rgba(15, 23, 42, 0.04);
      --bg-col: rgba(15, 23, 42, 0.03);
      --border: rgba(15, 23, 42, 0.08);
      --border-subtle: rgba(15, 23, 42, 0.055);
      --border-strong: rgba(15, 23, 42, 0.16);
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
      --purple: #7c3aed;
      --purple-soft: rgba(124, 58, 237, 0.10);
      --bar-empty: rgba(15, 23, 42, 0.08);
      --bar-fill: #111827;
      --bar-muted: rgba(15, 23, 42, 0.26);
      --skel-base: rgba(15, 23, 42, 0.065);
      --skel-shine: rgba(15, 23, 42, 0.13);
      --shadow-panel: 0 20px 50px rgba(15, 23, 42, 0.14);
      --shadow-pill: 0 1px 3px rgba(15, 23, 42, 0.10), 0 0 0 1px rgba(15, 23, 42, 0.06);
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      font-family: var(--sans);
      font-size: 13px;
      line-height: 1.48;
      color: var(--text);
      background: var(--bg-app);
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    html.theme-transitioning body,
    html.theme-transitioning .sidebar,
    html.theme-transitioning .bento-card,
    html.theme-transitioning .bento-metric,
    html.theme-transitioning .card,
    html.theme-transitioning .column,
    html.theme-transitioning .console-well,
    html.theme-transitioning .inspector-panel,
    html.theme-transitioning .setup-modal,
    html.theme-transitioning .am-confirm-modal,
    html.theme-transitioning .status-popover,
    html.theme-transitioning .btn,
    html.theme-transitioning .sb-item,
    html.theme-transitioning .sb-tile,
    html.theme-transitioning .list-wrap,
    html.theme-transitioning .host-card,
    html.theme-transitioning .host-row-compact,
    html.theme-transitioning .policy-section,
    html.theme-transitioning .policy-repo-row {
      transition: background-color 240ms var(--ease-in-out), color 240ms var(--ease-in-out), border-color 240ms var(--ease-in-out) !important;
    }

    a { color: inherit; text-decoration: none; }
    button { font-family: inherit; }
    .num { font-variant-numeric: tabular-nums; }
    .mono { font-family: var(--mono); }

    /* Desktop Inset App Shell */
    .app-shell {
      display: flex;
      gap: 12px;
      padding: 12px;
      min-height: 100vh;
      max-width: 1640px;
      margin: 0 auto;
      align-items: stretch;
    }

    /* Collapsible Left Inset Sidebar */
    .sidebar {
      width: 248px;
      flex-shrink: 0;
      background: var(--bg-sidebar);
      border: 1px solid var(--border);
      border-radius: var(--radius-shell);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: width var(--dur-surface) var(--ease-spring), padding var(--dur-surface) var(--ease-spring);
    }
    body.sidebar-collapsed .sidebar {
      width: 58px;
      padding: 10px 9px;
      align-items: center;
    }
    body.sidebar-collapsed .hide-collapsed {
      display: none !important;
    }
    .show-collapsed { display: none !important; }
    body.sidebar-collapsed .show-collapsed { display: inline-grid !important; }
    body.sidebar-expanding .hide-collapsed {
      animation: fadeSlideIn var(--dur-state) var(--ease-out) both;
    }

    /* Sidebar Search */
    .sb-search {
      position: relative;
      display: flex;
      align-items: center;
      background: var(--bg-input);
      border: 1px solid transparent;
      border-radius: 10px;
      height: 36px;
      padding: 0 10px;
      gap: 8px;
      transition: border-color var(--dur-micro) var(--ease-snap), background var(--dur-micro) var(--ease-snap), box-shadow var(--dur-micro) var(--ease-snap);
    }
    .sb-search:focus-within {
      border-color: var(--accent-ring);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    .sb-search-ic {
      color: var(--text-dim);
      display: grid;
      place-items: center;
      flex-shrink: 0;
      transition: color var(--dur-micro) var(--ease-snap);
    }
    .sb-search:focus-within .sb-search-ic { color: var(--accent); }
    .sb-search input {
      width: 100%;
      min-width: 0;
      border: 0;
      background: transparent;
      color: var(--text);
      font-family: var(--sans);
      font-size: 12.5px;
      outline: none;
    }
    .sb-search input::placeholder { color: var(--text-faint); }
    .sb-search input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
    .sb-kbd {
      font-family: var(--mono);
      font-size: 10px;
      color: var(--text-faint);
      padding: 1px 5px;
      border-radius: 4px;
      border: 1px solid var(--border);
      flex-shrink: 0;
      transition: opacity var(--dur-micro) var(--ease-out), transform var(--dur-micro) var(--ease-out);
    }
    .sb-search-clear {
      border: 0;
      background: transparent;
      color: var(--text-faint);
      cursor: pointer;
      padding: 2px;
      display: grid;
      place-items: center;
      border-radius: 5px;
      opacity: 0;
      transform: scale(0.8);
      pointer-events: none;
      width: 0;
      overflow: hidden;
      transition: opacity var(--dur-micro) var(--ease-out), transform var(--dur-micro) var(--ease-out), color var(--dur-micro) var(--ease-snap);
    }
    .sb-search-clear:hover { color: var(--text); }
    .sb-search.has-value .sb-search-clear {
      opacity: 1;
      transform: scale(1);
      pointer-events: auto;
      width: auto;
      overflow: visible;
    }
    .sb-search.has-value .sb-kbd,
    .sb-search:focus-within .sb-kbd {
      opacity: 0;
      transform: scale(0.85);
      pointer-events: none;
      width: 0;
      padding: 0;
      border: 0;
      overflow: hidden;
    }

    body.sidebar-collapsed .sb-search {
      width: 38px;
      height: 38px;
      padding: 0;
      justify-content: center;
      cursor: pointer;
    }

    /* Sidebar Filter Rows (Agents / Alerts / Unstarted) */
    .sb-nav {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin-top: 4px;
      width: 100%;
    }
    body.sidebar-collapsed .sb-nav {
      align-items: center;
      gap: 4px;
    }
    .sb-item {
      appearance: none;
      width: 100%;
      border: 0;
      background: transparent;
      color: var(--text-dim);
      border-radius: 9px;
      height: 32px;
      padding: 0 8px;
      font-size: 12.5px;
      font-weight: 500;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      cursor: pointer;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
      position: relative;
    }
    .sb-item:hover { background: var(--bg-tile); color: var(--text); }
    .sb-item:active { transform: scale(0.992); transition-duration: var(--dur-press); }
    .sb-item.active { background: var(--bg-tile-active); color: var(--text); }
    .sb-item-left {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-width: 0;
    }
    .sb-item-left span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sb-meta {
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--text-faint);
      flex-shrink: 0;
    }
    .sb-meta.live { color: var(--green); }
    .sb-meta.warn { color: var(--amber); }
    .sb-meta.danger { color: var(--red); }

    body.sidebar-collapsed .sb-item {
      width: 38px;
      height: 36px;
      padding: 0;
      justify-content: center;
    }

    .corner-dot {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--green);
      display: none;
    }
    .corner-dot.warn { background: var(--amber); }
    .corner-dot.danger { background: var(--red); }
    body.sidebar-collapsed .corner-dot.show { display: block; }

    /* 4 Squircle View Tiles */
    .sb-tiles {
      position: relative;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 6px;
      margin-top: 8px;
      width: 100%;
    }
    body.sidebar-collapsed .sb-tiles {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      margin-top: 6px;
    }
    .sb-tile {
      appearance: none;
      height: 36px;
      border-radius: 10px;
      border: 1px solid transparent;
      background: var(--bg-tile);
      color: var(--text-dim);
      cursor: pointer;
      display: grid;
      place-items: center;
      position: relative;
      z-index: 1;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    body.sidebar-collapsed .sb-tile { width: 38px; height: 38px; }
    .sb-tile:hover { background: var(--bg-tile-active); color: var(--text); }
    .sb-tile:active { transform: scale(0.96); transition-duration: var(--dur-press); }
    .sb-tile.active {
      background: var(--bg-tile-active);
      border-color: var(--border-strong);
      color: var(--text);
    }
    .sb-tiles.has-indicator .sb-tile.active {
      background: transparent;
      border-color: transparent;
    }
    .seg-indicator {
      position: absolute;
      top: 0;
      left: 0;
      border-radius: 7px;
      background: var(--bg-tile-active);
      box-shadow: var(--shadow-pill);
      pointer-events: none;
      z-index: 0;
      transition: transform var(--dur-state) var(--ease-spring), width var(--dur-state) var(--ease-spring), height var(--dur-state) var(--ease-spring), opacity var(--dur-micro) var(--ease-out);
    }
    .sb-tiles .seg-indicator {
      border-radius: 10px;
      background: var(--bg-tile-active);
      border: 1px solid var(--border-strong);
      box-shadow: none;
    }
    .tile-dot {
      position: absolute;
      top: 5px;
      right: 5px;
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: var(--green);
      display: none;
    }
    .tile-dot.show { display: block; }

    .sb-divider {
      height: 1px;
      width: 100%;
      background: var(--border-subtle);
      margin: 6px 0;
    }

    .sb-section-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 6px 3px;
      font-size: 11px;
      font-weight: 560;
      color: var(--text-faint);
      letter-spacing: 0.02em;
    }

    .sb-list {
      display: flex;
      flex-direction: column;
      gap: 2px;
      width: 100%;
    }
    body.sidebar-collapsed .sb-list { align-items: center; gap: 4px; }

    .sb-repo-badge {
      width: 22px;
      height: 22px;
      border-radius: 6px;
      display: grid;
      place-items: center;
      flex-shrink: 0;
      background: var(--bg-tile-active);
      color: var(--text);
    }
    .sb-repo-badge.is-github { background: rgba(243, 244, 246, 0.10); color: var(--text); }
    .sb-repo-badge.is-gitlab { background: rgba(251, 146, 60, 0.14); color: #fb923c; }
    .sb-repo-badge.is-all { background: var(--accent-soft); color: var(--accent); }
    html[data-theme="light"] .sb-repo-badge.is-github { background: rgba(15, 23, 42, 0.08); color: #111827; }

    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex-shrink: 0;
      display: inline-block;
      background: var(--text-faint);
      transition: background var(--dur-state) var(--ease-in-out);
    }
    .status-dot.active { background: var(--green); }
    .status-dot.warm { background: var(--amber); }
    .status-dot.fail { background: var(--red); }
    .status-dot.quiet { background: var(--text-faint); }

    .sb-wt-icon {
      width: 24px;
      height: 24px;
      border-radius: 7px;
      display: grid;
      place-items: center;
      flex-shrink: 0;
      background: var(--bg-tile);
      color: var(--text-dim);
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 600;
    }
    .sb-item.active .sb-wt-icon {
      background: var(--accent-soft);
      color: var(--accent);
    }

    .sb-footer {
      margin-top: auto;
      padding-top: 10px;
      border-top: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      width: 100%;
    }
    .sb-footer .sb-item {
      width: auto;
      flex: 1;
      min-width: 0;
    }
    body.sidebar-collapsed .sb-footer {
      justify-content: center;
    }
    body.sidebar-collapsed .sb-footer .sb-item {
      width: 38px;
      flex: 0 0 auto;
    }

    /* Main Workspace Column */
    .workspace {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .workspace > #top-alerts-wrap:empty,
    .workspace > #warnings-wrap:empty {
      display: none;
    }

    .ws-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px 12px;
      min-height: 40px;
      padding: 2px 4px;
    }
    .ws-title-group {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .icon-btn {
      appearance: none;
      width: 32px;
      height: 32px;
      border-radius: 9px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--text-dim);
      cursor: pointer;
      display: grid;
      place-items: center;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .icon-btn:hover { background: var(--bg-tile); color: var(--text); border-color: var(--border); }
    .icon-btn:active { transform: scale(0.95); transition-duration: var(--dur-press); }

    .ws-logo {
      width: 32px;
      height: 32px;
      border-radius: 9px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      display: grid;
      place-items: center;
      color: var(--text);
      flex-shrink: 0;
    }
    .ws-logo.is-github {
      background: rgba(243, 244, 246, 0.10);
      border-color: rgba(243, 244, 246, 0.18);
      color: var(--text);
    }
    html[data-theme="light"] .ws-logo.is-github {
      background: rgba(15, 23, 42, 0.08);
      border-color: rgba(15, 23, 42, 0.16);
      color: #111827;
    }
    .ws-logo.is-gitlab {
      background: rgba(251, 146, 60, 0.15);
      border-color: rgba(251, 146, 60, 0.32);
      color: #fb923c;
    }
    html[data-theme="light"] .ws-logo.is-gitlab {
      background: rgba(234, 88, 12, 0.10);
      border-color: rgba(234, 88, 12, 0.28);
      color: #c2410c;
    }
    .ws-title {
      margin: 0;
      font-size: 17px;
      font-weight: 620;
      letter-spacing: -0.02em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .ws-scope {
      font-size: 11.5px;
      color: var(--text-faint);
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--bg-tile);
      border: 1px solid var(--border-subtle);
      flex-shrink: 0;
    }

    .sb-right-group {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      flex-shrink: 0;
    }
    .sb-plat-tag {
      font-size: 9.5px;
      font-weight: 650;
      padding: 1px 4.5px;
      border-radius: 4px;
      line-height: 1.35;
      letter-spacing: 0.02em;
    }
    .sb-plat-tag.is-github { background: rgba(243, 244, 246, 0.09); color: var(--text-dim); }
    html[data-theme="light"] .sb-plat-tag.is-github { background: rgba(15, 23, 42, 0.07); color: #374151; }
    .sb-plat-tag.is-gitlab { background: rgba(251, 146, 60, 0.15); color: #fb923c; }
    html[data-theme="light"] .sb-plat-tag.is-gitlab { background: rgba(234, 88, 12, 0.10); color: #c2410c; }
    .sb-ext-link {
      width: 21px;
      height: 21px;
      border-radius: 6px;
      display: inline-grid;
      place-items: center;
      color: var(--text-faint);
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .sb-ext-link svg { transition: transform var(--dur-micro) var(--ease-snap); }
    .sb-ext-link:hover {
      background: var(--bg-card);
      color: var(--accent);
    }
    .sb-ext-link:hover svg { transform: translate(1.5px, -1.5px); }
    .sb-ext-link:active { transform: scale(0.94); transition-duration: var(--dur-press); }

    .forge-chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 8px;
      border-radius: 7px;
      font-size: 11px;
      font-weight: 560;
      line-height: 1.38;
      border: 1px solid var(--border);
      background: var(--bg-inset);
      color: var(--text-dim);
      white-space: nowrap;
      transition: background var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .forge-chip.is-compact {
      padding: 1.5px 6.5px;
      font-size: 10.5px;
      gap: 4px;
    }
    a.forge-chip:hover {
      border-color: var(--border-strong);
      background: var(--bg-tile-active);
      color: var(--text);
    }
    a.forge-chip:active { transform: scale(0.97); transition-duration: var(--dur-press); }
    .forge-chip.is-github {
      background: rgba(243, 244, 246, 0.08);
      border-color: rgba(243, 244, 246, 0.16);
      color: #f3f4f6;
    }
    html[data-theme="light"] .forge-chip.is-github {
      background: rgba(15, 23, 42, 0.06);
      border-color: rgba(15, 23, 42, 0.15);
      color: #111827;
    }
    a.forge-chip.is-github:hover {
      background: rgba(243, 244, 246, 0.15);
      border-color: rgba(243, 244, 246, 0.32);
    }
    html[data-theme="light"] a.forge-chip.is-github:hover {
      background: rgba(15, 23, 42, 0.11);
      border-color: rgba(15, 23, 42, 0.28);
    }
    .forge-chip.is-gitlab {
      background: rgba(251, 146, 60, 0.13);
      border-color: rgba(251, 146, 60, 0.30);
      color: #fb923c;
    }
    html[data-theme="light"] .forge-chip.is-gitlab {
      background: rgba(234, 88, 12, 0.09);
      border-color: rgba(234, 88, 12, 0.26);
      color: #c2410c;
    }
    a.forge-chip.is-gitlab:hover {
      background: rgba(251, 146, 60, 0.22);
      border-color: rgba(251, 146, 60, 0.48);
    }
    html[data-theme="light"] a.forge-chip.is-gitlab:hover {
      background: rgba(234, 88, 12, 0.15);
      border-color: rgba(234, 88, 12, 0.42);
    }
    .forge-chip-plat { font-weight: 640; }
    .forge-chip-sep { opacity: 0.45; }
    .forge-chip-name { max-width: 165px; overflow: hidden; text-overflow: ellipsis; }
    .forge-chip-ext { opacity: 0.68; display: inline-flex; align-items: center; transition: opacity var(--dur-micro) var(--ease-snap), transform var(--dur-micro) var(--ease-snap); }
    a.forge-chip:hover .forge-chip-ext { opacity: 1; transform: translate(1.5px, -1.5px); }

    .btn-warn {
      background: var(--amber-soft);
      border-color: rgba(251, 191, 36, 0.38);
      color: var(--amber);
      font-weight: 580;
    }
    .btn-warn:hover {
      background: rgba(251, 191, 36, 0.20);
      border-color: rgba(251, 191, 36, 0.55);
      color: var(--amber);
    }
    .setup-badge-cnt {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 16px;
      height: 16px;
      padding: 0 4px;
      border-radius: 999px;
      font-size: 10.5px;
      font-weight: 700;
      background: var(--amber);
      color: #111827;
    }

    .ws-controls {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 7px;
      flex-shrink: 0;
    }

    .btn {
      appearance: none;
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: var(--text-dim);
      border-radius: var(--radius-sm);
      height: 30px;
      padding: 0 10px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .btn:hover:not(:disabled) { background: var(--bg-card-hover); color: var(--text); border-color: var(--border-strong); }
    .btn:active:not(:disabled) { transform: scale(0.97); transition-duration: var(--dur-press); }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn-sm { height: 26px; padding: 0 9px; font-size: 11.5px; border-radius: 7px; }
    .btn-xs { height: 24px; padding: 0 8px; font-size: 11px; border-radius: 6px; }
    .btn-icon-only { width: 26px; height: 26px; padding: 0; justify-content: center; }
    .btn-primary {
      background: var(--accent-soft);
      border-color: var(--accent-ring);
      color: var(--accent);
      font-weight: 580;
    }
    .btn-primary:hover:not(:disabled) { background: rgba(96, 165, 250, 0.20); color: var(--accent); }
    .btn.copied {
      background: var(--green-soft) !important;
      border-color: rgba(74, 222, 128, 0.35) !important;
      color: var(--green) !important;
    }
    #sync-btn { min-width: 88px; justify-content: center; }
    .btn.spin svg { animation: spin 0.85s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes checkDraw {
      0% { stroke-dashoffset: 24; transform: scale(0.8); }
      60% { stroke-dashoffset: 0; transform: scale(1.1); }
      100% { stroke-dashoffset: 0; transform: scale(1); }
    }
    @keyframes iconPop {
      0% { transform: scale(0.74); opacity: 0.55; }
      65% { transform: scale(1.12); opacity: 1; }
      100% { transform: scale(1); opacity: 1; }
    }
    .btn.copied.is-pop svg,
    .copy-chip.copied.is-pop svg {
      stroke-dasharray: 24;
      animation: checkDraw 260ms var(--ease-out) both;
    }
    .icon-pop svg {
      animation: iconPop 220ms var(--ease-spring) both;
    }

    .status-cluster {
      position: relative;
      display: inline-flex;
      align-items: center;
      height: 30px;
      padding: 0 3px;
      gap: 2px;
      border-radius: var(--radius-sm);
      background: var(--bg-card);
      border: 1px solid var(--border);
    }
    .status-cluster.is-err { border-color: rgba(248, 113, 113, 0.36); }
    .status-cluster-live {
      display: inline-flex;
      align-items: center;
      gap: 2px;
    }
    .status-cluster-sep {
      width: 1px;
      height: 14px;
      background: var(--border);
      margin: 0 2px;
      flex-shrink: 0;
    }
    .cluster-icon-btn {
      appearance: none;
      width: 24px;
      height: 24px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--text-dim);
      cursor: pointer;
      display: inline-grid;
      place-items: center;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .cluster-icon-btn:hover { background: var(--bg-tile); color: var(--text); }
    .cluster-icon-btn:active { transform: scale(0.93); transition-duration: var(--dur-press); }
    .cluster-icon-btn.is-paused {
      background: var(--amber-soft);
      border-color: rgba(251, 191, 36, 0.32);
      color: var(--amber);
    }
    .forge-status-group {
      display: inline-flex;
      align-items: center;
      gap: 2px;
    }
    .forge-status-btn {
      appearance: none;
      height: 24px;
      padding: 0 7px;
      border-radius: 6px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--text-dim);
      font-size: 11.5px;
      font-weight: 530;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), opacity var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .forge-status-btn:hover,
    .forge-status-btn.is-open { background: var(--bg-tile); color: var(--text); }
    .forge-status-btn.is-open { border-color: var(--border-strong); }
    .forge-status-btn:active { transform: scale(0.96); transition-duration: var(--dur-press); }
    .forge-status-btn.is-gitlab svg { color: #fb923c; }
    html[data-theme="light"] .forge-status-btn.is-gitlab svg { color: #c2410c; }
    .forge-status-dot {
      position: relative;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
      background: var(--text-faint);
      color: var(--text-faint);
      transition: background var(--dur-state) var(--ease-in-out);
    }
    .forge-status-dot::after,
    .dot-pulse::after {
      content: "";
      position: absolute;
      inset: 0;
      border-radius: 50%;
      background: currentColor;
      opacity: 0;
      pointer-events: none;
    }
    .forge-status-btn.is-connected .forge-status-dot { background: var(--green); color: var(--green); }
    .forge-status-btn.is-connected { color: var(--text); }
    .forge-status-btn.is-syncing .forge-status-dot { background: var(--accent); color: var(--accent); }
    .forge-status-btn.is-syncing .forge-status-dot::after { animation: pulseRing 1.3s var(--ease-out) infinite; }
    .forge-status-btn.is-syncing { color: var(--text); }
    .forge-status-btn.is-auth .forge-status-dot,
    .forge-status-btn.is-partial .forge-status-dot { background: var(--amber); }
    .forge-status-btn.is-auth,
    .forge-status-btn.is-partial {
      background: var(--amber-soft);
      border-color: rgba(251, 191, 36, 0.24);
      color: var(--amber);
    }
    .forge-status-btn.is-error .forge-status-dot { background: var(--red); }
    .forge-status-btn.is-error {
      background: var(--red-soft);
      border-color: rgba(248, 113, 113, 0.28);
      color: var(--red);
    }
    .forge-status-btn.is-local .forge-status-dot { background: var(--text-faint); }
    .forge-status-btn.is-unconfigured { opacity: 0.68; }
    .forge-status-btn.is-unconfigured:hover,
    .forge-status-btn.is-unconfigured.is-open { opacity: 1; }
    .forge-status-btn.is-unconfigured .forge-status-dot {
      background: transparent;
      border: 1.5px solid var(--text-faint);
    }
    .forge-status-state {
      font-size: 10.5px;
      font-weight: 600;
      opacity: 0.92;
    }
    .status-popover {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      width: 360px;
      max-width: calc(100vw - 24px);
      z-index: 95;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: 13px;
      box-shadow: var(--shadow-panel);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 9px;
      visibility: hidden;
      opacity: 0;
      pointer-events: none;
      transform: translate3d(0, -6px, 0) scale(0.96);
      transform-origin: top right;
      transition: opacity var(--dur-exit) var(--ease-out), transform var(--dur-state) var(--ease-spring), visibility 0s linear var(--dur-exit);
    }
    .status-popover.open {
      visibility: visible;
      opacity: 1;
      pointer-events: auto;
      transform: translate3d(0, 0, 0) scale(1);
      transition: opacity var(--dur-micro) var(--ease-out), transform var(--dur-state) var(--ease-spring), visibility 0s;
    }
    @media (max-width: 600px) {
      .status-popover {
        position: fixed;
        top: 58px;
        left: 12px;
        right: 12px;
        width: auto;
        max-width: none;
        transform-origin: top center;
      }
    }
    .status-pop-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border-subtle);
      font-size: 11.5px;
      color: var(--text-dim);
    }
    .status-pop-live {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-weight: 580;
      color: var(--text);
    }
    .status-pop-card {
      padding: 9px 11px;
      border-radius: 10px;
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 7px;
    }
    .status-pop-card.is-focus { border-color: var(--accent-ring); }
    .status-pop-card-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .status-pop-plat {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      font-size: 12.5px;
      font-weight: 620;
      color: var(--text);
    }
    .status-pop-hosts {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .status-pop-host {
      padding: 7px 9px;
      border-radius: 8px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 11.5px;
    }
    .status-pop-host-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .status-pop-host-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 11px;
      color: var(--text-faint);
    }
    .status-pop-err {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 11px;
      color: var(--red);
      word-break: break-word;
    }
    .status-pop-empty {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 11.5px;
      color: var(--text-faint);
    }
    .status-pop-ftr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding-top: 2px;
    }
    @media (max-width: 960px) {
      .status-cluster .live-clock,
      .status-cluster .live-sep { display: none; }
      .forge-status-state { display: none; }
    }

    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 30px;
      padding: 0 10px;
      border-radius: var(--radius-sm);
      font-size: 11.5px;
      font-weight: 500;
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-dim);
    }
    .status-cluster .live-pill {
      height: 24px;
      padding: 0 7px;
      border: 0;
      background: transparent;
      border-radius: 6px;
    }
    .live-pill.is-live .dot-pulse { background: var(--green); color: var(--green); }
    .live-pill.is-live .dot-pulse::after { animation: pulseRing 2.1s var(--ease-out) infinite; }
    .live-pill.is-loading .dot-pulse,
    .live-pill.is-syncing .dot-pulse { background: var(--accent); color: var(--accent); }
    .live-pill.is-loading .dot-pulse::after,
    .live-pill.is-syncing .dot-pulse::after { animation: pulseRing 1.3s var(--ease-out) infinite; }
    .live-pill.is-loading,
    .live-pill.is-syncing { border-color: var(--accent-ring); color: var(--text); }
    .live-pill.is-local .dot-pulse { background: var(--text-faint); color: var(--text-faint); }
    .live-pill.is-err { color: var(--red); border-color: rgba(248, 113, 113, 0.32); }
    .dot-pulse {
      position: relative;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--text-faint);
      transition: background var(--dur-state) var(--ease-in-out);
    }
    @keyframes pulseRing {
      0% { transform: scale(1); opacity: 0.55; }
      70%, 100% { transform: scale(2.25); opacity: 0; }
    }

    /* Global Top Indeterminate Progress Bar */
    .top-progress {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 2.5px;
      z-index: 120;
      pointer-events: none;
      overflow: hidden;
      opacity: 0;
      transition: opacity var(--dur-state) var(--ease-out);
    }
    .top-progress.is-active { opacity: 1; }
    .top-progress-bar {
      position: absolute;
      top: 0;
      left: 0;
      bottom: 0;
      width: 38%;
      border-radius: 999px;
      background: linear-gradient(90deg, transparent, var(--accent), transparent);
      animation: topProgressSlide 1.35s var(--ease-in-out) infinite;
    }
    @keyframes topProgressSlide {
      0% { transform: translate3d(-110%, 0, 0); }
      100% { transform: translate3d(360%, 0, 0); }
    }

    /* Skeleton Loading Primitives (GPU-Composited Sweep) */
    .init-status-left svg {
      animation: spin 1s linear infinite;
      flex-shrink: 0;
    }
    .init-status-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      padding: 10px 14px;
      border-radius: 12px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-dim);
      font-size: 12.5px;
      margin-bottom: 12px;
    }
    .init-status-left {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      font-weight: 550;
      min-width: 0;
    }
    .init-status-left svg { color: var(--accent); }
    .init-status-sub {
      font-size: 11.5px;
      color: var(--text-faint);
    }
    .skel-block,
    .seg-pill.skel {
      position: relative;
      overflow: hidden;
      background: var(--skel-base);
    }
    .skel-block {
      display: inline-block;
      border-radius: 6px;
    }
    .skel-block::after,
    .seg-pill.skel::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, var(--skel-shine), transparent);
      transform: translate3d(-100%, 0, 0);
      animation: skelSweep 1.35s var(--ease-in-out) infinite;
      pointer-events: none;
    }
    @keyframes skelSweep {
      0% { transform: translate3d(-100%, 0, 0); }
      100% { transform: translate3d(100%, 0, 0); }
    }
    .sb-skel-row {
      height: 32px;
      padding: 0 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .bento-metric.is-skel { cursor: default; pointer-events: none; }
    .skel-wt-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 11px 12px;
      border-radius: var(--radius-row);
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
      .top-progress-bar,
      .skel-block::after,
      .seg-pill.skel::after,
      .dot-pulse::after,
      .forge-status-dot::after,
      .init-status-left svg,
      .btn.spin svg {
        animation: none !important;
      }
    }

    /* Bento Telemetry Row (Matches Uptime / CPU Reference Cards) */
    .telemetry-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    @media (max-width: 900px) {
      .telemetry-grid { grid-template-columns: 1fr; }
    }
    .bento-metric {
      appearance: none;
      text-align: left;
      width: 100%;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-card);
      padding: 14px 18px 13px;
      color: var(--text);
      display: flex;
      flex-direction: column;
      transition: border-color var(--dur-micro) var(--ease-snap), background var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    button.bento-metric { cursor: pointer; }
    button.bento-metric:hover { background: var(--bg-card-hover); border-color: var(--border-strong); }
    button.bento-metric:active { transform: scale(0.992); transition-duration: var(--dur-press); }
    .bento-metric.is-filtered { border-color: var(--accent-ring); }
    .bento-metric.is-warn { border-color: var(--border); }

    .metric-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-dim);
    }
    .metric-hdr-left {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .metric-val-row {
      margin-top: 6px;
      display: flex;
      align-items: baseline;
      gap: 5px;
    }
    .metric-num {
      font-size: 28px;
      font-weight: 600;
      letter-spacing: -0.03em;
      line-height: 1.08;
      color: var(--text);
    }
    .metric-unit {
      font-size: 13.5px;
      font-weight: 480;
      color: var(--text-dim);
    }

    /* Chunky Segmented Pill Bar */
    .seg-bar {
      display: grid;
      grid-template-columns: repeat(8, 1fr);
      gap: 6px;
      margin: 12px 0 9px;
    }
    .seg-pill {
      height: 14px;
      border-radius: 3.5px;
      background: var(--bar-empty);
      transition: background var(--dur-data) var(--ease-in-out);
    }
    .seg-pill.on { background: var(--bar-fill); }
    .seg-pill.dim { background: var(--bar-muted); }
    .seg-pill.green { background: var(--green); }
    .seg-pill.amber { background: var(--amber); }
    .seg-pill.red { background: var(--red); }

    .metric-sub {
      font-size: 11.5px;
      color: var(--text-faint);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .metric-sub.live { color: var(--green); }
    .metric-sub.warn { color: var(--amber); }

    /* Bento Card Container (Services & Logs Aesthetic) */
    .bento-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-card);
      padding: 15px 16px;
    }
    .bento-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .bento-title-row {
      display: flex;
      align-items: center;
      gap: 10px;
      row-gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
      flex: 1;
    }
    .bento-title {
      font-size: 13.5px;
      font-weight: 600;
      color: var(--text);
      white-space: nowrap;
      flex-shrink: 0;
    }
    .bento-sub {
      font-size: 12px;
      color: var(--text-faint);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }
    .bento-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      flex-shrink: 0;
    }

    /* Services-Style Worktree Rows */
    .wt-list {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .wt-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 10px 12px;
      border-radius: var(--radius-row);
      cursor: pointer;
      transition: background var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
      border: 1px solid transparent;
    }
    .wt-row:hover { background: var(--bg-tile); }
    .wt-row:active { transform: scale(0.994); transition-duration: var(--dur-press); }
    .wt-row.is-selected {
      background: var(--bg-row-active);
      border-color: var(--border-subtle);
    }
    .wt-row-left {
      display: flex;
      align-items: flex-start;
      gap: 11px;
      min-width: 0;
      flex: 1;
    }
    .wt-row-dot { margin-top: 6px; }
    .wt-row-main { min-width: 0; flex: 1; }
    .wt-row-top {
      display: flex;
      align-items: center;
      gap: 7px;
      flex-wrap: wrap;
    }
    .wt-row-title {
      font-size: 13.5px;
      font-weight: 560;
      color: var(--text);
    }
    .wt-row-sub {
      margin-top: 3px;
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--text-dim);
    }
    .wt-row-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }
    .wt-tasks-strip {
      margin-top: 7px;
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }
    .task-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      max-width: 260px;
      padding: 2px 7px;
      border-radius: 6px;
      font-size: 11px;
      line-height: 1.35;
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
      color: var(--text-dim);
    }
    .task-chip span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .task-chip.is-done { color: var(--green); border-color: rgba(74, 222, 128, 0.24); background: var(--green-soft); }
    .task-chip.is-prog { color: var(--accent); border-color: var(--accent-ring); background: var(--accent-soft); }
    .task-chip.is-blk { color: var(--red); border-color: rgba(248, 113, 113, 0.30); background: var(--red-soft); }

    .todo-strip {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .todo-strip-hdr {
      font-size: 11.5px;
      font-weight: 560;
      color: var(--text-faint);
      padding: 0 12px 4px;
    }

    /* Recessed Monospace Console Well (Logs Style) */
    .console-well {
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      padding: 13px 16px;
      font-family: var(--mono);
      font-size: 11.8px;
      line-height: 1.65;
      color: var(--text-dim);
      overflow-x: auto;
    }
    .log-line {
      display: flex;
      align-items: baseline;
      gap: 12px;
      white-space: nowrap;
    }
    .log-k {
      width: 68px;
      flex-shrink: 0;
      color: var(--text-faint);
    }
    .log-v { color: var(--text); min-width: 0; }
    .log-v.ok { color: var(--green); }
    .log-v.warn { color: var(--amber); }
    .log-v.err { color: var(--red); }
    .log-v.info { color: var(--accent); }
    .log-sep {
      height: 1px;
      background: var(--border-subtle);
      margin: 10px 0;
    }
    .handoff-block {
      margin: 0;
      font-family: var(--mono);
      font-size: 11.8px;
      line-height: 1.6;
      color: var(--text);
      white-space: pre-wrap;
      word-break: break-word;
    }

    .console-tabs {
      position: relative;
      display: inline-flex;
      flex-shrink: 0;
      padding: 2px;
      gap: 2px;
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
    }
    .console-tab {
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--text-dim);
      height: 22px;
      padding: 0 9px;
      font-size: 11.5px;
      font-weight: 500;
      border-radius: 6px;
      cursor: pointer;
      white-space: nowrap;
      position: relative;
      z-index: 1;
      transition: color var(--dur-micro) var(--ease-snap), background var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .console-tab:hover { color: var(--text); }
    .console-tab:active { transform: scale(0.96); transition-duration: var(--dur-press); }
    .console-tab.active {
      background: var(--bg-tile-active);
      color: var(--text);
    }
    .console-tabs.has-indicator .console-tab.active { background: transparent; }
    .console-tabs .seg-indicator {
      border-radius: 6px;
      background: var(--bg-tile-active);
      box-shadow: var(--shadow-pill);
    }
    .view-enter {
      animation: viewEnter var(--dur-state) var(--ease-out) both;
    }
    .console-swap {
      animation: consoleSwap var(--dur-exit) var(--ease-out) both;
    }
    @keyframes viewEnter {
      from { opacity: 0; transform: translate3d(0, 6px, 0); }
      to { opacity: 1; transform: translate3d(0, 0, 0); }
    }
    @keyframes consoleSwap {
      from { opacity: 0.45; transform: translate3d(0, 3px, 0); }
      to { opacity: 1; transform: translate3d(0, 0, 0); }
    }

    /* Badges & Inline Chips */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 1px 7px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 540;
      line-height: 1.4;
      background: var(--bg-inset);
      color: var(--text-dim);
      white-space: nowrap;
      transition: background var(--dur-state) var(--ease-in-out), color var(--dur-state) var(--ease-in-out);
    }
    .tone-info { background: var(--accent-soft); color: var(--accent); }
    .tone-success { background: var(--green-soft); color: var(--green); }
    .tone-warning { background: var(--amber-soft); color: var(--amber); }
    .tone-danger { background: var(--red-soft); color: var(--red); }
    .tone-violet { background: var(--purple-soft); color: var(--purple); }
    .tone-muted { background: var(--bg-inset); color: var(--text-faint); }

    .id-link {
      font-family: var(--mono);
      font-weight: 600;
      font-size: 12px;
      color: var(--text-dim);
      transition: color var(--dur-micro) var(--ease-snap);
    }
    .id-link:hover { color: var(--accent); }

    .diff-ins { font-family: var(--mono); color: var(--green); font-weight: 600; }
    .diff-del { font-family: var(--mono); color: var(--red); font-weight: 600; }

    .copy-chip {
      appearance: none;
      border: 0;
      background: transparent;
      padding: 2px 5px;
      margin: -2px -5px;
      border-radius: 5px;
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-dim);
      display: inline-flex;
      align-items: center;
      gap: 5px;
      max-width: 100%;
      min-width: 0;
      cursor: pointer;
      text-align: left;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .copy-chip:hover { background: var(--bg-tile-active); color: var(--text); }
    .copy-chip:active { transform: scale(0.97); transition-duration: var(--dur-press); }
    .copy-chip.copied { background: var(--green-soft); color: var(--green); }
    .copy-chip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .copy-chip svg { flex-shrink: 0; }

    /* Secondary Views: Kanban / Repos / List */
    .kanban {
      display: grid;
      grid-template-columns: repeat(4, minmax(210px, 1fr));
      gap: 12px;
      align-items: start;
    }
    @media (max-width: 1080px) { .kanban { grid-template-columns: repeat(2, minmax(210px, 1fr)); } }
    @media (max-width: 640px) { .kanban { grid-template-columns: 1fr; } }

    .column {
      background: var(--bg-sidebar);
      border: 1px solid var(--border);
      border-radius: var(--radius-card);
      padding: 11px;
      min-height: 220px;
    }
    .col-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 4px 10px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
    }
    .col-title { display: inline-flex; align-items: center; gap: 7px; }
    .col-count { font-family: var(--mono); font-size: 11px; color: var(--text-faint); }
    .card-stack { display: flex; flex-direction: column; gap: 8px; }
    .col-empty { padding: 22px 10px; text-align: center; color: var(--text-faint); font-size: 12px; }

    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      cursor: pointer;
      transition: border-color var(--dur-micro) var(--ease-snap), background var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .card:hover { border-color: var(--border-strong); background: var(--bg-card-hover); }
    .card:active { transform: scale(0.992); transition-duration: var(--dur-press); }
    .card.is-selected { border-color: var(--accent-ring); }
    .card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .card-meta { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--text-faint); min-width: 0; }
    .card-title { margin-top: 6px; font-size: 13px; font-weight: 560; color: var(--text); line-height: 1.42; }
    .card-context { margin-top: 8px; display: flex; flex-direction: column; gap: 5px; }
    .card-task { display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--text-dim); min-width: 0; }
    .card-task span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .card-prog { display: flex; align-items: center; gap: 8px; }
    .progress-track { flex: 1; height: 4px; border-radius: 999px; background: var(--bar-empty); overflow: hidden; }
    .progress-fill {
      height: 100%;
      background: var(--green);
      border-radius: 999px;
      transition: width var(--dur-data) var(--ease-out);
    }
    .prog-num { font-family: var(--mono); font-size: 11px; color: var(--text-faint); }
    .card-foot { margin-top: 9px; display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--text-faint); }

    .repo-section {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-card);
      padding: 14px 16px;
      margin-bottom: 12px;
    }
    .repo-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding-bottom: 10px;
      margin-bottom: 12px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .repo-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
      gap: 10px;
    }

    .list-wrap {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-card);
      overflow-x: auto;
    }
    .list-table { width: 100%; border-collapse: collapse; font-size: 12.5px; min-width: 720px; }
    .list-table th {
      text-align: left;
      padding: 8px 8px;
      font-size: 11px;
      font-weight: 600;
      color: var(--text-faint);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    .list-table td { padding: 8px 8px; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
    .list-table tbody tr {
      cursor: pointer;
      transition: background var(--dur-micro) var(--ease-snap);
    }
    .list-table tbody tr:hover { background: var(--bg-tile); }
    .list-table tbody tr.is-selected { background: var(--bg-row-active); }
    .list-table tbody tr:last-child td { border-bottom: 0; }

    /* Slide-Over Inspector Drawer (Used in Secondary Views) */
    .inspector-overlay {
      position: fixed;
      inset: 0;
      z-index: 50;
      background: rgba(0, 0, 0, 0.36);
      backdrop-filter: blur(3px);
      -webkit-backdrop-filter: blur(3px);
      visibility: hidden;
      opacity: 0;
      pointer-events: none;
      transition: opacity var(--dur-state) var(--ease-out), visibility 0s linear var(--dur-state);
    }
    .inspector-overlay.open {
      visibility: visible;
      opacity: 1;
      pointer-events: auto;
      transition: opacity var(--dur-surface) var(--ease-out), visibility 0s;
    }
    .inspector-panel {
      position: fixed;
      top: 12px;
      right: 12px;
      bottom: 12px;
      width: var(--inspector-width, 460px);
      max-width: calc(100vw - 24px);
      z-index: 60;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-shell);
      box-shadow: var(--shadow-panel);
      display: flex;
      flex-direction: column;
      visibility: hidden;
      transform: translate3d(calc(100% + 24px), 0, 0);
      transition: transform var(--dur-surface) var(--ease-spring), width var(--dur-surface) var(--ease-spring), visibility 0s linear var(--dur-surface);
    }
    .inspector-panel.open {
      visibility: visible;
      transform: translate3d(0, 0, 0);
      transition: transform var(--dur-surface) var(--ease-spring), width var(--dur-surface) var(--ease-spring), visibility 0s;
    }
    .inspector-panel.is-resizing {
      transition: none !important;
      user-select: none;
    }
    .inspector-content {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }
    .inspector-resizer {
      position: absolute;
      top: 14px;
      bottom: 14px;
      left: -6px;
      width: 12px;
      cursor: col-resize;
      z-index: 5;
      display: flex;
      align-items: center;
      justify-content: center;
      touch-action: none;
    }
    .inspector-resizer::after {
      content: "";
      width: 3px;
      height: 36px;
      border-radius: 999px;
      background: var(--border-strong);
      opacity: 0.28;
      transition: opacity var(--dur-micro) var(--ease-snap), background var(--dur-micro) var(--ease-snap), height var(--dur-micro) var(--ease-snap);
    }
    .inspector-resizer:hover::after,
    .inspector-panel.is-resizing .inspector-resizer::after {
      opacity: 1;
      height: 48px;
      background: var(--accent);
    }
    @media (max-width: 600px) {
      .inspector-resizer { display: none; }
      .inspector-panel {
        top: auto;
        left: 8px;
        right: 8px;
        bottom: 8px;
        width: auto !important;
        max-width: none;
        max-height: 86vh;
        border-radius: 18px;
        transform: translate3d(0, calc(100% + 24px), 0);
      }
      .inspector-panel.open { transform: translate3d(0, 0, 0); }
    }
    .inspector-hdr {
      padding: 16px 18px 13px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .inspector-title { margin: 6px 0 0; font-size: 15px; font-weight: 600; line-height: 1.4; }
    .inspector-body { flex: 1; overflow-y: auto; padding: 15px 18px 22px; }
    .meta-grid {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
    }
    .meta-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12px; }
    .meta-key { color: var(--text-faint); flex-shrink: 0; width: 64px; }
    .meta-val { font-family: var(--mono); font-size: 11.5px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; text-align: right; }

    .handoff-box {
      margin-top: 12px;
      padding: 11px 12px;
      border-radius: 10px;
      background: var(--accent-soft);
      border: 1px solid var(--accent-ring);
    }
    .handoff-box-hdr { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11.5px; font-weight: 600; color: var(--accent); }
    .handoff-pre { margin: 7px 0 0; font-family: var(--mono); font-size: 11.2px; line-height: 1.5; color: var(--text); white-space: pre-wrap; word-break: break-word; }

    .cmd-box { margin-top: 10px; padding: 10px 12px; border-radius: 10px; background: var(--bg-well); border: 1px solid var(--border-subtle); }
    .cmd-box-hdr { display: flex; align-items: center; justify-content: space-between; font-size: 11.5px; color: var(--text-faint); margin-bottom: 4px; }
    .cmd-code { font-family: var(--mono); font-size: 11.5px; color: var(--accent); word-break: break-all; }

    .tabs {
      position: relative;
      display: flex;
      gap: 4px;
      margin-top: 14px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .tab-btn {
      appearance: none;
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: var(--text-dim);
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 550;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      position: relative;
      transition: color var(--dur-micro) var(--ease-snap), border-color var(--dur-state) var(--ease-spring), transform var(--dur-press) var(--ease-snap);
    }
    .tab-btn:hover { color: var(--text); }
    .tab-btn:active { transform: scale(0.97); transition-duration: var(--dur-press); }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tabs.has-indicator .tab-btn.active { border-bottom-color: transparent; }
    .tabs .seg-indicator.is-underline {
      top: auto;
      bottom: -1px;
      height: 2px;
      border-radius: 2px;
      background: var(--accent);
      box-shadow: none;
    }
    .tab-pane { margin-top: 12px; }
    .task-row { padding: 9px 11px; border-radius: 9px; border: 1px solid var(--border-subtle); background: var(--bg-well); margin-bottom: 7px; }
    .task-row-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: 540; }
    .task-row-sub { margin-top: 4px; font-size: 11px; color: var(--text-faint); display: flex; flex-wrap: wrap; gap: 10px; }

    .file-list { border: 1px solid var(--border-subtle); border-radius: 9px; background: var(--bg-well); overflow: hidden; }
    .file-row { display: flex; align-items: center; gap: 9px; padding: 7px 10px; font-family: var(--mono); font-size: 11.5px; border-bottom: 1px solid var(--border-subtle); }
    .file-row:last-child { border-bottom: 0; }
    .file-code { min-width: 24px; text-align: center; padding: 1px 5px; border-radius: 4px; font-size: 10.5px; font-weight: 700; background: var(--bg-tile-active); color: var(--accent); }
    .file-code.untracked { color: var(--green); background: var(--green-soft); }
    .file-code.deleted { color: var(--red); background: var(--red-soft); }

    .empty-state {
      text-align: center;
      padding: 46px 24px;
      background: var(--bg-card);
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius-card);
      color: var(--text-dim);
    }
    .empty-state.is-error {
      border-style: solid;
      border-color: rgba(248, 113, 113, 0.36);
    }
    .empty-cmds { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 14px; }
    .empty-cmd { font-family: var(--mono); font-size: 12px; padding: 5px 10px; border-radius: 7px; background: var(--bg-well); border: 1px solid var(--border); color: var(--text); }

    .warnings-box {
      display: flex;
      align-items: flex-start;
      gap: 9px;
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid rgba(251, 191, 36, 0.32);
      background: var(--amber-soft);
      color: var(--amber);
      font-size: 12px;
    }
    .alert-collapse-wrap {
      display: grid;
      grid-template-rows: 1fr;
      transition: grid-template-rows 240ms var(--ease-out), opacity 180ms var(--ease-out), transform 220ms var(--ease-out);
    }
    .alert-collapse-wrap.is-entering {
      animation: fadeSlideIn var(--dur-state) var(--ease-out) both;
    }
    .alert-collapse-wrap.is-collapsing {
      grid-template-rows: 0fr;
      opacity: 0;
      transform: translate3d(0, -4px, 0);
      pointer-events: none;
    }
    .alert-collapse-inner {
      overflow: hidden;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .auth-alert-box {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 12px 16px;
      border-radius: 12px;
      border: 1px solid var(--border-strong);
      border-left: 3px solid var(--amber);
      background: var(--bg-card);
      color: var(--text);
      font-size: 12.5px;
    }
    .auth-alert-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
    }
    .auth-alert-main {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      min-width: 0;
    }
    .auth-alert-form {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }
    .token-input {
      flex: 1;
      min-width: 220px;
      height: 34px;
      padding: 0 11px;
      border-radius: 8px;
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      outline: none;
      transition: border-color var(--dur-micro) var(--ease-snap), box-shadow var(--dur-micro) var(--ease-snap);
    }
    .token-input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    .token-input.is-invalid-shake {
      border-color: var(--red);
      box-shadow: 0 0 0 3px var(--red-soft);
      animation: invalidShake 280ms var(--ease-out);
    }
    @keyframes invalidShake {
      0%, 100% { transform: translateX(0); }
      20% { transform: translateX(-5px); }
      40% { transform: translateX(4px); }
      60% { transform: translateX(-3px); }
      80% { transform: translateX(2px); }
    }
    @keyframes fadeSlideIn {
      from { opacity: 0; transform: translate3d(0, 4px, 0); }
      to { opacity: 1; transform: translate3d(0, 0, 0); }
    }
    .token-input::placeholder { font-family: var(--sans); color: var(--text-faint); }
    .auth-err-msg {
      font-size: 11.5px;
      color: var(--red);
      margin-top: 2px;
      animation: fadeSlideIn var(--dur-micro) var(--ease-out) both;
    }
    .policy-check-row {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 12px;
      color: var(--text-dim);
      cursor: pointer;
      user-select: none;
      margin-top: 2px;
    }
    .policy-check-row input[type="checkbox"] {
      accent-color: var(--accent);
      cursor: pointer;
    }
    .policy-section {
      padding: 12px 14px;
      border-radius: 13px;
      border: 1px solid var(--border);
      background: var(--bg-well);
      display: flex;
      flex-direction: column;
      gap: 9px;
    }
    .policy-section-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    .policy-repo-list {
      display: flex;
      flex-direction: column;
      gap: 7px;
    }
    .policy-repo-row {
      padding: 8px 10px;
      border-radius: 9px;
      border: 1px solid var(--border-subtle);
      background: var(--bg-card);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .btn-warn {
      background: var(--amber-soft);
      border-color: rgba(251, 191, 36, 0.36);
      color: var(--amber);
    }
    .btn-warn:hover {
      background: rgba(251, 191, 36, 0.22);
    }
    .sb-policy-btn {
      appearance: none;
      border: 1px solid rgba(251, 191, 36, 0.38);
      background: var(--amber-soft);
      color: var(--amber);
      border-radius: 5px;
      padding: 1px 5px;
      font-size: 10px;
      font-weight: 650;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 3px;
      flex-shrink: 0;
      transition: background var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .sb-policy-btn:hover { background: rgba(251, 191, 36, 0.24); }
    .sb-policy-btn:active:not(:disabled) { transform: scale(0.96); transition-duration: var(--dur-press); }
    .sb-policy-btn:disabled { opacity: 0.55; cursor: wait; }

    /* Focus-visible Ring for Keyboard Navigation */
    .btn:focus-visible,
    .icon-btn:focus-visible,
    .cluster-icon-btn:focus-visible,
    .sb-tile:focus-visible,
    .sb-item:focus-visible,
    .forge-status-btn:focus-visible,
    .wizard-nav-btn:focus-visible,
    .console-tab:focus-visible,
    .tab-btn:focus-visible,
    .copy-chip:focus-visible,
    .sb-policy-btn:focus-visible,
    .ghost-link-btn:focus-visible,
    .am-seg-btn:focus-visible,
    .am-header-pill:focus-visible,
    button.bento-metric:focus-visible,
    a.forge-chip:focus-visible {
      outline: 2px solid var(--accent-ring);
      outline-offset: 2px;
    }

    /* Auto-Merge Switch, 3-State Segmented Control & Header Pill */
    .am-toggle-switch {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      user-select: none;
    }
    .am-toggle-switch input {
      position: absolute;
      opacity: 0;
      width: 0;
      height: 0;
    }
    .am-toggle-track {
      width: 34px;
      height: 20px;
      border-radius: 999px;
      background: var(--bg-tile-active);
      border: 1px solid var(--border-strong);
      position: relative;
      transition: background var(--dur-state) var(--ease-in-out), border-color var(--dur-state) var(--ease-in-out);
      flex-shrink: 0;
    }
    .am-toggle-track::after {
      content: "";
      position: absolute;
      top: 2px;
      left: 2px;
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: var(--text-dim);
      transition: transform var(--dur-state) var(--ease-spring), background var(--dur-state) var(--ease-in-out);
    }
    .am-toggle-switch input:checked + .am-toggle-track {
      background: var(--green-soft);
      border-color: rgba(74, 222, 128, 0.45);
    }
    .am-toggle-switch input:checked + .am-toggle-track::after {
      transform: translateX(14px);
      background: var(--green);
    }
    .am-toggle-switch input:focus-visible + .am-toggle-track {
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    .am-toggle-switch input:disabled + .am-toggle-track {
      opacity: 0.55;
      cursor: wait;
    }
    .am-toggle-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-dim);
      transition: color var(--dur-micro) var(--ease-in-out);
    }
    .am-toggle-switch input:checked ~ .am-toggle-label {
      color: var(--green);
    }
    .am-seg-group {
      position: relative;
      display: inline-flex;
      padding: 2px;
      gap: 2px;
      border-radius: 8px;
      background: var(--bg-well);
      border: 1px solid var(--border);
      flex-shrink: 0;
    }
    .am-seg-btn {
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--text-dim);
      height: 22px;
      padding: 0 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 560;
      cursor: pointer;
      position: relative;
      z-index: 1;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .am-seg-btn:hover:not(:disabled) {
      color: var(--text);
      background: var(--bg-tile);
    }
    .am-seg-btn:active:not(:disabled) { transform: scale(0.96); transition-duration: var(--dur-press); }
    .am-seg-btn.active {
      background: var(--bg-tile-active);
      color: var(--text);
      font-weight: 650;
    }
    .am-seg-btn.active.is-on {
      background: var(--green-soft);
      color: var(--green);
    }
    .am-seg-btn.active.is-off {
      background: var(--bg-inset);
      color: var(--text-dim);
    }
    .am-seg-group.has-indicator .am-seg-btn.active { background: transparent; }
    .am-seg-group .seg-indicator { border-radius: 6px; background: var(--bg-tile-active); box-shadow: none; }
    .am-seg-group .seg-indicator.is-on { background: var(--green-soft); }
    .am-seg-group .seg-indicator.is-off { background: var(--bg-inset); }
    .am-seg-btn:disabled {
      opacity: 0.55;
      cursor: wait;
    }
    .am-header-pill {
      appearance: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--bg-tile);
      color: var(--text-dim);
      font-size: 11.5px;
      font-weight: 560;
      cursor: pointer;
      transition: background var(--dur-micro) var(--ease-snap), border-color var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .am-header-pill:hover:not(:disabled) {
      background: var(--bg-tile-active);
      color: var(--text);
      border-color: var(--border-strong);
    }
    .am-header-pill:active:not(:disabled) { transform: scale(0.97); transition-duration: var(--dur-press); }
    .am-header-pill.is-on {
      background: var(--green-soft);
      border-color: rgba(74, 222, 128, 0.36);
      color: var(--green);
    }
    .am-header-pill:disabled {
      opacity: 0.55;
      cursor: wait;
    }
    .am-dot {
      position: relative;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--text-faint);
      flex-shrink: 0;
      transition: background var(--dur-state) var(--ease-in-out);
    }
    .am-header-pill.is-on .am-dot {
      background: var(--green);
    }

    /* PR Auto-Approve Confirmation Warning Modal */
    .am-confirm-overlay {
      z-index: 95;
    }
    .am-confirm-modal {
      width: 480px;
      max-width: 100%;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: 16px;
      box-shadow: var(--shadow-panel);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      opacity: 0;
      transform: translate3d(0, 12px, 0) scale(0.975);
      transition: transform var(--dur-surface) var(--ease-spring), opacity var(--dur-state) var(--ease-out);
    }
    .am-confirm-overlay.open .am-confirm-modal {
      opacity: 1;
      transform: translate3d(0, 0, 0) scale(1);
    }
    .am-confirm-hdr {
      padding: 16px 20px 14px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }
    .am-confirm-icon {
      width: 34px;
      height: 34px;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .am-confirm-icon.is-warn {
      background: var(--amber-soft);
      border: 1px solid rgba(251, 191, 36, 0.36);
      color: var(--amber);
    }
    .am-confirm-icon.is-info {
      background: var(--accent-soft);
      border: 1px solid var(--accent-ring);
      color: var(--accent);
    }
    .am-confirm-title {
      margin: 0;
      font-size: 15px;
      font-weight: 650;
      color: var(--text);
      line-height: 1.35;
    }
    .am-confirm-sub {
      margin: 3px 0 0;
      font-size: 12px;
      color: var(--text-dim);
      line-height: 1.45;
    }
    .am-confirm-body {
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      font-size: 12.5px;
      color: var(--text-dim);
      line-height: 1.55;
    }
    .am-confirm-scope {
      padding: 8px 11px;
      border-radius: 9px;
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
      color: var(--text);
      font-size: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    .am-confirm-list {
      margin: 0;
      padding-left: 18px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .am-confirm-list strong {
      color: var(--text);
    }
    .am-confirm-note {
      padding: 9px 11px;
      border-radius: 9px;
      font-size: 11.5px;
      line-height: 1.5;
    }
    .am-confirm-note.is-warn {
      background: var(--amber-soft);
      border: 1px solid rgba(251, 191, 36, 0.28);
      color: var(--text);
    }
    .am-confirm-note.is-info {
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
      color: var(--text-dim);
    }
    .am-confirm-ftr {
      padding: 12px 20px;
      border-top: 1px solid var(--border-subtle);
      background: var(--bg-well);
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
    }
    .btn-danger-warn {
      background: var(--amber);
      border-color: var(--amber);
      color: #111827;
      font-weight: 650;
    }
    .btn-danger-warn:hover:not(:disabled) {
      filter: brightness(0.95);
    }
    html[data-theme="light"] .btn-danger-warn {
      background: #d97706;
      border-color: #d97706;
      color: #ffffff;
    }

    /* Setup & Quickstart Onboarding Wizard Modal (Clean Minimalist Hierarchy) */
    .modal-overlay {
      position: fixed;
      inset: 0;
      z-index: 85;
      background: rgba(0, 0, 0, 0.56);
      backdrop-filter: blur(4px);
      -webkit-backdrop-filter: blur(4px);
      display: grid;
      place-items: center;
      padding: 16px;
      visibility: hidden;
      opacity: 0;
      pointer-events: none;
      transition: opacity var(--dur-exit) var(--ease-out), visibility 0s linear var(--dur-exit);
    }
    .modal-overlay.open {
      visibility: visible;
      opacity: 1;
      pointer-events: auto;
      transition: opacity var(--dur-state) var(--ease-out), visibility 0s;
    }
    .setup-modal {
      width: 640px;
      max-width: 100%;
      max-height: calc(100vh - 32px);
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: 18px;
      box-shadow: var(--shadow-panel);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transform: translate3d(0, 10px, 0) scale(0.975);
      transition: transform var(--dur-surface) var(--ease-spring);
    }
    .modal-overlay.open .setup-modal { transform: translate3d(0, 0, 0) scale(1); }
    .setup-hdr {
      padding: 18px 22px 16px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .setup-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .wizard-nav {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px;
      border-radius: 10px;
      background: var(--bg-well);
      border: 1px solid var(--border-subtle);
    }
    .wizard-nav-btn {
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--text-dim);
      border-radius: 7px;
      height: 28px;
      padding: 0 12px;
      font-size: 12px;
      font-weight: 560;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      position: relative;
      z-index: 1;
      transition: background var(--dur-micro) var(--ease-snap), color var(--dur-micro) var(--ease-snap), box-shadow var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .wizard-nav-btn:hover { color: var(--text); }
    .wizard-nav-btn:active { transform: scale(0.97); transition-duration: var(--dur-press); }
    .wizard-nav-btn.active {
      background: var(--bg-card);
      color: var(--text);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.16);
    }
    .wizard-nav.has-indicator .wizard-nav-btn.active {
      background: transparent;
      box-shadow: none;
    }
    .wizard-nav .seg-indicator {
      border-radius: 7px;
      background: var(--bg-card);
      box-shadow: var(--shadow-pill);
    }
    .wizard-pane-next > * { animation: wizardSlideNext var(--dur-state) var(--ease-out) both; }
    .wizard-pane-prev > * { animation: wizardSlidePrev var(--dur-state) var(--ease-out) both; }
    .card-reveal { animation: fadeSlideIn var(--dur-state) var(--ease-out) both; }
    @keyframes wizardSlideNext {
      from { opacity: 0; transform: translate3d(10px, 0, 0); }
      to { opacity: 1; transform: translate3d(0, 0, 0); }
    }
    @keyframes wizardSlidePrev {
      from { opacity: 0; transform: translate3d(-10px, 0, 0); }
      to { opacity: 1; transform: translate3d(0, 0, 0); }
    }
    .wizard-num {
      width: 17px;
      height: 17px;
      border-radius: 50%;
      display: inline-grid;
      place-items: center;
      font-size: 10.5px;
      font-weight: 700;
      background: var(--bg-tile-active);
      color: var(--text-dim);
      transition: background var(--dur-state) var(--ease-in-out), color var(--dur-state) var(--ease-in-out);
    }
    .wizard-nav-btn.active .wizard-num {
      background: var(--accent);
      color: #ffffff;
    }
    .setup-title { margin: 0; font-size: 16.5px; font-weight: 650; letter-spacing: -0.02em; }
    .setup-sub { margin: 3px 0 0; font-size: 12.5px; color: var(--text-dim); }
    .setup-body {
      padding: 18px 22px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .host-card {
      padding: 16px 18px;
      border-radius: 14px;
      border: 1px solid var(--border-strong);
      background: var(--bg-well);
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .host-card-hdr {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .host-ident {
      display: flex;
      align-items: flex-start;
      gap: 11px;
      min-width: 0;
    }
    .host-ic {
      width: 34px;
      height: 34px;
      border-radius: 9px;
      display: grid;
      place-items: center;
      flex-shrink: 0;
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text);
    }
    .host-ic.sm { width: 26px; height: 26px; border-radius: 7px; }
    .host-ic.is-gitlab {
      background: rgba(251, 146, 60, 0.14);
      border-color: rgba(251, 146, 60, 0.28);
      color: #fb923c;
    }
    html[data-theme="light"] .host-ic.is-gitlab {
      background: rgba(234, 88, 12, 0.09);
      border-color: rgba(234, 88, 12, 0.24);
      color: #c2410c;
    }
    .host-ic.is-github {
      background: rgba(243, 244, 246, 0.09);
      border-color: rgba(243, 244, 246, 0.18);
      color: var(--text);
    }
    html[data-theme="light"] .host-ic.is-github {
      background: rgba(15, 23, 42, 0.06);
      border-color: rgba(15, 23, 42, 0.14);
      color: #111827;
    }
    .host-title-line {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 13.5px;
      font-weight: 620;
      color: var(--text);
    }
    .host-url-link {
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 450;
      color: var(--text-dim);
      transition: color var(--dur-micro) var(--ease-snap);
    }
    .host-url-link:hover { color: var(--accent); }
    .host-repo-list {
      margin-top: 4px;
      font-size: 11.5px;
      color: var(--text-faint);
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 4px 8px;
    }
    .host-repo-link {
      color: var(--text-dim);
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 2px;
      transition: color var(--dur-micro) var(--ease-snap);
    }
    .host-repo-link svg { transition: transform var(--dur-micro) var(--ease-snap); }
    .host-repo-link:hover { color: var(--accent); }
    .host-repo-link:hover svg { transform: translate(1.5px, -1.5px); }
    .host-flow {
      padding-top: 13px;
      border-top: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 13px;
    }
    .flow-step {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .flow-step-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .flow-step-title {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12.5px;
      font-weight: 600;
      color: var(--text);
    }
    .flow-num {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      display: inline-grid;
      place-items: center;
      font-size: 10.5px;
      font-weight: 700;
      background: var(--accent-soft);
      color: var(--accent);
      flex-shrink: 0;
    }
    .perm-box {
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 5px;
      font-size: 12px;
      line-height: 1.5;
      color: var(--text-dim);
    }
    .perm-row {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      color: var(--text);
    }
    .perm-tag {
      font-family: var(--mono);
      font-size: 11.5px;
      font-weight: 650;
      padding: 1px 7px;
      border-radius: 6px;
      background: var(--green-soft);
      color: var(--green);
      border: 1px solid rgba(74, 222, 128, 0.28);
    }
    .perm-sub { font-size: 11.5px; color: var(--text-faint); }
    .host-row-compact {
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: var(--bg-well);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
    }
    .ghost-link-btn {
      appearance: none;
      border: 0;
      background: transparent;
      color: var(--text-dim);
      font-size: 12px;
      font-weight: 550;
      padding: 4px 2px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: color var(--dur-micro) var(--ease-snap), transform var(--dur-press) var(--ease-snap);
    }
    .ghost-link-btn:hover { color: var(--accent); }
    .ghost-link-btn:active { transform: scale(0.97); transition-duration: var(--dur-press); }
    .guide-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    @media (max-width: 660px) {
      .guide-grid { grid-template-columns: 1fr; }
    }
    .guide-card {
      padding: 14px 16px;
      border-radius: 13px;
      border: 1px solid var(--border);
      background: var(--bg-well);
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .guide-card-top {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .guide-step-pill {
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 6px;
      background: var(--accent-soft);
      color: var(--accent);
      flex-shrink: 0;
    }
    .guide-card-title { font-size: 13.5px; font-weight: 620; color: var(--text); }
    .guide-card-desc { font-size: 12px; color: var(--text-dim); line-height: 1.55; }
    .guide-card-cmd {
      margin-top: auto;
      padding: 6px 9px;
      border-radius: 7px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      font-family: var(--mono);
      font-size: 11.2px;
      color: var(--accent);
    }
    .setup-ftr {
      padding: 13px 22px;
      border-top: 1px solid var(--border-subtle);
      background: var(--bg-sidebar);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
    }

    .footer {
      padding: 2px 6px;
      font-size: 11.5px;
      color: var(--text-faint);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }

    .toast-wrap { position: fixed; right: 20px; bottom: 20px; z-index: 80; display: flex; flex-direction: column; align-items: flex-end; gap: 8px; pointer-events: none; }
    .toast {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 13px;
      border-radius: 10px;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      box-shadow: var(--shadow-panel);
      opacity: 0;
      transform: translate3d(0, 12px, 0) scale(0.96);
      transition: opacity var(--dur-state) var(--ease-out), transform var(--dur-state) var(--ease-spring);
    }
    .toast.is-visible {
      opacity: 1;
      transform: translate3d(0, 0, 0) scale(1);
    }
    .toast.is-leaving {
      opacity: 0;
      transform: translate3d(0, -4px, 0) scale(0.98);
      transition: opacity var(--dur-exit) var(--ease-out), transform var(--dur-exit) var(--ease-out);
    }

    @media (max-width: 780px) {
      .app-shell { flex-direction: column; }
      .sidebar { width: 100% !important; }
      body.sidebar-collapsed .sidebar { padding: 10px 12px; }
      body.sidebar-collapsed .sb-nav,
      body.sidebar-collapsed .sb-tiles,
      body.sidebar-collapsed .sb-list {
        flex-direction: row;
        flex-wrap: wrap;
        justify-content: center;
      }
      body.sidebar-collapsed .sb-footer { justify-content: center; }
    }
    @media (max-width: 600px) {
      .toast-wrap { left: 12px; right: 12px; bottom: 14px; align-items: center; }
      .toast { max-width: 100%; }
    }
  </style>
</head>
<body>
  <div id="top-progress" class="top-progress is-active" aria-hidden="true"><div class="top-progress-bar"></div></div>
  <div class="app-shell">
    <!-- Left Inset Sidebar -->
    <aside class="sidebar" aria-label="工作区侧栏">
      <div id="search-wrap" class="sb-search">
        <span class="sb-search-ic" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
        </span>
        <input id="search-input" class="hide-collapsed" type="search" placeholder="搜索 #编号、目录、分支" />
        <span class="sb-kbd hide-collapsed">/</span>
        <button id="search-clear" class="sb-search-clear hide-collapsed" type="button" aria-label="清空搜索">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div id="sb-filters" class="sb-nav"></div>

      <div class="sb-tiles" role="tablist" aria-label="视图切换">
        <button id="view-cockpit" class="sb-tile active" type="button" title="驾驶舱视图（工作树 + 接力台）"></button>
        <button id="view-kanban" class="sb-tile" type="button" title="四列看板视图"></button>
        <button id="view-repos" class="sb-tile" type="button" title="按仓库分组视图"></button>
        <button id="view-list" class="sb-tile" type="button" title="紧凑列表视图"></button>
      </div>

      <div class="sb-divider"></div>
      <div class="sb-section-hdr hide-collapsed"><span id="sb-hdr-repos">仓库</span><span id="sb-repo-cnt" class="num">…</span></div>
      <div id="repo-pills" class="sb-list"></div>

      <div class="sb-section-hdr hide-collapsed" style="margin-top:4px;"><span id="sb-hdr-wts">并行目录</span><span id="sb-wt-cnt" class="num">…</span></div>
      <div id="wt-rail-list" class="sb-list"></div>

      <div class="sb-footer">
        <button id="theme-btn" class="sb-item" type="button" title="切换深浅色主题"></button>
        <button id="lang-btn" class="btn btn-xs hide-collapsed" type="button" title="Switch language / 切换语言">EN</button>
        <span class="sb-meta hide-collapsed">v__IDD_VERSION__</span>
      </div>
    </aside>

    <!-- Right Main Cockpit Workspace -->
    <div class="workspace">
      <header class="ws-header">
        <div class="ws-title-group">
          <button id="sidebar-toggle" class="icon-btn" type="button" title="收起 / 展开侧栏 ([)">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="3"></rect>
              <line x1="9" y1="3" x2="9" y2="21"></line>
            </svg>
          </button>
          <div id="ws-logo" class="ws-logo" aria-hidden="true">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="6" y1="3" x2="6" y2="15"></line><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M18 9a9 9 0 0 1-9 9"></path>
            </svg>
          </div>
          <h1 id="ws-title" class="ws-title">全局工作区</h1>
          <span id="scope-tag" class="ws-scope" style="display:none;"></span>
          <span id="ws-repo-link-wrap"></span>
        </div>
        <div class="ws-controls">
          <div id="status-cluster" class="status-cluster">
            <div class="status-cluster-live">
              <span id="conn-tag" class="live-pill is-loading">
                <span class="dot-pulse"></span>
                <span>初始化中</span>
                <span class="sep live-sep">·</span>
                <span id="updated-tag" class="num live-clock">扫描仓库...</span>
              </span>
              <button id="pause-btn" class="cluster-icon-btn" type="button" title="暂停自动轮询" aria-label="暂停自动轮询"></button>
            </div>
            <span class="status-cluster-sep" aria-hidden="true"></span>
            <div id="forge-status-group" class="forge-status-group"></div>
            <div id="forge-status-popover" class="status-popover" role="dialog" aria-label="托管平台连接详情" aria-hidden="true"></div>
          </div>
          <button id="setup-btn" class="btn" type="button"></button>
          <button id="sync-btn" class="btn btn-primary" type="button" title="快捷键 r"></button>
        </div>
      </header>

      <div id="top-alerts-wrap"></div>

      <section id="kpis" class="telemetry-grid"></section>

      <main id="main-content"></main>
      <div id="warnings-wrap"></div>
      <footer id="footer" class="footer"></footer>
    </div>
  </div>

  <div id="setup-modal-overlay" class="modal-overlay" aria-hidden="true">
    <div id="setup-modal" class="setup-modal" role="dialog" aria-modal="true" aria-label="初始化配置与上手指南"></div>
  </div>
  <div id="am-confirm-overlay" class="modal-overlay am-confirm-overlay" aria-hidden="true">
    <div id="am-confirm-modal" class="am-confirm-modal" role="alertdialog" aria-modal="true" aria-label="确认切换 PR 自动准入"></div>
  </div>
  <div id="inspector-overlay" class="inspector-overlay" aria-hidden="true"></div>
  <aside id="inspector-panel" class="inspector-panel" aria-label="任务详情抽屉" aria-hidden="true">
    <div id="inspector-resizer" class="inspector-resizer" role="separator" aria-orientation="vertical" aria-label="调整抽屉宽度" title="拖拽调整宽度（双击复位）"></div>
    <div id="inspector-content" class="inspector-content"></div>
  </aside>
  <div id="toast-wrap" class="toast-wrap" aria-live="polite"></div>

  <script>
    (function () {
      const ICONS = {
        github: '<path fill="currentColor" stroke="none" d="M12 .5C5.65.5.5 5.65.5 12c0 5.09 3.29 9.4 7.86 10.92.58.11.79-.25.79-.56 0-.28-.01-1.02-.02-2-3.2.7-3.88-1.54-3.88-1.54-.52-1.33-1.28-1.68-1.28-1.68-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.18-3.09-.12-.29-.51-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11.02 11.02 0 0 1 5.78 0c2.2-1.49 3.16-1.18 3.16-1.18.63 1.59.24 2.76.12 3.05.74.81 1.18 1.83 1.18 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14 0 1.55-.01 2.79-.01 3.17 0 .31.21.68.8.56A11.51 11.51 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z"/>',
        gitlab: '<path fill="currentColor" stroke="none" d="m22.4 13.76-1.48-4.55-2.95-9.05a.52.52 0 0 0-.98 0L14.28 8.45H9.72L7.01.16a.52.52 0 0 0-.98 0L3.08 9.21 1.6 13.76a1.06 1.06 0 0 0 .38 1.18L12 21.8l10.02-6.86a1.06 1.06 0 0 0 .38-1.18Z"/>',
        compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
        key: '<path d="m21 2-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
        terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
        branch: '<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
        pr: '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/>',
        checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
        xCircle: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
        clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        alertTriangle: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
        pause: '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
        play: '<polygon points="5 3 19 12 5 21 5 3"/>',
        refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
        sun: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
        moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
        columns: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>',
        folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
        list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
        cockpit: '<rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/>',
        copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
        check: '<polyline points="20 6 9 17 4 12"/>',
        externalLink: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
        x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
        activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
        layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
        sparkle: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z"/>',
        circle: '<circle cx="12" cy="12" r="8"/>',
        chevronRight: '<polyline points="9 18 15 12 9 6"/>'
      };

      function icon(name, size) {
        const s = size || 14;
        const body = ICONS[name] || "";
        return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + "</svg>";
      }

      function forgeIcon(forgeType, size) {
        if (forgeType === "github") return icon("github", size || 12);
        if (forgeType === "gitlab") return icon("gitlab", size || 12);
        return icon("terminal", size || 12);
      }

      const urlParams = new URLSearchParams(window.location.search);
      const queryLang = urlParams.get("lang");
      const initialLang = queryLang === "en" ? "en" : (queryLang === "zh" ? "zh" : (localStorage.getItem("idd_board_lang") === "en" ? "en" : "zh"));
      const state = {
        snapshot: null,
        selectedRepo: "ALL",
        viewMode: localStorage.getItem("idd_board_view") || "cockpit",
        sidebarCollapsed: urlParams.get("collapsed") === "1" || localStorage.getItem("idd_sidebar_collapsed") === "1",
        lang: initialLang,
        search: "",
        worktreeOnly: false,
        alertsOnly: false,
        todoOnly: false,
        paused: false,
        selectedKey: null,
        inspectedKey: null,
        didAutoInspect: false,
        didCheckOnboarding: false,
        setupOpen: false,
        setupTab: "auth",
        authStatus: null,
        authSavingHost: "",
        authErrors: {},
        tokenDrafts: {},
        editingHosts: {},
        showCustomHostForm: false,
        customHostForge: "gitlab",
        customHostUrl: "",
        customHostToken: "",
        autoRepoInit: true,
        repoInitRunning: {},
        repoInitErrors: {},
        repoInitBannerDismissed: false,
        autoMergeSaving: {},
        amConfirm: null,
        statusPopoverOpen: false,
        statusPopoverForge: "",
        lastForgeStatusSig: "",
        lastTopAlertsSig: "",
        consoleTab: "handoff",
        inspectorTab: "tasks",
        timerId: null,
        quickSyncTimerId: null,
        slowInitTimerId: null,
        fetching: false,
        manualRefreshing: false,
        hasLiveSnapshot: false,
        fromCache: false,
        initError: "",
        slowInit: false,
        lastClockStr: initialLang === "en" ? "Scanning..." : "扫描仓库...",
        lastSig: "",
        copiedFeedback: new Map(),
        shakeFieldKey: "",
        lastSyncBtnKey: "",
        lastPauseBtnKey: "",
        lastSetupBtnKey: "",
        indicatorRects: new Map(),
        prevProgressPct: new Map(),
        kpiPrevNums: { issue: null, pct: null, ready: null },
        kpiAnimFrames: new Map(),
        lastMainContextKey: "",
        hadRenderedData: false,
        setupTabAnimDir: "",
        revealModalCard: "",
        alertCollapseTimer: null
      };

      const SNAP_CACHE_KEY = "idd_board_last_snap:" + window.location.host;

      function loadCachedSnapshot() {
        if (urlParams.get("nocache") === "1") return null;
        try {
          const raw = sessionStorage.getItem(SNAP_CACHE_KEY);
          if (!raw) return null;
          const parsed = JSON.parse(raw);
          if (parsed && Array.isArray(parsed.repos) && Array.isArray(parsed.issues)) {
            return parsed;
          }
        } catch (_e) {
          /* ignore storage read errors */
        }
        return null;
      }

      function saveCachedSnapshot(snap) {
        if (!snap || !Array.isArray(snap.repos)) return;
        try {
          sessionStorage.setItem(SNAP_CACHE_KEY, JSON.stringify(snap));
        } catch (_e) {
          /* ignore quota or storage errors */
        }
      }

      function isEn() {
        return state.lang === "en";
      }

      function tr(zh, en) {
        return isEn() ? en : zh;
      }

      if (!["cockpit", "kanban", "repos", "list"].includes(state.viewMode)) {
        state.viewMode = "cockpit";
      }

      function escapeHtml(value) {
        return String(value == null ? "" : value)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }

      function safeUrl(raw) {
        if (typeof raw !== "string") return "";
        const trimmed = raw.trim();
        return /^https?:\/\//i.test(trimmed) ? trimmed : "";
      }

      function formatClock(ts) {
        if (!ts) return "—";
        const d = new Date(ts * 1000);
        return d.toLocaleTimeString(isEn() ? "en-GB" : "zh-CN", { hour12: false });
      }

      function showToast(msg, kind) {
        const wrap = document.getElementById("toast-wrap");
        if (!wrap) return;
        const el = document.createElement("div");
        el.className = "toast";
        const ic = kind === "err" ? icon("alertTriangle", 14) : icon("checkCircle", 14);
        const icColor = kind === "err" ? "var(--red)" : "var(--green)";
        el.innerHTML = '<span style="color:' + icColor + '">' + ic + "</span><span>" + escapeHtml(msg) + "</span>";
        wrap.appendChild(el);
        if (prefersReducedMotion()) {
          el.classList.add("is-visible");
        } else {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => el.classList.add("is-visible"));
          });
        }
        setTimeout(() => {
          el.classList.remove("is-visible");
          el.classList.add("is-leaving");
          let done = false;
          const cleanup = () => {
            if (done) return;
            done = true;
            el.remove();
          };
          el.addEventListener("transitionend", cleanup, { once: true });
          setTimeout(cleanup, 260);
        }, 1900);
      }

      function prefersReducedMotion() {
        return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
      }

      function syncSlidingIndicator(container, activeSelector, key, opts) {
        if (!container) return;
        const options = opts || {};
        const isUnderline = Boolean(options.underline);
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
          ind.setAttribute("aria-hidden", "true");
          container.insertBefore(ind, container.firstChild);
        }
        ind.className = "seg-indicator" + (isUnderline ? " is-underline" : "") + (options.toneClass ? " " + options.toneClass : "");
        container.classList.add("has-indicator");
        ind.style.opacity = "1";

        const applyRect = (r) => {
          ind.style.width = r.w + "px";
          if (!isUnderline) {
            ind.style.height = r.h + "px";
            ind.style.transform = "translate3d(" + r.x + "px," + r.y + "px,0)";
          } else {
            ind.style.transform = "translate3d(" + r.x + "px,0,0)";
          }
        };

        const prev = state.indicatorRects.get(key);
        const changed = prev && (prev.x !== target.x || prev.y !== target.y || prev.w !== target.w || prev.h !== target.h);
        if (prev && !changed && ind.style.width === target.w + "px" && ind.style.opacity === "1") {
          return;
        }
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

      function syncAllSlidingIndicators() {
        syncSlidingIndicator(document.querySelector(".sb-tiles"), ".sb-tile.active", "sb-tiles");
        syncSlidingIndicator(document.querySelector("#cockpit-console-slot .console-tabs"), ".console-tab.active", "console-tabs");
        syncSlidingIndicator(document.querySelector("#inspector-content .tabs"), ".tab-btn.active", "inspector-tabs", { underline: true });
        syncSlidingIndicator(document.querySelector("#setup-modal .wizard-nav"), ".wizard-nav-btn.active", "wizard-nav");
        document.querySelectorAll("#setup-modal .am-seg-group").forEach((grp, idx) => {
          const act = grp.querySelector(".am-seg-btn.active");
          const tone = act ? (act.classList.contains("is-on") ? "is-on" : (act.classList.contains("is-off") ? "is-off" : "")) : "";
          const gKey = "am-seg:" + ((act && act.getAttribute("data-am-repo-path")) || idx);
          syncSlidingIndicator(grp, ".am-seg-btn.active", gKey, { toneClass: tone });
        });
      }

      function animateNumber(el, fromVal, toVal, duration) {
        if (!el) return;
        const prevRaf = state.kpiAnimFrames.get(el);
        if (prevRaf) cancelAnimationFrame(prevRaf);
        if (prefersReducedMotion() || !Number.isFinite(fromVal) || !Number.isFinite(toVal) || fromVal === toVal) {
          el.textContent = String(toVal);
          return;
        }
        const dur = duration || 280;
        const t0 = performance.now();
        const step = (now) => {
          const p = Math.min(1, (now - t0) / dur);
          const eased = 1 - Math.pow(1 - p, 3);
          el.textContent = String(Math.round(fromVal + (toVal - fromVal) * eased));
          if (p < 1) {
            state.kpiAnimFrames.set(el, requestAnimationFrame(step));
          } else {
            state.kpiAnimFrames.delete(el);
          }
        };
        state.kpiAnimFrames.set(el, requestAnimationFrame(step));
      }

      function applyProgressTransitions(root) {
        const scope = root || document;
        const reduced = prefersReducedMotion();
        const pending = [];
        scope.querySelectorAll(".progress-fill[data-prog-key]").forEach((bar) => {
          const key = bar.getAttribute("data-prog-key");
          const target = Number(bar.getAttribute("data-prog-pct") || 0);
          const prev = state.prevProgressPct.get(key);
          if (prev !== undefined && prev !== target && !reduced) {
            bar.style.transition = "none";
            bar.style.width = prev + "%";
            pending.push({ bar, target });
          } else {
            bar.style.width = target + "%";
          }
          state.prevProgressPct.set(key, target);
        });
        if (pending.length) {
          void (scope.offsetWidth || document.body.offsetWidth);
          for (const entry of pending) {
            entry.bar.style.transition = "";
            entry.bar.style.width = entry.target + "%";
          }
        }
      }

      function preserveScroll(specs, fn) {
        const saved = [];
        for (const spec of specs) {
          const el = spec.root ? spec.root.querySelector(spec.selector) : document.querySelector(spec.selector);
          if (el) {
            saved.push({ spec, top: el.scrollTop, left: el.scrollLeft });
          }
        }
        fn();
        for (const item of saved) {
          const nextEl = item.spec.root ? item.spec.root.querySelector(item.spec.selector) : document.querySelector(item.spec.selector);
          if (nextEl) {
            nextEl.scrollTop = item.top;
            nextEl.scrollLeft = item.left;
          }
        }
      }

      function getCopyFeedbackKey(btnEl) {
        if (!btnEl) return "";
        const val = btnEl.getAttribute("data-copy-val") || "";
        const region = btnEl.closest("#inspector-panel")
          ? "inspector"
          : (btnEl.closest("#cockpit-console-slot") ? "console" : "main");
        const row = btnEl.closest("[data-select-key],[data-open-key]");
        const rowKey = row ? (row.getAttribute("data-select-key") || row.getAttribute("data-open-key") || "") : "";
        return region + "|" + rowKey + "|" + val;
      }

      function setButtonCopiedVisual(btnEl, animatePop) {
        if (!btnEl) return;
        if (!btnEl.dataset.prevHtml) {
          btnEl.dataset.prevHtml = btnEl.innerHTML;
        }
        btnEl.classList.add("copied");
        btnEl.classList.toggle("is-pop", Boolean(animatePop));
        btnEl.innerHTML = btnEl.classList.contains("btn-icon-only")
          ? icon("check", 12)
          : icon("check", 11) + "<span>" + tr("已复制", "Copied") + "</span>";
      }

      function applyCopiedStates(root) {
        const scope = root || document;
        const now = Date.now();
        for (const [k, entry] of state.copiedFeedback.entries()) {
          if (!entry || entry.expiresAt <= now) {
            state.copiedFeedback.delete(k);
          }
        }
        if (state.copiedFeedback.size === 0) return;
        scope.querySelectorAll("[data-copy-val]").forEach((btn) => {
          const key = getCopyFeedbackKey(btn);
          if (state.copiedFeedback.has(key)) {
            setButtonCopiedVisual(btn, false);
          }
        });
      }

      function triggerFieldShake(container, fieldKey) {
        if (!container || !fieldKey) return;
        const sel = fieldKey === "__custom__"
          ? "#custom-host-token"
          : '[data-token-draft="' + CSS.escape(fieldKey) + '"]';
        const inp = container.querySelector(sel);
        if (!inp) return;
        if (!prefersReducedMotion()) {
          inp.classList.remove("is-invalid-shake");
          void inp.offsetWidth;
          inp.classList.add("is-invalid-shake");
        }
        inp.focus();
      }

      async function copyText(text, btnEl, toastMsg) {
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
          } else {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
          }
          if (btnEl) {
            const copyKey = getCopyFeedbackKey(btnEl);
            const prevEntry = state.copiedFeedback.get(copyKey);
            if (prevEntry && prevEntry.timerId) clearTimeout(prevEntry.timerId);
            setButtonCopiedVisual(btnEl, true);
            const tid = setTimeout(() => {
              state.copiedFeedback.delete(copyKey);
              document.querySelectorAll("[data-copy-val]").forEach((cand) => {
                if (getCopyFeedbackKey(cand) === copyKey && cand.classList.contains("copied")) {
                  cand.classList.remove("copied", "is-pop");
                  if (cand.dataset.prevHtml) cand.innerHTML = cand.dataset.prevHtml;
                }
              });
            }, 1400);
            state.copiedFeedback.set(copyKey, { timerId: tid, expiresAt: Date.now() + 1400 });
          }
          showToast(toastMsg || tr("已复制到剪贴板", "Copied to clipboard"));
        } catch (err) {
          showToast(tr("复制失败: ", "Copy failed: ") + err.message, "err");
        }
      }

      function applyLang() {
        const en = isEn();
        document.documentElement.setAttribute("lang", en ? "en" : "zh-CN");
        document.title = en ? "IDD Live Worktree & Handoff Board" : "IDD 实时开发监控看板";
        const sb = document.querySelector("aside.sidebar");
        if (sb) sb.setAttribute("aria-label", tr("工作区侧栏", "Workspace sidebar"));
        const si = document.getElementById("search-input");
        if (si) si.placeholder = tr("搜索 #编号、目录、分支", "Search #id, dir, branch");
        const sc = document.getElementById("search-clear");
        if (sc) sc.setAttribute("aria-label", tr("清空搜索", "Clear search"));
        const tl = document.querySelector(".sb-tiles");
        if (tl) tl.setAttribute("aria-label", tr("视图切换", "View switcher"));
        const viewTitles = {
          "view-cockpit": tr("驾驶舱视图（工作树 + 接力台）", "Cockpit view (worktrees + handoff)"),
          "view-kanban": tr("四列看板视图", "Kanban columns view"),
          "view-repos": tr("按仓库分组视图", "Grouped by repository view"),
          "view-list": tr("紧凑列表视图", "Compact list view")
        };
        for (const [id, title] of Object.entries(viewTitles)) {
          const el = document.getElementById(id);
          if (el) el.title = title;
        }
        const rHdr = document.getElementById("sb-hdr-repos");
        if (rHdr) rHdr.textContent = tr("仓库", "Repositories");
        const wHdr = document.getElementById("sb-hdr-wts");
        if (wHdr) wHdr.textContent = tr("并行目录", "Worktrees");
        const tb = document.getElementById("theme-btn");
        if (tb) tb.title = tr("切换深浅色主题", "Toggle light/dark theme");
        const lb = document.getElementById("lang-btn");
        if (lb) {
          lb.textContent = en ? "中文" : "EN";
          lb.title = en ? "切换到中文" : "Switch to English";
        }
        const stg = document.getElementById("sidebar-toggle");
        if (stg) stg.title = tr("收起 / 展开侧栏 ([)", "Toggle sidebar ([)");
        const sy = document.getElementById("sync-btn");
        if (sy) sy.title = tr("快捷键 r", "Shortcut r");
        const fp = document.getElementById("forge-status-popover");
        if (fp) fp.setAttribute("aria-label", tr("托管平台连接详情", "Forge connection details"));
        const ip = document.getElementById("inspector-panel");
        if (ip) ip.setAttribute("aria-label", tr("任务详情抽屉", "Task details drawer"));
      }

      function applyTheme(theme, animate) {
        if (animate && !prefersReducedMotion()) {
          document.documentElement.classList.add("theme-transitioning");
          clearTimeout(window.__iddThemeTimer);
          window.__iddThemeTimer = setTimeout(() => {
            document.documentElement.classList.remove("theme-transitioning");
          }, 270);
        }
        document.documentElement.setAttribute("data-theme", theme);
        const btn = document.getElementById("theme-btn");
        if (btn) {
          const ic = theme === "dark" ? icon("sun", 14) : icon("moon", 14);
          const lbl = theme === "dark" ? tr("浅色模式", "Light") : tr("深色模式", "Dark");
          btn.innerHTML = '<span class="sb-item-left">' + ic + '<span class="hide-collapsed">' + lbl + "</span></span>";
          if (animate && !prefersReducedMotion()) {
            btn.classList.remove("icon-pop");
            void btn.offsetWidth;
            btn.classList.add("icon-pop");
          }
        }
      }

      function applySidebarState(userToggle) {
        if (userToggle && !state.sidebarCollapsed && !prefersReducedMotion()) {
          document.body.classList.add("sidebar-expanding");
          clearTimeout(window.__iddSbExpandTimer);
          window.__iddSbExpandTimer = setTimeout(() => {
            document.body.classList.remove("sidebar-expanding");
          }, 260);
        } else {
          document.body.classList.remove("sidebar-expanding");
        }
        document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
        const stg = document.getElementById("sidebar-toggle");
        if (stg) {
          stg.setAttribute("aria-expanded", state.sidebarCollapsed ? "false" : "true");
        }
      }

      function updateTopProgress() {
        const bar = document.getElementById("top-progress");
        if (!bar) return;
        const active =
          (!state.hasLiveSnapshot && !state.initError) ||
          Boolean(state.snapshot && state.snapshot.forge_syncing) ||
          state.manualRefreshing;
        bar.classList.toggle("is-active", Boolean(active));
      }

      function resolveForgeConnections() {
        const snap = state.snapshot;
        if (snap && snap.forge_connections && snap.forge_connections.github && snap.forge_connections.gitlab) {
          return snap.forge_connections;
        }
        const localOnly = Boolean(snap && snap.local_only);
        const authHosts = (state.authStatus && Array.isArray(state.authStatus.hosts)) ? state.authStatus.hosts : [];
        const repos = (snap && Array.isArray(snap.repos)) ? snap.repos : [];
        const out = {};
        for (const [fg, label] of [["github", "GitHub"], ["gitlab", "GitLab"]]) {
          const matchedHosts = authHosts.filter((h) => h.forge === fg);
          const matchedRepos = repos.filter((r) => r.forge === fg);
          const totalRepos = matchedRepos.length;
          const connectedRepos = matchedRepos.filter((r) => r.forge_connected).length;
          const syncingRepos = matchedRepos.filter((r) => r.forge_syncing).length;
          const authErrorRepos = matchedRepos.filter((r) => r.auth_alert).length;
          const errorRepos = matchedRepos.filter((r) => r.forge_error && !r.auth_alert).length;
          const configured = matchedHosts.some((h) => h.configured);
          let status = "unconfigured";
          if (localOnly) {
            status = (totalRepos > 0 || configured) ? "local_only" : "unconfigured";
          } else if (totalRepos > 0) {
            if (connectedRepos === totalRepos) status = "connected";
            else if (connectedRepos > 0) status = "partial";
            else if (authErrorRepos > 0) status = "auth_required";
            else if (errorRepos > 0) status = "error";
            else if (syncingRepos > 0) status = "syncing";
            else status = configured ? "syncing" : "auth_required";
          } else if (configured) {
            status = "connected";
          } else if (matchedHosts.length > 0) {
            status = "auth_required";
          }
          out[fg] = {
            forge: fg,
            label,
            status,
            configured,
            connected_repos: connectedRepos,
            total_repos: totalRepos,
            syncing_repos: syncingRepos,
            error_repos: errorRepos,
            auth_error_repos: authErrorRepos,
            last_synced_at: matchedRepos.reduce((mx, r) => Math.max(mx, Number(r.forge_fetched_at || 0)), 0),
            error: (matchedRepos.find((r) => r.forge_error) || {}).forge_error || "",
            hosts: matchedHosts.map((h) => ({
              host: h.host,
              api_base: h.api_base,
              status: h.configured ? status : "auth_required",
              configured: Boolean(h.configured),
              auth_source: h.auth_source || "missing",
              username: h.username || "",
              repo_count: (h.repos || []).length,
              connected_repos: 0,
              repos: (h.repos || []).map((x) => x.name),
              last_synced_at: 0,
              error: ""
            }))
          };
        }
        return out;
      }

      function forgeStatusBadgeMeta(status) {
        switch (status) {
          case "connected":
            return { cls: "is-connected", tone: "tone-success", shortText: "", longText: tr("已连接", "Connected") };
          case "syncing":
            return { cls: "is-syncing", tone: "tone-info", shortText: tr("同步中", "Syncing"), longText: tr("同步中", "Syncing") };
          case "auth_required":
            return { cls: "is-auth", tone: "tone-warning", shortText: tr("待配置", "Auth"), longText: tr("待配置令牌", "Token Required") };
          case "partial":
            return { cls: "is-partial", tone: "tone-warning", shortText: tr("部分异常", "Partial"), longText: tr("部分仓库异常", "Partially Connected") };
          case "error":
            return { cls: "is-error", tone: "tone-danger", shortText: tr("异常", "Error"), longText: tr("连接异常", "Connection Error") };
          case "local_only":
            return { cls: "is-local", tone: "tone-muted", shortText: tr("仅本地", "Local"), longText: tr("仅本地模式", "Local-Only") };
          default:
            return { cls: "is-unconfigured", tone: "tone-muted", shortText: tr("未配置", "Not set"), longText: tr("未配置", "Not Configured") };
        }
      }

      function formatAuthSourceLabel(authSource, username) {
        const tag = authSource === "gh_cli"
          ? "gh CLI"
          : (authSource === "env" ? "ENV" : (authSource === "hosts.json" ? "Token" : ""));
        if (username) {
          return "@" + username + (tag ? " · " + tag : "");
        }
        return tag || tr("未配置令牌", "No Token");
      }

      function renderForgeStatus(force) {
        const groupEl = document.getElementById("forge-status-group");
        const popEl = document.getElementById("forge-status-popover");
        if (!groupEl || !popEl) return;

        const conns = resolveForgeConnections();
        const snap = state.snapshot;
        const localOnly = Boolean(snap && snap.local_only);
        const syncingRemote = Boolean(snap && snap.forge_syncing);
        const sig = JSON.stringify({
          c: conns,
          po: state.statusPopoverOpen,
          pf: state.statusPopoverForge,
          lg: state.lang,
          pa: state.paused,
          lo: localOnly,
          fs: syncingRemote,
          ck: state.lastClockStr,
          sv: state.authSavingHost
        });
        if (!force && sig === state.lastForgeStatusSig) return;
        state.lastForgeStatusSig = sig;

        groupEl.innerHTML = ["github", "gitlab"].map((fg) => {
          const info = conns[fg] || { forge: fg, label: fg === "github" ? "GitHub" : "GitLab", status: "unconfigured", hosts: [] };
          const meta = forgeStatusBadgeMeta(info.status);
          const isOpen = state.statusPopoverOpen && (!state.statusPopoverForge || state.statusPopoverForge === fg);
          const hosts = Array.isArray(info.hosts) ? info.hosts : [];
          const primaryHost = hosts[0] || null;
          const tipParts = [info.label + "：" + meta.longText];
          if (primaryHost) {
            const hostStr = String(primaryHost.host || primaryHost.api_base || "");
            const whoStr = formatAuthSourceLabel(primaryHost.auth_source, primaryHost.username);
            tipParts.push(hostStr + " (" + whoStr + ")");
          }
          if (Number(info.total_repos || 0) > 0) {
            tipParts.push(tr("已连通仓库 ", "Connected repos ") + info.connected_repos + "/" + info.total_repos);
          }
          if (info.error) {
            tipParts.push(info.error);
          }
          tipParts.push(tr("点击查看连接详情", "Click for connection details"));
          return (
            '<button class="forge-status-btn is-' + fg + " " + meta.cls + (isOpen ? " is-open" : "") + '" type="button" data-forge-status="' + fg + '" aria-expanded="' + (isOpen ? "true" : "false") + '" title="' + escapeHtml(tipParts.join(" · ")) + '">' +
              '<span class="forge-status-dot" aria-hidden="true"></span>' +
              forgeIcon(fg, 12) +
              "<span>" + escapeHtml(info.label) + "</span>" +
              (meta.shortText ? '<span class="forge-status-state">' + escapeHtml(meta.shortText) + "</span>" : "") +
            "</button>"
          );
        }).join("");

        if (!state.statusPopoverOpen) {
          popEl.classList.remove("open");
          popEl.setAttribute("aria-hidden", "true");
          return;
        }

        popEl.classList.add("open");
        popEl.setAttribute("aria-hidden", "false");
        const pollStateLabel = state.paused
          ? tr("轮询已暂停", "Polling Paused")
          : (localOnly
              ? tr("仅本地模式 (--local-only)", "Local-Only Mode")
              : (syncingRemote ? tr("后台同步远端中...", "Syncing remote...") : tr("实时监控 · 2s 轮询", "Live · 2s polling")));
        const pollDotColor = state.paused ? "var(--amber)" : (localOnly ? "var(--text-faint)" : (syncingRemote ? "var(--accent)" : "var(--green)"));

        const cardsHtml = ["github", "gitlab"].map((fg) => {
          const info = conns[fg] || { forge: fg, label: fg === "github" ? "GitHub" : "GitLab", status: "unconfigured", hosts: [] };
          const meta = forgeStatusBadgeMeta(info.status);
          const isFocus = state.statusPopoverForge === fg;
          const hosts = Array.isArray(info.hosts) ? info.hosts : [];
          const repoSummary = Number(info.total_repos || 0) > 0
            ? '<span class="num" style="font-size:11px;color:var(--text-faint);">' + info.connected_repos + "/" + info.total_repos + tr(" 仓库", " repos") + "</span>"
            : "";

          let hostsHtml = "";
          if (hosts.length === 0) {
            hostsHtml =
              '<div class="status-pop-empty">' +
                "<span>" + tr("尚未检测到该平台仓库或令牌", "No repos or token configured yet") + "</span>" +
                '<button class="btn btn-xs" type="button" data-popover-open-setup="' + fg + '">' + tr("添加主机", "Add Host") + "</button>" +
              "</div>";
          } else {
            hostsHtml = '<div class="status-pop-hosts">' + hosts.map((h) => {
              const hMeta = forgeStatusBadgeMeta(h.status || info.status);
              const hUrl = safeUrl(h.api_base);
              const hLabel = String(h.host || h.api_base || fg).replace(/^https?:\/\//i, "");
              const authLabel = formatAuthSourceLabel(h.auth_source, h.username);
              const repoList = Array.isArray(h.repos) && h.repos.length ? h.repos.join(" · ") : tr("无纳管仓库", "No active repos");
              const syncClock = h.last_synced_at ? formatClock(h.last_synced_at) : "—";
              const actionBtn = h.status === "auth_required"
                ? '<button class="btn btn-xs btn-warn" type="button" data-popover-open-setup="' + fg + '">' + tr("配置令牌", "Setup") + "</button>"
                : (h.status === "error" && !localOnly
                    ? '<button class="btn btn-xs" type="button" data-popover-sync="1">' + tr("重试", "Retry") + "</button>"
                    : "");
              return (
                '<div class="status-pop-host">' +
                  '<div class="status-pop-host-top">' +
                    (hUrl
                      ? '<a class="host-url-link" href="' + escapeHtml(hUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(hLabel) + " ↗</a>"
                      : '<span class="host-url-link">' + escapeHtml(hLabel) + "</span>") +
                    '<span class="badge ' + hMeta.tone + '" style="font-size:10px;padding:1px 6px;">' + escapeHtml(authLabel) + "</span>" +
                  "</div>" +
                  '<div class="status-pop-host-meta">' +
                    '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:215px;" title="' + escapeHtml(repoList) + '">' + escapeHtml(repoList) + "</span>" +
                    '<span class="num">' + tr("同步 ", "Sync ") + escapeHtml(syncClock) + "</span>" +
                  "</div>" +
                  (h.error || actionBtn
                    ? '<div class="status-pop-err"><span style="color:' + (h.status === "auth_required" ? "var(--amber)" : "var(--red)") + ';">' + escapeHtml(h.error || "") + "</span>" + actionBtn + "</div>"
                    : "") +
                "</div>"
              );
            }).join("") + "</div>";
          }

          return (
            '<div class="status-pop-card' + (isFocus ? " is-focus" : "") + '">' +
              '<div class="status-pop-card-hdr">' +
                '<span class="status-pop-plat">' + forgeIcon(fg, 14) + "<span>" + escapeHtml(info.label) + "</span>" + repoSummary + "</span>" +
                '<span class="badge ' + meta.tone + '">' + escapeHtml(meta.longText) + "</span>" +
              "</div>" +
              hostsHtml +
            "</div>"
          );
        }).join("");

        popEl.innerHTML =
          '<div class="status-pop-hdr">' +
            '<span class="status-pop-live"><span style="width:7px;height:7px;border-radius:50%;background:' + pollDotColor + ';display:inline-block;"></span><span>' + escapeHtml(pollStateLabel) + "</span></span>" +
            '<span style="display:inline-flex;align-items:center;gap:6px;">' +
              '<span class="num">' + escapeHtml(state.lastClockStr || "—") + "</span>" +
              '<button class="cluster-icon-btn" type="button" data-popover-close="1" aria-label="' + tr("关闭", "Close") + '">' + icon("x", 13) + "</button>" +
            "</span>" +
          "</div>" +
          cardsHtml +
          '<div class="status-pop-ftr">' +
            '<button class="btn btn-xs" type="button" data-popover-open-setup="">' + icon("key", 11) + "<span>" + tr("连接配置与令牌", "Platform Setup") + "</span></button>" +
            (localOnly
              ? '<span style="font-size:11px;color:var(--text-faint);">--local-only</span>'
              : '<button class="btn btn-xs btn-primary" type="button" data-popover-sync="1">' + icon("refresh", 11) + "<span>" + tr("立即同步远端", "Sync Forge") + "</span></button>") +
          "</div>";
      }

      function syncHeaderControls() {
        const setupBtn = document.getElementById("setup-btn");
        if (setupBtn) {
          const authAlerts = (state.snapshot && state.snapshot.auth_alerts) || [];
          const unconfCnt = state.authStatus && typeof state.authStatus.unconfigured_count === "number"
            ? state.authStatus.unconfigured_count
            : authAlerts.length;
          const setupKey = unconfCnt + "|" + state.lang;
          if (setupKey !== state.lastSetupBtnKey) {
            state.lastSetupBtnKey = setupKey;
            setupBtn.classList.toggle("btn-warn", unconfCnt > 0);
            setupBtn.title = tr("打开连接配置与 IDD 四步上手指南", "Open GitHub/GitLab setup & IDD 4-step guide");
            setupBtn.innerHTML =
              icon(unconfCnt > 0 ? "key" : "compass", 12) +
              "<span>" + (unconfCnt > 0 ? tr("配置令牌", "Setup Token") : tr("引导与配置", "Setup & Guide")) + "</span>" +
              (unconfCnt > 0 ? '<span class="setup-badge-cnt num">' + unconfCnt + "</span>" : "");
          }
        }
        const pauseBtn = document.getElementById("pause-btn");
        if (pauseBtn) {
          const pauseKey = Boolean(state.paused) + "|" + state.lang;
          if (pauseKey !== state.lastPauseBtnKey) {
            const hadPrev = state.lastPauseBtnKey !== "";
            state.lastPauseBtnKey = pauseKey;
            const pLabel = state.paused ? tr("继续自动轮询", "Resume auto-refresh") : tr("暂停自动轮询", "Pause auto-refresh");
            pauseBtn.classList.toggle("is-paused", Boolean(state.paused));
            pauseBtn.title = pLabel;
            pauseBtn.setAttribute("aria-label", pLabel);
            pauseBtn.innerHTML = state.paused ? icon("play", 12) : icon("pause", 12);
            if (hadPrev && !prefersReducedMotion()) {
              pauseBtn.classList.remove("icon-pop");
              void pauseBtn.offsetWidth;
              pauseBtn.classList.add("icon-pop");
            }
          }
        }
        const isBusy =
          (!state.hasLiveSnapshot && !state.initError) ||
          Boolean(state.snapshot && state.snapshot.forge_syncing) ||
          state.manualRefreshing;
        const syncBtn = document.getElementById("sync-btn");
        if (syncBtn) {
          const localOnly = Boolean(state.snapshot && state.snapshot.local_only);
          const syncKey = Boolean(isBusy) + "|" + localOnly + "|" + state.lang;
          if (syncKey !== state.lastSyncBtnKey) {
            state.lastSyncBtnKey = syncKey;
            syncBtn.classList.toggle("spin", isBusy);
            syncBtn.title = localOnly
              ? tr("当前为仅本地模式 (快捷键 r 刷新本地)", "Local-only mode (press r to refresh)")
              : tr("同步 GitHub / GitLab 远端 (快捷键 r)", "Sync GitHub / GitLab (shortcut r)");
            syncBtn.innerHTML = icon("refresh", 12) + "<span>" + (isBusy ? tr("同步中", "Syncing") : tr("同步远端", "Sync Forge")) + "</span>";
          }
        }

        renderForgeStatus(false);

        const s = (state.snapshot && state.snapshot.summary) || {};
        const hasLive = Number(s.coding_now_count || 0) > 0 || Number(s.active_worktrees || 0) > 0;
        const modes = [
          { id: "view-cockpit", mode: "cockpit", ic: "cockpit", dot: hasLive },
          { id: "view-kanban", mode: "kanban", ic: "columns", dot: false },
          { id: "view-repos", mode: "repos", ic: "folder", dot: false },
          { id: "view-list", mode: "list", ic: "list", dot: false }
        ];
        for (const m of modes) {
          const el = document.getElementById(m.id);
          if (!el) continue;
          el.classList.toggle("active", state.viewMode === m.mode);
          const nextHtml = icon(m.ic, 14) + '<span class="tile-dot ' + (m.dot ? "show" : "") + '"></span>';
          if (el.dataset.tileHtml !== nextHtml) {
            el.dataset.tileHtml = nextHtml;
            el.innerHTML = nextHtml;
          }
        }
        syncSlidingIndicator(document.querySelector(".sb-tiles"), ".sb-tile.active", "sb-tiles");
        updateTopProgress();
      }

      function updateConnectionBadge(ok, errorMsg) {
        const tag = document.getElementById("conn-tag");
        const cluster = document.getElementById("status-cluster");
        if (cluster) cluster.classList.toggle("is-err", !ok);
        if (!tag) return;
        const clock = escapeHtml(state.lastClockStr || tr("同步中...", "Syncing..."));
        if (!ok) {
          tag.className = "live-pill is-err";
          tag.innerHTML = icon("alertTriangle", 12) + "<span>" + escapeHtml(errorMsg || tr("连接中断", "Disconnected")) + '</span><span id="updated-tag" style="display:none;">' + clock + "</span>";
          return;
        }
        if (state.paused) {
          tag.className = "live-pill";
          tag.innerHTML = icon("pause", 11) + "<span>" + tr("已暂停", "Paused") + '</span><span class="live-sep">·</span><span id="updated-tag" class="num live-clock">' + clock + "</span>";
          return;
        }
        if (!state.hasLiveSnapshot && !state.snapshot) {
          tag.className = "live-pill is-loading";
          tag.innerHTML = '<span class="dot-pulse"></span><span>' + tr("初始化中", "Initializing") + '</span><span class="live-sep">·</span><span id="updated-tag" class="num live-clock">' + tr("扫描中...", "Scanning...") + "</span>";
          return;
        }
        if (!state.hasLiveSnapshot && state.fromCache) {
          tag.className = "live-pill is-syncing";
          tag.innerHTML = '<span class="dot-pulse"></span><span>' + tr("更新中", "Updating") + '</span><span class="live-sep">·</span><span id="updated-tag" class="num live-clock">' + clock + "</span>";
          return;
        }
        if (state.snapshot && state.snapshot.local_only) {
          tag.className = "live-pill is-local";
          tag.innerHTML = '<span class="dot-pulse"></span><span>' + tr("仅本地", "Local") + '</span><span class="live-sep">·</span><span id="updated-tag" class="num live-clock">' + clock + "</span>";
          return;
        }
        const syncingRemote = Boolean(state.snapshot && state.snapshot.forge_syncing);
        tag.className = syncingRemote ? "live-pill is-syncing" : "live-pill is-live";
        tag.innerHTML = '<span class="dot-pulse"></span><span>' + (syncingRemote ? tr("同步中", "Syncing") : tr("实时", "Live")) + '</span><span class="live-sep">·</span><span id="updated-tag" class="num live-clock">' + clock + "</span>";
      }

      function parseStage(rawStage) {
        const cleaned = String(rawStage || "").replace(/^[\s\u{1F300}-\u{1FAFF}\u2600-\u27BF\uFE0F]+/u, "").trim();
        const canonical = cleaned === "待认领" ? "待处理" : (cleaned || "—");
        const enMap = {
          "待处理": "Queued",
          "开发中": "In Progress",
          "本地开发": "Local",
          "已完成": "Completed",
          "修 CI": "Fix CI",
          "受阻": "Blocked",
          "待合入": "Ready to Land",
          "CI 运行中": "CI Running"
        };
        let label = canonical;
        if (isEn()) {
          if (enMap[canonical]) label = enMap[canonical];
          else if (canonical.startsWith("草稿")) label = "Draft";
          else if (canonical.startsWith("待提")) label = "Ready for PR";
        }
        if (canonical === "修 CI" || canonical === "受阻") return { key: canonical, label, tone: "tone-danger", dot: "fail" };
        if (canonical === "待合入" || canonical === "已完成" || canonical.startsWith("待提")) return { key: canonical, label, tone: "tone-success", dot: "active" };
        if (canonical === "CI 运行中") return { key: canonical, label, tone: "tone-warning", dot: "warm" };
        if (canonical.startsWith("草稿")) return { key: canonical, label, tone: "tone-violet", dot: "quiet" };
        if (canonical === "待处理") return { key: canonical, label, tone: "tone-muted", dot: "quiet" };
        return { key: canonical, label, tone: "tone-info", dot: "active" };
      }

      function isItemAlert(item) {
        const pulse = item.pulse || null;
        const isStalled = pulse && pulse.activity_state === "stalled";
        const st = parseStage(item.stage).key;
        const isFail = st === "修 CI" || st === "受阻" || (item.change && item.change.checks_overall === "FAIL");
        return Boolean(isStalled || isFail);
      }

      function collectItems(ignoreFilters) {
        const snap = state.snapshot;
        if (!snap) return [];
        const list = [];
        for (const row of snap.issues || []) {
          list.push(Object.assign({ _kind: "issue", _key: row.repo_path + "#issue#" + row.issue_number }, row));
        }
        for (const loc of snap.local_only_items || []) {
          const blockedCnt = (loc.counts && loc.counts.blocked) || 0;
          const locTotal = Number(loc.total || 0);
          const locDone = Number(loc.done || 0);
          const allDone = locTotal > 0 && locDone === locTotal;
          const mrLbl = loc.mr_label || (loc.forge_type === "gitlab" ? "MR" : (loc.forge_type === "github" ? "PR" : ""));
          const locStage = blockedCnt > 0
            ? "受阻"
            : (allDone ? (mrLbl ? ("待提 " + mrLbl) : "已完成") : "本地开发");
          list.push(Object.assign({
            _kind: "local",
            _key: loc.repo_path + "#local#" + loc.issue + "#" + (loc.worktree || ""),
            title: loc.issue,
            stage: locStage,
            task_progress: loc.done + " / " + loc.total,
            forge_type: "local"
          }, loc));
        }
        for (const orph of snap.orphan_changes || []) {
          list.push(Object.assign({
            _kind: "orphan",
            _key: orph.repo_path + "#orphan#" + orph.number,
            branch: orph.headRefName || "",
            stage: orph.checks_overall === "FAIL" ? "修 CI" : (orph.isDraft ? "草稿" : "待合入"),
            task_progress: "—",
            forge_type: orph.forge_type || (orph.mr_label === "MR" ? "gitlab" : "github"),
            tasks: [],
            counts: {},
            pulse: null,
            change: orph,
            change_summary: orph.change_summary || ""
          }, orph));
        }
        if (ignoreFilters) return list;
        return list.filter(matchesFilters);
      }

      function matchesFilters(item) {
        if (state.selectedRepo !== "ALL" && item.repo_path !== state.selectedRepo) return false;
        if (state.worktreeOnly && !item.worktree) return false;
        if (state.todoOnly && (item.worktree || item.change)) return false;
        if (state.alertsOnly && !isItemAlert(item)) return false;
        const q = state.search.trim().toLowerCase();
        if (!q) return true;
        const hay = [
          item.repo_name,
          item.issue_number != null ? "#" + item.issue_number : "",
          item.title,
          item.issue,
          item.branch,
          item.worktree,
          item.current_task,
          item.stage
        ].join(" ").toLowerCase();
        return hay.includes(q);
      }

      function getProgressNumbers(item) {
        const tasks = item.tasks || [];
        const countsObj = item.counts || {};
        const countsTotal = Object.values(countsObj).reduce((a, b) => a + Number(b || 0), 0);
        const total = countsTotal > 0 ? countsTotal : (typeof item.total === "number" ? item.total : tasks.length);
        const done = countsTotal > 0
          ? Number(countsObj.done || 0)
          : (typeof item.done === "number" ? item.done : tasks.filter((t) => t.status === "done").length);
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        return { total, done, pct };
      }

      function shortWorktreePath(wt) {
        const parts = String(wt || "").split("/").filter(Boolean);
        if (parts.length <= 2) return String(wt || "");
        return parts.slice(-2).join("/");
      }

      function shortDirSlug(wt, repoName, branch) {
        const parts = String(wt || "").split("/").filter(Boolean);
        if (parts.length >= 2 && repoName && parts[parts.length - 1] === repoName && parts[parts.length - 2] !== "worktrees") {
          return parts[parts.length - 2];
        }
        if (parts.length) {
          const leaf = parts[parts.length - 1];
          if (!repoName || leaf !== repoName) return leaf;
        }
        if (branch && branch !== "(detached)") {
          return String(branch).replace(/^[^/]+\//, "");
        }
        return parts.length ? parts[parts.length - 1] : "";
      }

      function itemDotClass(item) {
        const stInfo = parseStage(item.stage);
        if (stInfo.key === "修 CI" || stInfo.key === "受阻" || (item.change && item.change.checks_overall === "FAIL")) {
          return "fail";
        }
        const p = item.pulse || null;
        if (p && p.activity_state === "active") return "active";
        if (p && (p.activity_state === "warm" || p.activity_state === "stalled")) return "warm";
        if (stInfo.key === "待合入") return "active";
        return "quiet";
      }

      function buildHandoffPrompt(item) {
        const stInfo = parseStage(item.stage);
        const { total, done } = getProgressNumbers(item);
        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const title = item.title || item.issue || tr("未命名任务", "Untitled task");
        if (isEn()) {
          const header = item.issue_number != null
            ? ("Please take over Issue #" + item.issue_number + " (" + title + "):")
            : ('Please take over local task "' + title + '":');
          const lines = [header];
          if (item.repo_name) lines.push("- Repo: " + item.repo_name);
          if (item.worktree) {
            lines.push("- Worktree: " + item.worktree);
            lines.push("- Branch: " + (item.branch || "—"));
            if (stInfo.key === "修 CI" || (item.change && item.change.checks_overall === "FAIL")) {
              const ch = item.change || {};
              const mrLabel = item.mr_label || (item.forge_type === "gitlab" ? "MR" : "PR");
              const mrPrefix = item.mr_prefix || (item.forge_type === "gitlab" ? "!" : "#");
              const chRef = ch.number != null ? (mrLabel + " " + mrPrefix + ch.number) : mrLabel;
              lines.push("- Status: CI failed on " + chRef + " (" + done + "/" + total + " TASK completed)");
              lines.push("Enter this worktree directory, inspect failing checks via `idd ci " + targetArg + " --logs` per the idd skill, fix the issues, and push an updated commit.");
            } else if (stInfo.key === "待合入") {
              lines.push("- Status: " + done + "/" + total + " TASK completed, PR/MR CI is green and ready to land");
              lines.push("Enter this worktree directory, verify the diff, and run `idd land " + targetArg + "` for a linear Squash merge into main.");
            } else if (stInfo.key.startsWith("待提") || stInfo.key === "已完成") {
              lines.push("- Status: Completed all " + done + "/" + total + " TASKs; PR/MR not opened yet");
              lines.push("Enter this worktree directory, verify the diff, and run `idd pr " + targetArg + "` per the idd skill to open a PR/MR and check CI.");
            } else {
              const progTxt = total > 0
                ? (done + "/" + total + " TASK completed" + (item.current_task ? " (current: " + item.current_task + ")" : ""))
                : "Isolated worktree ready; TASK/ breakdown pending";
              lines.push("- Progress: " + progTxt);
              lines.push("Enter this worktree directory directly, read the TASK/ ledger and uncommitted changes per the idd skill, and continue implementation and tests seamlessly.");
            }
          } else {
            lines.push("- Repo path: " + (item.repo_path || item.repo_name || ""));
            lines.push("Run `idd start " + targetArg + "` in this repo per the idd skill to create an isolated worktree, then break down TASK/ steps, implement, and verify.");
          }
          return lines.join("\n");
        }
        const header = item.issue_number != null
          ? ("请接手 Issue #" + item.issue_number + "（" + title + "）")
          : ("请接手本地任务「" + title + "」");
        const lines = [header + "："];
        if (item.repo_name) {
          lines.push("- 仓库：" + item.repo_name);
        }
        if (item.worktree) {
          lines.push("- 工作目录：" + item.worktree);
          lines.push("- 分支：" + (item.branch || "—"));
          if (stInfo.key === "修 CI" || (item.change && item.change.checks_overall === "FAIL")) {
            const ch = item.change || {};
            const mrLabel = item.mr_label || (item.forge_type === "gitlab" ? "MR" : "PR");
            const mrPrefix = item.mr_prefix || (item.forge_type === "gitlab" ? "!" : "#");
            const chRef = ch.number != null ? (mrLabel + " " + mrPrefix + ch.number) : mrLabel;
            lines.push("- 状态：" + chRef + " 的 CI 检查失败，已完成 " + done + "/" + total + " 个 TASK");
            lines.push("请直接进入该工作目录，按 idd 规范运行 `idd ci " + targetArg + " --logs` 排查修复失败项并更新提交。");
          } else if (stInfo.key === "待合入") {
            lines.push("- 状态：已完成 " + done + "/" + total + " 个 TASK，PR/MR CI 已全绿待合入");
            lines.push("请进入该工作目录确认后，运行 `idd land " + targetArg + "` 线性 Squash 合入 main。");
          } else if (stInfo.key.startsWith("待提") || stInfo.key === "已完成") {
            lines.push("- 状态：已完成全部 " + done + "/" + total + " 个 TASK，尚未提交 PR/MR");
            lines.push("请进入该工作目录复核改动，按 idd 规范运行 `idd pr " + targetArg + "`（GitLab 可用 `idd mr " + targetArg + "`）创建合并请求并检查 CI。");
          } else {
            const progTxt = total > 0
              ? ("已完成 " + done + "/" + total + " 个 TASK" + (item.current_task ? "（当前：" + item.current_task + "）" : ""))
              : "已创建独立工作目录，待拆解 TASK";
            lines.push("- 进度：" + progTxt);
            lines.push("请直接进入该工作目录，按 idd 规范读取 TASK/ 下任务记录与当前未提交改动，无缝继续后续实现与测试。");
          }
        } else {
          lines.push("- 仓库目录：" + (item.repo_path || item.repo_name || ""));
          lines.push("请按 idd 规范在该仓库运行 `idd start " + targetArg + "` 创建独立工作树，再拆解 TASK/ 步骤逐项实现并验证。");
        }
        return lines.join("\n");
      }

      function forgeLabel(forgeType) {
        if (forgeType === "github") return "GitHub";
        if (forgeType === "gitlab") return "GitLab";
        return tr("本地", "Local");
      }

      function resolveRepoMeta(item) {
        const snap = state.snapshot;
        const repos = (snap && snap.repos) || [];
        const matched = repos.find((r) =>
          (item && item.repo_path && r.repo_path === item.repo_path) ||
          (item && item.repo_name && r.repo_name === item.repo_name)
        );
        const rawForge = (item && item.forge_type) || "";
        const forgeType = (rawForge && rawForge !== "local")
          ? rawForge
          : ((matched && matched.forge) || rawForge || "local");
        const repoUrl = safeUrl((item && item.repo_url) || (matched && matched.repo_url) || "");
        const repoName = (item && item.repo_name) || (matched && matched.repo_name) || "";
        return { forgeType, repoUrl, repoName };
      }

      function renderRepoChip(itemOrMeta, opts) {
        const options = opts || {};
        const meta = itemOrMeta && (itemOrMeta._kind || itemOrMeta.repo_path || itemOrMeta.repo_name)
          ? resolveRepoMeta(itemOrMeta)
          : {
              forgeType: (itemOrMeta && itemOrMeta.forgeType) || "local",
              repoUrl: safeUrl(itemOrMeta && itemOrMeta.repoUrl),
              repoName: (itemOrMeta && itemOrMeta.repoName) || ""
            };
        const fg = meta.forgeType;
        const plat = forgeLabel(fg);
        const cls = [
          "forge-chip",
          fg === "github" ? "is-github" : (fg === "gitlab" ? "is-gitlab" : ""),
          options.compact ? "is-compact" : ""
        ].filter(Boolean).join(" ");
        const showName = options.hideName ? "" : meta.repoName;
        const labelText = options.customLabel || plat;
        const inner =
          forgeIcon(fg, options.compact ? 11 : 12) +
          '<span class="forge-chip-plat">' + escapeHtml(labelText) + "</span>" +
          (showName ? '<span class="forge-chip-sep">·</span><span class="forge-chip-name">' + escapeHtml(showName) + "</span>" : "") +
          (meta.repoUrl ? '<span class="forge-chip-ext">' + icon("externalLink", 10) + "</span>" : "");
        if (meta.repoUrl) {
          const tip = tr("点击跳转到 " + plat + " 仓库主页：", "Open " + plat + " repository homepage: ") + meta.repoUrl;
          return '<a class="' + cls + '" href="' + escapeHtml(meta.repoUrl) + '" target="_blank" rel="noopener noreferrer" data-stop-open="1" title="' + escapeHtml(tip) + '">' + inner + "</a>";
        }
        return '<span class="' + cls + '">' + inner + "</span>";
      }

      function renderIdHtml(item) {
        const issueHref = safeUrl(item.url);
        if (item._kind === "issue") {
          return issueHref
            ? '<a class="id-link" href="' + escapeHtml(issueHref) + '" target="_blank" rel="noopener noreferrer" data-stop-open="1">#' + item.issue_number + "</a>"
            : '<span class="id-link">#' + item.issue_number + "</span>";
        }
        if (item._kind === "orphan") {
          const lbl = (item.mr_label || "PR") + " " + (item.mr_prefix || "#") + item.number;
          return '<span class="id-link">' + escapeHtml(lbl) + "</span>";
        }
        return '<span class="badge tone-violet">' + tr("本地", "Local") + "</span>";
      }

      function renderChangeInline(item) {
        const ch = item.change;
        if (!ch) return "";
        const mrLabel = item.mr_label || (item.forge_type === "gitlab" ? "MR" : "PR");
        const mrPrefix = item.mr_prefix || (item.forge_type === "gitlab" ? "!" : "#");
        const num = ch.number != null ? ch.number : "";
        const prLabel = mrLabel + (num !== "" ? " " + mrPrefix + num : "");
        const overall = ch.checks_overall || "NONE";
        const toneMap = {
          PASS: { cls: "tone-success", text: prLabel + " · " + tr("CI 全绿", "CI PASS") },
          FAIL: { cls: "tone-danger", text: prLabel + " · " + tr("CI 失败", "CI FAIL") },
          PENDING: { cls: "tone-warning", text: prLabel + " · " + tr("CI 运行中", "CI Running") },
          NONE: { cls: "tone-muted", text: prLabel }
        };
        const cfg = toneMap[overall] || toneMap.NONE;
        const chUrl = safeUrl(ch.url);
        if (chUrl) {
          return '<a class="badge ' + cfg.cls + '" href="' + escapeHtml(chUrl) + '" target="_blank" rel="noopener noreferrer" data-stop-open="1">' + escapeHtml(cfg.text) + "</a>";
        }
        return '<span class="badge ' + cfg.cls + '">' + escapeHtml(cfg.text) + "</span>";
      }

      function localizeAgo(ago) {
        if (!ago) return "";
        if (!isEn()) return ago === "刚刚" ? "刚刚活跃" : ago;
        if (ago === "刚刚") return "Active now";
        const mSec = ago.match(/^(\d+)\s*秒前$/);
        if (mSec) return mSec[1] + "s ago";
        const mMin = ago.match(/^(\d+)\s*分钟前$/);
        if (mMin) return mMin[1] + "m ago";
        const mHr = ago.match(/^(\d+)\s*小时前$/);
        if (mHr) return mHr[1] + "h ago";
        const mDay = ago.match(/^(\d+)\s*天前$/);
        if (mDay) return mDay[1] + "d ago";
        return ago;
      }

      function renderPulseSummary(pulse) {
        if (!pulse) return "";
        const parts = [];
        const ago = pulse.last_active_ago || "";
        if (ago) parts.push(localizeAgo(ago));
        const dirty = Number(pulse.dirty_count || 0);
        const ins = Number(pulse.insertions || 0);
        const dels = Number(pulse.deletions || 0);
        if (dirty > 0) {
          let d = isEn() ? (dirty + (dirty === 1 ? " file" : " files")) : (dirty + " 文件");
          if (ins > 0 || dels > 0) {
            d += ' <span class="diff-ins">+' + ins + '</span> <span class="diff-del">-' + dels + "</span>";
          }
          parts.push(d);
        } else {
          parts.push(tr("干净", "Clean"));
        }
        const remoteState = String(pulse.remote_state || "");
        const unpushed = Number(pulse.unpushed_commits || 0);
        if (remoteState === "unpushed_branch") {
          parts.push('<span style="color:var(--amber);font-weight:600;">' + tr("未推远端", "Unpushed") + "</span>");
        } else if (unpushed > 0) {
          parts.push('<span style="color:var(--amber);font-weight:600;">↑' + unpushed + " " + tr("待推送", "unpushed") + "</span>");
        }
        return parts.join(" · ");
      }

      function renderSegBar(filledCount, totalSlots, toneList) {
        const pills = [];
        for (let i = 0; i < totalSlots; i++) {
          let cls = "seg-pill";
          if (toneList && toneList[i]) {
            cls += " " + toneList[i];
          } else if (i < filledCount) {
            cls += i === filledCount - 1 ? " on" : " dim";
          }
          pills.push('<span class="' + cls + '"></span>');
        }
        return '<div class="seg-bar">' + pills.join("") + "</div>";
      }

      function renderSidebarFilters(snap) {
        const s = snap.summary || {};
        const allItems = collectItems(true);
        const todoCount = allItems.filter((it) => it._kind === "issue" && !it.worktree && !it.change).length;
        const anomalies = Number(s.stalled_worktrees || 0) + Number(s.ci_failed_count || 0);
        const activeWt = Number(s.active_worktrees || 0);

        const rows = [
          {
            id: "filter-wt-btn",
            act: "toggle-wt",
            ic: "sparkle",
            label: tr("活跃工作树", "Active Worktrees"),
            meta: activeWt + " live",
            metaCls: activeWt > 0 ? "live" : "",
            active: state.worktreeOnly,
            dot: activeWt > 0 ? "show" : ""
          },
          {
            id: "filter-alert-btn",
            act: "toggle-alerts",
            ic: "alertTriangle",
            label: tr("异常提醒", "Alerts"),
            meta: anomalies > 0 ? (isEn() ? (anomalies + (anomalies === 1 ? " alert" : " alerts")) : (anomalies + " 异常")) : tr("正常", "OK"),
            metaCls: anomalies > 0 ? "danger" : "",
            active: state.alertsOnly,
            dot: anomalies > 0 ? "show danger" : ""
          },
          {
            id: "filter-todo-btn",
            act: "toggle-todo",
            ic: "circle",
            label: tr("待处理 Issue", "Open Issues"),
            meta: String(todoCount),
            metaCls: "",
            active: state.todoOnly,
            dot: ""
          }
        ];

        document.getElementById("sb-filters").innerHTML = rows.map((r) =>
          '<button id="' + r.id + '" class="sb-item ' + (r.active ? "active" : "") + '" data-kpi-action="' + r.act + '" type="button" title="' + escapeHtml(r.label + " (" + r.meta + ")") + '">' +
            '<span class="sb-item-left">' + icon(r.ic, 14) + '<span class="hide-collapsed">' + escapeHtml(r.label) + "</span></span>" +
            '<span class="sb-meta hide-collapsed ' + r.metaCls + '">' + escapeHtml(r.meta) + "</span>" +
            '<span class="corner-dot ' + r.dot + '"></span>' +
          "</button>"
        ).join("");
      }

      function renderSidebarReposAndWorktrees(snap) {
        const repos = snap.repos || [];
        const allItems = collectItems(true);
        const totalWt = allItems.filter((x) => x.worktree).length;

        const repoCntEl = document.getElementById("sb-repo-cnt");
        if (repoCntEl) repoCntEl.textContent = String(repos.length);

        const allReposLabel = tr("全部仓库", "All Repositories");
        const repoHtml = [
          '<button class="sb-item ' + (state.selectedRepo === "ALL" ? "active" : "") + '" data-repo="ALL" type="button" title="' + escapeHtml(allReposLabel + " (" + totalWt + "/" + allItems.length + ")") + '">' +
            '<span class="sb-item-left">' +
              '<span class="sb-repo-badge is-all">' + icon("layers", 12) + "</span>" +
              '<span class="hide-collapsed">' + escapeHtml(allReposLabel) + "</span>" +
            "</span>" +
            '<span class="sb-meta hide-collapsed">' + totalWt + "/" + allItems.length + "</span>" +
          "</button>"
        ];

        for (const r of repos) {
          const items = [...(r.issues || []), ...(r.local_only_items || [])];
          const wtCnt = items.filter((x) => x.worktree).length;
          const isAct = state.selectedRepo === r.repo_path;
          const forgeCls = r.forge === "github" ? "is-github" : (r.forge === "gitlab" ? "is-gitlab" : "");
          const platShort = r.forge === "github" ? "GH" : (r.forge === "gitlab" ? "GL" : "");
          const platFull = forgeLabel(r.forge);
          const repoHref = safeUrl(r.repo_url);
          const extBtn = repoHref
            ? '<a class="sb-ext-link hide-collapsed" href="' + escapeHtml(repoHref) + '" target="_blank" rel="noopener noreferrer" data-stop-repo="1" title="' + escapeHtml(tr("打开 " + platFull + " 主页: ", "Open " + platFull + " home: ") + repoHref) + '">' + icon("externalLink", 11) + "</a>"
            : "";
          const ri = r.repo_init || {};
          const isPolicyPending = (r.forge === "github" || r.forge === "gitlab") && (ri.state === "pending" || ri.state === "prompted");
          const riBusy = Boolean(state.repoInitRunning[r.repo_path]);
          const policyTitle = ri.error
            ? tr("自动初始化失败：" + ri.error + "（点击重试）", "Auto-init failed: " + ri.error + " (Click to retry)")
            : tr("点击一键初始化仓库线性 Squash 策略与提交模板", "Click to initialize linear Squash policy & commit templates");
          const policyBtn = isPolicyPending
            ? '<button class="sb-policy-btn hide-collapsed' + (riBusy ? " spin" : "") + '" type="button" data-stop-repo="1" data-apply-repo-init="' + escapeHtml(r.repo_path) + '" title="' + escapeHtml(policyTitle) + '" ' + (riBusy ? "disabled" : "") + ">" +
                (riBusy ? tr("执行中", "...") : (ri.error ? tr("重试", "Retry") : tr("待初始化", "Init"))) +
              "</button>"
            : "";
          repoHtml.push(
            '<div class="sb-item ' + (isAct ? "active" : "") + '" role="button" tabindex="0" data-repo="' + escapeHtml(r.repo_path) + '" title="' + escapeHtml("[" + platFull + "] " + r.repo_name + " (" + wtCnt + "/" + items.length + ")") + '">' +
              '<span class="sb-item-left">' +
                '<span class="sb-repo-badge ' + forgeCls + '">' + forgeIcon(r.forge, 12) + "</span>" +
                '<span class="hide-collapsed">' + escapeHtml(r.repo_name) + "</span>" +
              "</span>" +
              '<span class="sb-right-group hide-collapsed">' +
                policyBtn +
                (platShort ? '<span class="sb-plat-tag ' + forgeCls + '">' + platShort + "</span>" : "") +
                '<span class="sb-meta">' + wtCnt + "/" + items.length + "</span>" +
                extBtn +
              "</span>" +
            "</div>"
          );
        }
        document.getElementById("repo-pills").innerHTML = repoHtml.join("");

        const wtItems = allItems.filter((x) => x.worktree && (state.selectedRepo === "ALL" || x.repo_path === state.selectedRepo));
        const wtCntEl = document.getElementById("sb-wt-cnt");
        if (wtCntEl) wtCntEl.textContent = String(wtItems.length);

        const wtHtml = wtItems.map((it) => {
          const isSel = state.selectedKey === it._key || state.inspectedKey === it._key;
          const dotCls = itemDotClass(it);
          const { total, done } = getProgressNumbers(it);
          const isCiFail = it.change && it.change.checks_overall === "FAIL";
          const rightTag = isCiFail ? ":CI!" : (total > 0 ? (":" + done + "/" + total) : ":wt");
          const slug = shortDirSlug(it.worktree, it.repo_name, it.branch) || it.branch || ("#" + it.issue_number);
          const shortBadge = it.issue_number != null ? ("#" + it.issue_number) : "wt";
          return (
            '<button class="sb-item ' + (isSel ? "active" : "") + '" data-jump-key="' + escapeHtml(it._key) + '" type="button" title="' + escapeHtml(slug + " · " + (it.title || "")) + '">' +
              '<span class="sb-item-left">' +
                '<span class="status-dot ' + dotCls + ' hide-collapsed"></span>' +
                '<span class="sb-wt-icon show-collapsed">' + escapeHtml(shortBadge) + "</span>" +
                '<span class="hide-collapsed">' + escapeHtml(slug) + "</span>" +
              "</span>" +
              '<span class="sb-meta hide-collapsed ' + (isCiFail ? "danger" : "") + '">' + escapeHtml(rightTag) + "</span>" +
            "</button>"
          );
        });
        document.getElementById("wt-rail-list").innerHTML = wtHtml.join("");
      }

      function renderWorkspaceHeader(snap) {
        const repos = snap.repos || [];
        const activeRepo = state.selectedRepo === "ALL" ? null : repos.find((r) => r.repo_path === state.selectedRepo);
        const titleEl = document.getElementById("ws-title");
        const logoEl = document.getElementById("ws-logo");
        const scopeEl = document.getElementById("scope-tag");
        const linkWrap = document.getElementById("ws-repo-link-wrap");
        if (activeRepo) {
          if (titleEl) titleEl.textContent = activeRepo.repo_name;
          if (logoEl) {
            logoEl.className = "ws-logo " + (activeRepo.forge === "github" ? "is-github" : (activeRepo.forge === "gitlab" ? "is-gitlab" : ""));
            logoEl.innerHTML = forgeIcon(activeRepo.forge, 16);
          }
          if (scopeEl) {
            scopeEl.style.display = activeRepo.repo_url ? "none" : "inline-flex";
            scopeEl.textContent = forgeLabel(activeRepo.forge);
          }
          if (linkWrap) {
            const repoHref = safeUrl(activeRepo.repo_url);
            const chipHtml = repoHref
              ? renderRepoChip({
                  forgeType: activeRepo.forge,
                  repoUrl: repoHref,
                  repoName: ""
                }, {
                  hideName: true,
                  customLabel: forgeLabel(activeRepo.forge) + tr(" 主页", " Home")
                })
              : "";
            const ari = activeRepo.repo_init || {};
            const activePending = (activeRepo.forge === "github" || activeRepo.forge === "gitlab") && (ari.state === "pending" || ari.state === "prompted");
            const activeBusy = Boolean(state.repoInitRunning[activeRepo.repo_path]);
            const policyHdrBtn = activePending
              ? '<button class="btn btn-xs btn-warn' + (activeBusy ? " spin" : "") + '" type="button" data-apply-repo-init="' + escapeHtml(activeRepo.repo_path) + '" ' + (activeBusy ? "disabled" : "") + ">" +
                  icon(activeBusy ? "refresh" : "alertTriangle", 11) +
                  "<span>" + (activeBusy ? tr("初始化中...", "Applying...") : (ari.error ? tr("策略初始化失败 · 点击重试", "Policy Init Failed · Retry") : tr("待初始化策略 · 点击执行", "Policy Pending · Apply"))) + "</span>" +
                "</button>"
              : "";
            const am = activeRepo.auto_merge || {};
            const amEnabled = Boolean(am.enabled);
            const amBusy = Boolean(state.autoMergeSaving[activeRepo.repo_path]);
            const amSrc = am.source === "repo" ? tr("仓库", "Repo") : tr("全局", "Global");
            const mrTag = activeRepo.forge === "gitlab" ? "MR" : "PR";
            const amHdrBtn = (activeRepo.forge === "github" || activeRepo.forge === "gitlab")
              ? '<button class="am-header-pill ' + (amEnabled ? "is-on" : "") + '" type="button" data-am-quick-repo="' + escapeHtml(activeRepo.repo_path) + '" data-am-next="' + (amEnabled ? "0" : "1") + '" ' + (amBusy ? "disabled" : "") + ' title="' + escapeHtml(tr("点击查看影响说明并切换当前仓库 " + mrTag + " 自动准入开关", "Review impact and toggle " + mrTag + " Auto-Approve for this repo")) + '">' +
                  '<span class="am-dot"></span>' +
                  "<span>" + (amEnabled ? tr(mrTag + " 自动准入: 开 (" + amSrc + ")", mrTag + " Auto-Approve: ON (" + amSrc + ")") : tr(mrTag + " 自动准入: 关", mrTag + " Auto-Approve: OFF")) + "</span>" +
                "</button>"
              : "";
            linkWrap.innerHTML = chipHtml + amHdrBtn + policyHdrBtn;
          }
        } else {
          if (titleEl) titleEl.textContent = tr("全局工作区", "Global Workspace");
          if (logoEl) {
            logoEl.className = "ws-logo";
            logoEl.innerHTML = icon("branch", 15);
          }
          if (scopeEl) {
            scopeEl.style.display = snap.global ? "none" : "inline-flex";
            if (!snap.global) scopeEl.textContent = tr("单仓库", "Single Repo");
          }
          if (linkWrap) {
            const globalAm = Boolean(snap.config && snap.config.auto_merge);
            const gBusy = Boolean(state.autoMergeSaving.__global__);
            linkWrap.innerHTML =
              '<button class="am-header-pill ' + (globalAm ? "is-on" : "") + '" type="button" data-am-quick-global="1" data-am-next="' + (globalAm ? "0" : "1") + '" ' + (gBusy ? "disabled" : "") + ' title="' + escapeHtml(tr("点击查看影响说明并切换全局默认 PR 自动准入开关", "Review impact and toggle global default PR Auto-Approve")) + '">' +
                '<span class="am-dot"></span>' +
                "<span>" + (globalAm ? tr("PR 自动准入: 开", "PR Auto-Approve: ON") : tr("PR 自动准入: 关", "PR Auto-Approve: OFF")) + "</span>" +
              "</button>";
          }
        }
      }

      function renderKpis(snap) {
        const s = snap.summary || {};
        const allItems = collectItems(true);
        const scopedItems = state.selectedRepo === "ALL"
          ? allItems
          : allItems.filter((it) => it.repo_path === state.selectedRepo);
        const scopedIssues = scopedItems.filter((it) => it._kind === "issue");

        let issueInProg = 0;
        let issueReady = 0;
        let issueQueued = 0;
        let ciFailed = 0;
        let openChanges = 0;
        let dirtyWt = 0;
        let stalled = 0;
        let activeWt = 0;

        let totalSteps = 0;
        let doneSteps = 0;
        let inProgSteps = 0;
        let blockedSteps = 0;
        let plannedSteps = 0;

        for (const it of scopedItems) {
          if (it.worktree) activeWt += 1;
          if (it.change) openChanges += 1;
          const p = it.pulse || null;
          if (p && Number(p.dirty_count || 0) > 0) dirtyWt += 1;
          if (p && p.activity_state === "stalled") stalled += 1;
          const stKey = parseStage(it.stage).key;
          if (stKey === "修 CI" || (it.change && it.change.checks_overall === "FAIL")) ciFailed += 1;

          const counts = it.counts || {};
          const nums = getProgressNumbers(it);
          totalSteps += nums.total;
          doneSteps += nums.done;
          inProgSteps += Number(counts.in_progress || 0);
          blockedSteps += Number(counts.blocked || 0);
          plannedSteps += Number(counts.planned || 0);
        }

        for (const row of scopedIssues) {
          const b = cardBucket(row);
          if (b === "ready") issueReady += 1;
          else if (b === "todo") issueQueued += 1;
          else issueInProg += 1;
        }

        const issueTotal = scopedIssues.length;
        const pct = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 100) : 0;

        const issueTones = [];
        const issueDenominator = Math.max(issueTotal, 1);
        const readySlots = issueTotal > 0 ? Math.round((issueReady / issueDenominator) * 8) : 0;
        const progSlots = issueTotal > 0 ? Math.round((issueInProg / issueDenominator) * 8) : 0;
        for (let i = 0; i < 8; i++) {
          if (i < readySlots) issueTones.push("green");
          else if (i < readySlots + progSlots) issueTones.push("on");
          else if (i < issueTotal && i < Math.round((issueTotal / issueDenominator) * 8)) issueTones.push("dim");
          else issueTones.push("");
        }

        const taskTones = [];
        const doneSlots = totalSteps > 0 ? Math.round((doneSteps / totalSteps) * 8) : 0;
        const inProgSlots = totalSteps > 0 ? Math.max(inProgSteps > 0 ? 1 : 0, Math.round((inProgSteps / totalSteps) * 8)) : 0;
        const blkSlots = totalSteps > 0 ? Math.max(blockedSteps > 0 ? 1 : 0, Math.round((blockedSteps / totalSteps) * 8)) : 0;
        for (let i = 0; i < 8; i++) {
          if (i < doneSlots) taskTones.push("green");
          else if (i < doneSlots + inProgSlots) taskTones.push("on");
          else if (i < doneSlots + inProgSlots + blkSlots) taskTones.push("red");
          else taskTones.push("");
        }

        const prTones = [];
        for (let i = 0; i < 8; i++) {
          if (i < issueReady) prTones.push("green");
          else if (i < issueReady + ciFailed) prTones.push("red");
          else if (i < openChanges) prTones.push("amber");
          else prTones.push("");
        }

        const waitingFirstForge = Boolean(snap.forge_syncing) && (snap.repos || []).some((r) => r.forge !== "local" && !r.forge_fetched_at);
        const issueSub = (waitingFirstForge && issueTotal === 0)
          ? tr("正在拉取远端开放中的 Issue…", "Fetching open remote Issues…")
          : (isEn()
              ? (issueInProg + " active · " + issueQueued + " queued · " + issueReady + " ready")
              : ("推进中 " + issueInProg + " · 待认领 " + issueQueued + " · 待合入 " + issueReady));
        const taskSub = isEn()
          ? ("Done " + doneSteps + "/" + totalSteps + " · Active " + inProgSteps + " · Planned " + plannedSteps + (blockedSteps > 0 ? " · Blocked " + blockedSteps : ""))
          : ("已完成 " + doneSteps + "/" + totalSteps + " · 进行中 " + inProgSteps + " · 待开始 " + plannedSteps + (blockedSteps > 0 ? " · 受阻 " + blockedSteps : ""));
        const prSub = isEn()
          ? ("Open " + openChanges + " · CI failed " + ciFailed + " · " + activeWt + " worktrees")
          : ("Open " + openChanges + " · CI 失败 " + ciFailed + " · 活跃目录 " + activeWt + (dirtyWt > 0 ? " (" + dirtyWt + " 改)" : ""));

        const cards = [
          {
            key: "issue",
            action: "toggle-wt",
            ic: "circle",
            label: tr("Issue 状态", "Issue Status"),
            val: (waitingFirstForge && issueTotal === 0) ? "…" : String(issueTotal),
            numVal: (waitingFirstForge && issueTotal === 0) ? null : issueTotal,
            unit: "Open",
            slots: Array.from({ length: 8 }, (_, i) => issueTones[i] || ""),
            sub: issueSub,
            subCls: issueInProg > 0 ? "live" : "",
            filtered: state.worktreeOnly,
            warn: false
          },
          {
            key: "pct",
            action: "",
            ic: "layers",
            label: tr("TASK 拆分进度", "TASK Breakdown"),
            val: String(pct),
            numVal: pct,
            unit: "%",
            slots: Array.from({ length: 8 }, (_, i) => taskTones[i] || ""),
            sub: taskSub,
            subCls: blockedSteps > 0 ? "warn" : "",
            filtered: false,
            warn: blockedSteps > 0
          },
          {
            key: "ready",
            action: "toggle-alerts",
            ic: "pr",
            label: tr("PR / MR 与合入", "PR / MR & Land"),
            val: String(issueReady),
            numVal: issueReady,
            unit: tr("待合入", "ready"),
            slots: Array.from({ length: 8 }, (_, i) => prTones[i] || ""),
            sub: prSub,
            subCls: (ciFailed + stalled) > 0 ? "warn" : "",
            filtered: state.alertsOnly,
            warn: (ciFailed + stalled) > 0
          }
        ];

        const kpisEl = document.getElementById("kpis");
        const existingCards = kpisEl ? Array.from(kpisEl.querySelectorAll(".bento-metric:not(.is-skel)")) : [];
        if (existingCards.length === 3) {
          cards.forEach((c, idx) => {
            const cardEl = existingCards[idx];
            cardEl.className = ["bento-metric", c.filtered ? "is-filtered" : "", c.warn ? "is-warn" : ""].filter(Boolean).join(" ");
            const hdrText = cardEl.querySelector(".metric-hdr-left > span:last-child");
            if (hdrText && hdrText.textContent !== c.label) hdrText.textContent = c.label;
            const numEl = cardEl.querySelector(".metric-num");
            if (numEl) {
              const prevNum = state.kpiPrevNums[c.key];
              if (c.numVal !== null && prevNum !== null && prevNum !== c.numVal) {
                animateNumber(numEl, prevNum, c.numVal, 280);
              } else if (numEl.textContent !== c.val) {
                numEl.textContent = c.val;
              }
              state.kpiPrevNums[c.key] = c.numVal;
            }
            const unitEl = cardEl.querySelector(".metric-unit");
            if (unitEl && unitEl.textContent !== c.unit) unitEl.textContent = c.unit;
            const pills = cardEl.querySelectorAll(".seg-pill");
            if (pills.length === 8) {
              pills.forEach((pill, pi) => {
                const nextCls = "seg-pill" + (c.slots[pi] ? " " + c.slots[pi] : "");
                if (pill.className !== nextCls) pill.className = nextCls;
              });
            }
            const subEl = cardEl.querySelector(".metric-sub");
            if (subEl) {
              subEl.className = "metric-sub" + (c.subCls ? " " + c.subCls : "");
              if (subEl.textContent !== c.sub) subEl.textContent = c.sub;
            }
          });
          return;
        }

        const segBars = [
          renderSegBar(issueTotal, 8, issueTones),
          renderSegBar(doneSteps > 0 ? Math.max(1, doneSlots) : 0, 8, taskTones),
          renderSegBar(openChanges, 8, prTones)
        ];
        kpisEl.innerHTML = cards.map((c, idx) => {
          state.kpiPrevNums[c.key] = c.numVal;
          const cls = ["bento-metric", c.filtered ? "is-filtered" : "", c.warn ? "is-warn" : ""].filter(Boolean).join(" ");
          const tag = c.action ? "button" : "div";
          const attrs = c.action ? ' type="button" data-kpi-action="' + c.action + '"' : "";
          return (
            "<" + tag + ' class="' + cls + '"' + attrs + ">" +
              '<div class="metric-hdr">' +
                '<span class="metric-hdr-left">' + icon(c.ic, 12) + "<span>" + escapeHtml(c.label) + "</span></span>" +
              "</div>" +
              '<div class="metric-val-row">' +
                '<span class="metric-num num">' + escapeHtml(c.val) + "</span>" +
                '<span class="metric-unit">' + escapeHtml(c.unit) + "</span>" +
              "</div>" +
              segBars[idx] +
              '<div class="metric-sub ' + c.subCls + '">' + escapeHtml(c.sub) + "</div>" +
            "</" + tag + ">"
          );
        }).join("");
      }

      function renderCockpitConsole(item) {
        if (!item) {
          return (
            '<section class="bento-card">' +
              '<div class="bento-hdr"><div class="bento-title-row"><span class="bento-title">' + tr("跨 Agent 接力提示词", "Cross-Agent Handoff Prompt") + '</span><span class="bento-sub">' + tr("请在上方选择一个并行工作树或 Issue", "Select an active worktree or Issue above") + "</span></div></div>" +
              '<div class="console-well">' + tr("暂无选中项。", "No item selected.") + "</div>" +
            "</section>"
          );
        }

        const prompt = buildHandoffPrompt(item);
        const tasks = item.tasks || [];
        const pulse = item.pulse || null;
        const changedFiles = (pulse && pulse.changed_files) || [];
        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const startCmd = targetArg && item.repo_path ? ("cd " + item.repo_path + " && idd start " + targetArg) : "";
        const idLabel = item.issue_number != null ? ("#" + item.issue_number) : tr("本地", "Local");

        const repoMeta = resolveRepoMeta(item);
        let wellHtml = "";
        if (state.consoleTab === "files") {
          if (changedFiles.length === 0) {
            wellHtml = '<div style="color:var(--text-faint);">' + tr("工作区干净，暂无未提交改动。", "Clean working tree; no uncommitted changes.") + "</div>";
          } else {
            wellHtml = changedFiles.map((f) => {
              const code = String(f.code || "M").trim();
              const cls = code === "??" ? "ok" : (code.includes("D") ? "err" : "info");
              return '<div class="log-line"><span class="log-k ' + cls + '">' + escapeHtml(code) + '</span><span class="log-v">' + escapeHtml(f.path) + "</span></div>";
            }).join("");
          }
        } else {
          const metaLines = [
            '<div class="log-line"><span class="log-k">repo</span><span class="log-v" style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;">' + renderRepoChip(item, { compact: true }) + (item.branch ? '<span>·</span><span style="color:var(--accent)">' + escapeHtml(item.branch) + "</span>" : "") + "</span></div>",
            '<div class="log-line"><span class="log-k">worktree</span><span class="log-v">' + escapeHtml(item.worktree || tr("尚未创建（点击右侧复制开工命令）", "Not created yet (copy CLI Cmd on the right)")) + "</span></div>"
          ];
          if (pulse && pulse.last_commit_sha) {
            metaLines.push('<div class="log-line"><span class="log-k">commit</span><span class="log-v">' + escapeHtml(pulse.last_commit_sha + "  " + (pulse.last_commit_subject || "")) + "</span></div>");
          }
          const taskLines = tasks.map((t) => {
            const st = t.status || "planned";
            const sym = st === "done" ? "✓" : (st === "in_progress" ? "◐" : (st === "blocked" ? "✗" : "○"));
            const cls = st === "done" ? "ok" : (st === "in_progress" ? "info" : (st === "blocked" ? "err" : ""));
            return '<div class="log-line"><span class="log-k">' + escapeHtml(t.id || "TASK") + '</span><span class="log-v ' + cls + '">' + sym + "  " + escapeHtml(t.title || t.id) + '  <span style="color:var(--text-faint)">[' + escapeHtml(st) + "]</span></span></div>";
          });
          wellHtml =
            metaLines.join("") +
            (taskLines.length ? '<div class="log-sep"></div>' + taskLines.join("") : "") +
            '<div class="log-sep"></div>' +
            '<pre class="handoff-block">' + escapeHtml(prompt) + "</pre>";
        }

        return (
          '<section class="bento-card">' +
            '<div class="bento-hdr">' +
              '<div class="bento-title-row">' +
                '<span class="bento-title">' + tr("跨 Agent 接力提示词", "Agent Handoff") + "</span>" +
                '<span class="bento-sub">' + escapeHtml(idLabel + " · " + (item.title || item.issue || "")) + "</span>" +
                '<div class="console-tabs">' +
                  '<button class="console-tab ' + (state.consoleTab === "handoff" ? "active" : "") + '" data-console-tab="handoff" type="button">' + tr("接力与步骤", "Handoff") + " (" + tasks.length + ")</button>" +
                  '<button class="console-tab ' + (state.consoleTab === "files" ? "active" : "") + '" data-console-tab="files" type="button">' + tr("改动文件", "Files") + " (" + ((pulse && pulse.dirty_count) || 0) + ")</button>" +
                "</div>" +
              "</div>" +
              '<div class="bento-actions">' +
                '<button class="btn btn-sm btn-primary" data-copy-val="' + escapeHtml(prompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" type="button">' + icon("copy", 12) + "<span>" + tr("复制接力词", "Copy Handoff") + "</span></button>" +
                (item.worktree ? '<button class="btn btn-sm" data-copy-val="' + escapeHtml(item.worktree) + '" data-copy-msg="' + tr("已复制工作目录路径", "Copied worktree path") + '" type="button">' + icon("folder", 12) + "<span>" + tr("复制目录", "Copy Dir") + "</span></button>" : "") +
                (item.branch ? '<button class="btn btn-sm" data-copy-val="' + escapeHtml(item.branch) + '" data-copy-msg="' + tr("已复制分支名", "Copied branch name") + '" type="button">' + icon("branch", 12) + "<span>" + tr("复制分支", "Copy Branch") + "</span></button>" : "") +
                (startCmd ? '<button class="btn btn-sm" data-copy-val="' + escapeHtml(startCmd) + '" data-copy-msg="' + tr("已复制终端命令", "Copied CLI command") + '" type="button">' + icon("terminal", 12) + "<span>" + tr("终端命令", "CLI Cmd") + "</span></button>" : "") +
                (repoMeta.repoUrl ? '<a class="btn btn-sm" href="' + escapeHtml(repoMeta.repoUrl) + '" target="_blank" rel="noopener noreferrer">' + forgeIcon(repoMeta.forgeType, 12) + "<span>" + escapeHtml(forgeLabel(repoMeta.forgeType)) + tr(" 主页", " Home") + "</span></a>" : "") +
                renderPrimaryLinkBtn(item, "btn-sm", { iconSize: 12, stopOpen: false }) +
              "</div>" +
            "</div>" +
            '<div class="console-well">' + wellHtml + "</div>" +
          "</section>"
        );
      }

      function taskStatusMeta(rawStatus) {
        const st = String(rawStatus || "planned");
        if (st === "done") return { cls: "is-done", sym: "✓", label: tr("已完成", "done") };
        if (st === "in_progress") return { cls: "is-prog", sym: "◐", label: tr("进行中", "active") };
        if (st === "blocked") return { cls: "is-blk", sym: "✗", label: tr("受阻", "blocked") };
        if (st === "deferred") return { cls: "", sym: "⏸", label: tr("暂缓", "deferred") };
        if (st === "cancelled") return { cls: "", sym: "⊘", label: tr("已取消", "cancelled") };
        return { cls: "", sym: "○", label: tr("待开始", "planned") };
      }

      function renderTaskChips(tasks) {
        const list = tasks || [];
        if (!list.length) return "";
        return (
          '<div class="wt-tasks-strip">' +
          list.map((t) => {
            const meta = taskStatusMeta(t.status);
            const rawTitle = String(t.title || t.id || "TASK");
            const prefixRe = new RegExp("^" + String(t.id || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "[：:\\s]+");
            const cleanTitle = t.id && prefixRe.test(rawTitle) ? rawTitle.replace(prefixRe, "") : rawTitle;
            const chipText = (t.id ? (t.id + " · ") : "") + cleanTitle;
            return (
              '<span class="task-chip ' + meta.cls + '" title="' + escapeHtml((t.title || t.id || "") + " [" + (t.status || "planned") + "]") + '">' +
                "<span>" + meta.sym + "</span>" +
                "<span>" + escapeHtml(chipText) + "</span>" +
              "</span>"
            );
          }).join("") +
          "</div>"
        );
      }

      function resolvePrimaryLink(item) {
        const ch = item && item.change;
        const changeHref = safeUrl(ch && ch.url);
        if (changeHref) {
          const mrLabel = (item && item.mr_label) || (item && item.forge_type === "gitlab" ? "MR" : "PR");
          return {
            href: changeHref,
            label: tr("打开 " + mrLabel, "Open " + mrLabel),
            kind: "change"
          };
        }
        if (item && item._kind === "orphan") {
          const orphHref = safeUrl(item.url);
          if (orphHref) {
            const mrLabel = item.mr_label || (item.forge_type === "gitlab" ? "MR" : "PR");
            return {
              href: orphHref,
              label: tr("打开 " + mrLabel, "Open " + mrLabel),
              kind: "change"
            };
          }
        }
        const issueHref = safeUrl(item && item.url);
        if (issueHref) {
          return {
            href: issueHref,
            label: tr("打开 Issue", "Open Issue"),
            kind: "issue"
          };
        }
        return null;
      }

      function renderPrimaryLinkBtn(item, extraCls, opts) {
        const link = resolvePrimaryLink(item);
        if (!link) return "";
        const options = opts || {};
        const iconSize = options.iconSize || 11;
        const stopAttr = options.stopOpen === false ? "" : ' data-stop-open="1"';
        return '<a class="btn ' + (extraCls || "btn-xs") + '" href="' + escapeHtml(link.href) + '" target="_blank" rel="noopener noreferrer"' + stopAttr + ">" + icon("externalLink", iconSize) + "<span>" + escapeHtml(link.label) + "</span></a>";
      }

      function renderCockpitView(items) {
        const rankStage = (item) => {
          const k = parseStage(item.stage).key;
          if (k === "修 CI" || k === "受阻") return 0;
          if (k === "开发中" || k === "CI 运行中" || k.startsWith("待提") || k.startsWith("草稿")) return 1;
          if (k === "待合入") return 2;
          if (k === "待处理") return 4;
          return 3;
        };

        const issueRows = items.filter((it) => it._kind === "issue").sort((a, b) => {
          const ra = rankStage(a);
          const rb = rankStage(b);
          if (ra !== rb) return ra - rb;
          return Number(b.issue_number || 0) - Number(a.issue_number || 0);
        });
        const localRows = items.filter((it) => it._kind !== "issue");
        const activeCount = issueRows.filter((it) => it.worktree || it.change || (it.tasks && it.tasks.length > 0)).length;
        const todoCount = issueRows.filter((it) => !(it.worktree || it.change || (it.tasks && it.tasks.length > 0))).length;

        const displayIssues = state.todoOnly
          ? issueRows.filter((it) => !(it.worktree || it.change || (it.tasks && it.tasks.length > 0)))
          : issueRows;
        const allSelectable = [...displayIssues, ...localRows];
        let selected = items.find((it) => it._key === state.selectedKey);
        if (!selected) {
          selected = allSelectable[0] || items[0] || null;
          if (selected) state.selectedKey = selected._key;
        }

        const renderWtRow = (item) => {
          const isSel = selected && selected._key === item._key;
          const dotCls = itemDotClass(item);
          const stInfo = parseStage(item.stage);
          const { total, done } = getProgressNumbers(item);
          const pulseHtml = renderPulseSummary(item.pulse);
          const handoffPrompt = buildHandoffPrompt(item);
          const stageBadge = '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>";
          const progBadge = total > 0 ? '<span class="badge">' + done + "/" + total + " TASK</span>" : "";
          const chBadge = item.change ? renderChangeInline(item) : "";
          const primaryLinkBtn = renderPrimaryLinkBtn(item, "btn-xs");

          const subParts = [];
          if (item.branch) subParts.push("<span>" + escapeHtml(item.branch) + "</span>");
          if (item.worktree) subParts.push("<span>" + escapeHtml(shortWorktreePath(item.worktree)) + "</span>");
          if (pulseHtml) subParts.push("<span>" + pulseHtml + "</span>");

          return (
            '<div class="wt-row ' + (isSel ? "is-selected" : "") + '" data-select-key="' + escapeHtml(item._key) + '">' +
              '<div class="wt-row-left">' +
                '<span class="status-dot ' + dotCls + ' wt-row-dot"></span>' +
                '<div class="wt-row-main">' +
                  '<div class="wt-row-top">' +
                    renderIdHtml(item) +
                    '<span class="wt-row-title">' + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "</span>" +
                    renderRepoChip(item, { compact: true }) +
                    stageBadge +
                    progBadge +
                    chBadge +
                  "</div>" +
                  '<div class="wt-row-sub">' + (subParts.length ? subParts.join("<span>·</span>") : "<span>" + tr("尚未创建工作目录 · 点击右侧接力词即可让 Agent 开工", "Worktree not created yet · Copy Handoff to start") + "</span>") + "</div>" +
                  renderTaskChips(item.tasks) +
                "</div>" +
              "</div>" +
              '<div class="wt-row-actions" data-stop-open="1">' +
                primaryLinkBtn +
                '<button class="btn btn-xs ' + (isSel ? "btn-primary" : "") + '" data-copy-val="' + escapeHtml(handoffPrompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" data-stop-open="1" type="button">' + icon("copy", 11) + "<span>" + tr("接力词", "Handoff") + "</span></button>" +
                (item.worktree ? '<button class="btn btn-xs" data-copy-val="' + escapeHtml(item.worktree) + '" data-copy-msg="' + tr("已复制工作目录路径", "Copied worktree path") + '" data-stop-open="1" type="button">' + icon("folder", 11) + "<span>" + tr("目录", "Dir") + "</span></button>" : "") +
                (item.branch ? '<button class="btn btn-xs" data-copy-val="' + escapeHtml(item.branch) + '" data-copy-msg="' + tr("已复制分支名", "Copied branch name") + '" data-stop-open="1" type="button">' + icon("branch", 11) + "<span>" + tr("分支", "Branch") + "</span></button>" : "") +
              "</div>" +
            "</div>"
          );
        };

        const wtPill = activeCount > 0
          ? '<button class="btn btn-xs ' + (state.worktreeOnly ? "btn-primary" : "") + '" data-kpi-action="toggle-wt" type="button">' +
              icon("sparkle", 11) + "<span>" + tr("进行中", "Active") + " (" + activeCount + ")</span>" +
            "</button>"
          : "";
        const todoPill = todoCount > 0
          ? '<button class="btn btn-xs ' + (state.todoOnly ? "btn-primary" : "") + '" data-kpi-action="toggle-todo" type="button">' +
              icon("circle", 11) + "<span>" + tr("待处理 Issue", "Open Issues") + " (" + todoCount + ")</span>" +
            "</button>"
          : "";

        const localSection = localRows.length > 0 && !state.todoOnly
          ? '<section class="bento-card" style="margin-bottom:12px;">' +
              '<div class="bento-hdr">' +
                '<div class="bento-title-row">' +
                  '<span class="bento-title">' + tr("本地未绑定 Issue 工作树", "Local Worktrees (No Issue #)") + "</span>" +
                  '<span class="bento-sub num">' + localRows.length + "</span>" +
                "</div>" +
              "</div>" +
              '<div class="wt-list">' + localRows.map(renderWtRow).join("") + "</div>" +
            "</section>"
          : "";

        return (
          '<section class="bento-card" style="margin-bottom:12px;">' +
            '<div class="bento-hdr">' +
              '<div class="bento-title-row">' +
                '<span class="bento-title">' + (state.todoOnly ? tr("待处理 Issue", "Open Issues") : tr("Issue 进度总览", "Issues & Tasks")) + "</span>" +
                '<span class="bento-sub num">' + displayIssues.length + (state.todoOnly ? " items" : " issues") + "</span>" +
              "</div>" +
              '<div class="bento-actions">' + wtPill + todoPill + "</div>" +
            "</div>" +
            '<div class="wt-list">' +
              (displayIssues.length ? displayIssues.map(renderWtRow).join("") : '<div class="col-empty">' + tr("当前筛选条件下暂无 Issue", "No issues match the current filter") + "</div>") +
            "</div>" +
          "</section>" +
          localSection +
          '<div id="cockpit-console-slot">' + renderCockpitConsole(selected) + "</div>"
        );
      }

      function cardBucket(item) {
        if (item._kind === "orphan") {
          return item.checks_overall === "FAIL" || item.checks_overall === "PENDING" || item.isDraft ? "review" : "ready";
        }
        const key = parseStage(item.stage).key;
        if (key === "待处理" || key === "待认领") return "todo";
        if (key === "待合入" || key === "已完成" || key.startsWith("待提")) return "ready";
        if (key === "修 CI" || key === "CI 运行中" || key.startsWith("草稿")) return "review";
        return "developing";
      }

      function renderCard(item, opts) {
        const options = opts || {};
        const stInfo = parseStage(item.stage);
        const { total, done, pct } = getProgressNumbers(item);
        const handoffPrompt = buildHandoffPrompt(item);
        const isSelected = state.inspectedKey === item._key;
        const ctxParts = [];
        if (item.branch) {
          ctxParts.push('<button type="button" class="copy-chip" data-copy-val="' + escapeHtml(item.branch) + '" data-copy-msg="' + tr("已复制分支名", "Copied branch name") + '" data-stop-open="1">' + icon("branch", 11) + "<span>" + escapeHtml(item.branch) + "</span></button>");
        }
        if (item.worktree) {
          ctxParts.push('<button type="button" class="copy-chip" data-copy-val="' + escapeHtml(item.worktree) + '" data-copy-msg="' + tr("已复制工作目录路径", "Copied worktree path") + '" data-stop-open="1">' + icon("folder", 11) + "<span>" + escapeHtml(shortWorktreePath(item.worktree)) + "</span></button>");
        }
        if (item.current_task) {
          ctxParts.push('<div class="card-task">' + icon("chevronRight", 12) + "<span>" + escapeHtml(item.current_task) + "</span></div>");
        }
        if (total > 0) {
          ctxParts.push('<div class="card-prog"><div class="progress-track"><div class="progress-fill" data-prog-key="card:' + escapeHtml(item._key) + '" data-prog-pct="' + pct + '" style="width:' + pct + '%"></div></div><span class="prog-num">' + done + "/" + total + "</span></div>");
        }
        if (item.change) {
          ctxParts.push(renderChangeInline(item));
        }

        const pulseHtml = renderPulseSummary(item.pulse);
        const cardChip = renderRepoChip(item, { compact: true, hideName: !options.showRepo });
        return (
          '<article class="card ' + (isSelected ? "is-selected" : "") + '" data-open-key="' + escapeHtml(item._key) + '">' +
            '<div class="card-top">' +
              '<div class="card-meta">' + cardChip + renderIdHtml(item) + "</div>" +
              '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>" +
            "</div>" +
            '<div class="card-title">' + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "</div>" +
            (ctxParts.length ? '<div class="card-context">' + ctxParts.join("") + "</div>" : "") +
            '<div class="card-foot"><span>' + (pulseHtml || " ") + '</span><span style="display:inline-flex;gap:5px;">' + renderPrimaryLinkBtn(item, "btn-xs") + '<button class="btn btn-xs" data-copy-val="' + escapeHtml(handoffPrompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" data-stop-open="1" type="button">' + icon("copy", 11) + "<span>" + tr("接力词", "Handoff") + "</span></button></span></div>" +
          "</article>"
        );
      }

      function renderListTable(items) {
        const rowsHtml = items.map((item) => {
          const stInfo = parseStage(item.stage);
          const { total, done, pct } = getProgressNumbers(item);
          const handoffPrompt = buildHandoffPrompt(item);
          const isSelected = state.inspectedKey === item._key;
          const locParts = [];
          if (item.branch) {
            locParts.push('<button type="button" class="copy-chip" data-copy-val="' + escapeHtml(item.branch) + '" data-copy-msg="' + tr("已复制分支名", "Copied branch name") + '" data-stop-open="1">' + icon("branch", 11) + "<span>" + escapeHtml(item.branch) + "</span></button>");
          }
          if (item.worktree) {
            locParts.push('<button type="button" class="copy-chip" data-copy-val="' + escapeHtml(item.worktree) + '" data-copy-msg="' + tr("已复制工作目录路径", "Copied worktree path") + '" data-stop-open="1">' + icon("folder", 11) + "<span>" + escapeHtml(shortWorktreePath(item.worktree)) + "</span></button>");
          }
          const progHtml = total > 0
            ? '<div style="display:flex;align-items:center;gap:6px;min-width:96px;"><div class="progress-track"><div class="progress-fill" data-prog-key="list:' + escapeHtml(item._key) + '" data-prog-pct="' + pct + '" style="width:' + pct + '%"></div></div><span class="prog-num">' + done + "/" + total + "</span></div>"
            : '<span style="color:var(--text-faint);">—</span>';
          return (
            '<tr class="' + (isSelected ? "is-selected" : "") + '" data-open-key="' + escapeHtml(item._key) + '">' +
              "<td><div style=\"display:flex;align-items:center;gap:6px;max-width:210px;min-width:0;\">" + renderIdHtml(item) + "<span style=\"min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;\" title=\"" + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "\">" + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "</span></div></td>" +
              "<td>" + renderRepoChip(item, { compact: true }) + "</td>" +
              '<td><span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span></td>" +
              "<td>" + (locParts.length ? '<div style="display:flex;flex-direction:column;gap:4px;max-width:155px;">' + locParts.join("") + "</div>" : "—") + "</td>" +
              "<td>" + progHtml + "</td>" +
              "<td>" + (renderPulseSummary(item.pulse) || "—") + "</td>" +
              "<td>" + (renderChangeInline(item) || "—") + "</td>" +
              '<td><div style="display:inline-flex;gap:5px;white-space:nowrap;">' + renderPrimaryLinkBtn(item, "btn-xs") + '<button class="btn btn-xs" data-copy-val="' + escapeHtml(handoffPrompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" data-stop-open="1" type="button">' + icon("copy", 11) + "<span>" + tr("接力词", "Handoff") + "</span></button></div></td>" +
            "</tr>"
          );
        }).join("");

        return (
          '<div class="list-wrap">' +
            '<table class="list-table">' +
              "<thead><tr><th>" + tr("Issue / 标题", "Issue / Title") + "</th><th>" + tr("仓库", "Repo") + "</th><th>" + tr("状态", "Stage") + "</th><th>" + tr("分支 / 工作目录", "Branch / Worktree") + "</th><th>" + tr("步骤进度", "Progress") + "</th><th>" + tr("实时动态", "Pulse") + "</th><th>PR/MR &amp; CI</th><th>" + tr("操作", "Action") + "</th></tr></thead>" +
              "<tbody>" + rowsHtml + "</tbody>" +
            "</table>" +
          "</div>"
        );
      }

      function skelBar(w, h) {
        return '<span class="skel-block" style="width:' + w + ";height:" + (h || 12) + 'px;"></span>';
      }

      function renderMainSkeleton(bannerTitle, bannerSub) {
        const statusBar =
          '<div class="init-status-bar">' +
            '<span class="init-status-left">' + icon("refresh", 13) + "<span>" + escapeHtml(bannerTitle) + "</span></span>" +
            (bannerSub ? '<span class="init-status-sub">' + escapeHtml(bannerSub) + "</span>" : "") +
          "</div>";

        if (state.viewMode === "kanban") {
          const cols = [0, 1, 2, 3].map(() =>
            '<section class="column">' +
              '<div class="col-hdr">' + skelBar("76px", 13) + skelBar("18px", 12) + "</div>" +
              '<div class="card-stack">' +
                [0, 1].map(() =>
                  '<div class="card" style="cursor:default;">' +
                    '<div class="card-top">' + skelBar("84px", 16) + skelBar("48px", 16) + "</div>" +
                    '<div style="margin-top:9px;">' + skelBar("86%", 14) + "</div>" +
                    '<div style="margin-top:8px;">' + skelBar("60%", 11) + "</div>" +
                    '<div style="margin-top:10px;display:flex;justify-content:space-between;">' + skelBar("72px", 11) + skelBar("52px", 18) + "</div>" +
                  "</div>"
                ).join("") +
              "</div>" +
            "</section>"
          ).join("");
          return statusBar + '<div class="kanban">' + cols + "</div>";
        }

        if (state.viewMode === "repos") {
          const sections = [0, 1].map(() =>
            '<section class="repo-section">' +
              '<div class="repo-hdr"><div>' + skelBar("140px", 15) + '<div style="margin-top:6px;">' + skelBar("210px", 11) + "</div></div>" + skelBar("64px", 18) + "</div>" +
              '<div class="repo-grid">' +
                [0, 1].map(() =>
                  '<div class="card" style="cursor:default;">' +
                    '<div class="card-top">' + skelBar("72px", 16) + skelBar("48px", 16) + "</div>" +
                    '<div style="margin-top:9px;">' + skelBar("82%", 14) + "</div>" +
                    '<div style="margin-top:8px;">' + skelBar("54%", 11) + "</div>" +
                  "</div>"
                ).join("") +
              "</div>" +
            "</section>"
          ).join("");
          return statusBar + sections;
        }

        if (state.viewMode === "list") {
          const rows = [0, 1, 2, 3, 4].map(() =>
            "<tr>" +
              "<td>" + skelBar("190px", 13) + "</td>" +
              "<td>" + skelBar("76px", 16) + "</td>" +
              "<td>" + skelBar("58px", 16) + "</td>" +
              "<td>" + skelBar("120px", 12) + "</td>" +
              "<td>" + skelBar("88px", 10) + "</td>" +
              "<td>" + skelBar("70px", 12) + "</td>" +
              "<td>" + skelBar("64px", 16) + "</td>" +
              "<td>" + skelBar("52px", 20) + "</td>" +
            "</tr>"
          ).join("");
          return (
            statusBar +
            '<div class="list-wrap"><table class="list-table"><thead><tr>' +
              "<th>" + tr("Issue / 标题", "Issue / Title") + "</th>" +
              "<th>" + tr("仓库", "Repo") + "</th>" +
              "<th>" + tr("状态", "Stage") + "</th>" +
              "<th>" + tr("分支 / 工作目录", "Branch / Worktree") + "</th>" +
              "<th>" + tr("步骤进度", "Progress") + "</th>" +
              "<th>" + tr("实时动态", "Pulse") + "</th>" +
              "<th>PR/MR &amp; CI</th>" +
              "<th>" + tr("操作", "Action") + "</th>" +
            "</tr></thead><tbody>" + rows + "</tbody></table></div>"
          );
        }

        const wtSkelRows = [0, 1, 2, 3].map((idx) =>
          '<div class="skel-wt-row">' +
            '<div class="wt-row-left" style="align-items:center;">' +
              '<span class="skel-block" style="width:8px;height:8px;border-radius:50%;flex-shrink:0;"></span>' +
              '<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:7px;">' +
                '<div style="display:flex;align-items:center;gap:8px;">' + skelBar("34px", 14) + skelBar((52 + idx * 8) + "%", 14) + skelBar("62px", 16) + "</div>" +
                '<div style="display:flex;align-items:center;gap:8px;">' + skelBar("130px", 11) + skelBar("90px", 11) + "</div>" +
              "</div>" +
            "</div>" +
            '<div style="display:flex;gap:6px;flex-shrink:0;">' + skelBar("56px", 22) + skelBar("48px", 22) + "</div>" +
          "</div>"
        ).join("");

        return (
          statusBar +
          '<section class="bento-card" style="margin-bottom:12px;">' +
            '<div class="bento-hdr"><div class="bento-title-row">' + skelBar("108px", 15) + skelBar("48px", 12) + "</div></div>" +
            '<div class="wt-list">' + wtSkelRows + "</div>" +
          "</section>" +
          '<section class="bento-card">' +
            '<div class="bento-hdr"><div class="bento-title-row">' + skelBar("132px", 15) + skelBar("90px", 12) + "</div></div>" +
            '<div class="console-well" style="display:flex;flex-direction:column;gap:9px;">' +
              skelBar("46%", 12) + skelBar("68%", 12) + skelBar("38%", 12) +
            "</div>" +
          "</section>"
        );
      }

      function renderLoadingState() {
        const logoEl = document.getElementById("ws-logo");
        const titleEl = document.getElementById("ws-title");
        const scopeEl = document.getElementById("scope-tag");
        if (logoEl) {
          logoEl.className = "ws-logo";
          logoEl.innerHTML = icon("branch", 15);
        }
        if (titleEl) titleEl.textContent = tr("全局工作区", "Global Workspace");
        if (scopeEl) {
          scopeEl.style.display = "none";
        }

        const repoCntEl = document.getElementById("sb-repo-cnt");
        const wtCntEl = document.getElementById("sb-wt-cnt");
        if (repoCntEl) repoCntEl.textContent = state.initError ? "0" : "…";
        if (wtCntEl) wtCntEl.textContent = state.initError ? "0" : "…";

        const sbSkel = (widths) => widths.map((w) =>
          '<div class="sb-skel-row"><span style="display:inline-flex;align-items:center;gap:8px;">' +
            '<span class="skel-block" style="width:16px;height:16px;border-radius:5px;"></span>' +
            '<span class="hide-collapsed">' + skelBar(w + "px", 12) + "</span>" +
          '</span><span class="hide-collapsed">' + skelBar("24px", 11) + "</span></div>"
        ).join("");
        const sbFilters = document.getElementById("sb-filters");
        const repoPills = document.getElementById("repo-pills");
        const wtList = document.getElementById("wt-rail-list");
        if (sbFilters) sbFilters.innerHTML = sbSkel([74, 62, 80]);
        if (repoPills) repoPills.innerHTML = sbSkel([82, 96, 68]);
        if (wtList) wtList.innerHTML = sbSkel([92, 78]);

        const kpisEl = document.getElementById("kpis");
        if (kpisEl) {
          const pills = new Array(8).fill('<span class="seg-pill skel"></span>').join("");
          kpisEl.innerHTML = [0, 1, 2].map(() =>
            '<div class="bento-metric is-skel">' +
              '<div class="metric-hdr"><span class="metric-hdr-left">' + skelBar("88px", 12) + "</span></div>" +
              '<div class="metric-val-row" style="margin-top:8px;">' + skelBar("48px", 26) + skelBar("34px", 13) + "</div>" +
              '<div class="seg-bar">' + pills + "</div>" +
              skelBar("66%", 11) +
            "</div>"
          ).join("");
        }

        const warnsWrap = document.getElementById("warnings-wrap");
        if (warnsWrap) warnsWrap.innerHTML = "";

        const container = document.getElementById("main-content");
        if (!container) return;
        if (state.initError) {
          container.innerHTML =
            '<div class="empty-state is-error">' +
              '<div style="color:var(--red);margin-bottom:8px;">' + icon("alertTriangle", 22) + "</div>" +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">' + tr("无法加载工作台数据", "Failed to load board data") + "</h3>" +
              '<p style="margin:0 0 14px;font-size:12.5px;">' + escapeHtml(state.initError) + "</p>" +
              '<button class="btn btn-primary" type="button" data-retry-init="1">' + icon("refresh", 12) + "<span>" + tr("立即重试", "Retry Now") + "</span></button>" +
            "</div>";
        } else {
          const sub = state.slowInit
            ? tr("纳管仓库较多或响应较慢，仍在全力扫描中…", "Large workspace or slow response, still scanning…")
            : tr("首屏就绪后将自动同步远端状态", "Remote status syncs automatically once local scan finishes");
          container.innerHTML = renderMainSkeleton(
            tr("正在初始化工作区，扫描本机 Git 仓库与 Worktree…", "Initializing workspace — scanning local Git repositories and worktrees…"),
            sub
          );
        }

        const footerEl = document.getElementById("footer");
        if (footerEl) {
          footerEl.innerHTML =
            "<span>" + tr("正在连接本地 IDD 看板服务…", "Connecting to local IDD dashboard server…") + "</span>" +
            "<span>" + tr("快捷键 <code>[</code> 收起侧栏 · <code>/</code> 搜索 · <code>r</code> 同步远端", "Shortcuts: <code>[</code> sidebar · <code>/</code> search · <code>r</code> sync") + "</span>";
        }
      }

      function triggerMainViewEnter(container) {
        if (!container || prefersReducedMotion()) return;
        container.classList.remove("view-enter");
        void container.offsetWidth;
        container.classList.add("view-enter");
      }

      function renderMain() {
        const snap = state.snapshot;
        const container = document.getElementById("main-content");
        if (!snap || !container) return;

        const nextContextKey = [
          state.viewMode,
          state.selectedRepo,
          state.worktreeOnly ? 1 : 0,
          state.alertsOnly ? 1 : 0,
          state.todoOnly ? 1 : 0,
          state.search.trim()
        ].join("|");
        const contextChanged = state.lastMainContextKey !== "" && state.lastMainContextKey !== nextContextKey;
        const wasData = state.hadRenderedData;

        const repos = snap.repos || [];
        if (repos.length === 0) {
          state.lastMainContextKey = nextContextKey;
          state.hadRenderedData = false;
          container.innerHTML =
            '<div class="empty-state">' +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">' + tr("暂无已纳管的 Git 仓库", "No monitored Git repositories yet") + "</h3>" +
              '<p style="margin:0;font-size:12.5px;">' + tr("在任意项目目录执行以下任一命令后，仓库会自动同步到这里：", "Run any of these commands inside a project directory to register it here:") + "</p>" +
              '<div class="empty-cmds"><code class="empty-cmd">idd start &lt;issue#&gt;</code><code class="empty-cmd">idd status</code><code class="empty-cmd">idd repos add .</code></div>' +
            "</div>";
          if (contextChanged) triggerMainViewEnter(container);
          return;
        }

        const items = collectItems(false);
        const hasFilters = Boolean(state.search.trim() || state.worktreeOnly || state.alertsOnly || state.todoOnly);
        if (items.length === 0 && snap.forge_syncing && !hasFilters) {
          state.lastMainContextKey = nextContextKey;
          state.hadRenderedData = false;
          container.innerHTML = renderMainSkeleton(
            tr("正在从远端同步 " + repos.length + " 个仓库的 Issue 与 PR/MR…", "Syncing open Issues & PR/MRs from " + repos.length + " repository(ies)…"),
            tr("同步完成后将自动展示，无需刷新页面", "Results will appear automatically once sync completes")
          );
          return;
        }
        if (items.length === 0) {
          state.lastMainContextKey = nextContextKey;
          state.hadRenderedData = false;
          container.innerHTML =
            '<div class="empty-state">' +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">' + tr("当前筛选条件下没有内容", "No matching items") + "</h3>" +
              '<p style="margin:0 0 12px;font-size:12.5px;">' + tr("可以切换仓库、清空搜索词或重置筛选。", "Try switching repositories, clearing search, or resetting filters.") + "</p>" +
              '<button class="btn" type="button" data-kpi-action="clear-filters">' + icon("refresh", 12) + "<span>" + tr("重置筛选", "Reset Filters") + "</span></button>" +
            "</div>";
          if (contextChanged) triggerMainViewEnter(container);
          return;
        }

        state.lastMainContextKey = nextContextKey;
        state.hadRenderedData = true;

        if (state.viewMode === "cockpit") {
          preserveScroll([{ root: container, selector: ".console-well" }], () => {
            container.innerHTML = renderCockpitView(items);
          });
          applyCopiedStates(container);
          syncSlidingIndicator(document.querySelector("#cockpit-console-slot .console-tabs"), ".console-tab.active", "console-tabs");
          if (contextChanged || !wasData) triggerMainViewEnter(container);
          return;
        }

        const showRepoOnCard = state.selectedRepo === "ALL" && repos.length > 1;
        if (state.viewMode === "kanban") {
          const buckets = {
            todo: { id: "todo", title: tr("待处理 Issue", "Open Issues"), dot: "quiet", items: [] },
            developing: { id: "developing", title: tr("开发中", "In Progress"), dot: "active", items: [] },
            review: { id: "review", title: tr("PR / 修 CI", "PR / Fix CI"), dot: "warm", items: [] },
            ready: { id: "ready", title: tr("待合入", "Ready to Land"), dot: "active", items: [] }
          };
          for (const item of items) {
            buckets[cardBucket(item)].items.push(item);
          }
          container.innerHTML = '<div class="kanban">' + Object.values(buckets).map((col) =>
            '<section class="column">' +
              '<div class="col-hdr"><span class="col-title"><span class="status-dot ' + col.dot + '"></span><span>' + escapeHtml(col.title) + '</span></span><span class="col-count">' + col.items.length + "</span></div>" +
              '<div class="card-stack">' + (col.items.length ? col.items.map((it) => renderCard(it, { showRepo: showRepoOnCard })).join("") : '<div class="col-empty">' + tr("暂无", "Empty") + "</div>") + "</div>" +
            "</section>"
          ).join("") + "</div>";
        } else if (state.viewMode === "repos") {
          const repoByPath = new Map((snap.repos || []).map((r) => [r.repo_path, r]));
          const byRepo = new Map();
          for (const item of items) {
            const meta = resolveRepoMeta(item);
            const key = item.repo_path || item.repo_name || "unknown";
            if (!byRepo.has(key)) {
              const rMeta = repoByPath.get(key) || {};
              byRepo.set(key, {
                name: meta.repoName || key,
                path: key,
                forge: meta.forgeType,
                repoUrl: meta.repoUrl,
                repoInit: rMeta.repo_init || {},
                items: []
              });
            }
            byRepo.get(key).items.push(item);
          }
          container.innerHTML = Array.from(byRepo.values()).map((grp) => {
            const gri = grp.repoInit || {};
            const gPending = (grp.forge === "github" || grp.forge === "gitlab") && (gri.state === "pending" || gri.state === "prompted");
            const gBusy = Boolean(state.repoInitRunning[grp.path]);
            const gPolicyBtn = gPending
              ? '<button class="btn btn-xs btn-warn' + (gBusy ? " spin" : "") + '" type="button" data-apply-repo-init="' + escapeHtml(grp.path) + '" ' + (gBusy ? "disabled" : "") + ">" +
                  icon(gBusy ? "refresh" : "alertTriangle", 11) +
                  "<span>" + (gBusy ? tr("初始化中...", "Applying...") : (gri.error ? tr("初始化失败 · 重试", "Init Failed · Retry") : tr("待初始化策略 · 一键执行", "Policy Pending · Apply"))) + "</span>" +
                "</button>"
              : "";
            return (
              '<section class="repo-section">' +
                '<div class="repo-hdr">' +
                  '<div><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
                    renderRepoChip({ forgeType: grp.forge, repoUrl: grp.repoUrl, repoName: "" }, { hideName: true, customLabel: forgeLabel(grp.forge) + (grp.repoUrl ? tr(" 主页", " Home") : "") }) +
                    "<strong>" + escapeHtml(grp.name) + "</strong>" +
                  '</div><div class="mono" style="font-size:11px;color:var(--text-faint);margin-top:3px;">' + escapeHtml(grp.path) + "</div></div>" +
                  '<div style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
                    gPolicyBtn +
                    (grp.repoUrl ? '<a class="btn btn-xs" href="' + escapeHtml(grp.repoUrl) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 11) + "<span>" + tr("进入仓库主页", "Open Repo Home") + "</span></a>" : "") +
                    '<span class="col-count">' + grp.items.length + tr(" 项", " items") + "</span>" +
                  "</div>" +
                "</div>" +
                '<div class="repo-grid">' + grp.items.map((it) => renderCard(it, { showRepo: false })).join("") + "</div>" +
              "</section>"
            );
          }).join("");
        } else {
          preserveScroll([{ root: container, selector: ".list-wrap" }], () => {
            container.innerHTML = renderListTable(items);
          });
        }
        applyProgressTransitions(container);
        applyCopiedStates(container);
        if (contextChanged || !wasData) triggerMainViewEnter(container);
      }

      function renderInspectorTabBody(item) {
        const pulse = item.pulse || null;
        const tasks = item.tasks || [];
        const changedFiles = (pulse && pulse.changed_files) || [];
        const { total, done, pct } = getProgressNumbers(item);
        if (state.inspectorTab === "files") {
          return changedFiles.length === 0
            ? '<div class="col-empty">' + tr("当前工作区干净，暂无未提交改动", "Clean working tree; no uncommitted changes") + "</div>"
            : '<div class="file-list">' + changedFiles.map((f) => {
                const code = String(f.code || "M").trim();
                const cls = code === "??" ? "untracked" : (code.includes("D") ? "deleted" : "");
                return '<div class="file-row"><span class="file-code ' + cls + '">' + escapeHtml(code) + "</span><span>" + escapeHtml(f.path) + "</span></div>";
              }).join("") + "</div>";
        }
        return tasks.length === 0
          ? '<div class="col-empty">' + (item.worktree ? tr("已建工作目录，尚未拆解任务步骤", "Worktree ready; TASK/ steps pending") : tr("暂无本地任务步骤", "No local TASK steps yet")) + "</div>"
          : '<div style="margin-bottom:10px;"><div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--text-faint);margin-bottom:5px;" class="num"><span>' + tr("总体进度", "Progress") + "</span><span>" + done + " / " + total + " (" + pct + '%)</span></div><div class="progress-track"><div class="progress-fill" data-prog-key="inspector:' + escapeHtml(item._key) + '" data-prog-pct="' + pct + '" style="width:' + pct + '%"></div></div></div>' +
            tasks.map((t) => '<div class="task-row"><div class="task-row-top"><span>' + escapeHtml(t.title || t.id) + '</span><span class="badge">' + escapeHtml(t.status || "planned") + "</span></div></div>").join("");
      }

      function closeInspectorInPlace() {
        state.inspectedKey = null;
        document.querySelectorAll(".card.is-selected, .list-table tbody tr.is-selected").forEach((el) => el.classList.remove("is-selected"));
        document.querySelectorAll("#wt-rail-list .sb-item.active").forEach((el) => {
          if (el.getAttribute("data-jump-key") !== state.selectedKey) el.classList.remove("active");
        });
        renderInspector();
        if (state.snapshot) state.lastSig = computeRenderSignature(state.snapshot);
      }

      function switchInspectorTab(nextTab) {
        const panel = document.getElementById("inspector-panel");
        const content = document.getElementById("inspector-content") || panel;
        if (!content || !state.inspectedKey || !state.snapshot) return;
        const item = collectItems(true).find((x) => x._key === state.inspectedKey);
        if (!item) return;
        state.inspectorTab = nextTab || "tasks";
        content.querySelectorAll(".tab-btn[data-inspector-tab]").forEach((btn) => {
          btn.classList.toggle("active", btn.getAttribute("data-inspector-tab") === state.inspectorTab);
        });
        syncSlidingIndicator(content.querySelector(".tabs"), ".tab-btn.active", "inspector-tabs", { underline: true });
        const pane = content.querySelector(".tab-pane");
        if (pane) {
          pane.innerHTML = renderInspectorTabBody(item);
          if (!prefersReducedMotion()) {
            pane.classList.remove("console-swap");
            void pane.offsetWidth;
            pane.classList.add("console-swap");
          }
          applyProgressTransitions(pane);
        }
        state.lastSig = computeRenderSignature(state.snapshot);
      }

      function selectCockpitItem(key) {
        const snap = state.snapshot;
        if (!snap || !key) return;
        const item = collectItems(false).find((x) => x._key === key) || collectItems(true).find((x) => x._key === key);
        if (!item) {
          state.selectedKey = key;
          renderAll(true);
          return;
        }
        state.selectedKey = key;
        const mainEl = document.getElementById("main-content");
        if (mainEl) {
          mainEl.querySelectorAll(".wt-row[data-select-key]").forEach((row) => {
            const isSel = row.getAttribute("data-select-key") === key;
            row.classList.toggle("is-selected", isSel);
            const handoffBtn = row.querySelector(".wt-row-actions [data-copy-val]");
            if (handoffBtn) handoffBtn.classList.toggle("btn-primary", isSel);
          });
        }
        const rail = document.getElementById("wt-rail-list");
        if (rail) {
          rail.querySelectorAll("[data-jump-key]").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-jump-key") === key || btn.getAttribute("data-jump-key") === state.inspectedKey);
          });
        }
        const slot = document.getElementById("cockpit-console-slot");
        if (slot) {
          preserveScroll([{ root: slot, selector: ".console-well" }], () => {
            slot.innerHTML = renderCockpitConsole(item);
          });
          if (!prefersReducedMotion()) {
            slot.classList.remove("console-swap");
            void slot.offsetWidth;
            slot.classList.add("console-swap");
          }
          applyCopiedStates(slot);
          syncSlidingIndicator(slot.querySelector(".console-tabs"), ".console-tab.active", "console-tabs");
          state.lastSig = computeRenderSignature(snap);
        } else {
          renderAll(true);
        }
      }

      function switchConsoleTab(tab) {
        const snap = state.snapshot;
        if (!snap) return;
        state.consoleTab = tab || "handoff";
        const slot = document.getElementById("cockpit-console-slot");
        const item = collectItems(false).find((x) => x._key === state.selectedKey) || collectItems(true).find((x) => x._key === state.selectedKey);
        if (!slot || !item) {
          renderAll(true);
          return;
        }
        slot.innerHTML = renderCockpitConsole(item);
        const well = slot.querySelector(".console-well");
        if (well && !prefersReducedMotion()) {
          well.classList.remove("console-swap");
          void well.offsetWidth;
          well.classList.add("console-swap");
        }
        applyCopiedStates(slot);
        syncSlidingIndicator(slot.querySelector(".console-tabs"), ".console-tab.active", "console-tabs");
        state.lastSig = computeRenderSignature(snap);
      }

      function renderInspector() {
        const overlay = document.getElementById("inspector-overlay");
        const panel = document.getElementById("inspector-panel");
        const content = document.getElementById("inspector-content") || panel;
        if (!overlay || !panel || !content) return;

        if (!state.inspectedKey || !state.snapshot) {
          overlay.classList.remove("open");
          panel.classList.remove("open");
          overlay.setAttribute("aria-hidden", "true");
          panel.setAttribute("aria-hidden", "true");
          return;
        }

        const item = collectItems(true).find((x) => x._key === state.inspectedKey);
        if (!item) {
          state.inspectedKey = null;
          overlay.classList.remove("open");
          panel.classList.remove("open");
          overlay.setAttribute("aria-hidden", "true");
          panel.setAttribute("aria-hidden", "true");
          return;
        }

        const stInfo = parseStage(item.stage);
        const pulse = item.pulse || null;
        const tasks = item.tasks || [];
        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const startCmd = targetArg && item.repo_path ? ("cd " + item.repo_path + " && idd start " + targetArg) : "";
        const handoffPrompt = buildHandoffPrompt(item);
        const tabBody = renderInspectorTabBody(item);

        preserveScroll([{ root: content, selector: ".inspector-body" }], () => {
          content.innerHTML =
            '<div class="inspector-hdr">' +
              '<div style="min-width:0;flex:1;">' +
                '<div class="card-meta" style="flex-wrap:wrap;">' + renderRepoChip(item, { compact: true }) + renderIdHtml(item) + '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>" + renderPrimaryLinkBtn(item, "btn-xs", { stopOpen: false }) + "</div>" +
                '<h2 class="inspector-title">' + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "</h2>" +
              "</div>" +
              '<button class="icon-btn" id="inspector-close-btn" type="button" aria-label="' + tr("关闭详情", "Close details") + '">' + icon("x", 15) + "</button>" +
            "</div>" +
            '<div class="inspector-body">' +
              '<div class="meta-grid">' +
                '<div class="meta-row"><span class="meta-key">' + tr("分支", "Branch") + '</span><span class="meta-val">' + escapeHtml(item.branch || "—") + "</span>" + (item.branch ? '<button class="btn btn-xs btn-icon-only" data-copy-val="' + escapeHtml(item.branch) + '" data-copy-msg="' + tr("已复制分支名", "Copied branch name") + '" type="button">' + icon("copy", 11) + "</button>" : "") + "</div>" +
                '<div class="meta-row"><span class="meta-key">' + tr("工作目录", "Worktree") + '</span><span class="meta-val">' + escapeHtml(item.worktree || tr("尚未创建", "Not created")) + "</span>" + (item.worktree ? '<button class="btn btn-xs btn-icon-only" data-copy-val="' + escapeHtml(item.worktree) + '" data-copy-msg="' + tr("已复制工作目录路径", "Copied worktree path") + '" type="button">' + icon("copy", 11) + "</button>" : "") + "</div>" +
              "</div>" +
              '<div class="handoff-box">' +
                '<div class="handoff-box-hdr"><span>' + tr("跨 Agent 接力提示词", "Cross-Agent Handoff Prompt") + '</span><button class="btn btn-xs btn-primary" data-copy-val="' + escapeHtml(handoffPrompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" type="button">' + icon("copy", 11) + "<span>" + tr("复制接力词", "Copy Handoff") + "</span></button></div>" +
                '<pre class="handoff-pre">' + escapeHtml(handoffPrompt) + "</pre>" +
              "</div>" +
              (startCmd ? '<div class="cmd-box"><div class="cmd-box-hdr"><span>' + tr("终端快捷命令", "Quick CLI Command") + '</span><button class="btn btn-xs" data-copy-val="' + escapeHtml(startCmd) + '" data-copy-msg="' + tr("已复制接手命令", "Copied command") + '" type="button">' + icon("copy", 11) + "<span>" + tr("复制", "Copy") + '</span></button></div><div class="cmd-code">$ ' + escapeHtml(startCmd) + "</div></div>" : "") +
              '<div class="tabs">' +
                '<button class="tab-btn ' + (state.inspectorTab === "tasks" ? "active" : "") + '" data-inspector-tab="tasks" type="button">' + tr("任务步骤", "Steps") + " (" + tasks.length + ")</button>" +
                '<button class="tab-btn ' + (state.inspectorTab === "files" ? "active" : "") + '" data-inspector-tab="files" type="button">' + tr("改动文件", "Files") + " (" + ((pulse && pulse.dirty_count) || 0) + ")</button>" +
              "</div>" +
              '<div class="tab-pane">' + tabBody + "</div>" +
            "</div>";
        });

        applyProgressTransitions(content);
        applyCopiedStates(content);
        overlay.classList.add("open");
        panel.classList.add("open");
        overlay.setAttribute("aria-hidden", "false");
        panel.setAttribute("aria-hidden", "false");
        syncSlidingIndicator(content.querySelector(".tabs"), ".tab-btn.active", "inspector-tabs", { underline: true });
      }

      function buildFallbackAuthHosts() {
        const snap = state.snapshot;
        if (!snap) return [];
        const map = new Map();
        for (const a of snap.auth_alerts || []) {
          const k = a.host || a.api_base || "";
          if (!k) continue;
          map.set(k, {
            host: a.host || k,
            api_base: a.api_base || k,
            forge: a.forge || "gitlab",
            repos: (a.repos || []).map((name) => {
              const r = (snap.repos || []).find((x) => x.repo_name === name);
              return { name, url: (r && r.repo_url) || "", path: (r && r.repo_path) || "" };
            }),
            configured: false,
            auth_source: "missing",
            masked_token: "",
            username: "",
            token_url: a.token_url || "",
            can_remove: false
          });
        }
        for (const r of snap.repos || []) {
          if (r.forge !== "github" && r.forge !== "gitlab") continue;
          const u = safeUrl(r.repo_url);
          if (!u) continue;
          let hostKey = "";
          let apiBase = "";
          try {
            const parsed = new URL(u);
            hostKey = parsed.host;
            apiBase = parsed.origin;
          } catch (_e) {
            continue;
          }
          if (!map.has(hostKey) && !map.has(apiBase)) {
            map.set(hostKey, {
              host: hostKey,
              api_base: apiBase,
              forge: r.forge,
              repos: [{ name: r.repo_name, url: u, path: r.repo_path || "" }],
              configured: Boolean(r.forge_connected),
              auth_source: r.forge_connected ? "ready" : "missing",
              masked_token: "",
              username: "",
              token_url: r.forge === "gitlab"
                ? (apiBase + "/-/user_settings/personal_access_tokens?name=IDD+Board&scopes=api")
                : (hostKey === "github.com"
                    ? "https://github.com/settings/tokens/new?description=IDD+Board&scopes=repo"
                    : (apiBase + "/settings/tokens/new?description=IDD+Board&scopes=repo")),
              can_remove: false
            });
          } else {
            const existing = map.get(hostKey) || map.get(apiBase);
            if (existing && !existing.repos.some((x) => x.name === r.repo_name)) {
              existing.repos.push({ name: r.repo_name, url: u, path: r.repo_path || "" });
            }
          }
        }
        return Array.from(map.values());
      }

      async function fetchAuthStatus() {
        try {
          const res = await fetch("/api/auth/status", { cache: "no-store" });
          if (!res.ok) return;
          state.authStatus = await res.json();
          syncHeaderControls();
          if (state.setupOpen) renderSetupModal();
        } catch (_err) {
          /* ignore offline probe error */
        }
      }

      async function submitHostToken(targetHost, forgeType, rawToken, skipVerify) {
        const cleaned = String(rawToken || "").trim();
        if (!cleaned) {
          state.authErrors[targetHost] = tr("请先粘贴生成的个人访问令牌（Token）", "Please paste your Personal Access Token first");
          state.shakeFieldKey = targetHost;
          state.lastTopAlertsSig = "";
          renderTopAlerts(state.snapshot);
          if (state.setupOpen) renderSetupModal();
          return false;
        }
        state.authSavingHost = targetHost;
        delete state.authErrors[targetHost];
        state.lastTopAlertsSig = "";
        renderTopAlerts(state.snapshot);
        if (state.setupOpen) renderSetupModal();
        try {
          const res = await fetch("/api/auth/save", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-IDD-Request": "1"
            },
            body: JSON.stringify({
              host: targetHost,
              forge: forgeType,
              token: cleaned,
              no_verify: Boolean(skipVerify),
              auto_repo_init: Boolean(state.autoRepoInit)
            })
          });
          const data = await res.json();
          if (!res.ok || !data.ok) {
            throw new Error(data.error || ("HTTP " + res.status));
          }
          delete state.tokenDrafts[targetHost];
          delete state.editingHosts[targetHost];
          if (data.auth) state.authStatus = data.auth;
          state.showCustomHostForm = false;
          state.customHostUrl = "";
          state.customHostToken = "";
          const who = data.username ? (" (@" + data.username + ")") : "";
          const riRes = Array.isArray(data.repo_init_results) ? data.repo_init_results : [];
          const riAlignedCnt = riRes.filter((x) => x && x.ok && x.aligned).length;
          const riFailCnt = riRes.filter((x) => x && !x.ok).length;
          let toastMsg = tr("令牌已保存并验证成功" + who + "，正在同步远端数据...", "Token verified & saved" + who + "; syncing remote data...");
          if (riAlignedCnt > 0 && riFailCnt === 0) {
            toastMsg = tr("令牌已保存" + who + "，已自动初始化 " + riAlignedCnt + " 个仓库的线性 Squash 策略", "Saved" + who + " & auto-initialized " + riAlignedCnt + " repo(s)");
          } else if (riFailCnt > 0) {
            toastMsg = tr("令牌已保存" + who + "；" + riFailCnt + " 个仓库自动初始化未完成，可点击重试", "Saved" + who + "; " + riFailCnt + " repo(s) pending retry");
          }
          showToast(toastMsg, riFailCnt > 0 ? "err" : "ok");
          await fetchSnapshot(false);
          await fetchAuthStatus();
          state.lastTopAlertsSig = "";
          renderTopAlerts(state.snapshot);
          if (state.setupOpen) renderSetupModal();
          return true;
        } catch (err) {
          state.authErrors[targetHost] = err.message || tr("保存失败", "Failed to save token");
          state.shakeFieldKey = targetHost;
          state.lastTopAlertsSig = "";
          renderTopAlerts(state.snapshot);
          if (state.setupOpen) renderSetupModal();
          return false;
        } finally {
          state.authSavingHost = "";
        }
      }

      async function applyRepoInit(repoPathOrAll) {
        const key = repoPathOrAll || "__all__";
        if (state.repoInitRunning[key]) return false;
        state.repoInitRunning[key] = true;
        delete state.repoInitErrors[key];
        state.lastTopAlertsSig = "";
        renderAll(true);
        renderTopAlerts(state.snapshot);
        if (state.setupOpen) renderSetupModal();
        try {
          const payload = key === "__all__" ? { all: true } : { repo_path: key };
          const res = await fetch("/api/repo/init", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-IDD-Request": "1"
            },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (!res.ok) {
            throw new Error(data.error || ("HTTP " + res.status));
          }
          if (!data.ok) {
            const errMsg = data.error || tr("初始化策略未完成", "Failed to apply repo merge policy");
            state.repoInitErrors[key] = errMsg;
            showToast(tr("初始化未完成: ", "Init incomplete: ") + errMsg, "err");
          } else {
            const cnt = Number(data.applied_count || 0);
            showToast(
              cnt > 1
                ? tr("已完成 " + cnt + " 个仓库线性 Squash 策略与模板初始化", "Initialized " + cnt + " repositories")
                : tr("已完成仓库线性 Squash 策略与提交模板初始化", "Initialized linear Squash policy & commit templates")
            );
          }
          await fetchSnapshot(false);
          state.lastTopAlertsSig = "";
          renderAll(true);
          renderTopAlerts(state.snapshot);
          if (state.setupOpen) renderSetupModal();
          return Boolean(data.ok);
        } catch (err) {
          state.repoInitErrors[key] = err.message || tr("请求失败", "Request failed");
          showToast(tr("初始化失败: ", "Init failed: ") + state.repoInitErrors[key], "err");
          return false;
        } finally {
          delete state.repoInitRunning[key];
          renderAll(true);
          renderTopAlerts(state.snapshot);
          if (state.setupOpen) renderSetupModal();
        }
      }

      async function setAutoMergeSetting(scope, repoPath, value) {
        const busyKey = scope === "global" ? "__global__" : (repoPath || "");
        if (!busyKey || state.autoMergeSaving[busyKey]) return false;
        state.autoMergeSaving[busyKey] = true;
        renderAll(true);
        if (state.setupOpen) renderSetupModal();
        try {
          const payload = scope === "global"
            ? { scope: "global", enabled: Boolean(value) }
            : { scope: "repo", repo_path: repoPath, value: value };
          const res = await fetch("/api/config/auto-merge", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-IDD-Request": "1"
            },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (!res.ok || !data.ok) {
            throw new Error(data.error || ("HTTP " + res.status));
          }
          if (scope === "global") {
            showToast(
              data.auto_merge
                ? tr("已开启全局默认 PR 自动准入", "Enabled global default PR Auto-Approve")
                : tr("已关闭全局默认 PR 自动准入", "Disabled global default PR Auto-Approve")
            );
          } else if (value === null) {
            showToast(tr("已恢复跟随全局 PR 自动准入设置", "Repository PR Auto-Approve reset to inherit global"));
          } else {
            showToast(
              value
                ? tr("已为该仓库开启 PR/MR 自动准入", "Enabled PR/MR Auto-Approve for repository")
                : tr("已为该仓库关闭 PR/MR 自动准入", "Disabled PR/MR Auto-Approve for repository")
            );
          }
          await fetchSnapshot(false);
          renderAll(true);
          if (state.setupOpen) renderSetupModal();
          return true;
        } catch (err) {
          showToast(tr("保存开关失败: ", "Failed to save setting: ") + (err.message || ""), "err");
          return false;
        } finally {
          delete state.autoMergeSaving[busyKey];
          renderAll(true);
          if (state.setupOpen) renderSetupModal();
        }
      }

      function openAutoMergeConfirm(scope, repoPath, nextValue) {
        const snap = state.snapshot || {};
        const globalDefault = Boolean(snap.config && snap.config.auto_merge);
        const repos = snap.repos || [];
        if (scope === "global") {
          const nextBool = Boolean(nextValue);
          if (nextBool === globalDefault) return;
          state.amConfirm = {
            scope: "global",
            repoPath: "",
            repoName: tr("全局默认（未单独覆盖的仓库）", "Global Default (all inheriting repos)"),
            mrTag: "PR",
            nextValue: nextBool,
            nextEffective: nextBool,
            globalDefault: globalDefault,
            currentOverride: null
          };
          renderAutoMergeConfirmModal();
          return;
        }
        const targetRepo = repos.find((r) => r.repo_path === repoPath);
        if (!targetRepo) return;
        const am = targetRepo.auto_merge || {};
        const currentOverride = typeof am.repo_override === "boolean" ? am.repo_override : null;
        if (nextValue === currentOverride) return;
        const nextEffective = nextValue === null ? globalDefault : Boolean(nextValue);
        state.amConfirm = {
          scope: "repo",
          repoPath: targetRepo.repo_path,
          repoName: targetRepo.repo_name || targetRepo.repo_path,
          mrTag: targetRepo.forge === "gitlab" ? "MR" : "PR",
          nextValue: nextValue,
          nextEffective: nextEffective,
          globalDefault: globalDefault,
          currentOverride: currentOverride
        };
        renderAutoMergeConfirmModal();
      }

      function closeAutoMergeConfirm() {
        state.amConfirm = null;
        renderAutoMergeConfirmModal();
      }

      function renderAutoMergeConfirmModal() {
        const overlay = document.getElementById("am-confirm-overlay");
        const modal = document.getElementById("am-confirm-modal");
        if (!overlay || !modal) return;
        const pending = state.amConfirm;
        if (!pending) {
          overlay.classList.remove("open");
          overlay.setAttribute("aria-hidden", "true");
          return;
        }
        overlay.classList.add("open");
        overlay.setAttribute("aria-hidden", "false");

        const isGlobal = pending.scope === "global";
        const isOn = Boolean(pending.nextEffective);
        const tag = pending.mrTag || "PR";
        const titleText = isOn
          ? tr("确认开启 " + tag + " 自动准入？", "Enable " + tag + " Auto-Approve?")
          : tr("确认关闭 " + tag + " 自动准入？", "Disable " + tag + " Auto-Approve?");
        const subText = isOn
          ? tr("开启后将跳过人工口头确认，由 CI 决定是否直接合入主干分支。", "Skips verbal approval and lets CI gate direct Squash merges into main.")
          : tr("关闭后将恢复为「提交 PR/MR 后等待你人工确认才合入」。", "Restores manual confirmation before any PR/MR is merged into main.");

        const scopeLabel = isGlobal
          ? tr("全局默认设置（作用于所有未单独覆盖的仓库）", "Global default (applies to all repos without overrides)")
          : (pending.nextValue === null
              ? tr("仓库「" + pending.repoName + "」· 恢复跟随全局（当前全局为" + (pending.globalDefault ? "开" : "关") + "）", "Repo \"" + pending.repoName + "\" · Inherit global (currently " + (pending.globalDefault ? "ON" : "OFF") + ")")
              : tr("仓库「" + pending.repoName + "」（仅对当前仓库生效）", "Repo \"" + pending.repoName + "\" (repo-only override)"));

        const bulletsHtml = isOn
          ? '<ul class="am-confirm-list">' +
              "<li><strong>" + tr("自动进入 CI 流水线：", "Auto-enter CI:") + "</strong>" + tr("Agent 运行 `idd pr` / `idd mr` 创建或更新变更后，不再停下来等你口头说「准入 / 合入」，直接阻塞等待远端 CI 结算（失败仍保留最多 2 轮自愈）。", "After `idd pr` / `idd mr`, the agent stops pausing for verbal approval and immediately waits for CI (keeping the 2-round self-heal limit).") + "</li>" +
              "<li><strong>" + tr("自动清理并直线合入 main：", "Auto-clean & Squash merge:") + "</strong>" + tr("CI 全部通过（或仓库未配置远端 CI 且本地测试已通过）后，自动清理临时 `TASK/` 目录、执行 Squash 直线合入 `main`、勾选 Issue 验收框并快进本地 `main`。", "Once CI passes (or no remote CI exists and local tests pass), it cleans `TASK/`, Squash-merges linearly into `main`, checks Issue acceptance boxes, and fast-forwards local `main`.") + "</li>" +
              "<li><strong>" + tr("安全暂停兜底：", "Safety pause guards:") + "</strong>" + tr("`--draft` 草稿、CI 经 2 轮修复仍失败、Rebase 冲突或 `TASK/evidence/` 含附件时，仍会立刻暂停并保留现场交由人工处理。", "Still pauses safely for `--draft` PRs, 2-round CI failures, rebase conflicts, or `TASK/evidence/` attachments.") + "</li>" +
            "</ul>"
          : '<ul class="am-confirm-list">' +
              "<li><strong>" + tr("恢复人工把关：", "Restore manual approval:") + "</strong>" + tr("Agent 提交 `idd pr` / `idd mr` 并完成 CI 检查后，将停在「待验收」状态，等待你明确同意或运行 `idd land` 后才会合入 `main`。", "After `idd pr` / `idd mr` and CI checks, the workflow pauses at Pending Review until you explicitly approve or run `idd land`.") + "</li>" +
              "<li><strong>" + tr("单仓库覆盖说明：", "Override behavior:") + "</strong>" + (isGlobal
                ? tr("关闭全局开关不会影响你曾单独设为「开」的仓库。", "Disabling the global default does not alter repositories explicitly set to ON.")
                : tr("仅覆盖当前仓库，可随时在设置弹窗切回「跟随全局」或「开」。", "Overrides only this repository; you can switch back to Inherit or ON anytime in Setup.")) + "</li>" +
            "</ul>";

        const noteHtml = isOn
          ? '<div class="am-confirm-note is-warn">' + tr("⚠ 注意：一旦开启，满足条件的 " + tag + " 将自动进入主干分支 `main`（默认仍保留开发分支与工作树目录）。请确认对应分支保护与测试门禁符合团队要求。", "⚠ Notice: Eligible " + tag + "s will merge into `main` automatically without extra confirmation (branches and worktrees remain preserved).") + "</div>"
          : '<div class="am-confirm-note is-info">' + tr("提示：你也可以单次使用 `idd pr --auto-merge` 或 `idd pr --no-auto-merge` 临时覆盖。", "Tip: You can still override per command with `idd pr --auto-merge` or `--no-auto-merge`.") + "</div>";

        const submitLabel = isOn
          ? tr("确认开启 " + tag + " 自动准入", "Confirm & Enable " + tag + " Auto-Approve")
          : tr("确认关闭 " + tag + " 自动准入", "Confirm & Disable " + tag + " Auto-Approve");
        const submitCls = isOn ? "btn btn-danger-warn" : "btn btn-primary";

        modal.setAttribute("aria-label", titleText);
        modal.innerHTML =
          '<div class="am-confirm-hdr">' +
            '<div class="am-confirm-icon ' + (isOn ? "is-warn" : "is-info") + '">' + icon(isOn ? "alertTriangle" : "pr", 18) + "</div>" +
            '<div style="min-width:0;flex:1;">' +
              '<h3 class="am-confirm-title">' + escapeHtml(titleText) + "</h3>" +
              '<p class="am-confirm-sub">' + escapeHtml(subText) + "</p>" +
            "</div>" +
            '<button class="icon-btn" type="button" data-am-confirm-cancel="1" aria-label="' + escapeHtml(tr("取消", "Cancel")) + '">' + icon("x", 15) + "</button>" +
          "</div>" +
          '<div class="am-confirm-body">' +
            '<div class="am-confirm-scope"><span>' + tr("生效范围", "Scope") + "</span><strong>" + escapeHtml(scopeLabel) + "</strong></div>" +
            bulletsHtml +
            noteHtml +
          "</div>" +
          '<div class="am-confirm-ftr">' +
            '<button class="btn" type="button" data-am-confirm-cancel="1">' + tr("取消", "Cancel") + "</button>" +
            '<button class="' + submitCls + '" type="button" data-am-confirm-submit="1">' + icon("check", 13) + "<span>" + escapeHtml(submitLabel) + "</span></button>" +
          "</div>";
      }

      async function removeHostToken(targetHost) {
        state.authSavingHost = targetHost;
        if (state.setupOpen) renderSetupModal();
        try {
          const res = await fetch("/api/auth/logout", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-IDD-Request": "1"
            },
            body: JSON.stringify({ host: targetHost })
          });
          const data = await res.json();
          if (data.auth) state.authStatus = data.auth;
          showToast(tr("已移除该主机的本地令牌", "Removed saved token for host"));
          await fetchSnapshot(false);
          state.lastTopAlertsSig = "";
          renderTopAlerts(state.snapshot);
          if (state.setupOpen) renderSetupModal();
        } catch (err) {
          showToast(tr("移除失败: ", "Remove failed: ") + err.message, "err");
        } finally {
          state.authSavingHost = "";
        }
      }

      function openSetupModal(tab) {
        state.setupOpen = true;
        if (tab) state.setupTab = tab;
        renderSetupModal();
        fetchAuthStatus();
      }

      function closeSetupModal(markDismissed) {
        state.setupOpen = false;
        if (markDismissed) {
          sessionStorage.setItem("idd_setup_dismissed", "1");
        }
        renderSetupModal();
      }

      function renderPermissionGuide(forgeType) {
        if (forgeType === "gitlab") {
          return (
            '<div class="perm-box">' +
              '<div class="perm-row"><span>' + tr("必选权限 (Scopes)：", "Required Scope:") + '</span><code class="perm-tag">✓ api</code><span style="font-size:11.5px;color:var(--text-dim);">' + tr("仅勾选这一项即可（跳转已自动预填）", "Select only this checkbox (pre-checked via link)") + "</span></div>" +
              '<div class="perm-sub">' + tr("用途：创建/同步 Issue、提交并 Squash 合入 MR、拉取 CI 状态与失败日志。注意：不要只勾只读的 read_api；到期时间按需设置或留空。", "Grants read/write access to Issues, MRs & CI failure logs. Do not select read_api alone.") + "</div>" +
            "</div>"
          );
        }
        return (
          '<div class="perm-box">' +
            '<div class="perm-row"><span>' + tr("Classic 令牌（推荐）：", "Classic Token (Recommended):") + '</span><code class="perm-tag">✓ repo</code><span style="font-size:11.5px;color:var(--text-dim);">' + tr("跳转已自动预勾；若仓库使用私有 CI 或需改 .github/workflows 可加勾 workflow", "Pre-selected via link; add workflow only if editing GitHub Actions files") + "</span></div>" +
            '<div class="perm-sub">' + tr("若用 Fine-grained 细粒度令牌：在 Repository permissions 开启 Issues (读写)、Pull requests (读写)、Contents (读写)、Actions (只读)。", "Fine-grained PAT: enable Issues (R/W), Pull requests (R/W), Contents (R/W), and Actions (Read-only).") + "</div>" +
          "</div>"
        );
      }

      function renderQuietRepoLinks(repos) {
        if (!repos || !repos.length) return "";
        const links = repos.map((r) => {
          const href = safeUrl(r.url);
          if (href) {
            return '<a class="host-repo-link" href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(r.name) + icon("externalLink", 10) + "</a>";
          }
          return '<span class="host-repo-link">' + escapeHtml(r.name) + "</span>";
        }).join("<span>·</span>");
        return '<div class="host-repo-list"><span>' + tr("仓库：", "Repos:") + "</span>" + links + "</div>";
      }

      function renderSetupModal() {
        const overlay = document.getElementById("setup-modal-overlay");
        const modal = document.getElementById("setup-modal");
        if (!overlay || !modal) return;
        if (!state.setupOpen) {
          overlay.classList.remove("open");
          overlay.setAttribute("aria-hidden", "true");
          return;
        }
        overlay.classList.add("open");
        overlay.setAttribute("aria-hidden", "false");
        modal.setAttribute("aria-label", tr("初始化配置与上手指南", "Setup & Quickstart Guide"));

        const hosts = (state.authStatus && state.authStatus.hosts) || buildFallbackAuthHosts();
        const isGuide = state.setupTab === "guide";

        let bodyHtml = "";
        if (isGuide) {
          const steps = [
            {
              step: "01",
              title: tr("聊想法，建 Issue 锚点", "Chat Ideas into an Issue"),
              desc: tr(
                "先在 AI 工具里聊清需求并按 idd 创建 Issue（自动识别 GitHub 或自建 GitLab），不在 main 分支直接裸改业务代码。",
                "Align on scope in your AI tool and open a GitHub or self-hosted GitLab Issue first—keeping main clean."
              ),
              cmd: tr('对 Agent 说："按 idd 帮我建个导出 CSV 的 Issue"', 'Say: "Create an IDD Issue for CSV export"')
            },
            {
              step: "02",
              title: tr("独立 Worktree 拆解 TASK", "Parallel Worktrees & TASKs"),
              desc: tr(
                "开工时自动拉出独立目录和规范分支，将任务拆解为可验证的 TASK 步骤，多个 Agent 同时推进互不打扰。",
                "Each Issue gets its own physical worktree, validated branch, and TASK ledger so multiple agents run in parallel safely."
              ),
              cmd: tr('对 Agent 说："按 idd 开工 #42"', 'Say: "Start Issue #42 with idd"')
            },
            {
              step: "03",
              title: tr("看板盯进度 & 一键换手接力", "Live Board & 1-Click Handoff"),
              desc: tr(
                "在看板一眼看清进度和 CI，点平台图标直达仓库或 Issue；换工具时点击「复制接力词」粘贴到新窗口即可续写。",
                "Track live progress and CI here, open repos or Issues in one click, and copy Handoff prompts when switching agents."
              ),
              cmd: tr("点击「接力词」按钮 → 粘贴到另一个 Agent 对话框", "Click [Handoff] -> Paste into another Agent")
            },
            {
              step: "04",
              title: tr("CI 全绿后线性 Squash 合入", "CI Self-Healing & Squash Land"),
              desc: tr(
                "自动提 PR / MR 并监控流水线（失败会自动拉取日志修复），全绿后清理临时 TASK 并以直线历史合入 main；可在顶栏或配置开启「PR 自动准入」免口头确认。",
                "Opens PR/MR, auto-fetches failing CI logs for fixes, cleans temporary TASK files, and squash-merges linearly into main. Enable PR Auto-Approve to skip manual confirmation."
              ),
              cmd: tr('对 Agent 说："合入 #42" 或开启 PR 自动准入', 'Say: "Land #42" or enable PR Auto-Approve')
            }
          ];
          bodyHtml =
            '<div class="guide-grid">' +
            steps.map((s) =>
              '<div class="guide-card">' +
                '<div class="guide-card-top"><span class="guide-step-pill">' + escapeHtml(s.step) + '</span><span class="guide-card-title">' + escapeHtml(s.title) + "</span></div>" +
                '<div class="guide-card-desc">' + escapeHtml(s.desc) + "</div>" +
                '<div class="guide-card-cmd">' + escapeHtml(s.cmd) + "</div>" +
              "</div>"
            ).join("") +
            "</div>";
        } else {
          const hostCards = hosts.length === 0
            ? '<div class="perm-box"><div>' + tr("暂未检测到远端仓库；你可以点击下方链接提前添加自建 GitLab 或 GitHub 主机。", "No remote repositories detected yet. You can add a GitLab or GitHub host below.") + "</div></div>"
            : hosts.map((h) => {
                const target = h.api_base || h.host;
                const isGitLab = h.forge === "gitlab";
                const plat = isGitLab ? tr("自建 GitLab", "GitLab") : "GitHub";
                const hostLabel = String(h.host || target).replace(/^https?:\/\//i, "");
                const tokenHref = safeUrl(h.token_url);
                const hostHref = safeUrl(h.api_base);
                const isEditing = !h.configured || Boolean(state.editingHosts[target]);
                const draftVal = state.tokenDrafts[target] || "";
                const errMsg = state.authErrors[target] || "";
                const saving = state.authSavingHost === target;
                const icCls = isGitLab ? "is-gitlab" : "is-github";

                if (!isEditing && h.configured) {
                  const authTag = h.auth_source === "gh_cli" ? "gh CLI" : (h.auth_source === "env" ? "ENV" : "");
                  const srcNote = h.username
                    ? ("@" + h.username + (authTag ? " · " + authTag : ""))
                    : (authTag || h.masked_token || "");
                  const compactRepos = (h.repos || []).map((r) => {
                    const href = safeUrl(r.url);
                    return href
                      ? '<a class="host-repo-link" href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(r.name) + icon("externalLink", 10) + "</a>"
                      : '<span class="host-repo-link">' + escapeHtml(r.name) + "</span>";
                  }).join("<span>·</span>");

                  return (
                    '<div class="host-row-compact">' +
                      '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;">' +
                        '<span class="host-ic sm ' + icCls + '">' + forgeIcon(h.forge, 13) + "</span>" +
                        '<span style="font-weight:600;font-size:13px;">' + escapeHtml(plat) + "</span>" +
                        (hostHref
                          ? '<a class="host-url-link" href="' + escapeHtml(hostHref) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(hostLabel) + " ↗</a>"
                          : '<span class="host-url-link">' + escapeHtml(hostLabel) + "</span>") +
                        (compactRepos ? '<span style="color:var(--text-faint);">·</span>' + compactRepos : "") +
                      "</div>" +
                      '<div style="display:inline-flex;align-items:center;gap:6px;">' +
                        '<span class="badge tone-success">' + icon("check", 11) + "<span>" + tr("已连接", "Connected") + (srcNote ? " · " + escapeHtml(srcNote) : "") + "</span></span>" +
                        '<button class="btn btn-xs" type="button" data-toggle-edit-host="' + escapeHtml(target) + '">' + tr("更换令牌", "Update") + "</button>" +
                        (h.can_remove ? '<button class="btn btn-xs" type="button" data-remove-host="' + escapeHtml(h.host) + '">' + tr("移除", "Remove") + "</button>" : "") +
                      "</div>" +
                    "</div>"
                  );
                }

                const rightHdr = h.configured
                  ? '<button class="btn btn-xs" type="button" data-toggle-edit-host="' + escapeHtml(target) + '">' + tr("收起", "Cancel") + "</button>"
                  : '<span class="badge tone-warning">' + tr("待配置", "Setup Needed") + "</span>";

                return (
                  '<div class="host-card">' +
                    '<div class="host-card-hdr">' +
                      '<div class="host-ident">' +
                        '<span class="host-ic ' + icCls + '">' + forgeIcon(h.forge, 16) + "</span>" +
                        '<div style="min-width:0;">' +
                          '<div class="host-title-line">' +
                            "<span>" + escapeHtml(plat) + "</span>" +
                            (hostHref
                              ? '<a class="host-url-link" href="' + escapeHtml(hostHref) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(hostLabel) + " ↗</a>"
                              : '<span class="host-url-link">' + escapeHtml(hostLabel) + "</span>") +
                          "</div>" +
                          renderQuietRepoLinks(h.repos) +
                        "</div>" +
                      "</div>" +
                      '<div style="display:inline-flex;align-items:center;gap:6px;flex-shrink:0;">' +
                        rightHdr +
                        (h.can_remove ? '<button class="btn btn-xs" type="button" data-remove-host="' + escapeHtml(h.host) + '">' + tr("移除", "Remove") + "</button>" : "") +
                      "</div>" +
                    "</div>" +
                    '<div class="host-flow">' +
                      '<div class="flow-step">' +
                        '<div class="flow-step-hdr">' +
                          '<span class="flow-step-title"><span class="flow-num">1</span><span>' + tr("生成个人访问令牌并勾选权限", "Create Token with Required Permissions") + "</span></span>" +
                          (tokenHref ? '<a class="btn btn-sm" href="' + escapeHtml(tokenHref) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 12) + "<span>" + tr("打开生成页面", "Open Token Page") + "</span></a>" : "") +
                        "</div>" +
                        renderPermissionGuide(h.forge) +
                      "</div>" +
                      '<div class="flow-step">' +
                        '<div class="flow-step-hdr"><span class="flow-step-title"><span class="flow-num">2</span><span>' + tr("粘贴令牌并点击保存（自动验证，无需敲命令）", "Paste Token & Save (Verified Automatically)") + "</span></span></div>" +
                        '<div class="auth-alert-form">' +
                          '<input class="token-input" type="password" autocomplete="off" data-token-draft="' + escapeHtml(target) + '" value="' + escapeHtml(draftVal) + '" placeholder="' + escapeHtml(isGitLab ? tr("粘贴 GitLab 令牌（如 glpat-...）", "Paste GitLab Token (glpat-...)") : tr("粘贴 GitHub 令牌（如 ghp_... 或 github_pat_...）", "Paste GitHub Token (ghp_...)")) + '" />' +
                          '<button class="btn btn-primary' + (saving ? " spin" : "") + '" style="height:34px;padding:0 14px;" type="button" data-save-host="' + escapeHtml(target) + '" data-save-forge="' + escapeHtml(h.forge) + '" ' + (saving ? "disabled" : "") + ">" +
                            icon(saving ? "refresh" : "check", 12) +
                            "<span>" + (saving ? tr("验证中...", "Verifying...") : tr("保存并连接", "Save & Connect")) + "</span>" +
                          "</button>" +
                        "</div>" +
                        (errMsg ? '<div class="auth-err-msg">' + escapeHtml(errMsg) + "</div>" : "") +
                      "</div>" +
                    "</div>" +
                  "</div>"
                );
              }).join("");

          const customErr = state.authErrors.__custom__ || "";
          const customSaving = Boolean(state.authSavingHost && state.authSavingHost === state.customHostUrl.trim());
          const revealCustomCls = state.revealModalCard === "__custom__" ? " card-reveal" : "";
          const customForm = state.showCustomHostForm
            ? '<div class="host-card' + revealCustomCls + '">' +
                '<div class="host-card-hdr"><strong style="font-size:13px;">' + tr("添加其他 GitLab / GitHub 主机", "Add Custom GitLab / GitHub Host") + '</strong><button class="btn btn-xs" type="button" data-toggle-custom-host="0">' + tr("收起", "Close") + "</button></div>" +
                '<div class="auth-alert-form">' +
                  '<button class="btn btn-sm ' + (state.customHostForge === "gitlab" ? "btn-primary" : "") + '" type="button" data-custom-forge="gitlab">' + forgeIcon("gitlab", 12) + "<span>GitLab</span></button>" +
                  '<button class="btn btn-sm ' + (state.customHostForge === "github" ? "btn-primary" : "") + '" type="button" data-custom-forge="github">' + forgeIcon("github", 12) + "<span>GitHub</span></button>" +
                  '<input class="token-input" type="text" id="custom-host-url" value="' + escapeHtml(state.customHostUrl) + '" placeholder="' + escapeHtml(state.customHostForge === "gitlab" ? "http://192.168.31.14:10081" : "https://github.com") + '" />' +
                "</div>" +
                renderPermissionGuide(state.customHostForge) +
                '<div class="auth-alert-form">' +
                  '<input class="token-input" type="password" id="custom-host-token" value="' + escapeHtml(state.customHostToken) + '" placeholder="' + escapeHtml(tr("粘贴生成的访问令牌 (Token)", "Paste Personal Access Token")) + '" />' +
                  '<button class="btn btn-primary' + (customSaving ? " spin" : "") + '" style="height:34px;padding:0 14px;" type="button" id="custom-host-save-btn" ' + (customSaving ? "disabled" : "") + ">" + icon(customSaving ? "refresh" : "check", 12) + "<span>" + (customSaving ? tr("验证中...", "Verifying...") : tr("保存并连接", "Save & Connect")) + "</span></button>" +
                "</div>" +
                (customErr ? '<div class="auth-err-msg">' + escapeHtml(customErr) + "</div>" : "") +
              "</div>"
            : '<div><button class="ghost-link-btn" type="button" data-toggle-custom-host="1">+ ' + tr("添加其他 GitLab / GitHub 主机", "Add Another GitLab / GitHub Host") + "</button></div>";

          const autoCheckHtml =
            '<label class="policy-check-row">' +
              '<input type="checkbox" data-auto-repo-init-toggle="1" ' + (state.autoRepoInit ? "checked" : "") + " />" +
              "<span>" + tr("连接成功后自动初始化仓库线性 Squash 策略与提交模板（`idd repo-init --apply`）", "Auto-apply linear Squash policy & commit templates after connecting") + "</span>" +
            "</label>";

          const remoteRepos = ((state.snapshot && state.snapshot.repos) || []).filter((r) => r.forge === "github" || r.forge === "gitlab");
          const pendingRemoteRepos = remoteRepos.filter((r) => {
            const ri = r.repo_init || {};
            return ri.state === "pending" || ri.state === "prompted";
          });
          const allBusy = Boolean(state.repoInitRunning.__all__);
          const policyRowsHtml = remoteRepos.length === 0
            ? ""
            : '<div class="policy-section">' +
                '<div class="policy-section-hdr">' +
                  '<span style="font-size:12.5px;font-weight:600;color:var(--text);">' + tr("仓库合入策略与模板状态", "Repository Merge Policy & Templates") + "</span>" +
                  (pendingRemoteRepos.length > 1
                    ? '<button class="btn btn-xs btn-warn' + (allBusy ? " spin" : "") + '" type="button" data-apply-repo-init="__all__" ' + (allBusy ? "disabled" : "") + ">" +
                        icon(allBusy ? "refresh" : "check", 11) +
                        "<span>" + (allBusy ? tr("全部初始化中...", "Applying All...") : tr("全部一键初始化 (" + pendingRemoteRepos.length + ")", "Apply All (" + pendingRemoteRepos.length + ")")) + "</span>" +
                      "</button>"
                    : "") +
                "</div>" +
                '<div class="policy-repo-list">' +
                  remoteRepos.map((r) => {
                    const ri = r.repo_init || {};
                    const st = ri.state || "";
                    const isAligned = st === "aligned";
                    const isPending = st === "pending" || st === "prompted";
                    const busy = Boolean(state.repoInitRunning[r.repo_path]);
                    const errText = state.repoInitErrors[r.repo_path] || ri.error || "";
                    const mmList = Array.isArray(ri.mismatches) ? ri.mismatches : [];
                    const subText = errText
                      ? tr("失败原因：", "Error: ") + errText
                      : (mmList.length ? mmList.join(" · ") : (isAligned ? tr("已锁定线性 Squash 与默认提交模板", "Linear Squash & commit templates aligned") : tr("等待首次检测或初始化", "Pending initial check")));
                    const badgeHtml = isAligned
                      ? '<span class="badge tone-success">' + icon("check", 11) + "<span>" + tr("已对齐", "Aligned") + "</span></span>"
                      : (isPending
                          ? '<button class="btn btn-xs btn-warn' + (busy ? " spin" : "") + '" type="button" data-apply-repo-init="' + escapeHtml(r.repo_path) + '" ' + (busy ? "disabled" : "") + ">" +
                              icon(busy ? "refresh" : "alertTriangle", 11) +
                              "<span>" + (busy ? tr("初始化中...", "Applying...") : (errText ? tr("重试初始化", "Retry Init") : tr("一键初始化", "Apply Now"))) + "</span>" +
                            "</button>"
                          : '<button class="btn btn-xs' + (busy ? " spin" : "") + '" type="button" data-apply-repo-init="' + escapeHtml(r.repo_path) + '" ' + (busy ? "disabled" : "") + ">" +
                              icon("refresh", 11) +
                              "<span>" + (busy ? tr("检测中...", "Checking...") : tr("立即初始化", "Initialize")) + "</span>" +
                            "</button>");
                    return (
                      '<div class="policy-repo-row">' +
                        '<div style="min-width:0;flex:1;">' +
                          '<div style="display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600;">' +
                            '<span class="host-ic sm ' + (r.forge === "gitlab" ? "is-gitlab" : "is-github") + '">' + forgeIcon(r.forge, 12) + "</span>" +
                            "<span>" + escapeHtml(r.repo_name) + "</span>" +
                          "</div>" +
                          '<div style="font-size:11px;color:' + (errText ? "var(--red)" : "var(--text-faint)") + ';margin-top:2px;word-break:break-word;">' + escapeHtml(subText) + "</div>" +
                        "</div>" +
                        badgeHtml +
                      "</div>"
                    );
                  }).join("") +
                "</div>" +
              "</div>";

          const globalAm = Boolean(state.snapshot && state.snapshot.config && state.snapshot.config.auto_merge);
          const gAmBusy = Boolean(state.autoMergeSaving.__global__);
          const autoMergeRepoRows = remoteRepos.length === 0
            ? ""
            : '<div class="policy-repo-list">' +
                remoteRepos.map((r) => {
                  const am = r.auto_merge || {};
                  const ovr = am.repo_override;
                  const mode = ovr === true ? "on" : (ovr === false ? "off" : "inherit");
                  const eff = Boolean(am.enabled);
                  const rBusy = Boolean(state.autoMergeSaving[r.repo_path]);
                  const effBadge = eff
                    ? '<span class="badge tone-success">' + tr("生效: 开", "Active: ON") + (am.source === "repo" ? tr(" · 仓库", " · Repo") : tr(" · 全局", " · Global")) + "</span>"
                    : '<span class="badge">' + tr("生效: 关", "Active: OFF") + "</span>";
                  return (
                    '<div class="policy-repo-row">' +
                      '<div style="min-width:0;flex:1;">' +
                        '<div style="display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600;">' +
                          '<span class="host-ic sm ' + (r.forge === "gitlab" ? "is-gitlab" : "is-github") + '">' + forgeIcon(r.forge, 12) + "</span>" +
                          "<span>" + escapeHtml(r.repo_name) + "</span>" +
                          effBadge +
                        "</div>" +
                      "</div>" +
                      '<div class="am-seg-group" role="group" aria-label="' + escapeHtml(r.repo_name) + '">' +
                        '<button class="am-seg-btn ' + (mode === "inherit" ? "active" : "") + '" type="button" data-am-repo-path="' + escapeHtml(r.repo_path) + '" data-am-repo-val="inherit" ' + (rBusy ? "disabled" : "") + ">" + tr("跟随全局", "Inherit") + "</button>" +
                        '<button class="am-seg-btn ' + (mode === "on" ? "active is-on" : "") + '" type="button" data-am-repo-path="' + escapeHtml(r.repo_path) + '" data-am-repo-val="on" ' + (rBusy ? "disabled" : "") + ">" + tr("开", "ON") + "</button>" +
                        '<button class="am-seg-btn ' + (mode === "off" ? "active is-off" : "") + '" type="button" data-am-repo-path="' + escapeHtml(r.repo_path) + '" data-am-repo-val="off" ' + (rBusy ? "disabled" : "") + ">" + tr("关", "OFF") + "</button>" +
                      "</div>" +
                    "</div>"
                  );
                }).join("") +
              "</div>";

          const autoMergeSectionHtml =
            '<div class="policy-section">' +
              '<div class="policy-section-hdr">' +
                '<span style="font-size:12.5px;font-weight:600;color:var(--text);">' + tr("PR 自动准入（auto_merge）", "PR Auto-Approve (auto_merge)") + "</span>" +
                '<label class="am-toggle-switch">' +
                  '<input type="checkbox" data-am-global-toggle="1" ' + (globalAm ? "checked" : "") + " " + (gAmBusy ? "disabled" : "") + " />" +
                  '<span class="am-toggle-track"></span>' +
                  '<span class="am-toggle-label">' + (globalAm ? tr("全局默认: 开", "Global Default: ON") : tr("全局默认: 关", "Global Default: OFF")) + "</span>" +
                "</label>" +
              "</div>" +
              '<div style="font-size:11.5px;color:var(--text-dim);line-height:1.45;">' +
                tr(
                  "默认关闭。开启后，Agent 运行 `idd pr` / `idd mr` 将跳过口头确认直接等待 CI 结算，通过（或无远端 CI 且本地测试通过）后自动清理 `TASK/` 并 Squash 直线合入；遇 CI 2 轮修复失败、Rebase 冲突或 evidence/ 含附件时自动暂停。",
                  "Disabled by default. When enabled, `idd pr` / `idd mr` skips verbal approval, waits for CI settlement, and squash-lands linearly (including repos without remote CI after local tests pass). Pauses safely on CI failure, rebase conflicts, or evidence attachments."
                ) +
              "</div>" +
              autoMergeRepoRows +
            "</div>";

          bodyHtml = hostCards + autoCheckHtml + policyRowsHtml + autoMergeSectionHtml + customForm;
        }

        const hdrTitle = isGuide
          ? tr("四步上手 IDD 工作流", "How IDD Works in 4 Steps")
          : tr("连接代码托管平台", "Connect GitHub / GitLab");
        const hdrSub = isGuide
          ? tr("多 Agent 各自独立目录并行开发，在看板盯进度并一键换手接力。", "Parallel isolated worktrees for every agent, with live progress and 1-click handoff.")
          : tr("生成个人访问令牌并粘贴保存，即可自动同步 Issue、PR/MR 与 CI 状态（免命令行）。", "Create a personal access token with the required scopes below and save directly in the browser.");

        const ftrHtml = !isGuide
          ? '<span style="font-size:11.5px;color:var(--text-faint);">' + tr("本机加密权限保存 (<code>~/.config/idd/hosts.json</code>, 0600)", "Stored locally (<code>~/.config/idd/hosts.json</code>, 0600)") + "</span>" +
            '<div style="display:inline-flex;gap:8px;">' +
              '<button class="btn" type="button" data-setup-close="1">' + tr("稍后再说", "Later") + "</button>" +
              '<button class="btn btn-primary" type="button" data-setup-tab="guide"><span>' + tr("下一步：了解工作流", "Next: 4-Step Guide") + "</span>" + icon("chevronRight", 13) + "</button>" +
            "</div>"
          : '<button class="btn" type="button" data-setup-tab="auth"><span>' + tr("← 返回平台配置", "<- Back to Setup") + "</span></button>" +
            '<button class="btn btn-primary" type="button" id="finish-onboarding-btn">' + icon("check", 13) + "<span>" + tr("开始使用看板", "Finish & Enter Board") + "</span></button>";

        const bodyCls = state.setupTabAnimDir === "next"
          ? "setup-body wizard-pane-next"
          : (state.setupTabAnimDir === "prev" ? "setup-body wizard-pane-prev" : "setup-body");
        state.setupTabAnimDir = "";
        state.revealModalCard = "";

        preserveScroll([{ root: modal, selector: ".setup-body" }], () => {
          modal.innerHTML =
            '<div class="setup-hdr">' +
              '<div class="setup-topbar">' +
                '<div class="wizard-nav">' +
                  '<button class="wizard-nav-btn ' + (!isGuide ? "active" : "") + '" type="button" data-setup-tab="auth"><span class="wizard-num">1</span><span>' + tr("连接代码平台", "Connect Platforms") + "</span></button>" +
                  '<button class="wizard-nav-btn ' + (isGuide ? "active" : "") + '" type="button" data-setup-tab="guide"><span class="wizard-num">2</span><span>' + tr("四步上手流程", "4-Step Workflow") + "</span></button>" +
                "</div>" +
                '<button class="icon-btn" type="button" data-setup-close="1" aria-label="' + tr("关闭", "Close") + '">' + icon("x", 16) + "</button>" +
              "</div>" +
              "<div>" +
                '<h2 class="setup-title">' + hdrTitle + "</h2>" +
                '<p class="setup-sub">' + hdrSub + "</p>" +
              "</div>" +
            "</div>" +
            '<div class="' + bodyCls + '">' + bodyHtml + "</div>" +
            '<div class="setup-ftr">' + ftrHtml + "</div>";
        });
        syncSlidingIndicator(modal.querySelector(".wizard-nav"), ".wizard-nav-btn.active", "wizard-nav");
        modal.querySelectorAll(".am-seg-group").forEach((grp, idx) => {
          const act = grp.querySelector(".am-seg-btn.active");
          const tone = act ? (act.classList.contains("is-on") ? "is-on" : (act.classList.contains("is-off") ? "is-off" : "")) : "";
          const gKey = "am-seg:" + ((act && act.getAttribute("data-am-repo-path")) || idx);
          syncSlidingIndicator(grp, ".am-seg-btn.active", gKey, { toneClass: tone });
        });
        if (state.shakeFieldKey) {
          const fk = state.shakeFieldKey;
          state.shakeFieldKey = "";
          triggerFieldShake(modal, fk);
        }
      }

      function renderTopAlerts(snap) {
        const topWrap = document.getElementById("top-alerts-wrap");
        if (!topWrap || !snap) return;
        const authAlerts = snap.auth_alerts || [];
        const pendingPolicyRepos = (snap.repos || []).filter((r) => {
          if (r.forge !== "github" && r.forge !== "gitlab") return false;
          if (!r.forge_connected) return false;
          const ri = r.repo_init || {};
          return ri.state === "pending" || ri.state === "prompted";
        });
        const sig = JSON.stringify({
          aa: authAlerts,
          pr: pendingPolicyRepos.map((r) => [r.repo_path, r.repo_init]),
          lg: state.lang,
          sv: state.authSavingHost,
          er: state.authErrors,
          ri: state.repoInitRunning,
          rie: state.repoInitErrors,
          ribd: state.repoInitBannerDismissed
        });
        if (sig === state.lastTopAlertsSig) return;
        state.lastTopAlertsSig = sig;

        const showPolicyBanner = pendingPolicyRepos.length > 0 && !state.repoInitBannerDismissed;
        if (!authAlerts.length && !showPolicyBanner) {
          const wrapNode = topWrap.querySelector(".alert-collapse-wrap");
          if (wrapNode && !prefersReducedMotion()) {
            clearTimeout(state.alertCollapseTimer);
            wrapNode.classList.remove("is-entering");
            wrapNode.classList.add("is-collapsing");
            state.alertCollapseTimer = setTimeout(() => {
              state.alertCollapseTimer = null;
              if (!topWrap.querySelector(".alert-collapse-wrap.is-collapsing")) return;
              topWrap.innerHTML = "";
            }, 250);
          } else {
            topWrap.innerHTML = "";
          }
          return;
        }
        clearTimeout(state.alertCollapseTimer);
        state.alertCollapseTimer = null;
        const wasEmpty = !topWrap.querySelector(".auth-alert-box");

        const authHtml = authAlerts.map((a) => {
          const target = a.api_base || a.host || "";
          const fg = a.forge || "gitlab";
          const isGitLab = fg === "gitlab";
          const plat = isGitLab ? tr("GitLab", "GitLab") : "GitHub";
          const scopeName = isGitLab ? "api" : "repo";
          const hostLabel = String(a.host || target).replace(/^https?:\/\//i, "");
          const tokenHref = safeUrl(a.token_url);
          const hostHref = safeUrl(a.api_base);
          const draftVal = state.tokenDrafts[target] || "";
          const errMsg = state.authErrors[target] || "";
          const saving = state.authSavingHost === target;

          const quietRepos = (a.repos || []).map((name) => {
            const matched = (snap.repos || []).find((r) => r.repo_name === name);
            const href = matched ? safeUrl(matched.repo_url) : "";
            return href
              ? '<a class="host-repo-link" href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(name) + icon("externalLink", 10) + "</a>"
              : '<span class="host-repo-link">' + escapeHtml(name) + "</span>";
          }).join('<span style="color:var(--text-faint);">·</span>');

          return (
            '<div class="auth-alert-box">' +
              '<div class="auth-alert-top">' +
                '<div class="auth-alert-main">' +
                  '<span class="host-ic sm ' + (isGitLab ? "is-gitlab" : "is-github") + '">' + forgeIcon(fg, 13) + "</span>" +
                  "<strong>" + tr("待配置 " + plat + " 访问令牌", plat + " Token Required") + "</strong>" +
                  (hostHref ? '<a class="host-url-link" href="' + escapeHtml(hostHref) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(hostLabel) + " ↗</a>" : '<span class="host-url-link">' + escapeHtml(hostLabel) + "</span>") +
                  (quietRepos ? '<span style="color:var(--text-faint);">·</span>' + quietRepos : "") +
                  '<code class="perm-tag">' + tr("需勾选: " + scopeName, "Scope: " + scopeName) + "</code>" +
                "</div>" +
                '<button class="btn btn-xs" type="button" data-open-setup="auth">' + icon("compass", 11) + "<span>" + tr("权限说明与向导", "Permissions & Guide") + "</span></button>" +
              "</div>" +
              '<div class="auth-alert-form">' +
                (tokenHref ? '<a class="btn btn-sm" href="' + escapeHtml(tokenHref) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 12) + "<span>" + tr("1. 去生成令牌 (勾选 " + scopeName + ")", "1. Create Token (" + scopeName + ")") + "</span></a>" : "") +
                '<input class="token-input" type="password" autocomplete="off" data-token-draft="' + escapeHtml(target) + '" value="' + escapeHtml(draftVal) + '" placeholder="' + escapeHtml(tr("2. 粘贴生成的令牌，点右侧直接保存（无需执行命令）", "2. Paste token here and click Save")) + '" />' +
                '<button class="btn btn-sm btn-primary' + (saving ? " spin" : "") + '" style="height:34px;padding:0 14px;" type="button" data-save-host="' + escapeHtml(target) + '" data-save-forge="' + escapeHtml(fg) + '" ' + (saving ? "disabled" : "") + ">" +
                  icon(saving ? "refresh" : "check", 12) +
                  "<span>" + (saving ? tr("验证中...", "Verifying...") : tr("保存并连接", "Save & Connect")) + "</span>" +
                "</button>" +
              "</div>" +
              (errMsg ? '<div class="auth-err-msg">' + escapeHtml(errMsg) + "</div>" : "") +
            "</div>"
          );
        }).join("");

        let policyHtml = "";
        if (showPolicyBanner) {
          const allBusy = Boolean(state.repoInitRunning.__all__);
          const repoPills = pendingPolicyRepos.map((r) => {
            const ri = r.repo_init || {};
            const busy = Boolean(state.repoInitRunning[r.repo_path]);
            const errMsg = state.repoInitErrors[r.repo_path] || ri.error || "";
            const mm = Array.isArray(ri.mismatches) ? ri.mismatches : [];
            const detail = errMsg ? errMsg : (mm.length ? mm.join(" · ") : tr("尚未锁定线性 Squash 策略与提交模板", "Merge policy not initialized"));
            return (
              '<div class="policy-repo-row" style="width:100%;">' +
                '<div style="min-width:0;flex:1;">' +
                  '<div style="display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600;">' +
                    '<span class="host-ic sm ' + (r.forge === "gitlab" ? "is-gitlab" : "is-github") + '">' + forgeIcon(r.forge, 12) + "</span>" +
                    "<span>" + escapeHtml(r.repo_name) + "</span>" +
                  "</div>" +
                  '<div style="font-size:11px;color:' + (errMsg ? "var(--red)" : "var(--text-dim)") + ';margin-top:2px;word-break:break-word;">' + escapeHtml(detail) + "</div>" +
                "</div>" +
                '<button class="btn btn-xs btn-warn' + (busy ? " spin" : "") + '" type="button" data-apply-repo-init="' + escapeHtml(r.repo_path) + '" ' + (busy ? "disabled" : "") + ">" +
                  icon(busy ? "refresh" : "check", 11) +
                  "<span>" + (busy ? tr("初始化中...", "Applying...") : (errMsg ? tr("重试初始化", "Retry") : tr("立即初始化", "Apply Now"))) + "</span>" +
                "</button>" +
              "</div>"
            );
          }).join("");

          policyHtml =
            '<div class="auth-alert-box">' +
              '<div class="auth-alert-top">' +
                '<div class="auth-alert-main">' +
                  icon("alertTriangle", 14) +
                  "<strong>" + tr("待初始化仓库线性 Squash 合入策略 (" + pendingPolicyRepos.length + ")", "Repository Linear Squash Policy Pending (" + pendingPolicyRepos.length + ")") + "</strong>" +
                  '<span style="font-size:11.5px;color:var(--text-dim);">' + tr("暂跳过或失败时仍可在左侧仓库栏与设置向导点击执行", "You can still trigger initialization anytime from the sidebar or Setup") + "</span>" +
                "</div>" +
                '<div style="display:inline-flex;align-items:center;gap:6px;">' +
                  (pendingPolicyRepos.length > 1
                    ? '<button class="btn btn-xs btn-warn' + (allBusy ? " spin" : "") + '" type="button" data-apply-repo-init="__all__" ' + (allBusy ? "disabled" : "") + ">" +
                        icon(allBusy ? "refresh" : "check", 11) +
                        "<span>" + (allBusy ? tr("全部初始化中...", "Applying...") : tr("全部一键初始化", "Apply All")) + "</span>" +
                      "</button>"
                    : "") +
                  '<button class="btn btn-xs" type="button" data-dismiss-repo-init-banner="1">' + tr("稍后", "Later") + "</button>" +
                "</div>" +
              "</div>" +
              '<div class="policy-repo-list">' + repoPills + "</div>" +
            "</div>";
        }

        topWrap.innerHTML =
          '<div class="alert-collapse-wrap' + (wasEmpty && !prefersReducedMotion() ? " is-entering" : "") + '">' +
            '<div class="alert-collapse-inner">' + authHtml + policyHtml + "</div>" +
          "</div>";
        if (!state.setupOpen && state.shakeFieldKey) {
          const fk = state.shakeFieldKey;
          state.shakeFieldKey = "";
          triggerFieldShake(topWrap, fk);
        }
      }

      function computeRenderSignature(snap) {
        if (!snap) return "";
        return JSON.stringify({
          g: snap.global,
          rc: snap.repos_config_path,
          s: snap.summary,
          r: snap.repos,
          i: snap.issues,
          l: snap.local_only_items,
          o: snap.orphan_changes,
          aa: snap.auth_alerts,
          fs: snap.forge_syncing,
          lo: snap.local_only,
          fconn: snap.forge_connections,
          ac: state.authStatus ? state.authStatus.unconfigured_count : -1,
          fc: state.fromCache,
          hl: state.hasLiveSnapshot,
          w: snap.warnings,
          sr: state.selectedRepo,
          vm: state.viewMode,
          sc: state.sidebarCollapsed,
          lg: state.lang,
          sq: state.search,
          wo: state.worktreeOnly,
          ao: state.alertsOnly,
          to: state.todoOnly,
          sk: state.selectedKey,
          ct: state.consoleTab,
          ik: state.inspectedKey,
          it: state.inspectorTab,
          ri: state.repoInitRunning,
          rie: state.repoInitErrors,
          ribd: state.repoInitBannerDismissed,
          cfg: snap.config,
          ams: state.autoMergeSaving
        });
      }

      function renderAll(force) {
        const snap = state.snapshot;
        if (!snap) {
          syncHeaderControls();
          updateConnectionBadge(!state.initError, state.initError);
          renderLoadingState();
          return;
        }

        state.lastClockStr = formatClock(snap.generated_at);
        const updatedTag = document.getElementById("updated-tag");
        if (updatedTag) updatedTag.textContent = state.lastClockStr;

        const sig = computeRenderSignature(snap);
        if (!force && sig === state.lastSig) {
          return;
        }
        state.lastSig = sig;

        syncHeaderControls();
        renderWorkspaceHeader(snap);
        renderTopAlerts(snap);
        renderSidebarFilters(snap);
        renderKpis(snap);
        renderMain();
        renderSidebarReposAndWorktrees(snap);
        renderInspector();

        const authAlerts = snap.auth_alerts || [];
        const warns = (snap.warnings || []).filter((w) => !authAlerts.length || !String(w).includes("需要鉴权"));
        const warnsHtml = warns.length
          ? '<div class="warnings-box">' + icon("alertTriangle", 14) + "<div><strong>" + tr("提示：", "Notice: ") + "</strong>" + warns.map((w) => escapeHtml(w)).join(" ｜ ") + "</div></div>"
          : "";
        document.getElementById("warnings-wrap").innerHTML = warnsHtml;

        const retainedCount = (snap.repos || []).reduce((acc, r) => acc + (r.retained_idle_worktrees || []).length, 0);
        const retainedText = retainedCount > 0
          ? tr("已合入保留目录：" + retainedCount + " 个", retainedCount + " retained merged worktree(s)")
          : tr("保留目录均已清理", "No retained merged worktrees");
        document.getElementById("footer").innerHTML =
          "<span>" + tr("仓库索引：", "Repo index: ") + "<code>" + escapeHtml(snap.repos_config_path || "~/.config/idd/repos.json") + "</code></span>" +
          "<span>" + escapeHtml(retainedText) + " · " + tr("快捷键 <code>[</code> 收起侧栏 · <code>/</code> 搜索 · <code>r</code> 同步远端", "Shortcuts: <code>[</code> sidebar · <code>/</code> search · <code>r</code> sync") + "</span>";
      }

      async function fetchSnapshot(forceRefresh) {
        if (state.fetching && !forceRefresh) return;
        state.fetching = true;
        if (forceRefresh) state.manualRefreshing = true;
        if (!state.snapshot && !state.slowInitTimerId) {
          state.slowInitTimerId = setTimeout(() => {
            state.slowInitTimerId = null;
            if (!state.snapshot && !state.initError) {
              state.slowInit = true;
              renderAll(true);
            }
          }, 3500);
        }
        syncHeaderControls();
        try {
          const url = forceRefresh ? "/api/snapshot?refresh=1" : "/api/snapshot";
          const res = await fetch(url, { cache: "no-store" });
          if (!res.ok) throw new Error("HTTP " + res.status);
          const nextSnap = await res.json();
          clearTimeout(state.slowInitTimerId);
          state.slowInitTimerId = null;
          state.snapshot = nextSnap;
          state.hasLiveSnapshot = true;
          state.fromCache = false;
          state.initError = "";
          state.slowInit = false;
          saveCachedSnapshot(nextSnap);
          if (!state.didAutoInspect) {
            state.didAutoInspect = true;
            const qInspect = urlParams.get("inspect");
            if (qInspect) {
              const found = collectItems(true).find((it) => String(it.issue_number) === qInspect || it._key === qInspect);
              if (found) {
                state.selectedKey = found._key;
                if (state.viewMode !== "cockpit") {
                  state.inspectedKey = found._key;
                }
              }
            }
          }
          state.lastClockStr = formatClock(state.snapshot.generated_at);
          updateConnectionBadge(true);
          renderAll(false);
          if (!state.didCheckOnboarding) {
            const qOnb = urlParams.get("onboarding");
            const forceOnb = qOnb === "1" || qOnb === "guide";
            if (forceOnb || !state.snapshot.forge_syncing) {
              state.didCheckOnboarding = true;
              const hasAlerts = ((state.snapshot && state.snapshot.auth_alerts) || []).length > 0;
              if (forceOnb) {
                openSetupModal(qOnb === "guide" ? "guide" : "auth");
              } else if (!urlParams.has("inspect") && qOnb !== "0") {
                if (hasAlerts && !sessionStorage.getItem("idd_setup_dismissed")) {
                  openSetupModal("auth");
                } else if (!localStorage.getItem("idd_onboarding_done")) {
                  openSetupModal(hasAlerts ? "auth" : "guide");
                }
              }
            }
          }
          clearTimeout(state.quickSyncTimerId);
          if (state.snapshot && state.snapshot.forge_syncing && !state.paused) {
            state.quickSyncTimerId = setTimeout(() => fetchSnapshot(false), 800);
          }
          if (forceRefresh) {
            showToast(tr("已触发远端同步，正在更新...", "Triggered remote sync..."));
          }
        } catch (err) {
          if (!state.snapshot) {
            clearTimeout(state.slowInitTimerId);
            state.slowInitTimerId = null;
            state.initError = err && err.message ? err.message : tr("连接异常", "Network error");
            updateConnectionBadge(false, tr("初始化失败", "Init failed"));
            renderAll(true);
          } else {
            updateConnectionBadge(false, tr("连接异常: ", "Sync error: ") + err.message);
          }
        } finally {
          state.fetching = false;
          if (forceRefresh) state.manualRefreshing = false;
          syncHeaderControls();
        }
      }

      function handleActionClick(e) {
        const copyBtn = e.target.closest("[data-copy-val]");
        if (copyBtn) {
          e.stopPropagation();
          copyText(copyBtn.getAttribute("data-copy-val") || "", copyBtn, copyBtn.getAttribute("data-copy-msg") || "");
          return true;
        }
        if (e.target.closest("[data-stop-open]")) {
          return true;
        }
        const kpiBtn = e.target.closest("[data-kpi-action]");
        if (kpiBtn) {
          const act = kpiBtn.getAttribute("data-kpi-action");
          if (act === "toggle-wt") {
            state.worktreeOnly = !state.worktreeOnly;
            if (state.worktreeOnly) state.todoOnly = false;
          } else if (act === "toggle-alerts") {
            state.alertsOnly = !state.alertsOnly;
            if (state.alertsOnly) state.todoOnly = false;
          } else if (act === "toggle-todo") {
            state.todoOnly = !state.todoOnly;
            if (state.todoOnly) {
              state.worktreeOnly = false;
              state.alertsOnly = false;
            }
          } else if (act === "clear-filters") {
            state.selectedRepo = "ALL";
            state.worktreeOnly = false;
            state.alertsOnly = false;
            state.todoOnly = false;
            state.search = "";
            document.getElementById("search-input").value = "";
            document.getElementById("search-wrap").classList.remove("has-value");
          }
          renderAll(true);
          return true;
        }
        return false;
      }

      document.getElementById("sb-filters").addEventListener("click", handleActionClick);
      document.getElementById("kpis").addEventListener("click", handleActionClick);
      document.getElementById("warnings-wrap").addEventListener("click", handleActionClick);

      document.getElementById("setup-btn").addEventListener("click", () => {
        const hasAlerts = ((state.snapshot && state.snapshot.auth_alerts) || []).length > 0;
        openSetupModal(hasAlerts ? "auth" : (state.setupTab || "auth"));
      });

      document.getElementById("top-alerts-wrap").addEventListener("input", (e) => {
        const inp = e.target.closest("[data-token-draft]");
        if (inp) {
          state.tokenDrafts[inp.getAttribute("data-token-draft")] = inp.value || "";
        }
      });

      document.getElementById("top-alerts-wrap").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const inp = e.target.closest("[data-token-draft]");
          if (inp) {
            const target = inp.getAttribute("data-token-draft");
            const btn = document.querySelector('#top-alerts-wrap [data-save-host="' + CSS.escape(target) + '"]');
            if (btn) btn.click();
          }
        }
      });

      document.getElementById("top-alerts-wrap").addEventListener("click", (e) => {
        const dismissBanner = e.target.closest("[data-dismiss-repo-init-banner]");
        if (dismissBanner) {
          state.repoInitBannerDismissed = true;
          state.lastTopAlertsSig = "";
          renderTopAlerts(state.snapshot);
          return;
        }
        const applyBtn = e.target.closest("[data-apply-repo-init]");
        if (applyBtn) {
          applyRepoInit(applyBtn.getAttribute("data-apply-repo-init") || "");
          return;
        }
        const openBtn = e.target.closest("[data-open-setup]");
        if (openBtn) {
          openSetupModal(openBtn.getAttribute("data-open-setup") || "auth");
          return;
        }
        const saveBtn = e.target.closest("[data-save-host]");
        if (saveBtn) {
          const host = saveBtn.getAttribute("data-save-host") || "";
          const fg = saveBtn.getAttribute("data-save-forge") || "gitlab";
          submitHostToken(host, fg, state.tokenDrafts[host] || "", false);
          return;
        }
        handleActionClick(e);
      });

      document.getElementById("setup-modal").addEventListener("change", (e) => {
        if (e.target && e.target.matches("[data-auto-repo-init-toggle]")) {
          state.autoRepoInit = Boolean(e.target.checked);
          return;
        }
        if (e.target && e.target.matches("[data-am-global-toggle]")) {
          const nextChecked = Boolean(e.target.checked);
          e.target.checked = !nextChecked;
          openAutoMergeConfirm("global", "", nextChecked);
        }
      });

      document.getElementById("setup-modal").addEventListener("input", (e) => {
        const inp = e.target.closest("[data-token-draft]");
        if (inp) {
          state.tokenDrafts[inp.getAttribute("data-token-draft")] = inp.value || "";
          return;
        }
        if (e.target.id === "custom-host-url") state.customHostUrl = e.target.value || "";
        if (e.target.id === "custom-host-token") state.customHostToken = e.target.value || "";
      });

      document.getElementById("setup-modal").addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const inp = e.target.closest("[data-token-draft]");
          if (inp) {
            const target = inp.getAttribute("data-token-draft");
            const btn = document.querySelector('#setup-modal [data-save-host="' + CSS.escape(target) + '"]');
            if (btn) btn.click();
          } else if (e.target.id === "custom-host-token" || e.target.id === "custom-host-url") {
            const cbtn = document.getElementById("custom-host-save-btn");
            if (cbtn) cbtn.click();
          }
        }
      });

      document.getElementById("setup-modal").addEventListener("click", async (e) => {
        if (e.target.closest("[data-setup-close]")) {
          closeSetupModal(true);
          return;
        }
        const applyPolicyBtn = e.target.closest("[data-apply-repo-init]");
        if (applyPolicyBtn) {
          await applyRepoInit(applyPolicyBtn.getAttribute("data-apply-repo-init") || "");
          return;
        }
        const amSegBtn = e.target.closest("[data-am-repo-path][data-am-repo-val]");
        if (amSegBtn) {
          const rp = amSegBtn.getAttribute("data-am-repo-path") || "";
          const rawVal = amSegBtn.getAttribute("data-am-repo-val") || "inherit";
          const nextVal = rawVal === "on" ? true : (rawVal === "off" ? false : null);
          openAutoMergeConfirm("repo", rp, nextVal);
          return;
        }
        const tabBtn = e.target.closest("[data-setup-tab]");
        if (tabBtn) {
          const nextTab = tabBtn.getAttribute("data-setup-tab") || "auth";
          if (nextTab !== state.setupTab) {
            state.setupTabAnimDir = nextTab === "guide" ? "next" : "prev";
          }
          state.setupTab = nextTab;
          renderSetupModal();
          return;
        }
        if (e.target.closest("#finish-onboarding-btn")) {
          localStorage.setItem("idd_onboarding_done", "1");
          closeSetupModal(true);
          return;
        }
        const saveBtn = e.target.closest("[data-save-host]");
        if (saveBtn) {
          const host = saveBtn.getAttribute("data-save-host") || "";
          const fg = saveBtn.getAttribute("data-save-forge") || "gitlab";
          await submitHostToken(host, fg, state.tokenDrafts[host] || "", false);
          return;
        }
        const editBtn = e.target.closest("[data-toggle-edit-host]");
        if (editBtn) {
          const h = editBtn.getAttribute("data-toggle-edit-host") || "";
          state.editingHosts[h] = !state.editingHosts[h];
          renderSetupModal();
          return;
        }
        const rmBtn = e.target.closest("[data-remove-host]");
        if (rmBtn) {
          await removeHostToken(rmBtn.getAttribute("data-remove-host") || "");
          return;
        }
        const customToggle = e.target.closest("[data-toggle-custom-host]");
        if (customToggle) {
          state.showCustomHostForm = customToggle.getAttribute("data-toggle-custom-host") === "1";
          if (state.showCustomHostForm) state.revealModalCard = "__custom__";
          renderSetupModal();
          return;
        }
        const cfBtn = e.target.closest("[data-custom-forge]");
        if (cfBtn) {
          state.customHostForge = cfBtn.getAttribute("data-custom-forge") || "gitlab";
          renderSetupModal();
          return;
        }
        if (e.target.closest("#custom-host-save-btn")) {
          const rawUrl = (state.customHostUrl || "").trim();
          const rawTok = (state.customHostToken || "").trim();
          if (!rawUrl || !rawTok) {
            state.authErrors.__custom__ = tr("请填写主机地址并粘贴访问令牌", "Please enter both host URL and token");
            state.shakeFieldKey = "__custom__";
            renderSetupModal();
            return;
          }
          delete state.authErrors.__custom__;
          state.tokenDrafts[rawUrl] = rawTok;
          const ok = await submitHostToken(rawUrl, state.customHostForge, rawTok, false);
          if (!ok && state.authErrors[rawUrl]) {
            state.authErrors.__custom__ = state.authErrors[rawUrl];
            state.shakeFieldKey = "__custom__";
            renderSetupModal();
          }
        }
      });

      document.getElementById("setup-modal-overlay").addEventListener("click", (e) => {
        if (e.target.id === "setup-modal-overlay") {
          closeSetupModal(true);
        }
      });

      document.getElementById("am-confirm-overlay").addEventListener("click", (e) => {
        if (e.target.id === "am-confirm-overlay") {
          closeAutoMergeConfirm();
        }
      });

      document.getElementById("am-confirm-modal").addEventListener("click", async (e) => {
        if (e.target.closest("[data-am-confirm-cancel]")) {
          closeAutoMergeConfirm();
          return;
        }
        const submitBtn = e.target.closest("[data-am-confirm-submit]");
        if (submitBtn && state.amConfirm) {
          const pending = state.amConfirm;
          submitBtn.disabled = true;
          await setAutoMergeSetting(pending.scope, pending.repoPath, pending.nextValue);
          closeAutoMergeConfirm();
        }
      });

      document.getElementById("ws-repo-link-wrap").addEventListener("click", (e) => {
        const applyBtn = e.target.closest("[data-apply-repo-init]");
        if (applyBtn) {
          applyRepoInit(applyBtn.getAttribute("data-apply-repo-init") || "");
          return;
        }
        const qGlobal = e.target.closest("[data-am-quick-global]");
        if (qGlobal) {
          const nextOn = qGlobal.getAttribute("data-am-next") === "1";
          openAutoMergeConfirm("global", "", nextOn);
          return;
        }
        const qRepo = e.target.closest("[data-am-quick-repo]");
        if (qRepo) {
          const rp = qRepo.getAttribute("data-am-quick-repo") || "";
          const nextOn = qRepo.getAttribute("data-am-next") === "1";
          openAutoMergeConfirm("repo", rp, nextOn);
        }
      });

      document.getElementById("repo-pills").addEventListener("click", (e) => {
        const applyBtn = e.target.closest("[data-apply-repo-init]");
        if (applyBtn) {
          e.stopPropagation();
          applyRepoInit(applyBtn.getAttribute("data-apply-repo-init") || "");
          return;
        }
        if (e.target.closest("[data-stop-repo]")) return;
        const btn = e.target.closest("[data-repo]");
        if (!btn) return;
        state.selectedRepo = btn.getAttribute("data-repo") || "ALL";
        state.selectedKey = null;
        renderAll(true);
      });

      document.getElementById("wt-rail-list").addEventListener("click", (e) => {
        const btn = e.target.closest("[data-jump-key]");
        if (!btn) return;
        const key = btn.getAttribute("data-jump-key");
        if (state.viewMode === "cockpit") {
          selectCockpitItem(key);
          return;
        }
        state.selectedKey = key;
        state.inspectedKey = key;
        renderAll(true);
      });

      document.getElementById("main-content").addEventListener("click", (e) => {
        if (handleActionClick(e)) return;
        const applyBtn = e.target.closest("[data-apply-repo-init]");
        if (applyBtn) {
          applyRepoInit(applyBtn.getAttribute("data-apply-repo-init") || "");
          return;
        }
        if (e.target.closest("[data-retry-init]")) {
          state.initError = "";
          state.slowInit = false;
          renderAll(true);
          fetchSnapshot(true);
          return;
        }
        const ctab = e.target.closest("[data-console-tab]");
        if (ctab) {
          switchConsoleTab(ctab.getAttribute("data-console-tab") || "handoff");
          return;
        }
        const selRow = e.target.closest("[data-select-key]");
        if (selRow) {
          selectCockpitItem(selRow.getAttribute("data-select-key"));
          return;
        }
        const openEl = e.target.closest("[data-open-key]");
        if (openEl) {
          state.inspectedKey = openEl.getAttribute("data-open-key");
          renderAll(true);
        }
      });

      document.getElementById("inspector-panel").addEventListener("click", (e) => {
        if (handleActionClick(e)) return;
        if (e.target.closest("#inspector-close-btn")) {
          closeInspectorInPlace();
          return;
        }
        const tabBtn = e.target.closest("[data-inspector-tab]");
        if (tabBtn) {
          switchInspectorTab(tabBtn.getAttribute("data-inspector-tab") || "tasks");
        }
      });

      document.getElementById("inspector-overlay").addEventListener("click", () => {
        closeInspectorInPlace();
      });

      (function initInspectorResizer() {
        const panel = document.getElementById("inspector-panel");
        const resizer = document.getElementById("inspector-resizer");
        if (!panel || !resizer) return;
        const WIDTH_KEY = "idd_inspector_width";
        const clampWidth = (w) => Math.max(360, Math.min(Math.min(760, window.innerWidth - 48), Math.round(w)));
        try {
          const savedW = Number(localStorage.getItem(WIDTH_KEY));
          if (savedW >= 360 && savedW <= 760) {
            panel.style.setProperty("--inspector-width", clampWidth(savedW) + "px");
          }
        } catch (_e) { /* ignore */ }
        let dragging = false;
        resizer.addEventListener("pointerdown", (e) => {
          if (window.innerWidth <= 600) return;
          e.preventDefault();
          dragging = true;
          panel.classList.add("is-resizing");
          if (resizer.setPointerCapture) {
            try { resizer.setPointerCapture(e.pointerId); } catch (_err) {}
          }
        });
        const stopDrag = (e) => {
          if (!dragging) return;
          dragging = false;
          panel.classList.remove("is-resizing");
          if (e && resizer.releasePointerCapture) {
            try { resizer.releasePointerCapture(e.pointerId); } catch (_err) {}
          }
          const finalW = parseInt(panel.style.getPropertyValue("--inspector-width") || "460", 10);
          if (finalW) {
            try { localStorage.setItem(WIDTH_KEY, String(finalW)); } catch (_err) {}
          }
          syncAllSlidingIndicators();
        };
        resizer.addEventListener("pointermove", (e) => {
          if (!dragging) return;
          const nextW = clampWidth(window.innerWidth - e.clientX - 12);
          panel.style.setProperty("--inspector-width", nextW + "px");
        });
        resizer.addEventListener("pointerup", stopDrag);
        resizer.addEventListener("pointercancel", stopDrag);
        resizer.addEventListener("dblclick", () => {
          panel.style.setProperty("--inspector-width", "460px");
          try { localStorage.setItem(WIDTH_KEY, "460"); } catch (_err) {}
          setTimeout(syncAllSlidingIndicators, 220);
        });
      })();

      document.getElementById("sidebar-toggle").addEventListener("click", () => {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        localStorage.setItem("idd_sidebar_collapsed", state.sidebarCollapsed ? "1" : "0");
        applySidebarState(true);
        syncAllSlidingIndicators();
      });

      document.getElementById("pause-btn").addEventListener("click", () => {
        state.paused = !state.paused;
        syncHeaderControls();
        updateConnectionBadge(true);
        if (!state.paused) fetchSnapshot(false);
      });

      document.getElementById("forge-status-group").addEventListener("click", (e) => {
        const btn = e.target.closest("[data-forge-status]");
        if (!btn) return;
        e.stopPropagation();
        const fg = btn.getAttribute("data-forge-status") || "";
        if (state.statusPopoverOpen && state.statusPopoverForge === fg) {
          state.statusPopoverOpen = false;
          state.statusPopoverForge = "";
        } else {
          state.statusPopoverOpen = true;
          state.statusPopoverForge = fg;
        }
        renderForgeStatus(true);
      });

      document.getElementById("forge-status-popover").addEventListener("click", (e) => {
        e.stopPropagation();
        if (e.target.closest("[data-popover-close]")) {
          state.statusPopoverOpen = false;
          state.statusPopoverForge = "";
          renderForgeStatus(true);
          return;
        }
        if (e.target.closest("[data-popover-sync]")) {
          fetchSnapshot(true);
          fetchAuthStatus();
          renderForgeStatus(true);
          return;
        }
        const setupTarget = e.target.closest("[data-popover-open-setup]");
        if (setupTarget) {
          const fg = setupTarget.getAttribute("data-popover-open-setup") || "";
          state.statusPopoverOpen = false;
          state.statusPopoverForge = "";
          if (fg === "github" || fg === "gitlab") {
            const authHosts = (state.authStatus && Array.isArray(state.authStatus.hosts)) ? state.authStatus.hosts : [];
            if (!authHosts.some((h) => h.forge === fg)) {
              state.showCustomHostForm = true;
              state.customHostForge = fg;
            }
          }
          renderForgeStatus(true);
          openSetupModal("auth");
        }
      });

      document.addEventListener("click", (e) => {
        if (state.statusPopoverOpen && !e.target.closest("#status-cluster")) {
          state.statusPopoverOpen = false;
          state.statusPopoverForge = "";
          renderForgeStatus(true);
        }
      });

      document.getElementById("sync-btn").addEventListener("click", () => {
        fetchSnapshot(true);
      });

      document.getElementById("theme-btn").addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme") || "dark";
        const next = cur === "dark" ? "light" : "dark";
        localStorage.setItem("idd_board_theme", next);
        applyTheme(next, true);
      });

      document.getElementById("lang-btn").addEventListener("click", () => {
        state.lang = isEn() ? "zh" : "en";
        localStorage.setItem("idd_board_lang", state.lang);
        state.lastTopAlertsSig = "";
        state.lastForgeStatusSig = "";
        applyLang();
        applyTheme(document.documentElement.getAttribute("data-theme") || "dark", false);
        syncHeaderControls();
        updateConnectionBadge(true);
        renderForgeStatus(true);
        renderAll(true);
        if (state.setupOpen) renderSetupModal();
      });

      const searchInput = document.getElementById("search-input");
      const searchWrap = document.getElementById("search-wrap");
      searchWrap.addEventListener("click", () => {
        if (state.sidebarCollapsed) {
          state.sidebarCollapsed = false;
          localStorage.setItem("idd_sidebar_collapsed", "0");
          applySidebarState(true);
          syncAllSlidingIndicators();
          setTimeout(() => searchInput.focus(), 40);
        }
      });
      searchInput.addEventListener("input", (e) => {
        state.search = e.target.value || "";
        searchWrap.classList.toggle("has-value", state.search.length > 0);
        renderAll(true);
      });

      document.getElementById("search-clear").addEventListener("click", (e) => {
        e.stopPropagation();
        state.search = "";
        searchInput.value = "";
        searchWrap.classList.remove("has-value");
        searchInput.focus();
        renderAll(true);
      });

      function setViewMode(mode) {
        state.viewMode = mode;
        localStorage.setItem("idd_board_view", mode);
        syncHeaderControls();
        renderAll(true);
      }

      document.getElementById("view-cockpit").addEventListener("click", () => setViewMode("cockpit"));
      document.getElementById("view-kanban").addEventListener("click", () => setViewMode("kanban"));
      document.getElementById("view-repos").addEventListener("click", () => setViewMode("repos"));
      document.getElementById("view-list").addEventListener("click", () => setViewMode("list"));

      document.addEventListener("keydown", (e) => {
        const tag = (e.target && e.target.tagName) || "";
        const inInput = tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable);
        if (e.key === "Escape") {
          if (state.amConfirm) {
            closeAutoMergeConfirm();
          } else if (state.setupOpen) {
            closeSetupModal(true);
          } else if (state.statusPopoverOpen) {
            state.statusPopoverOpen = false;
            state.statusPopoverForge = "";
            renderForgeStatus(true);
          } else if (state.inspectedKey) {
            closeInspectorInPlace();
          } else if (document.activeElement === searchInput) {
            searchInput.blur();
          }
          return;
        }
        if (inInput) return;
        if (e.key === "[" && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          state.sidebarCollapsed = !state.sidebarCollapsed;
          localStorage.setItem("idd_sidebar_collapsed", state.sidebarCollapsed ? "1" : "0");
          applySidebarState(true);
          syncAllSlidingIndicators();
        } else if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          if (state.sidebarCollapsed) {
            state.sidebarCollapsed = false;
            localStorage.setItem("idd_sidebar_collapsed", "0");
            applySidebarState(true);
            syncAllSlidingIndicators();
          }
          searchInput.focus();
          searchInput.select();
        } else if ((e.key === "r" || e.key === "R") && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          fetchSnapshot(true);
        }
      });

      const sbAside = document.querySelector("aside.sidebar");
      if (sbAside) {
        sbAside.addEventListener("transitionend", (e) => {
          if (e.propertyName === "width") syncAllSlidingIndicators();
        });
      }
      window.addEventListener("resize", () => {
        clearTimeout(window.__iddResizeIndicatorTimer);
        window.__iddResizeIndicatorTimer = setTimeout(syncAllSlidingIndicators, 80);
      });

      const savedTheme = localStorage.getItem("idd_board_theme") || "dark";
      applyLang();
      applyTheme(savedTheme, false);
      applySidebarState(false);
      const cachedSnap = loadCachedSnapshot();
      if (cachedSnap) {
        state.snapshot = cachedSnap;
        state.fromCache = true;
        state.lastClockStr = formatClock(cachedSnap.generated_at);
      }
      syncHeaderControls();
      updateConnectionBadge(true);
      renderAll(true);
      fetchSnapshot(false);
      fetchAuthStatus();
      state.timerId = setInterval(() => {
        if (!state.paused) fetchSnapshot(false);
      }, 2000);
    })();
  </script>
</body>
</html>
"""


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


class BoardHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server configured for clean local port reuse and shutdown."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: object, client_address: object) -> None:
        _, exc, _ = sys.exc_info()
        if exc is not None and _is_client_disconnect(exc):
            return
        super().handle_error(request, client_address)


class BoardRequestHandler(BaseHTTPRequestHandler):
    """Serve the IDD Web Dashboard HTML and JSON snapshot endpoints."""

    def __init__(
        self,
        *args: object,
        cache: monitor.ForgeSnapshotCache,
        root: Path | None,
        global_mode: bool,
        local_only: bool,
        version: str,
        **kwargs: object,
    ) -> None:
        self.cache = cache
        self.root = root
        self.global_mode = global_mode
        self.local_only = local_only
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

    def _send_json(self, status: HTTPStatus, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

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

    def _refresh_cached_repos(self, *, timeout: float = 2.0) -> None:
        monitor._GH_CLI_CACHE["checked_at"] = 0.0  # noqa: SLF001
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
            if force_refresh and not self.local_only:
                self.cache.warm_async(self._target_repos(), force_refresh=True)
            try:
                snapshot = monitor.collect_scope_snapshot(
                    root=self.root,
                    global_mode=self.global_mode,
                    open_only=False,
                    local_only=self.local_only,
                    forge_cache=self.cache,
                    force_refresh=False,
                    allow_stale_async=True,
                )
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

            hosts = load_hosts_config()
            hosts[host_key] = {
                "forge": forge_type,
                "api_url": api_base,
                "token": token,
                "username": username,
            }
            save_hosts_config(hosts)
            auto_repo_init = payload.get("auto_repo_init", True)
            if isinstance(auto_repo_init, str):
                auto_repo_init = auto_repo_init.strip().lower() not in ("0", "false", "no")
            else:
                auto_repo_init = bool(auto_repo_init)
            repo_init_results: list[dict[str, object]] = []
            for repo_path in self._target_repos():
                resolved_repo = repo_path.expanduser().resolve()
                has_origin, _ = monitor._detect_repo_meta_ro(resolved_repo)  # noqa: SLF001
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
                    has_origin, _ = monitor._detect_repo_meta_ro(rp)  # noqa: SLF001
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
            hosts = load_hosts_config()
            removed = False
            if raw_host:
                candidates = {raw_host}
                try:
                    hk, _ = normalize_host_input(raw_host)
                    candidates.add(hk)
                except ForgeError:
                    pass
                for k in list(hosts.keys()):
                    if k in candidates:
                        hosts.pop(k, None)
                        removed = True
                if removed:
                    save_hosts_config(hosts)
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
            if not scope and payload.get("global") is True:
                scope = "global"
            if scope == "global":
                raw_enabled = payload.get("enabled")
                if not isinstance(raw_enabled, bool):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "enabled 必须为布尔值"})
                    return
                cfg = monitor.set_global_auto_merge(raw_enabled)
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
            if scope == "repo":
                raw_repo_path = str(payload.get("repo_path") or "").strip()
                if not raw_repo_path:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "缺少 repo_path 参数"})
                    return
                try:
                    req_path = Path(raw_repo_path).expanduser().resolve()
                except OSError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "无效的仓库路径"})
                    return
                target_repos = [p.expanduser().resolve() for p in self._target_repos()]
                if req_path not in target_repos:
                    self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "仓库不在当前监控白名单内"})
                    return
                val = payload.get("value")
                if val is not None and not isinstance(val, bool):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "value 必须为 true、false 或 null"})
                    return
                resolved = monitor.set_repo_auto_merge_override(req_path, val)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "scope": "repo",
                        "repo_path": str(req_path),
                        "auto_merge": resolved,
                    },
                )
                return
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "scope 必须为 global 或 repo"})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})


def _bind_server(host: str, port: int | None, handler_cls: type[BaseHTTPRequestHandler]) -> BoardHTTPServer:
    if port is None:
        try:
            return BoardHTTPServer((host, 17890), handler_cls)
        except OSError:
            return BoardHTTPServer((host, 0), handler_cls)
    return BoardHTTPServer((host, port), handler_cls)


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
    if not local_only:
        def _warm_on_boot() -> None:
            if not global_mode and root is not None:
                cache.warm_async([root], force_refresh=False)
            else:
                repos = [Path(r["path"]) for r in monitor.load_registered_repos(prune_missing=True)]
                cache.warm_async(repos, force_refresh=False)
        threading.Thread(target=_warm_on_boot, daemon=True).start()
    handler_cls = partial(
        BoardRequestHandler,
        cache=cache,
        root=root,
        global_mode=global_mode,
        local_only=local_only,
        version=resolved_version,
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
