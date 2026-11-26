# TASK-01：重构看板工作台布局与信息架构

- Issue: #47
- Status: done
- Depends on: none
- Test: `tests/test_monitor_and_board.py` 与 `node --check`

## 任务范围
重构 `scripts/board_ui.py` 中 `BOARD_HTML` 的页面骨架、CSS 样式与前端交互逻辑：
1. 精简左侧栏：移除「并行目录」（`#sb-hdr-wts` / `#wt-rail-list`）和 `#sb-filters` 重复筛选区，改为「品牌标头 + 4 个带文字视图导航（工作台 / 流程看板 / 按仓库 / 紧凑列表）+ 仓库空间（含自动准入与待初始化标记）+ 底部工具区」。
2. 重构顶栏：将 `#search-wrap` 搜索框移入 `.ws-controls` 右侧并保留 `/` 快捷键与清空按钮。
3. 压缩顶部指标区：将 `#kpis` 从 3 张大卡片重构为单行紧凑 `.telemetry-strip`（场景筛选胶囊：全部活跃 / 施工中 / 需关注 / 待处理 Issue / 可清理目录 + 紧凑 `TASK` 8 段进度条）。
4. 重构工作台默认视图（`viewMode === "cockpit"`）：改为左右分栏 `.workbench-grid`（左栏按优先级分组的任务推进流 + 底部可折叠的已合入保留工作树抽屉，右栏 sticky 跨 Agent 接力台含智能阶段命令与步骤/改动/接力词 3 Tab）；窄屏（`< 1140px`）自动退化为上下堆叠。
5. 保持 `kanban`、`repos`、`list` 视图、`#inspector-panel` 抽屉、托管平台状态、令牌向导、`repo-init` 策略横幅、`auto_merge` 确认弹窗及双语/双主题零回归。

不包含后端 `/api/*` 与 `monitor.py` 数据采集逻辑改动。

## 验收标准

- [x] 侧栏移除「并行目录」与重复筛选区块，4 个带文字视图导航与仓库空间正常展示与折叠。
- [x] 搜索框位于顶栏右侧且 `/` 快捷键有效；顶部 `#kpis` 为单行紧凑态势筛选条（含可清理目录）。
- [x] 工作台为左右分栏（左任务流 + 右 sticky 接力台），支持已合入保留目录折叠展示及一键复制 `idd cleanup`。
- [x] 所有既有测试（含 `test_monitor_and_board.py`、`node --check`）继续通过。

## 实现注意事项

- 保留测试依赖的核心 DOM ID 与函数名（`top-progress`、`status-cluster`、`forge-status-group`、`forge-status-popover`、`view-cockpit`、`view-kanban`、`view-repos`、`view-list`、`inspector-panel`、`lang-btn`、`setup-btn`、`top-alerts-wrap`、`setup-modal`、`am-confirm-overlay`、`am-confirm-modal`、`renderWorkspaceHeader`、`renderTopAlerts`、`renderPrimaryLinkBtn`、`shortDirSlug`、`buildHandoffPrompt` 等）。
- 保留 `.auth-alert-box` 的柔和琥珀细框与 `.alert-warn-ic` 样式规范。

## 验证方式

- Command: `python3 -m unittest tests/test_monitor_and_board.py -v`
- Expected: 全部现有测试与 JS 语法检查通过。

## 执行结果

- Outcome: passed
- Notes: 已完成 `scripts/board_ui.py` 结构、CSS 与 JS 渲染重构，既有 19 项板端与监控测试（含 `node --check`）全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v` | passed (19 passed, 含 `node --check`) | `scripts/board_ui.py` |
