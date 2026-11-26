# TASK-01：优化看板顶栏 PR 自动准入文案、移除冗余全局标签并增加切换警示弹窗

- Issue: 34-board-pr
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围
- 隐藏全局工作区与初始化状态冗余的 `#scope-tag`（「全局」/「初始化」）标签。
- 将看板顶栏胶囊、设置弹窗卡片及提示文案统一为「PR 自动准入」（单 GitLab 仓库为「MR 自动准入」）。
- 为顶栏胶囊、设置弹窗全局开关及仓库三态按钮增加警示确认弹窗，说明变更范围、操作与影响及安全暂停兜底，仅二次确认后保存。
- 在 `tests/test_monitor_and_board.py` 补充前端渲染、弹窗逻辑与 `node --check` 校验。

## 验收标准
- [x] 全局工作区顶栏不再显示冗余「全局」标签，初始化态不显示冗余「初始化」标签。
- [x] 顶栏与设置弹窗文案更新为「PR 自动准入」（单 GitLab 仓库为「MR 自动准入」）。
- [x] 点击顶栏胶囊、设置弹窗全局开关或单仓库三态按钮均先弹警示确认窗，取消不提交修改，确认后保存。
- [x] `tests/test_monitor_and_board.py` 与全量单元测试通过。

## 实现注意事项
- 确认弹窗需支持点击遮罩与 `Esc` 取消，且优先级高于 `#setup-modal`。

## 验证方式
- Command: `python3 -m unittest discover -s tests -p "test_monitor_and_board.py" -v && python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全部测试与版本检查通过。

## 执行结果
- Outcome: passed
- Notes: 已移除全局工作区/初始化态冗余 `#scope-tag`，将顶栏与设置弹窗文案统一为「PR 自动准入」（GitLab 仓库为「MR 自动准入」），并为全部切换入口接入警示确认弹窗；全量 82 项单测与版本检查通过。

### 当前阻塞
无。

### 验证记录
| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest discover -s tests -p "test_monitor_and_board.py" -v` (含 `node --check` 与 JS 渲染/弹窗单元测试) | passed (18/18) | `tests/test_monitor_and_board.py` |
| 2026-11-26 | `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check` | passed (82/82 + `v0.0.3` 一致性通过) | `tests/`, `scripts/release.py` |
