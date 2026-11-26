# TASK-02：更新看板默认视图与布局自动化测试

- Issue: 53-board
- Status: planned
- Depends on: 53-board/TASK-01
- Test: `python3 -m unittest discover -s tests -v`

## 任务范围
- 完善 `tests/test_monitor_and_board.py`：
  - 在 `test_board_web_server_serves_offline_ui_and_live_snapshots` 校验移除 `view-cockpit` / `workbench-grid` / `renderCockpitView` / `wt-tasks-strip`，保留 3 视图与默认 `repos` 高亮及白名单归一化。
  - 在 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees` 补充 Node JS 运行时校验：验证 `cockpit` 旧缓存回退为 `repos`、`renderReposView` 仓库分组与阶段优先级排序、`.cleanup-drawer` 默认折叠与展开、`cleanupOnly` 模式与 `idd cleanup` 提示词、以及 `getStageQuickCli` 与 `renderInspector` 在全 5 阶段下的快捷命令输出。
- 运行全量测试套件确认无回归。

## 验收标准

- [ ] `test_board_web_server_serves_offline_ui_and_live_snapshots` 与 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees` 全面覆盖新默认视图与交互边界。
- [ ] `python3 -m unittest discover -s tests -v` 全部通过。

## 实现注意事项

- 所有 JS 运行时测试通过真实提取 `scripts/board_ui.py` 内联函数并用 `node` 执行断言验证。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全部单元测试通过，无跳过或错误。

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
