---
name: idd
description: 面向 Issue 的跨工具开发工作流（Issue-Driven Development）。让 Claude Code、Codex 与 Antigravity 共用同一套「聊想法建 Issue → 独立 Worktree 并行 → TASK 拆解与真测试 → PR/MR CI 自愈 → Squash 直线合入 main 并清理 TASK 目录」流水线，同时支持 GitHub 与自建 GitLab。支持多工具无缝接手、长期阻塞恢复与历史补录；只读咨询或评估不创建任务。
metadata:
  version: "0.0.4"
---

# IDD（Issue-Driven Development）

**先用 Issue 锚定需求，再为每个 Issue 开出独立 Worktree 与分支，逐项实现、验证并提交 `TASK`，在 PR / MR 上完成 CI 自愈与验收，最后将整个需求压缩成一条直线提交 Squash 合入 `main`（合入前清理临时 `TASK/` 目录）。**

本工作流通过统一的目录约定与共用 CLI 工具 **`idd`**，同时支持 **GitHub** 与 **自建 GitLab**，让 **Claude Code、Codex、Antigravity** 之间随时无缝接手同一个 Issue，多个 Issue 并行开发互不冲突。

保持流程轻量。不要生成重量级的 Spec、Plan、Design 文档，只保留执行和验证任务所必需的文件。

---

## 一、共用工具 `idd` 速查

所有跨工具的 Git / Worktree / 平台确定性操作优先使用 `idd` 命令（若部分无交互子进程 `PATH` 未包含 `~/.local/bin`，可直接执行 `python3 "$HOME/.agents/skills/idd/scripts/idd"`）：

| 命令 | 用途 |
| :--- | :--- |
| `idd board` / `idd ui` | 启动本地 Web 实时监控看板（浏览器零 Token 跨仓库盯盘，2s 刷新工作树脉搏） |
| `idd preview <file-or-dir>... [--compare] [--title "..."] [--port ...] [--no-open]` | 启动本地交互原型预览工作台（支持热更新、A/B 并排对比与桌面/平板/手机视口切换） |
| `idd watch [--current-only] [--once]` | 启动终端实时监控面板（默认全局聚合，2s 刷新本地脉搏、30s 缓存远端） |
| `idd status [-g\|--global] [--open-only] [--local-only] [--json]` | 聚合并展示 Issue、`TASK` 进度、实时脉搏与 PR/MR CI 状态（非 Git 目录自动全局聚合） |
| `idd repos [list\|add\|remove\|prune]` | 查看或管理本机全局监控的活跃仓库索引（`~/.config/idd/repos.json`） |
| `idd issue create --title "..." [--type ...] [--scope ...] [--raw] [--body "..."] [--label ...]` | 聊天确认需求后按规范标题创建 GitHub / GitLab Issue |
| `idd start <issue# \| slug> [--slug ...] [--prefix ...] [--no-push]` | 认领 Issue 创建（或**幂等复用**已有）独立 Worktree，使用 `--no-track` 建分支并立即 `push -u origin HEAD` 推远端，同时同步 `.worktreeinclude` |
| `idd sync [issue#] [--no-push] [--dry-run]` | 将当前 Worktree 的 `TASK` 勾选进度同步回 Issue 正文（渲染原生进度条），并自动推送当前开发分支到远端 |
| `idd pr [issue# \| slug] [--auto-merge \| --no-auto-merge]` / `idd mr ...` | 基于 `TASK` 与提交记录生成结构化描述（含 `Closes #<id>`）并创建/更新 PR 或 MR；若 `auto_merge` 生效则自动等待 CI 结算并直线合入 |
| `idd ci [issue# \| pr# \| !mr#] [--watch] [--logs] [--json]` | 查看 PR / MR 的 CI 状态并拉取失败 Job/Run 日志 |
| `idd land [issue# \| slug] [--keep-tasks] [--force-unfinished-tasks] [--rm-worktree] [--auto] [--wait-ci] [--no-check-acceptance] [--dry-run]` | 自动 Rebase、汇总正文、清理 `TASK/<issue>/`、Squash 直线合入并自动勾选 Issue 验收标准（默认保留分支与工作树） |
| `idd cleanup [--dry-run]` | 按需移除已合入且 HEAD 一致的干净工作树目录（保留所有分支） |
| `idd repo-init [--apply]` | 检查或配置 GitHub / GitLab 为线性 Squash 合入策略（保留分支） |
| `idd config [auto-merge on\|off\|inherit] [-g\|--global] [--json]` | 查看或切换全局/单仓库 PR/MR 自动准入与自动合入开关（默认关闭） |
| `idd auth login <host> --token <PAT>` / `status` / `logout` | 保存与检查自建 GitLab / GitHub 企业版主机凭据 |
| `idd upgrade [--check]` | 检查或立即拉取远端更新并快进同步本地 `idd`（另支持后台 6 小时安全自动同步） |
| `idd uninstall [--dry-run] [--keep-config] [-y]` | 安全完全卸载 `idd`（移除软链、技能仓库、配置与缓存） |

