# TASK-01：移除工作台视图并将按仓库设为默认看板

- Issue: 53-board
- Status: done
- Depends on: none
- Test: `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v`

## 任务范围
- 修改 `scripts/board_ui.py`：
  - 移除侧栏「工作台（`view-cockpit`）」按钮及对应状态、i18n、事件监听与无用 CSS/JS（`workbench-grid`、`renderCockpitView`、`renderCockpitConsole`、`selectedKey`、`consoleTab` 等）。
  - 将默认视图设为 `repos`（「按仓库」），侧栏视图顺序调整为：按仓库 → 流程看板 → 紧凑列表，并兼容旧 `localStorage` 值 `cockpit` 自动回退为 `repos`。
  - 新增 `renderReposView(items, snap)`：按仓库分组展示卡片，组内按阶段优先级排序，保留可清理已合入工作树的折叠抽屉（`.cleanup-drawer`）与 `可清理目录` 筛选态下的 `idd cleanup` 快捷复制按钮；首屏骨架屏默认展示按仓库分组骨架。
  - 更新 `parseStage`（支持 `已合入` / `Merged`）、`renderCard`（可清理卡片底部状态文案）和 `renderInspector`（接入 `getStageQuickCli` 展示与阶段匹配的终端快捷命令）。
- 同步更新 `tests/test_monitor_and_board.py` 中失效的旧 cockpit 断言，保证本任务提交时测试全绿。

## 验收标准

- [x] 侧栏仅保留 3 个视图：`view-repos`（默认首位且高亮）、`view-kanban`、`view-list`，不含 `view-cockpit` 与 `workbench-grid`。
- [x] 默认视图与未知/旧 `cockpit` 缓存回退至 `repos`，骨架屏默认渲染 `.repo-section` 与 `.repo-grid`。
- [x] `renderReposView` 支持阶段优先级排序、`.cleanup-drawer` 折叠/展开及 `cleanupOnly` 态 `idd cleanup` 复制按钮。
- [x] `renderInspector` 使用 `getStageQuickCli(item)` 渲染对应阶段的终端快捷命令。
- [x] `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v` 通过且内联 `<script>` 通过 `node --check`。

## 实现注意事项

- 保留 `.cleanup-drawer`、`.cleanup-hdr`、`.cleanup-body`、`.telemetry-strip`、`.repo-section`、`.repo-hdr`、`.repo-grid`、`.card*`、`.inspector-*` 样式与 `collectRetainedWorktrees`、`getStageQuickCli`、`resolvePrimaryLink`、`renderPrimaryLinkBtn` 函数。
- 避免遗留死变量或未定义的 DOM ID 查询。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v`
- Expected: 全部测试通过，内联 JS 语法校验通过。

## 执行结果

- Outcome: passed
- Notes: 已移除「工作台」视图并将「按仓库」设为默认看板；内联 JS 语法与 `test_monitor_and_board` 23 项测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `node --check`（校验 `scripts/board_ui.py` 内联 `<script>`） | passed (exit 0) | `scripts/board_ui.py` |
| 2026-11-26 | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v` | passed (23 passed) | `tests/test_monitor_and_board.py` |
