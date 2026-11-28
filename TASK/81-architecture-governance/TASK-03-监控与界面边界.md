# TASK-03：监控与界面边界

- Issue: #81
- Status: done
- Depends on: TASK-01
- Test: tests/test_monitor_and_board.py, tests/test_preview_ui.py

## 任务范围

由监控拥有快照与缓存内部状态，迁移跨模块私有访问，按需加载界面。

## 验收标准

- [x] 页面、JSON 和终端输出契约通过，监控的 Git 调用预算和并发请求合并通过。

## 验证方式

通过对应的 unittest 和实际命令验证上述行为，结果见下表。

## 执行结果

- Outcome: passed
- Notes: 看板消费监控契约，Git 默认分支规则共用，认证刷新在失效后不会被旧请求覆盖。普通 CLI 启动只加载本次命令需要的界面。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / f0331b9 | PYTHONPATH=tests python3 -B -m unittest test_monitor_and_board test_preview_ui test_idd_cli.TestIddCli.test_start_creates_worktree_syncs_includes_and_is_idempotent_across_tools | 43 项通过 |
| 2026-11-28 / f0331b9 | 独立进程运行 scripts/idd --version 并检查 sys.modules | 输出 idd 0.0.4，未加载两个界面模块 |
| 2026-11-28 / f0331b9 | OCR 本地规则与 Git 差异复审 | 5 个源文件全部复核，验证缓存失效、Git 调用预算及输出契约 |
