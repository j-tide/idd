# TASK-04：同步 SKILL 与文档并完成全量回归验证

- Issue: 28-auto-merge-pr-mr-ci
- Status: planned
- Depends on: TASK-02, TASK-03
- Test: python3 -m unittest discover -s tests -v && python3 scripts/release.py --check

## 任务范围
- 同步更新 `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md`，记录 `idd config`、自动准入/自动合入闭环行为与安全边界。
- 执行全量单元测试与发布一致性检查（`release.py --check`），审核完整 Diff 并对照 Issue 验收标准。
- 创建 PR 并等待远端 CI 结算（遵循授权红线，本 PR 停在待验收状态不擅自合入）。

## 验收标准
- [ ] `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md` 内容准确一致，不改动 `metadata.version`。
- [ ] 全量单元测试与 `scripts/release.py --check` 全部通过。
- [ ] 已发起 PR 且远端 CI 状态明晰。

## 实现注意事项
- 不提前修改版本号；仅在全部功能与文档完成后执行最终全量回归。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全量测试 OK 且版本检查通过。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
