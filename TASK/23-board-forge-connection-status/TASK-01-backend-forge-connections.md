# TASK-01：后端 Forge 连接状态汇总与错误诊断

- Issue: #23
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py, tests/test_gitlab_forge.py

## 任务范围

1. 在 `scripts/forge.py` 中保留 `GitLabForge.list_open_issues` 与 `GitHubForge.list_open_issues` 的真实鉴权（`ForgeAuthError`）及网络/API 异常（`ForgeError`），不再静默返回 `None`。
2. 在 `scripts/monitor.py` 中扩展 `_GH_CLI_CACHE` 与 `_check_gh_cli_status()` 以解析并缓存 `gh auth status` 用户名（兼容 `account <user>` 与 `as <user>` 格式），并在 `collect_auth_hosts_status()` 中回填 `gh_cli` 用户名。
3. 在 `ForgeSnapshotCache` 与 `collect_repo_snapshot` 记录 `forge_host`、`forge_api_base`、`forge_error`，并新增 `_build_forge_connections()` 在 `collect_global_snapshot` 和 `collect_scope_snapshot` 输出 `local_only` 及 `forge_connections`（覆盖 `github` 与 `gitlab` 的 `connected`/`syncing`/`auth_required`/`error`/`partial`/`local_only`/`unconfigured` 状态与主机详情）。

## 验收标准

- [x] `GitLabForge.list_open_issues` 与 `GitHubForge.list_open_issues` 在鉴权失效或网络/API 报错时抛出准确异常
- [x] `_check_gh_cli_status` 正确解析并缓存 `gh` 用户名，且保持 `_GH_CLI_CACHE["checked_at"]` 兼容
- [x] `collect_scope_snapshot` / `collect_global_snapshot` 输出完整的 `forge_connections` 与 `local_only` 字段

## 实现注意事项

- `_build_forge_connections` 会在 2s 轮询中频繁调用，严禁触发未缓存的网络或子进程调用；在 `allow_stale_async=True` 时通过 `_get_gh_cli_status_nonblocking()` 异步探测 `gh auth status`，保持快照秒级返回。
- 当平台所有关联仓库均已连接（`connected_repos == total_repos`）时，后台 TTL 刷新期间保持 `connected` 状态以避免顶栏每 30 秒闪烁。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_gitlab_forge test_monitor_and_board -v`
- Expected: 相关测试全部通过，无回归。

## 执行结果

- Outcome: passed
- Notes: 已完成 `forge.py` 与 `monitor.py` 改造及非阻塞 `gh` 探测优化，24 项回归测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `PYTHONPATH=tests python3 -m unittest test_gitlab_forge test_monitor_and_board -v` | passed (24 passed) | `scripts/forge.py`, `scripts/monitor.py` |
