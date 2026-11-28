# TASK-02：安全清理工作树

- Issue: #81
- Status: done
- Depends on: TASK-01
- Test: tests/test_worktree_cleanup.py, tests/test_idd_cli.py, tests/test_monitor_and_board.py, tests/test_gitlab_forge.py

## 任务范围

集中清理资格与实际移除，保留 CLI 批量、dry-run、看板单项结果和两入口既有目录范围。

## 验收标准

- [x] 两个入口共享删除保护，并发清理可重入、可重试。保留分支，跳过脏工作区和与合入记录不匹配的 HEAD。

## 验证方式

通过对应的 unittest 和实际命令验证上述行为，结果见下表。

## 执行结果

- Outcome: passed
- Notes: 两个入口共用仓库锁和锁内复核。临时 Git 工作树验证了并发重复清理、不同线程的互斥、HEAD 变化以及原分支保留。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 0b8d86c | PYTHONPATH=tests python3 -B -m unittest test_worktree_cleanup test_idd_cli.TestIddCli.test_cleanup_verifies_head_oid_and_preserves_branches test_idd_cli.TestIddCli.test_repo_file_lock_reentrant_cross_process_wait_and_timeout test_idd_cli.TestIddCli.test_concurrent_pr_auto_merge_serializes_via_land_lock test_monitor_and_board.TestMonitorAndBoard.test_board_cleanup_endpoint_security_and_safety_guards test_gitlab_forge.TestGitLabForge.test_gitlab_mr_auto_rebase_when_behind_and_concurrent_mr_serialization | 8 项通过 |
| 2026-11-28 / 0b8d86c | OCR 本地规则与 Git 差异复审 | 4 个源文件全部复核，收紧了缺失 HEAD 和公共目录的错误处理，复测通过 |
