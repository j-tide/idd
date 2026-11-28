# TASK-08：平台错误响应的资源释放

- Issue: #81
- Status: done
- Depends on: TASK-04
- Test: tests/test_gitlab_forge.py

## 任务范围

关闭 HTTP 失败响应，保留双平台错误码、错误正文和既有合入重试。

## 验收标准

- [x] GitLab 并发合入测试覆盖的 409 响应完成资源释放，错误语义和重试验证通过。

## 验证方式

在隔离配置、工作树或模拟平台上运行上述真实入口的回归测试。

## 执行结果

- Outcome: passed
- Notes: 身份校验和 GitLab API 的 HTTPError 在退出错误处理前关闭。保留 HTTP 状态、错误正文和可选探测语义。

### 验证记录

| 日期 / 基线 | 命令或操作 | 实际结果 |
| --- | --- | --- |
| 2026-11-28 / 71b530e | PYTHONPATH=tests python3 -B -W always::ResourceWarning -m unittest test_gitlab_forge | 15 项通过，未出现 ResourceWarning |
| 2026-11-28 / 71b530e | OCR 差异与两个 HTTP 边界复审 | 1 个源文件，检查 401 和 409 的响应关闭、状态及错误正文 |
