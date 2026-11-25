# IDD（Issue-Driven Development）

面向 Issue 的跨工具开发工作流与共享 CLI 工具。

让 **Claude Code、Codex、Antigravity** 共用同一套工作流规范、Worktree 目录映射与本地命令行工具 `idd`：

> **聊想法建 Issue → 独立 Worktree 并行 / 跨工具无缝接手 → TASK 拆解与真测试 → PR / CI 自愈 → Squash 直线合入 `main` 并清理 `TASK/` 目录**

---

## 目录结构

```text
idd/
├── SKILL.md                    # 核心工作流规范（供 AI Agent 读取）
├── README.md
├── .gitignore
├── references/
│   ├── task-records.md         # TASK 模板、Status/Outcome 状态分离与证据规范
│   ├── git-issue-workflow.md   # Worktree 映射、跨工具接力、CI 自愈与线性合入
│   └── final-reply.md          # 任务完成/受阻交付汇报模板
├── scripts/
│   ├── idd                     # CLI 可执行入口（零第三方依赖，纯 Python 3 标准库）
│   ├── idd_cli.py              # CLI 主实现
│   └── task_status.py          # 只读 TASK 解析与多 Worktree 聚合脚本
└── tests/
    ├── test_task_status.py
    └── test_idd_cli.py
```

---

## 快速安装（新机器配置）

前置条件：本机已安装 `git`、`python3` 与 `gh`（GitHub CLI 并已登录）。

```bash
git clone https://github.com/j-tide/idd.git "$HOME/.agents/skills/idd"

# 挂载技能到 Claude Code、Codex 与 Antigravity
mkdir -p "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.gemini/config/skills" "$HOME/.local/bin"
ln -sfn "$HOME/.agents/skills/idd" "$HOME/.claude/skills/idd"
ln -sfn "$HOME/.agents/skills/idd" "$HOME/.codex/skills/idd"
ln -sfn "$HOME/.agents/skills/idd" "$HOME/.gemini/config/skills/idd"

# 挂载全局共用短命令 idd（确保 ~/.local/bin 在 PATH 中）
chmod +x "$HOME/.agents/skills/idd/scripts/idd" "$HOME/.agents/skills/idd/scripts/task_status.py"
ln -sfn "$HOME/.agents/skills/idd/scripts/idd" "$HOME/.local/bin/idd"
```

---

## `idd` 命令速查

| 命令 | 说明 |
| :--- | :--- |
| `idd status [--open-only] [--local-only] [--json]` | 聚合展示 GitHub Open Issues、所有本地 Worktree 的 `TASK` 进度与 PR / CI 状态 |
| `idd issue create --title "..." [--body "..."] [--label ...]` | 聊完想法后快速创建 GitHub Issue |
| `idd start <issue# \| slug> [--slug ...] [--prefix ...]` | 认领 Issue 创建独立 Worktree 并同步 `.worktreeinclude`；若已存在则幂等复用 |
| `idd sync [issue#] [--dry-run]` | 将当前 Worktree 的 `TASK` 勾选进度同步回 GitHub Issue 正文 |
| `idd pr [issue# \| slug] [--draft] [--dry-run]` | 自动汇总 `TASK` 与提交验证生成结构化描述（含 `Closes #id`）并创建/更新 PR |
| `idd ci [issue# \| pr#] [--watch] [--logs] [--json]` | 查看 PR 的 CI 状态并拉取失败 Job 日志 |
| `idd land [issue# \| slug] [--keep-tasks] [--auto] [--dry-run]` | 自动 Rebase 最新 `main`、持久化汇总、清理 `TASK/<goal>/` 并 Squash 直线合入 |
| `idd cleanup [--dry-run]` | 批量清理 PR 已合并的干净本地 Worktree 与分支 |
| `idd repo-init [--apply]` | 检查或一键将仓库设置为仅允许 Squash Merge 且合入后自动删分支 |
| `idd upgrade [--check]` | 检查或立即拉取远端更新并快进同步本地 `idd` |
| `idd --version` | 查看当前安装的 `idd` 版本号 |

---

## 自动更新说明

- **后台静默安全同步**：运行任意 `idd` 命令且距上次检查超过 6 小时时，会在后台异步检查 `origin/main`（不阻塞当前命令，不污染 `stdout`）；仅当本地技能目录停留在 `main`、工作区完全干净且无未推送提交时才自动 `merge --ff-only`，并在下一次执行时于 `stderr` 提示更新结果。
- **存在本地改动时自动跳过**：若本地有未提交改动或不在 `main` 分支，只提示存在更新而不修改本地文件，可随时运行 `idd upgrade --check` 查看或清理后运行 `idd upgrade` 更新（设置 `IDD_NO_AUTO_UPDATE=1` 可临时禁用后台检测）。

---

## 运行测试

无需安装 `pytest` 或其他外部依赖，直接使用 Python 标准库即可运行全部测试：

```bash
python3 -m unittest discover -s tests -v
```
