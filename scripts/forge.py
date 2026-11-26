#!/usr/bin/env python3
"""Dual-forge adapter supporting GitHub (`gh`) and self-hosted GitLab (REST v4 / `glab`)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


FAIL_CONCLUSIONS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE"}
PASS_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
GITLAB_PASS_STATUSES = {"success", "skipped", "manual"}
GITLAB_FAIL_STATUSES = {"failed", "canceled"}


class ForgeError(Exception):
    """Error raised when communicating with GitHub/GitLab or resolving forge credentials."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ForgeAuthError(ForgeError):
    """Error raised when a remote forge host is missing or rejecting authentication."""

    def __init__(
        self,
        message: str,
        *,
        host: str = "",
        api_base: str = "",
        forge_type: str = "gitlab",
        login_cmd: str = "",
        token_url: str = "",
        exit_code: int = 1,
    ) -> None:
        super().__init__(message, exit_code=exit_code)
        self.host = host
        self.api_base = api_base
        self.forge_type = forge_type
        self.login_cmd = login_cmd
        self.token_url = token_url


@dataclass(frozen=True)
class RemoteSpec:
    """Parsed Git remote coordinates for GitHub or self-hosted GitLab."""

    scheme: str
    host: str
    hostname: str
    port: int | None
    project_path: str
    api_base: str


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ForgeError(f"找不到可执行文件 `{args[0]}`，请确认已安装并在 PATH 中。") from exc
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}"
        raise ForgeError(f"命令 `{' '.join(args)}` 执行失败：{detail}")
    return proc


def parse_remote_url(url: str) -> RemoteSpec | None:
    """Parse HTTPS, HTTP, ssh://, or SCP-style git remote URL into a RemoteSpec."""
    raw = url.strip()
    if not raw or raw.startswith(("file://", "/", "./", "../")):
        return None

    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return None
        path = parsed.path.lstrip("/").rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if not path:
            return None
        if scheme in ("http", "https"):
            port = parsed.port
            host = f"{hostname}:{port}" if port else hostname
            api_base = f"{scheme}://{host}"
            return RemoteSpec(
                scheme=scheme,
                host=host,
                hostname=hostname,
                port=port,
                project_path=path,
                api_base=api_base,
            )
        # ssh://[user@]host[:ssh_port]/group/repo — do NOT leak SSH port into HTTP API URL
        return RemoteSpec(
            scheme=scheme,
            host=hostname,
            hostname=hostname,
            port=None,
            project_path=path,
            api_base=f"https://{hostname}",
        )

    scp_match = re.match(r"^(?:[^/@:\s]+@)?([^:/\s]+):(.+)$", raw)
    if scp_match:
        hostname = scp_match.group(1).lower()
        path = scp_match.group(2).lstrip("/").rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if not path:
            return None
        return RemoteSpec(
            scheme="ssh",
            host=hostname,
            hostname=hostname,
            port=None,
            project_path=path,
            api_base=f"https://{hostname}",
        )
    return None


