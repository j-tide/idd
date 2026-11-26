# TASK-01：首次接管仓库策略探测与提示

- Issue: #7
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 包含：
  - 在 `scripts/monitor.py` 扩展 `~/.config/idd/repos.json` 可选字段 `repo_init_state`（`prompted` / `aligned`）读取、持久化与既有字段保留；
  - 在 `scripts/idd_cli.py` 新增 `evaluate_repo_init_settings` 与 `_maybe_check_first_time_repo_init`，并在 `cmd_issue_create`、`cmd_start`、`cmd_repos`（`add`）及 `cmd_repo_init` 接入一次性探测、提示输出（含 `--json` 的 `repo_init_hint` 字段）与状态同步；
  - 在 `SKILL.md` 与 `references/git-issue-workflow.md` 补充首次接管提示及确认后执行 `idd repo-init --apply` 的工作流约定；
  - 在 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 补充 GitHub / GitLab 回归测试。
- 不包含：未经用户确认自动修改远端仓库合入策略，以及改写已有仓库的历史记录。

## 验收标准

- [x] `~/.config/idd/repos.json` 持久化可选字段 `repo_init_state`（`prompted` / `aligned`），并保持既有字段向后兼容；
- [x] 首次在带远端的仓库运行 `idd issue create`、`idd start` 或 `idd repos add` 时，只读探测一次远端合入策略（离线/无鉴权/无权限时静默跳过不阻断主流程）；若未锁定线性 Squash + 保留分支，输出 `💡 首次接管提示`（`--json` 模式写入 `repo_init_hint` 字段保持 JSON 合法），且后续不再重复刷屏；
- [x] 运行 `idd repo-init [--apply]` 后同步更新该仓库的 `repo_init_state`；
- [x] 更新 `SKILL.md` 与 `references/git-issue-workflow.md`，约定 Agent 看到首次接管提示后先向用户确认，再执行 `idd repo-init --apply`；
- [x] 在 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 补充 GitHub / GitLab 回归测试，全量单测与 CI 通过。

## 实现注意事项

- 所有只在首次探测失败/离线/无鉴权时静默跳过（不阻断 `issue create` / `start` / `repos add`）；
- `register_repo` 与 `load_registered_repos` 触达已有仓库时必须保留既有 `repo_init_state` 字段，避免重置提示状态。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_idd_cli test_gitlab_forge test_monitor_and_board -v && python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单测通过（0 failures / 0 errors），且 `release.py --check` 返回退出码 0。

## 执行结果

- Outcome: passed
- Notes: 已完成 `scripts/monitor.py` 状态持久化、`scripts/idd_cli.py` 一次性远端合入策略探测与提示、`SKILL.md` / `references/git-issue-workflow.md` 规范联动，以及 GitHub / GitLab 回归测试；全量 52 项单测与版本一致性校验全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / base `81d5f45` | `PYTHONPATH=tests python3 -m unittest test_idd_cli test_gitlab_forge test_monitor_and_board -v` | passed (28 tests, 55.226s) | `tests/test_idd_cli.py`、`tests/test_gitlab_forge.py`、`tests/test_monitor_and_board.py` |
| 2026-11-26 / base `81d5f45` | `python3 -m unittest discover -s tests -v` | passed (52 tests, 75.440s) | `tests/` 全量测试套件 |
| 2026-11-26 / base `81d5f45` | `python3 scripts/release.py --check` | passed (`v0.0.3`) | `SKILL.md == README.md == README.en.md == idd --version` |
