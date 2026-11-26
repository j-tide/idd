# TASK-02：看板顶栏状态胶囊整合与连接详情弹窗

- Issue: #23
- Status: done
- Depends on: TASK-01
- Test: tests/test_monitor_and_board.py

## 任务范围

1. 重构 `scripts/board_ui.py` 顶栏右侧 `.ws-controls` 为统一的状态胶囊 `#status-cluster`（包含实时/本地轮询指示 `#conn-tag`、紧凑暂停按钮 `#pause-btn`、分隔线以及 `#forge-status-group` 中的 GitHub / GitLab 实时连接状态按钮）与 `#forge-status-popover` 详情弹窗。
2. 编写完整深浅色主题样式与响应式布局（960px 以下自适应紧凑展示）。
3. 实现前端 JS 逻辑：`resolveForgeConnections()`、`renderForgeStatus()`、`updateConnectionBadge()`、`syncHeaderControls()`、`computeRenderSignature()`、弹窗开关及点击外部/Esc 关闭、中英文切换与快捷键/操作联动；同时优化向导中 `gh_cli` 账号展示。

## 验收标准

- [x] 顶栏显示实时状态、暂停按钮以及 GitHub / GitLab 连接状态指示（支持 `connected`/`syncing`/`auth_required`/`error`/`partial`/`local_only`/`unconfigured`）
- [x] 点击 GitHub / GitLab 状态可打开/切换/关闭连接详情弹窗，查看主机、账号/认证来源、关联仓库、最近同步时间与错误原因，并支持一键同步与跳转配置
- [x] 保留所有既有测试断言的 DOM ID 与文案标记（且不引入 `backlog` 字样），`node --check` 检查通过

## 实现注意事项

- 不修改 `#top-alerts-wrap` / `.auth-alert-box` 顶部提醒卡片样式，避免与 #21 冲突。
- 确保中英文切换与深浅色主题下对比度清晰、无横向溢出。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v`
- Expected: 看板与前端脚本检查全部通过。

## 执行结果

- Outcome: passed
- Notes: 已完成顶栏状态胶囊与详情弹窗 UI 及 JS 逻辑，`node --check` 语法校验及 24 项测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `node --check` + `PYTHONPATH=tests python3 -m unittest test_gitlab_forge test_monitor_and_board -v` | passed (24 passed, JS syntax OK) | `scripts/board_ui.py` |
