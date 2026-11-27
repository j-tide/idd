# TASK-01：统一动效设计语言与 `idd board` 导航、浮层、抽屉及微交互打磨

- Issue: 59-apple-motion-polish
- Status: done
- Depends on: none
- Test: `tests/test_monitor_and_board.py`（动效 Token、无 `transition: all`、`prefers-reduced-motion`、`.btn:disabled`、`.spin` 按钮、本地化步骤徽章、空态文案及 JS 单测）

## 任务范围
- 在 `scripts/board_ui.py` 建立统一动效 CSS Token 体系，收敛/清理过度循环动画，补充全量 `:active`、`:focus-visible`、`.btn:disabled` 与 `tabular-nums`
- 实现共享滑动指示器 `syncSegmentedIndicator`（侧栏视图、设置向导、详情页签、三态分段开关）
- 改造状态浮层、设置弹窗、自动准入确认弹窗、顶部告警横幅、可清理抽屉的非对称进出场、高度平滑、输入框聚焦保护及校验错误轻晃
- 修复 8 处阻塞按钮缺 `.spin` 旋转反馈、复制宽度锁定与对勾弹性反馈、提示气泡合并防堆叠，并优化中英文交互微文案

## 验收标准

- [x] `board_ui.py` 使用统一动效 Token，无 `transition: all`，并完整覆盖 `prefers-reduced-motion: reduce`
- [x] 所有交互按钮/卡片具备按压缩放与焦点环；忙碌按钮旋转动画生效；复制按钮锁定宽度不抖动
- [x] 浮层、弹窗、横幅、抽屉具备非对称进出场与平滑折叠展开，且不破坏 `tests/test_monitor_and_board.py` 任何既有断言与 JS 抽取器契约

## 实现注意事项
- 严禁在 `BOARD_HTML` 中出现 `"backlog"` 字样或移除测试锁定的 CSS 选择器/DOM 标记
- 保留所有被 `_extract_js_fn` 抽取的顶层函数签名与花括号平衡，不破坏 Node mock DOM 兼容路径

## 验证方式
- Command: `python3 -m unittest tests.test_monitor_and_board.TestMonitorAndBoard.test_board_web_server_serves_offline_ui_and_live_snapshots tests.test_monitor_and_board.TestMonitorAndBoard.test_board_top_alert_box_uses_soft_amber_outline_and_warn_icon_badge tests.test_monitor_and_board.TestMonitorAndBoard.test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees tests.test_monitor_and_board.TestMonitorAndBoard.test_board_auto_merge_config_endpoints_security_and_ui_script tests.test_monitor_and_board.TestMonitorAndBoard.test_board_primary_link_switches_to_pr_or_mr_when_change_exists tests.test_monitor_and_board.TestMonitorAndBoard.test_board_ui_stale_badge_and_handoff_js -v`
- Expected: 全部定向测试通过，JS 语法校验零报错

## 执行结果
- Outcome: passed
- Notes: 已完成 `board_ui.py` 统一动效 Token、收敛过度循环动画、全量交互态与无障碍焦点、滑动分段胶囊、浮层/弹窗/横幅/抽屉平滑进出场、忙碌旋转与中英文微文案打磨，全部 6 项看板定向测试及 JS 语法校验通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board.TestMonitorAndBoard.test_board_web_server_serves_offline_ui_and_live_snapshots test_monitor_and_board.TestMonitorAndBoard.test_board_top_alert_box_uses_soft_amber_outline_and_warn_icon_badge test_monitor_and_board.TestMonitorAndBoard.test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees test_monitor_and_board.TestMonitorAndBoard.test_board_auto_merge_config_endpoints_security_and_ui_script test_monitor_and_board.TestMonitorAndBoard.test_board_primary_link_switches_to_pr_or_mr_when_change_exists test_monitor_and_board.TestMonitorAndBoard.test_board_ui_stale_badge_and_handoff_js -v` | passed (6 tests in 5.064s) | `scripts/board_ui.py` |