---

## 二、核心映射与目录约定

只要当前仓库已配置 GitHub / GitLab 远端，所有可独立验收的开发需求（功能、修复、重构、样式与文档改动）**必须先绑定一个远端 Issue**，全链路使用稳定一致的命名映射：

- **Issue 标题规范**：
  - 使用 `<type>: <简明描述>` 或 `<type>(<scope>): <简明描述>`（复用 8 类 `<type>`，如 `fix(sync): 避免误匹配行内进度标记`、`feat(land): 自动勾选验收标准`），单行建议 ≤ 50 字符、不重复类型动词（如 `fix:` 后不写“修复…”）。
  - 可选 `(<scope>)` **必须简短**：仅限单个小写英文/数字/连字符标识（`^[a-z0-9]+(?:-[a-z0-9]+)*$`，**≤ 16 字符**），禁止空格、逗号、斜杠或中文；跨模块改动直接省略括号。
  - `idd issue create` 默认在入口校验（支持 `--type` / `--scope` 自动拼接，极少数非工程单可传 `--raw` 放行）；`idd start` 推断分支前缀优先级为 `--prefix` > Issue 标题 `<type>` > Labels > `feat`，并自动兼容历史无前缀 Issue。
- **Issue ↔ 目录 ↔ Worktree ↔ 分支**：
  - `Issue #42` ↔ 任务目录 `42-<slug>` ↔ 独立工作树 `../<主仓库名>-worktrees/42-<slug>` ↔ 分支 `<type>/42-<slug>`（例如 `feat/42-export-csv`、`fix/43-dark-flicker`）。
  - **仅当仓库完全没有配置 GitHub / GitLab 远端（纯本地仓库）时**，才允许回退使用无 Issue 编号的 `<issue-slug>` 与 `<type>/<issue-slug>`。
  - **分支与提交共用 8 类合法 `<type>`**：`feat | fix | refactor | perf | docs | test | ci | chore`。
  - **严禁使用不规范分支前缀**：禁止 `codex/*`、`claude/*`、`agy/*`、`antigravity/*`、`cursor/*`、`ai/*` 等工具前缀，也禁止 `feature/*`、`bugfix/*`、`tmp/*`、`wip/*` 等混写或临时前缀。`idd` 命令会在入口和出口直接拦截并给出 `git branch -m` 重命名提示。
