# TASK-01：改造 PR/MR 汇总正文为结构化 Markdown 并补齐单测

- Issue: 42-pr-summary-markdown
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 修改 `scripts/idd_cli.py`：
  1. `_collect_commit_task_records` 保留提交正文 `extra` 内的段落空行与列表结构；
  2. 新增 `_wrap_inline_code` 与 `_format_test_summary_line` 辅助函数，对 `Test:` 命令部分自动安全包裹反引号（兼容已带反引号、含字面反引号、多段 `; ` 分隔命令及无结果纯文本回退）；
  3. `build_issue_summary` 按方案 A（`### TASK-XX <标题>` + 空行分段 + 保留的 `extra` + `- **Test:** ...`）生成正文，并用 `first_change` 修复单 TASK 无 `issue_title` 时的 `suggested_title` 提取逻辑。
- 更新 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 的相关断言并新增边界单测。
- 不包含 `SKILL.md` 文档同步（由 TASK-02 承接）。

## 验收标准
- [x] `build_issue_summary` 按 `### TASK-XX <标题>` + 空行分段 + `- **Test:** \`<命令>\` — <结果>` 生成正文
- [x] `_collect_commit_task_records` 保留 `extra` 段落空行与子列表，剔除末尾多余空行
- [x] `_format_test_summary_line` 正确处理普通命令、多段 `; ` 命令、自带反引号、字面反引号及无结果回退文本
- [x] 单 TASK 且 `issue_title=None` 时 `suggested_title` 不含 `###` 或 `TASK-01`
- [x] `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 全部通过

## 实现注意事项
- 多段 `; ` 拆分仅在拆分后段数 > 1 且每段均含 `" — "` 时触发，避免把命令自身的 `; `（如 `cmd1; cmd2 — 10 passed`）误拆。
- 仅在 `TASK-*.md` / 提交中实际提取到的命令非空时包裹反引号。

## 验证方式
- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 全部用例通过（退出码 0）。

## 执行结果
- Outcome: passed
- Notes: 已完成 `build_issue_summary` 结构化 Markdown 改造与 `_format_test_summary_line` 边界单测，34 个用例全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_idd_cli.py -v` | passed (23 tests) | `tests/test_idd_cli.py` |
| 2026-11-26 | `python3 -m unittest tests/test_gitlab_forge.py -v` | passed (11 tests) | `tests/test_gitlab_forge.py` |
