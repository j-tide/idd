# Issue 与 Git 协作流

本文件规范 **Issue 认领、多 Worktree 并行隔离、跨工具接力、GitHub/自建 GitLab 双平台 PR/MR 与 CI 自愈、合入前 `TASK/` 清理及直线 Squash 合入** 的完整 Git 操作。

## 1. 一比一命名与路径映射

为防止不同工具（Claude Code、Codex、Antigravity）各自新建散落的分支或工作树，统一由 `idd` CLI 强制约定如下映射：

| 维度 | 命名规范 | 示例（Issue #42） |
| :--- | :--- | :--- |
| Issue 标题 | `<type>: <简明描述>` 或 `<type>(<scope>): <简明描述>`（≤ 50 字符，不重复动词；可选 `scope` 须简短 ≤ 16 字符小写标识，跨模块省去括号） | `feat(export): 支持导出 CSV` |
| Issue 编号 | GitHub / GitLab 仓库 Issue 编号 | `#42` |
| 目录名 / 任务目录 | `<issue>-<slug>` | `42-export-csv` / `TASK/42-export-csv/` |
| 独立工作树路径 | `<主仓库同级>/<仓库名>-worktrees/<issue-dir>`（可用 `IDD_WORKTREE_ROOT` 覆盖） | `../my-app-worktrees/42-export-csv` |
| 开发分支 | `<type>/<issue-dir>`（纯本地无 Issue 为 `<type>/<slug>`） | `feat/42-export-csv` |
| PR / MR 关联 | PR / MR 正文自动带 `Closes #<issue>` | `Closes #42` |

### 允许的 8 类 Issue / 分支 / 提交 `<type>`

> `idd issue create` 默认校验标题前缀与简短 `scope`（≤ 16 字符，支持 `--type`/`--scope` 拼接或 `--raw` 放行）；`idd start` 推断分支前缀时优先读取 `--prefix`，其次读取 Issue 标题中的 `<type>`，最后回退到 Issue Labels 与默认 `feat`。

| `type` | 适用场景 | 分支示例（带 Issue） |
| :--- | :--- | :--- |
| `feat` | 新增功能、UI 页面/样式/动效迭代（默认项） | `feat/42-export-csv` |
| `fix` | 修复 Bug 或异常问题（Issue 标题带 `fix:` 或含 `bug` 标签自动采用） | `fix/43-dark-mode-flicker` |
| `refactor` | 重构代码结构（不改变外部业务行为） | `refactor/44-auth-token` |
| `perf` | 专项性能优化（耗时、内存、包体积、帧率） | `perf/45-table-virtual-scroll` |
| `docs` | 纯文档、注释或说明更新 | `docs/46-setup-guide` |
| `test` | 补充或重构测试代码（无生产逻辑改动） | `test/47-webhook-retry` |
| `ci` | CI/CD 工作流配置调整 | `ci/48-parallel-unittest` |
| `chore` | 依赖升级、构建脚本、工程配置杂项 | `chore/49-bump-deps` |

**禁止前缀（零 Git Hooks 侵入，由 `idd` 命令自动拦截）**：
- 禁止工具/身份前缀：`codex/*`、`claude/*`、`agy/*`、`antigravity/*`、`cursor/*`、`copilot/*`、`ai/*`
- 禁止混写/临时前缀：`feature/*`（用 `feat/*`）、`bugfix/*` / `hotfix/*`（用 `fix/*`）、`tmp/*`、`temp/*`、`wip/*`、`dev/*`

> **关键约束**：永远保留主工作树干净地停留在 `main`（或仓库默认分支），不要在主工作树直接切分支改代码。存在 `origin` 远端时，`idd start` 建分支会使用 `--no-track` 避免错绑 `origin/main`，并立即 `git push -u origin HEAD` 推送到远端。

## 2. 双平台支持（GitHub & 自建 GitLab）

`idd` 根据仓库 `origin` 远端地址自动识别平台，支持 HTTPS、HTTP、SCP（`git@host:group/sub/repo.git`）和自定义端口 SSH（`ssh://git@host:port/group/sub/repo.git`），原生兼容 GitLab 多级子组（`dept/team/repo`）：

