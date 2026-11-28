# TASK-02：BEHIND 止损、取消废流水线与并发合入核验

- Issue: #79
- Status: in_progress
- Depends on: TASK-01
- Test: tests/test_gitlab_forge.py, tests/test_idd_cli.py

## 任务范围
- 在 `scripts/forge.py` 为 `GitLabForge._normalize_mr` 暴露 `headPipelineId` 与 `headPipelineStatus`，为 `GitHubForge` 与 `GitLabForge` 增加 `cancel_change_pipeline()` 方法。
- 在 `scripts/idd_cli.py` 增强 `_wait_for_ci_settlement(..., abort_on_behind: bool = False)`，遇到 `DIRTY` 或（`abort_on_behind` 时）`BEHIND` 立即中止等待。
- 修复 `_gitlab_land_result` 在紧邻并发第二次合入导致 `origin/main` 继续前移时的误报，同时保留对非 Squash 多提交合入的严格拦截。
- 在 `tests/test_gitlab_forge.py` 补齐流水线取消、状态提前中止及并发第二次合入验证测试。

## 验收标准
- [ ] `GitLabForge.cancel_change_pipeline` 仅对活跃态流水线发送 `POST .../pipelines/<id>/cancel` 且容错不崩溃
- [ ] `_wait_for_ci_settlement` 在 `BEHIND`（当 `abort_on_behind=True`）与 `DIRTY` 时立即提前返回，不再死等超时
- [ ] `_gitlab_land_result` 在远端已紧跟合入后一条时通过单父祖先链路校验返回 `squashCommitOid`，非 Squash 多提交仍严格报错

## 实现注意事项
- 当 `after == merged_oid` 时保持原有严格校验 `parents == [after, before]` 与错误文案，确保既有断言完全兼容。

## 验证方式
- Command: `python3 -m unittest tests.test_gitlab_forge tests.test_idd_cli -v`
- Expected: 新增与既有测试全部通过

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
