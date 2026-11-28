# TASK-05：架构约束与治理记录

- Issue: #81
- Status: done
- Depends on: TASK-02, TASK-03, TASK-04, TASK-06, TASK-07, TASK-08, TASK-09, TASK-10, TASK-11, TASK-12, TASK-13, TASK-14
- Test: tests/test_architecture.py, .github/workflows/ci.yml

## 任务范围

记录模块依赖、技术选择、状态所有权、替代方案、任务池和产品待决事项。把已治理边界纳入现有 CI。

## 验收标准

- [x] 架构规则、版本一致性和全量测试通过，可从真实入口复核关键约束。

## 验证方式

通过对应的 unittest 和实际命令验证上述行为，结果见下表。

## 执行结果

- Outcome: passed
- Notes: 架构图、状态所有权、决策和待确认事项已落盘。关键调用方向、公共接口、Git 清单、命名规则和普通 CLI 的加载边界进入 CI。独立复审发现的问题均有修复提交及回归。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 0d1dc49 | python3 -B -m unittest discover -s tests -v | 126 项通过 |
| 2026-11-28 / 0d1dc49 | python3 -B scripts/release.py --check | v0.0.4 一致 |
| 2026-11-28 / 0d1dc49 | sh -n install.sh | 通过 |
| 2026-11-28 / 0d1dc49 | PYTHONPATH=tests python3 -B -m unittest -v test_architecture | 5 项通过，Python 导入无环 |
| 2026-11-28 / 0d1dc49 | 图中每条边与 AST 对照 | 18 个模块、45 条内部导入完全一致 |
| 2026-11-28 / 0d1dc49 | 对照原版 CLI 的所有帮助入口 | 30 个路径逐字节一致 |
| 2026-11-28 / 0d1dc49 | 独立审阅者对照及复核 | 4320 个命名样例、693 组交付记录、8 组 HTTP 响应；4 项功能发现已逐条核销，安装启动等待已设时限 |
