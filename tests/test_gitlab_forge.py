"""End-to-end tests for self-hosted GitLab support using a real local HTTP server."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
IDD_BIN = SCRIPTS_DIR / "idd"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import forge  # noqa: E402


class MockGitLabState:
    """In-memory state backing a real ThreadingHTTPServer simulating GitLab REST API v4."""

    def __init__(self, origin_dir: Path, base_url: str = "") -> None:
        self.origin_dir = origin_dir
        self.base_url = base_url
        self.expected_token = "glpat-secret"
        self.encoded_project = "dept%2Fsub%2Fdemo"
        self.next_issue_iid = 1
        self.next_mr_iid = 10
        self.issues: dict[int, dict] = {}
        self.mrs: dict[int, dict] = {}
        self.jobs: dict[int, dict] = {
            701: {
                "id": 701,
                "name": "pytest",
                "status": "failed",
                "allow_failure": False,
                "web_url": "",
                "trace": "AssertionError: csv header mismatch\nFAILED tests/test_export.py::test_csv",
            }
        }
        self.project_settings = {
            "id": 99,
            "path_with_namespace": "dept/sub/demo",
            "merge_method": "merge",
            "squash_option": "default_off",
            "remove_source_branch_after_merge": True,
        }
        self.last_merge_payload: dict | None = None
        self.stale_get_polls: int = 0
        self.merge_transient_failures: list[tuple[int, str]] = []
        self.merge_attempts: int = 0
        self.mr_get_calls: int = 0
        self.merge_without_squash = False
        self.defer_auto_merge = False

    def origin_sha(self, branch: str) -> str:
        proc = subprocess.run(
            ["git", "--git-dir", str(self.origin_dir), "rev-parse", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def perform_ff_squash(self, mr: dict, message: str) -> str:
        head = mr["source_branch"]
        base = mr["target_branch"]
        tree = subprocess.check_output(
            ["git", "--git-dir", str(self.origin_dir), "rev-parse", f"refs/heads/{head}^{{tree}}"],
            text=True,
        ).strip()
        parent = subprocess.check_output(
            ["git", "--git-dir", str(self.origin_dir), "rev-parse", f"refs/heads/{base}"],
            text=True,
        ).strip()
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = "GitLab"
        env["GIT_AUTHOR_EMAIL"] = "gitlab@corp.local"
        env["GIT_COMMITTER_NAME"] = "GitLab"
        env["GIT_COMMITTER_EMAIL"] = "gitlab@corp.local"
        squash_sha = subprocess.check_output(
            ["git", "--git-dir", str(self.origin_dir), "commit-tree", tree, "-p", parent, "-m", message],
            text=True,
            env=env,
        ).strip()
        subprocess.check_call(["git", "--git-dir", str(self.origin_dir), "update-ref", f"refs/heads/{base}", squash_sha])
        return squash_sha


def make_handler(state: MockGitLabState):
    class GitLabHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _send_json(self, code: int, payload: object) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_text(self, code: int, text: str) -> None:
            raw = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _auth_ok(self) -> bool:
            if self.headers.get("PRIVATE-TOKEN") != state.expected_token:
                self._send_json(401, {"message": "401 Unauthorized"})
                return False
            return True

        def do_GET(self) -> None:
            if not self._auth_ok():
                return
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path == "/api/v4/user":
                self._send_json(200, {"id": 7, "username": "j.tide"})
                return

            proj_prefix = f"/api/v4/projects/{state.encoded_project}"
            if path == proj_prefix:
                self._send_json(200, state.project_settings)
                return

            if path == f"{proj_prefix}/issues":
                req_state = (qs.get("state") or ["all"])[0]
                items = [v for v in state.issues.values() if req_state == "all" or v["state"] == req_state]
                self._send_json(200, items)
                return

            m_issue = re.fullmatch(rf"{re.escape(proj_prefix)}/issues/(\d+)", path)
            if m_issue:
                iid = int(m_issue.group(1))
                if iid not in state.issues:
                    self._send_json(404, {"message": "Issue not found"})
                    return
                self._send_json(200, state.issues[iid])
                return

            if path == f"{proj_prefix}/merge_requests":
                req_state = (qs.get("state") or ["all"])[0]
                src = (qs.get("source_branch") or [None])[0]
                items = [
                    mr for mr in state.mrs.values()
                    if (req_state == "all" or mr["state"] == req_state)
                    and (not src or mr["source_branch"] == src)
                ]
                self._send_json(200, items)
                return

            m_mr = re.fullmatch(rf"{re.escape(proj_prefix)}/merge_requests/(\d+)", path)
            if m_mr:
                iid = int(m_mr.group(1))
                if iid not in state.mrs:
                    self._send_json(404, {"message": "MR not found"})
                    return
                mr = state.mrs[iid]
                state.mr_get_calls += 1
                if state.stale_get_polls > 0:
                    state.stale_get_polls -= 1
                    mr["detailed_merge_status"] = "checking"
                else:
                    oid = state.origin_sha(mr["source_branch"])
                    if oid:
                        mr["sha"] = oid
                        mr.setdefault("diff_refs", {})["head_sha"] = oid
                    mr["detailed_merge_status"] = "mergeable"
                    mr["head_pipeline"]["status"] = state.jobs[701]["status"]
                self._send_json(200, mr)
                return

            m_jobs = re.fullmatch(rf"{re.escape(proj_prefix)}/pipelines/(\d+)/jobs", path)
            if m_jobs:
                self._send_json(200, list(state.jobs.values()))
                return

            m_trace = re.fullmatch(rf"{re.escape(proj_prefix)}/jobs/(\d+)/trace", path)
            if m_trace:
                jid = int(m_trace.group(1))
                job = state.jobs.get(jid)
                if not job:
                    self._send_text(404, "not found")
                    return
                self._send_text(200, job["trace"])
                return

            self._send_json(404, {"message": f"Unhandled GET {path}"})

        def do_POST(self) -> None:
            if not self._auth_ok():
                return
            path = urllib.parse.urlparse(self.path).path
            body = self._read_json()
            proj_prefix = f"/api/v4/projects/{state.encoded_project}"

            if path == f"{proj_prefix}/issues":
                iid = state.next_issue_iid
                state.next_issue_iid += 1
                labels = [x.strip() for x in str(body.get("labels", "")).split(",") if x.strip()]
                issue = {
                    "iid": iid,
                    "title": body.get("title", ""),
                    "description": body.get("description", ""),
                    "labels": labels,
                    "state": "opened",
                    "web_url": f"{state.base_url}/dept/sub/demo/-/issues/{iid}",
                }
                state.issues[iid] = issue
                self._send_json(201, issue)
                return

            if path == f"{proj_prefix}/merge_requests":
                iid = state.next_mr_iid
                state.next_mr_iid += 1
                src = body["source_branch"]
                sha = state.origin_sha(src)
                mr = {
                    "iid": iid,
                    "title": body.get("title", ""),
                    "description": body.get("description", ""),
                    "source_branch": src,
                    "target_branch": body.get("target_branch", "main"),
                    "state": "opened",
                    "sha": sha,
                    "diff_refs": {"head_sha": sha},
                    "has_conflicts": False,
                    "detailed_merge_status": "mergeable",
                    "head_pipeline": {
                        "id": 500,
                        "status": state.jobs[701]["status"],
                        "web_url": f"{state.base_url}/dept/sub/demo/-/pipelines/500",
                    },
                    "web_url": f"{state.base_url}/dept/sub/demo/-/merge_requests/{iid}",
                }
                state.mrs[iid] = mr
                self._send_json(201, mr)
                return

            self._send_json(404, {"message": f"Unhandled POST {path}"})

        def do_PUT(self) -> None:
            if not self._auth_ok():
                return
            path = urllib.parse.urlparse(self.path).path
            body = self._read_json()
            proj_prefix = f"/api/v4/projects/{state.encoded_project}"

            if path == proj_prefix:
                for key in ("merge_method", "squash_option", "remove_source_branch_after_merge"):
                    if key in body:
                        state.project_settings[key] = body[key]
                self._send_json(200, state.project_settings)
                return

            m_issue = re.fullmatch(rf"{re.escape(proj_prefix)}/issues/(\d+)", path)
            if m_issue:
                iid = int(m_issue.group(1))
                issue = state.issues[iid]
                if "description" in body:
                    issue["description"] = body["description"]
                self._send_json(200, issue)
                return

            m_mr = re.fullmatch(rf"{re.escape(proj_prefix)}/merge_requests/(\d+)", path)
            if m_mr:
                iid = int(m_mr.group(1))
                mr = state.mrs[iid]
                if "title" in body:
                    mr["title"] = body["title"]
                if "description" in body:
                    mr["description"] = body["description"]
                if state.stale_get_polls == 0:
                    oid = state.origin_sha(mr["source_branch"])
                    if oid:
                        mr["sha"] = oid
                        mr.setdefault("diff_refs", {})["head_sha"] = oid
                    mr["head_pipeline"]["status"] = state.jobs[701]["status"]
                self._send_json(200, mr)
                return

            m_merge = re.fullmatch(rf"{re.escape(proj_prefix)}/merge_requests/(\d+)/merge", path)
            if m_merge:
                iid = int(m_merge.group(1))
                mr = state.mrs[iid]
                state.merge_attempts += 1
                state.last_merge_payload = body
                if state.merge_transient_failures:
                    code, msg = state.merge_transient_failures.pop(0)
                    self._send_json(code, {"message": msg})
                    return
                diff_head_sha = (mr.get("diff_refs") or {}).get("head_sha") or mr.get("sha")
                if body.get("sha") and body.get("sha") != diff_head_sha:
                    self._send_json(409, {"message": "SHA does not match HEAD of source branch"})
                    return
                oid = state.origin_sha(mr["source_branch"])
                if oid:
                    mr["sha"] = oid
                    mr.setdefault("diff_refs", {})["head_sha"] = oid
                if body.get("merge_when_pipeline_succeeds") and state.defer_auto_merge:
                    self._send_json(200, mr)
                    return
                msg = body.get("squash_commit_message") or mr["title"]
                if state.merge_without_squash:
                    subprocess.check_call(["git", "--git-dir", str(state.origin_dir), "update-ref",
                                           f"refs/heads/{mr['target_branch']}", oid])
                else:
                    mr["squash_commit_sha"] = state.perform_ff_squash(mr, msg)
                mr["state"] = "merged"
                for m in re.finditer(r"Closes\s+#(\d+)", msg):
                    num = int(m.group(1))
                    if num in state.issues:
                        state.issues[num]["state"] = "closed"
                self._send_json(200, mr)
                return

            self._send_json(404, {"message": f"Unhandled PUT {path}"})

    return GitLabHandler


class TestGitLabForge(unittest.TestCase):
    def test_remote_url_parser_handles_self_hosted_gitlab_formats(self) -> None:
        https_spec = forge.parse_remote_url("https://gitlab.company.com/dept/team/sub/repo.git")
        self.assertIsNotNone(https_spec)
        self.assertEqual(https_spec.hostname, "gitlab.company.com")
        self.assertEqual(https_spec.project_path, "dept/team/sub/repo")
        self.assertEqual(https_spec.api_base, "https://gitlab.company.com")

        http_port = forge.parse_remote_url("http://10.0.0.5:8080/group/app.git")
        self.assertEqual(http_port.host, "10.0.0.5:8080")
        self.assertEqual(http_port.api_base, "http://10.0.0.5:8080")

        scp_spec = forge.parse_remote_url("git@gitlab.corp.local:org/nested/service.git")
        self.assertEqual(scp_spec.hostname, "gitlab.corp.local")
        self.assertEqual(scp_spec.project_path, "org/nested/service")
        self.assertEqual(scp_spec.api_base, "https://gitlab.corp.local")

        ssh_port = forge.parse_remote_url("ssh://git@gitlab.corp.local:2222/org/service.git")
        self.assertEqual(ssh_port.hostname, "gitlab.corp.local")
        self.assertEqual(ssh_port.host, "gitlab.corp.local")
        self.assertEqual(ssh_port.api_base, "https://gitlab.corp.local")
        self.assertEqual(ssh_port.project_path, "org/service")

        self.assertIsNone(forge.parse_remote_url("/tmp/bare/origin.git"))

    def test_normalize_mr_prefers_diff_refs_head_sha_and_tracks_checking_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gl = forge.GitLabForge(
                Path(tmp),
                forge.RemoteSpec("https", "gitlab.example.com", "gitlab.example.com", None, "org/repo", "https://gitlab.example.com"),
                {"token": "glpat-test"},
            )
            for status in ("checking", "unchecked", "preparing"):
                normalized = gl._normalize_mr(
                    {
                        "iid": 12,
                        "title": "fix: test",
                        "state": "opened",
                        "sha": "new_branch_sha",
                        "diff_refs": {"head_sha": "old_diff_sha"},
                        "detailed_merge_status": status,
                        "source_branch": "fix/1-test",
                        "target_branch": "main",
                    },
                    fetch_jobs=False,
                )
                self.assertEqual(normalized["headRefOid"], "old_diff_sha")
                self.assertEqual(normalized["rawSha"], "new_branch_sha")
                self.assertEqual(normalized["mergeStateStatus"], "CHECKING")
                self.assertEqual(normalized["detailedMergeStatus"], status)

            fallback = gl._normalize_mr(
                {
                    "iid": 13,
                    "title": "fix: list item",
                    "state": "opened",
                    "sha": "list_sha",
                    "merge_status": "unchecked",
                    "source_branch": "fix/2-test",
                    "target_branch": "main",
                },
                fetch_jobs=False,
            )
            self.assertEqual(fallback["headRefOid"], "list_sha")
            self.assertEqual(fallback["rawSha"], "list_sha")
            self.assertEqual(fallback["mergeStateStatus"], "CHECKING")

    def test_merge_squash_passes_expected_sha_and_http_status_on_error(self) -> None:
        captured: list[tuple[str, str, dict | None]] = []

        class StubGitLabForge(forge.GitLabForge):
            def _request(self, method, path, *, query=None, json_body=None, raw_text=False, check=True):
                captured.append((method, path, json_body))
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gl = StubGitLabForge(
                root,
                forge.RemoteSpec("https", "gitlab.example.com", "gitlab.example.com", None, "org/repo", "https://gitlab.example.com"),
                {"token": "glpat-test"},
            )
            gl.merge_squash(15, "fix: title", "Closes #1", auto=False, expected_sha="abc123")
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0][0], "PUT")
            self.assertEqual(captured[0][2]["sha"], "abc123")

            gh = forge.GitHubForge(root)
            calls: list[list[str]] = []
            orig_run = forge._run
            try:
                def fake_run(args, *, cwd=None, check=True, env=None):
                    calls.append(args)
                    return forge.subprocess.CompletedProcess(args, 0, "", "")

                forge._run = fake_run
                gh.merge_squash(9, "fix: title", "Closes #1", auto=True, expected_sha="def456")
            finally:
                forge._run = orig_run

            self.assertEqual(len(calls), 1)
            self.assertIn("--auto", calls[0])
            self.assertIn("--match-head-commit", calls[0])
            idx = calls[0].index("--match-head-commit")
            self.assertEqual(calls[0][idx + 1], "def456")

            err = forge.ForgeError("conflict", exit_code=1, http_status=409)
            self.assertEqual(err.http_status, 409)

    def test_self_hosted_gitlab_end_to_end_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            repo = root / "demo"
            config_dir = root / "config"

            subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
            state = MockGitLabState(origin)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
            port = server.server_address[1]
            base_url = f"http://127.0.0.1:{port}"
            state.base_url = base_url
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                remote_url = f"{base_url}/dept/sub/demo.git"
                subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
                subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
                (repo / "README.md").write_text("# GitLab Demo\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
                subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: init"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
                subprocess.run(["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

                # Keep `origin` URL as real self-hosted HTTP URL while git transport goes to local bare origin
                subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", remote_url], check=True)
                subprocess.run(["git", "-C", str(repo), "config", f"url.{origin}.insteadOf", remote_url], check=True)
                subprocess.run(["git", "-C", str(repo), "fetch", "origin", "main"], check=True, capture_output=True)

                env = dict(os.environ)
                env["IDD_CONFIG_DIR"] = str(config_dir)
                env["IDD_NO_AUTO_UPDATE"] = "1"
                env.pop("IDD_WORKTREE_ROOT", None)
                env.pop("IDD_FORGE", None)
                env.pop("GITLAB_TOKEN", None)

                def run_idd(*args: str, cwd: Path | None = None, check: bool = True):
                    return subprocess.run(
                        [sys.executable, str(IDD_BIN), *args],
                        cwd=str(cwd or repo),
                        env=env,
                        capture_output=True,
                        text=True,
                        check=check,
                    )

                # 0. Missing token error includes full http:// scheme for idd auth login
                unauth_res = run_idd("issue", "create", "--title", "feat: No token yet", check=False)
                self.assertNotEqual(unauth_res.returncode, 0)
                self.assertIn(f"idd auth login http://127.0.0.1:{port} --token", unauth_res.stderr)

                # 1. Auth login + status + permissions check
                login_res = run_idd("auth", "login", f"http://127.0.0.1:{port}", "--token", "glpat-secret")
                self.assertIn("已校验用户：j.tide", login_res.stdout)
                hosts_file = config_dir / "hosts.json"
                self.assertEqual(stat.S_IMODE(hosts_file.stat().st_mode), 0o600)
                auth_status = run_idd("auth", "status").stdout
                self.assertIn("127.0.0.1", auth_status)
                self.assertNotIn("glpat-secret", auth_status)

                # 2. Create Issue on self-hosted GitLab
                created = json.loads(
                    run_idd(
                        "issue",
                        "create",
                        "--title",
                        "feat: Export CSV",
                        "--body",
                        "## 验收标准\n\n- [ ] 支持 CSV 下载\n- [ ] 单测通过\n\n## 后续计划\n\n- [ ] 支持 Excel",
                        "--label",
                        "feat",
                        "--json",
                    ).stdout
                )
                self.assertEqual(created["number"], 1)
                self.assertIn("/dept/sub/demo/-/issues/1", created["url"])

                # 3. Start worktree from Issue #1
                started = json.loads(run_idd("start", "1", "--slug", "export-csv", "--json").stdout)
                wt = Path(started["worktree"])
                self.assertEqual(started["branch"], "feat/1-export-csv")

                # 4. Write TASK, commit, and sync checklist back to GitLab Issue
                task_dir = wt / "TASK/1-export-csv"
                task_dir.mkdir(parents=True)
                (task_dir / "TASK-01-impl.md").write_text(
                    "# TASK-01：实现 CSV 导出\n\n"
                    "- Issue: 1-export-csv\n"
                    "- Status: done\n"
                    "- Depends on: none\n"
                    "- Test: pytest test_csv.py\n\n"
                    "## 执行结果\n- Outcome: passed\n",
                    encoding="utf-8",
                )
                (wt / "csv_export.py").write_text("def run(): return True\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
                subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
                subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
                subprocess.run(
                    [
                        "git", "-C", str(wt), "commit", "-m",
                        "feat: 实现 CSV 导出\n\nTask: 1-export-csv/TASK-01\nRefs: #1\nTest: pytest test_csv.py — 2 passed",
                    ],
                    check=True,
                    capture_output=True,
                )

                sync_res = run_idd("sync", "1")
                self.assertIn("已同步 Issue #1", sync_res.stdout)
                self.assertIn("- [x] TASK-01：实现 CSV 导出", state.issues[1]["description"])

                # 5. Open MR via `idd mr` alias
                mr_res = run_idd("mr", "1")
                self.assertIn("已创建 MR !10", mr_res.stdout)
                self.assertIn("Closes #1", state.mrs[10]["description"])
                self.assertNotIn("Goal:", state.mrs[10]["description"])

                # 6. Check failed CI log & status board
                ci_res = run_idd("ci", "1")
                self.assertIn("MR !10", ci_res.stdout)
                self.assertIn("[FAIL] pytest", ci_res.stdout)
                self.assertIn("AssertionError: csv header mismatch", ci_res.stdout)

                st_json = json.loads(run_idd("status", "--json").stdout)
                self.assertEqual(st_json["forge"], "gitlab")
                self.assertEqual(st_json["issues"][0]["stage"], "🛠️ 修 CI")
                self.assertIn("MR !10", st_json["issues"][0]["change_summary"])

                # 7. Configure GitLab linear ff + squash via repo-init
                ri = run_idd("repo-init", "--apply").stdout
                self.assertIn("merge_method: ff", ri)
                self.assertIn("squash_option: always", ri)
                self.assertIn("remove_source_branch_after_merge: False", ri)

                # 8. Mark CI green, advance main remotely, then `idd land 1`
                state.jobs[701]["status"] = "success"
                helper = root / "helper"
                subprocess.run(["git", "clone", str(origin), str(helper)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(helper), "checkout", "main"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(helper), "config", "user.name", "Other"], check=True)
                subprocess.run(["git", "-C", str(helper), "config", "user.email", "other@example.com"], check=True)
                (helper / "OTHER.md").write_text("main moved forward\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(helper), "add", "OTHER.md"], check=True)
                subprocess.run(["git", "-C", str(helper), "commit", "-m", "docs: main update"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(helper), "push", "origin", "main"], check=True, capture_output=True)

                land_res = run_idd("land", "1")
                self.assertIn("已通过 Squash Merge 直线合入 MR !10", land_res.stdout)
                self.assertIn("已保留本地与远端分支：feat/1-export-csv", land_res.stdout)
                self.assertIn("已自动勾选 Issue #1 验收标准（2 项）", land_res.stdout)
                self.assertTrue(wt.exists())

                # Verify GitLab merge payload & linear main without TASK/1-export-csv
                wt_head = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()
                self.assertTrue(state.last_merge_payload["squash"])
                self.assertEqual(state.last_merge_payload.get("sha"), wt_head)
                self.assertFalse(state.last_merge_payload["should_remove_source_branch"])
                self.assertEqual(state.issues[1]["state"], "closed")
                self.assertIn("- [x] 支持 CSV 下载", state.issues[1]["description"])
                self.assertIn("- [x] 单测通过", state.issues[1]["description"])
                self.assertIn("- [ ] 支持 Excel", state.issues[1]["description"])
                self.assertEqual(
                    subprocess.check_output(["git", "-C", str(repo), "rev-list", "--merges", "--count", "main"], text=True).strip(),
                    "0",
                )
                self.assertTrue((repo / "csv_export.py").is_file())
                self.assertTrue((repo / "OTHER.md").is_file())
                self.assertFalse((repo / "TASK/1-export-csv").exists())

                # 9. `idd cleanup` removes worktree while keeping both local & origin branches
                cleanup_res = run_idd("cleanup")
                self.assertIn("已移除工作树目录", cleanup_res.stdout)
                self.assertFalse(wt.exists())
                self.assertEqual(
                    subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", "refs/heads/feat/1-export-csv"]).returncode,
                    0,
                )
                self.assertEqual(
                    subprocess.run(["git", "--git-dir", str(origin), "show-ref", "--verify", "--quiet", "refs/heads/feat/1-export-csv"]).returncode,
                    0,
                )

                # 10. Logout removes host entry cleanly
                logout_res = run_idd("auth", "logout", f"127.0.0.1:{port}")
                self.assertIn("已移除主机", logout_res.stdout)
            finally:
                server.shutdown()
                server.server_close()

    def _setup_gitlab_mr_repo(self, tmp: str):
        root = Path(tmp)
        origin = root / "origin.git"
        repo = root / "demo"
        config_dir = root / "config"

        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
        state = MockGitLabState(origin)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        state.base_url = base_url
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        remote_url = f"{base_url}/dept/sub/demo.git"
        subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
        (repo / "README.md").write_text("# GitLab Demo\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
        subprocess.run(["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

        subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", remote_url], check=True)
        subprocess.run(["git", "-C", str(repo), "config", f"url.{origin}.insteadOf", remote_url], check=True)
        subprocess.run(["git", "-C", str(repo), "fetch", "origin", "main"], check=True, capture_output=True)

        env = dict(os.environ)
        env["IDD_CONFIG_DIR"] = str(config_dir)
        env["IDD_NO_AUTO_UPDATE"] = "1"
        env["IDD_LAND_SYNC_INTERVAL"] = "0.05"
        env["IDD_LAND_MERGE_RETRY_DELAY"] = "0.05"
        env.pop("IDD_WORKTREE_ROOT", None)
        env.pop("IDD_FORGE", None)
        env.pop("GITLAB_TOKEN", None)

        def run_idd(*args: str, cwd: Path | None = None, check: bool = True):
            return subprocess.run(
                [sys.executable, str(IDD_BIN), *args],
                cwd=str(cwd or repo),
                env=env,
                capture_output=True,
                text=True,
                check=check,
            )

        run_idd("auth", "login", base_url, "--token", "glpat-secret")
        run_idd("issue", "create", "--title", "fix: Land test", "--body", "## 验收标准\n\n- [ ] 确认合入", "--label", "fix")
        started = json.loads(run_idd("start", "1", "--slug", "async-land", "--json").stdout)
        wt = Path(started["worktree"])
        task_dir = wt / "TASK/1-async-land"
        task_dir.mkdir(parents=True)
        (task_dir / "TASK-01-fix.md").write_text(
            "# TASK-01：修复问题\n\n"
            "- Issue: 1-async-land\n"
            "- Status: done\n"
            "- Depends on: none\n"
            "- Test: pytest test_fix.py\n\n"
            "## 执行结果\n- Outcome: passed\n",
            encoding="utf-8",
        )
        (wt / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt), "config", "user.name", "Tester"], check=True)
        subprocess.run(["git", "-C", str(wt), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-m", "fix: 修复逻辑\n\nTask: 1-async-land/TASK-01\nRefs: #1\nTest: pytest — 1 passed"],
            check=True,
            capture_output=True,
        )
        run_idd("sync", "1")
        state.jobs[701]["status"] = "success"
        run_idd("mr", "1")
        state.project_settings.update(merge_method="ff", squash_option="always")
        return root, repo, wt, state, server, env, run_idd

    def test_gitlab_land_waits_for_async_head_sha_refresh_and_retries_transient_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, wt, state, server, _, run_idd = self._setup_gitlab_mr_repo(tmp)
            try:
                old_sha = state.mrs[10]["diff_refs"]["head_sha"]
                gl_direct = forge.GitLabForge(
                    repo,
                    forge.RemoteSpec("http", f"127.0.0.1:{server.server_address[1]}", "127.0.0.1", server.server_address[1], "dept/sub/demo", state.base_url),
                    {"token": "glpat-secret"},
                )
                with self.assertRaises(forge.ForgeError) as ctx:
                    gl_direct.merge_squash(10, "fix: stale", "Closes #1", expected_sha="0000000000000000000000000000000000000000")
                self.assertEqual(ctx.exception.http_status, 409)
                state.merge_attempts = 0

                # Simulate GitLab async Sidekiq lag after `idd land` commits `git rm -rf TASK/...` and pushes
                state.stale_get_polls = 2
                state.merge_transient_failures = [(406, "Branch cannot be merged")]
                state.mr_get_calls = 0

                before = state.origin_sha("main")
                land_res = run_idd("land", "1")
                self.assertIn("已通过 Squash Merge 直线合入 MR !10", land_res.stdout)
                after = state.origin_sha("main")
                self.assertIn(f"已核对远端 `main` 只新增一条提交 `{after[:12]}`", land_res.stdout)
                self.assertEqual(state.mrs[10]["squash_commit_sha"], after)
                self.assertEqual(subprocess.check_output(
                    ["git", "-C", str(repo), "rev-list", "--parents", "-n", "1", "main"], text=True
                ).split(), [after, before])
                self.assertGreaterEqual(state.mr_get_calls, 3)
                self.assertEqual(state.merge_attempts, 2)

                wt_head = subprocess.check_output(["git", "-C", str(wt), "rev-parse", "HEAD"], text=True).strip()
                self.assertNotEqual(wt_head, old_sha)
                self.assertEqual(state.last_merge_payload.get("sha"), wt_head)
                self.assertTrue((repo / "app.py").is_file())
                self.assertFalse((repo / "TASK/1-async-land").exists())
            finally:
                server.shutdown()
                server.server_close()

    def test_gitlab_land_requires_fast_forward_and_mandatory_squash_before_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, wt, state, server, _, run_idd = self._setup_gitlab_mr_repo(tmp)
            try:
                before = state.origin_sha("main")
                original_mr = state.mrs[10].copy()
                for method, squash in (("ff", "never"), ("ff", "default_on"), ("merge", "always"), ("ff", None)):
                    with self.subTest(method=method, squash=squash):
                        state.project_settings.update(merge_method=method, squash_option=squash)
                        land = run_idd("land", "1", check=False)
                        self.assertNotEqual(land.returncode, 0)
                        self.assertIn("强制 Squash", land.stderr)
                        self.assertIn("idd repo-init --apply", land.stderr)
                        self.assertTrue((wt / "TASK/1-async-land").is_dir())
                        self.assertEqual(state.mrs[10], original_mr)
                        self.assertEqual(state.merge_attempts, 0)
                        self.assertEqual(state.origin_sha("main"), before)
            finally:
                server.shutdown()
                server.server_close()

    def test_gitlab_land_rejects_success_response_when_five_commits_reach_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, wt, state, server, _, run_idd = self._setup_gitlab_mr_repo(tmp)
            try:
                state.merge_without_squash = True
                before = state.origin_sha("main")
                for index in range(3):
                    subprocess.run(["git", "-C", str(wt), "commit", "--allow-empty", "-m", f"fix: change {index}"],
                                   check=True, capture_output=True)
                land = run_idd("land", "1", check=False)
                self.assertNotEqual(land.returncode, 0)
                self.assertIn("区间有 5 条提交", land.stderr)
                self.assertIn("GitLab 可能已经合入", land.stderr)
                self.assertNotIn("已通过 Squash Merge", land.stdout)
                self.assertEqual(state.mrs[10]["state"], "merged")
                self.assertIn("- [ ] 确认合入", state.issues[1]["description"])
                self.assertEqual(subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                                         text=True).strip(), before)
            finally:
                server.shutdown()
                server.server_close()

    def test_gitlab_auto_land_reports_pending_or_verified_result(self) -> None:
        for deferred in (True, False):
            with self.subTest(deferred=deferred), tempfile.TemporaryDirectory() as tmp:
                _, _, _, state, server, _, run_idd = self._setup_gitlab_mr_repo(tmp)
                try:
                    state.defer_auto_merge = deferred
                    before = state.origin_sha("main")
                    land = run_idd("land", "1", "--auto")
                    self.assertTrue(state.last_merge_payload["merge_when_pipeline_succeeds"])
                    if deferred:
                        self.assertEqual(state.origin_sha("main"), before)
                        self.assertIn("合入结果待确认", land.stdout)
                        self.assertNotIn("已通过 Squash Merge", land.stdout)
                        self.assertIn("- [ ] 确认合入", state.issues[1]["description"])
                    else:
                        self.assertIn("已核对远端 `main` 只新增一条提交", land.stdout)
                        self.assertIn("- [x] 确认合入", state.issues[1]["description"])
                finally:
                    server.shutdown()
                    server.server_close()

    def test_gitlab_land_fails_safely_when_head_sha_refresh_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, wt, state, server, env, run_idd = self._setup_gitlab_mr_repo(tmp)
            try:
                env["IDD_LAND_SYNC_TIMEOUT"] = "0.2"
                state.stale_get_polls = 99
                state.merge_attempts = 0

                land_res = run_idd("land", "1", check=False)
                self.assertEqual(land_res.returncode, 3)
                self.assertIn("超时", land_res.stderr)
                self.assertEqual(state.merge_attempts, 0)
                self.assertEqual(state.mrs[10]["state"], "opened")
                self.assertFalse((wt / "TASK/1-async-land").exists())
            finally:
                server.shutdown()
                server.server_close()

    def test_gitlab_first_time_repo_init_hint_prompts_once_and_aligns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = root / "origin.git"
            repo = root / "demo"
            config_dir = root / "config"

            subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
            state = MockGitLabState(origin)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
            port = server.server_address[1]
            base_url = f"http://127.0.0.1:{port}"
            state.base_url = base_url
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                remote_url = f"{base_url}/dept/sub/demo.git"
                subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
                subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
                (repo / "README.md").write_text("# GitLab Demo\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
                subprocess.run(["git", "-C", str(repo), "commit", "-m", "chore: init"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
                subprocess.run(["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

                subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", remote_url], check=True)
                subprocess.run(["git", "-C", str(repo), "config", f"url.{origin}.insteadOf", remote_url], check=True)
                subprocess.run(["git", "-C", str(repo), "fetch", "origin", "main"], check=True, capture_output=True)

                env = dict(os.environ)
                env["IDD_CONFIG_DIR"] = str(config_dir)
                env["IDD_NO_AUTO_UPDATE"] = "1"
                env.pop("IDD_WORKTREE_ROOT", None)
                env.pop("IDD_FORGE", None)
                env.pop("GITLAB_TOKEN", None)

                def run_idd(*args: str) -> subprocess.CompletedProcess[str]:
                    return subprocess.run(
                        [sys.executable, str(IDD_BIN), *args],
                        cwd=str(repo),
                        env=env,
                        capture_output=True,
                        text=True,
                        check=True,
                    )

                run_idd("auth", "login", f"http://127.0.0.1:{port}", "--token", "glpat-secret")

                first_out = run_idd("issue", "create", "--title", "feat: Init check", "--body", "desc").stdout
                self.assertIn("💡 首次接管提示", first_out)
                self.assertIn("GitLab", first_out)
                self.assertIn("merge_method=merge（建议 ff）", first_out)
                self.assertIn("squash_option=default_off（建议 always）", first_out)
                self.assertIn("idd repo-init --apply", first_out)

                repos_file = config_dir / "repos.json"
                repos_data = json.loads(repos_file.read_text(encoding="utf-8"))
                self.assertEqual(repos_data["repos"][0]["repo_init_state"], "prompted")

                second_out = run_idd("start", "1", "--slug", "init-check").stdout
                self.assertNotIn("💡 首次接管提示", second_out)

                run_idd("repo-init", "--apply")
                repos_after = json.loads(repos_file.read_text(encoding="utf-8"))
                self.assertEqual(repos_after["repos"][0]["repo_init_state"], "aligned")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
