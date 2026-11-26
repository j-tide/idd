# TASK-02：更新最新看板截图与架构配图并同步主干规则模板

- Issue: #44
- Status: done
- Depends on: TASK-01
- Test: `python3 scripts/release.py --check`、`python3 -m unittest discover -s tests -v`、PNG 尺寸与视觉核对、SVG XML 校验

## 任务范围
- 将分支变基至最新 `origin/main`（含 `#39`、`#40`、`#42`）并在 `README.md` / `README.en.md` 保留 `#39` 的可选默认工作流规则模板
- 基于最新 `scripts/board_ui.py` 重新截取 4 张中英文暗/亮主题看板图（`assets/board-{zh,en}-{dark,light}.png`），展示顶栏 GitHub/GitLab 连接状态、PR 自动准入开关、移除冗余全局标签、动态打开 PR/MR 与打开 Issue 按钮等最新 UI
- 刷新 4 张架构流程图（`assets/workflow-{zh,en}-{dark,light}.svg`）以体现原型对齐（`idd preview`）与可控自动准入能力

## 验收标准

- [x] 变基至最新 `origin/main`，中英文 README 完整保留 `#39` 可选默认工作流规则模板
- [x] 4 张 `assets/board-{zh,en}-{dark,light}.png`（`2760 x 1780`）均体现最新 `board_ui.py` 界面，无骨架屏、弹窗遮挡或文案重叠
- [x] 4 张 `assets/workflow-{zh,en}-{dark,light}.svg` 合法且体现最新流程
- [x] `python3 scripts/release.py --check` 与 `python3 -m unittest discover -s tests -v` 全量通过

## 实现注意事项

- 使用独立临时目录与 Headless Chrome 捕获（2x DPI、`1380x890` → `2760x1780`），不向业务仓库提交临时脚本
- 使用只读视觉子代理核对 4 张新截图的内容、主题与语言一致性

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性校验通过，全部单元测试通过，PNG 尺寸为 `2760 x 1780` 且 SVG XML 合法

## 执行结果

- Outcome: passed
- Notes: 已变基至最新 `origin/main` 并保留 `#39` 规则模板；4 张看板截图已基于最新 `board_ui.py` 重新截取并通过视觉核对，4 张 SVG 流程图已刷新，版本校验与 84 项单元测试全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | Headless Chrome 截图 + `file assets/board-*.png` + 只读视觉核对 | passed（4 张均 `2760 x 1780`，`ALL CLEAN`） | 顶栏连接状态、`PR 自动准入: 关`、动态 `打开 PR/MR` 与 `#115` 接力控制台均正常渲染 |
| 2026-11-26 | `python3 -c 'import xml.etree.ElementTree as ET...'` | passed（4 个 SVG XML 合法、`#39` 模板已保留） | 本地工作树校验输出 `SVGs valid & #39 preserved` |
| 2026-11-26 | `python3 scripts/release.py --check` | passed（`v0.0.3` 一致性校验通过） | `SKILL.md == README.md == README.en.md == idd --version` |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed（84 tests in 182.068s, OK） | 含 `test_repo_version_consistency` 与 `test_monitor_and_board` |
