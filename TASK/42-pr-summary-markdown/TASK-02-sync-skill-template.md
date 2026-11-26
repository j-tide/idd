# TASK-02：同步 SKILL 汇总正文模板并完成全量回归

- Issue: 42-pr-summary-markdown
- Status: planned
- Depends on: TASK-01
- Test: python3 -m unittest discover -s tests -v && python3 scripts/release.py --check

## 任务范围
- 更新 `SKILL.md` 中「主线需求提交 / PR / MR 汇总正文模板」代码块为 `markdown` 方案 A 格式。
- 在工作树执行全量单元测试与版本一致性校验。

## 验收标准
- [ ] `SKILL.md` 模板与 `build_issue_summary` 实际输出结构完全一致
- [ ] 全量单元测试与 `scripts/release.py --check` 通过

## 实现注意事项
- 保持 `SKILL.md` 其余内容和版本号不变。

## 验证方式
- Command: `python3 -m unittest discover -s tests -v && python3 scripts/release.py --check`
- Expected: 全量测试通过且版本一致性校验通过。

## 执行结果
- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞
无。

### 验证记录
尚未执行，不预填通过记录。
