# TASK-01：跨进程配置锁与仓库级文件锁

- Issue: #79
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py, tests/test_idd_cli.py

## 任务范围
- 在 `scripts/monitor.py` 为 `config.json` 与 `repos.json` 的读写函数引入基于 `fcntl.flock` 的跨进程文件锁（`.config.lock` / `.repos.lock`），在既有线程锁内层加锁，无 `fcntl` 平台优雅降级。
- 在 `scripts/idd_cli.py` 新增 `_resolve_git_common_dir` 与可重入跨进程文件锁 `_repo_file_lock`（`LOCK_EX | LOCK_NB` 探测持锁者信息并打印排队提示，支持阻塞或配置超时退出码 `3`）。
- 使用 `idd-main-git.lock` 串行保护 `cmd_start`、`_execute_land` Step G 与 `cmd_cleanup` 中对共享 `main_worktree` 的 Git 写操作。
- 在 `tests/test_monitor_and_board.py` 与 `tests/test_idd_cli.py` 补齐多进程并发与锁重入/超时测试。

## 验收标准
- [x] `repos.json` 与 `config.json` 多进程并发读写不丢失记录、不损坏 JSON
- [x] `_repo_file_lock` 支持同进程安全重入、跨进程互斥排队打印持锁者信息及超时退出码 `3`
- [x] `cmd_start` / `_execute_land` Step G / `cmd_cleanup` 对共享 `main_worktree` 的写操作均持有 `idd-main-git.lock`
- [x] 新增单测与既有相关测试全部通过

## 实现注意事项
- 永远先获取线程锁（`_REPOS_LOCK` / `_CONFIG_LOCK`）再获取文件锁 `_file_lock`，避免锁序颠倒。
- 持锁元数据 JSON 仅在成功拿锁后覆写，异常退出时在 `finally` 中清空内容并释放 `flock`。

## 验证方式
- Command: `python3 -m unittest tests.test_monitor_and_board tests.test_idd_cli -v`
- Expected: 新增与既有测试全部通过

## 执行结果

- Outcome: passed
- Notes: 已在 `scripts/monitor.py` 为配置与仓库索引加上 `fcntl.flock` 跨进程锁，在 `scripts/idd_cli.py` 新增 `_repo_file_lock` 与 `idd-main-git.lock` 保护，并补齐多进程并发注册与重入/超时测试，4 个针对性用例全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-28 (worktree) | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board.TestMonitorAndBoard.test_concurrent_processes_register_and_update_repos_without_data_loss test_monitor_and_board.TestMonitorAndBoard.test_board_auto_merge_config_endpoints_security_and_ui_script test_idd_cli.TestIddCli.test_repo_file_lock_reentrant_cross_process_wait_and_timeout test_idd_cli.TestIddCli.test_config_auto_merge_global_only_and_persistence -v` | passed (4 passed, 0 failed) | `scripts/monitor.py`, `scripts/idd_cli.py`, `tests/test_monitor_and_board.py`, `tests/test_idd_cli.py` |
