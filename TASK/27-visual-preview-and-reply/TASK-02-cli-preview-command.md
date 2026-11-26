# TASK-02：接入 `idd preview` CLI 子命令与安装清单测试

- Issue: 27-visual-preview-and-reply
- Status: done
- Depends on: TASK-01
- Test: tests/test_preview_ui.py, tests/test_install_uninstall.py

## 任务范围
- 包含：
  - 在 `scripts/idd_cli.py` 中导入 `preview_ui`、实现 `cmd_preview`，并在 `build_parser()` 注册 `preview` 子命令（`targets`、`--title`、`--compare`、`--host`、`--port`、`--no-open`）。
  - 更新 `tests/test_install_uninstall.py` 的 `SCRIPT_FILES`，加入 `"scripts/preview_ui.py"`。
  - 在 `tests/test_preview_ui.py` 补充 CLI 端到端测试（`idd preview --help`、不存在目标时的非零报错）。
- 不包含：
  - 修改 `SKILL.md`、`references/` 与 `README*.md`。

## 验收标准

- [x] `idd preview --help` 正常输出参数说明并退出 0
- [x] `idd preview` 对不存在的目标返回非零状态与清晰中文提示
- [x] `tests/test_install_uninstall.py` 与 `tests/test_preview_ui.py` 全部通过

## 实现注意事项

- 将 `preview_ui.PreviewError` 统一转为 `IddError` 以便走标准 CLI 错误格式输出。

## 验证方式

- Command: `python3 -m unittest tests/test_preview_ui.py tests/test_install_uninstall.py -v`
- Expected: 两个测试文件全部用例通过。

## 执行结果

- Outcome: passed
- Notes: 已在 `scripts/idd_cli.py` 接入 `idd preview` 子命令并同步安装清单，13 项单测全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 -m unittest tests/test_preview_ui.py tests/test_install_uninstall.py -v` | passed (13/13) | `tests/test_preview_ui.py`, `tests/test_install_uninstall.py` |
