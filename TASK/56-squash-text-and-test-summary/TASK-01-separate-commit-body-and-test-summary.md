# TASK-01：分离 Squash 纯文本正文并优化多测试汇总展示

- Issue: 56-squash-text-and-test-summary
- Status: done
- Depends on: none
- Test: `tests/test_idd_cli.py`, `tests/test_gitlab_forge.py`

## 任务范围
- 在 `scripts/idd_cli.py` 中：
  - `_collect_commit_task_records()` 支持同一提交内多行 `Test:` 累加；
  - 新增测试条目拆分与命令精简解析辅助函数，支持 `; ` 混合检查项拆解与常见执行器（`pytest`、`unittest`、`pnpm`/`npm`/`yarn`/`bun`、`vitest`/`jest`/`mocha`/`go test`/`cargo test`）精简标签与多文件计数；
  - `build_issue_summaries()` 同时产出结构化 Markdown（用于 PR/MR 描述，命令被精简时附 `<details><summary>完整验证命令</summary>`）与零 Markdown 符号的干净纯文本（用于 `idd land` 写入 Squash Commit 与 `--dry-run` 预览）；保持 `build_issue_summary()` 2 元组兼容；
  - `cmd_land()` 将 Markdown 写入 PR/MR 描述，将纯文本写入 Squash Commit。
- 在 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 中补充单测与端到端校验。
- 不包含：不做 Git Diff AST 用例增删改自动统计。

## 验收标准

- [x] 提交内多行 `Test:` 累加、混合 `; ` 检查项正确拆解并精简长命令/多文件列表
- [x] `idd pr` / `idd mr` 保持 Markdown 并按需附可折叠完整命令块（无精简时不冗余输出）
- [x] `idd land` 将 Markdown 写入 PR/MR、将零 Markdown 纯文本写入 Squash Commit 及 `--dry-run` 预览
- [x] `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 全部通过

## 实现注意事项

- 保留 `_format_test_summary_line()` 与 `build_issue_summary()` 现有接口兼容。
- 折叠块 `<summary>` 后与 `</details>` 前各保留空行，确保 GitHub 与 GitLab 均正确渲染内部 Markdown 列表。
- 列表项内命令与结果之间继续使用 ` — ` 分隔，避免含冒号的脚本名（如 `pnpm test:architecture`）出现双冒号。

## 验证方式

- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 全部测试通过且无失败或报错

## 执行结果

- Outcome: passed
- Notes: 已分离 PR/MR 的 Markdown 汇总与 Squash Commit 的零 Markdown 纯文本正文，并支持多行 `Test:` 累加、混合 `; ` 拆分与长命令精简折叠。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v` | 35 passed | `tests/test_idd_cli.py`, `tests/test_gitlab_forge.py` |
