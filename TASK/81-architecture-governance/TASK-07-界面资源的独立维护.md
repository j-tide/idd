# TASK-07：界面资源的独立维护

- Issue: #81
- Status: done
- Depends on: TASK-03
- Test: tests/test_monitor_and_board.py, tests/test_preview_ui.py, tests/test_install_uninstall.py

## 任务范围

将页面源文件与 Python 服务端解耦，使前端与采集或工作流改动可独立进行。

## 验收标准

- [x] 两个页面原始 UTF-8 字节相同，安装后的页面可由真实 HTTP 入口加载，构建链与路由延用现有契约。

## 验证方式

在隔离配置、工作树或模拟平台上运行上述真实入口的回归测试。

## 执行结果

- Outcome: passed
- Notes: 看板与预览现在有独立 HTML 源文件，公共 HTTP 服务负责断连处理、响应头和 JSON 写出。两份页面及安装后入口验证通过。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / f7b4341 | PYTHONPATH=tests python3 -B -m unittest test_monitor_and_board test_preview_ui test_install_uninstall | 48 项通过 |
| 2026-11-28 / f7b4341 | 与父提交的 Python 字符串逐字节比较 | 看板 353815 字节，预览 54156 字节完全相同 |
| 2026-11-28 / f7b4341 | OCR 本地规则与 Git 差异复审 | 3 个 Python 源文件和 2 个 HTML 文件全部复核，页面内容无字节差异 |
