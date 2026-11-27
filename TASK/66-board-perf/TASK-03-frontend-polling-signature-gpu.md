# TASK-03：前端智能轮询、签名缓存修复与 GPU 渲染减负

- Issue: #66
- Status: planned
- Depends on: TASK-02
- Test: tests/test_monitor_and_board.py

## 任务范围

优化 `scripts/board_ui.py` 中 `BOARD_HTML` 的前端轮询、状态 diff 与 CSS 渲染性能：
1. **智能轮询与后台暂停**：将固定 2s `setInterval` 改为串行自适应 `setTimeout`（同步中 `1.2s`、活跃编码/脏工作树 `4s`、常规有工作树 `8s`、静态无工作树 `15s`）；监听 `visibilitychange`，切后台时暂停轮询并给根元素加 `is-tab-hidden` 暂停全部 CSS 动画，切回前台时立即恢复并拉取最新快照。
2. **修复 `computeRenderSignature` 缓存失效**：剥离 `generated_at`、`last_seen_at`、`forge_fetched_at`、以及浮点 `idle_seconds`（保留实际渲染文本 `last_active_ago`/`pulse_summary` 等），使无实质变化时跳过全量 `renderAll` DOM diff、FLIP `getBoundingClientRect` 强制回流以及 `sessionStorage` 写入。
3. **消除 GPU 空转合成开销**：`.top-progress-bar` 仅在 `.top-progress.is-active` 时运行 `topProgressSlide` 动画；`.live-pill.is-live .dot-pulse` 取消常态 24×7 无限 `pulse`（仅加载/同步态运行）；优化双层嵌套 `backdrop-filter`（外层容器保留柔和磨砂玻璃，内层 `.card`/`.bento-card` 改用分层半透明表面与高光边框），完整保留苹果级视觉与既有动效规范。

## 验收标准

- [ ] 前端使用 `visibilitychange` 后台暂停轮询与 CSS 动画，前台按活跃度自适应退避串行调度
- [ ] `computeRenderSignature` 对仅 `generated_at` / `last_seen_at` / `idle_seconds` 变化的快照产出完全一致的签名，避免无意义 DOM diff 与 `sessionStorage` 覆写
- [ ] `.top-progress-bar` 默认不运行动画（仅 `.is-active` 启用），常态绿点无无限 `pulse`，内层 `.card` 不再与外层容器形成双层 `backdrop-filter` 嵌套
- [ ] 通过 Node/Python 测试验证前端 JS 逻辑与 CSS 规则，全量测试套件通过并在本机真实环境完成优化前后性能实测对比

## 实现注意事项

- 严禁破坏 `test_board_motion_tokens_reduced_motion_and_tty_watch_frame`、`test_board_collapsed_sidebar_and_header_pill_layout_css` 等既有测试断言与动效 Token。

## 验证方式

- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全量单元测试通过，且真实环境基准脚本显示后端子进程数与 CPU 占用大幅下降。

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
