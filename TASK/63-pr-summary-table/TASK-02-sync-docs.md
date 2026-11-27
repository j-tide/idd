# TASK-02：同步 PR/MR 汇总正文模板文档与全量验收

- Issue: #63
- Status: done
- Depends on: TASK-01
- Test: python3 -m unittest discover -s tests -v && python3 scripts/release.py --check

## 任务范围
- 更新 `SKILL.md` 中 PR / MR 汇总正文模板与说明，反映 `## 变更内容` 列表 + `## 验证记录` 表格及 `<details>` 折叠块。
- 更新 `references/git-issue-workflow.md` 中对 `idd pr` / `idd mr` 生成正文的简要描述。
- 运行全量单测与发布规范检查 `scripts/release.py --check`。

## 验收标准

- [x] `SKILL.md` 与 `references/git-issue-workflow.md` 文档与实际代码输出一致。
- [x] `python3 -m unittest discover -s tests -v` 与 `python3 scripts/release.py --check` 全部通过。

## 实现注意事项

- 保持文档中主线 Squash Commit 纯文本模板与现有行为一致，不引入冗余改动。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部单测通过且 `release.py --check` 返回 0。

## 执行结果

- Outcome: passed
- Notes: 文档模板与流程说明已同步，全量 93 项单测与版本一致性校验全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check` | passed (93 tests; v0.0.4 consistency ok) | `SKILL.md`, `references/git-issue-workflow.md` |
