# TASK-01：静默处理看板客户端断连异常

- Issue: #3
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 包含：
  - 在 `scripts/board_ui.py` 新增 `_CLIENT_DISCONNECT_ERRNOS` 与 `_is_client_disconnect` 辅助判断；
  - 覆写 `BoardHTTPServer.handle_error`，静默忽略客户端断连引发的常见 socket/pipe 异常，保留非断连服务端异常的标准错误输出；
  - 在 `BoardRequestHandler._send_bytes` 中捕获客户端断连异常，设置 `self.close_connection = True` 并安全返回；
  - 将 `BoardRequestHandler.do_GET` 中 `/api/auth/status` 与 `/api/snapshot` 的正常 `_send_json(HTTPStatus.OK, ...)` 调用移出 `try ... except Exception:` 块，避免断连后误触发二次 500 响应写入；
  - 在 `tests/test_monitor_and_board.py` 中补充单元测试及真实本地 HTTP server 断连回归测试。
- 不包含：修改前端轮询间隔或重构其他无关接口。

## 验收标准

- [x] `BoardRequestHandler._send_bytes` 与 `BoardHTTPServer.handle_error` 静默忽略常见客户端断连异常（`BrokenPipeError`、`ConnectionResetError`、`ConnectionAbortedError` 及对应 socket errno），并标记 `close_connection = True`，不向终端打印 Traceback；
- [x] `do_GET` 中 `/api/snapshot` 与 `/api/auth/status` 的正常响应发送移出 `try ... except Exception`，避免断连触发二次 500 写响应，同时保留真实业务异常返回 HTTP 500 与非断连服务端异常的 stderr 输出；
- [x] 在 `tests/test_monitor_and_board.py` 补充单元测试与端到端断连回归测试，且全量单测与 CI 通过。

## 实现注意事项

- 主仓库 `/Users/iamzjt/.agents/skills/idd` 存在未提交文档改动，所有修改与测试仅在隔离工作树 `/Users/iamzjt/.agents/skills/idd-worktrees/3-board-ui-broken-pipe` 内执行；
- `BoardRequestHandler._send_bytes` 若在发送 500 错误响应期间也遇到断连，同样会被静默忽略且不二次抛错；
- 保持原有非断连异常（如 `RuntimeError`）的 HTTP 500 返回与 `BoardHTTPServer.handle_error` 打印行为不变。

## 验证方式

- Command: `python3 -m unittest tests.test_monitor_and_board -v && python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单元测试通过（0 failures / 0 errors），且 `release.py --check` 返回退出码 0。

## 执行结果

- Outcome: passed
- Notes: 已完成 `scripts/board_ui.py` 客户端断连异常静默处理及 `do_GET` 正常响应发送与异常兜底分离，并在 `tests/test_monitor_and_board.py` 补充单元测试与真实进程 RST 断连回归测试；全量 50 项单测与版本一致性校验全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / base `4de1d33` | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v` | passed (13 tests, 23.678s) | `tests/test_monitor_and_board.py`（含 3 项新增断连与异常过滤用例） |
| 2026-11-26 / base `4de1d33` | `python3 -m unittest discover -s tests -v` | passed (50 tests, 69.879s) | `tests/` 全量测试套件 |
| 2026-11-26 / base `4de1d33` | `python3 scripts/release.py --check` | passed (`v0.0.2`) | `SKILL.md == README.md == README.en.md == idd --version` |
