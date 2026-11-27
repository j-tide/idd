# TASK-02：统一看板前端 API 文档并全量验证

- Issue: 65-global-auto-merge
- Status: done
- Depends on: TASK-01
- Test: `tests/test_monitor_and_board.py`, 全量 `python3 -m unittest discover -s tests -v`

## 任务范围
- `scripts/board_ui.py`：
  - 移除侧栏 `.sb-auto-tag` 样式与仓库行「自动」徽标；
  - 移除设置弹窗单仓库三态分段按钮与 `.am-seg-*` 样式及 glider 同步；
  - 顶栏胶囊统一显示 `PR 自动准入: 开/关` 或 `MR 自动准入: 开/关`（无 `(全局)` / `(仓库)` 括号），点击均触发全局开关确认弹窗；
  - 简化 `openAutoMergeConfirm` / `renderAutoMergeConfirmModal` / `setAutoMergeSetting` 与 `/api/config/auto-merge`（拒绝 `scope: "repo"`，仅支持全局开关）。
- `SKILL.md`、`references/git-issue-workflow.md`、`README.md`、`README.en.md`：更新 `auto_merge` 与 `idd config` 描述为纯全局开关。
- `tests/test_monitor_and_board.py`：更新 API 与前端 JS 渲染测试覆盖全局统一行为。

## 验收标准
- [x] 看板顶栏（全局工作区、GitHub/GitLab 单仓库）均不带 `(全局)` / `(仓库)` 括号且点击切换全局开关
- [x] 侧栏仓库列表不再重复显示「自动」标签，设置弹窗仅保留全局开关
- [x] `/api/config/auto-merge` 拒绝 `scope: "repo"`，支持全局开关读写
- [x] 文档已同步且全量测试与 JS 语法检查通过

## 实现注意事项
- 确认弹窗中仍按当前仓库类型动态展示 `PR` 或 `MR` 标签，但生效范围明确为全局。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全量单元测试及 Node JS 语法与渲染用例通过。

## 执行结果
- Outcome: passed
- Notes: 已移除看板前端与 API 中的仓库级 `auto_merge` 配置及展示，文档已同步更新，全量 93 项单元测试及 Node JS 语法与渲染校验全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `python3 -m unittest discover -s tests -v` | passed (93/93) | `tests/`（含 `test_board_auto_merge_api_and_ui` 与 Node JS 检查） |
