# TASK-01：看板推送与静默更新

- Issue: #83
- Status: done
- Depends on: none
- Test: tests/test_board_events.py、tests/test_monitor_and_board.py

## 任务范围

接通共享采集、HTTP 事件流和网页订阅。区分连接、自动更新与显式同步，复用现有快照和卡片更新逻辑。

## 验收标准

- [x] 首次显示当前快照，多页面共享一个采集循环，业务变化推送、重复采集静默。
- [x] 首次加载、手动操作、暂停、后台标签和断线恢复正确展示且能继续工作。

## 验证方式

- Command: python3 -m unittest discover -s tests -p test_board_events.py，以及现有看板相关测试。
- Expected: HTTP 流、共享采集和前端状态测试通过。

## 执行结果

- Outcome: passed
- Notes: SSE 的订阅者共享采集，网页只在数据或连接状态发生变化时更新。手动同步等待指定仓库的远端查询。

### 验证记录

| 日期 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 | `python3 -m unittest discover -s tests -p test_board_events.py -v` | 4 项通过，覆盖 HTTP 共享推送、重复快照、查询异常与恢复、采集间隔及手动同步失败。 |
| 2026-11-28 | `python3 -m unittest discover -s tests -p test_monitor_and_board.py -v` | 35 项通过，包含真实工作树新增文件后直接从 SSE 收到变更，以及网页加载、卡片增量更新和已有 HTTP 接口。 |
| 2026-11-28 | Chrome 两个窗口连接同一个临时 Git 工作树和模拟远端 | 两个可见页面自动快照 GET 均为 0。CI、TASK 的变化能推送到页面，暂停后恢复追上最新状态。 |
