# TASK-01：将同步状态收口至顶栏筛选区并移除主区横幅

- Issue: 73-board
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 移除 `scripts/board_ui.py` 中的 `.init-status-bar` 相关 CSS 与 `renderMainSkeleton()` 内的横幅 DOM，主区仅保留干净骨架屏。
- 在 `scripts/board_ui.py` 中新增 `.glass-filter-hint.is-syncing` 样式及 `prefers-reduced-motion` 兼容规则。
- 在 `renderLoadingState()` 与 `renderKpis()` 中将初始化扫描与远端同步提示收口至顶栏 `.glass-filter-hint.is-syncing`（保留 tooltip 提示与激活筛选优先展示重置按钮），并确保原位 DOM patch 同步 `className`、`title` 与 `innerHTML`。
- 在 `tests/test_monitor_and_board.py` 中更新并补充对应 HTML 结构与前端 JS 行为测试。
- 不包含：不重构 `.top-progress`、`#conn-tag`、`#sync-btn` 或 `#bento-kpis`。

## 验收标准

- [x] `#main-content` 骨架屏不再渲染 `.init-status-bar`，同步完成后无主区域高度跳动。
- [x] 初始化加载阶段，顶栏 `.glass-filter-hint.is-syncing` 正确展示扫描本机仓库提示与旋转图标。
- [x] 远端同步阶段（`forge_syncing=true` 且无激活筛选），顶栏 `.glass-filter-hint.is-syncing` 展示仓库同步提示与 `title`；同步结束后原位恢复默认筛选提示且移除 `is-syncing` 与 `title`。
- [x] 存在激活筛选条件时，`.glass-filter-hint` 优先展示已筛选状态与重置按钮。
- [x] `python3 -m unittest discover -s tests -v` 全量通过。

## 实现注意事项

- 复用 `@keyframes spin` 与 `.glass-filter-hint` 既有布局，保证 `@media (max-width: 860px)` 下行为不变。
- `renderKpis()` 原位 patch 时必须同时同步 `className`、`title` 属性与 `innerHTML`，避免状态切换残留 `is-syncing` 或旧 `title`。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全部单元测试（含内嵌 JS 语法检查与新增 DOM 行为测试）通过。

## 执行结果

- Outcome: passed
- Notes: 已移除 `#main-content` 中的 `.init-status-bar`，将扫描/同步提示收口至 `.ws-top-deck` 第二行右侧 `.glass-filter-hint.is-syncing`，并通过全量 100 项及看板模块 32 项单元测试。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest discover -s tests -v` | passed (100 tests in 474.861s, OK) | `tests/test_monitor_and_board.py` |
| 2026-11-27 | `python3 -m unittest discover -s tests -p test_monitor_and_board.py -v` | passed (32 tests in 45.516s, OK；修复测试正则原始字符串警告后复测) | `tests/test_monitor_and_board.py` |
