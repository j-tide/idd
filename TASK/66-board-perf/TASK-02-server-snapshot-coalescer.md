# TASK-02：看板服务端短 TTL 快照缓存与并发 singleflight 合并

- Issue: #66
- Status: in_progress
- Depends on: TASK-01
- Test: tests/test_monitor_and_board.py

## 任务范围

在 `scripts/board_ui.py` 的服务端层新增线程安全的 `_SnapshotCoalescer`（短 TTL 缓存 + in-flight singleflight 合并），接入 `run_board_server` 与 `BoardRequestHandler`：
1. `GET /api/snapshot` 在短 TTL（默认 `1.5s`）内直接返回已序列化字节/字典，并发到达的多个请求合并为单次 `collect_scope_snapshot` 调用。
2. `GET /api/snapshot?refresh=1` 及所有写接口（`/api/auth/save`、`/api/auth/logout`、`/api/repo/init`、`/api/config/auto-merge`）立即 `invalidate()` 穿透缓存。
3. 保持 `BoardRequestHandler` 构造签名向后兼容（`snapshot_cache` 为可选参数）。

## 验收标准

- [ ] 短时间内并发或多个标签页请求 `GET /api/snapshot` 只触发一次 `collect_scope_snapshot`
- [ ] `GET /api/snapshot?refresh=1` 与任一配置/鉴权/初始化 POST 写操作后，下次 `/api/snapshot` 立即获取最新数据
- [ ] 单元测试覆盖并发合并、TTL 过期、手动穿透与写接口失效

## 实现注意事项

- 复用 JSON 字节缓存时注意确保异常不会被缓存，且 `invalidate()` 推进 epoch 防止并发中的旧采样回写覆盖新状态。

## 验证方式

- Command: `python3 -m unittest tests/test_monitor_and_board.py -v`
- Expected: 新增与既有看板服务端测试全部通过。

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
