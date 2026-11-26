<div align="center">

# IDD

**让 Claude Code、Codex 与 Antigravity 各自独立并行、互不打扰；在本地看板看清每个 Worktree 进度，一键复制上下文换任意 Agent 接着做。**

**简体中文** · [English](README.en.md)

[![Version](https://img.shields.io/badge/version-v0.0.3-10b981?style=flat-square)](https://github.com/j-tide/idd/releases)
[![Forges](https://img.shields.io/badge/forges-GitHub%20%C2%B7%20Self--Hosted%20GitLab-fc6d26?style=flat-square)](#)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib)-8b5cf6?style=flat-square)](#)
[![Agents](https://img.shields.io/badge/agents-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20Antigravity-38bdf8?style=flat-square)](#)

</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/board-zh-dark.png" />
    <source media="(prefers-color-scheme: light)" srcset="assets/board-zh-light.png" />
    <img src="assets/board-zh-dark.png" width="100%" alt="IDD 实时 Worktree 雷达看板与一键跨 Agent 接力台" />
  </picture>
</p>

---

## IDD 解决什么问题

同时开几个 AI 编程工具干活时，最常见两个痛点：大家挤在同一个目录里容易互相改乱代码；某一个 Agent 额度耗尽或卡住时，对话上下文也跟着锁死在那个窗口里。

**IDD 不把你绑进重型套壳客户端**——你依然在各自原生顺手的窗口里用 Claude Code、Codex 和 Antigravity，底层靠三件事串成闭环：

- **统一研发规范（`SKILL.md` Skill）**：让三个工具遵循同一套约定——先用 GitHub / GitLab **Issue** 锚定需求，再为每个 Issue 开出独立 **Git Worktree**，把拆分步骤与进度记在工作树里的 `TASK/<issue>/` 账本中。
- **全局进度雷达与接力跳板（`idd board`）**：零 Token 实时总览所有仓库和并行需求——一眼看清哪个需求在**哪个 Worktree 目录、哪个分支、做到第几个 `TASK`、CI 过没过**；想换工具时，点一下 **「复制接力词」**（或直接复制工作目录路径 / 分支名），切到另一个 Agent 窗口粘贴就能接着做（看板支持中英文切换）。
- **幕后确定性引擎（`idd` CLI）**：主要供 Agent 自动调用，把 `worktree` 创建、`.worktreeinclude`（`.env`）同步、8 类分支命名拦截、PR/MR 汇总、CI 失败日志拉取与 **Squash 直线合入 `main`** 封装成安全动作，平时无需背命令。

---

## 日常怎么用

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/workflow-zh-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="assets/workflow-zh-light.svg" />
    <img src="assets/workflow-zh-light.svg" width="100%" alt="IDD 多原生 Agent 隔离并行与看板一键接力架构" />
  </picture>
</p>

1. **聊想法，先看样再立 Issue 锚点**：在任意 Agent 窗口聊清需求，必要时先看可交互 HTML 原型或 Before/After 样例对齐效果，确认后再说 *「按 idd 建个 Issue」*，不污染当前代码工作区。
2. **多 Agent 各做各的、互不打扰**：让 **Claude Code** *「开工 #115」*，同时让 **Codex** *「开工 #51」*。每个需求自动进独立的物理 Worktree 目录和规范分支，自动复制 `.env` 并各自维护 `TASK/` 进度。
3. **打开 `idd board` 盯进度，随时一键换手**：通过看板看改动行数、当前步骤和 CI 状态。需要换工具接着做时，在卡片或接力控制台点击 **「复制接力词」**（或直接复制目录/分支），贴进 **Antigravity** 等任意另一个 Agent 对话框即可无缝续写。
4. **验收通过，干净 Squash 合入 `main`**：在最后一个 Agent 里说 *「合入 #115」*（或预先开启 `idd config auto-merge on` / 在 `idd board` 顶栏开启自动合入开关，CI 通过后自动完成无需额外确认），自动 rebase、把 `TASK` 汇总写入 PR/MR 与提交正文、清理临时 `TASK/<issue>/` 目录后以单条直线提交合入 `main`——默认保留需求分支与工作树，空间不够时再运行 `idd cleanup`。

*(首次接管仓库建议执行一次 `idd repo-init --apply`，锁定 GitHub 仅 Squash 合入或 GitLab `ff` + `squash` 策略并保留分支。)*

---

## 快速开始

前置条件：本机已安装 `git` 与 `python3`（打开 `idd board` 会自动弹出初始化向导，点击跳转生成令牌后直接在网页粘贴保存即可连接 GitHub / 自建 GitLab，无需手动敲登录命令）。

```bash
# 1. 一键安装 Skill（挂载到 Claude Code / Codex / Antigravity）与全局 `idd` CLI
curl -fsSL https://raw.githubusercontent.com/j-tide/idd/main/install.sh | sh

# 2. 启动本地进度雷达与一键接力看板
idd board
```

> 每 6 小时会在后台安全检查并快进同步 `origin/main`（仅当本地技能仓库位于干净 `main` 分支时更新，也可手动 `idd upgrade [--check]`）。随时可运行 `idd uninstall`（或兜底脚本 `curl -fsSL https://raw.githubusercontent.com/j-tide/idd/main/install.sh | sh -s -- --uninstall -y`）安全清理，绝不影响业务仓库。

<details>
<summary><strong>可选：将 IDD 设为默认工作流</strong>（个人全局规则 / 项目 <code>AGENTS.md</code> 模板，安装脚本绝不自动写入）</summary>

`install.sh` 仅挂载 Skill 与 `idd` 全局命令，`idd repo-init` 仅配置远端合入策略，**两者都不会自动创建或修改任何全局规则或项目 `AGENTS.md`**。如希望默认启用 IDD，可按需复制下方模板：

### 方式一：个人全局默认（推荐，不污染项目仓库）

将下方片段添加到你所使用的工具的全局规则文件中：

- **Claude Code**：`~/.claude/CLAUDE.md`
- **Codex**：`~/.codex/AGENTS.md`
- **Antigravity**：全局用户规则（User Rules / `~/.gemini/GEMINI.md`）

```markdown
# 全局开发工作流约定（IDD）

所有非只读代码、配置与文档开发任务默认使用全局 `idd` 技能（`~/.agents/skills/idd/SKILL.md`）。

- **先建 Issue 再建 Worktree**：仓库已配置 GitHub / GitLab 远端且未关联 Issue 时，先运行 `idd issue create` 建单，再运行 `idd start <issue#>` 创建或复用独立 Worktree 与 `<type>/<id>-<slug>` 分支并立即推送 `origin`（禁止在 `main` 上直接修改）。
- **逐 TASK 验证与立即推送**：在 `TASK/<issue>/TASK-XX-*.md` 中拆解范围与测试映射，逐项实现、运行真实测试并提交；每次提交后立即执行 `idd sync`（或 `git push -u origin HEAD`）推送到远端开发分支。
- **PR/MR、CI 与直线合入**：完成后运行 `idd pr` / `idd mr` 与 `idd ci --watch`；验收通过（或已开启 `auto_merge` 开关）后运行 `idd land` 清理 `TASK/<issue>/` 并 Squash 直线合入 `main`。
- **安全边界**：仅纯本地无远端仓库使用无编号 `<slug>` 流程；保护未提交修改，未经授权不强推 `main`、不擅自合入主线、不执行部署或生产变更。
```

### 方式二：项目级强制（团队共享）

希望某仓库对所有协作者生效时，在仓库根目录 `AGENTS.md` 中加入以下约定（若团队同时使用 Claude Code，可在根目录 `CLAUDE.md` 写入 `@AGENTS.md` 引入），并建议配合 `idd repo-init --apply` 与远端 `main` 分支保护使用：

```markdown
# 协作开发规范（IDD）

本仓库统一使用 `idd` 技能（Issue-Driven Development）进行开发交付：
- 有 GitHub / GitLab 远端时，新需求先通过 `idd issue create` 建单，再通过 `idd start <issue#>` 在独立 Worktree 与 `<type>/<id>-<slug>` 分支中开发，禁止直接提交 `main`。
- 在 `TASK/<issue>/` 拆解任务并记录真实测试验证；每完成一项即提交并运行 `idd sync` 推送。
- 通过 `idd pr` / `idd mr` 发起合入并等待 CI 通过，验收后使用 `idd land` 清理临时 `TASK/` 目录并 Squash 直线合入 `main`。
```

</details>

---

<details>
<summary><strong>CLI 命令与分支规范速查</strong>（主要由 Agent 自动调用，也可在终端手动运行）</summary>

### 常用命令

| 命令 | 说明 |
| :--- | :--- |
| `idd board` / `idd ui` | 启动本地离线 Web 进度雷达与一键接力看板（每 2 秒刷新脉搏，支持中/英切换） |
| `idd preview <target>... [--compare]` | 启动本地交互原型预览工作台（支持热更新、A/B 并排对比与桌面/平板/手机视口切换） |
| `idd watch [--current-only]` | 在终端按 2 秒频率实时刷新全局（或当前仓库）Worktree 脉搏、当前 TASK 与 CI |
| `idd status [-g\|--global]` | 终端一次性输出 Open Issues、Worktree `TASK` 进度、脉搏与 PR/MR CI |
| `idd repos [list\|add\|remove\|prune]` | 查看或管理全局自动监控的仓库索引（`~/.config/idd/repos.json`） |
| `idd issue create --title "..." [--type ...] [--scope ...]` | 按规范标题创建 GitHub / GitLab Issue |
| `idd start <issue# \| slug>` | 创建或幂等复用独立 Worktree，`--no-track` 建分支并立即推远端 `origin`，同步 `.worktreeinclude` |
| `idd sync [issue#]` | 将本地 `TASK` 勾选进度同步回 Issue 正文并自动推送当前开发分支 |
| `idd pr` / `idd mr` | 汇总 `TASK` 与测试记录（附 `Closes #id`）创建或更新 PR / MR（开启 `auto_merge` 时自动等待 CI 并合入，支持 `--auto-merge` / `--no-auto-merge`） |
| `idd ci [issue# \| pr# \| !mr#] [--logs]` | 检查 PR / MR 的 CI 状态并拉取失败日志 |
| `idd land [issue# \| slug]` | Rebase、清理 `TASK/<issue>/`、Squash 直线合入并自动勾选 Issue 验收标准（默认保留分支与工作树，可选 `--wait-ci` / `--no-check-acceptance` / `--rm-worktree`） |
| `idd cleanup [--dry-run]` | 按需清理工作区干净且 `HEAD == headRefOid` 的已合入工作树目录（**不删分支**） |
| `idd repo-init [--apply]` | 检查或配置 GitHub / GitLab 为线性 Squash 合入策略且保留分支 |
| `idd config [auto-merge on\|off\|inherit] [-g]` | 查看或切换全局与单仓库 PR/MR 自动准入及自动合入开关（默认关闭） |
| `idd auth login / status / logout` | 管理自建 GitLab / GitHub 企业版主机凭据 |
| `idd upgrade [--check]` | 检查或立即快进更新本地 `idd`（`idd --version` 查看当前版本） |
| `idd uninstall [--dry-run] [--keep-config] [-y]` | 安全完全卸载 `idd`（移除软链、技能仓库、配置与缓存） |

### Issue 与分支规范（零 Git Hooks 侵入）

Issue 标题、分支前缀与 Commit `<type>` 共用以下 **8 类标准词表**（Issue 标题为 `<type>: <描述>` 或 `<type>(<scope>): <描述>`，可选 `scope` 须为 ≤ 16 字符的小写英文标识；绑定 Issue 分支为 `<type>/<issue#>-<slug>`，纯本地为 `<type>/<slug>`）：

`feat` · `fix` · `refactor` · `perf` · `docs` · `test` · `ci` · `chore`

`idd` 内置拦截 `codex/*`、`claude/*`、`agy/*`、`feature/*`、`bugfix/*`、`tmp/*` 等不规范前缀，并在报错时给出标准 `git branch -m` 修复命令，不在业务仓库写入任何 Git Hook。

</details>

---

## 开发、测试与发版

零外部依赖，使用 Python 3 标准库直接运行全部单元测试，并以 [SKILL.md](SKILL.md) 中的 `metadata.version` 作为唯一版本源：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/release.py --check
python3 scripts/release.py patch --tag && git push origin main && git push origin v0.0.2
```
