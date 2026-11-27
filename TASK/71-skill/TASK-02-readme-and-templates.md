# TASK-02：同步 `README.md` 与 `README.en.md` 工作流说明及规则模板

- Issue: #71
- Status: done
- Depends on: TASK-01
- Test: 运行全量单元测试 `python3 -m unittest discover -s tests` 并排查中英文文档与模板一致性

## 任务范围
- 更新 `README.md` 与 `README.en.md` 的「工作原理」「自然语言驱动表」以及可选模板（「个人全局默认」「项目级强制」），将「先确认方案，再建 Issue 与 Worktree」写为第一条硬约定并列出 2 条免确认例外。
- 不修改 `install.sh`（保持零侵入），不改动版本号徽章与中英文切换链接。

## 验收标准

- [x] `README.md` 与 `README.en.md` 的工作原理、自然语言场景及两套规则模板全面同步「先确认方案再建单」约定
- [x] 全量单元测试 `python3 -m unittest discover -s tests` 全部通过
- [x] `git diff origin/main...HEAD` 仅包含预期文档与 `TASK/` 变更

## 实现注意事项

- 保持中英文内容一一对应，保留顶部版本号徽章和语言切换链接不变。

## 验证方式

- Command: `python3 -m unittest discover -s tests`
- Expected: 全部单元测试通过，退出码为 0

## 执行结果

- Outcome: passed
- Notes: 已完成 `README.md` 与 `README.en.md` 的工作流说明及两套规则模板同步，中英文一致且旧文案已清零，全量单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest discover -s tests` | passed（Ran 93 tests in 370.014s, OK） | `README.md` / `README.en.md` |
| 2026-11-27 | 正则排查旧文案与 `git diff --stat origin/main...` 核对 | passed（0 matches；仅含预期 6 个文档/TASK 文件） | `TASK/71-skill/TASK-02-readme-and-templates.md` |
