# TASK-01：收紧 Squash 正文单个 TASK 内部空行并补齐单测

- Issue: #74
- Status: done
- Depends on: none
- Test: python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v

## 任务范围
- 在 `scripts/idd_cli.py` 新增 `_format_plain_task_block` 辅助函数，并在 `build_issue_summaries` 中替换旧的 `plain_blocks` 拼接逻辑：单个 `TASK` 块内紧缩无空行（顶格不缩进，若 `extra` 含内部空行亦折叠去除），仅在 `Closes #<id>` 与不同 `TASK` 之间保留 1 个空行，保持零 Markdown 纯文本。
- 保持 PR / MR 的 Markdown 汇总正文（`## 变更内容`、`## 验证记录`、`<details>`）不受影响。
- 更新并补充 `tests/test_idd_cli.py` 与验证 `tests/test_gitlab_forge.py`（覆盖单/多 TASK、无说明、单段/多段说明、单条/多条 `Test:` 及相邻两项均带说明的场景）。
- 不含 `SKILL.md` 模板示例更新与全量发布检查（由 `TASK-02` 负责）。

## 验收标准

- [x] `_format_plain_task_block` 生成紧凑零 Markdown、无尾随空格、块内零空行的纯文本块
- [x] 多 TASK 之间及 `Closes #<id>` 后均以单个空行隔离
- [x] PR/MR Markdown 正文格式保持不变
- [x] `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 全部通过

## 实现注意事项

- 严禁使用 `---` 分隔线或连续双空行 `\n\n\n`。
- `tests/test_idd_cli.py` 中的 `expected_single_pr` 保持不变。

## 验证方式

- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 全部测试通过（exit code 0）

## 执行结果

- Outcome: passed
- Notes: 已实现 `_format_plain_task_block` 并更新/补充 `test_idd_cli.py` 与 `test_gitlab_forge.py` 断言，37 项单测全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 / worktree | `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v` | passed (37 tests) | `scripts/idd_cli.py`、`tests/test_idd_cli.py`、`tests/test_gitlab_forge.py` |
