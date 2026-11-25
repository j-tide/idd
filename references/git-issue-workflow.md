# Issue 与 Git 协作流

本文件规范 **Issue 认领、多 Worktree 并行隔离、跨工具接力、PR 与 CI 自愈、合入前 `TASK/` 清理及直线 Squash 合入** 的完整 Git 操作。

## 1. 一比一命名与路径映射

为防止不同工具（Claude Code、Codex、Antigravity）各自新建散落的分支或工作树，统一由 `idd` CLI 强制约定如下映射：

| 维度 | 命名规范 | 示例（Issue #42） |
| :--- | :--- | :--- |
| Issue | GitHub 仓库 Issue 编号 | `#42` |
| 目标名 / 任务目录 | `<issue>-<slug>` | `42-export-csv` / `TASK/42-export-csv/` |
| 独立工作树路径 | `<主仓库同级>/<仓库名>-worktrees/<目标名>`（可用 `IDD_WORKTREE_ROOT` 覆盖） | `../my-app-worktrees/42-export-csv` |
| 开发分支 | `feat/<目标名>`（含 `bug`/`fix` 标签时默认 `fix/<目标名>`） | `feat/42-export-csv` |
| PR 关联 | PR 正文自动带 `Closes #<issue>` | `Closes #42` |

> **关键约束**：永远保留主工作树干净地停留在 `main`（或仓库默认分支），不要在主工作树直接切分支改代码。

## 2. `.worktreeinclude` 环境初始化

新建的 Git Worktree 默认不包含 `.gitignore` 忽略的本地文件（如 `.env`、`.env.local`、本地调试配置）。

在项目根目录放置 `.worktreeinclude`（每行一个相对 glob 模式，支持 `#` 注释）：

```text
# 创建工作树时自动从主工作树复制，不会覆盖目标目录已存在的文件
.env
.env.local
config/local.*.json
```

运行 `idd start <issue#>` 创建新工作树时会自动同步上述匹配文件。需要安装依赖（如 `pnpm install` / `uv sync`）或生成本地状态时，在新建的工作树内执行即可。

## 3. 跨工具接力规范（Claude / Codex / Antigravity）

在不同工具间交接同一个需求时，**不依赖各自工具的私有聊天历史，全部通过同一工作树 + `TASK/` 文件交接**：

1. **进入或接手任务**：新打开任意一个工具，首先在仓库下运行 `idd start <issue#>`。
   - 因为幂等设计，`idd start` 会定位到已经存在的工作树路径，并输出当前 `git status`、最近 5 条提交与各 `TASK` 的实际状态。
2. **续接现场**：
   - 先运行 `idd status` 或阅读 `TASK/<目标名称>/TASK-*.md` 与 `git log -5`；
   - 已标 `done` 且验证记录完整的 TASK **绝不重做**；
   - 若正在处理挂掉的 CI，先跑 `idd ci <issue#> --logs` 读失败日志再改代码；
   - 若是 `blocked` 状态，先读“当前阻塞”摘要并核对解除条件是否已满足。
3. **同步进度到 GitHub**：完成关键 TASK 后运行 `idd sync`（在工作树内可省略编号），将 `TASK` 勾选进度写入 Issue 正文的 `<!-- idd:progress:start --> ... <!-- idd:progress:end -->` 受控块中，网页端与手机端可实时看到原生进度条，同时不会破坏 Issue 原本的正文内容。

## 4. PR 创建与 CI 自愈闭环

1. **发起 / 更新 PR**：
   - 确认工作树无未提交改动（`git status --porcelain` 为空）且已完成目标级最终 Review。
   - 运行 `idd pr`（支持 `--draft`、`--title`、`--dry-run`）：自动扫描本分支相对于 `origin/<main>` 的提交记录与 `TASK/` 文件，生成包含 `Goal:`、`Closes #<id>` 以及按顺序排列的 `TASK-XX` / `Test:` 块，推送分支并创建（或更新已有）PR。
2. **CI 监控与两轮自愈上限**：
   - 运行 `idd ci --watch` 等待远端 Checks 结束；失败时执行 `idd ci --logs` 获取失败 Run 的日志末尾内容。
   - 回到该工作树分析原因并修复（若属明确新增修复任务，按范围规则追加 `TASK-XX`），本地复测通过后提交并 `git push`。
   - **熔断限制**：同一个 CI 失败问题**最多尝试两轮有针对性的修复与重推**；两轮后仍未通过，将相关任务标为 `blocked` 并记录失败 Run 链接与日志摘要向用户汇报。
