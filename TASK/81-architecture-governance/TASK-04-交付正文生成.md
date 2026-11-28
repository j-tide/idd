# TASK-04：交付正文生成

- Issue: #81
- Status: done
- Depends on: TASK-01
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围

将 PR 和 Squash 的交付记录生成收拢到明确的模块，一次解析测试记录并生成两种格式。

## 验收标准

- [x] GitHub/GitLab 的正文、表格转义、长命令和纯文本空行契约通过。

## 验证方式

通过对应的 unittest 和实际命令验证上述行为，结果见下表。

## 执行结果

- Outcome: passed
- Notes: 每条 Test 记录只解析一次，Markdown 表格与纯文本共用结构化结果。GitHub 的正文临时文件由一个出口创建与清理。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / cb14c66 | PYTHONPATH=tests python3 -B -m unittest test_idd_cli test_gitlab_forge test_task_status | 56 项通过 |
| 2026-11-28 / cb14c66 | PYTHONPATH=tests python3 -B -m unittest test_idd_cli.TestIddCli.test_repo_init_and_issue_create test_idd_cli.TestIddCli.test_sync_updates_issue_progress_idempotently test_idd_cli.TestIddCli.test_pr_ci_and_land_full_linear_flow test_idd_cli.TestIddCli.test_verification_table_formats_supported_commands | 4 项通过 |
| 2026-11-28 / cb14c66 | 同一工作树的迁移前后正文逐字节比较 | 标题 67 字节、PR Markdown 2092 字节、Squash 纯文本 721 字节完全相同 |
| 2026-11-28 / cb14c66 | OCR 本地规则与 Git 差异复审 | 4 个源文件全部复核，11 个原验证样例改由真实 Git 提交及最终 PR 表格验证 |
