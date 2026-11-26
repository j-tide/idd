# TASK-02：补充看板重构布局测试并完成全量回归

- Issue: #47
- Status: done
- Depends on: TASK-01
- Test: `tests/test_monitor_and_board.py` 与 `python3 -m unittest discover -s tests -v`

## 任务范围
在 `tests/test_monitor_and_board.py` 中新增测试方法 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees`，覆盖以下验证：
1. HTML / CSS 静态断言：确认移除 `wt-rail-list`、`sb-hdr-wts`、`sb-filters`、`并行目录`，保留 4 视图入口（`view-cockpit`、`view-kanban`、`view-repos`、`view-list`），包含新布局选择器（`workbench-grid`、`console-sticky`、`telemetry-strip`、`toggle-cleanup`、`cleanup-drawer`）。
2. Node JS 行为测试：抽取 `collectRetainedWorktrees`、`getStageQuickCli`、`buildHandoffPrompt`、`renderKpis`、`renderCockpitView` 等函数，验证 `retained_idle_worktrees` 聚合、「可清理目录」筛选切换、折叠抽屉默认收起与展开显示 `idd cleanup`、以及 5 个阶段的智能阶段命令推荐。
3. 运行全量测试套件验证无任何回归。

## 验收标准

- [x] 新增测试覆盖侧栏精简、4 视图保留、可清理工作树分层与智能阶段命令逻辑。
- [x] `python3 -m unittest discover -s tests -v` 全量通过且无跳过或放宽断言。

## 实现注意事项

- 复用 `tests/test_monitor_and_board.py` 中已有的 `_extract_js_fn` + `node -e` 模式，不破坏既有测试隔离性。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v`
- Expected: 所有测试文件与用例全部通过。

## 执行结果

- Outcome: passed
- Notes: 已补充 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees` 并完成全量 85 项测试回归，全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed (85 passed) | `tests/test_monitor_and_board.py` |
