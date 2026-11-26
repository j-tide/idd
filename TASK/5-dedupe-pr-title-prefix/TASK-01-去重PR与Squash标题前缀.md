# TASK-01：去重 PR 与 Squash 标题前缀

- Issue: #5
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py

## 任务范围
- 包含：
  - 在 `scripts/idd_cli.py` 新增 `CONVENTIONAL_TITLE_RE` 与 `_format_conventional_title` 辅助函数；
  - 在 `build_issue_summary` 中使用 `_format_conventional_title` 处理 `issue_title`、单 `TASK` 标题及单 Commit 变更描述，避免在已有合法 `<type>(<scope>)?!?: ` 前缀时重复拼接 `<dominant_type>: `；
  - 在 `tests/test_idd_cli.py` 补充单元测试与 `idd pr` / `idd land` 端到端回归测试。
- 不包含：改写历史已合入提交记录（如 `4de1d33`）。

## 验收标准

- [x] `build_issue_summary` 在生成 PR / Squash 提交标题时识别已有合法 `<type>(<scope>)?!?: `（含中英文冒号与大小写）前缀并规范化复用，不再重复拼接；
- [x] 非合法提交类型的冒号前缀（如 `API: 新增接口`）仍正常补齐 `<dominant_type>: ` 前缀；
- [x] 在 `tests/test_idd_cli.py` 补充单元测试与 `idd pr` / `idd land` 端到端回归测试，全量单测与 CI 通过。

## 实现注意事项

- 合法前缀仅限 `ALLOWED_TYPES`（`feat|fix|refactor|perf|docs|test|ci|chore`），支持可选 `(scope)`、`!` 及半角/全角冒号；
- 保持 `(#<issue_number>)` 自动附加逻辑不变。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_idd_cli -v && python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单测通过（0 failures / 0 errors），且 `release.py --check` 返回退出码 0。

## 执行结果

- Outcome: passed
- Notes: 已完成 `scripts/idd_cli.py` 中 `CONVENTIONAL_TITLE_RE`、`_format_conventional_title` 与 `build_issue_summary` 标题前缀去重修复，并在 `tests/test_idd_cli.py` 补充单元测试与 `idd pr` / `idd land` 端到端回归测试，全量 51 项单测与版本一致性校验均已通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / base `81d5f45` | `PYTHONPATH=tests python3 -m unittest test_idd_cli -v` | passed (12 tests, 28.892s) | `tests/test_idd_cli.py`（含 `test_pr_and_land_avoid_duplicate_conventional_title_prefixes`） |
| 2026-11-26 / base `81d5f45` | `python3 -m unittest discover -s tests -v` | passed (51 tests, 72.583s) | `tests/` 全量测试套件 |
| 2026-11-26 / base `81d5f45` | `python3 scripts/release.py --check` | passed (`v0.0.3`) | `SKILL.md == README.md == README.en.md == idd --version` |
