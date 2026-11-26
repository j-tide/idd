# TASK-02：同步规范文档并执行全量验收检查

- Issue: 19-issue-title-convention
- Status: planned
- Depends on: TASK-01
- Test: python3 -m unittest discover -s tests -v & python3 scripts/release.py --check

## 任务范围
- 同步更新 `SKILL.md`、`references/git-issue-workflow.md`、`README.md` 与 `README.en.md` 中的 Issue 标题规范（`<type>(<scope>): <简明描述>`、简短 scope ≤ 16 字符约束、去冗余动词与长度建议）、`idd issue create` 参数说明及 `idd start` 类型推断优先级；
- 在工作树执行全量单元测试与版本一致性检查。
- 不包含：新增依赖或变更版本号。

## 验收标准

- [ ] `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md` 内容准确一致
- [ ] `python3 -m unittest discover -s tests -v` 全量通过
- [ ] `python3 scripts/release.py --check` 通过

## 实现注意事项

- 文档示例需严格遵守新的短 scope 规则（≤ 16 字符，单个小写英文标识，无冗余动词）。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单测与版本一致性检查通过。

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
