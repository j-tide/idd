# TASK-01：严格按独立行与非代码块匹配进度块并补齐测试

- Issue: 13-progress-block-line-anchor
- Status: done
- Depends on: none
- Test: `tests/test_idd_cli.py`

## 任务范围
- 更新 `scripts/idd_cli.py` 中的 `PROGRESS_RE`、`_update_fence_state`、`_find_progress_block_span`、`merge_progress_block`、`check_acceptance_criteria` 与 `cmd_land`，确保进度块仅在非代码块中以整行独立标记匹配，不被正文行内引用或代码块示例误截断。
- 在 `tests/test_idd_cli.py` 补齐 `merge_progress_block`、`check_acceptance_criteria` 以及复现 Issue #8 场景的 `idd sync` + `idd land` 端到端回归测试。

## 验收标准

- [x] `merge_progress_block` 与 `idd sync` 仅替换非代码块中独立成行的进度块，保留行内引用与代码块示例及后续章节
- [x] `check_acceptance_criteria` 不被验收项中的行内标记或围栏代码示例提前截断
- [x] 新增单测与端到端回归测试及全量测试、`release.py --check` 全部通过

## 实现注意事项

- 复用同一围栏代码块跟踪辅助函数 `_update_fence_state`，避免在 `_find_progress_block_span` 与 `check_acceptance_criteria` 中重复实现。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部测试通过且 `release.py --check` 退出码为 0

## 执行结果

- Outcome: passed
- Notes: 已修复进度块整行锚定与围栏跳过逻辑，并同步修复 `check_acceptance_criteria` 对进度块标记的检测顺序，全量 58 项测试与版本一致性校验均通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check` | passed（58 passed，含新增单元测试与 Issue #8 端到端回归；版本校验 `v0.0.3` 通过） | `scripts/idd_cli.py`、`tests/test_idd_cli.py` |
