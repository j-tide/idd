# TASK-02：在 install.sh 补充零侵入安装指引并完善单元测试

- Issue: #39
- Status: done
- Depends on: TASK-01
- Test: `sh -n install.sh && python3 -m unittest tests.test_install_uninstall -v`

## 任务范围
- 在 `install.sh` 安装完成输出末尾增加 1 行零侵入提示，说明未修改任何 `AGENTS.md` / 全局规则，并引导查看 README 可选模板。
- 在 `tests/test_install_uninstall.py` 中断言安装输出包含零侵入指引，且全新安装不会在临时 `HOME` 创建 `~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md` 或 `~/.gemini/GEMINI.md`。
- 不在 `install.sh` 或 CLI 中自动写入任何规则文件。

## 验收标准

- [x] `install.sh` 末尾增加 1 行 POSIX `sh` 兼容的零侵入提示。
- [x] `tests/test_install_uninstall.py` 覆盖输出提示及零规则文件创建断言。
- [x] `sh -n install.sh && python3 -m unittest tests.test_install_uninstall -v` 全部通过。

## 实现注意事项

- 保持 `install.sh` 严格 POSIX `sh` 语法，复用已有 `$C_CYAN` / `$C_DIM` / `$C_RESET` 颜色变量。

## 验证方式

- Command: `sh -n install.sh && python3 -m unittest tests.test_install_uninstall -v`
- Expected: 退出码 0，所有安装与卸载测试通过。

## 执行结果

- Outcome: passed
- Notes: 已在 `install.sh` 安装完成输出追加零侵入提示，并在 `tests/test_install_uninstall.py` 增加输出指引与零规则文件创建断言，POSIX `sh` 语法及 6 项单测全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 (`89ee051`) | `sh -n install.sh && python3 -m unittest tests.test_install_uninstall -v` | passed (Ran 6 tests in 9.737s, OK) | `install.sh`, `tests/test_install_uninstall.py` |
