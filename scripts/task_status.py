#!/usr/bin/env python3
"""Read task headers and print a derived overview without changing any files."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess


STATUSES = ("planned", "in_progress", "blocked", "deferred", "cancelled", "done", "unknown")
FIELD = re.compile(r"^- (Goal|Issue|Status|Depends on|Test):[ \t]*(.*)$")


def parse_issue_number(raw_issue: str, goal_name: str = "") -> int | None:
    """Extract an integer GitHub issue number from an Issue header or goal directory prefix."""
    cleaned = raw_issue.strip()
    if cleaned and cleaned.lower() != "none":
        match = re.fullmatch(r"#?(\d+)", cleaned)
        if match:
            return int(match.group(1))
        url_match = re.search(r"/issues/(\d+)(?:[/?#].*)?$", cleaned)
        if url_match:
            return int(url_match.group(1))
    if goal_name:
        prefix_match = re.match(r"^(\d+)-", goal_name)
        if prefix_match:
            return int(prefix_match.group(1))
    return None


def read_task(path: Path, task_root: Path) -> dict:
    """Parse one TASK-*.md file's header fields without mutating the file."""
    relative = path.relative_to(task_root)
    fields: dict[str, str] = {}
    duplicates = set()
    issues = []
    title = path.stem
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        lines = []
        issues.append(f"读取失败：{type(exc).__name__}")
    for line in lines:
        if re.match(r"^##(?:\s|$)", line):
            break
        if line.startswith("# "):
            title = line[2:].strip()
        match = FIELD.fullmatch(line)
        if match:
            key, value = match.groups()
            if key in fields:
                duplicates.add(key)
            else:
                fields[key] = value.strip()
    for key in ("Goal", "Status", "Depends on", "Test"):
        if not fields.get(key):
            issues.append(f"缺少头部字段：{key}")
    issues.extend(f"重复头部字段：{key}" for key in sorted(duplicates))
    goal = relative.parts[0]
    if fields.get("Goal") and fields["Goal"] != goal:
        issues.append(f"Goal 与目录不一致：{fields['Goal']}")
    raw_status = fields.get("Status", "")
    status = raw_status if raw_status in STATUSES[:-1] and "Status" not in duplicates else "unknown"
    if status == "unknown" and raw_status:
        issues.append(f"状态无法确定：{raw_status}")
    raw_issue = fields.get("Issue", "")
    issue_number = parse_issue_number(raw_issue, goal)
    return {
        "id": "-".join(path.stem.split("-")[:2]),
        "title": title,
        "path": f"TASK/{relative.as_posix()}",
        "status": status,
        "raw_status": raw_status,
        "depends_on": fields.get("Depends on", ""),
        "issue": raw_issue,
        "issue_number": issue_number,
        "test": fields.get("Test", ""),
        "issues": issues,
    }


def _collect_from_task_root(
    task_root: Path,
    goal: str | None,
    open_only: bool,
    *,
    worktree: Path | None = None,
    branch: str | None = None,
) -> tuple[list[dict], list[str], bool]:
    """Collect goal summaries from one TASK/ root. Returns (goals, warnings, matched_goal)."""
    grouped: dict[str, list[dict]] = {}
    for path in sorted(task_root.glob("*/TASK-*.md")):
        if path.is_file() and re.match(r"^TASK-\d+(?:-|\.md)", path.name):
            if goal is None or path.parent.name == goal:
                grouped.setdefault(path.parent.name, []).append(read_task(path, task_root))
    matched_goal = goal is None or goal in grouped
    goals: list[dict] = []
    warnings: list[str] = []
    for name, tasks in grouped.items():
        counts = Counter(task["status"] for task in tasks)
        if open_only and counts["done"] == len(tasks):
            continue
        for task in tasks:
            prefix = f"[{worktree.name}] " if worktree is not None else ""
            warnings.extend(f"{prefix}{task['path']}: {issue}" for issue in task["issues"])
        issue_number = next((t["issue_number"] for t in tasks if t["issue_number"] is not None), None)
        if issue_number is None:
            issue_number = parse_issue_number("", name)
        entry: dict = {
            "goal": name,
            "issue_number": issue_number,
            "total": len(tasks),
            "done": counts["done"],
            "counts": {status: counts[status] for status in STATUSES},
            "tasks": [task for task in tasks if not open_only or task["status"] != "done"],
        }
        if worktree is not None:
            entry["worktree"] = str(worktree)
            entry["branch"] = branch or ""
        goals.append(entry)
    return goals, warnings, matched_goal


def collect(task_root: Path, goal: str | None, open_only: bool) -> dict:
    """Collect task status under a single TASK/ directory."""
    goals, warnings, matched_goal = _collect_from_task_root(task_root, goal, open_only)
    if goal is not None and not matched_goal:
        raise ValueError(f"没有匹配的任务目标：{goal}")
    return {"goals": goals, "warnings": warnings}


