"""End-to-end tests for `install.sh` and `idd uninstall` using isolated temp HOME and bare git repos."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _create_bare_idd_origin(root: Path) -> tuple[Path, Path]:
    """Create a bare git origin containing the real `SKILL.md`, `install.sh`, and `scripts/`."""
    origin = root / "idd-origin.git"
    seed = root / "idd-seed"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    _git(seed, "checkout", "-B", "main")
    _git(seed, "config", "user.name", "Tester")
    _git(seed, "config", "user.email", "tester@example.com")

    shutil.copy2(REPO_ROOT / ".gitignore", seed / ".gitignore")
    shutil.copy2(REPO_ROOT / "SKILL.md", seed / "SKILL.md")
    shutil.copy2(INSTALL_SH, seed / "install.sh")
    shutil.copytree(REPO_ROOT / "scripts", seed / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "feat: initial seed")
    _git(seed, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    return origin, seed


def _isolated_env(home_dir: Path, *, extra_path: str | None = None) -> dict[str, str]:
    env = {
        "HOME": str(home_dir),
        "PATH": extra_path if extra_path is not None else os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    for key in ("TMPDIR", "USER", "LOGNAME"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class TestInstallAndUninstall(unittest.TestCase):
    def test_install_sh_syntax_and_fresh_install(self) -> None:
        syntax = subprocess.run(["sh", "-n", str(INSTALL_SH)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            origin, _ = _create_bare_idd_origin(tmp_path)
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            bin_dir = home_dir / ".local" / "bin"

            env = _isolated_env(home_dir)
            env["IDD_REPO_URL"] = origin.as_uri()
            res = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            self.assertIn("已安装 idd", res.stdout)
            self.assertIn("export PATH=", res.stdout)
            self.assertIn("零侵入安装", res.stdout)
            self.assertIn("AGENTS.md", res.stdout)
            self.assertIn("README", res.stdout)
            for rule_path in (
                home_dir / ".claude" / "CLAUDE.md",
                home_dir / ".codex" / "AGENTS.md",
                home_dir / ".gemini" / "GEMINI.md",
            ):
                self.assertFalse(rule_path.exists(), f"{rule_path} must not be auto-created")

            skill_dir = (home_dir / ".agents" / "skills" / "idd").resolve()
            self.assertTrue((skill_dir / "SKILL.md").is_file())
            for link in (
                home_dir / ".claude" / "skills" / "idd",
                home_dir / ".codex" / "skills" / "idd",
                home_dir / ".gemini" / "config" / "skills" / "idd",
            ):
                self.assertTrue(link.is_symlink(), f"{link} should be a symlink")
                self.assertEqual(link.resolve(), skill_dir)

            cli_link = bin_dir / "idd"
            self.assertTrue(cli_link.is_symlink())
            self.assertEqual(cli_link.resolve(), (skill_dir / "scripts" / "idd").resolve())

            # Running via installed symlink works
            ver_env = _isolated_env(home_dir, extra_path=f"{bin_dir}:{env['PATH']}")
            ver_env["IDD_NO_AUTO_UPDATE"] = "1"
            ver = subprocess.run([str(cli_link), "--version"], env=ver_env, capture_output=True, text=True, check=True)
            self.assertIn("idd ", ver.stdout)

            status = subprocess.run(
                [str(cli_link), "status", "--local-only", "--json"],
                cwd=skill_dir, env=ver_env, capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(status.stdout)["repo_path"], str(skill_dir))

            sample = tmp_path / "example.html"
            sample.write_text("<title>example</title>", encoding="utf-8")
            for command, args, marker in (
                ("board", ["--local-only"], "IDD 实时开发监控看板"),
                ("preview", [str(sample)], 'id="compareBtn"'),
            ):
                with self.subTest(command=command), subprocess.Popen(
                    [str(cli_link), command, *args, "--host", "127.0.0.1", "--port", "0", "--no-open"],
                    env=ver_env, cwd=skill_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ) as server:
                    try:
                        banner = server.stdout.readline()
                        url = re.search(r"http://127\.0\.0\.1:\d+", banner)
                        self.assertIsNotNone(url, banner)
                        with urllib.request.urlopen(url.group(), timeout=5) as response:
                            self.assertIn(marker, response.read().decode("utf-8"))
                    finally:
                        server.terminate()
                        server.communicate(timeout=5)

            # Re-running when BIN_DIR is already on PATH omits PATH export warning
            env_with_bin = dict(env)
            env_with_bin["PATH"] = f"{bin_dir}:{env['PATH']}"
            res_again = subprocess.run(["sh", str(INSTALL_SH)], env=env_with_bin, capture_output=True, text=True)
            self.assertEqual(res_again.returncode, 0, res_again.stderr + res_again.stdout)
            self.assertNotIn("export PATH=", res_again.stdout)

    def test_install_sh_idempotent_update_and_safety_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            origin, seed = _create_bare_idd_origin(tmp_path)
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            env = _isolated_env(home_dir)
            env["IDD_REPO_URL"] = origin.as_uri()

            # Initial install
            subprocess.run(["sh", str(INSTALL_SH)], env=env, check=True, capture_output=True, text=True)
            skill_dir = (home_dir / ".agents" / "skills" / "idd").resolve()

            # Push upstream update -> clean rerun fast-forwards automatically
            (seed / "UPSTREAM_MARKER.txt").write_text("v2\n", encoding="utf-8")
            _git(seed, "add", "UPSTREAM_MARKER.txt")
            _git(seed, "commit", "-m", "feat: upstream update")
            _git(seed, "push", "origin", "main")

            res_ff = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True)
            self.assertEqual(res_ff.returncode, 0, res_ff.stderr + res_ff.stdout)
            self.assertTrue((skill_dir / "UPSTREAM_MARKER.txt").is_file())

            # Dirty local edits + real non-symlink file at mount point are both preserved safely
            (skill_dir / "LOCAL_DIRTY.txt").write_text("keep me\n", encoding="utf-8")
            claude_link = home_dir / ".claude" / "skills" / "idd"
            claude_link.unlink()
            claude_link.mkdir(parents=True)
            (claude_link / "custom.txt").write_text("user-owned\n", encoding="utf-8")

            res_dirty = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True)
            self.assertEqual(res_dirty.returncode, 0, res_dirty.stderr + res_dirty.stdout)
            self.assertIn("保留本地状态", res_dirty.stdout)
            self.assertIn("跳过已存在的非软链路径", res_dirty.stderr)
            self.assertEqual((skill_dir / "LOCAL_DIRTY.txt").read_text(encoding="utf-8"), "keep me\n")
            self.assertFalse(claude_link.is_symlink())
            self.assertEqual((claude_link / "custom.txt").read_text(encoding="utf-8"), "user-owned\n")

            # Non-git directory at SKILL_DIR must fail safely
            other_home = tmp_path / "other_home"
            non_git_skill = other_home / ".agents" / "skills" / "idd"
            non_git_skill.mkdir(parents=True)
            (non_git_skill / "important.txt").write_text("do not delete\n", encoding="utf-8")
            bad_env = _isolated_env(other_home)
            bad_env["IDD_REPO_URL"] = origin.as_uri()
            res_bad = subprocess.run(["sh", str(INSTALL_SH)], env=bad_env, capture_output=True, text=True)
            self.assertNotEqual(res_bad.returncode, 0)
            self.assertIn("不是 Git 仓库", res_bad.stderr)
            self.assertEqual((non_git_skill / "important.txt").read_text(encoding="utf-8"), "do not delete\n")

    def test_idd_uninstall_safety_dry_run_keep_config_and_full_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            origin, _ = _create_bare_idd_origin(tmp_path)
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            env = _isolated_env(home_dir)
            env["IDD_REPO_URL"] = origin.as_uri()
            subprocess.run(["sh", str(INSTALL_SH)], env=env, check=True, capture_output=True, text=True)

            skill_dir = (home_dir / ".agents" / "skills" / "idd").resolve()
            bin_idd = home_dir / ".local" / "bin" / "idd"
            config_dir = home_dir / ".config" / "idd"
            cache_dir = home_dir / ".cache" / "idd"
            config_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "hosts.json").write_text('{"gitlab.local": {"token": "abc"}}', encoding="utf-8")
            (config_dir / "repos.json").write_text('{"repos": []}', encoding="utf-8")
            (cache_dir / "update_state.json").write_text('{"last_checked_at": 1}', encoding="utf-8")

            # Unrelated repo and unrelated codex symlink must never be touched
            biz_repo = tmp_path / "business-repo"
            biz_repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(biz_repo)], check=True, capture_output=True)
            (biz_repo / "app.py").write_text("print('ok')\n", encoding="utf-8")

            other_skill = tmp_path / "other-skill"
            other_skill.mkdir()
            codex_link = home_dir / ".codex" / "skills" / "idd"
            codex_link.unlink()
            codex_link.symlink_to(other_skill)

            run_env = _isolated_env(home_dir, extra_path=f"{home_dir / '.local' / 'bin'}:{env['PATH']}")
            run_env["IDD_UPDATE_INTERVAL"] = "0"  # verify uninstall does NOT trigger bg auto-update

            # 1. --dry-run removes nothing
            dry = subprocess.run([str(bin_idd), "uninstall", "--dry-run"], env=run_env, capture_output=True, text=True)
            self.assertEqual(dry.returncode, 0, dry.stderr + dry.stdout)
            self.assertIn("[dry-run]", dry.stdout)
            self.assertIn("跳过无关软链", dry.stderr)
            self.assertTrue(skill_dir.exists())
            self.assertTrue(config_dir.exists())
            self.assertTrue(cache_dir.exists())

            # 2. Non-TTY without -y is rejected
            no_yes = subprocess.run(
                [str(bin_idd), "uninstall"],
                env=run_env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(no_yes.returncode, 0)
            self.assertIn("-y", no_yes.stderr)
            self.assertTrue(skill_dir.exists())

            # 3. Dirty skill repo blocks uninstall even with -y
            (skill_dir / "UNCOMMITTED.txt").write_text("dirty\n", encoding="utf-8")
            dirty_block = subprocess.run([str(bin_idd), "uninstall", "-y"], env=run_env, capture_output=True, text=True)
            self.assertNotEqual(dirty_block.returncode, 0)
            self.assertIn("未提交改动", dirty_block.stderr)
            self.assertTrue(skill_dir.exists())

            # Clean dirty file, then add an unpushed commit -> also blocks without --force
            (skill_dir / "UNCOMMITTED.txt").unlink()
            _git(skill_dir, "config", "user.name", "Tester")
            _git(skill_dir, "config", "user.email", "tester@example.com")
            (skill_dir / "LOCAL_COMMIT.txt").write_text("ahead\n", encoding="utf-8")
            _git(skill_dir, "add", "LOCAL_COMMIT.txt")
            _git(skill_dir, "commit", "-m", "chore: local unpushed commit")

            ahead_block = subprocess.run([str(bin_idd), "uninstall", "-y"], env=run_env, capture_output=True, text=True)
            self.assertNotEqual(ahead_block.returncode, 0)
            self.assertIn("未推送提交", ahead_block.stderr)
            self.assertTrue(skill_dir.exists())

            # 4. --keep-config --force -y removes links, cache, and skill repo while preserving config
            keep_res = subprocess.run(
                [str(bin_idd), "uninstall", "--keep-config", "--force", "-y"],
                env=run_env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(keep_res.returncode, 0, keep_res.stderr + keep_res.stdout)
            self.assertFalse((home_dir / ".claude" / "skills" / "idd").is_symlink())
            self.assertFalse((home_dir / ".gemini" / "config" / "skills" / "idd").is_symlink())
            self.assertFalse(bin_idd.is_symlink())
            self.assertFalse(cache_dir.exists())
            self.assertFalse(skill_dir.exists())
            self.assertTrue((config_dir / "hosts.json").is_file())
            self.assertTrue((config_dir / "repos.json").is_file())
            self.assertTrue(codex_link.is_symlink())
            self.assertEqual(codex_link.resolve(), other_skill.resolve())

            # 5. Reinstall and run default full uninstall (-y) -> removes everything including config, no cache respawn
            subprocess.run(["sh", str(INSTALL_SH)], env=env, check=True, capture_output=True, text=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "update_state.json").write_text('{"last_checked_at": 1}', encoding="utf-8")
            full_res = subprocess.run([str(bin_idd), "uninstall", "-y"], env=run_env, capture_output=True, text=True)
            self.assertEqual(full_res.returncode, 0, full_res.stderr + full_res.stdout)
            self.assertFalse(skill_dir.exists())
            self.assertFalse(config_dir.exists())
            self.assertFalse(cache_dir.exists())
            self.assertFalse(bin_idd.is_symlink())
            self.assertFalse((home_dir / ".claude" / "skills" / "idd").is_symlink())
            self.assertFalse((home_dir / ".codex" / "skills" / "idd").is_symlink())
            self.assertFalse((home_dir / ".gemini" / "config" / "skills" / "idd").is_symlink())
            self.assertTrue((biz_repo / "app.py").is_file())

    def test_idd_uninstall_rejects_home_or_non_idd_skill_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            not_idd = tmp_path / "random_dir"
            not_idd.mkdir()
            (not_idd / "keep.txt").write_text("safe\n", encoding="utf-8")

            env = _isolated_env(home_dir)
            env["IDD_NO_AUTO_UPDATE"] = "1"
            env["IDD_SKILL_DIR"] = str(home_dir)
            bad_home = subprocess.run(
                ["python3", str(REPO_ROOT / "scripts" / "idd"), "uninstall", "-y"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(bad_home.returncode, 0)
            self.assertIn("受保护路径", bad_home.stderr)
            self.assertTrue(home_dir.is_dir())

            env["IDD_SKILL_DIR"] = str(not_idd)
            bad_dir = subprocess.run(
                ["python3", str(REPO_ROOT / "scripts" / "idd"), "uninstall", "-y"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(bad_dir.returncode, 0)
            self.assertIn("不像是 idd 技能目录", bad_dir.stderr)
            self.assertTrue((not_idd / "keep.txt").is_file())

    def test_install_sh_uninstall_delegates_and_falls_back_when_skill_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            origin, _ = _create_bare_idd_origin(tmp_path)
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            env = _isolated_env(home_dir)
            env["IDD_REPO_URL"] = origin.as_uri()

            # Install, populate config/cache, then uninstall via `install.sh --uninstall -y`
            subprocess.run(["sh", str(INSTALL_SH)], env=env, check=True, capture_output=True, text=True)
            config_dir = home_dir / ".config" / "idd"
            cache_dir = home_dir / ".cache" / "idd"
            config_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "hosts.json").write_text("{}", encoding="utf-8")
            (cache_dir / "update_state.json").write_text("{}", encoding="utf-8")

            un_res = subprocess.run(
                ["sh", str(INSTALL_SH), "--uninstall", "-y"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(un_res.returncode, 0, un_res.stderr + un_res.stdout)
            self.assertFalse((home_dir / ".agents" / "skills" / "idd").exists())
            self.assertFalse(config_dir.exists())
            self.assertFalse(cache_dir.exists())
            self.assertFalse((home_dir / ".local" / "bin" / "idd").is_symlink())

            # Reinstall, manually delete ~/.agents (leaving dangling symlinks + cache/config), then fallback uninstall
            subprocess.run(["sh", str(INSTALL_SH)], env=env, check=True, capture_output=True, text=True)
            config_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "hosts.json").write_text("{}", encoding="utf-8")
            (cache_dir / "update_state.json").write_text("{}", encoding="utf-8")
            shutil.rmtree(home_dir / ".agents")

            # Fallback dry-run leaves dangling symlinks intact
            fb_dry = subprocess.run(
                ["sh", str(INSTALL_SH), "--uninstall", "--dry-run"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(fb_dry.returncode, 0, fb_dry.stderr + fb_dry.stdout)
            self.assertIn("[dry-run]", fb_dry.stdout)
            self.assertTrue((home_dir / ".claude" / "skills" / "idd").is_symlink())

            # Fallback non-TTY without -y refuses
            fb_nontty = subprocess.run(
                ["sh", str(INSTALL_SH), "--uninstall"],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(fb_nontty.returncode, 0)
            self.assertTrue((home_dir / ".claude" / "skills" / "idd").is_symlink())

            # Fallback with -y removes all dangling symlinks + config + cache
            fb_yes = subprocess.run(
                ["sh", str(INSTALL_SH), "--uninstall", "-y"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(fb_yes.returncode, 0, fb_yes.stderr + fb_yes.stdout)
            self.assertFalse((home_dir / ".claude" / "skills" / "idd").is_symlink())
            self.assertFalse((home_dir / ".codex" / "skills" / "idd").is_symlink())
            self.assertFalse((home_dir / ".gemini" / "config" / "skills" / "idd").is_symlink())
            self.assertFalse((home_dir / ".local" / "bin" / "idd").is_symlink())
            self.assertFalse(config_dir.exists())
            self.assertFalse(cache_dir.exists())

    def test_install_and_uninstall_color_and_pretty_path_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            origin, _ = _create_bare_idd_origin(tmp_path)
            home_dir = tmp_path / "home"
            home_dir.mkdir()

            # 1. Default non-TTY install emits clean plain text with `~/` paths
            plain_env = _isolated_env(home_dir)
            plain_env["IDD_REPO_URL"] = origin.as_uri()
            res_plain = subprocess.run(["sh", str(INSTALL_SH)], env=plain_env, capture_output=True, text=True)
            self.assertEqual(res_plain.returncode, 0, res_plain.stderr + res_plain.stdout)
            self.assertNotIn("\x1b[", res_plain.stdout)
            self.assertNotIn("\x1b[", res_plain.stderr)
            self.assertIn("◆ IDD", res_plain.stdout)
            self.assertIn("~/.agents/skills/idd", res_plain.stdout)
            self.assertIn("~/.local/bin/idd", res_plain.stdout)

            # 2. FORCE_COLOR=1 emits ANSI escapes
            color_env = dict(plain_env)
            color_env["FORCE_COLOR"] = "1"
            res_color = subprocess.run(["sh", str(INSTALL_SH)], env=color_env, capture_output=True, text=True)
            self.assertEqual(res_color.returncode, 0, res_color.stderr + res_color.stdout)
            self.assertIn("\x1b[", res_color.stdout)

            # 3. NO_COLOR=1 overrides FORCE_COLOR=1
            nocolor_env = dict(color_env)
            nocolor_env["NO_COLOR"] = "1"
            res_nocolor = subprocess.run(["sh", str(INSTALL_SH)], env=nocolor_env, capture_output=True, text=True)
            self.assertEqual(res_nocolor.returncode, 0, res_nocolor.stderr + res_nocolor.stdout)
            self.assertNotIn("\x1b[", res_nocolor.stdout)

            # 4. Same rules for `idd uninstall --dry-run`
            bin_idd = home_dir / ".local" / "bin" / "idd"
            un_plain_env = _isolated_env(home_dir)
            un_plain_env["IDD_NO_AUTO_UPDATE"] = "1"
            un_plain = subprocess.run(
                [str(bin_idd), "uninstall", "--dry-run"],
                env=un_plain_env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(un_plain.returncode, 0, un_plain.stderr + un_plain.stdout)
            self.assertNotIn("\x1b[", un_plain.stdout)
            self.assertIn("~/.agents/skills/idd", un_plain.stdout)

            un_color_env = dict(un_plain_env)
            un_color_env["FORCE_COLOR"] = "1"
            un_color = subprocess.run(
                [str(bin_idd), "uninstall", "--dry-run"],
                env=un_color_env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(un_color.returncode, 0, un_color.stderr + un_color.stdout)
            self.assertIn("\x1b[", un_color.stdout)

            un_nocolor_env = dict(un_color_env)
            un_nocolor_env["NO_COLOR"] = "1"
            un_nocolor = subprocess.run(
                [str(bin_idd), "uninstall", "--dry-run"],
                env=un_nocolor_env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(un_nocolor.returncode, 0, un_nocolor.stderr + un_nocolor.stdout)
            self.assertNotIn("\x1b[", un_nocolor.stdout)


if __name__ == "__main__":
    unittest.main()
