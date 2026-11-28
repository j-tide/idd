# TASK-07：界面资源的独立维护

- Issue: #81
- Status: planned
- Depends on: TASK-03
- Test: tests/test_monitor_and_board.py, tests/test_preview_ui.py, tests/test_install_uninstall.py

## 任务范围

将页面源文件与 Python 服务端解耦，使前端与采集或工作流改动可独立进行。

## 验收标准

- [ ] 两个页面原始 UTF-8 字节相同，安装后的页面可由真实 HTTP 入口加载，构建链与路由延用现有契约。

## 验证方式

在隔离配置、工作树或模拟平台上运行上述真实入口的回归测试。

## 执行结果

- Outcome: pending

### 验证记录

尚未执行。
