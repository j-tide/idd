# TASK-02：cmd_land 推后同步等待 head_sha、有限退避重试与端到端回归测试

- Issue: 10-land-wait-head-sha
- Status: done
- Depends on: TASK-01
- Test: python3 -m unittest discover -s tests -v

## 任务范围
- 包含：更新 `scripts/idd_cli.py` 的 `cmd_land`，调整 push 与 `update_change` 顺序，新增 `_is_change_synced_to_head`、`_wait_for_change_head_sync`、`_is_transient_gitlab_merge_error` 与 `_merge_squash_with_retry`，确保普通合入与 `--auto` 均校验 `local_head` 并携带 `expected_sha`；升级 `tests/test_gitlab_forge.py` 与 `tests/test_idd_cli.py` 的 Mock 并新增异步刷新等待、瞬态 406 重试、409 拒绝旧 SHA、同步超时及 `--match-head-commit` 端到端回归测试。
- 不包含：修改与合入流程无关的看板、状态展示或安装脚本逻辑。

## 验收标准

- [x] `cmd_land` 先推送 `local_head` 再更新 PR/MR 描述，随后轮询等待远端 `headRefOid == local_head`（及 `rawSha`）且非 `CHECKING`
- [x] 同步超时时明确报错退出（`exit_code=3`），绝不盲目合入旧 SHA
- [x] 对 GitLab 瞬态 `405/406/409/422` 保持 `expected_sha` 做有限退避重试；若已冲突（`DIRTY`）或非 `--auto` 下 CI `FAIL` 则立即 fail-fast
- [x] 全量单元测试（含新增异步刷新/重试/超时/SHA 锁测试）与版本一致性校验通过

## 实现注意事项

- 超时、轮询间隔、重试延迟支持通过 `IDD_LAND_SYNC_TIMEOUT`、`IDD_LAND_SYNC_INTERVAL`、`IDD_LAND_MERGE_RETRY_DELAY` 覆盖，非法环境变量值安全回退默认值。
- 任何重试分支均严禁去掉 `expected_sha`。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性检查通过且全部单元测试通过。

## 执行结果

- Outcome: passed
- Notes: 已完成 `cmd_land` 推后同步等待、有限退避重试及 GitLab/GitHub 端到端回归测试，版本一致性校验与全部 54 项单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v` | passed（v0.0.3 一致；54 passed） | `scripts/idd_cli.py`, `tests/test_gitlab_forge.py`, `tests/test_idd_cli.py` |