def get_config_dir() -> Path:
    override = os.environ.get("IDD_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".config" / "idd").resolve()


def get_hosts_path() -> Path:
    return get_config_dir() / "hosts.json"


def load_hosts_config() -> dict[str, dict[str, str]]:
    path = get_hosts_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_hosts_config(data: dict[str, dict[str, str]]) -> None:
    path = get_hosts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(prefix="hosts-", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def normalize_host_input(host_or_url: str, *, use_http: bool = False) -> tuple[str, str]:
    """Normalize host or URL input into (host_key, api_base)."""
    raw = host_or_url.strip().rstrip("/")
    if not raw:
        raise ForgeError("请提供有效的主机名或 URL。")
    if raw.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(raw)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ForgeError(f"无法解析主机地址：{host_or_url}")
        host_key = f"{hostname}:{parsed.port}" if parsed.port else hostname
        scheme = "http" if use_http else parsed.scheme.lower()
        return host_key, f"{scheme}://{host_key}"
    host_key = raw.split("/", 1)[0].lower()
    scheme = "http" if use_http else "https"
    return host_key, f"{scheme}://{host_key}"


def verify_host_token(forge_type: str, api_base: str, token: str) -> str:
    """Verify a Personal Access Token against GitLab or GitHub API; return username."""
    if forge_type == "github":
        base = "https://api.github.com" if api_base.rstrip("/") == "https://github.com" else f"{api_base.rstrip('/')}/api/v3"
        url = f"{base}/user"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "idd-cli",
        }
    else:
        url = f"{api_base.rstrip('/')}/api/v4/user"
        headers = {
            "PRIVATE-TOKEN": token,
            "Accept": "application/json",
            "User-Agent": "idd-cli",
        }

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return str(payload.get("username") or payload.get("login") or "authenticated")
    except urllib.error.HTTPError as exc:
        raise ForgeError(f"Token 校验失败（HTTP {exc.code}）：请检查 Token 权限与主机地址 {api_base}。") from exc
    except urllib.error.URLError as exc:
        raise ForgeError(f"无法连接 {api_base}：{exc.reason}") from exc


def parse_number_from_url(url: str) -> int | None:
    match = re.search(r"/(?:issues|merge_requests|pull)/(\d+)(?:[/?#].*)?$", url.strip())
    return int(match.group(1)) if match else None


def _classify_github_checks(rollup: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]], list[str]]:
    if not rollup:
        return "NONE", [], []
    checks: list[dict[str, str]] = []
    failed_runs: list[str] = []
    has_fail = False
    has_pending = False

    for item in rollup:
        name = item.get("name") or item.get("context") or "check"
        status = (item.get("status") or "").upper()
        conclusion = (item.get("conclusion") or item.get("state") or "").upper()
        url = item.get("detailsUrl") or item.get("targetUrl") or ""

        if conclusion in FAIL_CONCLUSIONS or conclusion == "ERROR":
            verdict = "FAIL"
            has_fail = True
            run_match = re.search(r"/actions/runs/(\d+)", url)
            if run_match and run_match.group(1) not in failed_runs:
                failed_runs.append(run_match.group(1))
        elif status and status != "COMPLETED" and not conclusion:
            verdict = "PENDING"
            has_pending = True
        elif conclusion in PASS_CONCLUSIONS or status == "COMPLETED":
            verdict = "PASS"
        elif conclusion == "PENDING" or not conclusion:
            verdict = "PENDING"
            has_pending = True
        else:
            verdict = conclusion

        checks.append({"name": name, "verdict": verdict, "url": url})

    overall = "FAIL" if has_fail else ("PENDING" if has_pending else "PASS")
    return overall, checks, failed_runs


