# TASK-04：工作流文档同步与全量回归验证

- Issue: #79
- Status: done
- Depends on: TASK-03
- Test: python3 -m py_compile scripts/*.py && python3 -m unittest discover -s tests -v

## 任务范围
- 更新 `SKILL.md` 与 `references/git-issue-workflow.md`，补充仓库级合入串行队列（`idd-land.lock`）、`auto_merge` 单轮 CI 与失败回滚保留 `TASK/`、GitLab `need_rebase` 自动止损与取消废流水线说明。
- 运行全量字节码编译检查与完整单元测试套件。

## 验收标准
- [x] `SKILL.md` 与 `references/git-issue-workflow.md` 描述与实际实现一致
- [x] `python3 -m py_compile scripts/*.py && python3 -m unittest discover -s tests -v` 全部通过

## 实现注意事项
- 仅补充与本次并发合入改进相关的必要说明，保持文档简洁。

## 验证方式
- Command: `python3 -m py_compile scripts/*.py && python3 -m unittest discover -s tests -v`
- Expected: 全部编译通过且全部测试用例 `OK`

## 执行结果

- Outcome: passed
- Notes: 已更新 `SKILL.md` 与 `references/git-issue-workflow.md`；全量语法编译与全部 107 个单元测试（含 6 个新增并发/锁/`BEHIND` 用例）均通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-28 (worktree) | `python3 -m py_compile scripts/*.py && python3 -m unittest discover -s tests -v` | passed (107 passed, 0 failed) | `scripts/*.py`, `tests/*.py`, `SKILL.md`, `references/git-issue-workflow.md` |
| 2026-11-28 (worktree) | `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null PYTHONPATH=tests python3 -m unittest test_gitlab_forge -v`（修复 GitHub Actions 无全局 Git 作者配置导致的 `commit-tree` 报错） | passed (14 passed, 0 failed) | `tests/test_gitlab_forge.py` |
