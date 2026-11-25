"""Tests for single-source-of-truth versioning, `scripts/release.py`, and upgrade version output."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import idd_cli  # noqa: E402
import version as idd_version  # noqa: E402


RELEASE_PY = SCRIPTS_DIR / "release.py"
IDD_BIN = SCRIPTS_DIR / "idd"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_temp_release_repo(root: Path, initial_ver: str = "0.5.0") -> tuple[Path, Path]:
    origin = root / "origin.git"
    repo = root / "repo"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
    _git(repo, "checkout", "-B", "main")
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.com")

    (repo / "SKILL.md").write_text(
        f"---\nname: idd\ndescription: demo\nmetadata:\n  version: \"{initial_ver}\"\n---\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        f"[![Version](https://img.shields.io/badge/version-v{initial_ver}-10b981?style=flat-square)](https://github.com/j-tide/idd/releases)\n",
        encoding="utf-8",
    )
    (repo / "README.zh-CN.md").write_text(
        f"[![Version](https://img.shields.io/badge/version-v{initial_ver}-10b981?style=flat-square)](https://github.com/j-tide/idd/releases)\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_sample.py").write_text(
        "import unittest\n\nclass SampleTest(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: initialize repository")
    _git(repo, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    return origin, repo


class TestVersionAndRelease(unittest.TestCase):
    def test_repo_version_consistency(self) -> None:
        skill_ver = idd_version.parse_skill_version()
        readme_ver = idd_version.parse_readme_badge_version()
        zh_path = REPO_ROOT / "README.zh-CN.md"
        self.assertTrue(zh_path.is_file())
        readme_zh_ver = idd_version.parse_readme_badge_version(zh_path)
        self.assertEqual(skill_ver, idd_cli.__version__)
        self.assertEqual(skill_ver, readme_ver)
        self.assertEqual(skill_ver, readme_zh_ver)

        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh_text = zh_path.read_text(encoding="utf-8")
        self.assertIn("](https://github.com/j-tide/idd/releases)", readme_text)
        self.assertIn("](https://github.com/j-tide/idd/releases)", readme_zh_text)

        env = dict(os.environ)
        env["IDD_NO_AUTO_UPDATE"] = "1"
        cli_res = subprocess.run(
            [sys.executable, "-B", str(IDD_BIN), "--version"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(cli_res.stdout.strip(), f"idd {skill_ver}")

        check_res = subprocess.run(
            [sys.executable, "-B", str(RELEASE_PY), "--check", "--expect-tag", f"v{skill_ver}"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f"v{skill_ver}", check_res.stdout)

        bad_tag = subprocess.run(
            [sys.executable, "-B", str(RELEASE_PY), "--check", "--expect-tag", "v99.99.99"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(bad_tag.returncode, 0)
        self.assertIn("版本不一致", bad_tag.stderr)

    def test_semver_parsing_bumping_and_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_path = Path(tmp) / "SKILL.md"
            crlf_text = (
                "---\r\n"
                "name: idd\r\n"
                "version: '9.9.9'\r\n"
                "metadata:\r\n"
                "  author:\r\n"
                "    version: \"8.8.8\"\r\n"
                "  version: '0.5.0'  # keep comment\r\n"
                "---\r\n"
            )
            skill_path.write_bytes(crlf_text.encode("utf-8"))
            self.assertEqual(idd_version.parse_skill_version(skill_path), "0.5.0")

            updated_skill = idd_version.replace_skill_version(crlf_text, "0.6.0-rc.1")
            self.assertIn("version: '9.9.9'\r\n", updated_skill)
            self.assertIn("    version: \"8.8.8\"\r\n", updated_skill)
            self.assertIn("  version: '0.6.0-rc.1'  # keep comment\r\n", updated_skill)
            skill_path.write_bytes(updated_skill.encode("utf-8"))
            self.assertEqual(idd_version.parse_skill_version(skill_path), "0.6.0-rc.1")

            unquoted_skill = Path(tmp) / "SKILL_unquoted.md"
            unquoted_skill.write_text("---\nmetadata:\n  version: 1.2.3\n---\n", encoding="utf-8")
            self.assertEqual(idd_version.parse_skill_version(unquoted_skill), "1.2.3")
            self.assertIn(
                "  version: 1.2.4\n",
                idd_version.replace_skill_version(unquoted_skill.read_text(encoding="utf-8"), "1.2.4"),
            )

            missing_meta = Path(tmp) / "BAD.md"
            missing_meta.write_text("---\nname: idd\n---\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                idd_version.parse_skill_version(missing_meta)

            readme_path = Path(tmp) / "README.md"
            readme_path.write_text(
                "[![Version](https://img.shields.io/badge/version-v0.5.0-10b981?style=flat-square)](https://github.com/j-tide/idd/releases)\n",
                encoding="utf-8",
            )
            updated_readme = idd_version.replace_readme_badge_version(
                readme_path.read_text(encoding="utf-8"),
                "0.6.0-rc.1",
            )
            self.assertIn("version-v0.6.0--rc.1-10b981?style=flat-square", updated_readme)
            readme_path.write_text(updated_readme, encoding="utf-8")
            self.assertEqual(idd_version.parse_readme_badge_version(readme_path), "0.6.0-rc.1")

        self.assertEqual(idd_version.bump_semver("0.5.0", "patch"), "0.5.1")
        self.assertEqual(idd_version.bump_semver("0.5.0", "minor"), "0.6.0")
        self.assertEqual(idd_version.bump_semver("0.5.0", "major"), "1.0.0")
        self.assertEqual(idd_version.bump_semver("0.6.0-rc.1", "patch"), "0.6.0")
        self.assertEqual(idd_version.bump_semver("0.5.0", "v0.7.0-alpha.1"), "0.7.0-alpha.1")
        with self.assertRaises(ValueError):
            idd_version.bump_semver("0.5.0", "invalid-ver")
        with self.assertRaises(ValueError):
            idd_version.bump_semver("bad", "patch")

    def test_release_script_dry_run_bump_tag_rollback_and_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo = _init_temp_release_repo(Path(tmp), "0.5.0")
            env = dict(os.environ)
            env["IDD_NO_AUTO_UPDATE"] = "1"

            def run_rel(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-B", str(RELEASE_PY), "--repo-root", str(repo), *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=check,
                )

            # Flag conflict guards
            self.assertEqual(run_rel("--check", "minor", check=False).returncode, 2)
            self.assertEqual(run_rel("--push", "minor", check=False).returncode, 2)
            self.assertEqual(run_rel("--expect-tag", "v0.5.0", "minor", check=False).returncode, 2)
            self.assertNotEqual(run_rel("0.5.0", check=False).returncode, 0)

            # Dry-run makes no changes
            dry = run_rel("minor", "--tag", "--dry-run")
            self.assertIn("v0.5.0 -> v0.6.0", dry.stdout)
            self.assertEqual(idd_version.parse_skill_version(repo / "SKILL.md"), "0.5.0")
            self.assertEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")

            # Dirty tree rejected before touching files
            (repo / "dirty.txt").write_text("wip\n", encoding="utf-8")
            dirty_res = run_rel("minor", "--tag", check=False)
            self.assertNotEqual(dirty_res.returncode, 0)
            self.assertIn("未提交改动", dirty_res.stderr)
            (repo / "dirty.txt").unlink()

            # Non-main branch rejected before touching files
            _git(repo, "checkout", "-b", "feat/1-other")
            branch_res = run_rel("minor", "--tag", check=False)
            self.assertNotEqual(branch_res.returncode, 0)
            self.assertIn("main", branch_res.stderr)
            _git(repo, "checkout", "main")

            # Rollback SKILL.md and README.md when tests fail during --tag
            fail_test = repo / "tests" / "test_fail.py"
            fail_test.write_text(
                "import unittest\n\nclass FailTest(unittest.TestCase):\n    def test_fail(self):\n        self.fail('boom')\n",
                encoding="utf-8",
            )
            _git(repo, "add", "tests/test_fail.py")
            _git(repo, "commit", "-m", "test: add failing test")
            fail_tag = run_rel("patch", "--tag", check=False)
            self.assertNotEqual(fail_tag.returncode, 0)
            self.assertIn("已自动回滚", fail_tag.stderr)
            self.assertEqual(idd_version.parse_skill_version(repo / "SKILL.md"), "0.5.0")
            self.assertEqual(idd_version.parse_readme_badge_version(repo / "README.md"), "0.5.0")
            self.assertEqual(idd_version.parse_readme_badge_version(repo / "README.zh-CN.md"), "0.5.0")
            self.assertEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")

            # Remove failing test and run successful --tag
            _git(repo, "rm", "tests/test_fail.py")
            _git(repo, "commit", "-m", "test: remove failing test")

            tag_res = run_rel("minor", "--tag")
            self.assertIn("v0.6.0", tag_res.stdout)
            self.assertIn("git push origin main v0.6.0", tag_res.stdout)
            self.assertEqual(idd_version.parse_skill_version(repo / "SKILL.md"), "0.6.0")
            self.assertEqual(idd_version.parse_readme_badge_version(repo / "README.md"), "0.6.0")
            self.assertEqual(idd_version.parse_readme_badge_version(repo / "README.zh-CN.md"), "0.6.0")
            self.assertEqual(_git(repo, "log", "-1", "--format=%s").stdout.strip(), "chore(release): v0.6.0")
            self.assertEqual(_git(repo, "tag", "-l", "v0.6.0").stdout.strip(), "v0.6.0")

            # Duplicate tag rejected
            dup_res = run_rel("0.6.0", "--tag", check=False)
            self.assertNotEqual(dup_res.returncode, 0)

            # --tag --push pushes both main and tag to origin
            push_res = run_rel("patch", "--tag", "--push")
            self.assertIn("v0.6.1", push_res.stdout)
            remote_tags = _git(repo, "ls-remote", "--tags", "origin", "v0.6.1").stdout
            self.assertIn("refs/tags/v0.6.1", remote_tags)

            # --check catches README.zh-CN.md drift
            zh_orig = (repo / "README.zh-CN.md").read_text(encoding="utf-8")
            (repo / "README.zh-CN.md").write_text(
                idd_version.replace_readme_badge_version(zh_orig, "0.9.9"),
                encoding="utf-8",
            )
            drift_res = run_rel("--check", "--skip-cli-check", check=False)
            self.assertNotEqual(drift_res.returncode, 0)
            self.assertIn("README.zh-CN.md", drift_res.stderr)
            (repo / "README.zh-CN.md").write_text(zh_orig, encoding="utf-8")

            # Plain bump without --tag updates files only
            plain_res = run_rel("major", "--no-test")
            self.assertIn("v0.6.1 -> v1.0.0", plain_res.stdout)
            self.assertEqual(idd_version.parse_skill_version(repo / "SKILL.md"), "1.0.0")
            self.assertEqual(idd_version.parse_readme_badge_version(repo / "README.md"), "1.0.0")
            self.assertEqual(idd_version.parse_readme_badge_version(repo / "README.zh-CN.md"), "1.0.0")
            self.assertNotEqual(_git(repo, "status", "--porcelain").stdout.strip(), "")

    def test_release_notes_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo = _init_temp_release_repo(Path(tmp), "0.5.0")
            _git(repo, "remote", "set-url", "origin", "git@github.com:j-tide/idd.git")

            def commit_msg(filename: str, msg: str) -> None:
                (repo / filename).write_text(f"{msg}\n", encoding="utf-8")
                _git(repo, "add", filename)
                _git(repo, "commit", "-m", msg)

            commit_msg("a.txt", "fix(cli): repair edge crash")
            commit_msg("b.txt", "refactor: simplify version parser")
            commit_msg("c.txt", "docs: update workflow guide")
            commit_msg("d.txt", "misc unprefixed change")
            commit_msg("e.txt", "chore(release): v0.5.0")
            _git(repo, "tag", "-a", "v0.5.0", "-m", "Release v0.5.0")

            env = dict(os.environ)
            env["IDD_NO_AUTO_UPDATE"] = "1"
            notes_050 = subprocess.run(
                [sys.executable, "-B", str(RELEASE_PY), "--repo-root", str(repo), "--notes", "v0.5.0"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("### 新功能", notes_050)
            self.assertIn("### 问题修复", notes_050)
            self.assertIn("### 重构与优化", notes_050)
            self.assertIn("### 文档与维护", notes_050)
            self.assertIn("### 其他变更", notes_050)
            self.assertNotIn("chore(release):", notes_050)
            self.assertIn("**Full Changelog**: https://github.com/j-tide/idd/commits/v0.5.0", notes_050)

            commit_msg("f.txt", "feat: add release helper")
            commit_msg("g.txt", "fix: guard tag preflight")
            commit_msg("h.txt", "chore(release): v0.6.0")
            _git(repo, "tag", "-a", "v0.6.0", "-m", "Release v0.6.0")

            notes_060 = subprocess.run(
                [sys.executable, "-B", str(RELEASE_PY), "--repo-root", str(repo), "--notes", "v0.6.0"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("feat: add release helper", notes_060)
            self.assertIn("fix: guard tag preflight", notes_060)
            self.assertNotIn("repair edge crash", notes_060)
            self.assertNotIn("chore(release):", notes_060)
            self.assertIn("**Full Changelog**: https://github.com/j-tide/idd/compare/v0.5.0...v0.6.0", notes_060)

    def test_upgrade_reports_version_transition_when_skill_md_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            skill_origin = tmp_path / "skill_origin.git"
            skill_repo = tmp_path / "skill_repo"
            upstream = tmp_path / "upstream"
            cache_dir = tmp_path / "cache"

            subprocess.run(["git", "init", "--bare", "-b", "main", str(skill_origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(skill_origin), str(skill_repo)], check=True, capture_output=True)
            _git(skill_repo, "checkout", "-B", "main")
            _git(skill_repo, "config", "user.name", "Tester")
            _git(skill_repo, "config", "user.email", "test@example.com")
            (skill_repo / "SKILL.md").write_text("---\nname: idd\nmetadata:\n  version: \"0.5.0\"\n---\n", encoding="utf-8")
            (skill_repo / "scripts").mkdir()
            shutil.copy2(IDD_BIN, skill_repo / "scripts" / "idd")
            _git(skill_repo, "add", ".")
            _git(skill_repo, "commit", "-m", "feat: v0.5.0")
            _git(skill_repo, "push", "-u", "origin", "main")
            subprocess.run(
                ["git", "--git-dir", str(skill_origin), "symbolic-ref", "HEAD", "refs/heads/main"],
                check=True,
                capture_output=True,
            )

            subprocess.run(["git", "clone", str(skill_origin), str(upstream)], check=True, capture_output=True)
            _git(upstream, "config", "user.name", "Upstream")
            _git(upstream, "config", "user.email", "up@example.com")
            (upstream / "SKILL.md").write_text("---\nname: idd\nmetadata:\n  version: \"0.6.0\"\n---\n", encoding="utf-8")
            _git(upstream, "add", "SKILL.md")
            _git(upstream, "commit", "-m", "chore(release): v0.6.0")
            _git(upstream, "push", "origin", "main")

            env = dict(os.environ)
            env["IDD_SKILL_DIR"] = str(skill_repo)
            env["IDD_CACHE_DIR"] = str(cache_dir)
            env["IDD_NO_AUTO_UPDATE"] = "1"

            res = subprocess.run(
                [sys.executable, "-B", str(IDD_BIN), "upgrade"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("v0.5.0 → v0.6.0", res.stdout)
            self.assertEqual(idd_version.parse_skill_version(skill_repo / "SKILL.md"), "0.6.0")


if __name__ == "__main__":
    unittest.main()
