# TASK-01：修复收起侧栏顶栏图标重叠与单仓库顶栏胶囊粘连

- Issue: 61-board
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 修复 `scripts/board_ui.py` 中侧栏收起态（`body.sidebar-collapsed`）下 `.sb-brand` 横向挤压导致 `.sb-logo` 与 `#sidebar-toggle` 重叠的问题（并在 `<=780px` 窄屏下恢复横向排布）。
- 修复 `scripts/board_ui.py` 中单仓库顶栏 `#ws-repo-link-wrap` 缺少 flex 间距与空状态隐藏、内部主页徽章和策略按钮与 `.am-header-pill` 高度/圆角不一致的问题。
- 在 `tests/test_monitor_and_board.py` 中补充布局与样式回归测试。

## 验收标准

- [x] 侧栏收起态 `.sb-brand` 垂直居中排布，`.sb-logo` 与 `#sidebar-toggle` 间距清晰、无任何重叠或挤压；窄屏（<=780px）保持横向排布。
- [x] 顶栏 `#ws-repo-link-wrap` 使用 `inline-flex` 并保持 8px 间距，空容器不占位；内部主页链接与策略按钮统一为 26px 高度的胶囊样式，与自动准入胶囊对齐。
- [x] 补充自动化回归测试并通过全量测试与发布校验。

## 实现注意事项

- 保持 `body.sidebar-collapsed .show-collapsed { display: inline-grid !important; }` 原样，避免破坏既有断言。
- 不引入 `transition: all`。
- 将 `26px` 胶囊覆写严格限定在 `#ws-repo-link-wrap .forge-chip, #ws-repo-link-wrap .btn-xs` 下，不影响卡片、表格或仓库分组标题内的紧凑徽章。

## 验证方式

- Command: `python3 -m unittest tests/test_monitor_and_board.py -v && python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 所有单元测试与 `release.py --check` 全部通过（0 failures/errors）。

## 执行结果

- Outcome: passed
- Notes: 已修复收起侧栏顶栏纵向排布与单仓库顶栏胶囊间距及高度对齐，补充回归测试并完成全量测试与版本一致性校验。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 (`fix/61-board`) | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v` | passed (25 passed in 83.508s) | `tests/test_monitor_and_board.py`（含 `test_board_collapsed_sidebar_and_header_pill_layout_css` 及 `node --check`） |
| 2026-11-27 (`fix/61-board`) | `python3 -m unittest discover -s tests -v` | passed (92 passed in 442.238s) | 全量测试套件 |
| 2026-11-27 (`fix/61-board`) | `python3 scripts/release.py --check` | passed (`v0.0.4`) | 版本一致性校验通过 |
