# TASK-06：并发配置与主机记录

- Issue: #81
- Status: done
- Depends on: TASK-03
- Test: tests/test_local_state.py, tests/test_monitor_and_board.py, tests/test_idd_cli.py

## 任务范围

统一 JSON 原子替换与配置文件锁。CLI 和看板通过逐主机事务保存或移除授权记录。

## 验收标准

- [x] 并发修改不同主机不丢失数据，旧格式、文件权限与 CLI 和看板分别使用的主机名匹配语义保持可验证。

## 验证方式

在隔离配置、工作树或模拟平台上运行上述真实入口的回归测试。

## 执行结果

- Outcome: passed
- Notes: 四处 JSON 写入复用同一原子替换。主机级变更持锁到写回结束，验证不同主机并发保存、两种移除规则、写失败和私有文件权限。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / d0c10f8 | PYTHONPATH=tests python3 -B -m unittest test_local_state test_monitor_and_board.TestMonitorAndBoard.test_board_in_browser_token_save_status_logout_and_repo_links test_monitor_and_board.TestMonitorAndBoard.test_concurrent_processes_register_and_update_repos_without_data_loss test_monitor_and_board.TestMonitorAndBoard.test_board_auto_repo_init_on_token_save_and_manual_retry_endpoint test_idd_cli.TestIddCli.test_config_auto_merge_global_only_and_persistence test_idd_cli.TestIddCli.test_safe_auto_update_and_upgrade_command test_gitlab_forge.TestGitLabForge.test_self_hosted_gitlab_end_to_end_workflow | 8 项通过 |
| 2026-11-28 / d0c10f8 | PYTHONPATH=tests python3 -B -m unittest test_local_state | 2 项通过 |
| 2026-11-28 / d0c10f8 | OCR 本地规则与 Git 差异复审 | 5 个源文件全部复核，核对目录 0700、凭据文件 0600 及注册表和升级缓存既有错误语义 |
