# TASK-01：Forge 层增加 SHA 乐观锁、http_status 透传与 CHECKING 状态解析

- Issue: 10-land-wait-head-sha
- Status: done
- Depends on: none
- Test: python3 -m unittest tests/test_gitlab_forge.py tests/test_idd_cli.py -v

## 任务范围
- 包含：`scripts/forge.py` 中 `ForgeError` / `ForgeAuthError` 透传 `http_status`；`GitLabForge._normalize_mr` 优先解析 `diff_refs.head_sha`、保留 `rawSha` 与 `detailedMergeStatus`，并将 `checking`/`unchecked`/`preparing` 映射为 `CHECKING`；`GitLabForge.merge_squash` 与 `GitHubForge.merge_squash` 支持 `expected_sha` 参数并传递 `sha` / `--match-head-commit`；在 `tests/test_gitlab_forge.py` 中补充对应单元测试。
- 不包含：`scripts/idd_cli.py` 的轮询等待与重试逻辑（由 TASK-02 负责）。

## 验收标准

- [x] `ForgeError` 与 `ForgeAuthError` 支持并透传 `http_status`（`GitLabForge._request` 的 `HTTPError` 路径正确填充）
- [x] `GitLabForge._normalize_mr` 优先取 `diff_refs.head_sha`，保留 `rawSha` 与 `detailedMergeStatus`，并将 `checking`/`unchecked`/`preparing` 识别为 `CHECKING`
- [x] `GitLabForge.merge_squash` 支持 `expected_sha` 并传入 `sha`，`GitHubForge.merge_squash` 支持 `expected_sha` 并传入 `--match-head-commit`
- [x] `tests/test_gitlab_forge.py` 新增对应单测且 `test_gitlab_forge.py` 与 `test_idd_cli.py` 全部通过

## 实现注意事项

- 保留既有调用方不传 `expected_sha` 时的向后兼容性。
- `GitLabForge._normalize_mr` 对 list 接口未返回 `diff_refs` 时回退到 `raw.get("sha")`。

## 验证方式

- Command: `python3 -m unittest tests/test_gitlab_forge.py tests/test_idd_cli.py -v`
- Expected: 所有单元测试通过，无失败或跳过。

## 执行结果

- Outcome: passed
- Notes: 已完成 `scripts/forge.py` 的 `http_status` 透传、`diff_refs.head_sha` / `CHECKING` 态解析以及 `expected_sha` 乐观锁支持，并补充单元测试，15 条定向测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_gitlab_forge.py tests/test_idd_cli.py -v` | passed（15 passed） | `tests/test_gitlab_forge.py`, `scripts/forge.py` |
