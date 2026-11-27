# TASK-02：根据最新功能与新版看板 UI 重写中英文 README

- Issue: 77-readme-ui-readme
- Status: planned
- Depends on: TASK-01
- Test: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`

## 任务范围
- 重写 `README.md` 与 `README.en.md`，全面同步最新特性与新版看板 UI：
  - Hero 看板图注、对比表与三层架构描述同步磨砂玻璃多视图看板、自适应低耗轮询、`idd preview` 与双格式交付汇总
  - 6 宫格核心特性同步：先对齐方案门禁与物理并行、磨砂玻璃雷达与详情抽屉、极致低耗引擎与零闪烁动效、全局 `auto-merge` 与两轮 CI 自愈、PR 变更列表/验证表格与 Squash 纯文本双格式汇总、看板逐卡流式清理与双平台零依赖
  - 工作原理、快速开始、可选全局/项目级规则模板与折叠 CLI 命令速查表与 `SKILL.md` 和 `scripts/idd_cli.py` 完整对齐
- 保持 `scripts/version.py` 校验的版本徽章格式（`v0.0.4`）和 Star History 区块完好。

## 验收标准

- [ ] `README.md` 与 `README.en.md` 内容完整、准确反映最新功能与新版看板交互
- [ ] 所有引用图片路径存在，文内目录锚点与标题匹配，中英文结构对称
- [ ] `python3 scripts/release.py --check` 与 `python3 -m unittest discover -s tests -v` 全量通过

## 实现注意事项

- 不修改 `SKILL.md` 中的版本号，README 版本徽章继续保持 `v0.0.4`。

## 验证方式

- Command: `python3 scripts/release.py --check && python3 -m unittest discover -s tests -v`
- Expected: 版本一致性检查通过，全部单元测试通过

## 执行结果

- Outcome: pending
- Notes: 尚未执行。

### 当前阻塞

无。

### 验证记录

尚未执行，不预填通过记录。
