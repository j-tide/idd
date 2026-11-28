"""Build pull request Markdown and plain Squash messages from the same task records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from typing import Any

from command_runner import run_cmd
from naming import format_conventional_title
import task_status


def _parse_task_markdown_details(path: Path) -> dict[str, str]:
    """Extract fallback Test command/outcome info from a TASK markdown body."""
    info = {"command": "", "outcome": "", "latest_result": ""}
    if not path.is_file():
        return info
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- Command:") and not info["command"]:
            info["command"] = stripped[len("- Command:"):].strip()
        elif stripped.startswith("- Outcome:") and not info["outcome"]:
            info["outcome"] = stripped[len("- Outcome:"):].strip()
        elif stripped.startswith("|") and "---" not in stripped and "日期 / 修订" not in stripped:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 3 and cells[1]:
                info["latest_result"] = f"{cells[1]} — {cells[2]}"
    return info


def _collect_commit_task_records(worktree: Path, issue_dir: str, base_ref: str) -> list[dict[str, Any]]:
    """Read git commits since merge-base and extract Task/Test metadata."""
    check_ref = run_cmd(["git", "-C", str(worktree), "rev-parse", "--verify", base_ref], check=False)
    if check_ref.returncode != 0:
        return []

    mb = run_cmd(["git", "-C", str(worktree), "merge-base", base_ref, "HEAD"], check=False)
    if mb.returncode != 0 or not mb.stdout.strip():
        return []
    base_sha = mb.stdout.strip()
    log_proc = run_cmd(
        ["git", "-C", str(worktree), "log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{base_sha}..HEAD"],
        check=False,
    )
    if log_proc.returncode != 0:
        return []

    records: list[dict[str, Any]] = []
    for raw_entry in log_proc.stdout.split("\x1e"):
        entry = raw_entry.strip("\n")
        if not entry.strip():
            continue
        parts = entry.split("\x1f")
        if len(parts) < 3:
            continue
        sha, subject, body = parts[0].strip(), parts[1].strip(), parts[2]
        commit_type = ""
        change_desc = subject
        type_match = re.match(r"^([a-z]+)(?:\([^)]+\))?:\s*(.+)$", subject)
        if type_match:
            commit_type, change_desc = type_match.group(1), type_match.group(2).strip()

        task_id = ""
        test_lines: list[str] = []
        extra_lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if line.startswith("Task:"):
                val = line[len("Task:"):].strip()
                m = re.search(r"(TASK-\d+)", val)
                if m and (issue_dir in val or val.startswith("TASK-")):
                    task_id = m.group(1)
            elif line.startswith("Test:"):
                val = line[len("Test:"):].strip()
                if val:
                    test_lines.append(val)
            elif line.startswith(("Refs:", "Closes:", "Fixes:", "Co-authored-by:", "Signed-off-by:")):
                continue
            elif line:
                extra_lines.append(raw_line.rstrip())
            elif extra_lines and extra_lines[-1] != "":
                extra_lines.append("")
        while extra_lines and extra_lines[-1] == "":
            extra_lines.pop()

        records.append(
            {
                "sha": sha,
                "type": commit_type,
                "subject": subject,
                "change": change_desc,
                "task_id": task_id,
                "test": "; ".join(test_lines),
                "tests": test_lines,
                "extra": "\n".join(extra_lines).strip(),
            }
        )
    return records


def _wrap_inline_code(text: str) -> str:
    """Wrap command text in a safe CommonMark inline code span."""
    cleaned = _unwrap_inline_code(text)
    if not cleaned:
        return ""
    runs = re.findall(r"`+", cleaned)
    max_ticks = max((len(r) for r in runs), default=0)
    fence = "`" * (max_ticks + 1)
    if cleaned.startswith("`") or cleaned.endswith("`"):
        return f"{fence} {cleaned} {fence}"
    return f"{fence}{cleaned}{fence}"


def _unwrap_inline_code(text: str) -> str:
    """Strip matching outer CommonMark inline code backticks if present."""
    cleaned = text.strip()
    if not cleaned.startswith("`"):
        return cleaned
    open_match = re.match(r"^(`+)", cleaned)
    if not open_match:
        return cleaned
    fence = open_match.group(1)
    fence_len = len(fence)
    for m in re.finditer(r"`+", cleaned[fence_len:]):
        if len(m.group(0)) == fence_len:
            end_pos = fence_len + m.end()
            if end_pos == len(cleaned):
                inner = cleaned[fence_len : fence_len + m.start()].strip()
                if inner:
                    return inner
            break
    return cleaned


def _extract_single_paren_note(rem: str) -> str | None:
    """Return inner text when rem is one balanced parenthetical note without backticks."""
    if not rem or "`" in rem:
        return None
    if not ((rem.startswith("(") and rem.endswith(")")) or (rem.startswith("（") and rem.endswith("）"))):
        return None
    depth = 0
    for idx, ch in enumerate(rem):
        if ch in ("(", "（"):
            depth += 1
        elif ch in (")", "）"):
            depth -= 1
            if depth < 0:
                return None
            if depth == 0 and idx != len(rem) - 1:
                return None
    if depth != 0:
        return None
    return rem[1:-1].strip()


def _unwrap_inline_code_with_note(text: str) -> tuple[str, str]:
    """Unwrap outer inline code ticks and peel a trailing parenthetical annotation if present."""
    cleaned = text.strip()
    if cleaned.startswith("`"):
        open_match = re.match(r"^(`+)", cleaned)
        if open_match:
            fence_len = len(open_match.group(1))
            for m in re.finditer(r"`+", cleaned[fence_len:]):
                if len(m.group(0)) == fence_len:
                    inner = cleaned[fence_len : fence_len + m.start()].strip()
                    rem = cleaned[fence_len + m.end() :].strip()
                    if inner:
                        if not rem:
                            return inner, ""
                        note = _extract_single_paren_note(rem)
                        if note is not None:
                            return inner, note
                    break

    paren_match = re.match(r"^(.*?)\s+([（(][^()（）]+[）)])$", cleaned)
    if paren_match:
        cmd_part = paren_match.group(1).strip()
        raw_note = paren_match.group(2).strip()
        note = raw_note[1:-1].strip()
        if (
            cmd_part
            and note
            and not cmd_part.endswith("$")
            and (
                (raw_note.startswith("（") and raw_note.endswith("）"))
                or bool(re.search(r"[\u4e00-\u9fff]", note))
                or bool(re.match(r"^(?:ci|all|full|local|smoke)\b", note, re.IGNORECASE))
            )
        ):
            return _unwrap_inline_code(cmd_part), note

    return cleaned, ""


_COMPLETED_CHECK_END_RE = re.compile(
    r"(?:\b(?:passed|failed|skipped|errors?|ok|pass|fail)|(?:通过|失败|跳过|无错误))$",
    re.IGNORECASE,
)
_TRAILING_STATUS_RE = re.compile(
    r"^(.+?)\s+(passed|failed|skipped|ok|通过|失败)$",
    re.IGNORECASE,
)
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")

_UV_VALUE_FLAGS = {
    "--extra",
    "--with",
    "--group",
    "--python",
    "--directory",
    "--project",
    "-p",
    "-C",
    "--package",
    "--only-group",
}
_UV_BOOL_FLAGS = {
    "--offline",
    "--locked",
    "--frozen",
    "--no-sync",
    "--dev",
    "--no-dev",
    "--isolated",
    "--quiet",
    "-q",
    "--all-extras",
    "--no-editable",
}
_PYTEST_VALUE_FLAGS = {
    "-o",
    "-k",
    "-m",
    "-c",
    "-n",
    "-W",
    "-r",
    "--tb",
    "--maxfail",
    "--rootdir",
    "--junitxml",
    "--cov",
    "--cov-report",
    "--ignore",
    "--deselect",
    "--color",
    "--durations",
    "--capture",
    "--log-level",
    "--asyncio-mode",
    "--confcutdir",
}
_PYTEST_BOOL_FLAGS = {
    "-q",
    "--quiet",
    "-v",
    "--verbose",
    "-vv",
    "-vvv",
    "-x",
    "--exitfirst",
    "-s",
    "-l",
    "--showlocals",
    "--lf",
    "--last-failed",
    "--ff",
    "--failed-first",
    "--nf",
    "--new-first",
    "--no-header",
    "--no-summary",
    "--no-cov",
    "--strict-markers",
    "--strict-config",
    "--full-trace",
}
_JS_VALUE_FLAGS = {
    "--maxWorkers",
    "--filter",
    "--reporter",
    "--testNamePattern",
    "--testPathPattern",
    "-t",
    "--config",
    "-c",
    "-C",
    "--dir",
    "--prefix",
}
_JS_BOOL_FLAGS = {
    "--run",
    "--watch",
    "--silent",
    "--if-present",
    "--",
    "-w",
    "-s",
    "--passWithNoTests",
    "--coverage",
}


def _looks_like_completed_check(text: str) -> bool:
    """Return True if a semicolon-separated fragment already ends with a check verdict."""
    return bool(_COMPLETED_CHECK_END_RE.search(text.strip()))


def _split_top_level_semicolons(cleaned: str) -> list[str]:
    """Split on `; ` only outside parentheses and inline backtick spans."""
    parts: list[str] = []
    buf: list[str] = []
    in_ticks = 0
    paren_depth = 0
    i = 0
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch == "`":
            j = i
            while j < n and cleaned[j] == "`":
                j += 1
            run = cleaned[i:j]
            run_len = j - i
            if in_ticks == 0:
                in_ticks = run_len
            elif run_len == in_ticks:
                in_ticks = 0
            buf.append(run)
            i = j
            continue
        if in_ticks == 0:
            if ch in ("(", "（"):
                paren_depth += 1
            elif ch in (")", "）"):
                paren_depth = max(0, paren_depth - 1)
            elif ch == ";" and paren_depth == 0 and i + 1 < n and cleaned[i + 1].isspace():
                seg = "".join(buf).strip()
                if seg:
                    parts.append(seg)
                buf.clear()
                i += 1
                while i < n and cleaned[i].isspace():
                    i += 1
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _split_test_segments(cleaned: str) -> list[str]:
    """Split multi-check Test strings on `; ` while preserving compound shell commands."""
    parts = _split_top_level_semicolons(cleaned)
    if len(parts) <= 1:
        return parts

    segments: list[str] = []
    buf: list[str] = []
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        if " — " in part:
            buf.append(part)
            segments.append("; ".join(buf))
            buf.clear()
        elif not buf and _looks_like_completed_check(part):
            segments.append(part)
        elif not buf and not any(" — " in later or _looks_like_completed_check(later) for later in parts[idx:]):
            segments.append("; ".join(parts[idx:]))
            break
        elif not buf and not any(" — " in later for later in parts[idx + 1:]):
            segments.append(part)
        else:
            buf.append(part)
        idx += 1
    if buf:
        segments.append("; ".join(buf))
    return segments


def _is_file_target(target: str) -> bool:
    base = target.rstrip("/").rsplit("/", 1)[-1]
    return "." in base and not target.endswith("/")


def _format_targets_struct(prefix: str, targets: list[str], *, raw_cmd: str) -> dict[str, Any]:
    if not targets:
        return {"code": prefix, "target_code": "", "meta": "", "simplified": prefix != raw_cmd}
    if len(targets) == 1:
        target = targets[0]
        joined = f"{prefix} {target}"
        if _is_file_target(target) and (len(joined) > 48 or target.count("/") >= 3):
            base = target.rstrip("/").rsplit("/", 1)[-1]
            return {"code": prefix, "target_code": base, "meta": "", "simplified": True}
        if not _is_file_target(target) and len(joined) > 55 and target.count("/") >= 3:
            segs = [s for s in target.split("/") if s]
            short_dir = ".../" + "/".join(segs[-2:]) + ("/" if target.endswith("/") else "")
            return {"code": prefix, "target_code": short_dir, "meta": "", "simplified": True}
        return {"code": joined, "target_code": "", "meta": "", "simplified": joined != raw_cmd}
    if len(targets) == 2:
        joined = f"{prefix} {targets[0]} {targets[1]}"
        if len(joined) <= 55:
            return {"code": joined, "target_code": "", "meta": "", "simplified": joined != raw_cmd}
    unit = "测试文件" if all(_is_file_target(t) for t in targets) else "测试目标"
    return {"code": prefix, "target_code": "", "meta": f"{len(targets)} 个{unit}", "simplified": True}


def _collect_positional_targets(
    args: list[str],
    *,
    value_flags: set[str],
    bool_flags: set[str],
    skip_r_prefix: bool = False,
) -> list[str]:
    targets: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in bool_flags:
            i += 1
            continue
        if tok in value_flags:
            i += 2
            continue
        if skip_r_prefix and tok.startswith("-r") and len(tok) > 2:
            i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        targets.append(tok)
        i += 1
    return targets


def _summarize_single_part_struct(raw_cmd: str) -> dict[str, Any]:
    """Shorten a single shell command (no `&&`) into structured code + optional meta."""
    cleaned = _unwrap_inline_code(raw_cmd)
    if not cleaned:
        return {"code": "", "target_code": "", "meta": "", "simplified": False}
    try:
        tokens = shlex.split(cleaned)
    except ValueError:
        tokens = cleaned.split()
    if not tokens:
        return {"code": cleaned, "target_code": "", "meta": "", "simplified": False}

    while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
        tokens.pop(0)

    changed = True
    while changed and tokens:
        changed = False
        head = tokens[0]
        head_base = Path(head).name
        if head_base == "uv" and len(tokens) >= 2 and tokens[1] == "run":
            tokens = tokens[2:]
            while tokens:
                tok = tokens[0]
                if tok in _UV_BOOL_FLAGS or any(tok.startswith(f"{f}=") for f in _UV_VALUE_FLAGS):
                    tokens.pop(0)
                elif tok in _UV_VALUE_FLAGS and len(tokens) >= 2:
                    tokens = tokens[2:]
                else:
                    break
            changed = True
        elif head_base in ("poetry", "pipenv", "pdm", "hatch") and len(tokens) >= 2 and tokens[1] == "run":
            tokens = tokens[2:]
            changed = True
        elif head_base in ("corepack", "npx", "pnpx", "bunx"):
            tokens = tokens[1:]
            changed = True
        elif head_base in ("python", "python3", "py") and len(tokens) >= 3 and tokens[1] == "-m":
            tokens = tokens[2:]
            changed = True

    if not tokens:
        return {"code": cleaned, "target_code": "", "meta": "", "simplified": False}

    cmd = Path(tokens[0]).name
    rest = tokens[1:]

    if cmd == "pytest":
        targets = _collect_positional_targets(
            rest,
            value_flags=_PYTEST_VALUE_FLAGS,
            bool_flags=_PYTEST_BOOL_FLAGS,
            skip_r_prefix=True,
        )
        return _format_targets_struct("pytest", targets, raw_cmd=cleaned)

    if cmd == "unittest":
        if rest and rest[0] == "discover":
            start_dir = ""
            i = 1
            while i < len(rest):
                tok = rest[i]
                if tok in ("-s", "--start-directory") and i + 1 < len(rest):
                    start_dir = rest[i + 1]
                    i += 2
                elif tok.startswith("--start-directory="):
                    start_dir = tok.split("=", 1)[1]
                    i += 1
                elif tok in ("-p", "--pattern", "-t", "--top-level-directory") and i + 1 < len(rest):
                    i += 2
                else:
                    i += 1
            code = f"unittest {start_dir}" if start_dir else "unittest discover"
            return {"code": code, "target_code": "", "meta": "", "simplified": code != cleaned}
        targets = _collect_positional_targets(
            rest,
            value_flags={"-k"},
            bool_flags={"-v", "--verbose", "-q", "--quiet", "-f", "--failfast", "-b", "--buffer", "-c", "--catch"},
        )
        return _format_targets_struct("unittest", targets, raw_cmd=cleaned)

    if cmd in ("pnpm", "npm", "yarn", "bun"):
        idx = 0
        script = ""
        while idx < len(rest):
            tok = rest[idx]
            if tok == "run" or tok in ("-s", "--silent", "--if-present", "-w", "--workspace-root"):
                idx += 1
            elif tok in ("-C", "--dir", "--prefix", "--filter"):
                idx += 2
            elif tok.startswith("-"):
                idx += 1
            else:
                script = tok
                idx += 1
                break
        if script:
            targets = _collect_positional_targets(
                rest[idx:],
                value_flags=_JS_VALUE_FLAGS,
                bool_flags=_JS_BOOL_FLAGS,
            )
            return _format_targets_struct(f"{cmd} {script}", targets, raw_cmd=cleaned)

    if cmd in ("vitest", "jest", "mocha"):
        args = rest[1:] if (cmd == "vitest" and rest and rest[0] == "run") else rest
        targets = _collect_positional_targets(
            args,
            value_flags=_JS_VALUE_FLAGS,
            bool_flags=_JS_BOOL_FLAGS,
        )
        return _format_targets_struct(cmd, targets, raw_cmd=cleaned)

    if cmd == "go" and rest and rest[0] == "test":
        targets = _collect_positional_targets(
            rest[1:],
            value_flags={"-run", "-skip", "-count", "-timeout", "-tags", "-coverprofile"},
            bool_flags={"-v", "-race", "-cover", "-short", "-json"},
        )
        return _format_targets_struct("go test", targets, raw_cmd=cleaned)

    if cmd == "cargo" and rest and rest[0] == "test":
        targets = _collect_positional_targets(
            rest[1:],
            value_flags={"-p", "--package", "--test", "--bin", "--features"},
            bool_flags={"--workspace", "--all-targets", "--lib", "--quiet", "-q", "--nocapture", "--"},
        )
        return _format_targets_struct("cargo test", targets, raw_cmd=cleaned)

    if tokens != cleaned.split() and len(tokens) == 1:
        return {"code": tokens[0], "target_code": "", "meta": "", "simplified": tokens[0] != cleaned}
    if len(cleaned) > 80 and len(tokens) >= 4:
        trailing_files: list[str] = []
        for tok in reversed(tokens):
            if _is_file_target(tok):
                trailing_files.append(tok)
            else:
                break
        if len(trailing_files) >= 3:
            prefix_tokens = tokens[: len(tokens) - len(trailing_files)]
            return {
                "code": " ".join(prefix_tokens),
                "target_code": "",
                "meta": f"{len(trailing_files)} 个文件",
                "simplified": True,
            }
    return {"code": cleaned, "target_code": "", "meta": "", "simplified": False}


def _format_part_markdown(part: dict[str, Any]) -> str:
    code = _wrap_inline_code(str(part.get("code", "")))
    target_code = str(part.get("target_code", ""))
    meta = str(part.get("meta", ""))
    if target_code:
        return f"{code}（{_wrap_inline_code(target_code)}）"
    if meta:
        return f"{code}（{meta}）"
    return code


def _format_part_plain(part: dict[str, Any]) -> str:
    code = str(part.get("code", ""))
    target_code = str(part.get("target_code", ""))
    meta = str(part.get("meta", ""))
    if target_code:
        return f"{code} ({target_code})"
    if meta:
        return f"{code} ({meta})"
    return code


@dataclass(frozen=True)
class _Verification:
    result: str
    markdown_label: str = ""
    plain_label: str = ""
    full_command: str = ""


def _verification(raw_cmd: str, result: str, note: str) -> _Verification:
    cleaned = raw_cmd.strip()
    if not cleaned:
        return _Verification(result)
    if " && " in cleaned:
        raw_parts = [_unwrap_inline_code(p) for p in cleaned.split(" && ") if p.strip()]
    else:
        raw_parts = [_unwrap_inline_code(cleaned)]
    raw_parts = [p for p in raw_parts if p]
    if not raw_parts:
        return _Verification(result)

    parts_struct = [_summarize_single_part_struct(p) for p in raw_parts]
    md_label = "、".join(_format_part_markdown(p) for p in parts_struct)
    plain_label = " && ".join(_format_part_plain(p) for p in parts_struct)
    if note:
        md_label = f"{md_label}（{note}）"
        plain_label = f"{plain_label} ({note})"
    clean_raw = " && ".join(raw_parts)
    simplified = any(bool(p.get("simplified")) for p in parts_struct)
    return _Verification(result, md_label, plain_label, clean_raw if simplified else "")


def _parse_test_entries(test_text: str) -> list[_Verification]:
    cleaned = test_text.strip()
    if not cleaned or cleaned in ("未记录", "未在提交中记录"):
        return [_Verification(cleaned or "未记录")]

    entries: list[_Verification] = []
    for seg in _split_test_segments(cleaned):
        if " — " in seg:
            raw_cmd, result = seg.split(" — ", 1)
            cmd, note = _unwrap_inline_code_with_note(raw_cmd)
            entries.append(_verification(cmd, result.strip(), note))
            continue

        trailing = _TRAILING_STATUS_RE.match(seg)
        if trailing:
            prefix, note = _unwrap_inline_code_with_note(trailing.group(1))
            status = trailing.group(2)
            if (
                prefix
                and re.search(r"[A-Za-z_./:-]", prefix)
                and prefix.lower() not in {"all", "tests", "all tests"}
                and not re.fullmatch(r"\d+(?:\s+\w+)?", prefix)
            ):
                entries.append(_verification(prefix, status, note))
                continue

        entries.append(_Verification(seg))
    return entries


def _format_test_summary_plain(entries: list[_Verification]) -> str:
    labels = [" — ".join(filter(None, (entry.plain_label, entry.result))) for entry in entries]
    if len(labels) == 1:
        return f"Test: {labels[0]}"
    return "\n".join(["Test:", *(f"- {label}" for label in labels)])


def _escape_md_table_cell(text: str) -> str:
    """Normalize newlines and escape pipe characters for GFM/GitLab Markdown table cells."""
    collapsed = re.sub(r"\s*\r?\n\s*", " ", text.strip())
    return collapsed.replace("|", "\\|")


def _format_change_item(tid: str, change: str, extra: str) -> str:
    """Format a compact task bullet with optional indented commit body notes."""
    head = f"- **{tid}** {change}"
    if not extra:
        return head
    indented = "\n".join(f"  {line}" if line else "" for line in extra.splitlines())
    return f"{head}\n\n{indented}"


def _format_plain_task_block(tid: str, change: str, extra: str, plain_test: str) -> str:
    """Format a compact zero-Markdown plain-text TASK block without internal blank lines."""
    lines = [f"{tid}: {change}"]
    if extra:
        lines.extend(line.rstrip() for line in extra.splitlines() if line.strip())
    if plain_test:
        lines.append(plain_test)
    return "\n".join(lines)


def build_issue_summaries(
    worktree: Path,
    issue_dir: str,
    issue_number: int | None,
    base_ref: str,
    issue_title: str | None = None,
    branch: str = "",
) -> tuple[str, str, str]:
    """Generate (suggested_title, pr_markdown_body, commit_plain_body) from TASKs and commits."""
    task_dir = worktree / "TASK" / issue_dir
    tasks: list[dict[str, Any]] = []
    if task_dir.is_dir():
        for path in sorted(task_dir.glob("TASK-*.md")):
            if task_status.is_task_record(path):
                parsed = task_status.read_task(path, worktree / "TASK")
                parsed["_details"] = _parse_task_markdown_details(path)
                tasks.append(parsed)

    commits = _collect_commit_task_records(worktree, issue_dir, base_ref)
    commit_by_task: dict[str, dict[str, Any]] = {}
    for rec in commits:
        if rec["task_id"]:
            commit_by_task[rec["task_id"]] = rec

    commit_types = [c["type"] for c in commits if c["type"] and c["type"] != "chore"]
    dominant_type = commit_types[0] if commit_types else "feat"

    first_change = ""
    change_items: list[str] = []
    has_extra_details = False
    verification_rows: list[str] = []
    plain_blocks: list[str] = []
    detailed_commands: list[tuple[str, str]] = []
    seen_commands: set[tuple[str, str]] = set()

    def _append_task_block(tid: str, change: str, extra: str, test_text: str) -> None:
        nonlocal has_extra_details
        change_items.append(_format_change_item(tid, change, extra))
        if extra:
            has_extra_details = True

        entries = _parse_test_entries(test_text)
        for idx, entry in enumerate(entries):
            task_cell = tid if idx == 0 else ""
            check_cell = _escape_md_table_cell(entry.markdown_label) or "—"
            result_cell = _escape_md_table_cell(entry.result) or "—"
            verification_rows.append(f"| {task_cell} | {check_cell} | {result_cell} |")
            raw_cmd = entry.full_command
            if raw_cmd:
                pair = (tid, raw_cmd)
                if pair not in seen_commands:
                    seen_commands.add(pair)
                    detailed_commands.append(pair)

        plain_test = _format_test_summary_plain(entries)
        plain_blocks.append(_format_plain_task_block(tid, change, extra, plain_test))

    if tasks:
        for task in tasks:
            tid = task["id"]
            commit_rec = commit_by_task.get(tid, {})
            details = task["_details"]
            raw_title = re.sub(rf"^{re.escape(tid)}[：:\s]+", "", task["title"]).strip()
            change = commit_rec.get("change") or raw_title or task["title"]
            if not first_change:
                first_change = change
            test_text = (
                commit_rec.get("test")
                or details.get("latest_result")
                or (f"{details['command']} — {details['outcome']}" if details.get("command") else "")
                or (
                    f"{task['test']} — {details['outcome'] or task['status']}"
                    if task.get("test") and task["test"] not in ("未记录", "未在提交中记录")
                    else "未记录"
                )
            )
            _append_task_block(tid, change, str(commit_rec.get("extra", "")), test_text)
    elif commits:
        for idx, rec in enumerate(commits, start=1):
            if rec["subject"].startswith("chore: 清理已汇总的任务记录"):
                continue
            tid = rec["task_id"] or f"TASK-{idx:02d}"
            change = rec["change"]
            if not first_change:
                first_change = change
            _append_task_block(tid, change, str(rec["extra"]), rec["test"] or "未在提交中记录")

    if issue_title:
        suggested_title = format_conventional_title(dominant_type, issue_title)
    elif len(tasks) == 1:
        only_change = first_change or issue_dir
        suggested_title = format_conventional_title(dominant_type, only_change)
    elif len(commits) == 1 and commits[0]["change"]:
        suggested_title = format_conventional_title(dominant_type, commits[0]["change"])
    else:
        suggested_title = f"{dominant_type}: 完成 {issue_dir}"

    if issue_number is not None and f"(#{issue_number})" not in suggested_title:
        suggested_title = f"{suggested_title} (#{issue_number})"

    header_lines = [f"Closes #{issue_number}"] if issue_number is not None else [f"Branch: {branch or issue_dir}"]
    header = "\n".join(header_lines)

    pr_parts = [header]
    if change_items:
        joiner = "\n\n" if has_extra_details else "\n"
        pr_parts.append("## 变更内容\n\n" + joiner.join(change_items))
    if verification_rows:
        table_lines = ["| 任务 | 验证项 | 结果 |", "| --- | --- | --- |", *verification_rows]
        pr_parts.append("## 验证记录\n\n" + "\n".join(table_lines))
    if detailed_commands:
        detail_lines = ["<details>", "<summary>完整验证命令</summary>", ""]
        for tid, raw_cmd in detailed_commands:
            detail_lines.append(f"- **{tid}:** {_wrap_inline_code(raw_cmd)}")
        detail_lines.extend(["", "</details>"])
        pr_parts.append("\n".join(detail_lines))

    commit_parts = [header]
    if plain_blocks:
        commit_parts.extend(plain_blocks)

    return suggested_title, "\n\n".join(pr_parts) + "\n", "\n\n".join(commit_parts) + "\n"
