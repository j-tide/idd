# TASK-09：清理预览免写锁

- Issue: #81
- Status: done
- Depends on: TASK-02
- Test: tests/test_worktree_cleanup.py, tests/test_idd_cli.py

## 任务范围与验收标准

- [x] 预览使用与实际移除相同的资格检查，在只读仓库和正在合入的仓库均可返回结果。实际移除持锁复核。

## 执行结果

- Outcome: passed
- Notes: 独立复审发现预览会创建仓库写锁。预览改用相同的只读核验，删除继续持锁；测试证明另一线程持锁时预览仍能返回。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 98d3302 | PYTHONPATH=tests python3 -B -m unittest test_worktree_cleanup test_idd_cli.TestIddCli.test_cleanup_verifies_head_oid_and_preserves_branches test_monitor_and_board.TestMonitorAndBoard.test_board_cleanup_endpoint_security_and_safety_guards | 6 项通过 |
| 2026-11-28 / 98d3302 | 独立复审问题与差异复核 | 实际删除仍在锁内，预览不写锁文件、不夺锁，工作树保留 |
