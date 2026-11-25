#!/usr/bin/env python3
"""Local HTTP server and offline single-page Web Dashboard for `idd board`."""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import urllib.parse
import webbrowser

import monitor


BOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IDD 实时开发监控看板</title>
  <style>
    :root {
      --bg: #0b1020;
      --bg-elev: #11182d;
      --bg-card: #161f38;
      --bg-muted: #1d2744;
      --border: rgba(148, 163, 184, 0.16);
      --border-strong: rgba(148, 163, 184, 0.28);
      --text: #e2e8f0;
      --text-dim: #94a3b8;
      --text-faint: #64748b;
      --accent: #38bdf8;
      --accent-soft: rgba(56, 189, 248, 0.14);
      --green: #10b981;
      --green-soft: rgba(16, 185, 129, 0.15);
      --yellow: #f59e0b;
      --yellow-soft: rgba(245, 158, 11, 0.15);
      --orange: #fb923c;
      --orange-soft: rgba(251, 146, 60, 0.18);
      --red: #f43f5e;
      --red-soft: rgba(244, 63, 94, 0.16);
      --purple: #a78bfa;
      --purple-soft: rgba(167, 139, 250, 0.15);
      --shadow: 0 10px 26px rgba(2, 6, 23, 0.35);
      --radius: 12px;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }

    html[data-theme="light"] {
      --bg: #f1f5f9;
      --bg-elev: #ffffff;
      --bg-card: #ffffff;
      --bg-muted: #f8fafc;
      --border: rgba(15, 23, 42, 0.1);
      --border-strong: rgba(15, 23, 42, 0.2);
      --text: #0f172a;
      --text-dim: #475569;
      --text-faint: #64748b;
      --accent: #0284c7;
      --accent-soft: rgba(2, 132, 199, 0.1);
      --green: #059669;
      --green-soft: rgba(5, 150, 105, 0.12);
      --yellow: #d97706;
      --yellow-soft: rgba(217, 119, 6, 0.12);
      --orange: #ea580c;
      --orange-soft: rgba(234, 88, 12, 0.12);
      --red: #e11d48;
      --red-soft: rgba(225, 29, 72, 0.12);
      --purple: #7c3aed;
      --purple-soft: rgba(124, 58, 237, 0.1);
      --shadow: 0 6px 20px rgba(15, 23, 42, 0.07);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    code, pre { font-family: var(--mono); }

    .container {
      max-width: 1480px;
      margin: 0 auto;
      padding: 18px 22px 36px;
    }

    /* Header */
    .topbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 18px;
      background: var(--bg-elev);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .logo {
      width: 34px;
      height: 34px;
      border-radius: 9px;
      background: linear-gradient(135deg, #0ea5e9, #10b981);
      color: #fff;
      font-weight: 800;
      font-size: 13px;
      display: grid;
      place-items: center;
      letter-spacing: 0.5px;
    }
    .brand h1 {
      margin: 0;
      font-size: 17px;
      font-weight: 700;
      letter-spacing: -0.01em;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 12px;
      padding: 2px 9px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--bg-muted);
      color: var(--text-dim);
      font-weight: 500;
    }
    .tag-live {
      border-color: rgba(16, 185, 129, 0.35);
      background: var(--green-soft);
      color: var(--green);
    }
    .tag-paused {
      border-color: rgba(245, 158, 11, 0.35);
      background: var(--yellow-soft);
      color: var(--yellow);
    }
    .tag-err {
      border-color: rgba(244, 63, 94, 0.4);
      background: var(--red-soft);
      color: var(--red);
    }
    .dot-pulse {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
      display: inline-block;
      box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.65);
      animation: pulse 1.8s infinite;
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.65); }
      70% { box-shadow: 0 0 0 7px rgba(16, 185, 129, 0); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .btn {
      appearance: none;
      border: 1px solid var(--border-strong);
      background: var(--bg-muted);
      color: var(--text);
      border-radius: 8px;
      padding: 7px 12px;
      font-size: 12.5px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: border-color 0.15s, background 0.15s, transform 0.1s;
    }
    .btn:hover { border-color: var(--accent); background: var(--accent-soft); }
    .btn:active { transform: translateY(1px); }
    .btn-primary {
      border-color: rgba(56, 189, 248, 0.4);
      background: var(--accent-soft);
      color: var(--accent);
    }
    .btn-xs { padding: 3px 8px; font-size: 11.5px; border-radius: 6px; }

    /* KPI grid */
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .kpi {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 13px 15px;
      box-shadow: var(--shadow);
    }
    .kpi.warn {
      border-color: rgba(251, 146, 60, 0.45);
      background: linear-gradient(180deg, var(--orange-soft), var(--bg-card));
    }
    .kpi-label { font-size: 12px; color: var(--text-dim); }
    .kpi-value { font-size: 25px; font-weight: 700; margin-top: 2px; line-height: 1.2; }
    .kpi-sub { font-size: 12px; color: var(--text-faint); margin-top: 4px; }

    /* Filter toolbar */
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 14px;
      padding: 11px 14px;
      background: var(--bg-elev);
      border: 1px solid var(--border);
      border-radius: var(--radius);
    }
    .pills {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .pill {
      border: 1px solid var(--border);
      background: var(--bg-muted);
      color: var(--text-dim);
      padding: 5px 11px;
      border-radius: 999px;
      font-size: 12.5px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .pill.active {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: var(--text);
      font-weight: 600;
    }
    .toolbar-right {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }
    .search-box {
      border: 1px solid var(--border-strong);
      background: var(--bg);
      color: var(--text);
      border-radius: 8px;
      padding: 6px 11px;
      font-size: 12.5px;
      min-width: 220px;
      outline: none;
    }
    .search-box:focus { border-color: var(--accent); }
    .toggle-label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12.5px;
      color: var(--text-dim);
      cursor: pointer;
      user-select: none;
    }
    .seg {
      display: inline-flex;
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      overflow: hidden;
    }
    .seg button {
      border: 0;
      background: var(--bg-muted);
      color: var(--text-dim);
      padding: 6px 11px;
      font-size: 12.5px;
      cursor: pointer;
    }
    .seg button.active {
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 600;
    }

    /* Kanban */
    .kanban {
      display: grid;
      grid-template-columns: repeat(4, minmax(260px, 1fr));
      gap: 14px;
      margin-top: 14px;
      align-items: start;
    }
    @media (max-width: 1180px) {
      .kanban { grid-template-columns: repeat(2, minmax(260px, 1fr)); }
    }
    @media (max-width: 680px) {
      .kanban { grid-template-columns: 1fr; }
    }
    .column {
      background: var(--bg-elev);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px;
      min-height: 220px;
    }
    .col-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 13px;
      font-weight: 700;
      padding-bottom: 10px;
      margin-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }
    .col-count {
      font-size: 12px;
      padding: 1px 8px;
      border-radius: 999px;
      background: var(--bg-muted);
      color: var(--text-dim);
    }
    .card-stack {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    /* Cards */
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 13px;
      box-shadow: var(--shadow);
      transition: border-color 0.15s;
    }
    .card:hover { border-color: var(--border-strong); }
    .card.is-stalled {
      border-color: rgba(251, 146, 60, 0.55);
    }
    .card.is-fail {
      border-color: rgba(244, 63, 94, 0.55);
    }
    .card-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
    }
    .card-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
      font-size: 11.5px;
      color: var(--text-dim);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 1px 7px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      border: 1px solid var(--border);
      background: var(--bg-muted);
      color: var(--text-dim);
    }
    .badge-github { color: #93c5fd; border-color: rgba(147, 197, 253, 0.28); }
    .badge-gitlab { color: #fdba74; border-color: rgba(253, 186, 116, 0.28); }
    .badge-stage { background: var(--accent-soft); color: var(--accent); border-color: rgba(56, 189, 248, 0.3); }
    .badge-fail { background: var(--red-soft); color: var(--red); border-color: rgba(244, 63, 94, 0.35); }
    .badge-pass { background: var(--green-soft); color: var(--green); border-color: rgba(16, 185, 129, 0.35); }
    .badge-pending { background: var(--yellow-soft); color: var(--yellow); border-color: rgba(245, 158, 11, 0.35); }
    .badge-op { background: var(--purple-soft); color: var(--purple); border-color: rgba(167, 139, 250, 0.4); }

    .card-title {
      margin: 6px 0 4px;
      font-size: 14px;
      font-weight: 650;
      word-break: break-word;
    }
    .branch-line {
      font-family: var(--mono);
      font-size: 11.5px;
      color: var(--text-dim);
      word-break: break-all;
      margin-bottom: 6px;
    }

    .pulse-box {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      font-size: 12px;
      padding: 6px 9px;
      border-radius: 7px;
      background: var(--bg-muted);
      border: 1px solid var(--border);
      margin-top: 6px;
    }
    .pulse-active { border-color: rgba(16, 185, 129, 0.35); background: var(--green-soft); }
    .pulse-stalled { border-color: rgba(251, 146, 60, 0.45); background: var(--orange-soft); color: var(--orange); }

    .stalled-alert {
      margin-top: 6px;
      font-size: 11.5px;
      padding: 5px 8px;
      border-radius: 6px;
      background: var(--orange-soft);
      color: var(--orange);
      border: 1px solid rgba(251, 146, 60, 0.35);
    }

    .cur-task {
      margin-top: 7px;
      font-size: 12px;
      color: var(--text);
      background: var(--bg-muted);
      border-left: 3px solid var(--accent);
      padding: 5px 8px;
      border-radius: 0 6px 6px 0;
    }

    .progress-wrap {
      margin-top: 8px;
    }
    .progress-label {
      display: flex;
      justify-content: space-between;
      font-size: 11.5px;
      color: var(--text-dim);
      margin-bottom: 3px;
    }
    .progress-track {
      height: 6px;
      border-radius: 999px;
      background: var(--bg-muted);
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--green));
      border-radius: 999px;
      transition: width 0.25s ease;
    }

    .commit-line {
      margin-top: 7px;
      font-size: 11.5px;
      color: var(--text-dim);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .card-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--border);
    }

    .drawer {
      margin-top: 8px;
      padding: 8px 10px;
      border-radius: 7px;
      background: var(--bg);
      border: 1px solid var(--border);
      font-size: 12px;
    }
    .task-item {
      display: flex;
      align-items: flex-start;
      gap: 6px;
      padding: 3px 0;
    }
    .file-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-family: var(--mono);
      font-size: 11.5px;
      padding: 2px 0;
      word-break: break-all;
    }
    .file-code {
      min-width: 22px;
      text-align: center;
      font-weight: 700;
      color: var(--accent);
    }

    /* Repo list view */
    .repo-section {
      margin-top: 14px;
      background: var(--bg-elev);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
    }
    .repo-hdr {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }
    .repo-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 12px;
    }

    .empty-state {
      text-align: center;
      padding: 46px 20px;
      background: var(--bg-elev);
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius);
      margin-top: 16px;
      color: var(--text-dim);
    }

    .warnings-box {
      margin-top: 14px;
      padding: 10px 14px;
      border-radius: var(--radius);
      border: 1px solid rgba(245, 158, 11, 0.35);
      background: var(--yellow-soft);
      color: var(--yellow);
      font-size: 12.5px;
    }

    .footer {
      margin-top: 18px;
      font-size: 12px;
      color: var(--text-faint);
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header class="topbar">
      <div class="brand">
        <div class="logo">IDD</div>
        <h1>IDD 实时开发监控看板</h1>
        <span id="scope-tag" class="tag">全局仓库</span>
        <span id="conn-tag" class="tag tag-live"><span class="dot-pulse"></span>2s 自动刷新</span>
        <span id="updated-tag" class="tag">同步中...</span>
      </div>
      <div class="controls">
        <button id="pause-btn" class="btn" type="button">⏸ 暂停刷新</button>
        <button id="sync-btn" class="btn btn-primary" type="button">🔄 立即同步远端</button>
        <button id="theme-btn" class="btn" type="button">☀️ 浅色</button>
      </div>
    </header>

    <section id="kpis" class="kpis"></section>

    <section class="toolbar">
      <div id="repo-pills" class="pills"></div>
      <div class="toolbar-right">
        <label class="toggle-label">
          <input id="wt-only-cb" type="checkbox" />
          仅看已有 Worktree 的任务
        </label>
        <input id="search-input" class="search-box" type="search" placeholder="搜索 #Issue、标题、分支、TASK..." />
        <div class="seg" role="tablist" aria-label="视图切换">
          <button id="view-kanban" class="active" type="button">阶段看板</button>
          <button id="view-repos" type="button">仓库视图</button>
        </div>
      </div>
    </section>

    <main id="main-content"></main>
    <div id="warnings-wrap"></div>
    <footer id="footer" class="footer"></footer>
  </div>

  <script>
    (function () {
      const state = {
        snapshot: null,
        selectedRepo: "ALL",
        viewMode: "kanban",
        search: "",
        worktreeOnly: false,
        paused: false,
        expandedDrawers: new Set(),
        copiedMap: new Map(),
        timerId: null,
        fetching: false,
      };

      const savedTheme = localStorage.getItem("idd_board_theme") || "dark";
      applyTheme(savedTheme);

      function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        const btn = document.getElementById("theme-btn");
        if (btn) btn.textContent = theme === "dark" ? "☀️ 浅色" : "🌙 深色";
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

      async function copyText(text, key) {
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
          state.copiedMap.set(key, Date.now() + 1800);
          renderAll();
          setTimeout(() => renderAll(), 1900);
        } catch (err) {
          console.error("Copy failed", err);
        }
      }

      function isCopied(key) {
        const exp = state.copiedMap.get(key) || 0;
        return Date.now() < exp;
      }

      function updateConnectionBadge(ok, errorMsg) {
        const tag = document.getElementById("conn-tag");
        if (!tag) return;
        if (!ok) {
          tag.className = "tag tag-err";
          tag.textContent = errorMsg || "连接中断，等待重试";
          return;
        }
        if (state.paused) {
          tag.className = "tag tag-paused";
          tag.textContent = "⏸ 已暂停刷新";
          return;
        }
        tag.className = "tag tag-live";
        tag.innerHTML = '<span class="dot-pulse"></span>2s 自动刷新';
      }

      async function fetchSnapshot(forceRefresh = false) {
        if (state.fetching && !forceRefresh) return;
        state.fetching = true;
        try {
          const url = forceRefresh ? "/api/snapshot?refresh=1" : "/api/snapshot";
          const res = await fetch(url, { cache: "no-store" });
          if (!res.ok) throw new Error("HTTP " + res.status);
          state.snapshot = await res.json();
          updateConnectionBadge(true);
          renderAll();
        } catch (err) {
          updateConnectionBadge(false, "连接异常: " + err.message);
        } finally {
          state.fetching = false;
        }
      }

      function toggleDrawer(key) {
        if (state.expandedDrawers.has(key)) {
          state.expandedDrawers.delete(key);
        } else {
          state.expandedDrawers.add(key);
        }
        renderMain();
      }

      function cardBucket(item) {
        if (item._kind === "local") return "developing";
        if (item._kind === "orphan") {
          return item.checks_overall === "FAIL" || item.checks_overall === "PENDING" || item.isDraft
            ? "review"
            : "ready";
        }
        const st = item.stage || "";
        if (st === "⚪ 待认领") return "todo";
        if (st === "🔵 待合入") return "ready";
        if (st === "🛠️ 修 CI" || st === "⏳ CI 运行中" || st.startsWith("📝 草稿")) return "review";
        return "developing";
      }

      function matchesFilters(item) {
        if (state.selectedRepo !== "ALL" && item.repo_path !== state.selectedRepo) {
          return false;
        }
        if (state.worktreeOnly && !item.worktree) {
          return false;
        }
        const q = state.search.trim().toLowerCase();
        if (!q) return true;
        const hay = [
          item.repo_name,
          item.issue_number != null ? "#" + item.issue_number : "",
          item.title,
          item.issue,
          item.branch,
          item.current_task,
          item.stage,
        ].join(" ").toLowerCase();
        return hay.includes(q);
      }

      function collectItems() {
        const snap = state.snapshot;
        if (!snap) return [];
        const list = [];
        for (const row of snap.issues || []) {
          list.push(Object.assign({ _kind: "issue", _key: row.repo_path + "#issue#" + row.issue_number }, row));
        }
        for (const loc of snap.local_only_items || []) {
          list.push(Object.assign({
            _kind: "local",
            _key: loc.repo_path + "#local#" + loc.issue + "#" + (loc.worktree || ""),
            title: loc.issue,
            stage: "🟡 本地开发",
            task_progress: loc.done + " / " + loc.total,
            forge_type: "local",
          }, loc));
        }
        for (const orph of snap.orphan_changes || []) {
          list.push(Object.assign({
            _kind: "orphan",
            _key: orph.repo_path + "#orphan#" + orph.number,
            branch: orph.headRefName || "",
            stage: orph.checks_overall === "FAIL" ? "🛠️ 修 CI" : (orph.isDraft ? "📝 草稿" : "🔵 PR/MR"),
            task_progress: "—",
            change: orph,
            change_summary: orph.change_summary || "",
          }, orph));
        }
        return list.filter(matchesFilters);
      }

      function renderKpis(snap) {
        const s = snap.summary || {};
        const anomalies = (s.stalled_worktrees || 0) + (s.ci_failed_count || 0);
        const cards = [
          { label: "已接入活跃仓库", value: s.repo_count || 0, sub: "自动注册 · 失效自动剔除", warn: false },
          { label: "活跃 Worktree", value: s.active_worktrees || 0, sub: "🟢 刚刚活跃: " + (s.coding_now_count || 0), warn: false },
          { label: "进行中 TASK", value: s.in_progress_tasks || 0, sub: "✏️ 含未提交改动 Worktree: " + (s.dirty_worktrees || 0), warn: false },
          { label: "待合入 PR / MR", value: s.ready_to_land_count || 0, sub: "Open PR / MR 总数: " + (s.open_changes || 0), warn: false },
          {
            label: "需要关注 / 异常",
            value: anomalies,
            sub: "🟠 疑似卡住 " + (s.stalled_worktrees || 0) + " · ❌ CI 失败 " + (s.ci_failed_count || 0),
            warn: anomalies > 0,
          },
        ];
        document.getElementById("kpis").innerHTML = cards.map((c) => `
          <div class="kpi ${c.warn ? "warn" : ""}">
            <div class="kpi-label">${escapeHtml(c.label)}</div>
            <div class="kpi-value">${c.value}</div>
            <div class="kpi-sub">${escapeHtml(c.sub)}</div>
          </div>
        `).join("");
      }

      function renderRepoPills(snap) {
        const repos = snap.repos || [];
        const totalItems = (snap.issues || []).length + (snap.local_only_items || []).length;
        const parts = [
          `<button class="pill ${state.selectedRepo === "ALL" ? "active" : ""}" data-repo="ALL" type="button">全部仓库 <span class="col-count">${totalItems}</span></button>`
        ];
        for (const r of repos) {
          const cnt = (r.issues || []).length + (r.local_only_items || []).length;
          const activeWt = (r.issues || []).filter((x) => x.worktree).length + (r.local_only_items || []).length;
          const forgeLabel = r.forge === "github" ? "GitHub" : (r.forge === "gitlab" ? "GitLab" : "Local");
          const isAct = state.selectedRepo === r.repo_path;
          parts.push(
            `<button class="pill ${isAct ? "active" : ""}" data-repo="${escapeHtml(r.repo_path)}" type="button">` +
            `<span>${escapeHtml(r.repo_name)}</span>` +
            `<span class="badge">${escapeHtml(forgeLabel)}</span>` +
            `<span class="col-count">${activeWt}/${cnt}</span>` +
            `</button>`
          );
        }
        const el = document.getElementById("repo-pills");
        el.innerHTML = parts.join("");
        el.querySelectorAll("button[data-repo]").forEach((btn) => {
          btn.addEventListener("click", () => {
            state.selectedRepo = btn.getAttribute("data-repo") || "ALL";
            renderAll();
          });
        });
      }

      function renderCard(item) {
        const pulse = item.pulse || null;
        const isStalled = pulse && pulse.activity_state === "stalled";
        const isFail = item.stage === "🛠️ 修 CI" || (item.change && item.change.checks_overall === "FAIL");
        const cardCls = ["card", isStalled ? "is-stalled" : "", isFail ? "is-fail" : ""].filter(Boolean).join(" ");
        const issueHref = safeUrl(item.url);
        const changeUrl = item.change ? safeUrl(item.change.url) : "";
        const forgeTag = item.forge_type === "github" ? "badge-github" : (item.forge_type === "gitlab" ? "badge-gitlab" : "");
        const forgeText = item.forge_type === "github" ? "GitHub" : (item.forge_type === "gitlab" ? "GitLab" : "Local");

        const idChip = item._kind === "issue"
          ? (issueHref
              ? `<a href="${escapeHtml(issueHref)}" target="_blank" rel="noopener noreferrer">#${item.issue_number}</a>`
              : `<span>#${item.issue_number}</span>`)
          : (item._kind === "orphan"
              ? `<span>${escapeHtml((item.mr_label || "PR") + " " + (item.mr_prefix || "#") + item.number)}</span>`
              : `<span>[本地]</span>`);

        const stageClass = isFail ? "badge-fail" : (item.stage === "🔵 待合入" ? "badge-pass" : (item.stage === "⏳ CI 运行中" ? "badge-pending" : "badge-stage"));

        let pulseHtml = "";
        if (pulse) {
          const pCls = pulse.activity_state === "active" ? "pulse-box pulse-active" : (isStalled ? "pulse-box pulse-stalled" : "pulse-box");
          const opBadge = pulse.git_op ? `<span class="badge badge-op">${escapeHtml(pulse.git_op.toUpperCase())}</span>` : "";
          pulseHtml = `
            <div class="${pCls}">
              <span>${escapeHtml(pulse.pulse_summary)}</span>
              ${opBadge}
            </div>
          `;
          if (isStalled) {
            pulseHtml += `<div class="stalled-alert">⚠️ 超过 30 分钟无新写入或提交，可能卡在权限确认或等待人工决策</div>`;
          }
        }

        let curTaskHtml = "";
        if (item.current_task) {
          curTaskHtml = `<div class="cur-task">▶ ${escapeHtml(item.current_task)}</div>`;
        } else if (item.worktree && (item.tasks || []).length === 0) {
          curTaskHtml = `<div class="cur-task">🧭 已建 Worktree，待拆解 TASK/</div>`;
        }

        let progressHtml = "";
        const tasks = item.tasks || [];
        if (tasks.length > 0 || item.worktree) {
          const total = tasks.length || (item.counts ? Object.values(item.counts).reduce((a, b) => a + b, 0) : 0);
          const done = tasks.filter((t) => t.status === "done").length;
          const pct = total > 0 ? Math.round((done / total) * 100) : 0;
          progressHtml = `
            <div class="progress-wrap">
              <div class="progress-label">
                <span>TASK 进度</span>
                <span>${done} / ${total} (${pct}%)</span>
              </div>
              <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
            </div>
          `;
        }

        let changeHtml = "";
        if (item.change_summary && item.change_summary !== "—") {
          changeHtml = changeUrl
            ? `<div style="margin-top:6px;font-size:12px;"><a href="${escapeHtml(changeUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.change_summary)}</a></div>`
            : `<div style="margin-top:6px;font-size:12px;color:var(--text-dim);">${escapeHtml(item.change_summary)}</div>`;
        }

        let commitHtml = "";
        if (pulse && pulse.last_commit_sha) {
          commitHtml = `<div class="commit-line" title="${escapeHtml(pulse.last_commit_subject)}">最近提交 <code>${escapeHtml(pulse.last_commit_sha)}</code> · ${escapeHtml(pulse.last_commit_subject || "")}</div>`;
        }

        const taskKey = "tasks:" + item._key;
        const filesKey = "files:" + item._key;
        const showTasks = state.expandedDrawers.has(taskKey);
        const showFiles = state.expandedDrawers.has(filesKey);

        const targetArg = item.issue_number != null ? String(item.issue_number) : (item.issue || item.issue_dir || "");
        const startCmd = targetArg ? `cd ${item.repo_path} && idd start ${targetArg}` : "";
        const startBtnKey = "start:" + item._key;
        const wtBtnKey = "wt:" + item._key;

        const actionBtns = [];
        if (tasks.length > 0) {
          actionBtns.push(`<button class="btn btn-xs" data-toggle="${escapeHtml(taskKey)}" type="button">${showTasks ? "收起 TASK" : `查看 TASK (${tasks.length})`}</button>`);
        }
        if (pulse && (pulse.changed_files || []).length > 0) {
          actionBtns.push(`<button class="btn btn-xs" data-toggle="${escapeHtml(filesKey)}" type="button">${showFiles ? "收起改动文件" : `改动文件 (${pulse.dirty_count})`}</button>`);
        }
        if (item.worktree) {
          actionBtns.push(`<button class="btn btn-xs" data-copy-key="${escapeHtml(wtBtnKey)}" data-copy-val="${escapeHtml(item.worktree)}" type="button">${isCopied(wtBtnKey) ? "✓ 已复制路径" : "📁 复制路径"}</button>`);
        }
        if (startCmd) {
          actionBtns.push(`<button class="btn btn-xs" data-copy-key="${escapeHtml(startBtnKey)}" data-copy-val="${escapeHtml(startCmd)}" type="button">${isCopied(startBtnKey) ? "✓ 已复制命令" : "📋 接手命令"}</button>`);
        }

        let drawersHtml = "";
        if (showTasks && tasks.length > 0) {
          const rows = tasks.map((t) => {
            const icon = t.status === "done" ? "✅" : (t.status === "in_progress" ? "🔵" : (t.status === "blocked" ? "⛔" : "⬜"));
            return `<div class="task-item"><span>${icon}</span><div><strong>${escapeHtml(t.title)}</strong> <span class="badge">${escapeHtml(t.status)}</span></div></div>`;
          }).join("");
          drawersHtml += `<div class="drawer">${rows}</div>`;
        }
        if (showFiles && pulse && (pulse.changed_files || []).length > 0) {
          const rows = pulse.changed_files.map((f) =>
            `<div class="file-item"><span class="file-code">${escapeHtml(f.code)}</span><span>${escapeHtml(f.path)}</span></div>`
          ).join("");
          const more = pulse.has_more_files ? `<div style="color:var(--text-faint);margin-top:4px;">... 还有更多文件</div>` : "";
          drawersHtml += `<div class="drawer">${rows}${more}</div>`;
        }

        return `
          <article class="${cardCls}">
            <div class="card-top">
              <div class="card-meta">
                <span class="badge ${forgeTag}">${escapeHtml(forgeText)}</span>
                <span>${escapeHtml(item.repo_name || "")}</span>
                <span>·</span>
                <strong>${idChip}</strong>
              </div>
              <span class="badge ${stageClass}">${escapeHtml(item.stage || "—")}</span>
            </div>
            <div class="card-title">${escapeHtml(item.title || item.issue || "未命名任务")}</div>
            ${item.branch ? `<div class="branch-line">🌿 ${escapeHtml(item.branch)}</div>` : ""}
            ${pulseHtml}
            ${curTaskHtml}
            ${progressHtml}
            ${changeHtml}
            ${commitHtml}
            ${actionBtns.length ? `<div class="card-actions">${actionBtns.join("")}</div>` : ""}
            ${drawersHtml}
          </article>
        `;
      }

      function bindCardEvents(container) {
        container.querySelectorAll("button[data-toggle]").forEach((btn) => {
          btn.addEventListener("click", () => toggleDrawer(btn.getAttribute("data-toggle")));
        });
        container.querySelectorAll("button[data-copy-key]").forEach((btn) => {
          btn.addEventListener("click", () => {
            copyText(btn.getAttribute("data-copy-val") || "", btn.getAttribute("data-copy-key"));
          });
        });
      }

      function renderMain() {
        const snap = state.snapshot;
        const container = document.getElementById("main-content");
        if (!snap) return;

        const repos = snap.repos || [];
        if (repos.length === 0) {
          container.innerHTML = `
            <div class="empty-state">
              <h3 style="margin:0 0 8px;">暂无已纳管的 Git 仓库</h3>
              <p style="margin:0;">在任意项目目录执行一次 <code>idd start &lt;issue#&gt;</code>、<code>idd status</code> 或 <code>idd repos add .</code> 后，仓库会自动出现在全局看板。</p>
            </div>
          `;
          return;
        }

        const items = collectItems();
        if (items.length === 0) {
          container.innerHTML = `
            <div class="empty-state">
              <h3 style="margin:0 0 8px;">当前筛选条件下暂无任务</h3>
              <p style="margin:0;">可切换仓库过滤标签、清空搜索词或取消勾选「仅看已有 Worktree」。</p>
            </div>
          `;
          return;
        }

        if (state.viewMode === "kanban") {
          const buckets = {
            todo: { title: "⚪ 待认领 Backlog", items: [] },
            developing: { title: "🟡 开发中 / Worktree 推进", items: [] },
            review: { title: "⏳ PR·MR / 修 CI", items: [] },
            ready: { title: "🔵 待合入 main", items: [] },
          };
          for (const item of items) {
            buckets[cardBucket(item)].items.push(item);
          }
          container.innerHTML = `<div class="kanban">` + Object.values(buckets).map((col) => `
            <section class="column">
              <div class="col-hdr">
                <span>${escapeHtml(col.title)}</span>
                <span class="col-count">${col.items.length}</span>
              </div>
              <div class="card-stack">
                ${col.items.length ? col.items.map(renderCard).join("") : `<div style="color:var(--text-faint);font-size:12px;padding:10px 4px;">暂无条目</div>`}
              </div>
            </section>
          `).join("") + `</div>`;
        } else {
          const byRepo = new Map();
          for (const item of items) {
            const key = item.repo_path || item.repo_name || "unknown";
            if (!byRepo.has(key)) {
              byRepo.set(key, { name: item.repo_name || key, path: key, forge: item.forge_type || "local", items: [] });
            }
            byRepo.get(key).items.push(item);
          }
          container.innerHTML = Array.from(byRepo.values()).map((grp) => `
            <section class="repo-section">
              <div class="repo-hdr">
                <div>
                  <strong>📦 ${escapeHtml(grp.name)}</strong>
                  <span class="badge" style="margin-left:6px;">${escapeHtml(grp.forge.toUpperCase())}</span>
                  <div style="font-size:12px;color:var(--text-faint);font-family:var(--mono);margin-top:2px;">${escapeHtml(grp.path)}</div>
                </div>
                <span class="col-count">${grp.items.length} 项</span>
              </div>
              <div class="repo-grid">${grp.items.map(renderCard).join("")}</div>
            </section>
          `).join("");
        }

        bindCardEvents(container);
      }

      function renderAll() {
        const snap = state.snapshot;
        if (!snap) return;
        const scopeTag = document.getElementById("scope-tag");
        if (scopeTag) scopeTag.textContent = snap.global ? "全局跨仓库" : "单仓库视图";
        const updatedTag = document.getElementById("updated-tag");
        if (updatedTag) updatedTag.textContent = "更新于 " + formatClock(snap.generated_at);

        renderKpis(snap);
        renderRepoPills(snap);
        renderMain();

        const warns = snap.warnings || [];
        document.getElementById("warnings-wrap").innerHTML = warns.length
          ? `<div class="warnings-box"><strong>提示：</strong>${warns.map((w) => escapeHtml(w)).join(" ｜ ")}</div>`
          : "";

        const retainedCount = (snap.repos || []).reduce((acc, r) => acc + (r.retained_idle_worktrees || []).length, 0);
        const retainedText = retainedCount > 0 ? `已合入保留的干净工作树：${retainedCount} 个` : "所有保留工作树均已归位";
        document.getElementById("footer").innerHTML = `
          <span>仓库索引：<code>${escapeHtml(snap.repos_config_path || "~/.config/idd/repos.json")}</code></span>
          <span>${escapeHtml(retainedText)}</span>
        `;
      }

      document.getElementById("pause-btn").addEventListener("click", () => {
        state.paused = !state.paused;
        document.getElementById("pause-btn").textContent = state.paused ? "▶ 继续刷新" : "⏸ 暂停刷新";
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

      document.getElementById("wt-only-cb").addEventListener("change", (e) => {
        state.worktreeOnly = Boolean(e.target.checked);
        renderMain();
      });

      document.getElementById("search-input").addEventListener("input", (e) => {
        state.search = e.target.value || "";
        renderMain();
      });

      document.getElementById("view-kanban").addEventListener("click", () => {
        state.viewMode = "kanban";
        document.getElementById("view-kanban").classList.add("active");
        document.getElementById("view-repos").classList.remove("active");
        renderMain();
      });

      document.getElementById("view-repos").addEventListener("click", () => {
        state.viewMode = "repos";
        document.getElementById("view-repos").classList.add("active");
        document.getElementById("view-kanban").classList.remove("active");
        renderMain();
      });

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
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", BOARD_HTML.encode("utf-8"))
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
    version: str = "0.5.0",
) -> int:
    """Start the local IDD Web Dashboard server and open the browser unless disabled."""
    cache = monitor.ForgeSnapshotCache(ttl_seconds=forge_ttl)
    handler_cls = partial(
        BoardRequestHandler,
        cache=cache,
        root=root,
        global_mode=global_mode,
        local_only=local_only,
        version=version,
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
