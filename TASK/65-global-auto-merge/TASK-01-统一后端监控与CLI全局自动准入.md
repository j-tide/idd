# TASK-01：统一后端监控与 CLI 全局自动准入

- Issue: 65-global-auto-merge
- Status: done
- Depends on: none
- Test: `tests/test_idd_cli.py`, `tests/test_gitlab_forge.py`

## 任务范围
- `scripts/monitor.py`：移除仓库级 `auto_merge` 覆盖读写（`get_repo_auto_merge_override`、`set_repo_auto_merge_override`）及 `_copy_repo_init_fields` 中对 `auto_merge` 的复制，使历史 `repos.json` 残留字段在写回时自动清理；简化 `resolve_auto_merge` 始终返回全局配置。
- `scripts/idd_cli.py`：移除 `--repo` 与 `inherit`/`unset`/`default`/`reset` 逻辑，简化 `idd config` / `idd repos list` / `idd status` / `idd pr` 的自动准入展示与来源判断（保留 `-g/--global` 兼容参数），单仓库状态不加 `(全局)` / `(仓库)` 括号。
- `tests/test_idd_cli.py`、`tests/test_gitlab_forge.py`：更新并补充纯全局开关与旧 `repos.json` 兼容性测试。

## 验收标准
- [x] 不再存在仓库级 `auto_merge` 读写接口，`resolve_auto_merge` 始终返回全局状态
- [x] `idd config auto-merge on/off/status` 在任意目录直接操作全局开关并兼容 `-g/--global`，拒绝 `inherit`
- [x] `idd status` 单仓库视图不再输出 `(全局)` / `(仓库)` 括号，`idd repos list` 不再输出 `[auto-merge: ...]`
- [x] `tests/test_idd_cli.py` 与 `tests/test_gitlab_forge.py` 全部通过

## 实现注意事项
- 保留 `resolve_auto_merge(main_worktree: Path | None = None)` 的可选参数签名与 `idd config auto-merge -g/--global` 参数，确保既有调用方与脚本向后兼容。

## 验证方式
- Command: `python3 -m unittest tests/test_idd_cli.py tests/test_gitlab_forge.py -v`
- Expected: 全部测试用例通过。

## 执行结果
- Outcome: passed
- Notes: 已移除 `monitor.py` 与 `idd_cli.py` 中的仓库级 `auto_merge` 覆盖逻辑及状态括号后缀，CLI 与 GitLab 集成测试全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest tests/test_gitlab_forge.py -v` | passed (11/11) | `tests/test_gitlab_forge.py` |
| 2026-11-27 | `python3 -m unittest tests/test_idd_cli.py -v` | passed (25/25) | `tests/test_idd_cli.py` |
