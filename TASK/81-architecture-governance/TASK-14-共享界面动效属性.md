# TASK-14：共享界面动效属性

- Issue: #81
- Status: done
- Depends on: TASK-07
- Test: tests/test_monitor_and_board.py, tests/test_preview_ui.py, tests/test_install_uninstall.py

## 任务范围与验收标准

- [x] 看板与预览相同的 13 项缓动、时长和按压缩放属性只定义一次。服务端加载时内联，页面响应字节、离线使用和两页各自的减少动态效果规则保持可验证。

## 执行结果

- Outcome: passed
- Notes: 两个页面使用同一份动效 CSS 声明，模板加载时展开。保留页面各自的颜色、组件交互和减少动态效果覆盖。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 18c7092 | PYTHONPATH=tests python3 -B -m unittest test_preview_ui test_monitor_and_board.TestMonitorAndBoard.test_board_web_server_serves_offline_ui_and_live_snapshots test_monitor_and_board.TestMonitorAndBoard.test_board_motion_tokens_reduced_motion_and_tty_watch_frame test_install_uninstall.TestInstallAndUninstall.test_install_sh_syntax_and_fresh_install | 12 项通过 |
| 2026-11-28 / 18c7092 | 与治理前 579903a 的两个页面常量逐字节比较 | 看板 353815 字节、预览 54156 字节分别完全相同 |
| 2026-11-28 / 18c7092 | 复核两个模板、服务端加载和声明片段 | 13 个属性只定义一次，输出内联且无额外 HTTP 请求 |
