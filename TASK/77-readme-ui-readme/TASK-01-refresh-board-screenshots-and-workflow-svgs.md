# TASK-01：更新新版看板实景截图与架构流程图

- Issue: 77-readme-ui-readme
- Status: done
- Depends on: none
- Test: `sips -g pixelWidth -g pixelHeight assets/board-*.png` + 子代理抽检 4 张 PNG 与 4 张 SVG 渲染图

## 任务范围
- 基于最新 `scripts/board_ui.py` 启动本地预览服务并注入真实感多仓库双平台（GitHub + 自建 GitLab）Mock 快照，使用本机 Headless Chrome 2x Retina 拍摄 4 张高清截图：
  - `assets/board-zh-dark.png`
  - `assets/board-zh-light.png`
  - `assets/board-en-dark.png`
  - `assets/board-en-light.png`
- 同步升级 4 张架构流程图 SVG，对齐新版磨砂玻璃深浅色配色与最新完整闭环（先对齐方案/原型 → 独立 Worktree 并行 → `idd board` 自适应脉搏/一键接力/逐卡清理 → 直线 Squash 合入 `main`）：
  - `assets/workflow-zh-dark.svg`
  - `assets/workflow-zh-light.svg`
  - `assets/workflow-en-dark.svg`
  - `assets/workflow-en-light.svg`
- 不修改任何 CLI 或看板运行时代码。

## 验收标准

- [x] 4 张 `assets/board-*.png` 尺寸均为 `3080 × 2040`（2x Retina），展现磨砂玻璃侧栏、两行顶栏、3 栏 Bento 进度卡、6 项语义胶囊、双平台仓库卡片与可清理抽屉，无骨架屏、弹窗遮挡或 `NaN`/`undefined`
- [x] 4 张 `assets/workflow-*.svg` 在中英文与深浅色下文字排版清晰、无截断重叠，且反映最新闭环
- [x] 通过只读子代理完成截图与 SVG 渲染图的视觉抽检

## 实现注意事项

- 截图脚本仅放在 conversation scratch 目录，不写入工作树。
- 若发现字体折行、文字重叠或暗/亮色对比异常，修正后重新拍摄复核。

## 验证方式

- Command: `sips -g pixelWidth -g pixelHeight assets/board-*.png` 及只读子代理视觉检查
- Expected: 4 张 PNG 均为 `2760 × 1780`，8 张配图视觉审查全部通过

## 执行结果

- Outcome: passed
- Notes: 已完成 4 张新版 `idd board` 实景截图（`3080 × 2040`）与 4 张 `workflow` 架构 SVG 升级，经只读视觉审查子代理逐张核验 8/8 全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `sips -g pixelWidth -g pixelHeight assets/board-*.png` | passed：4 张 PNG 均为 `3080 × 2040` | `assets/board-{zh,en}-{dark,light}.png` |
| 2026-11-27 | 视觉审查子代理抽检（4 张看板 PNG + 4 张架构 SVG 渲染图） | passed：8/8 通过（无骨架屏、无截断重叠、双语/深浅色对齐） | `assets/workflow-{zh,en}-{dark,light}.svg` |
