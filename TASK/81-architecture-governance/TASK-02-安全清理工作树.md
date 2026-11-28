# TASK-02：安全清理工作树

- Issue: #81
- Status: planned
- Depends on: TASK-01
- Test: tests/test_idd_cli.py, tests/test_monitor_and_board.py

## 任务范围

集中清理资格与实际移除，保留 CLI 批量、dry-run、看板单项结果和两入口既有目录范围。

## 验收标准

- [ ] 两个入口共享删除保护，并发清理可重入、可重试。保留分支，跳过脏工作区和与合入记录不匹配的 HEAD。

## 验证方式

通过对应的 unittest 和实际命令验证上述行为，结果见下表。

## 执行结果

- Outcome: pending

### 验证记录

尚未执行。
