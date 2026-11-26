# TASK-01：过滤主干清理 TASK 后历史分支经 merge-base 继承的遗留任务

- Issue: #1
- Status: done
- Depends on: none
- Test: python3 -B -m unittest discover -s tests -v

## 任务范围

1. **识别祖先提交中的历史 `TASK/` 目录（`scripts/monitor.py`）**：
   - 新增 `_get_worktree_base_task_dirs(wt_path, default_branch)`，通过 `git merge-base` 与 `git ls-tree -d --name-only <sha>:TASK` 获取分叉点已存在但已在 `main` 删除的历史 `TASK` 目录名集合，与 `main_task_dirs` 合并为 `inherited_dirs`。
   - 对非当前工作树自身改动且未关联开放 Issue 编号的已抑制完成态历史工作树，通过 `suppressed_worktrees` 归入 `retained_idle_worktrees`，避免在纯本地扫描模式下退化为空白活跃项。
2. **补充回归测试（`tests/test_monitor_and_board.py`）**：
   - 覆盖 `main` 删除历史 `TASK/` 后旧工作树仍能屏蔽祖先继承任务的场景，并验证纯本地扫描下已完成旧工作树不会产生空白残留项。

## 验收标准

- [x] 通过 `merge-base(default_branch, HEAD)` 识别并过滤二级工作树继承自祖先提交的历史 `TASK/` 目录
- [x] 被抑制的已完成历史工作树归入保留空闲列表，不在纯本地扫描下退化为空白活跃项
- [x] 补充单元测试并通过全量回归校验

## 执行结果

- Outcome: passed
- Notes: 在工作树 `/Users/iamzjt/.agents/skills/idd-worktrees/1-filter-merge-base-legacy-tasks` 中完成实现并运行全量 `unittest`，47 项测试全部通过。
