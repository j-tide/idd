# TASK-02：同步更新 SKILL 与文档说明

- Issue: 8-land-check-acceptance
- Status: done
- Depends on: TASK-01
- Test: `python3 scripts/release.py --check` 与文档一致性检查（`idd land --help` 对照）

## 任务范围
- 在 `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md` 补充 `idd land` 合入成功后自动勾选 Issue 验收标准与 `--no-check-acceptance` 参数说明。
- 不修改任何版本号，确保 `release.py --check` 校验通过。

## 验收标准

- [x] 四个文档中 `idd land` 的说明准确反映默认自动勾选验收标准及 `--no-check-acceptance` 开关
- [x] `python3 scripts/release.py --check` 通过且与 `idd land --help` 一致

## 实现注意事项

- 保持现有表格格式与风格一致，不引入冗余文档或版本变更。

## 验证方式

- Command: `python3 scripts/idd land --help && python3 scripts/release.py --check`
- Expected: 输出包含 `--no-check-acceptance` 说明，且版本一致性检查退出码为 0

## 执行结果

- Outcome: passed
- Notes: 已更新四个文档中的 `idd land` 说明并与 `idd land --help` 对齐，版本一致性校验通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 scripts/idd land --help && python3 scripts/release.py --check` | passed（帮助信息包含 `--no-check-acceptance`，版本一致性通过 `v0.0.3`） | `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md` |
