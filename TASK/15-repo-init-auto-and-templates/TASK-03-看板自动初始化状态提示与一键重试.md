# TASK-03：看板自动初始化状态提示与一键重试

- Issue: #15
- Status: done
- Depends on: TASK-01, TASK-02
- Test: tests/test_monitor_and_board.py

## 任务范围
- 包含：
  - 在 `scripts/board_ui.py` 新增 `POST /api/repo/init`（含 CSRF 与本地注册仓库白名单校验），支持单仓库与批量初始化；
  - 扩展 `POST /api/auth/save` 支持 `auto_repo_init`（默认 `true`），连接保存后自动初始化匹配主机且未对齐的仓库（取消勾选时仅只读探测并标为 `pending`）；
  - 在看板前端增加自动初始化开关、设置向导状态与一键执行/重试列表、顶部提示横幅（可暂关），以及在侧边栏仓库列表、工作区顶栏、仓库视图持久显示的可点击「待初始化 / 重试」徽章；
  - 在 `tests/test_monitor_and_board.py` 新增端到端回归测试。
- 不包含：修改看板轮询架构。

## 验收标准

- [x] `POST /api/auth/save` 默认自动初始化匹配主机仓库，传 `auto_repo_init: false` 时标为 `pending`；
- [x] `POST /api/repo/init` 强制执行 CSRF 与仓库白名单校验，失败时保留 `pending` 与错误摘要，重试成功后刷新为 `aligned`；
- [x] 顶部横幅关闭后，侧边栏/顶栏/仓库视图/设置向导仍持久显示待初始化状态与一键点击重试入口，且全量测试与 CI 通过。

## 实现注意事项

- 保持前端渲染签名 `computeRenderSignature` 与 `renderTopAlerts` 签名包含 `repoInitRunning`、`repoInitErrors`、`repoInitBannerDismissed`，确保状态变化即时重绘。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单测通过（0 failures / 0 errors）且 `release.py --check` 返回退出码 0。

## 执行结果

- Outcome: passed
- Notes: 已在 `scripts/board_ui.py` 完成 `POST /api/repo/init`、`POST /api/auth/save` 自动初始化及前端设置向导开关、顶部提示横幅、侧边栏/顶栏/仓库视图持久状态与一键重试功能，并通过 JS 语法检查、全量 60 项单测及版本一致性校验。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / base `59dbe23` | `node --check` on `BOARD_HTML` `<script>` | passed (`JS syntax check: OK`) | `scripts/board_ui.py` |
| 2026-11-26 / base `59dbe23` | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board -v` | passed (14 tests, 28.450s) | `tests/test_monitor_and_board.py` |
| 2026-11-26 / base `59dbe23` | `python3 -m unittest discover -s tests -v` | passed (60 tests, 111.283s) | `tests/` 全量测试套件 |
| 2026-11-26 / base `59dbe23` | `python3 scripts/release.py --check` | passed (`v0.0.3`) | `SKILL.md == README.md == README.en.md == idd --version` |
