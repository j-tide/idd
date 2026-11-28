"""The IDD issue, branch and commit naming conventions."""

from __future__ import annotations

from pathlib import Path
import re

from command_runner import IddError


ALLOWED_TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "ci", "chore")
BRANCH_PREFIXES = tuple(f"{kind}/" for kind in ALLOWED_TYPES)
_TYPE_PATTERN = "|".join(ALLOWED_TYPES)
MAX_ISSUE_SCOPE_LEN = 16
ISSUE_SCOPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONVENTIONAL_TITLE_RE = re.compile(
    rf"^({_TYPE_PATTERN})(\([^)\r\n]+\))?(!)?[:：]\s*(.+)$",
    re.IGNORECASE,
)
EMPTY_SCOPE_PREFIX_RE = re.compile(
    rf"^({_TYPE_PATTERN})\(\s*\)(!)?[:：]\s*(.*)$",
    re.IGNORECASE,
)
ISSUE_BRANCH_RE = re.compile(rf"^({_TYPE_PATTERN})/(\d+)-[a-z0-9]+(?:-[a-z0-9]+)*$")
LOCAL_BRANCH_RE = re.compile(rf"^({_TYPE_PATTERN})/[a-z0-9]+(?:-[a-z0-9]+)*$")
FORBIDDEN_PREFIXES = {
    "codex",
    "claude",
    "agy",
    "antigravity",
    "cursor",
    "copilot",
    "ai",
    "feature",
    "bugfix",
    "hotfix",
    "tmp",
    "temp",
    "wip",
    "dev",
}


