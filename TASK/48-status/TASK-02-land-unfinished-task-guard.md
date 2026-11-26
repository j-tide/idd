# TASK-02：idd land 合入前拦截未完成 TASK 并提供强制放行参数

- Issue: #48
- Status: done
- Depends on: TASK-01
- Test: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`

## 任务范围
- 修改 `scripts/idd_cli.py`：新增 `UNFINISHED_LAND_TASK_STATUSES` 与 `_find_unfinished_tasks()`，在 `_execute_land()`（含 `--dry-run` 与 `auto_merge` 自动合入链路）清理与 rebase 前拦截含 `planned`/`in_progress`/`blocked`/`unknown` 状态的 TASK（退出码 `2`），并在 `cmd_land` 与 CLI 参数新增 `--force-unfinished-tasks`
- 更新 `SKILL.md` 中 `idd land` 速查行参数与安全暂停红线
- 在 `tests/test_idd_cli.py` 补全未完成 TASK 拦截、`--force-unfinished-tasks` 放行、`cancelled`/`deferred` 允许合入以及 `auto_merge` 拦截测试
- 不修改 `README.md` 与 `README.en.md`

## 验收标准

- [x] `idd land`（含 `--dry-run` 与 `auto_merge`）在检测到 `planned`/`in_progress`/`blocked`/`unknown` TASK 时以退出码 `2` 拦截并列出未完成项与 `--force-unfinished-tasks` 提示
- [x] `cancelled`/`deferred` TASK 无需额外参数即可正常合入；传入 `--force-unfinished-tasks` 可强制放行
- [x] `SKILL.md` 同步更新且 `python3 scripts/release.py --check` 通过
- [x] 全量单元测试 `python3 -m unittest discover -s tests -v` 通过

## 实现注意事项

- 拦截检查置于 `_require_clean_worktree(wt_path)` 之后、Step A `fetch`/`rebase` 之前

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 全部单测与版本一致性校验通过

## 执行结果

- Outcome: passed
- Notes: 已完成 `idd land` 未完成 TASK 合入拦截、`--force-unfinished-tasks` 参数及 `SKILL.md` 更新，版本一致性校验与全量 88 项单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -k test_land_blocks_unfinished_tasks_and_allows_force_or_terminal_states -v` | passed（1 test in 15.119s, OK） | 覆盖 `in_progress`/`planned`/`blocked` 拦截、`auto_merge` 拦截、`--force-unfinished-tasks` 放行及 `cancelled`/`deferred` 放行 |
| 2026-11-26 | `python3 scripts/release.py --check` | passed（`v0.0.3` 一致性校验通过） | `SKILL.md == README.md == README.en.md == idd --version` |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed（88 tests in 200.421s, OK） | 全量回归测试通过 |
