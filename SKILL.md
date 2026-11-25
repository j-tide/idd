---
name: idd
description: 面向 Issue 的跨工具开发工作流（Issue-Driven Development）。让 Claude Code、Codex 与 Antigravity 共用同一套「聊想法建 Issue → 独立 Worktree 并行 → TASK 拆解与真测试 → PR/CI 自愈 → Squash 直线合入 main 并清理 TASK 目录」流水线。支持多工具无缝接手、长期阻塞恢复与历史补录；只读咨询或评估不创建任务。
metadata:
  version: "0.2.0"
---

# IDD（Issue-Driven Development）

**先用 Issue 锚定需求，再为每个 Issue 开出独立 Worktree 与分支，逐项实现、验证并提交 `TASK`，在 PR 上完成 CI 自愈与验收，最后将整个需求压缩成一条直线提交 Squash 合入 `main`（合入前清理临时 `TASK/` 目录）。**

本工作流通过统一的目录约定与共用 CLI 工具 **`idd`**，让 **Claude Code、Codex、Antigravity** 之间随时无缝接手同一个需求，多个 Issue 并行开发互不冲突。

保持流程轻量。不要生成重量级的 Spec、Plan、Design 文档，只保留执行和验证任务所必需的文件。

---

## 一、共用工具 `idd` 速查

所有跨工具的 Git / Worktree / GitHub 确定性操作优先使用 `idd` 命令（若部分无交互子进程 `PATH` 未包含 `~/.local/bin`，可直接执行 `python3 "$HOME/.agents/skills/idd/scripts/idd"`）：

| 命令 | 用途 |
| :--- | :--- |
| `idd status [--open-only] [--local-only] [--json]` | 聚合并展示 GitHub Open Issues、所有 Worktree 的 `TASK` 进度与 PR/CI 状态 |
| `idd issue create --title "..." [--body "..."] [--label ...]` | 聊天确认需求后创建 GitHub Issue |
| `idd start <issue# \| slug> [--slug ...] [--prefix ...]` | 认领 Issue 创建（或**幂等复用**已有）独立 Worktree，自动同步 `.worktreeinclude` |
| `idd sync [issue#] [--dry-run]` | 将当前 Worktree 的 `TASK` 勾选进度同步回 GitHub Issue 正文（渲染原生进度条） |
| `idd pr [issue# \| slug] [--draft] [--dry-run]` | 基于 `TASK` 记录与提交日志生成结构化描述（含 `Closes #<id>`）并创建/更新 PR |
| `idd ci [issue# \| pr#] [--watch] [--logs] [--json]` | 查看 PR 的 CI 检查汇总与 Merge 状态，自动拉取失败 Job 日志 |
| `idd land [issue# \| slug] [--keep-tasks] [--auto] [--dry-run]` | 自动 Rebase 最新 `main`、持久化汇总正文、清理 `TASK/<goal>/` 并 Squash 直线合入 |
| `idd cleanup [--dry-run]` | 批量回收 PR 已合并且工作区干净的本地 Worktree 与分支 |
| `idd repo-init [--apply]` | 检查或配置仓库为仅允许 Squash Merge 且合入后自动删远端分支 |
| `idd upgrade [--check]` | 检查或立即拉取远端更新并快进同步本地 `idd`（另支持后台 6 小时安全自动同步） |

---

## 二、核心映射与目录约定

一个可独立验收的需求优先绑定一个 GitHub Issue，全链路使用稳定一致的命名映射：

- **Issue ↔ 目标 ↔ Worktree ↔ 分支**：
  - `Issue #42` ↔ 目标目录 `42-<slug>` ↔ 独立工作树 `../<主仓库名>-worktrees/42-<slug>` ↔ 分支 `feat/42-<slug>`（或 `fix/42-<slug>`）。
  - 纯本地/无远端场景使用 `<目标名称>` 与 `feature/<目标名称>`。
