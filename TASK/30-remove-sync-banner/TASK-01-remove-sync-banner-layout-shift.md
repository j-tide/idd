# TASK-01：移除刷新同步横幅避免页面抖动

- Issue: #30
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 移除文档流内的 `#sync-banner-wrap`、`.sync-banner` 样式与 `renderSyncBanner()` 逻辑，避免刷新、30s 自动同步和手动同步时主内容区上下跳动。
- 隐藏空的 `#top-alerts-wrap` 与 `#warnings-wrap`，消除无内容时的多余 flex gap。
- 收敛 `#conn-tag` 同步中文案并固定 `#sync-btn` 最小宽度，减少顶栏横向宽度波动。
- 更新并补充 `tests/test_monitor_and_board.py` 回归断言；不改动后端 `ForgeSnapshotCache` 与冷启动骨架屏逻辑。

## 验收标准
- [x] 页面重载、30s 后台同步及手动触发同步时，不再弹出文档流内 `.sync-banner`，主内容区无上下抖动
- [x] 顶部进度条 `#top-progress`、状态胶囊 `#conn-tag` / `#forge-status-group` 与 `#sync-btn` 仍清晰反馈同步状态，且顶栏宽度稳定
- [x] 空的 `#top-alerts-wrap` / `#warnings-wrap` 不产生多余纵向间距
- [x] 自动化测试全部通过且前端 JS 通过 `node --check` 语法检查

## 实现注意事项
- 保留 `.init-status-left svg` 的旋转动画与 `@media (prefers-reduced-motion: reduce)` 规则。
- 保留 `updateTopProgress()`、`syncHeaderControls()`、`updateConnectionBadge()`、`renderForgeStatus()`、`renderKpis()` 的 `waitingFirstForge` 与 `renderMainSkeleton()`。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全部测试通过，包含 `node --check` 前端脚本语法检查。

## 执行结果
- Outcome: passed
- Notes: 已移除文档流内同步横幅并消除空容器间距与顶栏按钮宽度抖动，全量 70 项测试全部通过（含前端 JS `node --check` 校验）。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / working-tree | `python3 -m unittest discover -s tests -v` | passed (70 passed in 123.934s，含 `node --check` JS 语法检查) | `scripts/board_ui.py`, `tests/test_monitor_and_board.py` |