- **GitHub**：默认直接复用本机已登录的 `gh` CLI。
- **自建 GitLab**（无需额外安装 `glab`，纯 Python 标准库直连 GitLab REST API v4）：
  ```bash
  # 登录自建 GitLab（保存至 ~/.config/idd/hosts.json，权限 0600，会自动调用 /api/v4/user 校验）
  idd auth login gitlab.company.com --token <Personal-Access-Token>
  # 内网 HTTP 或带端口示例：
  idd auth login http://10.0.0.5:8080 --token <PAT>

  idd auth status
  ```
  也可直接设置环境变量 `GITLAB_TOKEN`；若未配置 Token 但本机已安装登录 `glab`，会自动回退调用 `glab api`。如需强制指定平台，可设置 `IDD_FORGE=gitlab` 或 `github`。

## 3. `.worktreeinclude` 环境初始化

新建的 Git Worktree 默认不包含 `.gitignore` 忽略的本地文件（如 `.env`、`.env.local`、本地调试配置）。

在项目根目录放置 `.worktreeinclude`（每行一个相对 glob 模式，支持 `#` 注释）：

```text
# 创建工作树时自动从主工作树复制，不会覆盖目标目录已存在的文件
.env
.env.local
config/local.*.json
```

运行 `idd start <issue#>` 创建新工作树时会自动同步上述匹配文件。需要安装依赖（如 `pnpm install` / `uv sync`）或生成本地状态时，在新建的工作树内执行即可。

## 4. 跨工具接力规范（Claude / Codex / Antigravity）

在不同工具间交接同一个 Issue 时，**不依赖各自工具的私有聊天历史，全部通过同一工作树 + `TASK/` 文件交接**：

1. **进入或接手 Issue**：新打开任意一个工具，首先在仓库下运行 `idd start <issue#>`。
   - 因为幂等设计，`idd start` 会定位到已经存在的工作树路径，自动修复错绑的上游并为未推分支补推 `origin/<branch>`，输出当前 `git status`、最近 5 条提交与各 `TASK` 的实际状态。
2. **续接现场**：
   - 先运行 `idd status` 或阅读 `TASK/<issue>/TASK-*.md` 与 `git log -5`；
   - 已标 `done` 且验证记录完整的 TASK **绝不重做**；
   - 若正在处理挂掉的 CI，先跑 `idd ci <issue#> --logs` 读失败日志再改代码；
   - 若是 `blocked` 状态，先读“当前阻塞”摘要并核对解除条件是否已满足。
3. **同步进度并推送开发分支**：完成每个 `TASK` 提交后，运行 `idd sync`（在工作树内可省略编号），将 `TASK` 勾选进度写入 Issue 正文的 `<!-- idd:progress:start --> ... <!-- idd:progress:end -->` 受控块中并自动推送当前分支最新提交至 `origin/<branch>`（若为无远端仓库或手工补推，执行 `git push -u origin HEAD`），确保网页端与手机端可实时看到进度条且代码不滞留本地。

## 5. PR / MR 创建与 CI 自愈闭环

1. **发起 / 更新 PR 或 MR**：
   - 确认工作树无未提交改动（`git status --porcelain` 为空）且已完成 Issue 级最终 Review。
   - 运行 `idd pr`（GitLab 也可直接敲别名 `idd mr`，支持 `--draft`、`--title`、`--auto-merge`、`--no-auto-merge`、`--dry-run`）：自动扫描本分支相对于 `origin/<main>` 的提交记录与 `TASK/` 文件，生成包含 `Closes #<id>`、`## 变更内容` 列表与 `## 验证记录` 表格的 PR / MR 描述，推送分支并创建或更新 PR / MR。
