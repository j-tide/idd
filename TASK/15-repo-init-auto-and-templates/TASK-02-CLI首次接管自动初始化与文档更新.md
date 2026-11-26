# TASK-02：CLI 首次接管自动初始化与文档更新

- Issue: #15
- Status: done
- Depends on: TASK-01
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 包含：
  - 在 `scripts/idd_cli.py` 为 `issue create`、`start`、`repos add` 增加 `--no-repo-init`，默认首次接管带远端仓库时自动尝试 `repo_init(apply=True)`，跳过或 403/失败时降级记录 `pending` 状态与原因，不阻断主流程；
  - 在 `idd repos list` 文本输出为 `pending` 仓库展示 `[待初始化策略: idd repo-init --apply]`；
  - 更新 `SKILL.md` 与 `references/git-issue-workflow.md`；
  - 在 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 扩展 mock 与自动初始化/跳过/403 降级回归测试。
- 不包含：`idd ui` 前后端（由 TASK-03 负责）。

## 验收标准

- [x] CLI 首次接管默认自动执行 `repo-init --apply` 并标记 `aligned`，后续命令不再重复执行；
- [x] 传入 `--no-repo-init` 或遇到 403/权限异常时记录 `pending`、`mismatches` 及 `error` 且不阻断建单/开工；
- [x] GitHub 与 GitLab 回归测试全部通过。

## 实现注意事项

- 若只读探测本身因未认证或离线抛错，不提前落盘 `pending`，以便登录或联网后再自动完成首次初始化。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_idd_cli test_gitlab_forge -v`
- Expected: 全部通过（0 failures / 0 errors）。

## 执行结果

- Outcome: passed
- Notes: 已完成 `scripts/idd_cli.py` 默认首次接管自动初始化（含 `--no-repo-init` 跳过与 403 降级）、`idd repos list` 待初始化标识、`SKILL.md` / `references/git-issue-workflow.md` 更新及 GitHub/GitLab 回归测试。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / base `59dbe23` | `PYTHONPATH=tests python3 -m unittest test_idd_cli test_gitlab_forge -v` | passed (22 tests, 70.158s) | `tests/test_idd_cli.py`、`tests/test_gitlab_forge.py` |
