# TASK-10：认证探测失败可恢复

- Issue: #81
- Status: done
- Depends on: TASK-03
- Test: tests/test_monitor_and_board.py

## 任务范围与验收标准

- [x] 线程未能启动或同步探测中断时，既有等待方能得到异常，后续调用可以重新探测。

## 执行结果

- Outcome: passed
- Notes: 后台工作线程成功启动后才公布 Future。同步探测异常或中断会结算旧 Future，下一次调用能重新加载。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / a57858d | PYTHONPATH=tests python3 -B -m unittest test_monitor_and_board.TestMonitorAndBoard.test_auth_probe_recovers_from_worker_start_failure_and_interruption test_monitor_and_board.TestMonitorAndBoard.test_auth_refresh_cannot_overwrite_a_new_identity_after_invalidation test_monitor_and_board.TestMonitorAndBoard.test_forge_connections_states_and_gh_username_parsing test_monitor_and_board.TestMonitorAndBoard.test_board_forge_connections_transitions_auth_connected_and_offline | 4 项通过 |
| 2026-11-28 / a57858d | 复审故障注入 | 线程创建失败、同步中断、重新探测和旧结果失效均有回归覆盖 |
