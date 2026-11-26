#!/usr/bin/env python3
"""Local HTTP server and offline single-page Web Dashboard for `idd board`."""

from __future__ import annotations

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

import monitor  # noqa: E402
from version import get_version  # noqa: E402


BOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IDD 实时开发监控看板</title>
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
      --shadow-panel: 0 20px 50px rgba(0, 0, 0, 0.55);
      --radius-shell: 16px;
      --radius-card: 16px;
      --radius-row: 11px;
      --radius-sm: 8px;
      --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
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
      --shadow-panel: 0 20px 50px rgba(15, 23, 42, 0.14);
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
      transition: width 0.16s ease, padding 0.16s ease;
    }
    body.sidebar-collapsed .sidebar {
      width: 58px;
      padding: 10px 9px;
      align-items: center;
    }
    body.sidebar-collapsed .hide-collapsed {
      display: none !important;
    }
    .show-collapsed { display: none; }
    body.sidebar-collapsed .show-collapsed { display: inline-flex; }

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
      transition: border-color 0.14s, background 0.14s;
    }
    .sb-search:focus-within { border-color: var(--border-strong); }
    .sb-search-ic {
      color: var(--text-dim);
      display: grid;
      place-items: center;
      flex-shrink: 0;
    }
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
    }
    .sb-search-clear {
      border: 0;
      background: transparent;
      color: var(--text-faint);
      cursor: pointer;
      padding: 2px;
      display: none;
      place-items: center;
    }
    .sb-search.has-value .sb-search-clear { display: grid; }
    .sb-search.has-value .sb-kbd,
    .sb-search:focus-within .sb-kbd { display: none; }

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
      transition: background 0.12s, color 0.12s;
      position: relative;
    }
    .sb-item:hover { background: var(--bg-tile); color: var(--text); }
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
      transition: background 0.14s, color 0.14s, border-color 0.14s;
    }
    body.sidebar-collapsed .sb-tile { width: 38px; height: 38px; }
    .sb-tile:hover { background: var(--bg-tile-active); color: var(--text); }
    .sb-tile.active {
      background: var(--bg-tile-active);
      border-color: var(--border-strong);
      color: var(--text);
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

    .ws-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
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
      transition: background 0.12s, color 0.12s, border-color 0.12s;
    }
    .icon-btn:hover { background: var(--bg-tile); color: var(--text); border-color: var(--border); }

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

    .ws-controls {
      display: flex;
      align-items: center;
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
      transition: background 0.12s, color 0.12s, border-color 0.12s;
    }
    .btn:hover { background: var(--bg-card-hover); color: var(--text); border-color: var(--border-strong); }
    .btn-sm { height: 26px; padding: 0 9px; font-size: 11.5px; border-radius: 7px; }
    .btn-xs { height: 24px; padding: 0 8px; font-size: 11px; border-radius: 6px; }
    .btn-icon-only { width: 26px; height: 26px; padding: 0; justify-content: center; }
    .btn-primary {
      background: var(--accent-soft);
      border-color: var(--accent-ring);
      color: var(--accent);
      font-weight: 580;
    }
    .btn-primary:hover { background: rgba(96, 165, 250, 0.20); color: var(--accent); }
    .btn.copied {
      background: var(--green-soft) !important;
      border-color: rgba(74, 222, 128, 0.35) !important;
      color: var(--green) !important;
    }
    .btn.spin svg { animation: spin 0.8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }

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
    .live-pill.is-live .dot-pulse { background: var(--green); animation: pulse 2s infinite; }
    .live-pill.is-err { color: var(--red); border-color: rgba(248, 113, 113, 0.32); }
    .dot-pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint); }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.45; }
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
      transition: border-color 0.14s, background 0.14s;
    }
    button.bento-metric { cursor: pointer; }
    button.bento-metric:hover { background: var(--bg-card-hover); border-color: var(--border-strong); }
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
      transition: background 0.12s;
      border: 1px solid transparent;
    }
    .wt-row:hover { background: var(--bg-tile); }
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
    }
    .console-tab.active {
      background: var(--bg-tile-active);
      color: var(--text);
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
      transition: background 0.12s, color 0.12s;
    }
    .copy-chip:hover { background: var(--bg-tile-active); color: var(--text); }
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
      transition: border-color 0.14s, background 0.14s;
    }
    .card:hover { border-color: var(--border-strong); background: var(--bg-card-hover); }
    .card.is-selected { border-color: var(--accent-ring); }
    .card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .card-meta { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--text-faint); min-width: 0; }
    .card-title { margin-top: 6px; font-size: 13px; font-weight: 560; color: var(--text); line-height: 1.42; }
    .card-context { margin-top: 8px; display: flex; flex-direction: column; gap: 5px; }
    .card-task { display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--text-dim); min-width: 0; }
    .card-task span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .card-prog { display: flex; align-items: center; gap: 8px; }
    .progress-track { flex: 1; height: 4px; border-radius: 999px; background: var(--bar-empty); overflow: hidden; }
    .progress-fill { height: 100%; background: var(--green); border-radius: 999px; }
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
    .list-table { width: 100%; border-collapse: collapse; font-size: 12.5px; min-width: 860px; }
    .list-table th {
      text-align: left;
      padding: 10px 14px;
      font-size: 11px;
      font-weight: 600;
      color: var(--text-faint);
      border-bottom: 1px solid var(--border);
    }
    .list-table td { padding: 10px 14px; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
    .list-table tbody tr { cursor: pointer; }
    .list-table tbody tr:hover { background: var(--bg-tile); }
    .list-table tbody tr.is-selected { background: var(--bg-row-active); }
    .list-table tbody tr:last-child td { border-bottom: 0; }

    /* Slide-Over Inspector Drawer (Used in Secondary Views) */
    .inspector-overlay {
      position: fixed;
      inset: 0;
      z-index: 50;
      background: rgba(0, 0, 0, 0.36);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.16s ease;
    }
    .inspector-overlay.open { opacity: 1; pointer-events: auto; }
    .inspector-panel {
      position: fixed;
      top: 12px;
      right: 12px;
      bottom: 12px;
      width: 460px;
      max-width: calc(100vw - 24px);
      z-index: 60;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-shell);
      box-shadow: var(--shadow-panel);
      display: flex;
      flex-direction: column;
      transform: translateX(106%);
      transition: transform 0.18s cubic-bezier(0.22, 1, 0.36, 1);
    }
    .inspector-panel.open { transform: translateX(0); }
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

    .tabs { display: flex; gap: 4px; margin-top: 14px; border-bottom: 1px solid var(--border-subtle); }
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
    }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
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
    .auth-alert-box {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
      padding: 10px 14px;
      margin-bottom: 8px;
      border-radius: 12px;
      border: 1px solid var(--accent-ring);
      background: var(--accent-soft);
      color: var(--text);
      font-size: 12px;
    }
    .auth-alert-main {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      min-width: 0;
    }
    .auth-alert-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
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

    .toast-wrap { position: fixed; right: 20px; bottom: 20px; z-index: 80; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
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
    }

    @media (max-width: 780px) {
      .app-shell { flex-direction: column; }
      .sidebar { width: 100% !important; }
    }
  </style>
