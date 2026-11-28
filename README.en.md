<a id="readme-top"></a>

<div align="center">

# IDD

**Issue-Driven Development · Isolated Parallel Workflow & 1-Click Handoff for AI Coding Agents**

Run **Claude Code**, **Codex**, and **Antigravity** natively in parallel without stepping on each other's files—<br />
track every worktree on a zero-token frosted-glass radar and hand off context to any agent in one click.

[简体中文](README.md) · **English**

[![Version](https://img.shields.io/badge/version-v0.0.4-10b981?style=flat-square)](https://github.com/j-tide/idd/releases)
[![GitHub Stars](https://img.shields.io/github/stars/j-tide/idd?style=flat-square&logo=github&color=f59e0b)](https://github.com/j-tide/idd/stargazers)
[![CI](https://img.shields.io/github/actions/workflow/status/j-tide/idd/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/j-tide/idd/actions/workflows/ci.yml)
[![Forges](https://img.shields.io/badge/forges-GitHub%20%C2%B7%20Self--Hosted%20GitLab-fc6d26?style=flat-square)](#supported-ecosystem)
[![Agents](https://img.shields.io/badge/agents-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20Antigravity-38bdf8?style=flat-square)](#supported-ecosystem)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib)-8b5cf6?style=flat-square)](#development-testing--releases)

[Why IDD](#why-idd) · [Key Features](#key-features) · [How It Works](#how-it-works) · [Quick Start](#quick-start) · [Ecosystem](#supported-ecosystem) · [CLI Reference](#cli-reference--naming-conventions) · [Star History](#star-history)

</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/board-en-dark.png" />
    <source media="(prefers-color-scheme: light)" srcset="assets/board-en-light.png" />
    <img src="assets/board-en-dark.png" width="100%" alt="IDD frosted-glass live worktree radar and one-click cross-agent handoff console" />
  </picture>
  <br />
  <sub><em><code>idd board</code> local frosted-glass Web radar: By-Repo / Kanban / List views, 3-column Bento progress KPIs, 6 semantic filter chips, adaptive low-overhead pulse & CI checks—plus 1-click cross-agent handoff, safe per-card cleanup, and EN / 中文 switching.</em></sub>
</p>

---

## Why IDD

When you run multiple AI coding tools at once, two bottlenecks hit immediately: **agents collide in the same working directory**, and when one model stalls or hits a quota limit, **your progress and context stay trapped in that chat window**.

| Dimension | Ad-Hoc Multi-Window AI | Heavy Wrapper IDE / Orchestrator | **IDD** |
| :--- | :--- | :--- | :--- |
| **Native Experience** | Native windows, no extra lock-in | Forces a custom UI or wrapper | **Keep Claude Code, Codex, and Antigravity native** |
| **Parallel Isolation** | Shared directory, frequent conflicts | Proprietary sandboxes or containers | **Dedicated physical Git Worktree per Issue** |
| **Cross-Agent Handoff** | Manual copy-paste of chat history | Restricted to built-in model swaps | **On-disk `TASK/` ledger + 1-click Handoff prompt** |
| **Global Visibility** | Check chat tabs one by one | Extra daemon & token overhead | **Zero-token frosted-glass Web radar (adaptive polling) & terminal watch** |
| **Git & Merge Hygiene** | Messy merge commits or `main` edits | Local-only or platform-locked state | **GitHub & GitLab native, CI self-healing, linear Squash to `main`** |
| **Dependencies & Footprint** | None | Heavy runtime & configuration | **0 dependencies (Python 3 stdlib + sh), zero Git hooks** |

IDD connects three lightweight pieces into a single loop that you drive with natural language:

- **Shared Agent Skill (`SKILL.md`)**: Teaches Claude Code, Codex, and Antigravity the same plan-first gate and delivery discipline—inspect read-only and confirm a plan first (with visual prototypes for UI/output changes), anchor scope to a GitHub / GitLab **Issue**, develop inside an isolated **Git Worktree**, and track steps in `TASK/<issue>/`.
- **Zero-Token Frosted-Glass Radar & Handoff Console (`idd board`)**: Defaults to a repo-grouped view across all local projects with 3-column Bento progress KPIs, PR/MR CI checks, and cleanable directories; click any card to open the inspector drawer, or click **Handoff** anytime to resume seamlessly in another agent window.
- **Deterministic Under-the-Hood CLI (`idd`)**: Invoked automatically by agents to handle worktree creation, `.env` (`.worktreeinclude`) syncing, 8-prefix branch validation, structured PR/MR summaries, CI log inspection, and plain-text linear **Squash merges**.

---

## Key Features

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>Plan-First Gate · Physical Worktree Parallelism</h3>
      Enforces a strict plan-confirmation gate before creating Issues or editing code. For UI/UX changes, preview interactive HTML prototypes via <code>idd preview</code> (hot reload, side-by-side A/B comparison, desktop/tablet/mobile viewports) without polluting your repo. Each Issue gets an isolated directory at <code>../&lt;repo&gt;-worktrees/&lt;id&gt;-&lt;slug&gt;</code>, a <code>--no-track</code> branch pushed immediately to <code>origin</code>, and auto-synced <code>.env</code> files via <code>.worktreeinclude</code>.
    </td>
    <td width="50%" valign="top">
      <h3>Frosted-Glass Radar · Multi-View & 1-Click Handoff</h3>
      <code>idd board</code> features a collapsible frosted-glass sidebar and unified 2-row topbar: switch between <strong>By Repo (default) / Kanban / Compact List</strong> views, track <strong>3-column segmented Bento KPIs</strong>, and filter via <strong>6 semantic chips</strong> (All Active / In Worktree / Attention / Ready / Queued / Cleanable). Click any card for a slide-over inspector drawer, configure tokens in-browser, toggle EN / 中文 & Dark / Light, and copy handoff prompts, paths, or branches in one click.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>Low-Overhead Engine · Zero-Flicker Motion</h3>
      Shows layout skeletons only on initial load and updates via <strong>in-place DOM reconciliation & FLIP card motion</strong>, consolidating sync status into the topbar with zero layout jump. Automatically pauses polling in background tabs, backs off serially between <code>1.2s–15s</code>, and pairs <code>porcelain v2</code> scanning with a 30s idle signature cache and server-side singleflight coalescing.
    </td>
    <td width="50%" valign="top">
      <h3>Global Auto-Merge · 2-Round CI Self-Healing</h3>
      Unifies <code>auto_merge</code> into a single global switch read live by <code>idd pr</code> / <code>idd mr</code>—toggleable via CLI (<code>idd config auto-merge on|off</code>) or the board topbar with a confirmation dialog. Guards against premature ready-to-land status when tasks or local edits remain unfinished, caps CI log fixes at 2 targeted rounds, and auto-pauses safely on Drafts, conflicts, or <code>evidence/</code> attachments.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>Dual-Format Delivery · Linear Squash History</h3>
      <code>idd pr</code> / <code>idd mr</code> generates structured Markdown (<code>## 变更内容</code> bullets + <code>## 验证记录</code> table with compact command labels and collapsible full commands). <code>idd land</code> rebases onto <code>main</code>, removes <code>TASK/&lt;issue&gt;/</code>, writes a <strong>zero-Markdown compact plain-text</strong> body into the Squash commit (no blank lines inside a <code>TASK</code> block), merges linearly, and checks off Issue acceptance boxes.
    </td>
    <td width="50%" valign="top">
      <h3>1-Click Safe Cleanup · Dual-Forge, Zero Deps</h3>
      Clean up merged worktrees one card at a time with confirmation streaming right inside the <code>idd board</code> bottom drawer (or via <code>idd cleanup</code>), strictly verifying a clean tree and <code>HEAD == headRefOid</code> while <strong>never deleting branches</strong>. Pure Python 3 stdlib + POSIX <code>sh</code>, native GitHub / GHE / Self-Hosted GitLab support, zero Git hooks, and safe 6-hour background upgrades.
    </td>
  </tr>
</table>

---

## How It Works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/workflow-en-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="assets/workflow-en-light.svg" />
    <img src="assets/workflow-en-light.svg" width="100%" alt="IDD parallel native agents, isolated issue worktrees, and board handoff loop" />
  </picture>
</p>

1. **Confirm the plan first, then anchor an Issue**: Discuss scope in any agent window, inspect read-only, and align on a concise plan (reviewing an interactive HTML prototype via `idd preview` / Artifact or Before-After sample when UI or output changes). **Only after explicit user confirmation** does the agent run `idd issue create`—neither the Issue nor the working tree is touched beforehand.
2. **Run multiple agents in isolated worktrees**: Tell **Claude Code** *"Start #115"* while **Codex** runs *"Start #51"*. Each task enters its own physical worktree, gets `.env` synced, pushes its branch immediately, and maintains its own `TASK/<issue>/` ledger.
3. **Monitor on `idd board` & hand off in one click**: Track live pulses, 3-column Bento KPIs, and CI checks across repos (press `[` to collapse sidebar, `/` to search, `r` to sync, or click any card for the inspector drawer). Need to switch tools? Click **Handoff** and paste into **Antigravity** or any other agent to continue straight from `TASK/`.
4. **Land a single linear commit onto `main` & clean up safely**: Say *"Land #115"* (or enable global **PR Auto-Approve** so green PRs/MRs land automatically). `idd land` removes `TASK/`, writes a clean plain-text Squash commit, and checks off acceptance criteria; clean up retained worktrees anytime from the board drawer or `idd cleanup`.

```text
~/code/
├── my-app/                                  # Main repo (stays clean on main)
└── my-app-worktrees/                        # Isolated parallel worktrees managed by IDD
    ├── 115-export-csv/                      # ← Claude Code working on feat/115-export-csv
    │   ├── .env                             #   Synced from .worktreeinclude
    │   └── TASK/115-export-csv/             #   On-disk task ledger (cleaned before Squash merge)
    │       ├── TASK-01-csv-serializer.md    #   Status: done
    │       └── TASK-02-stream-endpoint.md   #   Status: in_progress
    └── 51-fix-dark-flicker/                 # ← Codex working concurrently on fix/51-fix-dark-flicker
        └── TASK/51-fix-dark-flicker/
```

---

## Quick Start

Prerequisites: `git` and `python3` installed locally.

### 1. Install the shared skill & global `idd` CLI

```bash
curl -fsSL https://raw.githubusercontent.com/j-tide/idd/main/install.sh | sh
```

### 2. Launch the local board & connect your forge

```bash
idd board
```

> On first launch, `idd board` opens a browser setup wizard where you can generate and paste a GitHub or self-hosted GitLab token directly—no CLI login command required—and optionally enable automatic linear merge policy initialization.

### 3. Drive everything with natural language in any agent

| Stage | Say to your Agent | Under-the-hood Action |
| :--- | :--- | :--- |
| **Align & open Issue** | *"Propose a plan/prototype first, then open an IDD Issue after sign-off"* | Plan / `idd preview` → confirm → `idd issue create` |
| **Parallel execution** | *"Start #115"* (and *"Start #51"* in another window) | `idd start` creates worktree & pushes branch |
| **Switch agents anytime** | Click **Handoff** in `idd board` and paste into another agent | `idd start` reuses worktree & resumes `TASK/` |
| **Review & land** | *"Open a PR"* / *"Land #115"* | `idd pr` → `idd ci --watch` → `idd land` |

> [!TIP]
> On first contact with a repository, `idd start` / `idd issue create` / `idd repos add` automatically probes and applies `idd repo-init --apply` (Squash-only with `PR_TITLE`/`PR_BODY` on GitHub, or `ff` + `always` squash on GitLab while preserving branches); if skipped or lacking permissions, click retry directly in `idd board`. Want CI-green PRs/MRs to merge automatically? Run `idd config auto-merge on` or toggle it in the `idd board` top bar.

> [!NOTE]
> `idd` safely checks `origin/main` in the background every 6 hours and fast-forwards only when your local skill clone is on a clean `main` branch (or run `idd upgrade [--check]` anytime). To uninstall cleanly without touching any project repository, run `idd uninstall` (or `curl -fsSL https://raw.githubusercontent.com/j-tide/idd/main/install.sh | sh -s -- --uninstall -y`).

<details>
<summary><strong>Optional: Set IDD as Your Default Workflow</strong> (Global User Rules / Project <code>AGENTS.md</code> templates — installer never writes these automatically)</summary>

`install.sh` only symlinks the shared Skill and `idd` CLI, and `idd repo-init` only configures remote merge rules—**neither creates or edits any global rules or project `AGENTS.md` automatically**. If you want IDD active by default, copy one of the snippets below:

### Option 1: Personal Global Default (Recommended — keeps project repos untouched)

Add this snippet to your agent's user-level global instructions:

- **Claude Code**: `~/.claude/CLAUDE.md`
- **Codex**: `~/.codex/AGENTS.md`
- **Antigravity**: Global User Rules (`~/.gemini/GEMINI.md` or User Rules settings)

```markdown
# Global Development Workflow (IDD)

Default to the global `idd` skill (`~/.agents/skills/idd/SKILL.md`) for all non-read-only code, config, and documentation tasks.

- **Confirm plan first, then Issue & worktree**: Unless continuing an existing Issue with clear acceptance criteria or explicitly authorized to skip confirmation this turn, all new requests and changes (including bug fixes, refactors, config, and docs) must first inspect read-only and present a concise plan (plus a prototype or Before/After sample for UI/UX/output changes). **Wait for explicit user confirmation** before running `idd issue create` (never auto-create an Issue or edit code in the same turn) and then `idd start <issue#>` to create or reuse an isolated worktree and `<type>/<id>-<slug>` branch pushed to `origin` (never edit directly on `main`).
- **Per-TASK verification & immediate push**: Break work down under `TASK/<issue>/TASK-XX-*.md` with test mappings, verify with real tests, commit per task, and push right away via `idd sync` (or `git push -u origin HEAD`).
- **PR/MR, CI & linear merge**: Run `idd pr` / `idd mr` and `idd ci --watch`; once approved (or when `auto_merge` is enabled), run `idd land` to clean `TASK/<issue>/` and Squash-merge linearly onto `main`.
- **Safety boundaries**: Use the unnumbered `<slug>` flow only in local-only repos without remotes; protect uncommitted edits and never force-push or merge into `main`, deploy, or touch production without authorization.
```

### Option 2: Project-Level Enforcement (Shared with collaborators)

To enforce IDD across all contributors in a repository, add the snippet below to the repository's root `AGENTS.md` (and put `@AGENTS.md` in `CLAUDE.md` if teammates use Claude Code), optionally paired with `idd repo-init --apply` and remote `main` branch protection:

```markdown
# Repository Workflow (IDD)

This repository uses the `idd` skill (Issue-Driven Development) for all changes:
- Unless continuing an existing Issue with clear acceptance criteria or explicitly authorized to skip confirmation, present a concise plan (including bug fixes) and **wait for explicit user confirmation** before creating an Issue with `idd issue create`, then develop in an isolated worktree and `<type>/<id>-<slug>` branch via `idd start <issue#>`—never commit directly to `main`.
- Track steps and real test results under `TASK/<issue>/`; commit per task and push with `idd sync`.
- Open a PR/MR via `idd pr` / `idd mr`, wait for green CI, and land with `idd land` to remove temporary `TASK/` files and Squash-merge onto `main`.
```

</details>

---

## Supported Ecosystem

| Category | Supported Target | Integration & Capabilities |
| :--- | :--- | :--- |
| **AI Agents** | **Claude Code** | Symlinked to `~/.claude/skills/idd` |
| **AI Agents** | **Codex** | Symlinked to `~/.codex/skills/idd` |
| **AI Agents** | **Antigravity** | Symlinked to `~/.gemini/config/skills/idd` |
| **Git Forges** | **GitHub / GitHub Enterprise** | Native Issue progress bars, structured PR summaries, Actions CI logs, linear `Squash` merges |
| **Git Forges** | **Self-Hosted GitLab** | Native Issue progress bars, structured MR summaries, Pipeline logs, `ff` + `squash` linear merges |

---

## CLI Reference & Naming Conventions

<details>
<summary><strong>Expand full CLI command table, 8 standard prefixes & zero-hook guardrails</strong> (mostly invoked by Agents, or runnable manually)</summary>

### Common Commands

| Command | Description |
| :--- | :--- |
| `idd board` / `idd ui [--current-only] [--local-only] [--port ...]` | Start the frosted-glass Web radar & 1-click handoff board (multi-view, adaptive polling, per-card cleanup, bilingual 中文 / EN) |
| `idd preview <target>... [--compare] [--title "..."] [--port ...]` | Launch the local prototype preview workbench (hot reload, side-by-side A/B compare, and responsive viewports) |
| `idd watch [--current-only] [--open-only] [--once]` | Live terminal monitor for global or single-repo worktrees, tasks, and CI |
| `idd status [-g\|--global] [--open-only] [--local-only] [--json]` | One-shot terminal summary of Open Issues, `TASK` progress, pulse, and PR/MR CI |
| `idd repos [list\|add\|remove\|prune] [--json]` | Inspect or manage the global monitored repository index (`~/.config/idd/repos.json`) |
| `idd issue create --title "..." [--type ...] [--scope ...] [--raw]` | Create a GitHub or GitLab Issue with validated title after plan confirmation |
| `idd start <issue# \| slug> [--slug ...] [--prefix ...] [--base ...]` | Create or idempotently reuse an isolated worktree, create `--no-track` branch & push to `origin`, and sync `.worktreeinclude` |
| `idd sync [issue#] [--no-push] [--dry-run]` | Sync local `TASK` checklist progress back to the Issue body and auto-push branch commits |
| `idd pr` / `idd mr [target] [--draft] [--auto-merge \| --no-auto-merge]` | Generate structured change list & verification table (`Closes #id`) to create or update a PR / MR; reads live global `auto_merge` |
| `idd ci [issue# \| pr# \| !mr#] [--watch] [--logs] [--json]` | Check PR / MR CI status and fetch failing job logs |
| `idd land [issue# \| slug] [--wait-ci] [--rm-worktree] [--no-check-acceptance]` | Rebase, write zero-Markdown plain-text Squash body, clean `TASK/<issue>/`, Squash-merge onto `main`, and auto-check Issue acceptance boxes (keeps branches & worktrees by default) |
| `idd cleanup [--dry-run]` | Safely remove merged worktree directories when clean and `HEAD == headRefOid` (**never deletes branches**) |
| `idd repo-init [--apply]` | Check or apply linear Squash merge rules with branch retention on GitHub / GitLab |
| `idd config [show \| auto-merge on\|off\|status] [--json]` | View or toggle the global PR/MR auto-merge switch (off by default) |
| `idd auth login / status / logout` | Manage credentials for self-hosted GitLab or GitHub Enterprise hosts |
| `idd upgrade [--check]` | Check for updates or fast-forward `idd` (`idd --version` prints current version) |
| `idd uninstall [--dry-run] [--keep-config] [-y]` | Completely remove `idd` symlinks, skill clone, config, and cache |

### Issue & Branch Naming (Zero Git Hooks)

Issue titles, branches, and commit `<type>` tags share **8 standard prefixes**:

```text
feat · fix · refactor · perf · docs · test · ci · chore
```

- **Issue titles**: `<type>: <summary>` or `<type>(<scope>): <summary>` (optional lowercase `scope` ≤ 16 chars).
- **Branch naming**: `<type>/<issue#>-<slug>` for Issue worktrees, or `<type>/<slug>` for local-only repositories.
- **Zero-hook guardrails**: `idd` blocks tool-specific or noisy prefixes (`codex/*`, `claude/*`, `agy/*`, `feature/*`, `bugfix/*`, `tmp/*`) with an exact `git branch -m` fix command—without writing any Git hooks into your repositories.

</details>

---

## Development, Testing & Releases

For module ownership, state, and regression checks, see the [architecture map and decisions](references/architecture.md) (in Chinese).

Zero external dependencies—run the Python 3 standard-library test suite directly, with [SKILL.md](SKILL.md) (`metadata.version`) as the single source of truth:

```bash
# Run the full unit test suite
python3 -m unittest discover -s tests -v

# Verify version consistency across SKILL.md, READMEs, and CLI
python3 scripts/release.py --check

# Bump version, tag, and push release
python3 scripts/release.py patch --tag --push
```

---

## Star History

<a href="https://www.star-history.com/#j-tide/idd&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=j-tide/idd&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=j-tide/idd&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=j-tide/idd&type=Date" width="100%" />
  </picture>
</a>

---

<div align="center">
  <sub>If IDD helps you run multiple AI coding agents cleanly in parallel, consider leaving a ⭐ Star or opening an <a href="https://github.com/j-tide/idd/issues">Issue</a> / <a href="https://github.com/j-tide/idd/pulls">PR</a>.</sub>
</div>

<p align="right"><a href="#readme-top">↑ Back to top</a></p>
