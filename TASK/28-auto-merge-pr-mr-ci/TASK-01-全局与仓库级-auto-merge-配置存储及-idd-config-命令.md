# TASK-01：全局与仓库级 auto-merge 配置存储及 idd config 命令

- Issue: 28-auto-merge-pr-mr-ci
- Status: done
- Depends on: none
- Test: tests/test_idd_cli.py, tests/test_monitor_and_board.py

## 任务范围
- 在 `scripts/monitor.py` 实现全局配置 `~/.config/idd/config.json`（默认 `{"auto_merge": false}`）和仓库级 `~/.config/idd/repos.json` 可选 `auto_merge` 布尔覆盖字段读写及优先级解析 `resolve_auto_merge`。
- 确保 `load_registered_repos`、`register_repo`、`set_repo_init_meta` 在重写 `repos.json` 时保留仓库级 `auto_merge` 字段不丢失。
- 在 `collect_repo_snapshot` / `collect_global_snapshot` / `collect_scope_snapshot` 快照中透出 `auto_merge` 与 `config` 字段。
- 在 `scripts/idd_cli.py` 新增 `idd config` 子命令（支持 `show`、`auto-merge [on|off|inherit|status]`、`[-g|--global]`、`[--repo]`、`[--json]`），并在 `idd repos list` 与 `idd status` 中展示开启状态。

## 验收标准
- [x] 默认 `auto_merge` 为关闭；支持全局设置及仓库级 `on`/`off`/`inherit` 覆盖，仓库级优先于全局。
- [x] `repos.json` 任意刷新或更新 `repo_init` 状态时不丢失仓库级 `auto_merge` 字段。
- [x] `idd config` 支持人类可读输出与 `--json` 输出；非 Git 仓库且未传 `-g`/`--repo` 时给出明确错误提示。
- [x] 对应单元测试通过。

## 实现注意事项
- 使用独立 `_CONFIG_LOCK` 与原子临时文件替换写入 `config.json`。
- 兼容现有 `repos.json` 格式与 `_copy_repo_init_fields` 调用方。

## 验证方式
- Command: `python3 -m unittest tests/test_idd_cli.py -k test_config_auto_merge -v && python3 -m unittest discover -s tests -p "test_monitor_and_board.py" -v`
- Expected: 全部新增及现有测试通过。

## 执行结果
- Outcome: passed
- Notes: 已完成全局 `config.json` 与仓库级 `repos.json` `auto_merge` 覆盖存储、快照透出以及 `idd config` 子命令实现，定向单测全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_idd_cli.py -k test_config_auto_merge -v` | passed (1/1) | `tests/test_idd_cli.py` |
| 2026-11-26 | `python3 -m unittest discover -s tests -p "test_monitor_and_board.py" -v` | passed (17/17) | `tests/test_monitor_and_board.py` |