class GitHubForge:
    """GitHub backend powered by the `gh` CLI."""

    forge_type = "github"
    mr_label = "PR"
    mr_prefix = "#"

    def __init__(
        self,
        cwd: Path,
        spec: RemoteSpec | None = None,
        host_cfg: dict[str, str] | None = None,
    ) -> None:
        self.cwd = cwd
        self.spec = spec
        self.host_cfg = host_cfg or {}
        self.token = self.host_cfg.get("token", "").strip()

    def _gh_env(self) -> dict[str, str] | None:
        if not self.token:
            return None
        env = dict(os.environ)
        if self.spec and self.spec.hostname and self.spec.hostname != "github.com":
            env["GH_ENTERPRISE_TOKEN"] = self.token
        else:
            env["GH_TOKEN"] = self.token
        return env

    def _gh_json(self, args: list[str], *, check: bool = True) -> Any:
        proc = _run(["gh", *args], cwd=self.cwd, check=check, env=self._gh_env())
        if proc.returncode != 0:
            return None
        raw = proc.stdout.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ForgeError(f"无法解析 gh 输出的 JSON：{exc}") from exc

    def _normalize_issue(self, raw: dict[str, Any]) -> dict[str, Any]:
        labels = []
        for lbl in raw.get("labels") or []:
            if isinstance(lbl, dict):
                labels.append(str(lbl.get("name", "")))
            else:
                labels.append(str(lbl))
        return {
            "number": raw["number"],
            "title": raw.get("title", ""),
            "body": raw.get("body") or "",
            "labels": [x for x in labels if x],
            "state": (raw.get("state") or "OPEN").upper(),
            "url": raw.get("url", ""),
        }

    def _normalize_pr(self, raw: dict[str, Any]) -> dict[str, Any]:
        rollup = raw.get("statusCheckRollup") or []
        overall, checks, failed_ids = _classify_github_checks(rollup)
        return {
            "number": raw["number"],
            "title": raw.get("title", ""),
            "body": raw.get("body") or "",
            "url": raw.get("url", ""),
            "state": (raw.get("state") or "OPEN").upper(),
            "baseRefName": raw.get("baseRefName", ""),
            "headRefName": raw.get("headRefName", ""),
            "headRefOid": raw.get("headRefOid", ""),
            "isDraft": bool(raw.get("isDraft")),
            "mergeStateStatus": raw.get("mergeStateStatus") or "UNKNOWN",
            "checks_overall": overall,
            "checks": checks,
            "failed_log_ids": failed_ids,
        }

    def create_issue(
        self,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        args = ["gh", "issue", "create", "--title", title]
        tmp_path: Path | None = None
        try:
            if body is not None:
                fd, raw_path = tempfile.mkstemp(prefix="idd-issue-", suffix=".md")
                tmp_path = Path(raw_path)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(body)
                args.extend(["--body-file", str(tmp_path)])
            for label in labels or []:
                args.extend(["--label", label])
            for assignee in assignees or []:
                args.extend(["--assignee", assignee])
            proc = _run(args, cwd=self.cwd, env=self._gh_env())
            url = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
            return {"number": parse_number_from_url(url), "url": url, "title": title}
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def get_issue(self, number: int, *, check: bool = True) -> dict[str, Any] | None:
        raw = self._gh_json(
            ["issue", "view", str(number), "--json", "number,title,body,labels,state,url"],
            check=check,
        )
        return self._normalize_issue(raw) if isinstance(raw, dict) else None

    def list_open_issues(self, limit: int = 100) -> list[dict[str, Any]] | None:
        proc = _run(
            ["gh", "issue", "list", "--state", "open", "--limit", str(limit), "--json", "number,title,labels,url"],
            cwd=self.cwd,
            check=False,
            env=self._gh_env(),
        )
        if proc.returncode != 0:
            stderr_low = (proc.stderr or "").lower()
            if any(k in stderr_low for k in ("gh auth login", "not logged into", "bad credentials", "http 401")):
                host_key = self.spec.host if self.spec else "github.com"
                api_base = (self.spec.api_base if self.spec else "https://github.com").rstrip("/")
                token_url = f"{api_base}/settings/tokens/new?description=IDD+Board&scopes=repo" if host_key != "github.com" else "https://github.com/settings/tokens/new?description=IDD+Board&scopes=repo"
                login_cmd = f"idd auth login {api_base} --forge github --token <你的 GitHub PAT>"
                raise ForgeAuthError(
                    f"访问 GitHub ({api_base}) 需要鉴权 Token。\n"
                    f"可在看板直接粘贴 Token 保存，或执行 `{login_cmd}`。",
                    host=host_key,
                    api_base=api_base,
                    forge_type="github",
                    login_cmd=login_cmd,
                    token_url=token_url,
                )
            return None
        raw_txt = proc.stdout.strip()
        if not raw_txt:
            return []
        try:
            raw = json.loads(raw_txt)
        except json.JSONDecodeError as exc:
            raise ForgeError(f"无法解析 gh 输出的 JSON：{exc}") from exc
        if not isinstance(raw, list):
            return None
        return [self._normalize_issue(item) for item in raw]

    def update_issue_body(self, number: int, body: str) -> None:
        fd, raw_path = tempfile.mkstemp(prefix="idd-sync-", suffix=".md")
        tmp_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            _run(["gh", "issue", "edit", str(number), "--body-file", str(tmp_path)], cwd=self.cwd, env=self._gh_env())
        finally:
            tmp_path.unlink(missing_ok=True)

    def list_changes(
        self,
        *,
        state: str = "open",
        head_branch: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]] | None:
        args = ["pr", "list", "--state", state, "--limit", str(limit)]
        if head_branch:
            args.extend(["--head", head_branch])
        args.extend([
            "--json",
            "number,title,body,url,state,baseRefName,headRefName,headRefOid,mergeStateStatus,isDraft,statusCheckRollup",
        ])
        raw = self._gh_json(args, check=False)
        if not isinstance(raw, list):
            return None
        return [self._normalize_pr(item) for item in raw]

    def create_change(self, base: str, head: str, title: str, body: str, draft: bool = False) -> dict[str, Any]:
        fd, raw_path = tempfile.mkstemp(prefix="idd-pr-", suffix=".md")
        tmp_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            args = [
                "gh",
                "pr",
                "create",
                "--base",
                base,
                "--head",
                head,
                "--title",
                title,
                "--body-file",
                str(tmp_path),
            ]
            if draft:
                args.append("--draft")
            proc = _run(args, cwd=self.cwd, env=self._gh_env())
            url = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
            return {"number": parse_number_from_url(url), "url": url, "title": title}
        finally:
            tmp_path.unlink(missing_ok=True)

    def update_change(self, number: int, title: str, body: str) -> dict[str, Any]:
        fd, raw_path = tempfile.mkstemp(prefix="idd-pr-", suffix=".md")
        tmp_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            proc = _run(
                ["gh", "pr", "edit", str(number), "--title", title, "--body-file", str(tmp_path)],
                cwd=self.cwd,
                env=self._gh_env(),
            )
            url = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
            return {"number": number, "url": url, "title": title}
        finally:
            tmp_path.unlink(missing_ok=True)

    def get_change(self, number: int | None = None, branch: str | None = None, *, check: bool = True) -> dict[str, Any] | None:
        if number is None and branch:
            items = self.list_changes(state="open", head_branch=branch, limit=1)
            return items[0] if items else None
        args = ["pr", "view"]
        if number is not None:
            args.append(str(number))
        args.extend([
            "--json",
            "number,title,body,url,state,baseRefName,headRefName,headRefOid,mergeStateStatus,isDraft,statusCheckRollup",
        ])
        raw = self._gh_json(args, check=check)
        return self._normalize_pr(raw) if isinstance(raw, dict) else None

    def get_failed_logs(self, log_ids: list[str]) -> dict[str, str]:
        logs: dict[str, str] = {}
        for run_id in log_ids:
            proc = _run(["gh", "run", "view", run_id, "--log-failed"], cwd=self.cwd, check=False, env=self._gh_env())
            if proc.returncode == 0 and proc.stdout:
                logs[run_id] = "\n".join(proc.stdout.splitlines()[-150:])
        return logs

    def watch_checks(self, number: int | None = None) -> int:
        cmd = ["gh", "pr", "checks"]
        if number is not None:
            cmd.append(str(number))
        cmd.append("--watch")
        return subprocess.run(cmd, cwd=str(self.cwd), env=self._gh_env()).returncode

    def merge_squash(self, number: int, title: str, body: str, *, auto: bool = False) -> None:
        fd, raw_path = tempfile.mkstemp(prefix="idd-merge-", suffix=".md")
        tmp_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            args = [
                "gh",
                "pr",
                "merge",
                str(number),
                "--squash",
                "--subject",
                title,
                "--body-file",
                str(tmp_path),
            ]
            if auto:
                args.insert(4, "--auto")
            _run(args, cwd=self.cwd, env=self._gh_env())
        finally:
            tmp_path.unlink(missing_ok=True)

    def repo_init(self, *, apply: bool = False) -> dict[str, Any]:
        if apply:
            data = self._gh_json([
                "api",
                "-X",
                "PATCH",
                "repos/{owner}/{repo}",
                "-F",
                "allow_merge_commit=false",
                "-F",
                "allow_squash_merge=true",
                "-F",
                "delete_branch_on_merge=false",
            ])
        else:
            data = self._gh_json(["api", "repos/{owner}/{repo}"])
        return {
            "forge": "github",
            "repo": data.get("full_name", ""),
            "settings": {
                "allow_merge_commit": data.get("allow_merge_commit"),
                "allow_squash_merge": data.get("allow_squash_merge"),
                "allow_rebase_merge": data.get("allow_rebase_merge"),
                "delete_branch_on_merge": data.get("delete_branch_on_merge"),
                "allow_auto_merge": data.get("allow_auto_merge"),
            },
        }


