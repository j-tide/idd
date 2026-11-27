# TASK-02：看板已合入工作树二次确认弹窗与逐卡流式清理动效

- Issue: #67
- Status: planned
- Depends on: TASK-01
- Test: tests/test_monitor_and_board.py (test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees, test_board_cleanup_ui_modal_and_streaming_removal)

## 任务范围
- 在 `scripts/board_ui.py` 为「已合入但仍保留的本地工作树」抽屉、「可清理」筛选视图及单张已合入卡片增加「一键清理 / 清理」入口，保留紧凑的复制 `idd cleanup` 兜底图标按钮。
- 复用现有模态框样式体系新增 `#cleanup-confirm-overlay` / `#cleanup-confirm-modal`，支持批量列表预览与单卡详情确认、安全说明及 `Escape` / 遮罩 / 取消关闭。
- 确认后逐个调用 `POST /api/cleanup`，每完成一项播放退场动画并通过 `reconcileMainContent` / FLIP 动效实时移除对应卡片、扣减计数徽章，支持中途「停止」、跳过原因原地提示与汇总 Toast。
- 在 `tests/test_monitor_and_board.py` 补充前端 JS 单元测试验证弹窗、清理状态与筛选逻辑。

## 验收标准
- [ ] 点击「一键清理」或单卡「清理」弹出二次确认弹窗，明确展示清理对象及「仅删目录、保留分支」安全说明。
- [ ] 确认后按顺序逐卡清理，每成功移除一个即平滑退场并 FLIP 补位，计数徽章实时递减，支持随时点击「停止」。
- [ ] 被后端跳过或报错的卡片留在列表中并原地展示具体原因横幅，不中断后续卡片清理；兼容现有 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees` 断言。

## 实现注意事项
- `tests/test_monitor_and_board.py` 通过 `_extract_js_fn` 单独提取函数并用最小 `state` 对象测试，新增对 `state` 新字段的读取必须做空值守卫。
- 更新 `reconcileMainContent` 对 `.cleanup-toolbar` 的增量修补，避免批量清理时重置卡片 DOM 状态。

## 验证方式
- Command: `python3 -m unittest tests.test_monitor_and_board -v`
- Expected: 所有监控与看板测试通过。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
