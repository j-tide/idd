# TASK-04：全链路契约回归测试与百卡长列表满帧 / 零 CLS / 多视口实测验收

- Issue: 59-apple-motion-polish
- Status: done
- Depends on: TASK-02, TASK-03
- Test: `tests/test_monitor_and_board.py`、`tests/test_preview_ui.py` 与 Headless Chrome CDP 实测脚本

## 任务范围
- 在 `tests/test_monitor_and_board.py` 与 `tests/test_preview_ui.py` 补齐动效 Token、零 `transition: all`、减少动态效果、本地化步骤徽章、预览状态机及 `watch` 无清屏刷新的自动化回归测试
- 使用会话临时目录内的 Chrome CDP 脚本对 120 张卡片长列表轮询、复制宽度锁定、跟手拖拽、可打断视口缩放、手机(`390x844`)/窄窗(`720x800`)/宽屏(`1440x900`) × 深浅色 × 减少动态效果矩阵进行真实浏览器实测并记录实测数据
- 运行 `python3 scripts/release.py --check` 与全量 `unittest` 套件完成终验

## 验收标准
- [x] 所有新增与既有自动化单元测试全部通过
- [x] Chrome CDP 实测百卡轮询节点复用率 100%、满帧无掉帧与长任务（139 帧 `rAF P95 = 16.8ms`、`longTasks = []`）、CLS = 0、拖拽跟踪零滞后、全视口无横向溢出且控制台 0 报错
- [x] `python3 scripts/release.py --check` 与全量 `unittest` 通过，工作区干净（无 `TASK/.../evidence/` 残留）

## 实现注意事项
- 临时 CDP 评测脚本放在系统 scratch 目录，不写入项目仓库 `TASK/.../evidence/`

## 验证方式
- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本校验通过，全量测试全部 OK

## 执行结果
- Outcome: passed
- Notes: 已补齐 `test_board_motion_tokens_reduced_motion_and_tty_watch_frame` 与 `test_preview_motion_tokens_direct_manipulation_and_state_contracts`，并在 Chrome CDP 下实测消除 `#toast-wrap` 高度动画引起的 CLS 与轮询卡顿，完成全量 91 项单元测试与 `release.py --check`。

### 当前阻塞

无。

### 验证记录

- Chrome CDP 实测（120 张看板卡片 + `preview_ui` 交互，临时脚本位于会话 scratch 目录 `measure_motion.mjs`）：
  - `board_120_cards`: `preserved: 120/120`, `scrollBefore: 120 -> scrollAfter: 120`, `winScrollBefore: 260 -> winScrollAfter: 260`, `hasSelection: true`, `cls: 0`, `longTasks: []`, `p95: 16.8ms` (`139` frames)
  - `copy_width_delta_px: 0`, `reduced_motion_sample_dur: "1e-05s"`
  - `board_matrix`: `mobile/dark`, `mobile/light`, `narrow/dark`, `narrow/light`, `wide/dark`, `wide/light` 全部 `overflow=0`
  - `preview_compare_iframe_preserved: true`, `preview_drag_check`: `dragging=true`, `iframePE="none"`, `paneTr="0s"`, `leftRightEdge=893.015625`
  - `preview_grace_check`: `hasIframe=true`, `hasOverlay=true`, `statusText="文件写入中…"`；恢复后覆盖层正常退出
  - `preview_interruptible_resize`: `midWidth=589.0625 -> finalWidth=768`
  - `preview_matrix`: `mobile/dark`, `mobile/light`, `narrow/dark`, `narrow/light`, `wide/dark`, `wide/light` 全部 `ok`；`console_errors: 0`
- 发布与全量单测：
  - `python3 scripts/release.py --check` -> `版本一致性校验通过：v0.0.4 (SKILL.md == README.md == README.en.md == idd --version)`
  - `python3 -m unittest discover -s tests -v` -> `Ran 91 tests in 230.074s, OK`
