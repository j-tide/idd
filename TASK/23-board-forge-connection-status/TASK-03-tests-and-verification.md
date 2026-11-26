# TASK-03：自动化测试覆盖与全量回归验证

- Issue: #23
- Status: done
- Depends on: TASK-01, TASK-02
- Test: tests/test_monitor_and_board.py

## 任务范围

1. 在 `tests/test_monitor_and_board.py` 新增 `test_forge_connections_states_and_gh_username_parsing` 验证 `_check_gh_cli_status` 与 `_build_forge_connections` 全状态转换。
2. 扩展 `test_board_web_server_serves_offline_ui_and_live_snapshots` 校验新顶栏 DOM ID 与前端方法存在及 JS 语法。
3. 新增端到端测试 `test_board_forge_connections_transitions_auth_connected_and_offline` 验证真实 HTTP 服务下 GitLab 从待配置 -> 已连接 -> 鉴权失效 -> 离线不可达的实时状态流转。
4. 运行全量测试套件验证无回归。

## 验收标准

- [x] 新增单元测试与端到端集成测试真实运行并全部通过
- [x] 全量测试 `python3 -m unittest discover -s tests -v` 全部通过

## 实现注意事项

- 保持测试环境完全隔离（`IDD_CONFIG_DIR`、`IDD_NO_BROWSER=1`、MockGitLabState）。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全部测试用例通过。

## 执行结果

- Outcome: passed
- Notes: 已补充单元测试与实时服务端到端流转测试，全量测试 69 项全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed (69 passed) | `tests/test_monitor_and_board.py` |
