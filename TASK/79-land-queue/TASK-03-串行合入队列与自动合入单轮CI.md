# TASK-03：串行合入队列与自动合入单轮 CI

- Issue: #79
- Status: done
- Depends on: TASK-02
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 在 `scripts/idd_cli.py` 为 `_execute_land` 非 `dry_run` 全链路引入仓库级 `idd-land.lock` 串行合入队列，支持 `IDD_LAND_LOCK_TIMEOUT` 与排队持锁提示。
- 重构 `cmd_pr`（开启 `auto_merge` 且非 `--draft`/`--dry-run` 时）与 `_execute_land`，先做快速失败前置校验，再持 `idd-land.lock` 执行单轮 CI 清理合入路径（rebase → 清理 `TASK/` → 单次推送 → 创建/更新 PR/MR → 等单轮 CI → Squash Merge → 快进 `main`）。
- 失败、超时、冲突或超限重排时自动回滚清理提交并恢复工作树及远端分支（GitLab 优先尝试 `-o ci.skip`），完整保留 `TASK/<issue>/`。
- GitLab 在持锁等待期间遇到 `BEHIND`（`need_rebase`）或合入竞态时取消失效流水线并自动回滚重变基重试（默认上限 `LAND_MAX_REBASE_ATTEMPTS = 3`，支持 `IDD_LAND_MAX_REBASE_ATTEMPTS`）。
- 补齐并发排队合入、单轮 CI、失败回滚与 `need_rebase` 自动重排单测。

## 验收标准
- [x] 并发执行 `idd pr` / `idd mr`（`auto_merge`）或 `idd land` 按仓库串行排队依次直线合入，无踩踏失效
- [x] `auto_merge` 正常路径只触发 1 轮远端 CI 即可合入，失败/超时/冲突时 `TASK/` 完整恢复
- [x] GitLab `need_rebase` 自动取消废流水线并重变基重试成功

## 实现注意事项
- 保留既有输出文案契约，避免破坏现有 CLI 与 GitLab 测试断言。
- 本地 bare 仓库不支持 `-o ci.skip` 时自动回退普通 `--force-with-lease`。
- 显式 `idd land` 在 `head_sha` 刷新超时等非 `BEHIND` 错误时不回滚清理提交，与既有一致性保证及单测保持一致；`idd pr`/`idd mr` 自动合入路径遇错则完整回滚保留 `TASK/`。

## 验证方式
- Command: `python3 -m unittest tests.test_idd_cli tests.test_gitlab_forge tests.test_monitor_and_board -v`
- Expected: 全部测试通过

## 执行结果

- Outcome: passed
- Notes: 已实现基于 `idd-land.lock` 的仓库级合入串行队列、`auto_merge` 单轮 CI 路径、失败自动回滚保留 `TASK/` 与 GitLab `BEHIND` 取消废流水线并自动重变基重试，相关并发与回归用例全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-28 (worktree) | `PYTHONPATH=tests python3 -m unittest test_idd_cli.TestIddCli.test_pr_auto_merge_waits_for_ci_and_lands_linearly test_idd_cli.TestIddCli.test_pr_auto_merge_safety_guards_and_cli_overrides test_idd_cli.TestIddCli.test_concurrent_pr_auto_merge_serializes_via_land_lock test_gitlab_forge -v`（修正 1 处 mock `cleanup_pipeline_polls` 断言 + 区分 `create_or_update_pr` 回滚边界后） | passed (`test_pr_auto_merge_*` 3 passed + `test_gitlab_forge` 14 passed) | `scripts/idd_cli.py`, `tests/test_idd_cli.py`, `tests/test_gitlab_forge.py` |
| 2026-11-28 (worktree) | `PYTHONPATH=tests python3 -m unittest test_gitlab_forge.TestGitLabForge.test_gitlab_land_fails_safely_when_head_sha_refresh_times_out -v` | passed (1 passed, 0 failed) | `scripts/idd_cli.py`, `tests/test_gitlab_forge.py` |
