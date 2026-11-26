# TASK-01：精简验收后准入回执并要求 Issue 与 PR 链接可点击

- Issue: #35
- Status: done
- Depends on: none
- Test: 文档规则更新，通过 `python3 scripts/release.py --check`、`python3 -m unittest discover -s tests -v` 与 Markdown/Diff 人工核对验证

## 任务范围
- 更新 `references/final-reply.md`：
  - 区分「标准模板」与「验收后准入回执（精简版）」的适用边界；
  - 新增「验收后准入回执（精简版）」章节，省略「完成内容」「验证结果」与「交付状态」小标题，明确标明 PR / MR 已合入，并约定仅在出现 Rebase 解冲突复测、`--auto` 等待、主线未快进或 `evidence/` 清理暂停等额外情况时追加 `⚠️ 说明`；
  - 在「标准模板」与「精简准入回执」中统一要求关联的 Issue 和 PR / MR 使用可点击 Markdown 链接。
- 更新 `SKILL.md` 第七节「最终回复」，同步说明两档模板与可点击链接要求。
- 不改动 `idd` CLI 代码逻辑与版本号。

## 验收标准

- [x] `references/final-reply.md` 明确区分「标准模板」与「验收后准入回执（精简版）」的适用边界
- [x] 精简准入回执模板省略「完成内容」「验证结果」及「交付状态」小标题，并明确标明 PR / MR 已合入
- [x] 「标准模板」与「精简准入回执」均明确要求关联的 Issue 和 PR / MR 使用可点击 Markdown 链接并给出对应示例
- [x] `SKILL.md` 第七节「最终回复」同步说明两档模板与准入回执要求
- [x] `python3 scripts/release.py --check` 与全量单元测试通过

## 实现注意事项

- 保留既有受阻写法与各状态语义，不改变提请验收、同轮直通合入与受阻场景的完整报告结构。
- 严格遵循 `references/task-records.md` 规范。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性校验通过，全量单元测试全部通过，且 `git diff` 仅包含预期文档与任务记录改动。

## 执行结果

- Outcome: passed
- Notes: 已更新 `references/final-reply.md` 与 `SKILL.md`，新增「验收后准入回执（精简版）」并统一要求 Issue / PR / MR 使用可点击 Markdown 链接，版本校验与全量 82 项单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 (`docs/35-reply`) | `python3 scripts/release.py --check` | passed (`v0.0.3`: `SKILL.md == README.md == README.en.md == idd --version`) | 工作树命令输出 |
| 2026-11-26 (`docs/35-reply`) | `python3 -m unittest discover -s tests -v` | passed (82 tests OK in 208.233s) | 工作树命令输出 |
| 2026-11-26 (`docs/35-reply`) | `git diff` 人工核对 | passed（仅改动 `references/final-reply.md`、`SKILL.md` 与本任务文件） | `git diff` |
