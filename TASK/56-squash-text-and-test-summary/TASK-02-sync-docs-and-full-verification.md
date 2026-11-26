# TASK-02：同步规范文档并完成全量回归与发布校验

- Issue: 56-squash-text-and-test-summary
- Status: done
- Depends on: TASK-01
- Test: `tests/` 全量测试与 `scripts/release.py --check`

## 任务范围
- 更新 `SKILL.md` 与 `references/git-issue-workflow.md`，说明多行 `Test:` 累加、PR/MR Markdown 模板（含按需折叠完整命令）与 Squash Commit 零 Markdown 纯文本模板。
- 运行全量单元测试与发布一致性检查。

## 验收标准

- [x] `SKILL.md` 与 `references/git-issue-workflow.md` 准确反映双格式汇总行为
- [x] `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check` 全部通过

## 实现注意事项

- 仅更新与本次正文双格式及多测试拆分直接相关的说明，不改无关文档。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全量单测 0 失败且版本一致性校验通过

## 执行结果

- Outcome: passed
- Notes: 已同步 `SKILL.md` 与 `references/git-issue-workflow.md`，全量 89 项测试与版本一致性检查全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check` | 89 passed; v0.0.3 一致性校验通过 | `tests/` 全量套件与 `scripts/release.py` |
