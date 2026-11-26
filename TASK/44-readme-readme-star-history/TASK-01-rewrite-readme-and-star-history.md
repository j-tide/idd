# TASK-01：参考热门开源项目重写中英文 README 并挂上 Star History 增长曲线

- Issue: #44
- Status: done
- Depends on: none
- Test: `tests/test_version_and_release.py`、`python3 scripts/release.py --check`、`python3 -m unittest discover -s tests -v` 及链接/锚点检查

## 任务范围
- 重写 `README.md` 与 `README.en.md` 的信息架构、视觉层次与双语同步内容（Hero 居中头图与快捷导航、为什么选择 IDD 对比表、核心特性矩阵、工作原理与目录示意、快速开始、支持生态、折叠 CLI 速查、开发测试发版、Star History 增长曲线）
- 保持 `scripts/version.py` 与 `tests/test_version_and_release.py` 所需的版本徽章正则、语言切换链接及暗/亮主题资源路径不变量
- 不修改代码逻辑、`SKILL.md` 及其他参考文档

## 验收标准

- [x] `README.md` 与 `README.en.md` 采用现代热门开源项目结构，层次清晰、亮暗主题自适应
- [x] 挂载自适应暗/亮主题的 `j-tide/idd` Star History 增长曲线
- [x] `python3 scripts/release.py --check` 与 `python3 -m unittest discover -s tests -v` 全量通过
- [x] 保持与 `SKILL.md` 及现有功能（`idd board` / `idd preview` / `auto-merge` / 双平台支持）事实一致

## 实现注意事项

- 保留精确版本徽章：`[![Version](https://img.shields.io/badge/version-v0.0.3-10b981?style=flat-square)](https://github.com/j-tide/idd/releases)`
- 保留精确语言切换标识：`**简体中文** · [English](README.en.md)` 与 `[简体中文](README.md) · **English**`
- 保留暗/亮主题资源路径：`assets/board-{zh,en}-{dark,light}.png`、`assets/workflow-{zh,en}-{dark,light}.svg`
- 挂载 Star History SVG（`https://api.star-history.com/svg?repos=j-tide/idd&type=Date&theme=dark` 与浅色版）

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性校验通过，全部单元测试通过，所有资源路径与页内锚点有效

## 执行结果

- Outcome: passed
- Notes: 已完成 `README.md` 与 `README.en.md` 重写及 Star History 曲线接入，版本校验、全量 82 项单元测试与资源/锚点校验均通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `curl -sI "https://api.star-history.com/svg?repos=j-tide/idd&type=Date"` | passed（HTTP/2 200，`image/svg+xml`） | Star History SVG 端点可用 |
| 2026-11-26 | `python3 scripts/release.py --check` | passed（`v0.0.3` 一致性校验通过） | `SKILL.md == README.md == README.en.md == idd --version` |
| 2026-11-26 | `python3 -m unittest discover -s tests -v` | passed（82 tests in 163.000s, OK） | 含 `TestVersionAndRelease.test_repo_version_consistency` |
| 2026-11-26 | Python 脚本校验资源引用与页内锚点 | passed（`README.md` 与 `README.en.md` 各 6 个资源文件存在、10 个锚点全部有效） | 本地工作树脚本输出 |
