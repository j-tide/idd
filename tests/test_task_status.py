"""Unit tests for the read-only task_status overview CLI."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/task_status.py"


def write_task(
    root: Path,
    goal: str,
    number: int = 1,
    status: str | None = "planned",
    *,
    issue: str | None = None,
    extra: str = "",
    body: str = "",
    declared_goal: str | None = None,
) -> Path:
    directory = root / "TASK" / goal
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"TASK-{number:02d}-example.md"
    issue_line = f"- Issue: {issue}\n" if issue is not None else ""
    status_line = "" if status is None else f"- Status: {status}\n"
    path.write_text(
        f"# TASK-{number:02d}：验收示例\n\n"
        f"- Goal: {declared_goal or goal}\n{issue_line}{status_line}"
        f"- Depends on: none\n- Test: pytest existing_test.py\n{extra}"
        f"\n## 执行结果\n{body}",
        encoding="utf-8",
    )
    return path


def run_cli(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def query(root: Path, *args: str) -> dict:
    return json.loads(run_cli(root, *args, "--json").stdout)


class TestTaskStatus(unittest.TestCase):
    def test_lifecycle_states_are_not_conflated_with_completion(self) -> None:
        statuses = ["planned", "in_progress", "blocked", "deferred", "cancelled", "done", "in_review", None]
        for status in statuses:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                write_task(tmp_path, "states", status=status)
                data = query(tmp_path)
                goal = data["goals"][0]
                known = status if status not in ("in_review", None) else "unknown"
                self.assertEqual(goal["counts"][known], 1)
                self.assertEqual(goal["done"], 1 if status == "done" else 0)
                self.assertEqual(sum(goal["counts"].values()), goal["total"])
                self.assertEqual(goal["total"], 1)
                self.assertEqual(goal["tasks"][0]["raw_status"], status or "")
                self.assertEqual(bool(data["warnings"]), known == "unknown")

    def test_goal_totals_and_open_filter_keep_deferred_and_cancelled_work_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(tmp_path, "closed", status="done")
            for number, status in enumerate(["done", "blocked", "deferred", "cancelled", "new_state"], 1):
                write_task(tmp_path, "mixed", number, status)
            evidence = tmp_path / "TASK/mixed/evidence/TASK-99-screenshot.md"
            evidence.parent.mkdir()
            evidence.write_text("This is an attachment, not a task.")
            data = query(tmp_path, "--open-only")
            self.assertEqual([goal["goal"] for goal in data["goals"]], ["mixed"])
            mixed = data["goals"][0]
            self.assertEqual((mixed["done"], mixed["total"]), (1, 5))
            self.assertEqual(
                {task["status"] for task in mixed["tasks"]},
                {"blocked", "deferred", "cancelled", "unknown"},
            )
            self.assertEqual([goal["goal"] for goal in query(tmp_path)["goals"]], ["closed", "mixed"])

    def test_goal_filter_and_missing_goal_have_explicit_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(tmp_path, "one", status="done")
            write_task(tmp_path, "two", status="blocked")
            self.assertEqual([goal["goal"] for goal in query(tmp_path, "--goal", "two")["goals"]], ["two"])
            self.assertEqual(query(tmp_path, "--goal", "one", "--open-only")["goals"], [])
            result = run_cli(tmp_path, "--goal", "missing", check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("missing", result.stderr)

    def test_execution_history_and_code_examples_do_not_override_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(
                tmp_path,
                "history",
                status="blocked",
                body="- Outcome: done\n- Status: done\n\n### 旧记录\n```markdown\n- Status: passed\n```\n",
            )
            task = query(tmp_path)["goals"][0]["tasks"][0]
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["issues"], [])

    def test_ambiguous_status_is_reported_without_claiming_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(tmp_path, "ambiguous", status="done", extra="- Status: blocked\n")
            data = query(tmp_path)
            self.assertEqual(data["goals"][0]["done"], 0)
            self.assertEqual(data["goals"][0]["tasks"][0]["status"], "unknown")
            self.assertTrue(data["warnings"])

    def test_goal_directory_remains_authoritative_and_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(tmp_path, "actual", declared_goal="wrong")
            data = query(tmp_path)
            self.assertEqual(data["goals"][0]["goal"], "actual")
            self.assertTrue(any("wrong" in warning for warning in data["warnings"]))

    def test_unreadable_encoding_is_visible_instead_of_silently_dropping_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path = write_task(tmp_path, "encoding", status="done")
            path.write_bytes(b"\xff\xfeinvalid")
            data = query(tmp_path)
            self.assertEqual(data["goals"][0]["total"], 1)
            self.assertEqual(data["goals"][0]["done"], 0)
            self.assertEqual(data["goals"][0]["tasks"][0]["status"], "unknown")
            self.assertTrue(any("UnicodeDecodeError" in warning for warning in data["warnings"]))

    def test_queries_preserve_files_bytes_timestamps_and_directory_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace with spaces"
            write_task(root, "preserve", status="blocked")
            evidence = root / "TASK/preserve/evidence.json"
            evidence.write_text('{"historical": true}')

            def snapshot() -> dict:
                return {
                    str(path.relative_to(root)): (
                        (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else None
                    )
                    for path in root.rglob("*")
                }

            before = snapshot()
            query(root)
            query(root, "--open-only", "--goal", "preserve")
            run_cli(root)
            self.assertEqual(snapshot(), before)

    def test_empty_and_missing_task_directories_are_distinguished(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = run_cli(tmp_path, check=False)
            self.assertEqual(result.returncode, 2)
            (tmp_path / "TASK").mkdir()
            self.assertEqual(query(tmp_path), {"goals": [], "warnings": []})
            self.assertEqual(run_cli(tmp_path).returncode, 0)

    def test_markdown_output_keeps_table_cells_and_raw_unknown_status_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(tmp_path, "pipe|name", status="legacy")
            result = run_cli(tmp_path)
            self.assertIn(r"pipe\|name", result.stdout)
            self.assertIn("unknown", result.stdout)
            self.assertIn("legacy", result.stdout)
            self.assertIn("0 / 1", result.stdout)

    def test_optional_issue_header_and_goal_prefix_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_task(tmp_path, "explicit-dir", status="done", issue="#42")
            write_task(tmp_path, "77-prefix-dir", status="in_progress")
            write_task(tmp_path, "plain-local", status="planned")
            data = query(tmp_path)
            self.assertEqual(data["warnings"], [])
            by_goal = {g["goal"]: g for g in data["goals"]}
            self.assertEqual(by_goal["explicit-dir"]["issue_number"], 42)
            self.assertEqual(by_goal["77-prefix-dir"]["issue_number"], 77)
            self.assertIsNone(by_goal["plain-local"]["issue_number"])

    def test_all_worktrees_aggregates_multiple_git_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            (repo / "README.md").write_text("init\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: init"], check=True, capture_output=True)

            wt1 = tmp_path / "repo-worktrees/42-csv"
            wt2 = tmp_path / "repo-worktrees/43-auth"
            wt1.parent.mkdir(parents=True)
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "feat/42-csv", str(wt1), "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "fix/43-auth", str(wt2), "main"], check=True, capture_output=True)

            write_task(wt1, "42-csv", 1, status="done", issue="#42")
            write_task(wt1, "42-csv", 2, status="in_progress", issue="#42")
            write_task(wt2, "43-auth", 1, status="blocked")

            data = query(repo, "--all-worktrees")
            self.assertEqual([g["goal"] for g in data["goals"]], ["42-csv", "43-auth"])
            self.assertEqual(data["goals"][0]["branch"], "feat/42-csv")
            self.assertEqual(data["goals"][0]["done"], 1)
            self.assertEqual(data["goals"][0]["total"], 2)
            self.assertEqual(data["goals"][1]["issue_number"], 43)

            md = run_cli(repo, "--all-worktrees").stdout
            self.assertIn("#42", md)
            self.assertIn("feat/42-csv", md)
            self.assertIn("43-auth", md)


if __name__ == "__main__":
    unittest.main()
