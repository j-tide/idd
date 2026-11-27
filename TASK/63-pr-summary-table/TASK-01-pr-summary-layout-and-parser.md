# TASK-01：重构 PR/MR 汇总正文为变更列表与验证表格并修复命令解析

- Issue: #63
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py tests/test_gitlab_forge.py

## 任务范围
- 将 `scripts/idd_cli.py` 中 `build_issue_summaries` 生成的 PR/MR Markdown 正文重构为 `## 变更内容`（紧凑任务列表，支持提交补充说明缩进展示）+ `## 验证记录`（Markdown 表格，多条检查逐行对齐，安全转义 `|` 与换行），保留末尾 `<details><summary>完整验证命令</summary>` 折叠块。
- 修复命令解析与渲染缺陷：
  1. `_unwrap_inline_code_with_note` 处理外层反引号后紧跟括号备注（如 `` `pnpm ...` (CI ...) ``），避免反引号外露或括号被误删。
  2. `_split_top_level_semicolons` 仅在括号与反引号之外拆分 `; `，避免结果括号内的 `; ` 拆成多行。
  3. 结构化命令摘要将中文目标统计（如 `3 个测试文件`）与缩短后的单文件名移出外层大代码块，`&&` 复合命令拆分为独立行内代码并以 `、` 连接。
  4. 深层/超长单文件路径缩短为文件名并在 `<details>` 中保留完整命令。
- 保持 `idd land` 生成的 Squash Commit 纯文本正文（`commit_plain_body`）零 Markdown 格式。
- 同步更新并扩充 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 单测。
- 不包含：修改 `SKILL.md` 与 `references/git-issue-workflow.md`（由 TASK-02 负责）。

## 验收标准

- [x] `build_issue_summaries` 生成 `## 变更内容` 列表与 `## 验证记录` 表格，无 `### TASK-XX` 标题；提交补充说明正确缩进挂在对应任务下。
- [x] 外层反引号+括号备注、括号内 `; `、中文统计外置、`&&` 独立代码块、超长单文件路径缩短、表格内 `|` 转义全部覆盖并通过单测。
- [x] Squash Commit 纯文本正文保持零 Markdown 符号。
- [x] `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 全部通过。

## 实现注意事项

- 表格单元格内即使是行内代码中的 `|` 也会在 GitHub/GitLab 触发分列，必须统一转义为 `\|`。
- `_unwrap_inline_code_with_note` 需检查括号平衡且不含反引号，避免把 `` `cmd1` (a) && `cmd2` (b) `` 误当成整段反引号加备注。
- 仅拆解 `&&` 或剥离外层反引号但不缩短命令时，不应标记 `simplified=True` 生成冗余 `<details>`。
- 任务模板中 `- Test: 未记录` 在无提交 `Test:` 时回退为 `未记录`，避免渲染成 `` `未记录` | done ``。

## 验证方式

- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 全部测试用例通过（0 failures / 0 errors）。

## 执行结果

- Outcome: passed
- Notes: 已完成 PR/MR 表格重构、命令解析修复与全部回归单测。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v` | passed (36 tests) | `tests/test_idd_cli.py`, `tests/test_gitlab_forge.py` |
