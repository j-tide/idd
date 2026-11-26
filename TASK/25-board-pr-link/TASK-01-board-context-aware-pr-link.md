# TASK-01：看板主跳转按钮按阶段动态切换打开 PR/MR 与打开 Issue

- Issue: 25-board-pr-link
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 在 `scripts/board_ui.py` 中新增 `resolvePrimaryLink(item)` 与 `renderPrimaryLinkBtn(item, extraCls, opts)`，替换 `renderOpenIssueBtn` 及所有 5 处外部跳转按钮调用点（`renderCockpitConsole`、`renderWtRow`、`renderCard`、`renderListTable`、`renderInspector`）。
- 有有效关联 PR/MR（`item.change.url` 或 `_kind === "orphan"` 的 `item.url`）时，按钮切换为「打开 PR」/「Open PR」（GitLab 为「打开 MR」/「Open MR」）并指向对应 PR/MR URL。
- 尚未创建 PR/MR 或 PR/MR URL 无效/不安全时，回退为「打开 Issue」/「Open Issue」；`renderIdHtml` 的 `#<issue_number>` 徽标继续保留跳转至 Issue。
- 在 `tests/test_monitor_and_board.py` 中补充节点 JS 行为测试与 HTML 断言（覆盖中英文、GitHub/GitLab、孤立 PR/MR、不安全 URL 回退、本地任务、自定义 `iconSize`/`stopOpen`）。

## 验收标准

- [x] 有有效 `item.change.url` 或孤立 PR/MR 时，看板各处（总览行、卡片、列表行、接力控制台、任务详情抽屉）主按钮均显示「打开 PR」/「Open PR」（GitLab 为「打开 MR」/「Open MR」）并指向对应 PR/MR URL。
- [x] 尚无关联 PR/MR 时主按钮保持「打开 Issue」/「Open Issue」，且 `#<id>` 徽标始终可点击打开 Issue。
- [x] 补齐单元测试覆盖中英文与 GitHub/GitLab/孤立 PR/MR/异常 URL 回退场景，全量测试与版本检查通过。

## 实现注意事项

- `monitor.py` 的 `_build_status_row` 未在 `_kind === "issue"` 行上填充 `item.mr_label`，需用 `(item && item.mr_label) || (item && item.forge_type === "gitlab" ? "MR" : "PR")` 兜底。
- 保留 `tr("打开 Issue", "Open Issue")` 字面量调用，维持现有中英文切换与 HTML 断言兼容。
- 保持 `renderIdHtml(item)` 不变。

## 验证方式

- Command: `python3 -m unittest tests.test_monitor_and_board -v` 和 `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本检查退出码为 0，所有测试全部通过且无 `node --check` 语法错误。

## 执行结果

- Outcome: passed
- Notes: 已将看板 5 处主跳转按钮统一为 `resolvePrimaryLink` + `renderPrimaryLinkBtn`，并补充 Node JS 行为单测与 HTML 断言；局部与全量测试套件及版本一致性校验全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 / `feat/25-board-pr-link` | `python3 -m unittest discover -s tests -p test_monitor_and_board.py -v` | passed（17/17，含 `node --check` 与 `test_board_primary_link_switches_to_pr_or_mr_when_change_exists`） | `tests/test_monitor_and_board.py` |
| 2026-11-26 / `feat/25-board-pr-link` | `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v` | passed（版本一致性 `v0.0.3`；70/70 全量测试通过） | `scripts/release.py`、`tests/` |
