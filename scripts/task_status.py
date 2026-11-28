#!/usr/bin/env python3
"""Read task headers and print a derived overview without changing any files."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from git_worktrees import list_worktrees


STATUSES = ("planned", "in_progress", "blocked", "deferred", "cancelled", "done", "unknown")
FIELD = re.compile(r"^- (Issue|Goal|Status|Depends on|Test):[ \t]*(.*)$")


def parse_issue_number(raw_issue: str, dir_name: str = "") -> int | None:
    """Extract an integer Issue number from an Issue header or directory prefix."""
    cleaned = raw_issue.strip()
    if cleaned and cleaned.lower() != "none":
        match = re.fullmatch(r"[#! ]*(\d+)", cleaned)
        if match:
            return int(match.group(1))
        prefix_match = re.match(r"^(\d+)-", cleaned)
        if prefix_match:
            return int(prefix_match.group(1))
        url_match = re.search(r"/(?:issues|merge_requests|pull)/(\d+)(?:[/?#].*)?$", cleaned)
        if url_match:
            return int(url_match.group(1))
    if dir_name:
        dir_match = re.match(r"^(\d+)(?:-|$)", dir_name)
        if dir_match:
            return int(dir_match.group(1))
    return None


def _matches_issue_filter(dir_name: str, issue_filter: str | None) -> bool:
    if issue_filter is None:
        return True
    if dir_name == issue_filter:
        return True
    filter_num = parse_issue_number(issue_filter)
    dir_num = parse_issue_number("", dir_name)
    return filter_num is not None and dir_num == filter_num


def is_task_record(path: Path) -> bool:
    """Recognize numbered TASK records used by progress and delivery commands."""
    return path.is_file() and re.match(r"^TASK-\d+(?:-|\.md)", path.name) is not None


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

    has_issue_or_legacy = bool(fields.get("Issue") or fields.get("Goal"))
    if not has_issue_or_legacy:
        issues.append("缺少头部字段：Issue")
    for key in ("Status", "Depends on", "Test"):
        if not fields.get(key):
            issues.append(f"缺少头部字段：{key}")
    issues.extend(f"重复头部字段：{key}" for key in sorted(duplicates))

    issue_dir = relative.parts[0]
    dir_num = parse_issue_number("", issue_dir)

    raw_issue_field = fields.get("Issue", "")
    legacy_field = fields.get("Goal", "")
    if raw_issue_field:
        parsed_header_num = parse_issue_number(raw_issue_field)
        valid_match = (
            raw_issue_field == issue_dir
            or (parsed_header_num is not None and dir_num is not None and parsed_header_num == dir_num)
            or (raw_issue_field.lower() == "none" and dir_num is None)
        )
        if not valid_match:
            issues.append(f"Issue 与目录不一致：{raw_issue_field}")
    elif legacy_field and legacy_field != issue_dir:
        issues.append(f"Issue 目录不一致：{legacy_field}")

    raw_status = fields.get("Status", "")
    status = raw_status if raw_status in STATUSES[:-1] and "Status" not in duplicates else "unknown"
    if status == "unknown" and raw_status:
        issues.append(f"状态无法确定：{raw_status}")
    issue_number = parse_issue_number(raw_issue_field, issue_dir)
    return {
        "id": "-".join(path.stem.split("-")[:2]),
        "title": title,
        "path": f"TASK/{relative.as_posix()}",
        "status": status,
        "raw_status": raw_status,
        "depends_on": fields.get("Depends on", ""),
        "issue": raw_issue_field or legacy_field,
        "issue_number": issue_number,
        "test": fields.get("Test", ""),
        "issues": issues,
    }


def collect_task_entries(
    task_root: Path,
    issue_filter: str | None,
    open_only: bool,
    *,
    worktree: Path | None = None,
    branch: str | None = None,
) -> tuple[list[dict], list[str], bool]:
    """Collect Issue directory summaries from one TASK/ root."""
    grouped: dict[str, list[dict]] = {}
    for path in sorted(task_root.glob("*/TASK-*.md")):
        if is_task_record(path):
            if _matches_issue_filter(path.parent.name, issue_filter):
                grouped.setdefault(path.parent.name, []).append(read_task(path, task_root))
    matched = issue_filter is None or bool(grouped)
    entries: list[dict] = []
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
            "issue": name,
            "issue_number": issue_number,
            "total": len(tasks),
            "done": counts["done"],
            "counts": {status: counts[status] for status in STATUSES},
            "tasks": [task for task in tasks if not open_only or task["status"] != "done"],
        }
        if worktree is not None:
            entry["worktree"] = str(worktree)
            entry["branch"] = branch or ""
        entries.append(entry)
    return entries, warnings, matched


def collect(task_root: Path, issue_filter: str | None, open_only: bool) -> dict:
    """Collect task status under a single TASK/ directory."""
    entries, warnings, matched = collect_task_entries(task_root, issue_filter, open_only)
    if issue_filter is not None and not matched:
        raise ValueError(f"没有匹配的 Issue 目录：{issue_filter}")
    return {"issues": entries, "warnings": warnings}


def collect_all_worktrees(repo_root: Path, issue_filter: str | None, open_only: bool) -> dict:
    """Collect task status across all git worktrees belonging to the repository."""
    worktrees = list_worktrees(repo_root)
    all_entries: list[dict] = []
    all_warnings: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    matched_any = issue_filter is None

    for wt in worktrees:
        wt_path = Path(wt["path"]).resolve()
        task_root = wt_path / "TASK"
        if not task_root.is_dir():
            continue
        entries, warnings, matched = collect_task_entries(
            task_root,
            issue_filter,
            open_only,
            worktree=wt_path,
            branch=wt.get("branch", ""),
        )
        if matched:
            matched_any = True
        for entry in entries:
            dedup_key = (entry["issue"], str(wt_path))
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            all_entries.append(entry)
        all_warnings.extend(warnings)

    if issue_filter is not None and not matched_any:
        raise ValueError(f"没有匹配的 Issue 目录：{issue_filter}")

    all_entries.sort(key=lambda item: (item.get("issue_number") or 10**9, item["issue"], item.get("worktree", "")))
    return {"issues": all_entries, "warnings": all_warnings}


def cell(value: str) -> str:
    """Escape pipe characters for Markdown table cells."""
    return value.replace("|", r"\|")


def render(data: dict) -> str:
    """Render collected Issue/task data as a concise Markdown overview."""
    lines = ["按任务头部 Status 统计；任务全为 done 不代表 Issue 级验收已完成。", ""]
    entries = data.get("issues", [])
    if not entries:
        return "\n".join(lines + ["没有匹配的 Issue。"])

    has_worktree_info = any("worktree" in item for item in entries)
    if has_worktree_info:
        lines.extend([
            "| Issue | 目录 | done / 总数 | planned | in_progress | blocked | deferred | cancelled | unknown | 工作树 / 分支 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])
    else:
        lines.extend([
            "| Issue 目录 | done / 总数 | planned | in_progress | blocked | deferred | cancelled | unknown |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ])

    for item in entries:
        counts = item["counts"]
        if has_worktree_info:
            issue_str = f"#{item['issue_number']}" if item.get("issue_number") is not None else "—"
            wt_name = Path(item["worktree"]).name if item.get("worktree") else "—"
            branch = item.get("branch") or "—"
            wt_col = cell(f"`{wt_name}` ({branch})")
            values = [issue_str, cell(item["issue"]), f"{item['done']} / {item['total']}"]
            values.extend(str(counts[status]) for status in STATUSES if status != "done")
            values.append(wt_col)
        else:
            values = [cell(item["issue"]), f"{item['done']} / {item['total']}"]
            values.extend(str(counts[status]) for status in STATUSES if status != "done")
        lines.append("| " + " | ".join(values) + " |")

    remaining = [(item, task) for item in entries for task in item["tasks"] if task["status"] != "done"]
    if remaining:
        lines.extend(["", "非 done 任务（含暂缓与取消；依赖是否可执行需读取原任务确认）：", ""])
        for item, task in remaining:
            status = task["status"]
            if status == "unknown":
                status += f"（原值：{task['raw_status'] or '缺失'}）"
            issue_prefix = f"#{item['issue_number']} " if item.get("issue_number") is not None and has_worktree_info else ""
            lines.append(
                f"- {issue_prefix}{item['issue']}/{task['id']} [{status}] {task['title']}；"
                f"依赖：{task['depends_on'] or '未记录'}"
            )
    if data.get("warnings"):
        lines.extend(["", "记录问题：", ""])
        lines.extend(f"- {warning}" for warning in data["warnings"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="包含 TASK/ 或属于 Git 仓库的根目录，默认当前目录")
    parser.add_argument("--issue", dest="issue", help="只显示指定 Issue 目录（名称与 TASK/ 下子目录一致，也可传 #编号）")
    parser.add_argument("--goal", dest="issue", help=argparse.SUPPRESS)
    parser.add_argument("--open-only", action="store_true", help="只显示含非 done 任务的 Issue 及其非 done 任务")
    parser.add_argument("--all-worktrees", action="store_true", help="扫描当前 Git 仓库的所有工作树中的 TASK/ 目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    args = parser.parse_args()

    try:
        if args.all_worktrees:
            data = collect_all_worktrees(args.root, args.issue, args.open_only)
        else:
            task_root = args.root / "TASK"
            if not task_root.is_dir():
                parser.error(f"任务目录不存在：{task_root}")
            data = collect(task_root, args.issue, args.open_only)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data))


if __name__ == "__main__":
    main()
