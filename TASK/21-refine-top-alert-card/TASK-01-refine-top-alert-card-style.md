# TASK-01：移除看板顶部提醒卡片左侧竖条并统一卡片样式

- Issue: #21
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 修改 `scripts/board_ui.py`：
  - 为 `#top-alerts-wrap` 增加垂直堆叠间距与 `:empty` 隐藏样式。
  - 移除 `.auth-alert-box` 的 `border-left: 3px solid var(--amber);`，统一为 `var(--radius-card)` 圆角与 `1px solid var(--border)` 四边细边框。
  - 新增 `.alert-ic` 柔和图标徽章样式（深浅色主题均适配），并为 `.auth-alert-box .policy-repo-row` 设置嵌入槽位背景 `var(--bg-well)` 以区分层级。
  - 更新 `renderTopAlerts` 中 `policyHtml` 的标题区模板，使用 `.alert-ic` 与 `.badge.tone-warning.num` 计数徽章。
- 修改 `tests/test_monitor_and_board.py`：补充针对 `.auth-alert-box`、`.alert-ic`、`#top-alerts-wrap:empty` 及 `.auth-alert-box .policy-repo-row` 的回归断言。
- 不包含：看板交互逻辑、数据接口或设置向导弹窗内 `.policy-section` 样式改动。

## 验收标准

- [x] `.auth-alert-box` 不再包含左侧彩色竖条（`border-left`），四边边框与圆角与页面 Bento 卡片一致（深浅色主题均适配）。
- [x] 策略提醒卡片标题采用柔和图标徽章与计数标签，嵌套仓库行视觉层级清晰。
- [x] 自动化测试与 JS 语法检查、版本一致性检查全部通过。

## 实现注意事项

- 保留 `.policy-repo-row` 原样式供设置向导弹窗内的 `.policy-section` 使用，仅通过 `.auth-alert-box .policy-repo-row` 作用域覆盖顶部提醒卡片内部行的背景。
- 所有修改严格在独立工作树 `/Users/iamzjt/.agents/skills/idd-worktrees/21-refine-top-alert-card` 内进行。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性检查与全部单元测试（含 JS 语法检查与新增样式回归断言）退出码为 0。

## 执行结果

- Outcome: passed
- Notes: 已移除 `.auth-alert-box` 左侧竖条并统一为 Bento 卡片风格，全量单元测试（67 passed，含 `node --check` 语法检查）与版本一致性校验均通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 (基于 `96c9cb8`) | `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v` | passed（版本校验通过 `v0.0.3`；67 passed，含 `test_monitor_and_board.py` 新增样式断言与 `node --check`） | `scripts/board_ui.py`、`tests/test_monitor_and_board.py` |
