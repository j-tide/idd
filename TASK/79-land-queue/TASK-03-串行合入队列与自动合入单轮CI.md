# TASK-03：串行合入队列与自动合入单轮 CI

- Issue: #79
- Status: in_progress
- Depends on: TASK-02
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 在 `scripts/idd_cli.py` 为 `_execute_land` 非 `dry_run` 全链路引入仓库级 `idd-land.lock` 串行合入队列，支持 `IDD_LAND_LOCK_TIMEOUT` 与排队持锁提示。
- 重构 `cmd_pr`（开启 `auto_merge` 且非 `--draft`/`--dry-run` 时）与 `_execute_land`，先做快速失败前置校验，再持 `idd-land.lock` 执行单轮 CI 清理合入路径（rebase → 清理 `TASK/` → 单次推送 → 创建/更新 PR/MR → 等单轮 CI → Squash Merge → 快进 `main`）。
- 失败、超时、冲突或超限重排时自动回滚清理提交并恢复工作树及远端分支（GitLab 优先尝试 `-o ci.skip`），完整保留 `TASK/<issue>/`。
- GitLab 在持锁等待期间遇到 `BEHIND`（`need_rebase`）或合入竞态时取消失效流水线并自动回滚重变基重试（默认上限 `LAND_MAX_REBASE_ATTEMPTS = 3`，支持 `IDD_LAND_MAX_REBASE_ATTEMPTS`）。
- 补齐并发排队合入、单轮 CI、失败回滚与 `need_rebase` 自动重排单测。

## 验收标准
- [ ] 并发执行 `idd pr` / `idd mr`（`auto_merge`）或 `idd land` 按仓库串行排队依次直线合入，无踩踏失效
- [ ] `auto_merge` 正常路径只触发 1 轮远端 CI 即可合入，失败/超时/冲突时 `TASK/` 完整恢复
- [ ] GitLab `need_rebase` 自动取消废流水线并重变基重试成功

## 实现注意事项
- 保留既有输出文案契约，避免破坏现有 CLI 与 GitLab 测试断言。
- 本地 bare 仓库不支持 `-o ci.skip` 时自动回退普通 `--force-with-lease`。

## 验证方式
- Command: `python3 -m unittest tests.test_idd_cli tests.test_gitlab_forge tests.test_monitor_and_board -v`
- Expected: 全部测试通过

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
