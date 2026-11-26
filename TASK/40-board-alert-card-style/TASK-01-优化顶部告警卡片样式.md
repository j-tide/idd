# TASK-01：优化顶部告警卡片样式

- Issue: 40-board-alert-card-style
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 包含：
  - 修改 `scripts/board_ui.py` 中 `.auth-alert-box` 为方案 A（柔和琥珀 1px 细框 `--amber-border` + 顶部微渐变底纹 + 14px 圆角，彻底移除 `border-left: 3px solid var(--amber)`）
  - 新增 `.alert-warn-ic` 圆角琥珀图标徽章并在 `renderTopAlerts` 策略横幅中使用
  - 使用 `.auth-alert-box .policy-repo-row` 覆盖告警卡片内子行背景为 `--bg-well`（保持设置向导 `.policy-section` 内行不变）
  - 为 `#top-alerts-wrap` 增加纵向 `flex` 间距（`gap: 10px`）
  - 在 `tests/test_monitor_and_board.py` 新增自动化测试校验样式与 `renderTopAlerts` 渲染结果
- 不包含：修改与顶部告警横幅无关的其余看板区域样式或业务逻辑

## 验收标准

- [x] 移除 `.auth-alert-box` 的 `border-left: 3px solid var(--amber)`，消除与圆角叠加导致的弯折尖角
- [x] 改用四边统一 `1px` 柔琥珀描边（`--amber-border`，适配深/浅双主题）与顶部微渐变底纹，圆角 `14px`
- [x] 策略待初始化横幅警告图标升级为 `26×26` 圆角琥珀图标徽章（`.alert-warn-ic`），对齐 `.host-ic.sm`
- [x] `.auth-alert-box .policy-repo-row` 使用 `--bg-well` 拉开层次，且不影响设置向导 `.policy-section` 内行背景
- [x] `#top-alerts-wrap` 增加纵向 `flex` 间距（`gap: 10px`），多横幅叠加时不紧贴
- [x] 新增自动化测试并通过全量 `unittest` 与 `scripts/release.py --check`

## 实现注意事项

- 只通过 `.auth-alert-box .policy-repo-row` 覆盖顶部告警横幅内的子行背景，不修改全局 `.policy-repo-row`，避免影响设置向导内 `.policy-section`（背景为 `--bg-well`）的层次对比。
- 深色与浅色主题均需声明 `--amber-border` 与对应顶部微渐变底纹。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性检查与全部单元测试通过（返回码 0）。

## 执行结果

- Outcome: passed
- Notes: 已按方案 A 完成顶部告警卡片样式改造与回归测试补充，版本一致性校验与全量 83 项单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 (工作树未提交变更) | `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v` | passed（版本一致性 `v0.0.3` 通过；83 tests passed，含新增 `test_board_top_alert_box_uses_soft_amber_outline_and_warn_icon_badge` 与 Node DOM 渲染校验） | `scripts/board_ui.py`、`tests/test_monitor_and_board.py` |
