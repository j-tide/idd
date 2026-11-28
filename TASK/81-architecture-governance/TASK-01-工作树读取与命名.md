# TASK-01：工作树读取与命名

- Issue: #81
- Status: done
- Depends on: none
- Test: tests/test_task_status.py, tests/test_idd_cli.py, tests/test_install_uninstall.py

## 任务范围

统一 Git 工作树清单解析和八类工作分支规则，迁移 TASK 工具、CLI 和看板，安装样本从实际运行目录构造。

## 验收标准

- [x] 工作树路径、顺序、游离状态、命名校验和安装后的 CLI 与既有契约一致。

## 验证方式

通过对应的 unittest 和实际命令验证上述行为，结果见下表。

## 执行结果

- Outcome: passed
- Notes: CLI、监控、看板和独立任务脚本使用同一个 Git 清单，命名与安装测试调用方已迁移。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 579903a | 原始提交 python3 -m unittest discover -s tests -v | 107 项通过 |
| 2026-11-28 / 579903a | PYTHONPATH=tests python3 -m unittest test_task_status test_idd_cli.TestIddCli.test_branch_naming_enforces_eight_types_and_blocks_tool_prefixes test_idd_cli.TestIddCli.test_issue_title_validation_short_scope_and_flags test_idd_cli.TestIddCli.test_issue_create_cli_validation_and_start_title_inference test_idd_cli.TestIddCli.test_pr_and_land_avoid_duplicate_conventional_title_prefixes test_install_uninstall test_monitor_and_board.TestMonitorAndBoard.test_auto_global_status_from_non_git_dir_and_worktree_live_pulse test_monitor_and_board.TestMonitorAndBoard.test_board_cleanup_endpoint_security_and_safety_guards | 25 项通过 |
| 2026-11-28 / 579903a | OCR 本地规则与 Git 差异复审 | 7 个源文件全部复核，另核验安装及任务测试 |
