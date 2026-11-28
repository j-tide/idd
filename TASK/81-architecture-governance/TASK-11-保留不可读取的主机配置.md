# TASK-11：保留不可读取的主机配置

- Issue: #81
- Status: done
- Depends on: TASK-06
- Test: tests/test_local_state.py, tests/test_monitor_and_board.py

## 任务范围与验收标准

- [x] 状态查询继续提供宽容读取。保存和移除主机时，读取失败及非法 JSON 保留原始文件并返回明确错误。

## 执行结果

- Outcome: passed
- Notes: 查询仍可在缺失或损坏配置时读取空状态。更新遇到原文件读取或格式错误会报告错误并保留原始字节，CLI 和看板分别通过真实入口验证。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 48b1535 | PYTHONPATH=tests python3 -B -m unittest test_local_state test_monitor_and_board.TestMonitorAndBoard.test_board_in_browser_token_save_status_logout_and_repo_links test_gitlab_forge.TestGitLabForge.test_self_hosted_gitlab_end_to_end_workflow | 5 项通过 |
| 2026-11-28 / 48b1535 | 独立复审问题与差异复核 | 验证缺少权限、非法 UTF-8、损坏 JSON 和非对象格式，不会回写空配置 |
