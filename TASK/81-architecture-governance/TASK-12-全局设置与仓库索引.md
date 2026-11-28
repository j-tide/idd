# TASK-12：全局设置与仓库索引所有权

- Issue: #81
- Status: done
- Depends on: TASK-03, TASK-06, TASK-11
- Test: tests/test_local_state.py, tests/test_monitor_and_board.py, tests/test_idd_cli.py

## 任务范围与验收标准

- [x] 全局设置和仓库注册表拥有明确的持久化入口，CLI、监控和看板迁移到各自所有者。旧仓库列表可读取，并发注册不丢失。不可读的持久文件在查询和后续自动注册中保留原始字节。

## 执行结果

- Outcome: passed
- Notes: 全局开关由 local_state 读写，仓库列表和初始化元数据由 repo_registry 维护。查询、自动登记和显式管理保留各自的错误处理，当前和旧格式均已验证。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / eaf1791 | PYTHONPATH=tests python3 -B -m unittest test_local_state test_monitor_and_board test_idd_cli.TestIddCli.test_config_auto_merge_global_only_and_persistence test_idd_cli.TestIddCli.test_first_time_repo_init_hint_prompts_once_and_marks_aligned test_gitlab_forge.TestGitLabForge.test_gitlab_first_time_repo_init_hint_prompts_once_and_aligns | 42 项通过 |
| 2026-11-28 / eaf1791 | OCR 本地规则与 Git 差异复审 | 6 个源文件全部复核，旧顶层列表、并发登记、不可读状态和全局设置均有行为验证 |
