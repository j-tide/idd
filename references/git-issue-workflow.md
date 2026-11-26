# Issue 与 Git 协作流

本文件规范 **Issue 认领、多 Worktree 并行隔离、跨工具接力、GitHub/自建 GitLab 双平台 PR/MR 与 CI 自愈、合入前 `TASK/` 清理及直线 Squash 合入** 的完整 Git 操作。

## 1. 一比一命名与路径映射

为防止不同工具（Claude Code、Codex、Antigravity）各自新建散落的分支或工作树，统一由 `idd` CLI 强制约定如下映射：

| 维度 | 命名规范 | 示例（Issue #42） |
| :--- | :--- | :--- |
| Issue | GitHub / GitLab 仓库 Issue 编号 | `#42` |
| 目录名 / 任务目录 | `<issue>-<slug>` | `42-export-csv` / `TASK/42-export-csv/` |
| 独立工作树路径 | `<主仓库同级>/<仓库名>-worktrees/<issue-dir>`（可用 `IDD_WORKTREE_ROOT` 覆盖） | `../my-app-worktrees/42-export-csv` |
| 开发分支 | `<type>/<issue-dir>`（纯本地无 Issue 为 `<type>/<slug>`） | `feat/42-export-csv` |
| PR / MR 关联 | PR / MR 正文自动带 `Closes #<issue>` | `Closes #42` |

### 允许的 8 类分支与提交 `<type>`

| `type` | 适用场景 | 分支示例（带 Issue） |
| :--- | :--- | :--- |
| `feat` | 新增功能、UI 页面/样式/动效迭代（默认项） | `feat/42-export-csv` |
| `fix` | 修复 Bug 或异常问题（Issue 含 `bug` 标签自动采用） | `fix/43-dark-mode-flicker` |
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
   - 运行 `idd pr`（GitLab 也可直接敲别名 `idd mr`，支持 `--draft`、`--title`、`--dry-run`）：自动扫描本分支相对于 `origin/<main>` 的提交记录与 `TASK/` 文件，生成包含 `Closes #<id>` 以及按顺序排列的 `TASK-XX` / `Test:` 块，推送分支并创建或更新 PR / MR。
2. **CI 监控与两轮自愈上限**：
   - 运行 `idd ci --watch` 等待远端 Checks / Pipeline 结束；失败时执行 `idd ci --logs` 获取失败 Run/Job 的日志末尾内容（GitLab 自动拉取对应 Job trace）。
   - 回到该工作树分析原因并修复（若属明确新增修复任务，按范围规则追加 `TASK-XX`），本地复测通过后提交并 `git push`。
   - **熔断限制**：同一个 CI 失败问题**最多尝试两轮有针对性的修复与重推**；两轮后仍未通过，将相关任务标为 `blocked` 并记录失败日志摘要向用户汇报。
3. **并行开发导致的分支落后 / 冲突**：
   - 当并行的另一个 PR / MR 先合入 `main` 时，回到当前工作树执行：
     ```bash
     git fetch origin main
     git rebase origin/main
     # 如有冲突，按验收范围解决并复测后：
     git push --force-with-lease
     ```

## 6. 仓库线性设置与 `idd land` 合入清理

### 一次锁定仓库仅 Squash 直线合入（同时保留需求分支）

首次接管仓库时，可检查或一键启用线性合并策略且合入后保留需求分支（首次在带远端的仓库运行 `idd issue create`、`idd start` 或 `idd repos add` 时，CLI 也会自动只读探测一次并在未锁定该策略时输出一次性 `💡 首次接管提示`，结果记录于 `~/.config/idd/repos.json` 的 `repo_init_state`；Agent 看到提示后先向用户确认，再执行 `--apply`）：

```bash
idd repo-init          # 只读检查当前设置
idd repo-init --apply
```

- **GitHub**：关闭 merge commit，开启 squash merge，设置 `delete_branch_on_merge=false`（建议同步在 Branch Ruleset 勾选 `Require linear history`）。
- **GitLab**：将项目设置为 `merge_method="ff"`（Fast-Forward 零 Merge 节点）、`squash_option="always"`、`remove_source_branch_after_merge=false`。

### `idd land` 标准执行顺序

当 PR / MR 已获验收且 CI 绿灯后，执行 `idd land <issue#>`（建议先用 `--dry-run` 预览）：

1. **检查洁净度、分支名与自动 Rebase**：校验分支名合法且工作树干净后 `git fetch origin <base>`；若分支落后于 `origin/<base>` 自动执行 `git rebase`（发生冲突时以退出码 `2` 暂停并列出冲突文件，等待解决并 `git rebase --continue`）。
2. **先持久化汇总，再清理目录**：在删除 `TASK/` 前读取 `TASK/<issue>/` 与提交历史生成完整的 `Closes #<id>` + 逐 `TASK` 验证清单。
3. **清理 `TASK/<issue>/` 目录**：默认执行 `git rm -rf TASK/<issue>` 并提交 `chore: 清理已汇总的任务记录 (<issue>)`，确保 `main` 主干不堆积临时任务目录（传 `--keep-tasks` 可保留）。
   - **证据保护**：若 `TASK/<issue>/evidence/` 内存在附件文件，默认会安全拦截并列出清单；需确认附件已不再需要或已转存后，传 `--force-clean-evidence` 才一并清理。
4. **同步 PR/MR、Squash 直线合入并收口 Issue 验收框**：刷新描述、如有新提交则 `--force-with-lease` 推送；确认 CI 通过后执行 Squash 直线合入（保留远端分支；若刚强推需要等新一轮 CI，可传 `--auto` 挂起自动合入）。真正完成合入后默认自动勾选 Issue 正文「验收标准」节内未勾选的复选框并保底刷新 `TASK` 进度块（传 `--no-check-acceptance` 可跳过，`--auto` 等待 CI 时不提前勾选）。
5. **默认保留与快进主线**：**默认同时保留本地需求分支与本地 Worktree 目录**（如希望合入时顺带移除工作树目录可显式传 `--rm-worktree`），随后将干净的主工作树 `main` 快进（`git merge --ff-only`）到最新 `origin/main`。

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
