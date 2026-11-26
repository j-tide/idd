# TASK-01：实现 Issue 标题与简短 scope 校验及 start 分支推断联动

- Issue: 19-issue-title-convention
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 在 `scripts/idd_cli.py` 中新增 `MAX_ISSUE_SCOPE_LEN = 16`、`ISSUE_SCOPE_RE`、`_validate_issue_scope`、`validate_and_format_issue_title`、`_infer_prefix_from_title` 与 `_slug_source_from_issue_title`；
- 更新 `cmd_issue_create` 与 `build_parser()` 中的 `issue create` 参数（新增 `--type`、`--scope`、`--raw`）；
- 更新 `cmd_start` 的分支类型推断优先级（`--prefix` > Issue 标题 `<type>` > Label > `feat`）及 slug 生成逻辑（剥离 `<type>:` 前缀避免重复）；
- 适配 `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 中既有 `issue create` 调用，并补充针对性的单元与集成测试。
- 不包含：修改已有 Open Issue 标题；修改下游 `pr`/`land` 对外部无前缀 Issue 的兼容行为。

## 验收标准

- [x] `idd issue create` 默认要求 `<type>: <描述>` 或 `<type>(<scope>): <描述>`，且 `scope` 必须匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$` 且长度 ≤ 16 字符；支持 `--type`、`--scope` 拼接与 `--raw` 逃生参数
- [x] `idd start` 优先读取 Issue 标题中的 `<type>` 决定分支前缀，自动生成 `slug` 时不重复拼接 `<type>`，且对无前缀历史 Issue 保持兼容
- [x] `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 全部通过

## 实现注意事项

- `--raw` 禁止与 `--type` 或 `--scope` 同时传入；
- 若 `--type` 或 `--scope` 与 `--title` 中已有值冲突，必须报错提示而非静默覆盖；
- 先校验标题再访问远端 Forge，确保非法标题能立即快速报错。

## 验证方式

- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 所有测试全部通过（OK）。

## 执行结果

- Outcome: passed
- Notes: 已实现 `idd issue create` 的标题与简短 scope（≤ 16 字符）校验及 `--type`/`--scope`/`--raw` 参数，并完成 `idd start` 标题类型与去重 slug 推断联动，26 项单测全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v` | passed (26 tests in 75.895s) | `scripts/idd_cli.py`, `tests/test_idd_cli.py`, `tests/test_gitlab_forge.py` |
