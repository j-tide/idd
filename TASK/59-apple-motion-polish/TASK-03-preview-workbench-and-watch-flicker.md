# TASK-03：`idd preview` 苹果级工作台重构、跟手拖拽缩放与 `idd watch` 终端无闪烁刷新

- Issue: 59-apple-motion-polish
- Status: done
- Depends on: TASK-01
- Test: `tests/test_preview_ui.py` 与 `tests/test_monitor_and_board.py`

## 任务范围
- `scripts/preview_ui.py`：引入统一磨砂玻璃视觉、动效 Token、中英双语切换、`tabular-nums`、`prefers-reduced-motion` 及滑动胶囊指示器（页签与视口分段栏）
- `scripts/preview_ui.py`：实现可打断的像素级视口宽度过渡、保留 `<iframe>` 实例跨模式不重载、并排对比与视口预设共存 + `⇄` 互换、1:1 跟手拖拽分栏手柄与单屏边缘缩放手柄（拖拽期间禁用 iframe 事件穿透）
- `scripts/preview_ui.py`：修复断线重连后状态徽章卡死 Bug、加入 1 次轮询原子重写宽限遮罩避免误毁 iframe、升级多语义合并 Toast
- `scripts/monitor.py`：提取 `_format_tty_watch_frame` 使用 `\x1b[?2026h` 同步输出与 `\x1b[H...\x1b[K\x1b[J` 消除 `idd watch` TTY 全屏清屏闪烁

## 验收标准

- [x] `preview_ui.py` 支持 1:1 跟手拖拽调整对比分栏与单屏宽度，切换视口可自然打断衔接且不重载已有 `iframe`
- [x] 修复断线重连与原子重写闪现问题，`node --check` 与 `tests/test_preview_ui.py` 通过
- [x] `idd watch` TTY 输出不含 `\x1b[2J`，且 `--once` 与非 TTY 输出不变

## 实现注意事项
- 保持 `PreviewRegistry` API、`PREVIEW_HTML` 占位符（`__PREVIEW_TITLE__`、`__IDD_VERSION__`、`__DEFAULT_COMPARE__`）与静态资源安全路径校验不变

## 验证方式
- Command: `python3 -m unittest tests.test_preview_ui -v && python3 -m unittest tests.test_monitor_and_board.TestMonitorAndBoard.test_watch_once_renders_global_frame -v`
- Expected: 全部测试通过

## 执行结果
- Outcome: passed
- Notes: 已完成 `preview_ui.py` 苹果级工作台升级（共享动效 Token、滑动胶囊、双语切换、可打断像素级视口缩放、保留 `iframe` 实例、A/B 并排拖拽分栏与单屏边缘跟手缩放、断线重连状态修复、原子重写宽限遮罩）及 `monitor.py` 同步终端无清屏帧渲染，`test_preview_ui` 与 `test_watch_once_renders_global_frame` 共 8 项全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `PYTHONPATH=tests python3 -m unittest test_preview_ui test_monitor_and_board.TestMonitorAndBoard.test_watch_once_renders_global_frame -v` | passed (8 tests in 4.759s) | `scripts/preview_ui.py`, `scripts/monitor.py` |
