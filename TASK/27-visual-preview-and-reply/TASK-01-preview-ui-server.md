# TASK-01：实现本地原型预览服务端与前端工作台（preview_ui.py）

- Issue: 27-visual-preview-and-reply
- Status: done
- Depends on: none
- Test: tests/test_preview_ui.py

## 任务范围
- 包含：
  - 新增 `scripts/preview_ui.py`（纯 Python 3 标准库，零外部依赖），提供 `PreviewError`、`parse_target_spec`、`PreviewRegistry`、`PreviewRequestHandler`、`run_preview_server`。
  - 支持单个/多个 `.html`/`.htm` 文件（含可选 `标签=路径` 写法）及目录动态扫描；自动提取 HTML `<title>` 作为标签名；默认监听 `127.0.0.1:17891`（端口占用回退 `0`）。
  - 提供 `/api/health`、`/api/meta`、`/raw/<id>`、`/raw/<id>/<relpath>` 路由，严格使用 `is_relative_to` 防护目录穿越与越权符号链接（返回 `403`），处理文件临时缺失与热更新恢复。
  - 提供 `PREVIEW_HTML` 前端工作台（沿用 `board_ui.py` 深浅主题设计语言、实时状态灯、多方案标签页、A/B 并排对比、100%/桌面/平板/手机视口切换、800ms 轮询热更新与友好空态/缺失态）。
  - 新增 `tests/test_preview_ui.py` 验证服务端各接口、热更新信号、目录动态扫描、缺失恢复、越权拦截及内联 JS 语法校验。
- 不包含：
  - 修改 `scripts/idd_cli.py` 与 `tests/test_install_uninstall.py`（留待 `TASK-02`）。

## 验收标准

- [x] `scripts/preview_ui.py` 可独立启动本地预览服务并响应 `/api/health`、`/api/meta`、`/raw/<id>` 与安全受限的同级静态资源请求
- [x] 支持单文件、多文件、`标签=路径`、目录动态新增/删除、热更新信号以及越权路径 `403` 拦截
- [x] `tests/test_preview_ui.py` 全部用例通过

## 实现注意事项

- 参考 `scripts/board_ui.py` 的 `_is_client_disconnect`、`BoardHTTPServer`（允许端口复用并静默处理客户端断开）与主题 CSS 变量风格。
- `parse_target_spec` 仅当 `=` 左侧不含路径分隔符（`/`、`\`）且右侧指向有效目标时解析为自定义标签，避免含 `=` 的路径误判。

## 验证方式

- Command: `python3 -m unittest tests/test_preview_ui.py -v`
- Expected: 全部测试用例通过且无 skipped/relaxed 关键断言。

## 执行结果

- Outcome: passed
- Notes: 已实现 `scripts/preview_ui.py` 与 `tests/test_preview_ui.py`，6 项测试全部无警告通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_preview_ui.py -v` | passed (6/6) | `tests/test_preview_ui.py` |
