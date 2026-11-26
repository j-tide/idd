# TASK-03：看板 Web UI 自动合入开关与配置接口

- Issue: 28-auto-merge-pr-mr-ci
- Status: done
- Depends on: TASK-01
- Test: tests/test_monitor_and_board.py

## 任务范围
- 在 `scripts/board_ui.py` 后端新增 `GET /api/config` 与 `POST /api/config/auto-merge`（带本地 CSRF 校验与仓库白名单校验）。
- 在 `BOARD_HTML` 前端设置弹窗新增全局 `auto_merge` 开关与各远端仓库三态分段控制（跟随全局 / 开 / 关）。
- 在工作区顶栏 `#ws-repo-link-wrap` 新增全局与单仓库快捷切换胶囊按钮，实时反映并切换当前生效状态。
- 更新向导文案并在 `tests/test_monitor_and_board.py` 补充接口安全与前端交互标记/语法校验。

## 验收标准
- [x] `GET /api/config` 与 `POST /api/config/auto-merge` 正确读写全局和仓库级开关，CSRF 缺失或非法路径返回 403/400。
- [x] 设置弹窗与工作区顶栏均能清晰展示并切换全局及仓库级三态开关。
- [x] 前端 `<script>` 通过 `node --check` 语法校验，测试全通过。

## 实现注意事项
- 遵循 `board_ui.py` 现有中英双语（`tr(...)`）与深浅色主题变量规范。

## 验证方式
- Command: `python3 -m unittest discover -s tests -p "test_monitor_and_board.py" -v`
- Expected: 全部测试通过。

## 执行结果
- Outcome: passed
- Notes: 已完成 `/api/config`、`/api/config/auto-merge` 接口与看板设置弹窗/顶栏开关控件开发，安全校验与 JS 语法检查及全量看板测试（18/18）全部通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -p "test_monitor_and_board.py" -v` (含 `node --check` 校验) | passed (18/18) | `tests/test_monitor_and_board.py` |