class GitLabForge:
    """Self-hosted (or gitlab.com) GitLab backend via REST API v4 with optional `glab` fallback."""

    forge_type = "gitlab"
    mr_label = "MR"
    mr_prefix = "!"

    def __init__(
        self,
        cwd: Path,
        spec: RemoteSpec | None,
        host_cfg: dict[str, str] | None = None,
    ) -> None:
        self.cwd = cwd
        self.spec = spec
        self.host_cfg = host_cfg or {}

        env_url = os.environ.get("IDD_GITLAB_URL", "").strip()
        if self.host_cfg.get("api_url"):
            self.api_base = self.host_cfg["api_url"].rstrip("/")
        elif env_url:
            self.api_base = env_url.rstrip("/")
        elif spec is not None:
            self.api_base = spec.api_base.rstrip("/")
        else:
            self.api_base = ""

        project_path = os.environ.get("IDD_GITLAB_PROJECT", "").strip() or (spec.project_path if spec else "")
        self.project_path = project_path
        self.encoded_project = urllib.parse.quote(project_path, safe="")
        self.hostname = spec.hostname if spec else (urllib.parse.urlparse(self.api_base).hostname or "")
        self.token = (
            self.host_cfg.get("token", "").strip()
            or os.environ.get("GITLAB_TOKEN", "").strip()
            or os.environ.get("GITLAB_PRIVATE_TOKEN", "").strip()
        )
        self.has_glab = bool(shutil.which("glab"))

    def _require_project(self) -> None:
        if not self.project_path or not self.api_base:
            raise ForgeError("无法解析 GitLab 仓库路径或 API 地址，请检查 `origin` 远端或先运行 `idd auth login`。")

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        raw_text: bool = False,
        check: bool = True,
    ) -> Any:
        self._require_project()
        if not self.token and self.has_glab and not raw_text:
            return self._request_via_glab(method, path, query=query, json_body=json_body, check=check)

        if not self.token:
            host_label = self.spec.host if self.spec else self.api_base
            login_target = self.api_base or host_label
            login_cmd = f"idd auth login {login_target} --token <你的 GitLab PAT>"
            token_url = (
                f"{self.api_base}/-/user_settings/personal_access_tokens?name=IDD+Board&scopes=api"
                if self.api_base
                else ""
            )
            raise ForgeAuthError(
                f"访问自建 GitLab ({self.api_base}) 需要鉴权 Token。\n"
                f"请执行 `{login_cmd}` 或设置环境变量 `GITLAB_TOKEN`。",
                host=host_label,
                api_base=self.api_base,
                forge_type="gitlab",
                login_cmd=login_cmd,
                token_url=token_url,
            )

        url = f"{self.api_base}/api/v4{path}"
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                url = f"{url}?{urllib.parse.urlencode(filtered)}"

        data_bytes = None
        headers = {
            "PRIVATE-TOKEN": self.token,
            "Accept": "text/plain" if raw_text else "application/json",
            "User-Agent": "idd-cli",
        }
        if json_body is not None:
            data_bytes = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw_bytes = resp.read()
                text = raw_bytes.decode("utf-8", errors="replace")
                if raw_text:
                    return text
                return json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            if not check:
                return None
            detail = err_body
            try:
                parsed_err = json.loads(err_body)
                detail = str(parsed_err.get("message") or parsed_err.get("error") or err_body)
            except json.JSONDecodeError:
                pass
            if exc.code in (401, 403):
                host_label = self.spec.host if self.spec else self.api_base
                login_target = self.api_base or host_label
                login_cmd = f"idd auth login {login_target} --token <PAT>"
                token_url = (
                    f"{self.api_base}/-/user_settings/personal_access_tokens?name=IDD+Board&scopes=api"
                    if self.api_base
                    else ""
                )
                raise ForgeAuthError(
                    f"GitLab 鉴权失败（HTTP {exc.code}）：{detail}\n"
                    f"请检查或重新登录：`{login_cmd}`",
                    host=host_label,
                    api_base=self.api_base,
                    forge_type="gitlab",
                    login_cmd=login_cmd,
                    token_url=token_url,
                ) from exc
            raise ForgeError(f"GitLab API 请求失败（HTTP {exc.code} {method} {path}）：{detail}") from exc
        except urllib.error.URLError as exc:
            if not check:
                return None
            raise ForgeError(f"无法连接 GitLab ({self.api_base})：{exc.reason}") from exc

    def _request_via_glab(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        check: bool = True,
    ) -> Any:
        endpoint = path.lstrip("/")
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                endpoint = f"{endpoint}?{urllib.parse.urlencode(filtered)}"
        args = ["glab", "api", endpoint, "-X", method]
        if self.hostname:
            args.extend(["--hostname", self.hostname])
        if json_body is not None:
            for key, val in json_body.items():
                if isinstance(val, bool):
                    args.extend(["-F", f"{key}={'true' if val else 'false'}"])
                else:
                    args.extend(["-f", f"{key}={val}"])
        proc = _run(args, cwd=self.cwd, check=check)
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def _normalize_issue(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": raw["iid"],
            "title": raw.get("title", ""),
            "body": raw.get("description") or "",
            "labels": [str(x) for x in (raw.get("labels") or [])],
            "state": "OPEN" if raw.get("state") == "opened" else "CLOSED",
            "url": raw.get("web_url", ""),
        }

    def _classify_pipeline(self, mr: dict[str, Any], *, fetch_jobs: bool) -> tuple[str, list[dict[str, str]], list[str]]:
        pipeline = mr.get("head_pipeline") or mr.get("pipeline")
        if not pipeline and fetch_jobs:
            pipelines = self._request(
                "GET",
                f"/projects/{self.encoded_project}/merge_requests/{mr['iid']}/pipelines",
                check=False,
            )
            if isinstance(pipelines, list) and pipelines:
                pipeline = pipelines[0]
        if not isinstance(pipeline, dict) or not pipeline.get("id"):
            return "NONE", [], []

        pid = pipeline["id"]
        jobs = self._request(
            "GET",
            f"/projects/{self.encoded_project}/pipelines/{pid}/jobs",
            query={"per_page": 100},
            check=False,
        )
        if isinstance(jobs, list) and jobs:
            checks: list[dict[str, str]] = []
            failed_ids: list[str] = []
            has_fail = False
            has_pending = False
            for job in jobs:
                name = str(job.get("name") or "job")
                st = str(job.get("status") or "").lower()
                url = str(job.get("web_url") or "")
                allow_failure = bool(job.get("allow_failure"))
                if st in GITLAB_FAIL_STATUSES and not allow_failure:
                    verdict = "FAIL"
                    has_fail = True
                    failed_ids.append(str(job["id"]))
                elif st in GITLAB_PASS_STATUSES or (st in GITLAB_FAIL_STATUSES and allow_failure):
                    verdict = "PASS"
                else:
                    verdict = "PENDING"
                    has_pending = True
                checks.append({"name": name, "verdict": verdict, "url": url})
            overall = "FAIL" if has_fail else ("PENDING" if has_pending else "PASS")
            return overall, checks, failed_ids

        p_status = str(pipeline.get("status") or "").lower()
        p_url = str(pipeline.get("web_url") or "")
        if p_status in GITLAB_FAIL_STATUSES:
            return "FAIL", [{"name": f"pipeline #{pid}", "verdict": "FAIL", "url": p_url}], []
        if p_status in GITLAB_PASS_STATUSES:
            return "PASS", [{"name": f"pipeline #{pid}", "verdict": "PASS", "url": p_url}], []
        return "PENDING", [{"name": f"pipeline #{pid}", "verdict": "PENDING", "url": p_url}], []

    def _normalize_mr(self, raw: dict[str, Any], *, fetch_jobs: bool = True) -> dict[str, Any]:
        gl_state = str(raw.get("state") or "opened").lower()
        if gl_state == "merged":
            state = "MERGED"
        elif gl_state == "closed":
            state = "CLOSED"
        else:
            state = "OPEN"

        detailed = str(raw.get("detailed_merge_status") or "").lower()
        if raw.get("has_conflicts") or detailed == "conflict":
            merge_state = "DIRTY"
        elif detailed in {"need_rebase", "not_open"}:
            merge_state = "BEHIND"
        else:
            merge_state = "CLEAN"

        title = raw.get("title", "")
        is_draft = bool(raw.get("draft") or raw.get("work_in_progress") or title.startswith(("Draft:", "WIP:")))
        diff_refs = raw.get("diff_refs") or {}
        head_oid = str(raw.get("sha") or diff_refs.get("head_sha") or "")

        if state == "MERGED":
            overall, checks, failed_ids = "NONE", [], []
        else:
            overall, checks, failed_ids = self._classify_pipeline(raw, fetch_jobs=fetch_jobs)

        return {
            "number": raw["iid"],
            "title": title,
            "body": raw.get("description") or "",
            "url": raw.get("web_url", ""),
            "state": state,
            "baseRefName": raw.get("target_branch", ""),
            "headRefName": raw.get("source_branch", ""),
            "headRefOid": head_oid,
            "isDraft": is_draft,
            "mergeStateStatus": merge_state,
            "checks_overall": overall,
            "checks": checks,
            "failed_log_ids": failed_ids,
        }

    def create_issue(
        self,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title}
        if body is not None:
            payload["description"] = body
        if labels:
            payload["labels"] = ",".join(labels)
        if assignees:
            assignee_ids: list[int] = []
            for uname in assignees:
                users = self._request("GET", "/users", query={"username": uname}, check=False)
                if isinstance(users, list) and users and users[0].get("id"):
                    assignee_ids.append(int(users[0]["id"]))
            if assignee_ids:
                payload["assignee_ids"] = assignee_ids
        resp = self._request("POST", f"/projects/{self.encoded_project}/issues", json_body=payload)
        return {"number": resp["iid"], "url": resp.get("web_url", ""), "title": resp.get("title", title)}

    def get_issue(self, number: int, *, check: bool = True) -> dict[str, Any] | None:
        resp = self._request("GET", f"/projects/{self.encoded_project}/issues/{number}", check=check)
        return self._normalize_issue(resp) if isinstance(resp, dict) else None

    def list_open_issues(self, limit: int = 100) -> list[dict[str, Any]] | None:
        resp = self._request(
            "GET",
            f"/projects/{self.encoded_project}/issues",
            query={"state": "opened", "per_page": limit},
            check=False,
        )
        if not isinstance(resp, list):
            return None
        return [self._normalize_issue(item) for item in resp]

    def update_issue_body(self, number: int, body: str) -> None:
        self._request("PUT", f"/projects/{self.encoded_project}/issues/{number}", json_body={"description": body})

    def list_changes(
        self,
        *,
        state: str = "open",
        head_branch: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]] | None:
        gl_state = {"open": "opened", "merged": "merged", "all": "all"}.get(state, "opened")
        resp = self._request(
            "GET",
            f"/projects/{self.encoded_project}/merge_requests",
            query={"state": gl_state, "source_branch": head_branch, "per_page": limit},
            check=False,
        )
        if not isinstance(resp, list):
            return None
        return [self._normalize_mr(item, fetch_jobs=(state != "merged")) for item in resp]

    def create_change(self, base: str, head: str, title: str, body: str, draft: bool = False) -> dict[str, Any]:
        mr_title = f"Draft: {title}" if (draft and not title.startswith("Draft:")) else title
        resp = self._request(
            "POST",
            f"/projects/{self.encoded_project}/merge_requests",
            json_body={
                "source_branch": head,
                "target_branch": base,
                "title": mr_title,
                "description": body,
                "squash": True,
                "remove_source_branch": False,
            },
        )
        return {"number": resp["iid"], "url": resp.get("web_url", ""), "title": resp.get("title", mr_title)}

    def update_change(self, number: int, title: str, body: str) -> dict[str, Any]:
        resp = self._request(
            "PUT",
            f"/projects/{self.encoded_project}/merge_requests/{number}",
            json_body={"title": title, "description": body},
        )
        return {"number": resp["iid"], "url": resp.get("web_url", ""), "title": resp.get("title", title)}

    def get_change(self, number: int | None = None, branch: str | None = None, *, check: bool = True) -> dict[str, Any] | None:
        if number is None:
            if not branch:
                return None
            items = self.list_changes(state="open", head_branch=branch, limit=1)
            if not items:
                return None
            number = items[0]["number"]
        resp = self._request(
            "GET",
            f"/projects/{self.encoded_project}/merge_requests/{number}",
            check=check,
        )
        return self._normalize_mr(resp, fetch_jobs=True) if isinstance(resp, dict) else None

    def get_failed_logs(self, log_ids: list[str]) -> dict[str, str]:
        logs: dict[str, str] = {}
        for job_id in log_ids:
            trace = self._request(
                "GET",
                f"/projects/{self.encoded_project}/jobs/{job_id}/trace",
                raw_text=True,
                check=False,
            )
            if isinstance(trace, str) and trace.strip():
                logs[job_id] = "\n".join(trace.splitlines()[-150:])
        return logs

    def watch_checks(self, number: int | None = None) -> int:
        # Non-blocking fallback / simple poll message when glab watch isn't used
        if self.has_glab and not self.token and number is not None:
            return subprocess.run(["glab", "mr", "view", str(number)], cwd=str(self.cwd)).returncode
        return 0

    def merge_squash(self, number: int, title: str, body: str, *, auto: bool = False) -> None:
        self._request(
            "PUT",
            f"/projects/{self.encoded_project}/merge_requests/{number}/merge",
            json_body={
                "squash": True,
                "squash_commit_message": f"{title}\n\n{body}",
                "should_remove_source_branch": False,
                "merge_when_pipeline_succeeds": bool(auto),
            },
        )

    def repo_init(self, *, apply: bool = False) -> dict[str, Any]:
        if apply:
            data = self._request(
                "PUT",
                f"/projects/{self.encoded_project}",
                json_body={
                    "merge_method": "ff",
                    "squash_option": "always",
                    "remove_source_branch_after_merge": False,
                },
            )
        else:
            data = self._request("GET", f"/projects/{self.encoded_project}")
        return {
            "forge": "gitlab",
            "repo": data.get("path_with_namespace", self.project_path),
            "settings": {
                "merge_method": data.get("merge_method"),
                "squash_option": data.get("squash_option"),
                "remove_source_branch_after_merge": data.get("remove_source_branch_after_merge"),
            },
        }


