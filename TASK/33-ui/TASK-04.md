# TASK-04：自动化单测补全、真实浏览器性能/视口实测与 PR 交付

- Issue: 33-ui
- Status: done
- Depends on: TASK-02, TASK-03
- Test: python3 -m unittest discover -s tests -v

## 任务范围
- 在 `tests/test_monitor_and_board.py` 与 `tests/test_preview_ui.py` 新增动效契约测试（Motion Tokens、禁用 `transition: all`、`prefers-reduced-motion`、核心 JS 函数与拖拽手柄结构验证）。
- 启动临时 `board_ui`（45+ 条目压测快照）与 `preview_ui` 实例，使用真实浏览器实测长列表滚动与动画 FPS、p95 帧耗时、CLS、`console.error`、宽/窄/手机视口、深浅色与 `prefers-reduced-motion`。
- 根据实测结果修补任何问题后，运行全量单测，提交推送并创建 PR（`idd pr`）及跟踪 CI（`idd ci --watch`）。

## 验收标准
- [x] 新增动效系统与交互契约自动化测试通过
- [x] 真实浏览器 45+ 条目下平均 FPS >= 55、CLS < 0.05、`console.error` 为 0，宽/窄/手机视口无横向溢出
- [x] 全量单测 `python3 -m unittest discover -s tests -v` 通过，PR 创建且远端 CI 全绿

## 实现注意事项
- 浏览器测试仅使用临时本地端口与内存/临时目录测试数据，测完立即关闭进程，不污染用户真实 `~/.config/idd` 配置。
- 严禁未经授权执行 `idd land`。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v`
- Expected: 全部单测通过，CI 检查通过。

## 执行结果
- Outcome: passed
- Notes: 已在 `tests/test_monitor_and_board.py` 与 `tests/test_preview_ui.py` 补全动效契约与 token 一致性单测；并通过内建 WebView 与无头 Chrome CDP 在 48 条目压测快照下完成帧率、CLS、拖拽跟手、宽/窄/手机深浅色视口与 `prefers-reduced-motion` 实测，同步修复了实测暴露的 1015px 驾驶舱头部挤压、Ledger 表格超宽、预览工作台双栏选择器换行与 favicon 404 噪声。

### 当前阻塞
无。

### 验证记录
- `PYTHONPATH=tests python3 -m unittest tests/test_monitor_and_board.py tests/test_preview_ui.py -v` -> passed (`Ran 27 tests in 42.037s | OK`)
- Chrome Headless CDP 实测（48 条目看板 `board_ui` + 双栏预览 `preview_ui`）：
  - `board_ui`：6 个交互阶段平均 FPS **59.9**（idle 60.0 / cockpit_clicks 58.8 / view_switches 60.0 / list_scroll 60.3 / drawer_open_close 60.1 / modal_popover_theme_banner 60.1），最差 p95 **16.8ms**，**CLS 0**，`consoleErrors: []`；1015px 驾驶舱无重叠（`overlap: false`），1440px 总表无溢出（`tableWidth: 1154 <= wrapWidth: 1156`），抽屉拖拽（460→549）与双击复位生效；1440x900 / 820x800 / 390x844 深浅色均无横向溢出；`prefers-reduced-motion: reduce` 生效（`transitionDuration: 1e-05s`）。
  - `preview_ui`：平均 FPS **59.8**（tab_and_viewports 60.0 / compare_reload_theme 59.5），p95 **16.7ms**，**CLS 0**，`consoleErrors: []`；A/B 拖拽期间 `iframe` 计算属性 `pointer-events: none`、双栏拖拽（699→539）与双击复位生效；双栏选择器/链接全尺寸单行（27px）；1440x900 / 820x800 / 390x844 深浅色均无横向溢出，移动端上下叠放；`prefers-reduced-motion: reduce` 生效（`1e-05s`）。
- `python3 -m unittest discover -s tests -v` -> passed (`Ran 84 tests in 159.412s | OK`)