2. **PR / MR 自动准入与自动合入开关（`auto_merge`）**：
   - 全局配置：`~/.config/idd/config.json`（默认关闭 `false`）；CLI 支持 `idd config auto-merge [on|off|status]`，看板 `idd board` 顶栏与设置弹窗亦支持实时切换。
   - **禁止擅自覆写或缓存旧开关值**：除非用户本轮显式要求单次覆写，Agent 发起 PR / MR 时应直接运行 `idd pr` / `idd mr`，**不得凭对话早期的 `idd config` 快照自行附加 `--no-auto-merge` / `--auto-merge`**，确保用户中途通过 `idd board` 或 CLI 切换的开关在提 PR 当刻实时生效。
   - 开关开启（或单次传 `--auto-merge`）时：`idd pr` 创建/更新 PR 或 MR 后自动进入阻塞等待 CI 结算（对刚推送分支保留短暂注册宽限期，防远端 CI 尚未注册就被误判为无 CI）。
   - 若远端 CI 通过（`PASS`）或仓库未配置远端 CI（`NONE`）且本地测试已通过，`idd pr` 自动串行执行 `idd land --wait-ci`（Rebase、汇总正文、清理 `TASK/<issue>/`、推送清理提交并等待二次 CI 结算、Squash 直线合入、勾选 Issue 验收框与快进本地 `main`）。
   - **安全暂停条件**：`--draft` PR/MR 自动跳过；CI 失败或超时、Rebase 冲突、`TASK/<issue>/evidence/` 含附件时立即暂停且保留 `TASK/`，交由自愈循环或人工处理。
3. **CI 监控与两轮自愈上限**：
   - 运行 `idd ci --watch` 等待远端 Checks / Pipeline 结束（开关开启时 `idd pr` 已自动等待）；失败时执行 `idd ci --logs` 获取失败 Run/Job 的日志末尾内容（GitLab 自动拉取对应 Job trace）。
   - 回到该工作树分析原因并修复（若属明确新增修复任务，按范围规则追加 `TASK-XX`），本地复测通过后提交并 `git push`。
   - **熔断限制**：同一个 CI 失败问题**最多尝试两轮有针对性的修复与重推**；两轮后仍未通过，将相关任务标为 `blocked` 并记录失败日志摘要向用户汇报。
4. **并行开发导致的分支落后 / 冲突**：
   - 当并行的另一个 PR / MR 先合入 `main` 时，回到当前工作树执行：
     ```bash
     git fetch origin main
     git rebase origin/main
     # 如有冲突，按验收范围解决并复测后：
     git push --force-with-lease
     ```

## 6. 仓库线性设置与 `idd land` 合入清理

### 一次锁定仓库仅 Squash 直线合入（同时保留需求分支）

首次接管仓库时，可检查或一键启用线性合并策略、Squash 默认提交消息模板且合入后保留需求分支（首次在带远端的仓库运行 `idd issue create`、`idd start`、`idd repos add`，或在 `idd ui` 初始化向导连接成功后，默认会自动尝试执行 `--apply`；若传入 `--no-repo-init` 跳过、取消向导勾选或遇到权限失败，会在 `~/.config/idd/repos.json` 记录 `pending` 状态及原因，并在 `idd repos list` 与 `idd ui` 中持续提供一键重试入口）：

```bash
idd repo-init          # 只读检查当前设置
idd repo-init --apply
```

- **GitHub**：关闭 merge commit，开启 squash merge，设置 `delete_branch_on_merge=false`、`squash_merge_commit_title=PR_TITLE`、`squash_merge_commit_message=PR_BODY`（建议同步在 Branch Ruleset 勾选 `Require linear history`）。
- **GitLab**：将项目设置为 `merge_method="ff"`（Fast-Forward 零 Merge 节点）、`squash_option="always"`、`remove_source_branch_after_merge=false`、`squash_commit_template="%{title}\n\n%{description}"`。`idd land` 在修改工作树前检查前两项，并在请求合入时再次核对。

### `idd land` 标准执行顺序

当 PR / MR 已获验收且 CI 绿灯后，执行 `idd land <issue#>`（建议先用 `--dry-run` 预览）；当全局 `auto_merge` 开启时，`idd pr` / `idd mr` 亦会在持锁后直通单轮 CI 与合入流程：

