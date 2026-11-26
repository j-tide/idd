# TASK-03：预览工作台动效统一、跟手分栏/视口拖拽与热更新润色

- Issue: 33-ui
- Status: in_progress
- Depends on: TASK-01
- Test: tests/test_preview_ui.py

## 任务范围
- 在 `scripts/preview_ui.py` 引入与 `board_ui.py` 一致的 Motion Tokens，清除所有 `transition: all`，补全 `@media (prefers-reduced-motion: reduce)` 与 JS 检测。
- 配齐轻量化 SVG 图标、主题柔和切换、刷新旋转反馈与快捷键（`r`/`c`/`1-4`）。
- 为 `#viewportGroup` 与 `#tabBar` 接入同源滑动指示器；升级 `#statusDot` 呼吸光环与热更新自动回落；iframe 重载显示顶部 2px 加载条并轻淡画布防白闪；升级 Toast 进出反馈。
- 新增 A/B 并排对比中缝拖拽手柄与单栏右侧拖拽调宽手柄（拖拽时禁用 iframe `pointer-events` 防吞事件，显示实时比例/像素徽标，双击复位），移动端自适应上下双栏。

## 验收标准
- [ ] `preview_ui.py` 与 `board_ui.py` 共享相同 Motion Tokens，无 `transition: all`
- [ ] 单栏与 A/B 对比拖拽调宽顺滑跟手且不被 iframe 吞事件，双击可复位
- [ ] 视口切换复用面板平滑过渡宽度，热更新有加载进度与自动回落反馈
- [ ] `tests/test_preview_ui.py` 与 `node --check` 全部通过

## 实现注意事项
- 拖拽开始给 `.stage` 施加 `.is-dragging` 禁用 `iframe.canvas` 指针事件，并在 `pointerup`/`pointercancel`/`blur` 时确保清理。

## 验证方式
- Command: `python3 -m unittest tests/test_preview_ui.py -v`
- Expected: 所有测试通过且内嵌 JS 通过 `node --check`。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