def slugify(text: str, fallback: str) -> str:
    """Convert text to lowercase ASCII kebab-case (max 40 chars), returning fallback if empty."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > 40:
        slug = slug[:40].strip("-")
    return slug or fallback


def _suggest_branch_name(branch: str, issue_number: int | None = None) -> str:
    """Compute a valid `<type>/<issue#>-<slug>` or `<type>/<slug>` suggestion for an invalid branch."""
    prefix_map = {
        "feature": "feat",
        "bugfix": "fix",
        "hotfix": "fix",
        "bug": "fix",
    }
    if "/" in branch:
        raw_prefix, raw_tail = branch.split("/", 1)
        raw_prefix_l = raw_prefix.lower()
        suggested_type = prefix_map.get(raw_prefix_l, raw_prefix_l if raw_prefix_l in ALLOWED_TYPES else "feat")
    else:
        raw_tail = branch
        suggested_type = "feat"

    if issue_number is not None:
        tail_no_num = re.sub(rf"^{issue_number}(?:-|$)", "", raw_tail)
        clean_slug = slugify(tail_no_num, "task")
        return f"{suggested_type}/{issue_number}-{clean_slug}"
    clean_slug = slugify(raw_tail, "task")
    return f"{suggested_type}/{clean_slug}"


def validate_branch_name(
    branch: str,
    issue_number: int | None = None,
    worktree: Path | None = None,
) -> None:
    """Enforce 8-type branch naming and reject tool/alias prefixes without modifying Git hooks."""
    if not branch or branch == "(detached)":
        raise IddError("当前处于游离 HEAD（detached），请先切换到规范分支（如 `feat/<issue#>-<slug>`）。")

    prefix_part = branch.split("/", 1)[0].lower() if "/" in branch else ""
    if prefix_part in FORBIDDEN_PREFIXES:
        reason = f"禁止使用 `{prefix_part}/` 前缀"
    elif issue_number is not None:
        m = ISSUE_BRANCH_RE.fullmatch(branch)
        if m and int(m.group(2)) == issue_number:
            return
        reason = f"绑定 Issue #{issue_number} 的分支须匹配 `<type>/{issue_number}-<slug>`"
    else:
        if LOCAL_BRANCH_RE.fullmatch(branch):
            return
        reason = "分支须匹配 `<type>/<slug>`（kebab-case 小写字母数字）"

    suggested = _suggest_branch_name(branch, issue_number)
    rename_cmd = f"git -C {worktree} branch -m {branch} {suggested}" if worktree else f"git branch -m {branch} {suggested}"
    allowed_str = " | ".join(ALLOWED_TYPES)
    raise IddError(
        f"分支名 `{branch}` 不符合 IDD 规范（{reason}）。\n"
        f"允许的分支前缀：{allowed_str}\n"
        f"请先重命名分支再继续：{rename_cmd}"
    )


def format_conventional_title(default_type: str, raw_title: str) -> str:
    """Ensure a PR / Squash commit title has a single normalized Conventional Commit prefix."""
    cleaned = raw_title.strip()
    match = CONVENTIONAL_TITLE_RE.match(cleaned)
    if match:
        prefix_type = match.group(1).lower()
        scope = match.group(2) or ""
        bang = match.group(3) or ""
        subject = match.group(4).strip()
        return f"{prefix_type}{scope}{bang}: {subject}"
    return f"{default_type}: {cleaned}"


def _validate_issue_scope(raw_scope: str) -> str:
    """Validate and normalize an optional short Issue scope token (<= 16 chars, kebab-case)."""
    cleaned = raw_scope.strip().lower()
    if not cleaned:
        raise IddError("Issue 标题括号中的 scope 不能为空；不需要作用域时请省略括号。")
    if len(cleaned) > MAX_ISSUE_SCOPE_LEN or not ISSUE_SCOPE_RE.fullmatch(cleaned):
        raise IddError(
            f"Issue 标题括号中的 scope `{raw_scope.strip()}` 不符合规范。\n"
            f"括号内容必须简短：仅允许单个小写英文/数字/连字符标识（`a-z0-9-`，最多 {MAX_ISSUE_SCOPE_LEN} 字符），"
            "不含空格、逗号、斜杠或中文（如 `sync`、`land`、`repo-init`）；跨模块改动请直接省略括号。"
        )
    return cleaned


def validate_and_format_issue_title(
    raw_title: str,
    *,
    issue_type: str | None = None,
    scope: str | None = None,
    raw: bool = False,
) -> str:
    """Validate and normalize an Issue title against `<type>(<scope>): <subject>` rules."""
    cleaned = raw_title.strip()
    if not cleaned:
        raise IddError("Issue 标题不能为空。")
    if "\n" in cleaned or "\r" in cleaned:
        raise IddError("Issue 标题必须为单行文本。")

    if raw:
        if issue_type is not None or scope is not None:
            raise IddError("`--raw` 不能与 `--type` 或 `--scope` 同时使用。")
        return cleaned

    norm_type: str | None = None
    if issue_type is not None:
        norm_type = issue_type.strip().lower()
        if norm_type not in ALLOWED_TYPES:
            raise IddError(f"非法的 Issue 类型 `{issue_type}`，允许值：{' | '.join(ALLOWED_TYPES)}")

    norm_scope: str | None = _validate_issue_scope(scope) if scope is not None else None

    if EMPTY_SCOPE_PREFIX_RE.match(cleaned):
        _validate_issue_scope("")

    match = CONVENTIONAL_TITLE_RE.match(cleaned)
    if match:
        parsed_type = match.group(1).lower()
        raw_scope_group = match.group(2)
        parsed_scope = _validate_issue_scope(raw_scope_group[1:-1]) if raw_scope_group else None
        bang = match.group(3) or ""
        subject = match.group(4).strip()
        if not subject:
            raise IddError("Issue 标题冒号后的描述不能为空。")
        if norm_type is not None and norm_type != parsed_type:
            raise IddError(f"传入的 `--type {norm_type}` 与标题前缀 `{parsed_type}` 冲突。")
        if norm_scope is not None and parsed_scope is not None and norm_scope != parsed_scope:
            raise IddError(f"传入的 `--scope {norm_scope}` 与标题括号中的 `{parsed_scope}` 冲突。")
        final_type = norm_type or parsed_type
        final_scope = norm_scope or parsed_scope
        scope_part = f"({final_scope})" if final_scope else ""
        return f"{final_type}{scope_part}{bang}: {subject}"

    if norm_type is not None:
        scope_part = f"({norm_scope})" if norm_scope else ""
        return f"{norm_type}{scope_part}: {cleaned}"

    allowed_str = " | ".join(ALLOWED_TYPES)
    raise IddError(
        f"Issue 标题 `{cleaned}` 不符合 IDD 命名规范。\n"
        "请使用 `<type>: <简明描述>` 或 `<type>(<scope>): <简明描述>`（建议 ≤ 50 字符，不重复类型动词）。\n"
        f"允许的 `<type>`：{allowed_str}\n"
        f"可选 `(<scope>)` 须简短：单个小写英文/数字/连字符标识（≤ {MAX_ISSUE_SCOPE_LEN} 字符，如 `sync`、`land`）。\n"
        "示例：`idd issue create --title \"fix(sync): 避免误匹配行内标记\"`\n"
        "或自动拼接：`idd issue create --type fix --scope sync --title \"避免误匹配行内标记\"`\n"
        "若确需使用非规范标题，请显式传入 `--raw`。"
    )


def infer_prefix_from_title(title: str) -> str | None:
    """Extract standard `<type>` prefix from a Conventional-style Issue title."""
    match = CONVENTIONAL_TITLE_RE.match(title.strip())
    if not match:
        return None
    return match.group(1).lower()


def slug_source_from_issue_title(title: str) -> str:
    """Strip Conventional `<type>:` prefix when deriving a worktree/branch slug."""
    cleaned = title.strip()
    match = CONVENTIONAL_TITLE_RE.match(cleaned)
    if not match:
        return cleaned
    scope = (match.group(2) or "").strip("()").strip()
    subject = match.group(4).strip()
    return f"{scope} {subject}".strip() if scope else subject


def infer_prefix_from_labels(labels: set[str]) -> str:
    """Map Issue labels to one of the 8 standard branch/commit types."""
    if labels & {"bug", "fix", "bugfix"}:
        return "fix"
    if "refactor" in labels:
        return "refactor"
    if labels & {"perf", "performance"}:
        return "perf"
    if labels & {"docs", "documentation"}:
        return "docs"
    if labels & {"test", "testing"}:
        return "test"
    if "ci" in labels:
        return "ci"
    if labels & {"chore", "dependencies"}:
        return "chore"
    return "feat"