- **任务记录**：`TASK/<目标名称>/TASK-XX-<任务名称>.md`。
- **测试规范**：沿用项目现有的目录、命名、工具与入口；新测试按行为或模块命名，任务与测试的映射以任务文件的 `Test` 字段为准。不要额外创建平行的 `TEST/` 目录。
- **禁止冗余文档**：不要创建重复的 SPEC、PLAN、DESIGN、README、人工进度看板或索引文件。进度派生靠 `idd status` / `task_status.py`（以及 `idd sync` 回写 Issue 正文）。
- **证据附件**：必要的小型脱敏证据可放在 `TASK/<目标名称>/evidence/TASK-XX/`；留存要求见[任务记录约定](references/task-records.md#证据留存)。
- **文档与配置任务**：可以使用明确的命令或检查清单验证，不必创建没有实际意义的空测试文件；代码任务必须注明对应的真实测试文件或已有测试目标。

---

## 三、入口分流：4 种工作模式

动手前先读取 `AGENTS.md`、适用的嵌套指令文件及相关项目文档；在制定计划前检查相关实现代码、测试、脚本、配置和 `git status`。

### 模式 A｜想法建单（Chat → Issue）
当用户是在聊想法、提新需求、让你先建单而不急着改代码时：
1. 做必要的只读仓库核对（只问会实质影响设计的问题，不问查仓库就能确定的内容）。
2. 明确背景（Why）、范围与明确边界（Scope / Non-goals）、风险以及可勾选的验收标准（`- [ ]`）。
3. 调用 `idd issue create` 创建 GitHub Issue，向用户返回 Issue 编号与链接，**不修改当前工作树代码**。

### 模式 B｜认领 Issue 或跨工具接手（Start / Handoff）
当用户指定要做某个 Issue（如“做 `#42`”、“用 Codex/Claude 接手 `#42`”）：
1. **统一入口**：在项目根目录或任意工作树先运行 `idd start <issue#>`。
   - 若该 Issue **尚无工作树**：`idd start` 会拉取最新 `origin/<default_branch>`，在同级 `../<repo>-worktrees/<id>-<slug>` 创建工作树和分支，并同步 `.worktreeinclude` 里的 `.env` 等本地文件。
   - 若该 Issue **已有工作树（跨工具接手）**：`idd start` 幂等返回现有工作树路径、分支、`git status`、最近提交与 `TASK/` 进度。**严禁各工具自行在 `.claude/worktrees/` 或其他私有目录另起炉灶。**
2. 后续所有代码阅读、TASK 创建、测试和提交均在该独立工作树目录中进行。
3. **并行边界**：**不同 Issue 之间可通过各自独立 Worktree 完全并行开发；同一个目标内的多个 TASK 默认按依赖串行执行。**

### 模式 C｜拆解与创建任务文件
在对应工作树的 `TASK/<目标名称>/` 下创建任务文件（纯只读咨询不创建）：

```text
TASK/
└── 42-export-csv/
    ├── TASK-01-<任务名称>.md
    ├── TASK-02-<任务名称>.md
    └── ...
```

普通功能可参考 3～10 个有实际意义的任务（小目标可以只有 1 个，大目标可超过 10 个，按独立验收与依赖划分，不凑数）。创建或实质修改前先读取[任务记录约定](references/task-records.md)。

任务拆分规则：
- 编号递增且稳定；执行顺序由 `Depends on` 决定（无环有向图），不为排序重编号。跨目标依赖使用 `<目标名称>/TASK-XX`。
- 每个代码任务必须关联验证真实产品行为的自动化测试（可多任务共用同一测试文件）；确实不适合自动化测试的须说明原因并定义具体替代检查。
- 测试命令从项目配置、CI 或文档确认。
- 若由已明确验收标准的 GitHub Issue 启动且范围清晰低风险，或用户已明确授权覆盖本轮范围，创建完 `TASK` 文件（建议顺手跑一次 `idd sync` 更新 Issue 进度条）后直接进入执行；若需求本身模糊或存在重大设计取舍，先向用户展示任务列表、依赖关系与测试映射并等待确认。

### 模式 D｜只读全局进度
当用户询问“有哪些 Issue 在跑”、“做到哪一步了”或跨工具查看总览时，优先运行：

```bash
idd status [--open-only]
```

纯离线/无 Git 场景可直接调用：

```bash
python3 "$HOME/.agents/skills/idd/scripts/task_status.py" --root . --open-only
```

---

## 四、逐项执行任务

按以下顺序推进单个目标内的 `TASK`：

1. 阅读该目标下的所有任务文件与适用的项目指令。
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
8. 在工作树分支上为该 `TASK` 创建一次开发提交（只含本任务改动、测试及任务记录），关键节点可顺手运行 `idd sync` 同步 GitHub 进度条。
9. 发现新增范围时先按[范围增长](references/task-records.md#范围增长与任务依赖)评估：同一验收目标内追加编号任务，独立交付拆为新 Issue。不得把新工作塞进已完成任务。

### 提交标题与正文

开发提交和主线 Squash 提交都使用单行标题 `<type>: <中文改动>`（如 `feat`、`fix`、`refactor`、`docs`、`test`），冒号后直接写「哪个对象发生了什么变化」。

开发提交模板：

```text
<type>: <本任务的具体变化>

<可选的原因或其余变化>

Task: <目标名称>/TASK-XX
Refs: #<Issue编号>
Test: <实际执行的验证命令> — <结果，例如 12 passed>
```

主线需求提交 / PR 汇总正文模板（`idd pr` 与 `idd land` 自动按此结构汇总）：

```text
Goal: <目标名称>
Closes #<Issue编号>

TASK-01 <本任务的具体变化>
Test: <本任务实际执行的验证及结果>

TASK-02 <本任务的具体变化>
Test: <本任务实际执行的验证及结果>
```

---

## 五、目标级最终 Review、PR 与 CI 自愈

所有必要 `TASK` 完成后、提 PR 或合入前，详细规范见[Issue 与 Git 协作流](references/git-issue-workflow.md)：

1. **本地最终验收**：运行项目级相关测试套件、适用的构建 / 类型检查 / Lint，逐项核对 Issue 验收标准，Review 完整 Git Diff（检查回归、安全、错误处理与无关改动）。
2. **创建 / 更新 PR**：确认工作树干净后运行 `idd pr`（自动汇总 `TASK` 列表与 `Test:` 并关联 `Closes #<id>`）。
3. **CI 校验与自愈**：
   - 运行 `idd ci --watch` 等待结果；若 CI 失败，运行 `idd ci --logs` 拉取失败日志并在原工作树定位修复、本地复测后推送。
   - **同一 CI 失败问题同样严格遵守最多两轮有针对性修复的上限**；两轮后仍未变绿则将对应任务记为 `blocked` 并向用户报告，禁止死循环重试。
   - 若因其他 PR 先合入导致落后或冲突，执行 `git fetch origin main && git rebase origin/main`（解冲突并复测）后 `git push --force-with-lease`。
4. **验收状态**：PR 创建且本地检查/CI 状态明晰后，按用户习惯向用户报告「PR 待验收」或按明确授权直接合入。

---

## 六、线性合入主分支与目录清理（零 Merge 节点）

为了保证 `main` 分支永远是一条干净的直线，且主干不堆积已完成的 `TASK/` 档案，合入阶段统一遵循：

1. **GitHub 线性合入（推荐默认）**：用户验收确认（或已具备明确自动合入授权且 CI 全绿）后，执行：
   ```bash
   idd land <issue#>
   ```
   `idd land` 会自动完成：
   - 核对工作树干净 → `git fetch` 并自动 rebase 到最新 `origin/main`；
   - 在删除 `TASK/<goal>/` 前，先将完整 `Goal`、`Closes #<id>` 与所有 `TASK-XX` / `Test:` 写入 PR 描述与 Squash Commit 正文；
   - 执行 `git rm -rf TASK/<goal>` 并提交清理（若 `evidence/` 含附件且未传 `--force-clean-evidence` 会安全暂停提示）；
   - 通过 `gh pr merge --squash --delete-branch` 以**单条 Squash 提交**直线合入 `main`（自动关闭 Issue、删除远端分支）；
   - 删除本地 Worktree 与特性分支，并快进本地 `main`。
2. **无远端 / 纯本地仓库回退**：按照[Issue 与 Git 协作流 · 纯本地回退](references/git-issue-workflow.md#纯本地无远端回退流程)在临时集成分支完成压缩、删除 `TASK/<goal>/`、变基并与主线 `git merge --ff-only`。
3. 补录历史任务仍先读[补录流程](references/task-records.md#事后补录)，不得伪造事前记录。

---

## 七、执行记录、最终回复与约束

- **执行记录与证据**：任务头部为唯一当前状态源，`Status` 与 `Outcome` 独立记录；`run/` 等忽略目录不能作为唯一长期依据。详情见[任务记录约定](references/task-records.md)。
- **最终回复**：结束本轮开发或恢复执行时，读取[最终回复模板](references/final-reply.md)，按固定结构精简汇报结论、完成内容、验证结果与交付状态（含 Issue、PR、CI 与直线合入情况）。纯咨询或仅建单不套用开发交付报告。
- **执行红线**：
  - 不创建重复规划文档或人工维护的平行索引；
  - 不得为了让测试通过而削弱或删除测试；
  - 除非确有必要且理由充分，否则不要增加依赖；
  - 不修改无关文件，不覆盖用户已有修改；
  - 没有实际运行并通过的测试，绝不能声称通过；
  - 未经明确授权，不执行破坏性操作、部署或越权外部写入；
  - 若当前项目的 `AGENTS.md` 或自身指令更严格，以项目指令为准。
