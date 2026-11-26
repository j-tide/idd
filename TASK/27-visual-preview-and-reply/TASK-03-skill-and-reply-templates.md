# TASK-03：升级 IDD 直观对齐流程规范与极简交付状态模板

- Issue: 27-visual-preview-and-reply
- Status: done
- Depends on: TASK-02
- Test: python3 scripts/release.py --check

## 任务范围
- 包含：
  - 新建 `references/visual-alignment.md`，定义 4 类改动的直观预览标准、Claude Code / Codex / Antigravity 三端落地方式、必查边界态清单、定稿沉淀规则与薄切片早验收原则。
  - 升级 `SKILL.md`：速查表新增 `idd preview`，收紧模式 A / B 的直接开干门槛，在模式 C 加入 UI/交互任务的薄切片早验收约定。
  - 升级 `references/final-reply.md`：将「交付状态」替换为候选 A 极简状态表（`环节 | 对象 | 状态`），并同步更新受阻示例。
- 不包含：
  - `README.md` 与 `README.en.md`（留待 `TASK-04`），不更改 `metadata.version`。

## 验收标准

- [x] `references/visual-alignment.md` 结构完整、简明实用，覆盖 4 类改动分级与三端呈现
- [x] `SKILL.md` 与 `references/` 内部相对链接有效，模式 A / B / C 与速查表准确更新
- [x] `references/final-reply.md` 使用候选 A 极简状态表覆盖已合入、PR/MR 待验收、纯本地与受阻场景

## 实现注意事项

- 保持流程轻量，不引入重型文档要求；注意 `SKILL.md` 中的 `metadata.version` 保持不变。

## 验证方式

- Command: `python3 scripts/release.py --check` 与链接/结构校验命令
- Expected: 版本一致性校验通过且所有相对链接目标文件存在。

## 执行结果

- Outcome: passed
- Notes: 已完成 `SKILL.md`、`references/visual-alignment.md` 与 `references/final-reply.md` 升级，版本一致性及 5 份 Markdown 相对链接校验通过。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 scripts/release.py --check` & Markdown 相对链接校验 | passed (v0.0.3, 5 files valid) | `SKILL.md`, `references/visual-alignment.md`, `references/final-reply.md` |
