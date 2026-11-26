# TASK-04：同步中英文 README 并执行全量回归验证

- Issue: 27-visual-preview-and-reply
- Status: done
- Depends on: TASK-03
- Test: python3 -m unittest discover -s tests -v

## 任务范围
- 包含：
  - 更新 `README.md` 与 `README.en.md`，在常用命令表补充 `idd preview` 说明，并在日常用法第 1 步简短补充先看样对齐的说明（不修改版本徽章）。
  - 执行 `python3 scripts/release.py --check` 与全量单元测试 `python3 -m unittest discover -s tests -v`。
- 不包含：
  - 发版打 Tag 或执行 `idd land`。

## 验收标准

- [x] `README.md` 与 `README.en.md` 已同步补充 `idd preview` 与直观对齐说明，版本徽章未改动
- [x] `python3 scripts/release.py --check` 与全量 `unittest` 全部通过

## 实现注意事项

- 严格按照 `.github/workflows/ci.yml` 的检查命令复验。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 全部检查与测试通过。

## 执行结果

- Outcome: passed
- Notes: 已同步更新中英文 README，完成版本一致性检查与全量 77 项单元测试回归。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-26 | `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v` | passed (v0.0.3, 77/77 tests ok) | `README.md`, `README.en.md`, `tests/` |
