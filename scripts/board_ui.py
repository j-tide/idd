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
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IDD 实时开发监控看板</title>
  <style>
    :root {
      --bg: #0b0b0e;
      --bg-elev: rgba(11, 11, 14, 0.84);
      --bg-surface: #111115;
      --bg-col: rgba(255, 255, 255, 0.025);
      --bg-card: #131317;
      --bg-card-hover: #19191f;
      --bg-pill-active: rgba(255, 255, 255, 0.085);
      --bg-inset: rgba(255, 255, 255, 0.035);
      --border: rgba(255, 255, 255, 0.07);
      --border-faint: rgba(255, 255, 255, 0.048);
      --border-strong: rgba(255, 255, 255, 0.14);
      --text: #f4f4f5;
      --text-dim: #a1a1aa;
      --text-faint: #71717a;
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.12);
      --accent-ring: rgba(56, 189, 248, 0.32);
      --green: #34d399;
      --green-soft: rgba(52, 211, 153, 0.12);
      --green-ring: rgba(52, 211, 153, 0.32);
      --yellow: #fbbf24;
      --yellow-soft: rgba(251, 191, 36, 0.12);
      --yellow-ring: rgba(251, 191, 36, 0.32);
      --orange: #fb923c;
      --orange-soft: rgba(251, 146, 60, 0.13);
      --orange-ring: rgba(251, 146, 60, 0.34);
      --red: #fb7185;
      --red-soft: rgba(251, 113, 133, 0.13);
      --red-ring: rgba(251, 113, 133, 0.34);
      --purple: #c084fc;
      --purple-soft: rgba(192, 132, 252, 0.12);
      --purple-ring: rgba(192, 132, 252, 0.32);
      --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.35);
      --shadow-float: 0 20px 50px rgba(0, 0, 0, 0.58);
      --radius: 11px;
      --radius-sm: 7px;
      --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }

    html[data-theme="light"] {
      --bg: #f6f7f9;
      --bg-elev: rgba(246, 247, 249, 0.86);
      --bg-surface: #ffffff;
      --bg-col: #eef0f4;
      --bg-card: #ffffff;
      --bg-card-hover: #fbfcfd;
      --bg-pill-active: #ffffff;
      --bg-inset: #f3f5f8;
      --border: rgba(15, 23, 42, 0.075);
      --border-faint: rgba(15, 23, 42, 0.055);
      --border-strong: rgba(15, 23, 42, 0.16);
      --text: #18181b;
      --text-dim: #52525b;
      --text-faint: #71717a;
      --accent: #0284c7;
      --accent-soft: rgba(2, 132, 199, 0.09);
      --accent-ring: rgba(2, 132, 199, 0.28);
      --green: #059669;
      --green-soft: rgba(5, 150, 105, 0.09);
      --green-ring: rgba(5, 150, 105, 0.26);
      --yellow: #d97706;
      --yellow-soft: rgba(217, 119, 6, 0.09);
      --yellow-ring: rgba(217, 119, 6, 0.26);
      --orange: #ea580c;
      --orange-soft: rgba(234, 88, 12, 0.09);
      --orange-ring: rgba(234, 88, 12, 0.28);
      --red: #e11d48;
      --red-soft: rgba(225, 29, 72, 0.09);
      --red-ring: rgba(225, 29, 72, 0.28);
      --purple: #7c3aed;
      --purple-soft: rgba(124, 58, 237, 0.08);
      --purple-ring: rgba(124, 58, 237, 0.25);
      --shadow-card: 0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 4px rgba(15, 23, 42, 0.03);
      --shadow-float: 0 20px 50px rgba(15, 23, 42, 0.14);
    }

    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      font-family: var(--sans);
      font-size: 13px;
      line-height: 1.5;
      color: var(--text);
      background-color: var(--bg);
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    code, pre, .mono { font-family: var(--mono); }
    .num { font-variant-numeric: tabular-nums; }
    svg { display: block; flex-shrink: 0; }

    ::-webkit-scrollbar { width: 7px; height: 7px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 999px; }

    /* Minimal Topbar */
    .topbar-wrap {
      position: sticky;
      top: 0;
      z-index: 30;
      background: var(--bg-elev);
      backdrop-filter: blur(14px);
      -webkit-backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--border);
    }
    .topbar {
      max-width: 1480px;
      margin: 0 auto;
      padding: 9px 24px;
      min-height: 50px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 9px;
      min-width: 0;
    }
    .logo-mark {
      width: 26px;
      height: 26px;
      border-radius: 7px;
      background: linear-gradient(135deg, #10b981 0%, #0ea5e9 100%);
      color: #fff;
      display: grid;
      place-items: center;
    }
    .brand h1 {
      margin: 0;
      font-size: 14.5px;
      font-weight: 620;
      letter-spacing: -0.015em;
    }
    .brand-ver {
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--text-faint);
    }
    .brand-sep { color: var(--border-strong); font-size: 12px; }
    .brand-scope {
      font-size: 12px;
      color: var(--text-dim);
      font-weight: 500;
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      padding: 4px 10px;
      border-radius: 999px;
      background: var(--bg-inset);
      color: var(--text-dim);
      margin-right: 4px;
    }
    .live-pill.is-live { color: var(--green); background: var(--green-soft); }
    .live-pill.is-paused { color: var(--yellow); background: var(--yellow-soft); }
    .live-pill.is-err { color: var(--red); background: var(--red-soft); }
    .live-pill .sep { opacity: 0.45; }

    .dot-pulse {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--green);
      display: inline-block;
      box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.65);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6); }
      70% { box-shadow: 0 0 0 6px rgba(52, 211, 153, 0); }
      100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .spin svg { animation: spin 0.8s linear infinite; }

    /* Quiet Ghost Buttons */
    .btn {
      appearance: none;
      border: 1px solid transparent;
      background: transparent;
      color: var(--text-dim);
      border-radius: var(--radius-sm);
      height: 30px;
      padding: 0 10px;
      font-family: var(--sans);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: background 0.14s, color 0.14s, border-color 0.14s;
      white-space: nowrap;
    }
    .btn:hover {
      background: var(--bg-inset);
      color: var(--text);
    }
    .btn-primary { color: var(--accent); }
    .btn-primary:hover { background: var(--accent-soft); color: var(--accent); }
    .btn-outline {
      border-color: var(--border);
      background: var(--bg-card);
    }
    .btn-outline:hover { border-color: var(--border-strong); background: var(--bg-card-hover); }
    .btn-xs {
      height: 24px;
      padding: 0 7px;
      font-size: 11px;
      border-radius: 6px;
    }
    .btn-icon-only {
      width: 26px;
      height: 24px;
      padding: 0;
      justify-content: center;
    }
    .btn.copied {
      color: var(--green);
      background: var(--green-soft);
    }

    /* Main Container */
    .container {
      max-width: 1480px;
      margin: 0 auto;
      padding: 16px 24px 40px;
    }

    /* Unified Telemetry Strip (Replaces 5 giant boxes) */
    .telemetry-strip {
      display: flex;
      flex-wrap: wrap;
      align-items: stretch;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-card);
      overflow: hidden;
    }
    .metric-cell {
      flex: 1 1 160px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 16px;
      border: 0;
      border-right: 1px solid var(--border);
      background: transparent;
      color: inherit;
      text-align: left;
      font-family: var(--sans);
      transition: background 0.14s;
    }
    .metric-cell:last-child { border-right: 0; }
    .metric-cell.clickable { cursor: pointer; }
    .metric-cell.clickable:hover { background: var(--bg-inset); }
    .metric-cell.is-filtered {
      background: var(--accent-soft);
      box-shadow: inset 0 -2px 0 var(--accent);
    }
    .metric-cell.is-warn.is-filtered {
      background: var(--orange-soft);
      box-shadow: inset 0 -2px 0 var(--orange);
    }
    .metric-left { min-width: 0; }
    .metric-label {
      font-size: 11.5px;
      color: var(--text-dim);
      font-weight: 500;
    }
    .metric-sub {
      font-size: 11px;
      color: var(--text-faint);
      margin-top: 1px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .metric-sub.live { color: var(--green); }
    .metric-sub.warn { color: var(--orange); }
    .metric-val {
      font-size: 20px;
      font-weight: 650;
      letter-spacing: -0.02em;
      color: var(--text);
      flex-shrink: 0;
    }
    .metric-cell.is-warn .metric-val { color: var(--orange); }
    @media (max-width: 820px) {
      .metric-cell {
        flex: 1 1 48%;
        border-bottom: 1px solid var(--border);
      }
    }

    /* Borderless Airy Control Bar */
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin: 14px 0 12px;
    }
    .pills {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      align-items: center;
    }
    .pill {
      appearance: none;
      font-family: var(--sans);
      border: 1px solid transparent;
      background: transparent;
      color: var(--text-dim);
      padding: 5px 10px;
      border-radius: var(--radius-sm);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: background 0.14s, color 0.14s, border-color 0.14s;
    }
    .pill:hover { background: var(--bg-inset); color: var(--text); }
    .pill.active {
      background: var(--bg-pill-active);
      border-color: var(--border);
      color: var(--text);
      font-weight: 600;
      box-shadow: var(--shadow-card);
    }
    .pill.alert-pill { color: var(--orange); }
    .pill.alert-pill.active {
      background: var(--orange-soft);
      border-color: var(--orange-ring);
      color: var(--orange);
    }
    .pill-cnt {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-faint);
    }
    .pill.active .pill-cnt { color: var(--text-dim); }

    .toolbar-right {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }

    /* Custom Compact Switch */
    .switch-label {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      font-size: 12px;
      color: var(--text-dim);
      cursor: pointer;
      user-select: none;
      padding: 4px 6px;
      border-radius: 6px;
    }
    .switch-label:hover { color: var(--text); }
    .switch-label input { position: absolute; opacity: 0; width: 1px; height: 1px; }
    .switch-track {
      width: 28px;
      height: 16px;
      border-radius: 999px;
      background: var(--bg-inset);
      border: 1px solid var(--border-strong);
      position: relative;
      transition: background 0.15s, border-color 0.15s;
    }
    .switch-thumb {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--text-dim);
      position: absolute;
      top: 2px;
      left: 2px;
      transition: transform 0.15s, background 0.15s;
    }
    .switch-label input:checked + .switch-track {
      background: var(--accent-soft);
      border-color: var(--accent);
    }
    .switch-label input:checked + .switch-track .switch-thumb {
      transform: translateX(12px);
      background: var(--accent);
    }

    /* Minimal Search Box */
    .search-wrap {
      position: relative;
      display: flex;
      align-items: center;
    }
    .search-icon {
      position: absolute;
      left: 9px;
      color: var(--text-faint);
      pointer-events: none;
    }
    .search-box {
      border: 1px solid var(--border);
      background: var(--bg-surface);
      color: var(--text);
      border-radius: var(--radius-sm);
      height: 30px;
      padding: 0 28px 0 28px;
      font-family: var(--sans);
      font-size: 12px;
      width: 210px;
      outline: none;
      transition: border-color 0.14s, width 0.18s;
    }
    .search-box:focus {
      border-color: var(--border-strong);
      width: 240px;
    }
    .search-box::-webkit-search-cancel-button {
      -webkit-appearance: none;
      appearance: none;
    }
    .search-kbd {
      position: absolute;
      right: 7px;
      font-family: var(--mono);
      font-size: 10px;
      padding: 1px 5px;
      border-radius: 4px;
      border: 1px solid var(--border);
      color: var(--text-faint);
      pointer-events: none;
    }
    .search-clear {
      position: absolute;
      right: 6px;
      border: 0;
      background: transparent;
      color: var(--text-faint);
      cursor: pointer;
      padding: 2px;
      display: none;
      border-radius: 4px;
    }
    .search-clear:hover { color: var(--text); }
    .search-wrap.has-value .search-clear { display: grid; place-items: center; }
    .search-wrap.has-value .search-kbd,
    .search-wrap:focus-within .search-kbd { display: none; }

    /* Segmented View Switcher */
    .seg {
      display: inline-flex;
      padding: 2px;
      gap: 2px;
      background: var(--bg-inset);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
    }
    .seg button {
      border: 0;
      background: transparent;
      color: var(--text-dim);
      height: 24px;
      padding: 0 9px;
      font-family: var(--sans);
      font-size: 12px;
      font-weight: 500;
      border-radius: 5px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: background 0.14s, color 0.14s;
    }
    .seg button:hover { color: var(--text); }
    .seg button.active {
      background: var(--bg-surface);
      color: var(--text);
      box-shadow: var(--shadow-card);
    }

    /* 4-Column Kanban Fitted Cleanly Above the Fold */
    .kanban {
      display: grid;
      grid-template-columns: repeat(4, minmax(220px, 1fr));
      gap: 12px;
      align-items: start;
    }
    @media (max-width: 960px) {
      .kanban { grid-template-columns: repeat(2, minmax(220px, 1fr)); }
    }
    @media (max-width: 600px) {
      .kanban { grid-template-columns: 1fr; }
    }
    .column {
      background: var(--bg-col);
      border: 1px solid var(--border-faint);
      border-radius: 12px;
      padding: 10px;
      min-height: 220px;
    }
    .col-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 4px 9px;
      margin-bottom: 8px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-dim);
    }
    .col-title {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--text);
    }
    .col-count {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-faint);
    }
    .card-stack {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .col-empty {
      padding: 22px 10px;
      text-align: center;
      color: var(--text-faint);
      font-size: 12px;
    }

    .mini-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      display: inline-block;
      flex-shrink: 0;
    }
    .dot-green { background: var(--green); }
    .dot-amber { background: var(--yellow); }
    .dot-orange { background: var(--orange); }
    .dot-red { background: var(--red); }
    .dot-blue { background: var(--accent); }
    .dot-muted { background: var(--text-faint); }

    /* Ultra-Clean Zero-Nested-Box Cards */
    .card {
      position: relative;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 11px 12px;
      box-shadow: var(--shadow-card);
      cursor: pointer;
      transition: border-color 0.14s, background 0.14s;
      overflow: hidden;
    }
    .card::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 3px;
      background: transparent;
    }
    .card:hover {
      border-color: var(--border-strong);
      background: var(--bg-card-hover);
    }
    .card.is-selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent-ring), var(--shadow-card);
    }
    .card.is-live::before { background: var(--green); }
    .card.is-stalled::before { background: var(--orange); }
    .card.is-fail::before { background: var(--red); }

    .card-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-height: 18px;
    }
    .card-meta {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      min-width: 0;
      font-size: 11.5px;
      color: var(--text-faint);
    }
    .repo-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      max-width: 130px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--text-dim);
    }
    .id-link {
      font-family: var(--mono);
      font-weight: 600;
      color: var(--text-dim);
      font-size: 11.5px;
    }
    .id-link:hover { color: var(--accent); }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 1px 6px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 550;
      line-height: 1.35;
      background: var(--bg-inset);
      color: var(--text-dim);
      white-space: nowrap;
    }
    .tone-info { background: var(--accent-soft); color: var(--accent); }
    .tone-success { background: var(--green-soft); color: var(--green); }
    .tone-warning { background: var(--yellow-soft); color: var(--yellow); }
    .tone-orange { background: var(--orange-soft); color: var(--orange); }
    .tone-danger { background: var(--red-soft); color: var(--red); }
    .tone-violet { background: var(--purple-soft); color: var(--purple); }
    .tone-muted { background: var(--bg-inset); color: var(--text-faint); }

    .card-title {
      margin: 5px 0 0;
      font-size: 13.5px;
      font-weight: 560;
      line-height: 1.45;
      color: var(--text);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      word-break: break-word;
    }

    .card-context {
      margin-top: 8px;
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .card-branch {
      display: flex;
      align-items: center;
      gap: 5px;
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-faint);
      min-width: 0;
    }
    .card-branch span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .card-task {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 11.5px;
      color: var(--text-dim);
      min-width: 0;
    }
    .card-task span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .card-prog {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .progress-track {
      flex: 1;
      height: 3px;
      border-radius: 999px;
      background: var(--bg-inset);
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--green));
      border-radius: 999px;
      transition: width 0.25s ease;
    }
    .prog-num {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-faint);
      flex-shrink: 0;
    }

    .change-inline {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      font-size: 11.5px;
    }
    .pr-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-weight: 550;
      color: var(--text);
    }
    .pr-link:hover { color: var(--accent); text-decoration: none; }
    .ci-inline {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      font-size: 11px;
      font-weight: 500;
    }
    .ci-inline.pass { color: var(--green); }
    .ci-inline.fail { color: var(--red); }
    .ci-inline.pending { color: var(--yellow); }
    .ci-inline.none { color: var(--text-faint); }

    .card-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 8px;
      font-size: 11px;
      color: var(--text-faint);
      min-height: 22px;
    }
    .pulse-inline {
      display: inline-flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 5px;
      min-width: 0;
    }
    .diff-ins { font-family: var(--mono); color: var(--green); font-weight: 600; }
    .diff-del { font-family: var(--mono); color: var(--red); font-weight: 600; }
    .stalled-note {
      margin-top: 5px;
      font-size: 11px;
      color: var(--orange);
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .card-copy-btn {
      opacity: 0.45;
      transition: opacity 0.14s, background 0.14s, color 0.14s;
      flex-shrink: 0;
    }
    .card:hover .card-copy-btn,
    .card-copy-btn:focus-visible,
    .card-copy-btn.copied { opacity: 1; }

    /* Repo Group View */
    .repo-section {
      margin-top: 14px;
      background: var(--bg-col);
      border: 1px solid var(--border-faint);
      border-radius: 12px;
      padding: 13px 14px;
    }
    .repo-section:first-child { margin-top: 0; }
    .repo-hdr {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 11px;
      padding-bottom: 9px;
      border-bottom: 1px solid var(--border);
    }
    .repo-title-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .repo-path {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-faint);
      margin-top: 2px;
    }
    .repo-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 10px;
    }

    /* List / Table View */
    .list-wrap {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-card);
      overflow-x: auto;
    }
    .list-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12.5px;
      min-width: 900px;
    }
    .list-table th {
      text-align: left;
      padding: 9px 12px;
      font-size: 11px;
      font-weight: 600;
      color: var(--text-faint);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    .list-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border-faint);
      vertical-align: middle;
    }
    .list-table tbody tr {
      cursor: pointer;
      transition: background 0.12s;
    }
    .list-table tbody tr:hover { background: var(--bg-card-hover); }
    .list-table tbody tr:last-child td { border-bottom: 0; }
    .list-table tr.is-selected { background: var(--accent-soft); }
    .list-title-cell {
      max-width: 290px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 560;
      color: var(--text);
    }

    /* Slide-Over Inspector Drawer */
    .inspector-overlay {
      position: fixed;
      inset: 0;
      z-index: 50;
      background: rgba(0, 0, 0, 0.44);
      backdrop-filter: blur(2px);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease;
    }
    .inspector-overlay.open { opacity: 1; pointer-events: auto; }
    .inspector-panel {
      position: fixed;
      top: 0;
      right: 0;
      bottom: 0;
      width: 460px;
      max-width: 100vw;
      z-index: 60;
      background: var(--bg-surface);
      border-left: 1px solid var(--border-strong);
      box-shadow: var(--shadow-float);
      display: flex;
      flex-direction: column;
      transform: translateX(100%);
      transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1);
    }
    .inspector-panel.open { transform: translateX(0); }
    .inspector-hdr {
      padding: 16px 18px 13px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .inspector-title {
      margin: 6px 0 0;
      font-size: 15.5px;
      font-weight: 620;
      line-height: 1.4;
      word-break: break-word;
    }
    .inspector-body {
      flex: 1;
      overflow-y: auto;
      padding: 15px 18px 24px;
    }
    .meta-grid {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 9px;
      background: var(--bg-inset);
      border: 1px solid var(--border-faint);
    }
    .meta-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      font-size: 12px;
    }
    .meta-key { color: var(--text-faint); flex-shrink: 0; width: 64px; }
    .meta-val {
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
      text-align: right;
    }
    .cmd-box {
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 9px;
      background: var(--bg-inset);
      border: 1px solid var(--border-faint);
    }
    .cmd-box-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 11.5px;
      color: var(--text-faint);
      margin-bottom: 5px;
    }
    .cmd-code {
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--accent);
      word-break: break-all;
      line-height: 1.45;
    }

    .tabs {
      display: flex;
      gap: 4px;
      margin-top: 14px;
      border-bottom: 1px solid var(--border);
    }
    .tab-btn {
      appearance: none;
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: var(--text-dim);
      padding: 8px 12px;
      font-family: var(--sans);
      font-size: 12.5px;
      font-weight: 550;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .tab-btn:hover { color: var(--text); }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-pane { margin-top: 12px; }

    .task-row {
      padding: 9px 11px;
      border-radius: 8px;
      border: 1px solid var(--border-faint);
      background: var(--bg-inset);
      margin-bottom: 7px;
    }
    .task-row-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      font-size: 12.5px;
      font-weight: 550;
      word-break: break-word;
    }
    .task-row-sub {
      margin-top: 4px;
      font-size: 11px;
      color: var(--text-faint);
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .file-list {
      border: 1px solid var(--border-faint);
      border-radius: 8px;
      background: var(--bg-inset);
      overflow: hidden;
    }
    .file-row {
      display: flex;
      align-items: center;
      gap: 9px;
      padding: 7px 10px;
      font-family: var(--mono);
      font-size: 11.5px;
      border-bottom: 1px solid var(--border-faint);
      word-break: break-all;
    }
    .file-row:last-child { border-bottom: 0; }
    .file-code {
      min-width: 24px;
      text-align: center;
      padding: 1px 5px;
      border-radius: 4px;
      font-size: 10.5px;
      font-weight: 700;
      background: var(--bg-card);
      color: var(--accent);
    }
    .file-code.untracked { color: var(--green); background: var(--green-soft); }
    .file-code.deleted { color: var(--red); background: var(--red-soft); }

    /* Empty State & Warnings & Footer */
    .empty-state {
      text-align: center;
      padding: 54px 24px;
      background: var(--bg-col);
      border: 1px dashed var(--border-strong);
      border-radius: 12px;
      color: var(--text-dim);
    }
    .empty-icon {
      width: 40px;
      height: 40px;
      margin: 0 auto 12px;
      border-radius: 10px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      display: grid;
      place-items: center;
      color: var(--accent);
    }
    .empty-cmds {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 8px;
      margin-top: 14px;
    }
    .empty-cmd {
      font-family: var(--mono);
      font-size: 12px;
      padding: 5px 10px;
      border-radius: 7px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text);
    }

    .warnings-box {
      display: flex;
      align-items: flex-start;
      gap: 9px;
      margin-top: 16px;
      padding: 10px 14px;
      border-radius: var(--radius);
      border: 1px solid var(--yellow-ring);
      background: var(--yellow-soft);
      color: var(--yellow);
      font-size: 12px;
    }

    .footer {
      margin-top: 20px;
      padding-top: 12px;
      border-top: 1px solid var(--border-faint);
      font-size: 11.5px;
      color: var(--text-faint);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }

    /* Toast */
    .toast-wrap {
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 80;
      display: flex;
      flex-direction: column;
      gap: 8px;
      pointer-events: none;
    }
    .toast {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 13px;
      border-radius: 8px;
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      box-shadow: var(--shadow-float);
      animation: toast-in 0.16s ease;
    }
    @keyframes toast-in {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body>
  <div class="topbar-wrap">
    <header class="topbar">
      <div class="brand">
        <div class="logo-mark" aria-hidden="true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="6" y1="3" x2="6" y2="15"></line>
            <circle cx="18" cy="6" r="3"></circle>
            <circle cx="6" cy="18" r="3"></circle>
            <path d="M18 9a9 9 0 0 1-9 9"></path>
          </svg>
        </div>
        <h1>IDD 实时开发监控看板</h1>
        <span class="brand-ver">v__IDD_VERSION__</span>
        <span class="brand-sep">·</span>
        <span id="scope-tag" class="brand-scope">全局</span>
      </div>
      <div class="controls">
        <span id="conn-tag" class="live-pill is-live">
          <span class="dot-pulse"></span>
          <span>实时</span>
          <span class="sep">·</span>
          <span id="updated-tag" class="num">同步中...</span>
        </span>
        <button id="pause-btn" class="btn" type="button"></button>
        <button id="sync-btn" class="btn btn-primary" type="button" title="快捷键 r"></button>
        <button id="theme-btn" class="btn" type="button" title="切换深浅色"></button>
      </div>
    </header>
  </div>

  <div class="container">
    <section id="kpis" class="telemetry-strip"></section>

    <section class="toolbar">
      <div id="repo-pills" class="pills"></div>
      <div class="toolbar-right">
        <label class="switch-label">
          <input id="wt-only-cb" type="checkbox" />
          <span class="switch-track"><span class="switch-thumb"></span></span>
          <span>只看已开工</span>
        </label>
        <button id="alerts-only-btn" class="pill alert-pill" type="button" style="display:none;"></button>
        <div id="search-wrap" class="search-wrap">
          <span class="search-icon" aria-hidden="true">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
          </span>
          <input id="search-input" class="search-box" type="search" placeholder="搜索 #编号、标题、分支..." />
          <span class="search-kbd">/</span>
          <button id="search-clear" class="search-clear" type="button" aria-label="清空搜索">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div class="seg" role="tablist" aria-label="视图切换">
          <button id="view-kanban" class="active" type="button"></button>
          <button id="view-repos" type="button"></button>
          <button id="view-list" type="button"></button>
        </div>
      </div>
    </section>

    <main id="main-content"></main>
    <div id="warnings-wrap"></div>
    <footer id="footer" class="footer"></footer>
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
        commit: '<circle cx="12" cy="12" r="3"/><line x1="3" y1="12" x2="9" y2="12"/><line x1="15" y1="12" x2="21" y2="12"/>',
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
        copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
        check: '<polyline points="20 6 9 17 4 12"/>',
        externalLink: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
        x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
        fileDiff: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/>',
        listChecks: '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
        activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
        layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
        chevronRight: '<polyline points="9 18 15 12 9 6"/>',
        minusCircle: '<circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/>'
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

      const state = {
        snapshot: null,
        selectedRepo: "ALL",
        viewMode: localStorage.getItem("idd_board_view") || "kanban",
        search: "",
        worktreeOnly: false,
        alertsOnly: false,
        paused: false,
        inspectedKey: null,
        inspectorTab: "tasks",
        timerId: null,
        fetching: false,
        lastClockStr: "同步中...",
        lastSig: ""
      };

      if (!["kanban", "repos", "list"].includes(state.viewMode)) {
        state.viewMode = "kanban";
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
        return d.toLocaleTimeString("zh-CN", { hour12: false });
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
          el.style.transition = "opacity 0.18s";
          setTimeout(() => el.remove(), 200);
        }, 1900);
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
              : icon("check", 12) + "<span>已复制</span>";
            clearTimeout(Number(btnEl.dataset.timerId || 0));
            const tid = setTimeout(() => {
              btnEl.classList.remove("copied");
              btnEl.innerHTML = prevHtml;
            }, 1500);
            btnEl.dataset.timerId = String(tid);
          }
          showToast(toastMsg || "已复制到剪贴板");
        } catch (err) {
          showToast("复制失败: " + err.message, "err");
        }
      }

      function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        const btn = document.getElementById("theme-btn");
        if (btn) {
          btn.innerHTML = theme === "dark"
            ? icon("sun", 13) + "<span>浅色</span>"
            : icon("moon", 13) + "<span>深色</span>";
        }
      }

      function syncHeaderControls() {
        const pauseBtn = document.getElementById("pause-btn");
        if (pauseBtn) {
          pauseBtn.innerHTML = state.paused
            ? icon("play", 12) + "<span>继续</span>"
            : icon("pause", 12) + "<span>暂停</span>";
        }
        const syncBtn = document.getElementById("sync-btn");
        if (syncBtn) {
          syncBtn.classList.toggle("spin", state.fetching);
          syncBtn.innerHTML = icon("refresh", 12) + "<span>" + (state.fetching ? "同步中" : "同步远端") + "</span>";
        }
        const vk = document.getElementById("view-kanban");
        const vr = document.getElementById("view-repos");
        const vl = document.getElementById("view-list");
        if (vk) {
          vk.classList.toggle("active", state.viewMode === "kanban");
          vk.innerHTML = icon("columns", 12) + "<span>看板</span>";
        }
        if (vr) {
          vr.classList.toggle("active", state.viewMode === "repos");
          vr.innerHTML = icon("folder", 12) + "<span>按仓库</span>";
        }
        if (vl) {
          vl.classList.toggle("active", state.viewMode === "list");
          vl.innerHTML = icon("list", 12) + "<span>列表</span>";
        }
      }

      function updateConnectionBadge(ok, errorMsg) {
        const tag = document.getElementById("conn-tag");
        if (!tag) return;
        const clock = escapeHtml(state.lastClockStr || "同步中...");
        if (!ok) {
          tag.className = "live-pill is-err";
          tag.innerHTML = icon("alertTriangle", 12) + "<span>" + escapeHtml(errorMsg || "连接中断") + '</span><span id="updated-tag" style="display:none;">' + clock + "</span>";
          return;
        }
        if (state.paused) {
          tag.className = "live-pill is-paused";
          tag.innerHTML = icon("pause", 11) + '<span>已暂停</span><span class="sep">·</span><span id="updated-tag" class="num">' + clock + "</span>";
          return;
        }
        tag.className = "live-pill is-live";
        tag.innerHTML = '<span class="dot-pulse"></span><span>实时</span><span class="sep">·</span><span id="updated-tag" class="num">' + clock + "</span>";
      }

      function parseStage(rawStage) {
        const cleaned = String(rawStage || "").replace(/^[\s\u{1F300}-\u{1FAFF}\u2600-\u27BF\uFE0F]+/u, "").trim();
        const label = cleaned === "待认领" ? "待处理" : (cleaned || "—");
        if (label === "修 CI" || label === "受阻") return { label, tone: "tone-danger", dot: "dot-red" };
        if (label === "待合入" || label.startsWith("待提")) return { label, tone: "tone-success", dot: "dot-green" };
        if (label === "CI 运行中") return { label, tone: "tone-warning", dot: "dot-amber" };
        if (label.startsWith("草稿")) return { label, tone: "tone-violet", dot: "dot-muted" };
        if (label === "待处理") return { label, tone: "tone-muted", dot: "dot-muted" };
        return { label, tone: "tone-info", dot: "dot-blue" };
      }

      function isItemAlert(item) {
        const pulse = item.pulse || null;
        const isStalled = pulse && pulse.activity_state === "stalled";
        const st = parseStage(item.stage).label;
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
        if (state.alertsOnly && !isItemAlert(item)) return false;
        const q = state.search.trim().toLowerCase();
        if (!q) return true;
        const hay = [
          item.repo_name,
          item.issue_number != null ? "#" + item.issue_number : "",
          item.title,
          item.issue,
          item.branch,
          item.current_task,
          item.stage
        ].join(" ").toLowerCase();
        return hay.includes(q);
      }

      function cardBucket(item) {
        if (item._kind === "local") return "developing";
        if (item._kind === "orphan") {
          return item.checks_overall === "FAIL" || item.checks_overall === "PENDING" || item.isDraft ? "review" : "ready";
        }
        const label = parseStage(item.stage).label;
        if (label === "待处理" || label === "待认领") return "todo";
        if (label === "待合入") return "ready";
        if (label === "修 CI" || label === "CI 运行中" || label.startsWith("草稿")) return "review";
        return "developing";
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

      function renderPulseInline(pulse, showStalledBanner) {
        if (!pulse) return "";
        const st = pulse.activity_state || "quiet";
        const ago = pulse.last_active_ago || "无记录";
        let dotCls = "dot-muted";
        let timeLabel = ago;
        if (st === "active") {
          dotCls = "dot-green";
          timeLabel = ago === "刚刚" ? "刚刚活跃" : ago;
        } else if (st === "warm") {
          dotCls = "dot-amber";
        } else if (st === "stalled") {
          dotCls = "dot-orange";
          timeLabel = (ago.endsWith("前") ? ago.slice(0, -1) : ago) + "无动静";
        }
        const opHtml = pulse.git_op
          ? '<span class="badge tone-violet">' + escapeHtml(pulse.git_op.toUpperCase()) + "</span>"
          : "";
        const dirtyCount = Number(pulse.dirty_count || 0);
        const ins = Number(pulse.insertions || 0);
        const dels = Number(pulse.deletions || 0);
        let diffHtml = "<span>干净</span>";
        if (dirtyCount > 0) {
          diffHtml = "<span>" + dirtyCount + " 文件</span>";
          if (ins > 0 || dels > 0) {
            diffHtml += ' <span class="diff-ins">+' + ins + '</span> <span class="diff-del">-' + dels + "</span>";
          }
        }
        let res = '<div class="pulse-inline"><span class="mini-dot ' + dotCls + '"></span><span>' + escapeHtml(timeLabel) + "</span><span>·</span>" + diffHtml + opHtml + "</div>";
        if (showStalledBanner && st === "stalled") {
          res += '<div class="stalled-note">' + icon("alertTriangle", 12) + "<span>超过 30 分钟无动静，可能在等人工确认</span></div>";
        }
        return res;
      }

      function renderChangeInline(item) {
        const ch = item.change;
        if (!ch) return "";
        const mrLabel = item.mr_label || (item.forge_type === "gitlab" ? "MR" : "PR");
        const mrPrefix = item.mr_prefix || (item.forge_type === "gitlab" ? "!" : "#");
        const num = ch.number != null ? ch.number : "";
        const prLabel = mrLabel + (num !== "" ? " " + mrPrefix + num : "");
        const overall = ch.checks_overall || "NONE";
        const ciMap = {
          PASS: { cls: "pass", ic: "checkCircle", text: "CI 全绿" },
          FAIL: { cls: "fail", ic: "xCircle", text: "CI 失败" },
          PENDING: { cls: "pending", ic: "clock", text: "CI 运行中" },
          NONE: { cls: "none", ic: "minusCircle", text: "无 CI" }
        };
        const ci = ciMap[overall] || ciMap.NONE;
        const chUrl = safeUrl(ch.url);
        const prEl = chUrl
          ? '<a class="pr-link" href="' + escapeHtml(chUrl) + '" target="_blank" rel="noopener noreferrer" data-stop-open="1">' + icon("pr", 12) + "<span>" + escapeHtml(prLabel) + "</span></a>"
          : '<span class="pr-link">' + icon("pr", 12) + "<span>" + escapeHtml(prLabel) + "</span></span>";
        const draftEl = ch.isDraft ? '<span class="badge tone-violet">Draft</span>' : "";
        const ciEl = '<span class="ci-inline ' + ci.cls + '">' + icon(ci.ic, 11) + "<span>" + escapeHtml(ci.text) + "</span></span>";
        const mstate = ch.mergeStateStatus || "";
        const conflictEl = (mstate === "BEHIND" || mstate === "DIRTY")
          ? '<span class="badge tone-danger">有冲突</span>'
          : "";
        return '<div class="change-inline">' + prEl + draftEl + ciEl + conflictEl + "</div>";
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
        return '<span class="badge tone-violet">本地</span>';
      }

      function renderCard(item, opts) {
        const options = opts || {};
        const pulse = item.pulse || null;
        const isStalled = pulse && pulse.activity_state === "stalled";
        const isLive = pulse && pulse.activity_state === "active";
        const stInfo = parseStage(item.stage);
        const isFail = stInfo.label === "修 CI" || stInfo.label === "受阻" || (item.change && item.change.checks_overall === "FAIL");
        const isSelected = state.inspectedKey === item._key;
        const cardCls = [
          "card",
          isLive ? "is-live" : "",
          isStalled ? "is-stalled" : "",
          isFail ? "is-fail" : "",
          isSelected ? "is-selected" : ""
        ].filter(Boolean).join(" ");

        const suppressStage = options.columnId && (
          (options.columnId === "todo" && stInfo.label === "待处理") ||
          (options.columnId === "developing" && stInfo.label === "开发中") ||
          (options.columnId === "ready" && stInfo.label === "待合入")
        );
        const stageBadgeHtml = suppressStage
          ? ""
          : '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>";

        const { total, done, pct } = getProgressNumbers(item);
        const ctxParts = [];
        if (item.branch) {
          ctxParts.push('<div class="card-branch" title="' + escapeHtml(item.branch) + '">' + icon("branch", 11) + "<span>" + escapeHtml(item.branch) + "</span></div>");
        }
        if (item.current_task) {
          ctxParts.push('<div class="card-task" title="' + escapeHtml(item.current_task) + '">' + icon("chevronRight", 12) + "<span>" + escapeHtml(item.current_task) + "</span></div>");
        } else if (item.worktree && total === 0) {
          ctxParts.push('<div class="card-task">' + icon("activity", 12) + '<span style="color:var(--text-faint);">已建目录，待拆解步骤</span></div>');
        }
        if (total > 0) {
          ctxParts.push(
            '<div class="card-prog">' +
              '<div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
              '<span class="prog-num">' + done + "/" + total + "</span>" +
            "</div>"
          );
        }
        if (item.change) {
          ctxParts.push(renderChangeInline(item));
        }

        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const startCmd = targetArg && item.repo_path ? ("cd " + item.repo_path + " && idd start " + targetArg) : "";
        const pulseHtml = renderPulseInline(pulse, false);
        const copyBtnHtml = startCmd
          ? '<button class="btn btn-xs btn-icon-only card-copy-btn" data-copy-val="' + escapeHtml(startCmd) + '" data-copy-msg="已复制接手命令" data-stop-open="1" type="button" title="复制接手命令">' + icon("terminal", 12) + "</button>"
          : "";

        const showFooter = Boolean(pulseHtml || copyBtnHtml);
        const repoPart = options.showRepo
          ? '<span class="repo-chip">' + forgeIcon(item.forge_type, 11) + "<span>" + escapeHtml(item.repo_name || "") + "</span></span><span>·</span>"
          : "";

        return (
          '<article class="' + cardCls + '" data-open-key="' + escapeHtml(item._key) + '">' +
            '<div class="card-top">' +
              '<div class="card-meta">' + repoPart + renderIdHtml(item) + "</div>" +
              stageBadgeHtml +
            "</div>" +
            '<div class="card-title">' + escapeHtml(item.title || item.issue || "未命名任务") + "</div>" +
            (ctxParts.length ? '<div class="card-context">' + ctxParts.join("") + "</div>" : "") +
            (isStalled ? '<div class="stalled-note">' + icon("alertTriangle", 11) + "<span>超过 30 分钟无动静</span></div>" : "") +
            (showFooter ? '<div class="card-foot">' + (pulseHtml || "<span></span>") + copyBtnHtml + "</div>" : "") +
          "</article>"
        );
      }

      function renderListTable(items) {
        const rowsHtml = items.map((item) => {
          const pulse = item.pulse || null;
          const stInfo = parseStage(item.stage);
          const { total, done, pct } = getProgressNumbers(item);
          const progHtml = total > 0
            ? '<div style="display:flex;align-items:center;gap:8px;min-width:110px;"><div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div><span class="prog-num">' + done + "/" + total + "</span></div>"
            : '<span style="color:var(--text-faint);">—</span>';
          const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
          const startCmd = targetArg && item.repo_path ? ("cd " + item.repo_path + " && idd start " + targetArg) : "";
          const isSelected = state.inspectedKey === item._key;
          return (
            '<tr class="' + (isSelected ? "is-selected" : "") + '" data-open-key="' + escapeHtml(item._key) + '">' +
              "<td>" +
                '<div style="display:flex;align-items:center;gap:8px;">' +
                  renderIdHtml(item) +
                  '<span class="list-title-cell" title="' + escapeHtml(item.title || item.issue || "") + '">' + escapeHtml(item.title || item.issue || "未命名任务") + "</span>" +
                "</div>" +
              "</td>" +
              '<td><span class="repo-chip">' + forgeIcon(item.forge_type, 12) + "<span>" + escapeHtml(item.repo_name || "") + "</span></span></td>" +
              '<td><span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span></td>" +
              '<td>' + (item.branch ? '<code style="font-size:11px;color:var(--text-dim);">' + escapeHtml(item.branch) + "</code>" : '<span style="color:var(--text-faint);">—</span>') + "</td>" +
              "<td>" + progHtml + "</td>" +
              "<td>" + (renderPulseInline(pulse, false) || '<span style="color:var(--text-faint);">—</span>') + "</td>" +
              "<td>" + (renderChangeInline(item) || '<span style="color:var(--text-faint);">—</span>') + "</td>" +
              '<td>' + (startCmd ? '<button class="btn btn-xs btn-outline" data-copy-val="' + escapeHtml(startCmd) + '" data-copy-msg="已复制接手命令" data-stop-open="1" type="button">' + icon("terminal", 11) + "<span>接手</span></button>" : "—") + "</td>" +
            "</tr>"
          );
        }).join("");

        return (
          '<div class="list-wrap">' +
            '<table class="list-table">' +
              "<thead><tr><th>Issue / 标题</th><th>仓库</th><th>状态</th><th>分支</th><th>步骤进度</th><th>实时动态</th><th>PR/MR &amp; CI</th><th>操作</th></tr></thead>" +
              "<tbody>" + rowsHtml + "</tbody>" +
            "</table>" +
          "</div>"
        );
      }

      function renderKpis(snap) {
        const s = snap.summary || {};
        const stalled = s.stalled_worktrees || 0;
        const ciFailed = s.ci_failed_count || 0;
        const anomalies = stalled + ciFailed;
        const codingNow = s.coding_now_count || 0;
        const dirtyWt = s.dirty_worktrees || 0;
        const openChanges = s.open_changes || 0;

        const cells = [
          {
            action: "clear-filters",
            label: "仓库",
            value: s.repo_count || 0,
            sub: "点击重置筛选",
            subCls: "",
            warn: false,
            filtered: false
          },
          {
            action: "toggle-wt",
            label: "已开工",
            value: s.active_worktrees || 0,
            sub: codingNow > 0 ? "刚刚活跃 " + codingNow : "本地工作目录",
            subCls: codingNow > 0 ? "live" : "",
            warn: false,
            filtered: state.worktreeOnly
          },
          {
            action: "",
            label: "进行中步骤",
            value: s.in_progress_tasks || 0,
            sub: dirtyWt > 0 ? dirtyWt + " 处未提交改动" : "工作区干净",
            subCls: "",
            warn: false,
            filtered: false
          },
          {
            action: "",
            label: "待合入",
            value: s.ready_to_land_count || 0,
            sub: openChanges > 0 ? "共 " + openChanges + " 个 Open PR/MR" : "暂无 Open PR/MR",
            subCls: "",
            warn: false,
            filtered: false
          },
          {
            action: "toggle-alerts",
            label: "异常提醒",
            value: anomalies,
            sub: anomalies > 0 ? "卡住 " + stalled + " · CI 失败 " + ciFailed : "全部正常",
            subCls: anomalies > 0 ? "warn" : "",
            warn: anomalies > 0,
            filtered: state.alertsOnly
          }
        ];

        document.getElementById("kpis").innerHTML = cells.map((c) => {
          const cls = ["metric-cell", c.action ? "clickable" : "", c.warn ? "is-warn" : "", c.filtered ? "is-filtered" : ""].filter(Boolean).join(" ");
          const tag = c.action ? "button" : "div";
          const attrs = c.action ? ' type="button" data-kpi-action="' + c.action + '"' : "";
          return (
            "<" + tag + ' class="' + cls + '"' + attrs + ">" +
              '<div class="metric-left">' +
                '<div class="metric-label">' + escapeHtml(c.label) + "</div>" +
                '<div class="metric-sub ' + c.subCls + '">' + escapeHtml(c.sub) + "</div>" +
              "</div>" +
              '<div class="metric-val num">' + c.value + "</div>" +
            "</" + tag + ">"
          );
        }).join("");

        const alertBtn = document.getElementById("alerts-only-btn");
        if (alertBtn) {
          if (anomalies > 0 || state.alertsOnly) {
            alertBtn.style.display = "inline-flex";
            alertBtn.classList.toggle("active", state.alertsOnly);
            alertBtn.innerHTML = icon("alertTriangle", 12) + '<span>只看异常</span><span class="pill-cnt">' + anomalies + "</span>";
          } else {
            alertBtn.style.display = "none";
          }
        }
      }

      function renderRepoPills(snap) {
        const repos = snap.repos || [];
        const totalItems = (snap.issues || []).length + (snap.local_only_items || []).length;
        const parts = [
          '<button class="pill ' + (state.selectedRepo === "ALL" ? "active" : "") + '" data-repo="ALL" type="button">' +
            '<span>全部</span><span class="pill-cnt">' + totalItems + "</span></button>"
        ];
        for (const r of repos) {
          const cnt = (r.issues || []).length + (r.local_only_items || []).length;
          const activeWt = (r.issues || []).filter((x) => x.worktree).length + (r.local_only_items || []).length;
          const isAct = state.selectedRepo === r.repo_path;
          parts.push(
            '<button class="pill ' + (isAct ? "active" : "") + '" data-repo="' + escapeHtml(r.repo_path) + '" type="button">' +
              forgeIcon(r.forge, 12) +
              "<span>" + escapeHtml(r.repo_name) + "</span>" +
              '<span class="pill-cnt">' + activeWt + "/" + cnt + "</span>" +
            "</button>"
          );
        }
        document.getElementById("repo-pills").innerHTML = parts.join("");
      }

      function renderMain() {
        const snap = state.snapshot;
        const container = document.getElementById("main-content");
        if (!snap || !container) return;

        const repos = snap.repos || [];
        if (repos.length === 0) {
          container.innerHTML =
            '<div class="empty-state">' +
              '<div class="empty-icon">' + icon("layers", 18) + "</div>" +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">暂无已纳管的 Git 仓库</h3>' +
              '<p style="margin:0;font-size:12.5px;">在任意项目目录执行以下任一命令后，仓库会自动同步到这里：</p>' +
              '<div class="empty-cmds">' +
                '<code class="empty-cmd">idd start &lt;issue#&gt;</code>' +
                '<code class="empty-cmd">idd status</code>' +
                '<code class="empty-cmd">idd repos add .</code>' +
              "</div>" +
            "</div>";
          return;
        }

        const items = collectItems(false);
        if (items.length === 0) {
          container.innerHTML =
            '<div class="empty-state">' +
              '<div class="empty-icon">' + icon("activity", 18) + "</div>" +
              '<h3 style="margin:0 0 6px;font-size:14.5px;color:var(--text);">当前筛选条件下没有内容</h3>' +
              '<p style="margin:0 0 12px;font-size:12.5px;">可以切换仓库、清空搜索词或重置快捷筛选。</p>' +
              '<button class="btn btn-outline" type="button" data-kpi-action="clear-filters">' + icon("refresh", 12) + "<span>重置筛选</span></button>" +
            "</div>";
          return;
        }

        const showRepoOnCard = state.selectedRepo === "ALL" && repos.length > 1;

        if (state.viewMode === "kanban") {
          const buckets = {
            todo: { id: "todo", title: "待处理 Issue", dot: "dot-muted", items: [] },
            developing: { id: "developing", title: "开发中", dot: "dot-blue", items: [] },
            review: { id: "review", title: "PR / 修 CI", dot: "dot-amber", items: [] },
            ready: { id: "ready", title: "待合入", dot: "dot-green", items: [] }
          };
          for (const item of items) {
            buckets[cardBucket(item)].items.push(item);
          }
          container.innerHTML = '<div class="kanban">' + Object.values(buckets).map((col) =>
            '<section class="column">' +
              '<div class="col-hdr">' +
                '<span class="col-title"><span class="mini-dot ' + col.dot + '"></span><span>' + escapeHtml(col.title) + "</span></span>" +
                '<span class="col-count">' + col.items.length + "</span>" +
              "</div>" +
              '<div class="card-stack">' +
                (col.items.length
                  ? col.items.map((it) => renderCard(it, { showRepo: showRepoOnCard, columnId: col.id })).join("")
                  : '<div class="col-empty">暂无</div>') +
              "</div>" +
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
                "<div>" +
                  '<div class="repo-title-row">' +
                    forgeIcon(grp.forge, 14) +
                    '<strong style="font-size:14px;">' + escapeHtml(grp.name) + "</strong>" +
                    '<span class="badge">' + escapeHtml(grp.forge.toUpperCase()) + "</span>" +
                  "</div>" +
                  '<div class="repo-path">' + escapeHtml(grp.path) + "</div>" +
                "</div>" +
                '<span class="col-count">' + grp.items.length + " 项</span>" +
              "</div>" +
              '<div class="repo-grid">' + grp.items.map((it) => renderCard(it, { showRepo: false, columnId: "" })).join("") + "</div>" +
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

        const allItems = collectItems(true);
        const item = allItems.find((x) => x._key === state.inspectedKey);
        if (!item) {
          state.inspectedKey = null;
          overlay.classList.remove("open");
          panel.classList.remove("open");
          return;
        }

        const prevBody = panel.querySelector(".inspector-body");
        const prevScrollTop = prevBody ? prevBody.scrollTop : 0;

        const stInfo = parseStage(item.stage);
        const pulse = item.pulse || null;
        const tasks = item.tasks || [];
        const changedFiles = (pulse && pulse.changed_files) || [];
        const { total, done, pct } = getProgressNumbers(item);
        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const startCmd = targetArg && item.repo_path ? ("cd " + item.repo_path + " && idd start " + targetArg) : "";
        const issueHref = safeUrl(item.url);

        const taskStatusBadge = (st) => {
          const m = {
            done: { cls: "tone-success", ic: "checkCircle", text: "已完成" },
            in_progress: { cls: "tone-info", ic: "activity", text: "进行中" },
            blocked: { cls: "tone-danger", ic: "xCircle", text: "受阻" },
            deferred: { cls: "tone-warning", ic: "clock", text: "暂缓" },
            cancelled: { cls: "tone-muted", ic: "minusCircle", text: "已取消" },
            planned: { cls: "tone-muted", ic: "clock", text: "待开始" }
          };
          const cfg = m[st] || { cls: "tone-warning", ic: "alertTriangle", text: st || "未知" };
          return '<span class="badge ' + cfg.cls + '">' + icon(cfg.ic, 11) + "<span>" + escapeHtml(cfg.text) + "</span></span>";
        };

        let tabBody = "";
        if (state.inspectorTab === "files") {
          if (changedFiles.length === 0) {
            tabBody = '<div class="col-empty">当前工作区干净，暂无未提交改动</div>';
          } else {
            const summaryPills =
              '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">' +
                '<span class="badge">已修改 ' + (pulse.modified_count || 0) + "</span>" +
                '<span class="badge">未跟踪 ' + (pulse.untracked_count || 0) + "</span>" +
                '<span class="badge tone-success">+' + (pulse.insertions || 0) + "</span>" +
                '<span class="badge tone-danger">-' + (pulse.deletions || 0) + "</span>" +
              "</div>";
            const rows = changedFiles.map((f) => {
              const code = String(f.code || "M").trim();
              const codeCls = code === "??" ? "untracked" : (code.includes("D") ? "deleted" : "");
              return '<div class="file-row"><span class="file-code ' + codeCls + '">' + escapeHtml(code) + "</span><span>" + escapeHtml(f.path) + "</span></div>";
            }).join("");
            const more = pulse.has_more_files ? '<div style="padding:7px 10px;font-size:11.5px;color:var(--text-faint);">... 还有更多改动文件</div>' : "";
            tabBody = summaryPills + '<div class="file-list">' + rows + more + "</div>";
          }
        } else {
          if (tasks.length === 0) {
            tabBody = '<div class="col-empty">' + (item.worktree ? "已建工作目录，尚未拆解任务步骤" : "暂无本地任务步骤") + "</div>";
          } else {
            const prog =
              '<div style="margin-bottom:12px;">' +
                '<div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--text-faint);margin-bottom:5px;" class="num"><span>总体进度</span><span>' + done + " / " + total + " (" + pct + '%)</span></div>' +
                '<div class="progress-track" style="height:4px;"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
              "</div>";
            const cards = tasks.map((t) => {
              const b = taskStatusBadge(t.status);
              const dep = t.depends_on ? "依赖: " + t.depends_on : "";
              const testCmd = t.test ? "测试: " + t.test : "";
              return (
                '<div class="task-row">' +
                  '<div class="task-row-top"><span>' + escapeHtml(t.title || t.id) + "</span>" + b + "</div>" +
                  ((dep || testCmd)
                    ? '<div class="task-row-sub">' +
                        (dep ? "<span>" + escapeHtml(dep) + "</span>" : "") +
                        (testCmd ? '<span class="mono">' + escapeHtml(testCmd) + "</span>" : "") +
                      "</div>"
                    : "") +
                "</div>"
              );
            }).join("");
            tabBody = prog + cards;
          }
        }

        panel.innerHTML =
          '<div class="inspector-hdr">' +
            '<div style="min-width:0;flex:1;">' +
              '<div class="card-meta" style="flex-wrap:wrap;">' +
                forgeIcon(item.forge_type, 12) +
                "<span>" + escapeHtml(item.repo_name || "") + "</span>" +
                "<span>·</span>" +
                renderIdHtml(item) +
                '<span class="badge ' + stInfo.tone + '">' + escapeHtml(stInfo.label) + "</span>" +
                (issueHref ? '<a class="btn btn-xs" href="' + escapeHtml(issueHref) + '" target="_blank" rel="noopener noreferrer">' + icon("externalLink", 11) + "<span>查看原单</span></a>" : "") +
              "</div>" +
              '<h2 class="inspector-title">' + escapeHtml(item.title || item.issue || "未命名任务") + "</h2>" +
            "</div>" +
            '<button class="btn btn-icon-only" id="inspector-close-btn" type="button" aria-label="关闭详情">' + icon("x", 15) + "</button>" +
          "</div>" +
          '<div class="inspector-body">' +
            '<div class="meta-grid">' +
              '<div class="meta-row"><span class="meta-key">分支</span><span class="meta-val" title="' + escapeHtml(item.branch || "") + '">' + escapeHtml(item.branch || "—") + "</span>" +
                (item.branch ? '<button class="btn btn-xs btn-icon-only" data-copy-val="' + escapeHtml(item.branch) + '" data-copy-msg="已复制分支名" type="button" title="复制分支名">' + icon("copy", 11) + "</button>" : "") +
              "</div>" +
              '<div class="meta-row"><span class="meta-key">工作目录</span><span class="meta-val" title="' + escapeHtml(item.worktree || "") + '">' + escapeHtml(item.worktree || "尚未创建") + "</span>" +
                (item.worktree ? '<button class="btn btn-xs btn-icon-only" data-copy-val="' + escapeHtml(item.worktree) + '" data-copy-msg="已复制工作目录路径" type="button" title="复制工作目录路径">' + icon("copy", 11) + "</button>" : "") +
              "</div>" +
              (pulse && pulse.last_commit_sha
                ? '<div class="meta-row"><span class="meta-key">最近提交</span><span class="meta-val" title="' + escapeHtml(pulse.last_commit_subject || "") + '">' + escapeHtml(pulse.last_commit_sha + " · " + (pulse.last_commit_subject || "")) + "</span></div>"
                : "") +
            "</div>" +
            (pulse ? '<div style="margin-top:11px;">' + renderPulseInline(pulse, true) + "</div>" : "") +
            (item.change ? '<div style="margin-top:10px;">' + renderChangeInline(item) + "</div>" : "") +
            (startCmd
              ? '<div class="cmd-box">' +
                  '<div class="cmd-box-hdr"><span>快捷接手命令</span><button class="btn btn-xs btn-outline" data-copy-val="' + escapeHtml(startCmd) + '" data-copy-msg="已复制接手命令" type="button">' + icon("copy", 11) + "<span>复制</span></button></div>" +
                  '<div class="cmd-code">$ ' + escapeHtml(startCmd) + "</div>" +
                "</div>"
              : "") +
            '<div class="tabs">' +
              '<button class="tab-btn ' + (state.inspectorTab === "tasks" ? "active" : "") + '" data-inspector-tab="tasks" type="button">' + icon("listChecks", 13) + "<span>任务步骤 (" + tasks.length + ")</span></button>" +
              '<button class="tab-btn ' + (state.inspectorTab === "files" ? "active" : "") + '" data-inspector-tab="files" type="button">' + icon("fileDiff", 13) + "<span>改动文件 (" + ((pulse && pulse.dirty_count) || 0) + ")</span></button>" +
            "</div>" +
            '<div class="tab-pane">' + tabBody + "</div>" +
          "</div>";

        overlay.classList.add("open");
        panel.classList.add("open");
        overlay.setAttribute("aria-hidden", "false");
        panel.setAttribute("aria-hidden", "false");

        const newBody = panel.querySelector(".inspector-body");
        if (newBody && prevScrollTop) {
          newBody.scrollTop = prevScrollTop;
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
          w: snap.warnings,
          sr: state.selectedRepo,
          vm: state.viewMode,
          sq: state.search,
          wo: state.worktreeOnly,
          ao: state.alertsOnly,
          ik: state.inspectedKey,
          it: state.inspectorTab
        });
      }

      function renderAll(force) {
        const snap = state.snapshot;
        if (!snap) return;

        const scopeTag = document.getElementById("scope-tag");
        if (scopeTag) scopeTag.textContent = snap.global ? "全局" : "单仓库";
        state.lastClockStr = formatClock(snap.generated_at);
        const updatedTag = document.getElementById("updated-tag");
        if (updatedTag) updatedTag.textContent = state.lastClockStr;

        const sig = computeRenderSignature(snap);
        if (!force && sig === state.lastSig) {
          return;
        }
        state.lastSig = sig;

        renderKpis(snap);
        renderRepoPills(snap);
        renderMain();
        renderInspector();

        const warns = snap.warnings || [];
        document.getElementById("warnings-wrap").innerHTML = warns.length
          ? '<div class="warnings-box">' + icon("alertTriangle", 14) + "<div><strong>提示：</strong>" + warns.map((w) => escapeHtml(w)).join(" ｜ ") + "</div></div>"
          : "";

        const retainedCount = (snap.repos || []).reduce((acc, r) => acc + (r.retained_idle_worktrees || []).length, 0);
        const retainedText = retainedCount > 0 ? "已合入保留目录：" + retainedCount + " 个" : "保留目录均已清理";
        document.getElementById("footer").innerHTML =
          "<span>仓库索引：<code>" + escapeHtml(snap.repos_config_path || "~/.config/idd/repos.json") + "</code></span>" +
          "<span>" + escapeHtml(retainedText) + " · 快捷键 <code>/</code> 搜索 · <code>r</code> 同步远端 · <code>Esc</code> 关闭详情</span>";
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
          state.lastClockStr = formatClock(state.snapshot.generated_at);
          updateConnectionBadge(true);
          renderAll(false);
          if (forceRefresh) {
            showToast("已同步最新状态");
          }
        } catch (err) {
          updateConnectionBadge(false, "连接异常: " + err.message);
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
            document.getElementById("wt-only-cb").checked = state.worktreeOnly;
          } else if (act === "toggle-alerts") {
            state.alertsOnly = !state.alertsOnly;
          } else if (act === "clear-filters") {
            state.selectedRepo = "ALL";
            state.worktreeOnly = false;
            state.alertsOnly = false;
            state.search = "";
            document.getElementById("wt-only-cb").checked = false;
            document.getElementById("search-input").value = "";
            document.getElementById("search-wrap").classList.remove("has-value");
          }
          renderAll(true);
          return true;
        }
        return false;
      }

      document.getElementById("kpis").addEventListener("click", handleActionClick);

      document.getElementById("repo-pills").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-repo]");
        if (!btn) return;
        state.selectedRepo = btn.getAttribute("data-repo") || "ALL";
        renderAll(true);
      });

      document.getElementById("main-content").addEventListener("click", (e) => {
        if (handleActionClick(e)) return;
        const target = e.target.closest("[data-open-key]");
        if (target) {
          state.inspectedKey = target.getAttribute("data-open-key");
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
        const cur = document.documentElement.getAttribute("data-theme") || "light";
        const next = cur === "dark" ? "light" : "dark";
        localStorage.setItem("idd_board_theme", next);
        applyTheme(next);
      });

      document.getElementById("wt-only-cb").addEventListener("change", (e) => {
        state.worktreeOnly = Boolean(e.target.checked);
        renderAll(true);
      });

      document.getElementById("alerts-only-btn").addEventListener("click", () => {
        state.alertsOnly = !state.alertsOnly;
        renderAll(true);
      });

      const searchInput = document.getElementById("search-input");
      const searchWrap = document.getElementById("search-wrap");
      searchInput.addEventListener("input", (e) => {
        state.search = e.target.value || "";
        searchWrap.classList.toggle("has-value", state.search.length > 0);
        renderAll(true);
      });

      document.getElementById("search-clear").addEventListener("click", () => {
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
        if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          searchInput.focus();
          searchInput.select();
        } else if ((e.key === "r" || e.key === "R") && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault();
          fetchSnapshot(true);
        }
      });

      const savedTheme = localStorage.getItem("idd_board_theme") || "light";
      applyTheme(savedTheme);
      syncHeaderControls();
      fetchSnapshot(true);
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
            try:
                snapshot = monitor.collect_scope_snapshot(
                    root=self.root,
                    global_mode=self.global_mode,
                    open_only=False,
                    local_only=self.local_only,
                    forge_cache=self.cache,
                    force_refresh=force_refresh,
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
