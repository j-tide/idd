# TASK-01：核对 GitLab 强制 Squash 与合入结果

- Issue: 14-gitlab-land-squash-verification
- Status: done
- Depends on: none
- Test: tests/test_gitlab_forge.py，tests/test_idd_cli.py

## 任务范围

为 GitLab 的 idd land 增加合入前项目配置检查和合入后远端目标分支核对。用模拟 GitLab 和真实 Git 引用复现 Argus !17 暴露的问题。

## 验收标准

- [x] 配置未确认是快进和强制 Squash 时，停止本次合入，保留 TASK 和远端 MR。
- [x] GitLab 与远端 Git 同时证明本次只新增一条直接后继提交后，才报告合入成功和勾选 Issue 验收。
- [x] 合入结果不符时返回错误并提示检查现有远端历史。自动合入尚在等待时仅报告请求状态。
- [x] 已有 GitHub 与 GitLab 合入回归通过。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v`、`python3 scripts/release.py --check`、`python3 -m compileall -q scripts tests`、`git diff --check`。
- Expected: 真实 Git 流程验证拒绝不正确配置及多提交结果，合规合入和异步路径返回准确状态。

## 执行结果

- Outcome: passed
- Notes: GitLab 与 CLI 合入回归通过。

### 验证记录

| 日期 / 修订 | 操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-26 / TASK-01 | Python 3.12 单独运行 test_gitlab_forge.py 与 test_idd_cli.py | 25 项通过。模拟 GitLab 返回成功但实际快进 5 条时，CLI 返回错误且 Issue 验收仍未勾选。 |
| 2026-11-26 / TASK-01 | `scripts/release.py --check`、`compileall -q scripts tests`、`git diff --check` | 通过。 |
| 2026-11-26 / 66143a0 基线及任务首轮 | macOS 全量回归及基线复测 | 任务首轮 59 项通过、1 项错误。看板断连测试在未改动的基线上也复现 ConnectionResetError。 |
