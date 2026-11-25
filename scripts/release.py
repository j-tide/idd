#!/usr/bin/env python3
"""Version consistency check, release bump/tag helper, and release-notes generator."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from version import (  # noqa: E402
    REPO_ROOT,
    bump_semver,
    is_valid_semver,
    parse_readme_badge_version,
    parse_skill_version,
    replace_readme_badge_version,
    replace_skill_version,
)


CONVENTIONAL_RE = re.compile(r"^([a-z]+)(?:\([^)]*\))?!?\s*:\s*(.+)$", re.IGNORECASE)
RELEASE_COMMIT_RE = re.compile(r"^chore\(release\)\s*:", re.IGNORECASE)

SECTION_ORDER = (
    "### 新功能",
    "### 问题修复",
    "### 重构与优化",
    "### 文档与维护",
    "### 其他变更",
)

TYPE_TO_SECTION = {
    "feat": "### 新功能",
    "fix": "### 问题修复",
    "refactor": "### 重构与优化",
    "perf": "### 重构与优化",
    "docs": "### 文档与维护",
    "test": "### 文档与维护",
    "ci": "### 文档与维护",
    "chore": "### 文档与维护",
}


class ReleaseError(RuntimeError):
    """Expected release validation or git preflight error."""


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise ReleaseError(f"命令执行失败 `{' '.join(cmd)}`: {detail}")
    return proc


def _remote_url_to_https(raw_url: str) -> str | None:
    url = raw_url.strip().rstrip("/")
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url[:-4] if url.endswith(".git") else url
    ssh_scheme = re.match(r"^ssh://(?:[^@]+@)?([^:/]+)(?::\d+)?/(.+)$", url)
    if ssh_scheme:
        path = ssh_scheme.group(2).rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://{ssh_scheme.group(1)}/{path}"
    scp_like = re.match(r"^(?:[^@]+@)?([^:]+):(.+)$", url)
    if scp_like:
        path = scp_like.group(2).rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://{scp_like.group(1)}/{path}"
    return None


def _get_origin_https_url(repo_root: Path) -> str | None:
    proc = _run(["git", "-C", str(repo_root), "remote", "get-url", "origin"], cwd=repo_root, check=False)
    if proc.returncode != 0:
        return None
    return _remote_url_to_https(proc.stdout)


def _git_ref_exists(repo_root: Path, ref: str) -> bool:
    proc = _run(["git", "-C", str(repo_root), "rev-parse", "-q", "--verify", ref], cwd=repo_root, check=False)
    return proc.returncode == 0


def _git_rev_parse(repo_root: Path, ref: str) -> str:
    return _run(["git", "-C", str(repo_root), "rev-parse", ref], cwd=repo_root).stdout.strip()


def run_check(
    repo_root: Path,
    *,
    expect_tag: str | None = None,
    skip_cli_check: bool = False,
) -> str:
    """Validate version consistency across `SKILL.md`, `README.md`, CLI, and optional tag."""
    skill_path = repo_root / "SKILL.md"
    readme_path = repo_root / "README.md"

    try:
        skill_ver = parse_skill_version(skill_path)
    except (OSError, ValueError) as exc:
        raise ReleaseError(str(exc)) from exc

    try:
        readme_ver = parse_readme_badge_version(readme_path)
    except (OSError, ValueError) as exc:
        raise ReleaseError(str(exc)) from exc

    if skill_ver != readme_ver:
        raise ReleaseError(
            f"版本不一致：SKILL.md ({skill_ver}) != README.md 徽章 ({readme_ver})。"
        )

    checked_parts = ["SKILL.md", "README.md"]

    if not skip_cli_check:
        idd_bin = repo_root / "scripts" / "idd"
        if not idd_bin.is_file():
            raise ReleaseError(f"缺少 CLI 入口文件：{idd_bin}")
        env = dict(os.environ)
        env["IDD_NO_AUTO_UPDATE"] = "1"
        proc = _run([sys.executable, "-B", str(idd_bin), "--version"], cwd=repo_root, env=env)
        cli_output = proc.stdout.strip()
        expected_cli = f"idd {skill_ver}"
        if cli_output != expected_cli:
            raise ReleaseError(
                f"版本不一致：scripts/idd --version 输出 `{cli_output}`，预期 `{expected_cli}`。"
            )
        checked_parts.append("idd --version")

    if expect_tag is not None:
        if not expect_tag.startswith("v"):
            raise ReleaseError(f"预期 Tag `{expect_tag}` 必须以 `v` 开头（例如 v{skill_ver}）。")
        tag_ver = expect_tag[1:]
        if not is_valid_semver(tag_ver):
            raise ReleaseError(f"预期 Tag `{expect_tag}` 不是合法的 SemVer 标签。")
        if tag_ver != skill_ver:
            raise ReleaseError(
                f"版本不一致：Tag {expect_tag} ({tag_ver}) != SKILL.md ({skill_ver})。"
            )
        checked_parts.append(f"tag {expect_tag}")

    print(f"版本一致性校验通过：v{skill_ver} ({' == '.join(checked_parts)})")
    return skill_ver


def _find_previous_semver_tag(repo_root: Path, target_ref: str, exclude_tags: set[str]) -> str | None:
    proc = _run(
        ["git", "-C", str(repo_root), "tag", "--merged", target_ref, "--sort=-v:refname", "v*"],
        cwd=repo_root,
        check=False,
    )
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        tag = line.strip()
        if not tag or tag in exclude_tags:
            continue
        if tag.startswith("v") and is_valid_semver(tag[1:]):
            return tag
    return None


def generate_release_notes(repo_root: Path, tag_arg: str) -> str:
    """Generate grouped Markdown release notes from Conventional Commits."""
    requested_tag = tag_arg.strip()
    exclude_tags: set[str] = set()

    if requested_tag:
        label = requested_tag
        exclude_tags.add(requested_tag)
        target_ref = requested_tag if _git_ref_exists(repo_root, f"refs/tags/{requested_tag}") else "HEAD"
    else:
        target_ref = "HEAD"
        head_sha = _git_rev_parse(repo_root, "HEAD")
        current_tag: str | None = None
        try:
            current_ver = parse_skill_version(repo_root / "SKILL.md")
            candidate = f"v{current_ver}"
            if _git_ref_exists(repo_root, f"refs/tags/{candidate}"):
                if _git_rev_parse(repo_root, f"refs/tags/{candidate}") == head_sha:
                    exclude_tags.add(candidate)
                    label = candidate
                else:
                    label = "HEAD"
            else:
                label = candidate
            current_tag = candidate
        except (OSError, ValueError):
            label = "HEAD"
        _ = current_tag

    prev_tag = _find_previous_semver_tag(repo_root, target_ref, exclude_tags)
    rev_range = f"{prev_tag}..{target_ref}" if prev_tag else target_ref

    log_proc = _run(
        ["git", "-C", str(repo_root), "log", "--format=%h%x00%s", rev_range],
        cwd=repo_root,
    )

    sections: dict[str, list[str]] = {name: [] for name in SECTION_ORDER}
    for raw in log_proc.stdout.splitlines():
        if "\x00" not in raw:
            continue
        short_sha, subject = raw.split("\x00", 1)
        subject = subject.strip()
        if not subject or RELEASE_COMMIT_RE.match(subject):
            continue
        m = CONVENTIONAL_RE.match(subject)
        commit_type = m.group(1).lower() if m else ""
        section = TYPE_TO_SECTION.get(commit_type, "### 其他变更")
        sections[section].append(f"- {subject} ({short_sha.strip()})")

    blocks: list[str] = []
    for heading in SECTION_ORDER:
        items = sections[heading]
        if items:
            blocks.append(f"{heading}\n" + "\n".join(items))

    if not blocks:
        blocks.append("### 其他变更\n- 维护性发布，无其他功能变更。")

    https_url = _get_origin_https_url(repo_root)
    if https_url:
        if prev_tag:
            blocks.append(f"**Full Changelog**: {https_url}/compare/{prev_tag}...{label}")
        else:
            blocks.append(f"**Full Changelog**: {https_url}/commits/{label}")

    return "\n\n".join(blocks) + "\n"


def _preflight_tag(repo_root: Path, tag_name: str) -> None:
    _run(["git", "-C", str(repo_root), "rev-parse", "--git-dir"], cwd=repo_root)
    branch = _run(["git", "-C", str(repo_root), "branch", "--show-current"], cwd=repo_root).stdout.strip()
    if branch != "main":
        raise ReleaseError(f"执行 `--tag` 需要位于 `main` 分支，当前为 `{branch or '(detached)'}`。")
    status = _run(["git", "-C", str(repo_root), "status", "--porcelain"], cwd=repo_root).stdout.strip()
    if status:
        raise ReleaseError("工作区存在未提交改动，请先清理或提交后再执行 `--tag`。")
    if _git_ref_exists(repo_root, f"refs/tags/{tag_name}"):
        raise ReleaseError(f"Tag `{tag_name}` 已存在，已中止。")


def run_bump(
    repo_root: Path,
    target: str,
    *,
    create_tag: bool,
    push: bool,
    dry_run: bool,
    no_test: bool,
) -> int:
    """Bump version in `SKILL.md` and `README.md`, optionally test, commit, tag, and push."""
    skill_path = repo_root / "SKILL.md"
    readme_path = repo_root / "README.md"

    try:
        current_ver = parse_skill_version(skill_path)
        new_ver = bump_semver(current_ver, target)
    except (OSError, ValueError) as exc:
        raise ReleaseError(str(exc)) from exc

    if new_ver == current_ver:
        raise ReleaseError(f"目标版本与当前版本相同：v{current_ver}")

    try:
        skill_orig = skill_path.read_bytes().decode("utf-8")
        readme_orig = readme_path.read_bytes().decode("utf-8")
        skill_new = replace_skill_version(skill_orig, new_ver)
        readme_new = replace_readme_badge_version(readme_orig, new_ver)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseError(str(exc)) from exc

    tag_name = f"v{new_ver}"
    if create_tag:
        _preflight_tag(repo_root, tag_name)

    if dry_run:
        lines = [
            f"[dry-run] 版本将更新：v{current_ver} -> v{new_ver}",
            "将修改文件：SKILL.md, README.md",
        ]
        if create_tag:
            lines.append(f"将创建提交：chore(release): {tag_name}")
            lines.append(f"将创建注释标签：{tag_name}")
            if push:
                lines.append(f"将推送到远端：git push origin main {tag_name}")
        print("\n".join(lines))
        return 0

    skill_path.write_bytes(skill_new.encode("utf-8"))
    readme_path.write_bytes(readme_new.encode("utf-8"))

    if not no_test:
        env = dict(os.environ)
        env["IDD_NO_AUTO_UPDATE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        test_proc = _run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
            cwd=repo_root,
            check=False,
            env=env,
        )
        if test_proc.returncode != 0:
            skill_path.write_bytes(skill_orig.encode("utf-8"))
            readme_path.write_bytes(readme_orig.encode("utf-8"))
            output = "\n".join(part for part in (test_proc.stdout.strip(), test_proc.stderr.strip()) if part)
            raise ReleaseError(f"单元测试未通过，已自动回滚 SKILL.md 与 README.md：\n{output}")

    if create_tag:
        _run(["git", "-C", str(repo_root), "add", "SKILL.md", "README.md"], cwd=repo_root)
        _run(["git", "-C", str(repo_root), "commit", "-m", f"chore(release): {tag_name}"], cwd=repo_root)
        _run(["git", "-C", str(repo_root), "tag", "-a", tag_name, "-m", f"Release {tag_name}"], cwd=repo_root)
        if push:
            _run(["git", "-C", str(repo_root), "push", "origin", "main", tag_name], cwd=repo_root)
            print(f"已发布版本 {tag_name} 并推送到 origin/main。")
        else:
            print(f"已提交并打标签 {tag_name}。\n下一步执行：`git push origin main {tag_name}`")
    else:
        print(f"已更新版本：v{current_ver} -> v{new_ver}（SKILL.md, README.md）")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="IDD 版本一致性校验、版本递增与 GitHub Release 日志生成工具",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="递增类型（patch / minor / major）或目标版本号（如 0.6.0 / v0.6.0）",
    )
    parser.add_argument("--check", action="store_true", help="校验 SKILL.md、README.md 与 idd --version 是否一致")
    parser.add_argument("--expect-tag", default=None, help="配合 --check 验证期望的 Git Tag（如 v0.5.0）")
    parser.add_argument("--skip-cli-check", action="store_true", help="在 --check 时跳过调用 scripts/idd --version")
    parser.add_argument(
        "--notes",
        nargs="?",
        const="",
        default=None,
        metavar="TAG",
        help="按 Conventional Commits 生成 Markdown Release Notes",
    )
    parser.add_argument("--tag", action="store_true", help="跑完测试后自动提交 SKILL.md/README.md 并打注释 Tag")
    parser.add_argument("--push", action="store_true", help="配合 --tag 自动执行 `git push origin main vX.Y.Z`")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更，不写入文件或执行 Git 变更")
    parser.add_argument("--no-test", action="store_true", help="跳过单元测试")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    active_modes = int(bool(args.check)) + int(args.notes is not None) + int(args.target is not None)
    if active_modes > 1:
        print("错误：`--check`、`--notes` 与版本递增参数互斥，请分开执行。", file=sys.stderr)
        return 2
    if active_modes == 0:
        parser.print_usage(sys.stderr)
        return 2

    if args.expect_tag is not None and not args.check:
        print("错误：`--expect-tag` 只能与 `--check` 一起使用。", file=sys.stderr)
        return 2
    if args.push and not args.tag:
        print("错误：`--push` 只能与 `--tag` 一起使用。", file=sys.stderr)
        return 2
    if args.target is None and (args.tag or args.dry_run or args.no_test):
        print("错误：`--tag`、`--dry-run`、`--no-test` 需要指定版本递增目标（如 minor 或 0.6.0）。", file=sys.stderr)
        return 2

    try:
        if args.check:
            run_check(repo_root, expect_tag=args.expect_tag, skip_cli_check=args.skip_cli_check)
            return 0
        if args.notes is not None:
            print(generate_release_notes(repo_root, args.notes), end="")
            return 0
        return run_bump(
            repo_root,
            args.target,
            create_tag=args.tag,
            push=args.push,
            dry_run=args.dry_run,
            no_test=args.no_test,
        )
    except ReleaseError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
