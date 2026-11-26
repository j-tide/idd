# TASK-01：模板配置与策略状态持久化

- Issue: #15
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py, tests/test_gitlab_forge.py

## 任务范围
- 包含：
  - 在 `scripts/forge.py` 新增 `GITLAB_SQUASH_COMMIT_TEMPLATE` 与 `evaluate_repo_init_settings`，扩展 GitHub `repo_init` 读写 `squash_merge_commit_title=PR_TITLE`、`squash_merge_commit_message=PR_BODY`，扩展 GitLab `repo_init` 读写 `squash_commit_template="%{title}\n\n%{description}"`；
  - 在 `scripts/monitor.py` 扩展 `~/.config/idd/repos.json` 持久化 `repo_init_state`（兼容旧值 `"prompted"` 归一化为 `"pending"`）、`repo_init_mismatches` 与 `repo_init_error`；
  - 新增 `get_repo_init_meta` / `set_repo_init_meta`，并在 `ForgeSnapshotCache._query_and_store` 与 `collect_repo_snapshot` 同步/暴露仓库 `repo_init` 状态。
- 不包含：CLI 与 Web UI 交互层修改（分别在 TASK-02 / TASK-03 完成）。

## 验收标准

- [x] GitHub `repo_init(apply=True)` 设置 `squash_merge_commit_title=PR_TITLE`、`squash_merge_commit_message=PR_BODY` 并返回；
- [x] GitLab `repo_init(apply=True)` 设置 `squash_commit_template="%{title}\n\n%{description}"` 并返回；
- [x] `evaluate_repo_init_settings` 识别策略与模板差异，`repos.json` 持久保留 `repo_init_state`、`repo_init_mismatches`、`repo_init_error`，`collect_repo_snapshot` 输出 `repo_init` 字段。

## 实现注意事项

- 严格保持 `get_repo_init_state` / `set_repo_init_state` 向后兼容；
- `load_registered_repos` 和 `register_repo` 触达已有仓库时必须保留既有 `repo_init_*` 元数据。

## 验证方式

- Command: `PYTHONPATH=tests python3 -m unittest test_idd_cli test_gitlab_forge test_monitor_and_board -v`
- Expected: 在 TASK-02 / TASK-03 完成联调及补测后全量通过。

## 执行结果

- Outcome: passed
- Notes: 已在 `scripts/forge.py` 与 `scripts/monitor.py` 实现 GitHub/GitLab Squash 提交模板配置、策略对比函数及 `repos.json` 持久化元数据，并与 `TASK-02` 联调通过 22 项测试。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / base `59dbe23` | `PYTHONPATH=tests python3 -m unittest test_idd_cli test_gitlab_forge -v` | passed (22 tests, 70.158s) | `tests/test_idd_cli.py`、`tests/test_gitlab_forge.py` |
