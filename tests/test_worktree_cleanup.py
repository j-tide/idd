"""Real Git checks for worktree removal after a remote merge was observed."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from command_runner import IddError
from repository_lock import MAIN_GIT_LOCK, repo_file_lock
from worktree_cleanup import remove_merged_worktree


class TestWorktreeCleanup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.main = Path(tmp.name).resolve() / "repo"
        self.root = self.main.parent / "managed"
        self.path = self.root / "42-change"
        self.branch = "feat/42-change"
        subprocess.run(["git", "init", "-b", "main", str(self.main)], check=True, capture_output=True)
        self.git(self.main, "config", "user.name", "Tester")
        self.git(self.main, "config", "user.email", "test@example.com")
        self.git(self.main, "commit", "--allow-empty", "-m", "base")
        self.git(self.main, "worktree", "add", "-b", self.branch, str(self.path))
        self.merged = [{"number": 7, "headRefOid": self.git(self.path, "rev-parse", "HEAD")}]

    def git(self, path, *args):
        return subprocess.run(["git", "-C", str(path), *args], check=True, text=True, capture_output=True).stdout.strip()

    def remove(self, *, dry_run=False):
        return remove_merged_worktree(
            self.main, self.path, self.branch, self.root, self.merged, ref_prefix="PR #", dry_run=dry_run,
        )

    def test_rechecks_local_state_and_keeps_branch(self):
        self.assertEqual(self.remove(dry_run=True).status, "dry_run")
        dirty = self.path / "new.txt"
        dirty.write_text("local work", encoding="utf-8")
        self.assertEqual(self.remove().status, "skipped_dirty")
        self.git(self.path, "add", dirty.name)
        self.git(self.path, "commit", "-m", "new work")
        self.assertEqual(self.remove().status, "skipped_unmerged")
        self.git(self.path, "switch", "-c", "fix/99-another-issue")
        self.assertEqual(self.remove().status, "rejected")
        self.assertEqual(dirty.read_text(encoding="utf-8"), "local work")

    def test_dry_run_does_not_create_or_wait_for_a_write_lock(self):
        lock_path = self.main / ".git" / MAIN_GIT_LOCK
        self.assertEqual(self.remove(dry_run=True).status, "dry_run")
        self.assertFalse(lock_path.exists())
        with ThreadPoolExecutor(max_workers=1) as pool:
            with repo_file_lock(self.main, MAIN_GIT_LOCK):
                preview = pool.submit(self.remove, dry_run=True)
                self.assertEqual(preview.result(timeout=3).status, "dry_run")
        self.assertTrue(self.path.is_dir())

    def test_concurrent_cleanup_is_idempotent(self):
        ready = threading.Barrier(2)

        def remove_once():
            ready.wait(timeout=5)
            return self.remove().status

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(remove_once) for _ in range(2)]
            self.assertCountEqual([f.result(timeout=10) for f in results], ["removed", "already_removed"])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.git(self.main, "rev-parse", self.branch), self.merged[0]["headRefOid"])

    def test_reentrancy_belongs_to_one_thread(self):
        def contender():
            with repo_file_lock(self.path, MAIN_GIT_LOCK, timeout=0.15):
                self.fail("another thread entered the repository lock")

        with ThreadPoolExecutor(max_workers=1) as pool:
            with repo_file_lock(self.main, MAIN_GIT_LOCK):
                with self.assertRaises(IddError) as error:
                    pool.submit(contender).result(timeout=5)
            self.assertEqual(error.exception.exit_code, 3)
