# TASK-01：强化 `SKILL.md` 与 `references/visual-alignment.md` 方案确认门禁

- Issue: #71
- Status: done
- Depends on: none
- Test: 核对 `SKILL.md` 与 `references/visual-alignment.md` Diff、关键词排查旧豁免文案，并运行 `python3 -m unittest tests/test_version_and_release.py`

## 任务范围
- 更新 `SKILL.md` 的 frontmatter `description`、总纲、`idd` 速查表、`## 三、入口分流`（新增前置硬门禁并更新模式 A/B/C）及第七节执行红线，确立「先确认方案、再建单开工」硬门禁与仅有的 2 条免确认例外。
- 更新 `references/visual-alignment.md`，明确 Bug 修复与纯内部重构「仅豁免交互原型，不豁免方案确认」，以及用户明确拍板确认前严禁调用 `idd issue create`。
- 不包含 `README.md`、`README.en.md`（由 `TASK-02` 处理），不修改 `install.sh` 与 `metadata.version`。

## 验收标准

- [x] `SKILL.md` 移除“无 UI / 无交互歧义的明确单点修复可直接推进”旧豁免，明确禁止同轮边输出方案边顺手建单
- [x] `SKILL.md` 明确仅有的 2 条免确认例外（已有清晰验收标准 Issue / 本轮显式授权免确认）
- [x] `references/visual-alignment.md` 明确「仅豁免交互原型，不豁免方案确认」
- [x] `tests/test_version_and_release.py` 通过且 `metadata.version` 保持不变

## 实现注意事项

- 保持流程轻量，仅规定输出简明开发/修改方案与原型/样例对齐，不要求重量级 PRD/Design 文档。

## 验证方式

- Command: `python3 -m unittest tests/test_version_and_release.py` 及关键词检查
- Expected: 测试全部通过，无旧的跳过确认文案残留

## 执行结果

- Outcome: passed
- Notes: 已完成 `SKILL.md` 与 `references/visual-alignment.md` 的先确认方案再建单硬门禁更新，旧豁免措辞已清除，版本与发布单测通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest tests/test_version_and_release.py` | passed（Ran 5 tests in 6.438s, OK） | `SKILL.md` / `references/visual-alignment.md` |
| 2026-11-27 | 正则检索旧豁免措辞（`无 UI / 无交互歧义`、`明确单点 Bug 除外`、`**豁免原型**`） | passed（0 matches） | `TASK/71-skill/TASK-01-skill-and-visual-gate.md` |
