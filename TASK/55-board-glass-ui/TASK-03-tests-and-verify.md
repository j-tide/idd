# TASK-03：同步更新与扩充单测、全量回归验证并提 PR

- Issue: #55
- Status: done
- Depends on: TASK-02
- Test: python3 -m unittest discover -s tests && node --check

## 范围
- 更新并扩充 `tests/test_monitor_and_board.py` 中 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees` 等测试，验证：
  - 6 项 `.stat-chip`（含 `toggle-ready` 与 `toggle-cleanup`）及 `#bento-kpis` 3 栏分段进度卡的中英文/边界态渲染。
  - 按仓库视图的 `data-forge`、`.id-link.is-pill` 去重渲染，以及侧栏/主页无 `GH`/`GL` 缩写和无重复「进入仓库主页」按钮。
  - `.ws-top-deck`、`.bento-kpis`、`.kanban` 等高对齐与 `.workspace > #top-alerts-wrap:empty` 样式存在，且无任何外链 CDN。
- 在 worktree 中运行完整 `tests/test_monitor_and_board.py` 与全量 `unittest discover -s tests`，通过 `node --check`，提交并 `idd sync`，创建 PR 并观察 CI 全绿。
