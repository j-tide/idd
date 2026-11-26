# TASK-02：HTML 结构重构、6 胶囊筛选与 3 栏进度卡渲染器

- Issue: #55
- Status: in_progress
- Depends on: TASK-01
- Test: node --check & python3 -m unittest discover -s tests -p "test_monitor_and_board.py"

## 范围
更新 `scripts/board_ui.py` 的 HTML 骨架与前端 JS 渲染器：
- 用 `<div class="ws-top-deck">` 包裹 `.ws-header` 与 `#kpis.telemetry-strip`，在其下方紧接 `<section id="bento-kpis" class="bento-kpis"></section>`、`<div id="top-alerts-wrap"></div>`、`<main id="main-content"></main>`。
- 在 `ICONS` 中新增 `radar`、`settings`、`queue` 矢量图标。
- 增加 `state.readyOnly` 状态、`matchesFilters` 过滤、`handleActionClick` 中的 `toggle-ready` 与互斥逻辑、`computeRenderSignature` 中的 `ro` 签名及 `renderMain` 中的 `hasFilters`。
- 移除 `renderSidebarReposAndWorktrees` 中的 `GH` / `GL` 文本缩写标签。
- 重构 `renderKpis(snap)`（内置自包含 `buildSegSlots` 辅助函数，确保单元测试单函数抽取可独立运行）：渲染 6 枚带语义动效与中英文切换的 `.stat-chip`、右侧筛选提示/重置按钮，以及 `#bento-kpis` 中的 3 张圆角分段进度概览卡（`Issue 状态` 8 格、`TASK 拆分进度` 10 格、`PR / MR 与合入` 8 格）。
- 更新 `renderLoadingState()` 为 `#kpis` 与 `#bento-kpis` 渲染对应磨砂骨架屏。
- 更新 `renderIdHtml(item, opts)` 支持 `is-pill` 样式；更新 `renderCard(item, opts)` 输出 `data-forge`、通过 `inRepoGroup` 在按仓库视图去重 `forge-chip` 并使用圆角 `#ID` 胶囊、按任务/CI 状态着色 `.progress-fill`；更新 `renderReposView(items, snap)` 输出 `data-forge` 并移除重复的「进入仓库主页」按钮。
