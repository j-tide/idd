# TASK-01：看板工作树单步安全清理接口 /api/cleanup

- Issue: #67
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py (test_board_cleanup_endpoint_security_and_safety_guards)

## 任务范围
- 在 `scripts/board_ui.py` 新增 `_MergedChangesCache`（60s TTL 缓存已合入 PR/MR 列表并支持按分支回退）与 `_cleanup_single_worktree()`。
- 在 `BoardRequestHandler.do_POST` 新增 `POST /api/cleanup` 接口，复用本地 CSRF 校验与监控仓库白名单校验。
- 在 `tests/test_monitor_and_board.py` 补充后端单步清理、安全门禁、白名单与缓存行为测试。
- 不包含前端 UI 弹窗与动效改动（由 TASK-02 负责）。

## 验收标准
- [x] `POST /api/cleanup` 强制校验 `X-IDD-Request` / 同源 `Origin` 与目标仓库白名单，缺失或越权返回 403/400。
- [x] 复用与 `idd cleanup` 一致的安全门禁：拒绝主工作树、跳过脏工作区（`skipped_dirty`）、跳过未合入或 `headRefOid != HEAD`（`skipped_unmerged`）、仅执行 `git worktree remove`（不传 `--force`，绝不删分支）。
- [x] `_MergedChangesCache` 在 TTL 内复用仓库级已合入 PR/MR 列表，避免批量清理时 N+1 远端查询；已移除目录幂等返回 `already_removed`。

## 实现注意事项
- 保持 `BoardRequestHandler.__init__` 向后兼容（`merged_cache` 默认为 `None`），确保现有 `_make_handler` 测试不破坏。
- 允许分支前缀沿用 `CLEANUP_ALLOWED_PREFIXES` 与受管工作树根目录检查。

## 验证方式
- Command: `python3 -m unittest tests.test_monitor_and_board.TestMonitorAndBoard.test_board_cleanup_endpoint_security_and_safety_guards -v`
- Expected: 测试全部通过，覆盖 CSRF/白名单/脏工作区/SHA 不一致/正常清理与缓存命中。

## 执行结果
- Outcome: passed
- Notes: 已实现 `_MergedChangesCache`、`_cleanup_single_worktree` 与 `POST /api/cleanup` 接口并补充单测，安全门禁与缓存命中全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board.TestMonitorAndBoard.test_board_cleanup_endpoint_security_and_safety_guards -v` | passed (1 passed in 8.558s) | [tests/test_monitor_and_board.py](../../tests/test_monitor_and_board.py) |