1. **仓库级合入串行队列与自动 Rebase**：非 `dry-run` 路径通过 `<git-common-dir>/idd-land.lock`（支持 `IDD_LAND_LOCK_TIMEOUT`）串行排队，等待方会输出当前持锁分支与 PID 提示；持锁后校验分支名与工作区洁净度、`git fetch origin <base>`，若落后则自动执行 `git rebase`（发生冲突时以退出码 `2` 暂停）。
2. **先持久化汇总，再清理目录**：在删除 `TASK/` 前读取 `TASK/<issue>/` 与提交历史，分别生成结构化 Markdown 写入 PR/MR 描述、以及零 Markdown 纯文本写入 Squash Commit 正文（均含 `Closes #<id>` + 逐 `TASK` 验证清单）。
3. **清理 `TASK/<issue>/` 目录与单轮推送**：默认执行 `git rm -rf TASK/<issue>` 并提交 `chore: 清理已汇总的任务记录 (<issue>)`，随后单次推送远端并创建/更新 PR/MR（传 `--keep-tasks` 可保留）。`idd pr`/`idd mr` 自动合入路径若遇到 CI 失败、超时或冲突，会自动回滚该清理提交以完整保留 `TASK/`。
   - **证据保护**：若 `TASK/<issue>/evidence/` 内存在附件文件，默认会安全拦截并列出清单；需确认附件已不再需要或已转存后，传 `--force-clean-evidence` 才一并清理。
4. **同步 PR/MR、落后止损、Squash 直线合入并收口 Issue 验收框**：等待 head 提交同步与 CI 结算（GitLab 轮询期间若遇 `need_rebase` / `BEHIND` 会立即取消失效流水线并在 `IDD_LAND_MAX_REBASE_ATTEMPTS` 上限内自动重变基重试），随后执行合入。GitLab 核对目标分支新增的 Squash 提交具备唯一父提交且位于目标分支历史链上。使用 `--auto` 时，若 GitLab 尚未合入，命令只报告合入请求待确认。完成核对后默认勾选 Issue 正文「验收标准」节内的复选框并刷新进度，可用 `--no-check-acceptance` 跳过。
5. **默认保留与快进主线**：**默认同时保留本地需求分支与本地 Worktree 目录**（如希望合入时顺带移除工作树目录可显式传 `--rm-worktree`），随后持有 `idd-main-git.lock` 将干净的主工作树 `main` 快进（`git merge --ff-only`）到最新 `origin/main`。

### `idd cleanup` 安全释放工作树磁盘空间

需要清理旧工作树目录释放磁盘时，手动运行 `idd cleanup`（支持 `--dry-run`）：
- **只删工作树目录，绝不删除本地或远端分支**；
- **双重安全校验**：仅当工作树工作区完全干净、且本地当前 `HEAD SHA` 与远端已合入 PR/MR 的 `headRefOid` **完全一致**时才执行 `git worktree remove`；若合入后本地又追加了任何新提交，一律跳过绝不误删。

---

## 纯本地 / 无远端回退流程

当项目**没有配置 GitHub / GitLab 远端**（仅在本地 Git 仓库开发）时，依然保持「一需求一单提交 + 直线历史」（若仓库实际存在 `origin` 远端，即使暂未走 PR/MR 也应先 `git push -u origin HEAD` 备份开发分支）：

1. 在工作树固定已验收提交 `issue_tip=$(git rev-parse HEAD)` 与分叉点 `issue_base=$(git merge-base "$main_branch" "$issue_tip")`。
2. 基于 `TASK/` 与 `git log --reverse "$issue_base..$issue_tip"` 整理出标准需求提交正文写入临时文件 `issue_message`。
3. 从分叉点切出临时本地集成分支并压缩合入：
   ```bash
   git switch -c "integrate/$issue_dir/$issue_tip" "$issue_base"
   git merge --squash "$issue_tip"
   if [ -d "TASK/$issue_dir" ]; then
     git rm -rf "TASK/$issue_dir"   # 若 evidence/ 含须留存附件则先转存或保留
   fi
   git commit --cleanup=verbatim -F "$issue_message"
   git rebase --no-update-refs "$(git rev-parse "$main_branch")"
   ```
4. 在集成分支运行项目级复测后，记录 `issue_commit=$(git rev-parse HEAD)`。
5. 回到干净的主线工作树执行快进合入与复测（多会话并行时用锁串行）：
   ```zsh
   git merge --ff-only "$issue_commit"
   ```
6. 验证通过后可保留需求分支与工作树（按需使用 `git worktree remove` 释放目录），并清理临时 `integrate/*` 分支。
