# TASK-01：后端 Git 脉搏合并、签名缓存与冗余调用消除

- Issue: #66
- Status: done
- Depends on: none
- Test: tests/test_monitor_and_board.py

## 任务范围

在 `scripts/monitor.py` 中重构 Worktree 脉搏采集与仓库扫描路径：
1. 单 Worktree 改用 `git status --porcelain=v2 --branch -uall` 合并脏文件、分支、HEAD OID、upstream 与 ahead/behind 查询；直接读取 `.git` 文件/目录解析 `git_dir`、`commondir`、rebase/merge 状态与远端分支引用；对不可变 `(git_dir, head_oid)` 的 `git log -1` 元数据进行进程内缓存。
2. 引入基于目录与 `.git` 元数据 mtime/size/ref 的 `_WorktreePulseCache`：未变更的干净 Worktree 复用缓存并实时刷新相对时间，对已合入闲置（`retained_idle`）工作树实施长窗口降频复查，活跃/修改变更即时失效重扫。
3. 消除每轮扫描中重复调用的 `git worktree list`、按 `.git/config` mtime 缓存仓库元信息与 origin URL、并对 `register_repo` 增加 60s 节流避免每次轮询重写 `repos.json`。

不包含 Web HTTP 层缓存（TASK-02）及前端 HTML/CSS/JS 优化（TASK-03）。

## 验收标准

- [x] `inspect_worktree_pulse` 在常规 Worktree 下单次探测仅派生 ≤ 2 个 `git` 子进程，二次命中 HEAD 缓存时仅 ≤ 1 个 `git` 子进程，返回字段与语义 100% 向后兼容
- [x] 引入签名驱动的 Worktree 脉搏缓存：未变动闲置工作树稳态复查子进程数为 0，任意文件改动/提交/TASK 更新立即触发缓存失效并反映最新状态
- [x] 消除 `collect_repo_snapshot` 重复 `git worktree list` 与 `register_repo` 高频写盘
- [x] 新增单元测试验证 porcelain v2 各种状态（dirty/untracked/renamed/unpushed/ahead/behind/misbound upstream）、缓存命中与失效行为，既有全量单测无回归

## 实现注意事项

- 严格保持只读 `--no-optional-locks` 与所有公开函数签名、返回字典键名兼容。
- 直接读取 `.git/refs/remotes/origin/*` 与 `packed-refs` 遇到 reftable 或异常结构时安全回退到 `git show-ref`，保证兼容性。
- 提供显式缓存清理函数供 `force_refresh=True` 与测试使用。

## 验证方式

- Command: `python3 -m unittest tests/test_monitor_and_board.py -v`
- Expected: 全部新增与既有测试通过，且单 Worktree 子进程数与稳态全量快照子进程数达到目标。

## 执行结果

- Outcome: passed
- Notes: 已在 `scripts/monitor.py` 实现 porcelain v2 合并探测、直读 `.git` 元数据与 packed-refs/HEAD/TASK 不可变缓存、闲置 Worktree 文件签名缓存（30s TTL）及 `register_repo` 60s 写盘节流。实测 5 仓库 64 Worktree 稳态快照子进程从 386 降至 12（-96.9%），耗时从 5025ms 降至 174ms，合并 CPU 从 7.59s 降至 0.318s（-95.8%）。

### 当前阻塞

无。

### 验证记录

| 日期 / 修订 | 命令或操作 | 实际结果 | 证据 |
| --- | --- | --- | --- |
| 2026-11-27 | `PYTHONPATH=tests python3 -m unittest test_monitor_and_board.TestMonitorAndBoard.test_pulse_porcelain_v2_subprocess_budget_and_idle_cache_invalidation ...` (5 项核心脉搏/缓存测试) | passed (5 passed in 13.6s) | `tests/test_monitor_and_board.py` |
| 2026-11-27 | 本机 5 仓库 64 Worktree 基准对比 (`collect_scope_snapshot`) | passed: COLD 156 cmds / 802ms; WARM 12 cmds / 174ms / 0.318s CPU (优化前 386 cmds / 5025ms / 7.59s CPU) | 实测对比输出 |
