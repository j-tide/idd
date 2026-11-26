# TASK-04：同步 SKILL 与文档并完成全量回归验证

- Issue: 28-auto-merge-pr-mr-ci
- Status: done
- Depends on: TASK-02, TASK-03
- Test: python3 -m unittest discover -s tests -v && python3 scripts/release.py --check

## 任务范围
- 同步更新 `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md`，记录 `idd config`、自动准入/自动合入闭环行为与安全边界。
- 执行全量单元测试与发布一致性检查（`release.py --check`），审核完整 Diff 并对照 Issue 验收标准。
- 创建 PR 并等待远端 CI 结算（遵循授权红线，本 PR 停在待验收状态不擅自合入）。

## 验收标准
- [x] `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md` 内容准确一致，不改动 `metadata.version`。
- [x] 全量单元测试与 `scripts/release.py --check` 全部通过。
- [x] 已发起 PR 且远端 CI 状态明晰。

## 实现注意事项
- 不提前修改版本号；仅在全部功能与文档完成后执行最终全量回归。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全量测试 OK 且版本检查通过。

## 执行结果
- Outcome: passed
- Notes: 已同步更新 `SKILL.md`、工作流文档与中英文 README，全量 75 项单元测试与版本一致性校验全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed (75/75) | `tests/` |
| 2026-11-26 | `python3 scripts/release.py --check` | passed (`v0.0.3` 一致性通过) | `scripts/release.py` |
