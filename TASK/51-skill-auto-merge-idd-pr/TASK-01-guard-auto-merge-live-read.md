# TASK-01：补充禁止擅自覆写 auto_merge 开关并要求 idd pr 实时读取的规范

- Issue: #51
- Status: done
- Depends on: none
- Test: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`

## 任务范围
- 在 `SKILL.md` 第五节补充：默认直接运行无参 `idd pr` / `idd mr`，禁止未经用户要求擅自附加 `--no-auto-merge` / `--auto-merge` 或缓存早期 `idd config` 快照
- 同步在 `references/git-issue-workflow.md` 第五节补充对应约束
- 不修改 Python 代码及无关文档

## 验收标准

- [x] `SKILL.md` 明文禁止 Agent 未经用户明确要求擅自覆写 `auto_merge` 标志，并要求由 `idd pr` 实时读取配置
- [x] `references/git-issue-workflow.md` 与 `SKILL.md` 约定保持一致
- [x] `python3 scripts/release.py --check` 与 `python3 -m unittest discover -s tests -v` 全部通过

## 实现注意事项

- 保留既有 `--auto-merge` / `--no-auto-merge` 的用户显式单次覆写能力，仅约束 Agent 默认行为

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性校验通过，全部单元测试通过

## 执行结果

- Outcome: passed
- Notes: 已在 `SKILL.md` 与 `references/git-issue-workflow.md` 补充禁止擅自覆写 `auto_merge` 开关的约定，版本校验与 85 项单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 scripts/release.py --check` | passed（`v0.0.3` 一致性校验通过） | `SKILL.md == README.md == README.en.md == idd --version` |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed（85 tests in 232.299s, OK） | 全量单测无跳过 |
