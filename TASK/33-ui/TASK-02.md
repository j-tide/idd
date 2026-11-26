# TASK-02：看板表面进出、空间滑动、数据插值与跟手抽屉调宽

- Issue: 33-ui
- Status: in_progress
- Depends on: TASK-01
- Test: tests/test_monitor_and_board.py

## 任务范围
- 实现通用 `syncSlidingIndicator`，为 4 视图切换 `.sb-tiles`、接力台 `.console-tabs`、抽屉 `.tabs` 与向导 `.wizard-nav` 提供平滑弹性滑动胶囊/指示器。
- 升级表面进出：`#forge-status-popover` 告别 `display:none/flex` 硬切并适配手机宽度；`#inspector-panel` 升级弹簧抽屉并支持桌面端左缘拖拽调宽（`360px`–`760px`）与移动端底部 Sheet；`#setup-modal` 支持步进切换方向淡入；`#top-alerts-wrap` 支持关闭平滑折叠；`.toast` 支持上浮进出。
- 实施局部就地更新：驾驶舱行选中、抽屉关闭、抽屉 Tab 切换不整页重绘；KPI 数值与进度条平滑插值；视图/筛选切换与骨架→真实数据平滑过渡；侧栏收展缓冲与主题平滑过渡。

## 验收标准
- [ ] Popover、抽屉、弹窗、提醒横幅、Toast 全部平滑进出且支持交互打断
- [ ] 分段控件滑块、KPI 数值、分段条与进度条在状态变化时平滑过渡，2s 轮询不误触发入场动画
- [ ] 桌面端详情抽屉支持跟手拖拽调宽与双击复位，手机端自动切换为底部 Sheet
- [ ] `tests/test_monitor_and_board.py` 全部通过

## 实现注意事项
- `syncSlidingIndicator` 在容器重建后需先无动画置于旧坐标，触发一次轻量回流后再开启动画滑向目标位置。
- 保持 `.workspace > #top-alerts-wrap:empty { display: none; }` 有效。

## 验证方式
- Command: `python3 -m unittest tests/test_monitor_and_board.py -v`
- Expected: 所有测试通过。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
