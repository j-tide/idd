# TASK-02：PR/MR 自动准入等待 CI 与自动 land 全链路闭环

- Issue: 28-auto-merge-pr-mr-ci
- Status: in_progress
- Depends on: TASK-01
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 在 `scripts/forge.py` 升级 `GitLabForge.watch_checks` 以支持通过 API 轮询 Pipeline 状态。
- 在 `scripts/idd_cli.py` 实现统一 CI 结算等待（含远端 `headRefOid` 同步、无 CI 仓库宽限期确认及超时/失败处理）。
- 在 `idd pr` / `idd mr` 接入 `auto_merge` 开关及 `--auto-merge` / `--no-auto-merge` 单次覆盖，自动等待 CI 结算后串行执行 `_execute_land`（清理 `TASK/`、推送清理提交并等待二次 CI 结算、Squash 直线合入、勾选验收框、快进 `main`）。
- 为 `idd land` 新增 `--wait-ci` 支持等待清理/变基提交引发的新 CI 结算。
- 保障 `--draft`、CI 失败（保留 `TASK/` 并输出日志）、Rebase 冲突、`evidence/` 含附件均安全暂停。

## 验收标准
- [ ] GitHub 与 GitLab 仓库在开启 `auto_merge` 时均可实现 `idd pr`/`idd mr` 自动等待 CI 通过并直线合入。
- [ ] 无远端 CI 仓库（`NONE`）经宽限期确认后允许自动合入。
- [ ] CI 失败、`evidence/` 含附件、Rebase 冲突、`--draft` 均安全暂停且不误删 `TASK/`。
- [ ] 对应单元测试通过。

## 实现注意事项
- 通过 `IDD_CI_GRACE_SECONDS`、`IDD_CI_POLL_INTERVAL`、`IDD_CI_WAIT_TIMEOUT` 控制轮询节奏，便于单元测试快速执行。

## 验证方式
- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 全部新增及现有测试通过。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
