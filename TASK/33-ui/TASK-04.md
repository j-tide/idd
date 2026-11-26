# TASK-04：自动化单测补全、真实浏览器性能/视口实测与 PR 交付

- Issue: 33-ui
- Status: planned
- Depends on: TASK-02, TASK-03
- Test: python3 -m unittest discover -s tests -v

## 任务范围
- 在 `tests/test_monitor_and_board.py` 与 `tests/test_preview_ui.py` 新增动效契约测试（Motion Tokens、禁用 `transition: all`、`prefers-reduced-motion`、核心 JS 函数与拖拽手柄结构验证）。
- 启动临时 `board_ui`（45+ 条目压测快照）与 `preview_ui` 实例，使用真实浏览器实测长列表滚动与动画 FPS、p95 帧耗时、CLS、`console.error`、宽/窄/手机视口、深浅色与 `prefers-reduced-motion`。
- 根据实测结果修补任何问题后，运行全量单测，提交推送并创建 PR（`idd pr`）及跟踪 CI（`idd ci --watch`）。

## 验收标准
- [ ] 新增动效系统与交互契约自动化测试通过
- [ ] 真实浏览器 45+ 条目下平均 FPS >= 55、CLS < 0.05、`console.error` 为 0，宽/窄/手机视口无横向溢出
- [ ] 全量单测 `python3 -m unittest discover -s tests -v` 通过，PR 创建且远端 CI 全绿

## 实现注意事项
- 浏览器测试仅使用临时本地端口与内存/临时目录测试数据，测完立即关闭进程，不污染用户真实 `~/.config/idd` 配置。
- 严禁未经授权执行 `idd land`。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全部单测通过，CI 检查通过。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
