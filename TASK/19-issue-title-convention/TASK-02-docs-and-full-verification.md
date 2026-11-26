# TASK-02：同步规范文档并执行全量验收检查

- Issue: 19-issue-title-convention
- Status: done
- Depends on: TASK-01
- Test: python3 -m unittest discover -s tests -v & python3 scripts/release.py --check

## 任务范围
- 同步更新 `SKILL.md`、`references/git-issue-workflow.md`、`README.md` 与 `README.en.md` 中的 Issue 标题规范（`<type>(<scope>): <简明描述>`、简短 scope ≤ 16 字符约束、去冗余动词与长度建议）、`idd issue create` 参数说明及 `idd start` 类型推断优先级；
- 在工作树执行全量单元测试与版本一致性检查。
- 不包含：新增依赖或变更版本号。

## 验收标准

- [x] `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md` 内容准确一致
- [x] `python3 -m unittest discover -s tests -v` 全量通过
- [x] `python3 scripts/release.py --check` 通过

## 实现注意事项

- 文档示例需严格遵守新的短 scope 规则（≤ 16 字符，单个小写英文标识，无冗余动词）。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单测与版本一致性检查通过。

## 执行结果

- Outcome: passed
- Notes: 已同步更新 `SKILL.md`、`references/git-issue-workflow.md`、`README.md` 与 `README.en.md`，全量 63 项单元测试及版本一致性检查全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 scripts/release.py --check` | passed (`v0.0.3`) | `SKILL.md`, `README.md`, `README.en.md` |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed (63 tests in 116.126s) | `tests/` |