def list_git_worktrees(repo_root: Path) -> list[dict[str, str]]:
    """Return list of {path, branch} dictionaries from `git worktree list --porcelain`."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or f"无法列出 Git 工作树：{repo_root}")
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            if current.get("path"):
                worktrees.append(current)
            current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/"):]
            current["branch"] = ref
        elif line == "detached":
            current.setdefault("branch", "(detached)")
    if current.get("path"):
        worktrees.append(current)
    return worktrees


def collect_all_worktrees(repo_root: Path, goal: str | None, open_only: bool) -> dict:
    """Collect task status across all git worktrees belonging to the repository."""
    worktrees = list_git_worktrees(repo_root)
    all_goals: list[dict] = []
    all_warnings: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    matched_any = goal is None

    for wt in worktrees:
        wt_path = Path(wt["path"]).resolve()
        task_root = wt_path / "TASK"
        if not task_root.is_dir():
            continue
        goals, warnings, matched_goal = _collect_from_task_root(
            task_root,
            goal,
            open_only,
            worktree=wt_path,
            branch=wt.get("branch", ""),
        )
        if matched_goal:
            matched_any = True
        for entry in goals:
            dedup_key = (entry["goal"], str(wt_path))
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            all_goals.append(entry)
        all_warnings.extend(warnings)

    if goal is not None and not matched_any:
        raise ValueError(f"没有匹配的任务目标：{goal}")

    all_goals.sort(key=lambda g: (g.get("issue_number") or 10**9, g["goal"], g.get("worktree", "")))
    return {"goals": all_goals, "warnings": all_warnings}


def cell(value: str) -> str:
    """Escape pipe characters for Markdown table cells."""
    return value.replace("|", r"\|")


def render(data: dict) -> str:
    """Render collected goal/task data as a concise Markdown overview."""
    lines = ["按任务头部 Status 统计；任务全为 done 不代表目标级验收已完成。", ""]
    if not data["goals"]:
        return "\n".join(lines + ["没有匹配的目标。"])

    has_worktree_info = any("worktree" in g for g in data["goals"])
    if has_worktree_info:
        lines.extend([
            "| Issue | 目标 | done / 总数 | planned | in_progress | blocked | deferred | cancelled | unknown | 工作树 / 分支 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])
    else:
        lines.extend([
            "| 目标 | done / 总数 | planned | in_progress | blocked | deferred | cancelled | unknown |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ])

    for goal in data["goals"]:
        counts = goal["counts"]
        if has_worktree_info:
            issue_str = f"#{goal['issue_number']}" if goal.get("issue_number") is not None else "—"
            wt_name = Path(goal["worktree"]).name if goal.get("worktree") else "—"
            branch = goal.get("branch") or "—"
            wt_col = cell(f"`{wt_name}` ({branch})")
            values = [issue_str, cell(goal["goal"]), f"{goal['done']} / {goal['total']}"]
            values.extend(str(counts[status]) for status in STATUSES if status != "done")
            values.append(wt_col)
        else:
            values = [cell(goal["goal"]), f"{goal['done']} / {goal['total']}"]
            values.extend(str(counts[status]) for status in STATUSES if status != "done")
        lines.append("| " + " | ".join(values) + " |")

    remaining = [(goal, task) for goal in data["goals"] for task in goal["tasks"] if task["status"] != "done"]
    if remaining:
        lines.extend(["", "非 done 任务（含暂缓与取消；依赖是否可执行需读取原任务确认）：", ""])
        for goal, task in remaining:
            status = task["status"]
            if status == "unknown":
                status += f"（原值：{task['raw_status'] or '缺失'}）"
            issue_prefix = f"#{goal['issue_number']} " if goal.get("issue_number") is not None and has_worktree_info else ""
            lines.append(
                f"- {issue_prefix}{goal['goal']}/{task['id']} [{status}] {task['title']}；"
                f"依赖：{task['depends_on'] or '未记录'}"
            )
    if data["warnings"]:
        lines.extend(["", "记录问题：", ""])
        lines.extend(f"- {warning}" for warning in data["warnings"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="包含 TASK/ 或属于 Git 仓库的根目录，默认当前目录")
    parser.add_argument("--goal", help="只显示指定目标，名称须与 TASK 下的目录一致")
    parser.add_argument("--open-only", action="store_true", help="只显示含非 done 任务的目标及其非 done 任务")
    parser.add_argument("--all-worktrees", action="store_true", help="扫描当前 Git 仓库的所有工作树中的 TASK/ 目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    args = parser.parse_args()

    try:
        if args.all_worktrees:
            data = collect_all_worktrees(args.root, args.goal, args.open_only)
        else:
            task_root = args.root / "TASK"
            if not task_root.is_dir():
                parser.error(f"任务目录不存在：{task_root}")
            data = collect(task_root, args.goal, args.open_only)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data))


if __name__ == "__main__":
    main()
