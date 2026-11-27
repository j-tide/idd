# TASK-02：同步 `README.md` 与 `README.en.md` 工作流说明及规则模板

- Issue: #71
- Status: planned
- Depends on: TASK-01
- Test: 运行全量单元测试 `python3 -m unittest discover -s tests` 并排查中英文文档与模板一致性

## 任务范围
- 更新 `README.md` 与 `README.en.md` 的「工作原理」「自然语言驱动表」以及可选模板（「个人全局默认」「项目级强制」），将「先确认方案，再建 Issue 与 Worktree」写为第一条硬约定并列出 2 条免确认例外。
- 不修改 `install.sh`（保持零侵入），不改动版本号徽章与中英文切换链接。

## 验收标准

- [ ] `README.md` 与 `README.en.md` 的工作原理、自然语言场景及两套规则模板全面同步「先确认方案再建单」约定
- [ ] 全量单元测试 `python3 -m unittest discover -s tests` 全部通过
- [ ] `git diff origin/main...HEAD` 仅包含预期文档与 `TASK/` 变更

## 实现注意事项

- 保持中英文内容一一对应，保留顶部版本号徽章和语言切换链接不变。

## 验证方式

- Command: `python3 -m unittest discover -s tests`
- Expected: 全部单元测试通过，退出码为 0

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
