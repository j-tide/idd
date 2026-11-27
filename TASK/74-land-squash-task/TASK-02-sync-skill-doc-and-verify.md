# TASK-02：同步 SKILL 正文模板示例并执行全量验收

- Issue: #74
- Status: done
- Depends on: TASK-01
- Test: python3 -m unittest discover -s tests -p "test_*.py" -v && python3 scripts/release.py --check

## 任务范围
- 更新 `SKILL.md` 中「主线 Squash Commit 正文模板」描述与示例，明确块内紧缩无空行、仅在不同 `TASK` 之间以空行隔离。
- 在工作树内执行全量单元测试与发布一致性检查。

## 验收标准

- [x] `SKILL.md` 模板示例与实际生成的 Squash Commit 纯文本格式一致
- [x] 全量单元测试 `python3 -m unittest discover -s tests -p "test_*.py" -v` 全部通过
- [x] `python3 scripts/release.py --check` 通过

## 实现注意事项

- 不修改无关文档或规则文件。

## 验证方式

- Command: `python3 -m unittest discover -s tests -p "test_*.py" -v && python3 scripts/release.py --check`
- Expected: 全量测试与发布检查均通过（exit code 0）

## 执行结果

- Outcome: passed
- Notes: 已更新 `SKILL.md` 模板示例，全量 100 项单测与发布版本一致性检查全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 / worktree | `python3 -m unittest discover -s tests -p "test_*.py" -v` | passed (100 tests) | 全量单元测试通过 |
| 2026-11-27 / worktree | `python3 scripts/release.py --check` | passed (v0.0.4) | `SKILL.md == README.md == README.en.md == idd --version` |
