# TASK-03：仅首次冷加载展示骨架屏并在后续增量刷新原地更新

- Issue: #67
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py (test_board_first_load_only_skeleton_and_incremental_reconcile)

## 任务范围
- 在 `scripts/board_ui.py` 引入 `state.initialLoadSettled`（并纳入 `computeRenderSignature`），确保仅首次冷加载完成前允许进入 `"loading-sync"` 骨架屏。
- 有缓存快照或首次 `fetchSnapshot` 结算 / 首屏渲染出实际卡片后置位 `initialLoadSettled = true`，后续 2s 轮询、30s 远端刷新与手动「同步远端」仅通过顶栏进度条与状态胶囊提示同步中，主区域保持现有视图并仅增量更新变更 DOM。
- 优化 `reconcileMainContent` 中 `repos` 视图对 `.empty-state` 与 `.cleanup-drawer` 的原地复用，减少无谓整块重建。
- 在 `tests/test_monitor_and_board.py` 补充冷加载与增量刷新骨架屏隔离的自动化测试。

## 验收标准
- [x] `initialLoadSettled === false` 且首次尚无卡片、远端同步中时展示骨架屏。
- [x] `initialLoadSettled === true` 后，即使活跃任务为空且 `forge_syncing === true`，`renderMain()` 也不再切换回 `"loading-sync"` 骨架屏，而是保持当前视图结构原地增量更新。
- [x] `repos` 视图下 `.empty-state` 与抽屉区域支持原地 DOM 修补，不闪烁、不丢失抽屉展开状态。

## 实现注意事项
- 需确保测试中 `_extract_js_fn` 提取 `renderMain` 时对 `state.initialLoadSettled` 等字段安全兼容。

## 验证方式
- Command: `PYTHONPATH=tests python3 -m unittest discover -s tests -v`
- Expected: 全量测试套件全部通过。

## 执行结果
- Outcome: passed
- Notes: 已引入 `initialLoadSettled` 并在 `renderMain`/`reconcileMainContent` 中实现仅首次加载显示骨架屏、后续增量原地更新，全量 96 项测试通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board.TestMonitorAndBoard.test_board_first_load_only_skeleton_and_incremental_reconcile -v` | passed (1 passed in 0.058s) | [tests/test_monitor_and_board.py](../../tests/test_monitor_and_board.py) |
| 2026-11-27 | `PYTHONPATH=tests python3 -m unittest discover -s tests -v` | passed (96 passed in 279.089s) | [tests/test_monitor_and_board.py](../../tests/test_monitor_and_board.py) |
