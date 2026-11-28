# TASK-08：平台错误响应的资源释放

- Issue: #81
- Status: planned
- Depends on: TASK-04
- Test: tests/test_gitlab_forge.py

## 任务范围

关闭 HTTP 失败响应，保留双平台错误码、错误正文和既有合入重试。

## 验收标准

- [ ] GitLab 并发合入测试覆盖的 409 响应完成资源释放，错误语义和重试验证通过。

## 验证方式

在隔离配置、工作树或模拟平台上运行上述真实入口的回归测试。

## 执行结果

- Outcome: pending

### 验证记录

尚未执行。
