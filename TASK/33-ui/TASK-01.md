# TASK-01：看板动效基座、微交互与渲染防抖动重构

- Issue: 33-ui
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 在 `scripts/board_ui.py` 注入统一 Motion Tokens（`--ease-*`、`--dur-*`、`--shadow-pill`）与完整 `@media (prefers-reduced-motion: reduce)` 支持。
- 统一既有离散过渡时长与曲线，补全微交互（按压微压缩 `:active`、`focus-visible` 焦点环、外链箭头微位移、搜索框焦点环）。
- 骨架屏扫光与活跃呼吸点改用 GPU 合成伪元素动画，清除高重绘动画与 `transition: all`。
- 修复 2s 轮询与交互时的 DOM 抖动：同步/暂停按钮防重写重置、异步提交按钮补齐 `.spin`、保留滚动条位置、复制态防冲刷与勾号描绘动画、令牌校验错误轻颤反馈。

## 验收标准
- [x] `board_ui.py` 定义完整 Motion Tokens 且无 `transition: all` 或 `background-position` 骨架重绘动画
- [x] `#sync-btn` 与 `#pause-btn` 在 2s 轮询中仅在状态变化时更新 DOM，旋转动画不重置
- [x] 复制成功态在窗口期内不被轮询冲掉，错误输入触发轻颤与错误提示淡入
- [x] `tests/test_monitor_and_board.py` 与 `node --check` 语法校验通过

## 实现注意事项
- 必须保留 `tests/test_monitor_and_board.py` 断言的全部关键 CSS/JS 字符串，且禁止出现 `backlog`、`cdn.`、`renderOpenIssueBtn`、`sync-banner-wrap`、`renderSyncBanner`。

## 验证方式
- Command: `python3 -m unittest tests/test_monitor_and_board.py -v`
- Expected: 所有测试通过且内嵌 JS 通过 `node --check`。

## 执行结果
- Outcome: passed
- Notes: 已完成 `board_ui.py` 统一 Motion Tokens、微交互按压/焦点环、GPU 合成骨架屏与呼吸光环、2s 轮询与操作防抖动（同步/暂停按钮防重置、异步提交按钮 `.spin`、滚动位置保留、复制态持久化与勾号绘制、错误轻颤），18 项看板与监控单测（含 `node --check`）全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `PYTHONPATH=tests python3 -m unittest tests/test_monitor_and_board.py -v` | passed (18/18, 含 `node --check`) | `scripts/board_ui.py` |