def build_repo_web_url(spec: RemoteSpec | None, forge_type: str) -> str:
    """Build clickable GitHub or GitLab repository homepage URL when remote coordinates exist."""
    if spec is None or not spec.project_path:
        return ""
    if forge_type in ("github", "gitlab"):
        return f"{spec.api_base.rstrip('/')}/{spec.project_path}"
    return ""


def build_issue_web_url(spec: RemoteSpec | None, forge_type: str, issue_number: int) -> str:
    """Build clickable GitHub or GitLab web URL for an Issue number when remote coordinates exist."""
    if spec is None or not spec.project_path:
        return ""
    base = spec.api_base.rstrip("/")
    if forge_type == "github":
        return f"{base}/{spec.project_path}/issues/{issue_number}"
    if forge_type == "gitlab":
        return f"{base}/{spec.project_path}/-/issues/{issue_number}"
    return ""


def _resolve_origin_context(main_worktree: Path) -> tuple[RemoteSpec | None, str, dict[str, str] | None]:
    origin_proc = _run(
        ["git", "--no-optional-locks", "-C", str(main_worktree), "config", "--get", "remote.origin.url"],
        check=False,
    )
    if origin_proc.returncode != 0 or not origin_proc.stdout.strip():
        origin_proc = _run(
            ["git", "--no-optional-locks", "-C", str(main_worktree), "remote", "get-url", "origin"],
            check=False,
        )
    origin_url = origin_proc.stdout.strip() if origin_proc.returncode == 0 else ""
    spec = parse_remote_url(origin_url)

    env_forge = os.environ.get("IDD_FORGE", "").strip().lower()
    hosts = load_hosts_config()
    host_cfg = (hosts.get(spec.host) or hosts.get(spec.hostname)) if spec else None
    if spec is not None and host_cfg and host_cfg.get("api_url"):
        api_override = host_cfg["api_url"].rstrip("/")
        if api_override:
            spec = RemoteSpec(
                scheme=spec.scheme,
                host=spec.host,
                hostname=spec.hostname,
                port=spec.port,
                project_path=spec.project_path,
                api_base=api_override,
            )

    if env_forge in ("github", "gitlab"):
        return spec, env_forge, host_cfg
    if spec is None:
        return None, "local", host_cfg
    if host_cfg and host_cfg.get("forge") in ("github", "gitlab"):
        return spec, str(host_cfg["forge"]), host_cfg
    if spec.hostname == "github.com" or spec.hostname.endswith(".github.com"):
        return spec, "github", host_cfg
    return spec, "gitlab", host_cfg


def inspect_remote_origin(main_worktree: Path) -> tuple[RemoteSpec | None, str]:
    """Return `(RemoteSpec | None, forge_type)` where `forge_type` is `github`, `gitlab`, or `local`."""
    spec, forge_type, _ = _resolve_origin_context(main_worktree)
    return spec, forge_type


def get_forge(main_worktree: Path) -> GitHubForge | GitLabForge:
    """Auto-detect GitHub vs self-hosted GitLab from `origin` URL, config, and overrides."""
    spec, forge_type, host_cfg = _resolve_origin_context(main_worktree)
    if forge_type == "gitlab":
        return GitLabForge(main_worktree, spec, host_cfg)
    return GitHubForge(main_worktree, spec, host_cfg)