3. **并行开发导致的分支落后 / 冲突**：
   - 当并行的另一个 PR 先合入 `main` 时，回到当前工作树执行：
     ```bash
     git fetch origin main
     git rebase origin/main
     # 如有冲突，按验收范围解决并复测后：
     git push --force-with-lease
     ```

## 5. 仓库线性设置与 `idd land` 合入清理

### 一次锁定仓库仅 Squash 合入

首次接管仓库时，可检查或一键启用仅允许 Squash Merge 与自动清理远端分支：

```bash
idd repo-init          # 只读检查当前设置
idd repo-init --apply  # 等价于 PATCH allow_merge_commit=false, allow_squash_merge=true, delete_branch_on_merge=true
```

*(底层使用 `gh api -X PATCH repos/{owner}/{repo} -F allow_merge_commit=false -F allow_squash_merge=true -F delete_branch_on_merge=true`，建议同步在 GitHub Branch Ruleset 勾选 `Require linear history`。)*

### `idd land` 标准执行顺序

当 PR 已获验收且 CI 绿灯后，执行 `idd land <issue#>`（建议先用 `--dry-run` 预览）：

1. **检查洁净度与自动 Rebase**：确认工作树干净后 `git fetch origin <base>`；若分支落后于 `origin/<base>` 自动执行 `git rebase`（发生冲突时以退出码 `2` 暂停并列出冲突文件，等待解决并 `git rebase --continue`）。
2. **先持久化汇总，再清理目录**：在删除 `TASK/` 前读取 `TASK/<目标>/` 与提交历史生成完整的 `Goal` + `Closes #<id>` + 逐 `TASK` 验证清单。
3. **清理 `TASK/<目标>/` 目录**：默认执行 `git rm -rf TASK/<目标>` 并提交 `chore: 清理已汇总的任务记录 (<目标>)`，确保 `main` 主干不堆积临时任务目录（传 `--keep-tasks` 可保留）。
   - **证据保护**：若 `TASK/<目标>/evidence/` 内存在附件文件，默认会安全拦截并列出清单；需确认附件已不再需要或已转存后，传 `--force-clean-evidence` 才一并清理。
4. **同步 PR 并 Squash 直线合入**：刷新 PR 正文、如有新提交则 `--force-with-lease` 推送；确认 CI 通过后执行 `gh pr merge --squash --delete-branch`（若刚强推需要等新一轮 CI，可传 `--auto` 挂起自动合入，合入完成后再跑 `idd cleanup`）。
5. **本地回收**：自动 `git worktree remove` 删除当前工作树、`git branch -D` 删除本地分支，并尝试将干净的主工作树 `main` 快进（`git merge --ff-only`）到最新 `origin/main`。

---

## 纯本地 / 无远端回退流程

当项目没有配置 GitHub/GitLab 远端（仅在本地 Git 仓库开发）时，依然保持「一需求一单提交 + 直线历史」：

1. 在工作树固定已验收提交 `goal_tip=$(git rev-parse HEAD)` 与分叉点 `goal_base=$(git merge-base "$main_branch" "$goal_tip")`。
2. 基于 `TASK/` 与 `git log --reverse "$goal_base..$goal_tip"` 整理出标准需求提交正文写入临时文件 `goal_message`。
3. 从分叉点切出临时本地集成分支并压缩合入：
   ```bash
   git switch -c "integrate/$goal_name/$goal_tip" "$goal_base"
   git merge --squash "$goal_tip"
   if [ -d "TASK/$goal_name" ]; then
     git rm -rf "TASK/$goal_name"   # 若 evidence/ 含须留存附件则先转存或保留
   fi
   git commit --cleanup=verbatim -F "$goal_message"
   git rebase --no-update-refs "$(git rev-parse "$main_branch")"
   ```
4. 在集成分支运行项目级复测后，记录 `goal_commit=$(git rev-parse HEAD)`。
5. 回到干净的主线工作树执行快进合入与复测（多会话并行时用锁串行）：
   ```zsh
   git merge --ff-only "$goal_commit"
   ```
6. 验证通过后清理工作树与临时分支；原始需求分支若需留存可在确认前保留，否则随工作树一并清理。
