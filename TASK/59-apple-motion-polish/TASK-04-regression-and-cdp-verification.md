# TASK-04：全链路契约回归测试与百卡长列表满帧 / 零 CLS / 多视口实测验收

- Issue: 59-apple-motion-polish
- Status: in_progress
- Depends on: TASK-02, TASK-03
- Test: `tests/test_monitor_and_board.py`、`tests/test_preview_ui.py` 与 Headless Chrome CDP 实测脚本

## 任务范围
- 在 `tests/test_monitor_and_board.py` 与 `tests/test_preview_ui.py` 补齐动效 Token、零 `transition: all`、减少动态效果、本地化步骤徽章、预览状态机及 `watch` 无清屏刷新的自动化回归测试
- 使用会话临时目录内的 Chrome CDP 脚本对 120 张卡片长列表轮询、复制宽度锁定、跟手拖拽、可打断视口缩放、手机(`390x844`)/窄窗(`720x800`)/宽屏(`1440x900`) × 深浅色 × 减少动态效果矩阵进行真实浏览器实测并记录实测数据
- 运行 `python3 scripts/release.py --check` 与全量 `unittest` 套件完成终验

## 验收标准
- [ ] 所有新增与既有自动化单元测试全部通过
- [ ] Chrome CDP 实测百卡轮询节点复用率 100%、rAF P95 < 16.7ms、CLS = 0、拖拽跟踪零滞后、全视口无横向溢出且控制台 0 报错
- [ ] `python3 scripts/release.py --check` 与全量 `unittest` 通过，工作区干净（无 `TASK/.../evidence/` 残留）

## 实现注意事项
- 临时 CDP 评测脚本放在系统 scratch 目录，不写入项目仓库 `TASK/.../evidence/`

## 验证方式
- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本校验通过，全量测试全部 OK

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
