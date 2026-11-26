# TASK-01：实现 land 合入后自动勾选验收标准与测试

- Issue: 8-land-check-acceptance
- Status: done
- Depends on: none
- Test: `tests/test_idd_cli.py`、`tests/test_gitlab_forge.py`

## 任务范围
- 在 `scripts/idd_cli.py` 新增验收标准标题识别与复选框勾选逻辑（`check_acceptance_criteria`），支持 `--no-check-acceptance` 参数。
- 更新 `cmd_land`：合入真正完成后自动勾选 Issue 正文「验收标准」节内未勾选的复选框并保底刷新 `TASK` 进度块；回写失败时仅输出告警而不阻断 `main` 快进；`--auto` 不提前勾选；`--dry-run` 展示预计勾选数。
- 在 `tests/test_idd_cli.py` 和 `tests/test_gitlab_forge.py` 补齐单测与端到端测试。
- 不含文档更新（由 `TASK-02` 承接）。

## 验收标准

- [x] `check_acceptance_criteria` 正确识别中英文验收节标题，保留子标题并终止于同级/更高级后续标题或 `<!-- idd:progress:start -->`，跳过围栏代码块
- [x] `idd land` 合入成功后自动勾选验收标准、同步进度块；支持 `--no-check-acceptance`、`--auto`、`--dry-run`；回写异常时非致命告警
- [x] GitHub 与 GitLab 单元测试和端到端测试全部通过

## 实现注意事项

- 仅修改验收节内的未勾复选框，不触碰「后续计划」、围栏代码块或进度块。
- 在 `cmd_land` 删除 `TASK/<issue_dir>/` 前先收集本地任务状态供合入后保底同步进度块。

## 验证方式

- Command: `python3 -m unittest tests.test_idd_cli tests.test_gitlab_forge -v`
- Expected: 所有用例全部通过

## 执行结果

- Outcome: passed
- Notes: 已实现 `check_acceptance_criteria`、`--no-check-acceptance` 与 `cmd_land` 合入后自动勾选及进度保底刷新逻辑，GitHub 与 GitLab 共 15 项测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests.test_idd_cli tests.test_gitlab_forge -v` | passed（15 passed，含 2 个新增 GitHub 用例与更新后的 GitLab 端到端用例） | `scripts/idd_cli.py`、`tests/test_idd_cli.py`、`tests/test_gitlab_forge.py` |
