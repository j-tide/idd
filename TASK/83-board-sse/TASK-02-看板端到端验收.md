# TASK-02：看板端到端验收

- Issue: #83
- Status: planned
- Depends on: TASK-01
- Test: tests/test_board_events.py、tests/test_monitor_and_board.py，以及 Chromium 真实多页面操作。

## 任务范围

用真实浏览器和 Git 工作树验证共享更新、视觉稳定和重连，更新看板用法说明，完成项目回归。

## 验收标准

- [ ] 多页面能看到相同数据，暂停／恢复和断线／重连能追上最新状态，缓存、卡片和连接反馈符合方案。
- [ ] 中英文说明明确 SSE 推送与远端缓存，全量测试及版本检查通过。

## 验证方式

- Command: python3 scripts/release.py --check 和 python3 -m unittest discover -s tests -v。真实浏览器打开两个页面操作。
- Expected: 版本一致、全套测试通过、浏览器场景符合验收标准。

## 执行结果

- Outcome: pending
- Notes: 尚未执行。