- **任务记录**：`TASK/<issue>/TASK-XX-<任务名称>.md`。
- **测试规范**：沿用项目现有的目录、命名、工具与入口；新测试按行为或模块命名，任务与测试的映射以任务文件的 `Test` 字段为准。不要额外创建平行的 `TEST/` 目录。
- **禁止冗余文档**：不要创建重复的 SPEC、PLAN、DESIGN、README、人工进度看板或索引文件。进度派生靠 `idd status` / `task_status.py`（以及 `idd sync` 回写 Issue 正文）。
- **证据附件**：必要的小型脱敏证据可放在 `TASK/<issue>/evidence/TASK-XX/`；留存要求见[任务记录约定](references/task-records.md#证据留存)。
- **文档与配置任务**：可以使用明确的命令或检查清单验证，不必创建没有实际意义的空测试文件；代码任务必须注明对应的真实测试文件或已有测试目标。

---

## 三、入口分流：4 种工作模式

动手前先读取 `AGENTS.md`、适用的嵌套指令文件及相关项目文档；在制定计划前检查相关实现代码、测试、脚本、配置和 `git status`。

### 模式 A｜想法建单（Chat → Preview → Issue）
当用户是在聊想法、提新需求、让你先建单而不急着改代码时：
1. 做必要的只读仓库核对（只问会实质影响设计的问题，不问查仓库就能确定的内容）；存在多种做法时先收敛 2~3 个关键取舍。
2. **直观对齐门禁（Show, Don't Just Tell）**：不要只甩大段文字方案让用户盲审，按[直观对齐规范](references/visual-alignment.md)先给可交互 HTML 原型（Antigravity 发交互 Artifact，Claude Code / Codex 写仓库外临时文件并用 `idd preview` 打开）、Before/After 真实样例或 Mermaid 状态流转图（明确单点 Bug 除外）。
3. 用户对预览效果拍板后，将确认的视觉/交互/边界态要点写入范围、边界（Scope / Non-goals）与可勾选验收标准（`- [ ]`），按规范格式（`<type>: <简明描述>` 或 `<type>(<scope>): <简明描述>`）调用 `idd issue create` 创建 Issue，向用户返回 Issue 编号与链接，**不修改当前工作树代码**。

### 模式 B｜新开发需求建单、认领 Issue 或跨工具接手（Start / Handoff）
**硬性前置规则**：若当前仓库已配置 GitHub / GitLab 远端且用户直接提出了新的功能/修复/重构需求、尚未关联已有 Issue，必须先完成直观对齐并运行 `idd issue create` 建单再开干。**仅当**属于无 UI / 无交互歧义的明确单点修复，或用户已直接确认具体原型/已有清晰验收标准的 Issue 时，才可直接 `idd start <issue#>` 推进；凡涉及 UI 页面、交互流转、终端输出格式或复杂分支的新需求，**严禁仅凭文字猜测直接写代码**，必须先按[直观对齐规范](references/visual-alignment.md)看样确认再建单。**严禁在有远端仓库里跳过建单直接开无 Issue 分支或本地快进合入 `main`。**

> **首次接管仓库自动初始化合入策略**：首次在带 GitHub / GitLab 远端的仓库运行 `idd issue create`、`idd start`、`idd repos add`，或在 `idd ui` 初始化向导保存令牌时，默认会自动只读探测并尝试执行 `idd repo-init --apply`（锁定 GitHub 仅 Squash、`PR_TITLE`/`PR_BODY` 模板，或 GitLab `ff` + `always` squash、`%{title}\n\n%{description}` 模板，且保留分支）。若用户选择跳过（`--no-repo-init` 或取消向导勾选）或因无权限失败，会在 `~/.config/idd/repos.json` 持久标记为 `pending`，并在 `idd repos list` 与 `idd ui` 中持续展示可点击的「待初始化 / 重试」入口。

当用户指定要做某个 Issue（如“做 `#42`”、“用 Codex/Claude 接手 `#42`”）或刚通过 `idd issue create` 完成建单后：
1. **统一入口**：在项目根目录或任意工作树先运行 `idd start <issue#>`。
   - 若该 Issue **尚无工作树**：`idd start` 会拉取最新 `origin/<default_branch>`，在同级 `../<repo>-worktrees/<id>-<slug>` 以 `--no-track` 创建工作树和分支（绝不将 upstream 错绑到 `origin/main`），同步 `.worktreeinclude` 里的 `.env` 等本地文件，并立即执行 `git push -u origin HEAD` 将开发分支推到远端（若无特殊原因禁止传 `--no-push`）。
   - 若该 Issue **已有工作树（跨工具接手）**：`idd start` 幂等返回现有工作树路径、分支、`git status`、最近提交与 `TASK/` 进度，并自动修复错绑上游且为未推分支补推 `origin/<branch>`。**严禁各工具自行在 `.claude/worktrees/` 或其他私有目录另起炉灶。**
2. 后续所有代码阅读、TASK 创建、测试和提交均在该独立工作树目录中进行。
3. **并行边界**：**不同 Issue 之间可通过各自独立 Worktree 完全并行开发；同一个 Issue 内的多个 TASK 默认按依赖串行执行。**

### 模式 C｜拆解与创建任务文件
在对应工作树的 `TASK/<issue>/` 下创建任务文件（纯只读咨询不创建）：

```text
TASK/
└── 42-export-csv/
    ├── TASK-01-<任务名称>.md
    ├── TASK-02-<任务名称>.md
    └── ...
```

普通功能可参考 3～10 个有实际意义的任务（小 Issue 可以只有 1 个，大 Issue 可超过 10 个，按独立验收与依赖划分，不凑数）。创建或实质修改前先读取[任务记录约定](references/task-records.md)。

任务拆分规则：
- 编号递增且稳定；执行顺序由 `Depends on` 决定（无环有向图），不为排序重编号。跨目录依赖使用 `<issue>/TASK-XX`。
- 每个代码任务必须关联验证真实产品行为的自动化测试（可多任务共用同一测试文件）；确实不适合自动化测试的须说明原因并定义具体替代检查。
- 测试命令从项目配置、CI 或文档确认。
- **薄切片早验收（UI / 交互类需求）**：高视觉或强交互需求拆解时，应让 `TASK-01` 优先跑通最小可交互真界面 / 主链路，尽早向用户展示真实效果并确认手感，再继续补齐边缘逻辑与全量测试，避免整批开发后再返工。
- 若由已明确验收标准的 Issue 启动且范围清晰低风险，或用户已明确授权覆盖本轮范围，创建完 `TASK` 文件（建议顺手跑一次 `idd sync` 更新 Issue 进度条）后直接进入执行；若需求本身模糊或存在重大设计取舍，先向用户展示任务列表、依赖关系与测试映射并等待确认。

### 模式 D｜只读全局进度与实时监控
当用户询问“有哪些 Issue 在跑”、“做到哪一步了”或跨工具查看总览时，优先运行：

```bash
idd status [--open-only]   # 在非 Git 目录或未挂工作区的全局对话中会自动切为跨仓库全局聚合；也可显式传 -g / --global
```

每次在任意仓库运行 `idd start` / `status` 等命令时，主仓库会自动记入本机全局索引 `~/.config/idd/repos.json`，`idd status` 会附带每个工作树的**实时脉搏**（未提交文件数、`+insertions/-deletions`、活跃心跳与疑似卡住告警）。

当用户希望**不打断当前对话、零 Token 实时盯盘**时，推荐直接让用户在独立终端启动：
- **浏览器网页看板（最直观）**：`idd board`（别名 `idd ui`，每 2 秒无锁轮询工作树脉搏并按 30 秒缓存同步 GitHub/GitLab 状态）；
- **终端实时看板**：`idd watch`（支持 `--once`、`--current-only`、`--interval`）。

纯离线/无 Git 场景也可直接调用：

```bash
python3 "$HOME/.agents/skills/idd/scripts/task_status.py" --root . --open-only
```

---

## 四、逐项执行任务

按以下顺序推进单个 Issue 内的 `TASK`：

1. 阅读该 Issue 目录下的所有任务文件与适用的项目指令。
2. 按依赖选择可执行的 `planned` 任务（若是从另一工具接手，先检查 `in_progress` 任务与最近提交继续，不重复执行 `done` 任务）。`deferred`、`cancelled` 或未知状态依赖不可视作完成。
3. 将当前任务头部 `Status` 更新为 `in_progress`。
4. 检查相关实现代码和现有测试，只实现当前任务范围内的内容。
5. 创建或更新关联测试并执行针对性验证命令。
6. 如果验证失败：
   - 区分问题来自当前改动、原有代码还是运行环境；
   - 修复当前改动引入的问题并重测，**同一失败问题最多进行两轮有针对性的修复与重测**；
   - 两轮后仍失败则标记 `blocked`，按[阻塞与恢复](references/task-records.md#长期阻塞与恢复)写明原因、影响、解除条件和下一步并停止依赖链工作。
   - **没有实际运行并通过的测试，绝不能声称通过。**
7. 约定范围、必要验证及证据留存都满足后，将 `Status` 设为 `done`、分别记录 `Outcome` 与验证记录表（纯文档检查也必须实际执行）。
8. 在工作树分支上为该 `TASK` 创建一次开发提交（只含本任务改动、测试及任务记录），提交后**必须立即推送到远端开发分支**（通过 `idd sync` 自动同步进度条并推送，或显式执行 `git push -u origin HEAD`），不得把已提交的开发分支长期只留在本地。
9. 发现新增范围时先按[范围增长](references/task-records.md#范围增长与任务依赖)评估：同一 Issue 验收范围内追加编号任务，独立交付拆为新 Issue。不得把新工作塞进已完成任务。

### 提交标题与正文

开发提交和主线 Squash 提交都使用单行标题 `<type>: <中文改动>`（`<type>` 同分支前缀：`feat`、`fix`、`refactor`、`perf`、`docs`、`test`、`ci`、`chore`），冒号后直接写「哪个对象发生了什么变化」。

开发提交模板（支持写多行 `Test:` 累加）：

```text
<type>: <本任务的具体变化>

<可选的原因或其余变化>

Task: <issue>/TASK-XX
Refs: #<Issue编号>
Test: <实际执行的验证命令> — <结果，例如 12 passed>
```

PR / MR 汇总正文模板（`idd pr` / `idd mr` 自动生成结构化 Markdown：`## 变更内容` 列表与 `## 验证记录` 表格；多项测试逐行对齐，`&&` 复合命令拆分为独立行内代码，冗长命令与深层路径自动提炼简短标签并在文末 `<details><summary>完整验证命令</summary>` 折叠保留原命令）：

```markdown
Closes #<Issue编号>

## 变更内容

- **TASK-01** <本任务的具体变化>

  <可选的详细说明（来自开发提交正文）>

- **TASK-02** <本任务的具体变化>

## 验证记录

| 任务 | 验证项 | 结果 |
| --- | --- | --- |
| TASK-01 | `<简短命令或命令标签>` | <结果> |
| TASK-02 | `<检查项 A>` | <结果> |
|  | `<检查项 B>` | <结果> |
```

主线 Squash Commit 正文模板（`idd land` 在合入时自动生成零 Markdown 符号的干净纯文本，确保 GitHub / GitLab Commit 页面与 `git log` 无 `###`、`**` 或反引号外露）：

```text
Closes #<Issue编号>

TASK-01: <本任务的具体变化>
Test: <简短命令或命令标签> — <结果>
```

---

## 五、Issue 级最终 Review、PR/MR 与 CI 自愈

所有必要 `TASK` 完成后、提 PR / MR 或合入前，详细规范见[Issue 与 Git 协作流](references/git-issue-workflow.md)：

1. **本地最终验收**：运行项目级相关测试套件、适用的构建 / 类型检查 / Lint，逐项核对 Issue 验收标准，Review 完整 Git Diff（检查回归、安全、错误处理与无关改动）。
2. **创建 / 更新 PR 或 MR**：确认工作树干净后运行 `idd pr`（GitLab 也可用别名 `idd mr`，自动汇总 `TASK` 列表与 `Test:` 并关联 `Closes #<id>`）。
   - `idd pr` 会自动读取本仓库生效的 `auto_merge` 开关（仓库覆盖 > 全局默认，默认关闭；可在 CLI `idd config auto-merge ...` 或 `idd board` 设置，也支持单次传 `--auto-merge` / `--no-auto-merge`）。
   - **禁止擅自覆写开关或缓存旧状态**：除非用户本轮明确要求单次覆写（如“这次先别自动合入”），否则**默认直接运行无参 `idd pr` / `idd mr`，严禁擅自附加 `--no-auto-merge` 或 `--auto-merge`**；也不要凭对话早期的 `idd config` 快照决定是否自动合入（用户随时可能在开发途中通过 `idd board` 顶栏切换开关），始终交由 `idd pr` 在提 PR 当刻实时读取最新配置。
3. **CI 校验与自愈**：
   - **当 `auto_merge` 关闭（默认）**：运行 `idd ci --watch` 等待远端 Checks / Pipeline 结束；失败时执行 `idd ci --logs` 拉取失败 Job/Run 日志并在原工作树定位修复、本地复测后推送。
   - **当 `auto_merge` 开启**：`idd pr` 自动准入并在创建/更新后直接阻塞等待 CI 结算（失败时会保留 `TASK/`、打印失败日志并以退出码 `3` 中止，此时回到工作树定位修复并复测推送后重跑 `idd pr`）。
   - **同一 CI 失败问题严格遵守最多两轮有针对性修复的上限**；两轮后仍未变绿则将对应任务记为 `blocked` 并向用户报告，禁止死循环重试。
   - 若因其他 PR/MR 先合入导致落后或冲突，执行 `git fetch origin main && git rebase origin/main`（解冲突并复测）后 `git push --force-with-lease`。
4. **验收状态与自动准入边界**：
   - 开关关闭时：PR / MR 创建且本地检查/CI 状态明晰后，向用户报告「PR/MR 待验收」等待确认（或按用户本轮明确授权执行 `idd land`）。
   - 开关开启时：**不再停下来等待用户口头确认**；CI 全绿（`PASS`）或仓库未配置远端 CI（`NONE`）且本地测试已通过时，`idd pr` 会自动串行执行 `idd land`（清理 `TASK/`、Squash 直线合入、勾选 Issue 验收框并快进 `main`）。
   - **安全暂停红线**（开关开启时遇到以下任一情况一律暂停交由人工处理）：`--draft` PR/MR、CI 经 2 轮修复仍失败或等待超时（退出码 `3`）、Rebase 冲突（退出码 `2`）、`TASK/<issue>/` 含未完成任务（退出码 `2`）、`TASK/<issue>/evidence/` 含附件（退出码 `2`）。

---

## 六、线性合入主分支与目录清理（零 Merge 节点）

为了保证 `main` 分支永远是一条干净的直线，且主干不堆积已完成的 `TASK/` 档案，合入阶段统一遵循：

1. **GitHub / 自建 GitLab 线性合入（推荐默认）**：用户验收确认、开启了 `auto_merge` 开关并满足安全边界，或本轮具备明确自动合入授权且 CI 全绿后，执行（开关开启时 `idd pr` 已自动串联调用）：
   ```bash
   idd land <issue#>
   ```
   `idd land` 会自动完成：
   - 核对工作树与分支。GitLab 先确认项目启用了快进合并和强制 Squash。随后 `git fetch` 并自动 rebase 到最新 `origin/main`；
   - 在删除 `TASK/<issue>/` 前，先生成结构化 Markdown 写入 PR/MR 描述，并生成零 Markdown 纯文本写入 Squash Commit 正文（均含 `Closes #<id>` 与所有 `TASK-XX` / `Test:`）；
   - 执行 `git rm -rf TASK/<issue>` 并提交清理（若 `evidence/` 含附件且未传 `--force-clean-evidence` 会安全暂停提示）；
   - 以**单条 Squash 提交**直线合入 `main`（GitHub 走 Squash Merge；GitLab 走 Squash + Fast-Forward，自动关闭 Issue 并**默认保留远端与本地需求分支**）；
   - GitLab 合入后根据 MR 结果和远端目标分支确认只新增一条提交。自动合入仍在等待时报告待确认状态；
   - 合入真正完成后（非 `--auto` 挂起），默认自动勾选 Issue 正文「验收标准」节内的未勾选复选框并保底刷新进度块（可用 `--no-check-acceptance` 跳过）；
   - **默认保留本地 Worktree**（只有显式传入 `--rm-worktree` 时才顺带移除工作树目录，分支依然保留），并尝试将干净的主工作树 `main` 快进至最新。
2. **释放本地工作树空间（按需手动）**：平时保留工作树便于回顾上下文；需要清理磁盘时手动运行 `idd cleanup`——它只删除工作树目录（**绝不删除分支**），且仅当工作区干净**且**本地 `HEAD` 与已合入 PR/MR 的 `headRefOid` 完全一致时才清理，避免误删合入后的本地新增提交。
3. **无远端 / 纯本地仓库回退**：按照[Issue 与 Git 协作流 · 纯本地回退](references/git-issue-workflow.md#纯本地无远端回退流程)在临时集成分支完成压缩、删除 `TASK/<issue>/`、变基并与主线 `git merge --ff-only`。
4. 补录历史任务仍先读[补录流程](references/task-records.md#事后补录)，不得伪造事前记录。

---

## 七、执行记录、最终回复与约束

- **执行记录与证据**：任务头部为唯一当前状态源，`Status` 与 `Outcome` 独立记录；`run/` 等忽略目录不能作为唯一长期依据。详情见[任务记录约定](references/task-records.md)。
- **最终回复**：结束本轮开发或恢复执行时，读取[最终回复模板](references/final-reply.md)。首次提请验收、同轮直通合入、部分完成或受阻时按「标准模板」汇报结论、完成内容、验证结果与交付状态；**验收后仅执行准入合入（`idd land`）时改用「验收后准入回执（精简版）」**，明确写清 PR / MR 已合入，且所有关联的 Issue 与 PR / MR 均使用可点击 Markdown 链接。纯咨询或仅建单不套用开发交付报告。
- **执行红线**：
  - 不创建重复规划文档或人工维护的平行索引；
  - 不得为了让测试通过而削弱或删除测试；
  - 除非确有必要且理由充分，否则不要增加依赖；
  - 不修改无关文件，不覆盖用户已有修改；
  - 没有实际运行并通过的测试，绝不能声称通过；
  - **常规开发分支推送默认允许且必须执行**：有 `origin` 远端时，向当前需求开发分支（`<type>/*`）执行 `git push -u origin HEAD`（含 `idd start` / `idd sync` 自动推送）属于标准开发动作，不属于“越权外部写入”；未经明确授权不得执行的是强推主干/重写共享历史、未经验收且未开启 `auto_merge` 开关时擅自合入 `main`、发版打 Tag、部署或生产变更（若当前仓库已开启 `auto_merge` 开关且满足安全门禁，则视作已获自动合入授权）；
  - 若当前项目的 `AGENTS.md` 在技术栈、测试门禁、安全边界等业务规则上更严格，以项目指令为准；若项目文档中仍残留已废弃的旧 `TaskFlow` 工作流引用，一律以本 IDD 流程替代（先建 Issue、独立 Worktree、PR/MR 与 Squash 直线合入），不得退回无 Issue 的旧流程。
