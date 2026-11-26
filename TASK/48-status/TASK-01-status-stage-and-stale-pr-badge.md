# TASK-01：结合本地任务与同步状态判定待合入并弱化过期 CI 绿标

- Issue: #48
- Status: done
- Depends on: none
- Test: `PYTHONPATH=tests python3 -m unittest tests/test_monitor_and_board.py -v`

## 任务范围
- 修改 `scripts/monitor.py`：为 `format_change_badge()` 增加 `local_unsynced` 参数，重写 `_build_status_row()` 结合本地 TASK 完成度、工作树 `dirty_count`、`unpushed_commits` 与 `git_op` 综合判定 `stage` 与 `change_stale`
- 修改 `scripts/board_ui.py`：在 `collectItems()` 本地工作树状态中考虑脏文件/未完成状态；在 `renderChangeInline()` 中将本地待同步的 `PASS`/`NONE` PR/MR 徽章弱化为 `tone-warning` 并标注待同步
- 修改 `scripts/idd_cli.py`：终端状态渲染（`_style_ci_badge` / `_style_change` / `_render_status_card` / `_render_repo_status_body`）透传 `change_stale` 并在终端显示 `(待同步)`
- 在 `tests/test_monitor_and_board.py` 补全 Python 单元测试、Node JS 单元测试与端到端集成测试
- 不修改 `README.md` 与 `README.en.md`

## 验收标准

- [x] 已有 PR/MR 且 CI 全绿时，存在 `blocked` TASK 判为 `⛔ 受阻`，存在 `planned`/`in_progress`/`unknown` TASK 或本地 `dirty_count`/`unpushed_commits`/`git_op` 判为 `🟡 开发中`
- [x] `cancelled` / `deferred` TASK 与合入清理后 `total == 0` 不阻塞 `🔵 待合入`；CI `FAIL` 仍优先判为 `🛠️ 修 CI`
- [x] Web 看板与终端 `idd status` 在 PR/MR 本地待同步时弱化 `CI 全绿` 徽章并标注待同步
- [x] `PYTHONPATH=tests python3 -m unittest tests/test_monitor_and_board.py -v` 全量通过

## 实现注意事项

- 保持对 `TASK/` 已清空（`total == 0`）或 `item=None` 场景的兼容性
- 无 PR/MR 时，`total > 0` 且 `done > 0` 且无未完成项且工作区干净（即使 `unpushed_commits > 0`）仍判为 `🟢 待提 PR/MR`

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest tests/test_monitor_and_board.py -v`
- Expected: 所有单元测试、JS 渲染测试与端到端集成测试全部通过

## 执行结果

- Outcome: passed
- Notes: 已完成阶段判定优先级重构、Web 与终端过期 CI 绿标弱化联动，以及 22 项监控与看板单测全量通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `PYTHONPATH=tests python3 -m unittest tests/test_monitor_and_board.py -v` | passed（22 tests in 36.861s, OK） | 含 `test_status_row_stage_and_stale_badge_matrix`、`test_board_ui_stale_badge_and_handoff_js`、`test_e2e_appended_task_after_green_pr_returns_to_developing_and_marks_stale` |
