# TASK-02：`idd board` 2s 轮询 DOM 保活调和、卡片 FLIP 位移、无损详情抽屉与移动端适配

- Issue: 59-apple-motion-polish
- Status: in_progress
- Depends on: TASK-01
- Test: `tests/test_monitor_and_board.py`（看板 JS 调和、无损详情抽屉、键盘无障碍与移动端底部抽屉响应式检查）

## 任务范围
- 对 `syncHeaderControls`、`updateConnectionBadge`、`renderSidebarReposAndWorktrees` 实行局部防抖/保活更新，消除 2s 轮询吞点击
- 在真实浏览器 DOM 中改造 `renderKpis`（数值跳变微动效与分段槽过渡）、`renderMain`（按 `data-open-key` 复用卡片与进度条节点并应用合成层 FLIP 位移）与 `renderInspector`（保留滚动条、选中文本与 `.copied` 状态，卡片切换交叉淡入）
- 补齐仓库与卡片键盘 `Enter`/`Space` 激活、以及 `<=780px` / `<=560px` 移动端底部抽屉与单行横滑筛选栏适配

## 验收标准
- [ ] 2s 轮询刷新时卡片与进度条 DOM 节点保留复用，`.inspector-body.scrollTop` 与文本选择不丢失
- [ ] 阶段/优先级变动时卡片执行合成层 FLIP 平滑位移；数值变化显示克制跳变
- [ ] `<=560px` 移动端详情抽屉转为底部 Sheet 形态，窄屏无横向溢出

## 实现注意事项
- `reconcileMainContent` 等真 DOM 逻辑放在不被测试单独抽取的协调路径或做好 mock DOM 回退，确保 `test_board_redesigned_layout_removes_worktree_rail_and_surfaces_cleanable_worktrees` 继续通过

## 验证方式
- Command: `python3 -m unittest tests.test_monitor_and_board -v`
- Expected: `test_monitor_and_board.py` 全部通过

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
