#!/usr/bin/env python3
"""Single source of truth for IDD version parsing, validation, and bumping."""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD_PATH = REPO_ROOT / "SKILL.md"
README_MD_PATH = REPO_ROOT / "README.md"
FALLBACK_VERSION = "0.0.0-dev"

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

README_BADGE_RE = re.compile(
    r"(\[!\[Version\]\(https://img\.shields\.io/badge/version-v)"
    r"((?:[0-9A-Za-z.+%]|--)+)"
    r"(-[0-9A-Za-z]+\?style=flat-square\)\]\()"
    r"([^)]+)"
    r"(\))"
)


def is_valid_semver(version: str) -> bool:
    """Return True if `version` is a valid Semantic Versioning string."""
    return isinstance(version, str) and bool(SEMVER_RE.fullmatch(version))


def encode_shields_version(version: str) -> str:
    """Encode hyphens for shields.io badge URLs (`-` -> `--`)."""
    return version.replace("-", "--")


def decode_shields_version(raw: str) -> str:
    """Decode shields.io escaped hyphens (`--` -> `-`)."""
    return raw.replace("--", "-")


def bump_semver(current: str, target: str) -> str:
    """Compute next SemVer from `current` given `patch`/`minor`/`major` or explicit version."""
    m = SEMVER_RE.fullmatch(current)
    if not m:
        raise ValueError(f"无效的当前版本号: {current!r}")

    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    has_prerelease = "-" in current.split("+", 1)[0]
    norm = target.strip()

    if norm == "major":
        return f"{major + 1}.0.0"
    if norm == "minor":
        return f"{major}.{minor + 1}.0"
    if norm == "patch":
        if has_prerelease:
            return f"{major}.{minor}.{patch}"
        return f"{major}.{minor}.{patch + 1}"

    candidate = norm[1:] if norm.startswith("v") else norm
    if not is_valid_semver(candidate):
        raise ValueError(f"无效的目标版本号或递增类型: {target!r}")
    return candidate


def _split_yaml_scalar(raw: str) -> tuple[str, str, str]:
    """Parse `(value, quote_char, trailing)` from a YAML scalar field value."""
    m_double = re.match(r'^"([^"]*)"(\s*(?:#.*)?)$', raw)
    if m_double:
        return m_double.group(1), '"', m_double.group(2)
    m_single = re.match(r"^'([^']*)'(\s*(?:#.*)?)$", raw)
    if m_single:
        return m_single.group(1), "'", m_single.group(2)
    m_unquoted = re.match(r"^([^\s#]+)(\s*(?:#.*)?)$", raw)
    if m_unquoted:
        return m_unquoted.group(1), "", m_unquoted.group(2)
    raise ValueError(f"无法解析 YAML 标量版本号: {raw!r}")


def _find_skill_version_line(lines: list[str]) -> tuple[int, str, str, str, str, str]:
    """Locate `metadata.version` inside YAML frontmatter.

    Returns `(line_index, prefix, value, quote_char, trailing, eol)`.
    """
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("SKILL.md 缺少起始 YAML frontmatter 分隔符 '---'")

    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].rstrip("\r\n") == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("SKILL.md 缺少结束 YAML frontmatter 分隔符 '---'")

    in_metadata = False
    metadata_child_indent: int | None = None

    for idx in range(1, end_idx):
        raw_line = lines[idx]
        eol = "\r\n" if raw_line.endswith("\r\n") else ("\n" if raw_line.endswith("\n") else "")
        content = raw_line[:-len(eol)] if eol else raw_line
        stripped = content.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(content) - len(stripped)
        if indent == 0:
            if re.match(r"^metadata\s*:\s*(?:#.*)?$", content):
                in_metadata = True
                metadata_child_indent = None
            else:
                in_metadata = False
                metadata_child_indent = None
            continue

        if not in_metadata:
            continue

        if metadata_child_indent is None:
            metadata_child_indent = indent
        elif indent < metadata_child_indent:
            # Indented key shallower than earlier child key; treat as direct child.
            metadata_child_indent = indent

        if indent != metadata_child_indent:
            continue

        vm = re.match(r"^(\s*version\s*:\s*)(.*)$", content)
        if vm:
            value, quote_char, trailing = _split_yaml_scalar(vm.group(2))
            return idx, vm.group(1), value, quote_char, trailing, eol

    raise ValueError("SKILL.md frontmatter 中未找到 metadata.version")


def parse_skill_version(skill_md: Path = SKILL_MD_PATH) -> str:
    """Read and validate `metadata.version` from `SKILL.md`."""
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    _, _, value, _, _, _ = _find_skill_version_line(lines)
    if not is_valid_semver(value):
        raise ValueError(f"SKILL.md metadata.version 不是合法 SemVer: {value!r}")
    return value


def get_version(skill_md: Path = SKILL_MD_PATH, *, fallback: str = FALLBACK_VERSION) -> str:
    """Return `SKILL.md` version, falling back safely if missing or invalid."""
    try:
        return parse_skill_version(skill_md)
    except (OSError, ValueError):
        return fallback


def parse_readme_badge_version(readme_md: Path = README_MD_PATH) -> str:
    """Read and validate the version badge from `README.md`."""
    text = readme_md.read_text(encoding="utf-8")
    m = README_BADGE_RE.search(text)
    if not m:
        raise ValueError("README.md 中未找到版本徽章")
    version = decode_shields_version(m.group(2))
    if not is_valid_semver(version):
        raise ValueError(f"README.md 版本徽章不是合法 SemVer: {version!r}")
    return version


def replace_skill_version(text: str, new_version: str) -> str:
    """Return updated `SKILL.md` text with `metadata.version` set to `new_version`."""
    if not is_valid_semver(new_version):
        raise ValueError(f"无效的 SemVer 版本号: {new_version!r}")
    lines = text.splitlines(keepends=True)
    idx, prefix, _, quote_char, trailing, eol = _find_skill_version_line(lines)
    quote = quote_char if quote_char in ('"', "'", "") else '"'
    lines[idx] = f"{prefix}{quote}{new_version}{quote}{trailing}{eol}"
    return "".join(lines)


def replace_readme_badge_version(text: str, new_version: str) -> str:
    """Return updated `README.md` text with version badge set to `new_version`."""
    if not is_valid_semver(new_version):
        raise ValueError(f"无效的 SemVer 版本号: {new_version!r}")
    if not README_BADGE_RE.search(text):
        raise ValueError("README.md 中未找到版本徽章")
    encoded = encode_shields_version(new_version)
    return README_BADGE_RE.sub(
        lambda m: f"{m.group(1)}{encoded}{m.group(3)}{m.group(4)}{m.group(5)}",
        text,
        count=1,
    )
