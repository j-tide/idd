# TASK-01：在 README.md 与 README.en.md 补充可选默认工作流规则模板

- Issue: #39
- Status: done
- Depends on: none
- Test: `python3 scripts/release.py --check && python3 -m unittest tests.test_version_and_release -v`

## 任务范围
- 在 `README.md` 的「快速开始」区下方新增「可选：将 IDD 设为默认工作流」折叠节。
- 在 `README.en.md` 的「Quick Start」区下方新增对应的英文「Optional: Set IDD as Your Default Workflow」折叠节。
- 明确区分个人全局默认（`~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`、Antigravity 全局用户规则）与项目级强制（仓库 `AGENTS.md` / `CLAUDE.md` `@AGENTS.md` + `idd repo-init --apply`），强调安装脚本零自动写入。
- 不修改版本号、`SKILL.md` 与任何徽章链接。

## 验收标准

- [x] `README.md` 新增中文可选规则模板折叠节，覆盖方式一（个人全局默认）与方式二（项目级强制）。
- [x] `README.en.md` 新增与中文版对齐的英文可选规则模板折叠节。
- [x] `python3 scripts/release.py --check` 与 `tests/test_version_and_release.py` 全部通过。

## 实现注意事项

- 保持现有版本徽章、语言切换链接和资源图片路径完整不被修改。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest tests.test_version_and_release -v`
- Expected: 退出码 0，版本与文档结构检查全部通过。

## 执行结果

- Outcome: passed
- Notes: 已在 `README.md` 与 `README.en.md` 快速开始区新增中英文可选默认工作流规则模板折叠节，版本检查与 `tests.test_version_and_release` 全部通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 (`0c674a0`) | `python3 scripts/release.py --check && python3 -m unittest tests.test_version_and_release -v` | passed (Ran 5 tests in 3.774s, OK) | `README.md`, `README.en.md` |
