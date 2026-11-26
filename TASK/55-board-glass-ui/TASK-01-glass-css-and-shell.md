# TASK-01：磨砂玻璃 CSS 令牌、统一顶栏与 3 栏概览卡样式

- Issue: #55
- Status: done
- Depends on: none
- Test: node --check on extracted <script> & CSS token verification

## 范围
在 `scripts/board_ui.py` 的 `<style>` 中落地已确认的 v12 磨砂玻璃视觉体系（完全离线内置、无外链 CDN）：
- 深色（`:root` 默认）与浅色（`html[data-theme="light"]`）磨砂玻璃与渐变背景网格令牌，保留所有已有测试依赖令牌（`--amber-border`、`.workspace > #top-alerts-wrap:empty`、`.auth-alert-box` 边框等）。
- 统一两行顶栏 `.ws-top-deck`（包含 `.ws-header` 与透明的 `.telemetry-strip`，且 `overflow: visible` 确保连接状态浮层 `#forge-status-popover` 不被裁切）。
- 6 项语义动效筛选胶囊（`.stat-strip`、`.stat-chip`、`.is-all` / `.is-wt` / `.is-alerts` / `.is-ready` / `.is-todo` / `.is-cleanup` 动效与 `prefers-reduced-motion` 支持）及 `.glass-filter-hint` / `.glass-filter-reset`。
- 顶栏下方 3 栏磨砂玻璃分段进度概览卡 `.bento-kpis` / `.bento-card` / `.bento-segs` / `.bento-slot`。
- 仓库区块 `.repo-section` 与卡片 `.card` 磨砂纹理及极浅 GitHub / GitLab 平台倾向色、`data-forge` 样式、`.id-link.is-pill`、多色调 `.progress-fill`、卡内全宽 PR/CI 状态条、`.kanban` 等高对齐（`align-items: stretch` + `.column` 铺底最小高度）、统一 12px 间距及抽屉/弹窗磨砂化；移除无用的 `.sb-plat-tag` 样式。