</head>
<body>
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
      <div class="sb-section-hdr hide-collapsed"><span id="sb-hdr-repos">仓库</span><span id="sb-repo-cnt" class="num">0</span></div>
      <div id="repo-pills" class="sb-list"></div>

      <div class="sb-section-hdr hide-collapsed" style="margin-top:4px;"><span id="sb-hdr-wts">并行目录</span><span id="sb-wt-cnt" class="num">0</span></div>
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
          <div id="ws-logo" class="ws-logo" aria-hidden="true"></div>
          <h1 id="ws-title" class="ws-title">全局工作区</h1>
          <span id="scope-tag" class="ws-scope">全局</span>
        </div>
        <div class="ws-controls">
          <span id="conn-tag" class="live-pill is-live">
            <span class="dot-pulse"></span>
            <span>实时</span>
            <span class="sep">·</span>
            <span id="updated-tag" class="num">同步中...</span>
          </span>
          <button id="pause-btn" class="btn" type="button"></button>
          <button id="sync-btn" class="btn btn-primary" type="button" title="快捷键 r"></button>
        </div>
      </header>

      <section id="kpis" class="telemetry-grid"></section>

      <main id="main-content"></main>
      <div id="warnings-wrap"></div>
      <footer id="footer" class="footer"></footer>
    </div>
  </div>

  <div id="inspector-overlay" class="inspector-overlay" aria-hidden="true"></div>
  <aside id="inspector-panel" class="inspector-panel" aria-label="任务详情抽屉" aria-hidden="true"></aside>
  <div id="toast-wrap" class="toast-wrap" aria-live="polite"></div>

  <script>
    (function () {
      const ICONS = {
        github: '<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>',
        gitlab: '<path d="m22 13.29-3.33-10a.42.42 0 0 0-.14-.18.38.38 0 0 0-.22-.11.39.39 0 0 0-.23.07.42.42 0 0 0-.14.18l-2.26 6.67H8.32L6.1 3.26a.42.42 0 0 0-.1-.18.38.38 0 0 0-.26-.08.39.39 0 0 0-.23.07.42.42 0 0 0-.14.18L2 13.29a.74.74 0 0 0 .27.83L12 21l9.69-6.88a.71.71 0 0 0 .31-.83Z"/>',
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
        consoleTab: "handoff",
        inspectorTab: "tasks",
        timerId: null,
        quickSyncTimerId: null,
        fetching: false,
        lastClockStr: initialLang === "en" ? "Syncing..." : "同步中...",
        lastSig: ""
      };

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
        setTimeout(() => {
          el.style.opacity = "0";
          el.style.transition = "opacity 0.16s";
          setTimeout(() => el.remove(), 180);
        }, 1800);
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
            const prevHtml = btnEl.dataset.prevHtml || btnEl.innerHTML;
            btnEl.dataset.prevHtml = prevHtml;
            btnEl.classList.add("copied");
            btnEl.innerHTML = btnEl.classList.contains("btn-icon-only")
              ? icon("check", 12)
              : icon("check", 11) + "<span>" + tr("已复制", "Copied") + "</span>";
            clearTimeout(Number(btnEl.dataset.timerId || 0));
            const tid = setTimeout(() => {
              btnEl.classList.remove("copied");
              btnEl.innerHTML = prevHtml;
            }, 1400);
            btnEl.dataset.timerId = String(tid);
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
        const ip = document.getElementById("inspector-panel");
        if (ip) ip.setAttribute("aria-label", tr("任务详情抽屉", "Task details drawer"));
      }

      function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        const btn = document.getElementById("theme-btn");
        if (btn) {
          const ic = theme === "dark" ? icon("sun", 14) : icon("moon", 14);
          const lbl = theme === "dark" ? tr("浅色模式", "Light") : tr("深色模式", "Dark");
          btn.innerHTML = '<span class="sb-item-left">' + ic + '<span class="hide-collapsed">' + lbl + "</span></span>";
        }
      }

      function applySidebarState() {
        document.body.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
      }

      function syncHeaderControls() {
        const pauseBtn = document.getElementById("pause-btn");
        if (pauseBtn) {
          pauseBtn.innerHTML = state.paused
            ? icon("play", 12) + "<span>" + tr("继续", "Resume") + "</span>"
            : icon("pause", 12) + "<span>" + tr("暂停", "Pause") + "</span>";
        }
        const syncBtn = document.getElementById("sync-btn");
        if (syncBtn) {
          syncBtn.classList.toggle("spin", state.fetching);
          syncBtn.innerHTML = icon("refresh", 12) + "<span>" + (state.fetching ? tr("同步中", "Syncing") : tr("同步远端", "Sync Forge")) + "</span>";
        }

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
          el.innerHTML = icon(m.ic, 14) + '<span class="tile-dot ' + (m.dot ? "show" : "") + '"></span>';
        }
      }

      function updateConnectionBadge(ok, errorMsg) {
        const tag = document.getElementById("conn-tag");
        if (!tag) return;
        const clock = escapeHtml(state.lastClockStr || tr("同步中...", "Syncing..."));
        if (!ok) {
          tag.className = "live-pill is-err";
          tag.innerHTML = icon("alertTriangle", 12) + "<span>" + escapeHtml(errorMsg || tr("连接中断", "Disconnected")) + '</span><span id="updated-tag" style="display:none;">' + clock + "</span>";
          return;
        }
        if (state.paused) {
          tag.className = "live-pill";
          tag.innerHTML = icon("pause", 11) + "<span>" + tr("已暂停", "Paused") + '</span><span>·</span><span id="updated-tag" class="num">' + clock + "</span>";
          return;
        }
        const syncingRemote = Boolean(state.snapshot && state.snapshot.forge_syncing);
        tag.className = "live-pill is-live";
        tag.innerHTML = '<span class="dot-pulse"></span><span>' + (syncingRemote ? tr("同步远端...", "Syncing...") : tr("实时", "Live")) + '</span><span>·</span><span id="updated-tag" class="num">' + clock + "</span>";
      }

      function parseStage(rawStage) {
        const cleaned = String(rawStage || "").replace(/^[\s\u{1F300}-\u{1FAFF}\u2600-\u27BF\uFE0F]+/u, "").trim();
        const canonical = cleaned === "待认领" ? "待处理" : (cleaned || "—");
        const enMap = {
          "待处理": "Queued",
          "开发中": "In Progress",
          "本地开发": "Local",
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
        if (canonical === "待合入" || canonical.startsWith("待提")) return { key: canonical, label, tone: "tone-success", dot: "active" };
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
          list.push(Object.assign({
            _kind: "local",
            _key: loc.repo_path + "#local#" + loc.issue + "#" + (loc.worktree || ""),
            title: loc.issue,
            stage: blockedCnt > 0 ? "受阻" : "本地开发",
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

      function shortDirSlug(wt) {
        const parts = String(wt || "").split("/").filter(Boolean);
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
          repoHtml.push(
            '<button class="sb-item ' + (isAct ? "active" : "") + '" data-repo="' + escapeHtml(r.repo_path) + '" type="button" title="' + escapeHtml(r.repo_name + " (" + wtCnt + "/" + items.length + ")") + '">' +
              '<span class="sb-item-left">' +
                '<span class="sb-repo-badge ' + forgeCls + '">' + forgeIcon(r.forge, 12) + "</span>" +
                '<span class="hide-collapsed">' + escapeHtml(r.repo_name) + "</span>" +
              "</span>" +
              '<span class="sb-meta hide-collapsed">:' + wtCnt + "/" + items.length + "</span>" +
            "</button>"
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
          const slug = shortDirSlug(it.worktree) || it.branch || ("#" + it.issue_number);
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
        if (activeRepo) {
          if (titleEl) titleEl.textContent = activeRepo.repo_name;
          if (logoEl) logoEl.innerHTML = forgeIcon(activeRepo.forge, 16);
          if (scopeEl) scopeEl.textContent = activeRepo.forge ? activeRepo.forge.toUpperCase() : "REPO";
        } else {
          if (titleEl) titleEl.textContent = tr("全局工作区", "Global Workspace");
          if (logoEl) logoEl.innerHTML = icon("branch", 15);
          if (scopeEl) scopeEl.textContent = snap.global ? tr("全局", "Global") : tr("单仓库", "Single Repo");
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

        const issueSub = isEn()
          ? (issueInProg + " active · " + issueQueued + " queued · " + issueReady + " ready")
          : ("推进中 " + issueInProg + " · 待认领 " + issueQueued + " · 待合入 " + issueReady);
        const taskSub = isEn()
          ? ("Done " + doneSteps + "/" + totalSteps + " · Active " + inProgSteps + " · Planned " + plannedSteps + (blockedSteps > 0 ? " · Blocked " + blockedSteps : ""))
          : ("已完成 " + doneSteps + "/" + totalSteps + " · 进行中 " + inProgSteps + " · 待开始 " + plannedSteps + (blockedSteps > 0 ? " · 受阻 " + blockedSteps : ""));
        const prSub = isEn()
          ? ("Open " + openChanges + " · CI failed " + ciFailed + " · " + activeWt + " worktrees")
          : ("Open " + openChanges + " · CI 失败 " + ciFailed + " · 活跃目录 " + activeWt + (dirtyWt > 0 ? " (" + dirtyWt + " 改)" : ""));

        const cards = [
          {
            action: "toggle-wt",
            ic: "circle",
            label: tr("Issue 状态", "Issue Status"),
            val: String(issueTotal),
            unit: "Open",
            bar: renderSegBar(issueTotal, 8, issueTones),
            sub: issueSub,
            subCls: issueInProg > 0 ? "live" : "",
            filtered: state.worktreeOnly,
            warn: false
          },
          {
            action: "",
            ic: "layers",
            label: tr("TASK 拆分进度", "TASK Breakdown"),
            val: String(pct),
            unit: "%",
            bar: renderSegBar(doneSteps > 0 ? Math.max(1, doneSlots) : 0, 8, taskTones),
            sub: taskSub,
            subCls: blockedSteps > 0 ? "warn" : "",
            filtered: false,
            warn: blockedSteps > 0
          },
          {
            action: "toggle-alerts",
            ic: "pr",
            label: tr("PR / MR 与合入", "PR / MR & Land"),
            val: String(issueReady),
            unit: tr("待合入", "ready"),
            bar: renderSegBar(openChanges, 8, prTones),
            sub: prSub,
            subCls: (ciFailed + stalled) > 0 ? "warn" : "",
            filtered: state.alertsOnly,
            warn: (ciFailed + stalled) > 0
          }
        ];

        document.getElementById("kpis").innerHTML = cards.map((c) => {
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
              c.bar +
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
        const issueHref = safeUrl(item.url);
        const idLabel = item.issue_number != null ? ("#" + item.issue_number) : tr("本地", "Local");

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
            '<div class="log-line"><span class="log-k">repo</span><span class="log-v">' + escapeHtml(item.repo_name || "—") + (item.branch ? '  ·  <span style="color:var(--accent)">' + escapeHtml(item.branch) + "</span>" : "") + "</span></div>",
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
                (issueHref ? '<a class="btn btn-sm" href="' + escapeHtml(issueHref) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 12) + "<span>" + tr("打开 Issue", "Open Issue") + "</span></a>" : "") +
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

      function renderOpenIssueBtn(item, extraCls) {
        const href = safeUrl(item.url);
        if (!href) return "";
        return '<a class="btn ' + (extraCls || "btn-xs") + '" href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer" data-stop-open="1">' + icon("externalLink", 11) + "<span>" + tr("打开 Issue", "Open Issue") + "</span></a>";
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
          const issueBtn = renderOpenIssueBtn(item, "btn-xs");

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
                    '<span class="badge tone-muted">' + escapeHtml(item.repo_name || "") + "</span>" +
                    stageBadge +
                    progBadge +
                    chBadge +
                  "</div>" +
                  '<div class="wt-row-sub">' + (subParts.length ? subParts.join("<span>·</span>") : "<span>" + tr("尚未创建工作目录 · 点击右侧接力词即可让 Agent 开工", "Worktree not created yet · Copy Handoff to start") + "</span>") + "</div>" +
                  renderTaskChips(item.tasks) +
                "</div>" +
              "</div>" +
              '<div class="wt-row-actions" data-stop-open="1">' +
                issueBtn +
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
          renderCockpitConsole(selected)
        );
      }

      function cardBucket(item) {
        if (item._kind === "local") return "developing";
        if (item._kind === "orphan") {
          return item.checks_overall === "FAIL" || item.checks_overall === "PENDING" || item.isDraft ? "review" : "ready";
        }
        const key = parseStage(item.stage).key;
        if (key === "待处理" || key === "待认领") return "todo";
        if (key === "待合入") return "ready";
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
          ctxParts.push('<div class="card-prog"><div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div><span class="prog-num">' + done + "/" + total + "</span></div>");
        }
        if (item.change) {
          ctxParts.push(renderChangeInline(item));
        }

        const pulseHtml = renderPulseSummary(item.pulse);
        return (
          '<article class="card ' + (isSelected ? "is-selected" : "") + '" data-open-key="' + escapeHtml(item._key) + '">' +
            '<div class="card-top">' +
              '<div class="card-meta">' + (options.showRepo ? ("<span>" + escapeHtml(item.repo_name || "") + "</span><span>·</span>") : "") + renderIdHtml(item) + "</div>" +
              '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>" +
            "</div>" +
            '<div class="card-title">' + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "</div>" +
            (ctxParts.length ? '<div class="card-context">' + ctxParts.join("") + "</div>" : "") +
            '<div class="card-foot"><span>' + (pulseHtml || " ") + '</span><span style="display:inline-flex;gap:5px;">' + renderOpenIssueBtn(item, "btn-xs") + '<button class="btn btn-xs" data-copy-val="' + escapeHtml(handoffPrompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" data-stop-open="1" type="button">' + icon("copy", 11) + "<span>" + tr("接力词", "Handoff") + "</span></button></span></div>" +
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
            ? '<div style="display:flex;align-items:center;gap:8px;min-width:110px;"><div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div><span class="prog-num">' + done + "/" + total + "</span></div>"
            : '<span style="color:var(--text-faint);">—</span>';
          return (
            '<tr class="' + (isSelected ? "is-selected" : "") + '" data-open-key="' + escapeHtml(item._key) + '">' +
              "<td><div style=\"display:flex;align-items:center;gap:8px;\">" + renderIdHtml(item) + "<span>" + escapeHtml(item.title || item.issue || tr("未命名任务", "Untitled task")) + "</span></div></td>" +
              "<td>" + escapeHtml(item.repo_name || "") + "</td>" +
              '<td><span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span></td>" +
              "<td>" + (locParts.length ? '<div style="display:flex;flex-direction:column;gap:4px;max-width:240px;">' + locParts.join("") + "</div>" : "—") + "</td>" +
              "<td>" + progHtml + "</td>" +
              "<td>" + (renderPulseSummary(item.pulse) || "—") + "</td>" +
              "<td>" + (renderChangeInline(item) || "—") + "</td>" +
              '<td><div style="display:inline-flex;gap:5px;">' + renderOpenIssueBtn(item, "btn-xs") + '<button class="btn btn-xs" data-copy-val="' + escapeHtml(handoffPrompt) + '" data-copy-msg="' + tr("已复制 Agent 接力词，可直接粘贴给任意 Agent", "Copied Agent handoff prompt") + '" data-stop-open="1" type="button">' + icon("copy", 11) + "<span>" + tr("接力词", "Handoff") + "</span></button></div></td>" +
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

      function renderMain() {
        const snap = state.snapshot;
        const container = document.getElementById("main-content");
        if (!snap || !container) return;

        const repos = snap.repos || [];
        if (repos.length === 0) {
          container.innerHTML =
            '<div class="empty-state">' +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">' + tr("暂无已纳管的 Git 仓库", "No monitored Git repositories yet") + "</h3>" +
              '<p style="margin:0;font-size:12.5px;">' + tr("在任意项目目录执行以下任一命令后，仓库会自动同步到这里：", "Run any of these commands inside a project directory to register it here:") + "</p>" +
              '<div class="empty-cmds"><code class="empty-cmd">idd start &lt;issue#&gt;</code><code class="empty-cmd">idd status</code><code class="empty-cmd">idd repos add .</code></div>' +
            "</div>";
          return;
        }

        const items = collectItems(false);
        if (items.length === 0) {
          container.innerHTML =
            '<div class="empty-state">' +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">' + tr("当前筛选条件下没有内容", "No matching items") + "</h3>" +
              '<p style="margin:0 0 12px;font-size:12.5px;">' + tr("可以切换仓库、清空搜索词或重置筛选。", "Try switching repositories, clearing search, or resetting filters.") + "</p>" +
              '<button class="btn" type="button" data-kpi-action="clear-filters">' + icon("refresh", 12) + "<span>" + tr("重置筛选", "Reset Filters") + "</span></button>" +
            "</div>";
          return;
        }

        if (state.viewMode === "cockpit") {
          container.innerHTML = renderCockpitView(items);
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
          const byRepo = new Map();
          for (const item of items) {
            const key = item.repo_path || item.repo_name || "unknown";
            if (!byRepo.has(key)) {
              byRepo.set(key, { name: item.repo_name || key, path: key, forge: item.forge_type || "local", items: [] });
            }
            byRepo.get(key).items.push(item);
          }
          container.innerHTML = Array.from(byRepo.values()).map((grp) =>
            '<section class="repo-section">' +
              '<div class="repo-hdr">' +
                '<div><div style="display:flex;align-items:center;gap:8px;">' + forgeIcon(grp.forge, 14) + "<strong>" + escapeHtml(grp.name) + '</strong><span class="badge">' + escapeHtml(grp.forge.toUpperCase()) + '</span></div><div class="mono" style="font-size:11px;color:var(--text-faint);margin-top:2px;">' + escapeHtml(grp.path) + "</div></div>" +
                '<span class="col-count">' + grp.items.length + tr(" 项", " items") + "</span>" +
              "</div>" +
              '<div class="repo-grid">' + grp.items.map((it) => renderCard(it, { showRepo: false })).join("") + "</div>" +
            "</section>"
          ).join("");
        } else {
          container.innerHTML = renderListTable(items);
        }
      }

      function renderInspector() {
        const overlay = document.getElementById("inspector-overlay");
        const panel = document.getElementById("inspector-panel");
        if (!overlay || !panel) return;

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
          return;
        }

        const stInfo = parseStage(item.stage);
        const pulse = item.pulse || null;
        const tasks = item.tasks || [];
        const changedFiles = (pulse && pulse.changed_files) || [];
        const { total, done, pct } = getProgressNumbers(item);
        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const startCmd = targetArg && item.repo_path ? ("cd " + item.repo_path + " && idd start " + targetArg) : "";
        const handoffPrompt = buildHandoffPrompt(item);
        const issueHref = safeUrl(item.url);

        let tabBody = "";
        if (state.inspectorTab === "files") {
          tabBody = changedFiles.length === 0
            ? '<div class="col-empty">' + tr("当前工作区干净，暂无未提交改动", "Clean working tree; no uncommitted changes") + "</div>"
            : '<div class="file-list">' + changedFiles.map((f) => {
                const code = String(f.code || "M").trim();
                const cls = code === "??" ? "untracked" : (code.includes("D") ? "deleted" : "");
                return '<div class="file-row"><span class="file-code ' + cls + '">' + escapeHtml(code) + "</span><span>" + escapeHtml(f.path) + "</span></div>";
              }).join("") + "</div>";
        } else {
          tabBody = tasks.length === 0
            ? '<div class="col-empty">' + (item.worktree ? tr("已建工作目录，尚未拆解任务步骤", "Worktree ready; TASK/ steps pending") : tr("暂无本地任务步骤", "No local TASK steps yet")) + "</div>"
            : '<div style="margin-bottom:10px;"><div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--text-faint);margin-bottom:5px;" class="num"><span>' + tr("总体进度", "Progress") + "</span><span>" + done + " / " + total + " (" + pct + '%)</span></div><div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div></div>' +
              tasks.map((t) => '<div class="task-row"><div class="task-row-top"><span>' + escapeHtml(t.title || t.id) + '</span><span class="badge">' + escapeHtml(t.status || "planned") + "</span></div></div>").join("");
        }

        panel.innerHTML =
          '<div class="inspector-hdr">' +
            '<div style="min-width:0;flex:1;">' +
              '<div class="card-meta">' + forgeIcon(item.forge_type, 12) + "<span>" + escapeHtml(item.repo_name || "") + "</span><span>·</span>" + renderIdHtml(item) + '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>" + (issueHref ? '<a class="btn btn-xs" href="' + escapeHtml(issueHref) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 11) + "<span>" + tr("打开 Issue", "Open Issue") + "</span></a>" : "") + "</div>" +
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

        overlay.classList.add("open");
        panel.classList.add("open");
        overlay.setAttribute("aria-hidden", "false");
        panel.setAttribute("aria-hidden", "false");
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
          it: state.inspectorTab
        });
      }

      function renderAll(force) {
        const snap = state.snapshot;
        if (!snap) return;

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
        renderSidebarFilters(snap);
        renderKpis(snap);
        renderMain();
        renderSidebarReposAndWorktrees(snap);
        renderInspector();

        const authAlerts = snap.auth_alerts || [];
        const authHtml = authAlerts.map((a) => {
          const target = a.api_base || a.host || "";
          const repoNames = (a.repos || []).join(", ");
          const tokenHref = safeUrl(a.token_url);
          const cmd = a.login_cmd || ("idd auth login " + target + " --token <PAT>");
          return (
            '<div class="auth-alert-box">' +
              '<div class="auth-alert-main">' +
                '<span style="color:var(--accent)">' + icon("alertTriangle", 14) + "</span>" +
                "<span><strong>" + tr("需配置 GitLab 登录凭据", "GitLab Token Required") + "</strong> (" + escapeHtml(target) + (repoNames ? " · " + escapeHtml(repoNames) : "") + ")</span>" +
              "</div>" +
              '<div class="auth-alert-actions">' +
                '<button class="btn btn-xs btn-primary" data-copy-val="' + escapeHtml(cmd) + '" data-copy-msg="' + tr("已复制登录命令，请替换 <PAT> 后在终端执行", "Copied login command") + '" type="button">' + icon("copy", 11) + "<span>" + tr("复制登录命令", "Copy Login Cmd") + "</span></button>" +
                (tokenHref ? '<a class="btn btn-xs" href="' + escapeHtml(tokenHref) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 11) + "<span>" + tr("生成 Token", "Create Token") + "</span></a>" : "") +
              "</div>" +
            "</div>"
          );
        }).join("");

        const warns = (snap.warnings || []).filter((w) => !authAlerts.length || !String(w).includes("需要鉴权"));
        const warnsHtml = warns.length
          ? '<div class="warnings-box">' + icon("alertTriangle", 14) + "<div><strong>" + tr("提示：", "Notice: ") + "</strong>" + warns.map((w) => escapeHtml(w)).join(" ｜ ") + "</div></div>"
          : "";
        document.getElementById("warnings-wrap").innerHTML = authHtml + warnsHtml;

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
        syncHeaderControls();
        try {
          const url = forceRefresh ? "/api/snapshot?refresh=1" : "/api/snapshot";
          const res = await fetch(url, { cache: "no-store" });
          if (!res.ok) throw new Error("HTTP " + res.status);
          state.snapshot = await res.json();
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
          clearTimeout(state.quickSyncTimerId);
          if (state.snapshot && state.snapshot.forge_syncing && !state.paused) {
            state.quickSyncTimerId = setTimeout(() => fetchSnapshot(false), 800);
          }
          if (forceRefresh) {
            showToast(tr("已触发远端同步，正在更新...", "Triggered remote sync..."));
          }
        } catch (err) {
          updateConnectionBadge(false, tr("连接异常: ", "Sync error: ") + err.message);
        } finally {
          state.fetching = false;
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

      document.getElementById("repo-pills").addEventListener("click", (e) => {
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
        state.selectedKey = key;
        if (state.viewMode !== "cockpit") {
          state.inspectedKey = key;
        }
        renderAll(true);
      });

      document.getElementById("main-content").addEventListener("click", (e) => {
        if (handleActionClick(e)) return;
        const ctab = e.target.closest("[data-console-tab]");
        if (ctab) {
          state.consoleTab = ctab.getAttribute("data-console-tab") || "handoff";
          renderAll(true);
          return;
        }
        const selRow = e.target.closest("[data-select-key]");
        if (selRow) {
          state.selectedKey = selRow.getAttribute("data-select-key");
          renderAll(true);
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
          state.inspectedKey = null;
          renderAll(true);
          return;
        }
        const tabBtn = e.target.closest("[data-inspector-tab]");
        if (tabBtn) {
          state.inspectorTab = tabBtn.getAttribute("data-inspector-tab") || "tasks";
          renderAll(true);
        }
      });

      document.getElementById("inspector-overlay").addEventListener("click", () => {
        state.inspectedKey = null;
        renderAll(true);
      });

      document.getElementById("sidebar-toggle").addEventListener("click", () => {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        localStorage.setItem("idd_sidebar_collapsed", state.sidebarCollapsed ? "1" : "0");
        applySidebarState();
        renderAll(true);
      });

      document.getElementById("pause-btn").addEventListener("click", () => {
        state.paused = !state.paused;
        syncHeaderControls();
        updateConnectionBadge(true);
        if (!state.paused) fetchSnapshot(false);
      });

      document.getElementById("sync-btn").addEventListener("click", () => {
        fetchSnapshot(true);
      });

      document.getElementById("theme-btn").addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme") || "dark";
        const next = cur === "dark" ? "light" : "dark";
        localStorage.setItem("idd_board_theme", next);
        applyTheme(next);
      });

      document.getElementById("lang-btn").addEventListener("click", () => {
        state.lang = isEn() ? "zh" : "en";
        localStorage.setItem("idd_board_lang", state.lang);
        applyLang();
        applyTheme(document.documentElement.getAttribute("data-theme") || "dark");
        syncHeaderControls();
        updateConnectionBadge(true);
        renderAll(true);
      });

      const searchInput = document.getElementById("search-input");
      const searchWrap = document.getElementById("search-wrap");
      searchWrap.addEventListener("click", () => {
        if (state.sidebarCollapsed) {
          state.sidebarCollapsed = false;
          localStorage.setItem("idd_sidebar_collapsed", "0");
          applySidebarState();
          renderAll(true);
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
          if (state.inspectedKey) {
            state.inspectedKey = null;
            renderAll(true);
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
          applySidebarState();
          renderAll(true);
        } else if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          if (state.sidebarCollapsed) {
            state.sidebarCollapsed = false;
            localStorage.setItem("idd_sidebar_collapsed", "0");
            applySidebarState();
            renderAll(true);
          }
          searchInput.focus();
          searchInput.select();
        } else if ((e.key === "r" || e.key === "R") && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          fetchSnapshot(true);
        }
      });

      const savedTheme = localStorage.getItem("idd_board_theme") || "dark";
      applyLang();
      applyTheme(savedTheme);
      applySidebarState();
      syncHeaderControls();
      fetchSnapshot(false);
      state.timerId = setInterval(() => {
        if (!state.paused) fetchSnapshot(false);
      }, 2000);
    })();
  </script>
</body>
</html>
"""


class BoardHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server configured for clean local port reuse and shutdown."""

    daemon_threads = True
    allow_reuse_address = True


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
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: HTTPStatus, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            rendered = BOARD_HTML.replace("__IDD_VERSION__", html.escape(self.version))
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", rendered.encode("utf-8"))
            return

        if parsed.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "version": self.version})
            return

        if parsed.path == "/api/snapshot":
            params = urllib.parse.parse_qs(parsed.query)
            force_refresh = params.get("refresh", ["0"])[0] in ("1", "true", "yes")
            if force_refresh and not self.local_only:
                if not self.global_mode and self.root is not None:
                    self.cache.warm_async([self.root], force_refresh=True)
                else:
                    repos = [Path(r["path"]) for r in monitor.load_registered_repos(prune_missing=True)]
                    self.cache.warm_async(repos, force_refresh=True)
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
                self._send_json(HTTPStatus.OK, snapshot)
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


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
