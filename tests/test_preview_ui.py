"""Tests for `preview_ui` local prototype workbench server and registry."""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import preview_ui  # noqa: E402


class TestPreviewUI(unittest.TestCase):
    def _start_server(
        self,
        targets: list[str],
        *,
        title: str | None = None,
        compare: bool = False,
    ) -> tuple[preview_ui.PreviewHTTPServer, str]:
        registry = preview_ui.PreviewRegistry(targets, title=title, compare_default=compare)
        handler_cls = partial(preview_ui.PreviewRequestHandler, registry=registry, version="0.0.3-test")
        server = preview_ui.PreviewHTTPServer(("127.0.0.1", 0), handler_cls)  # type: ignore[arg-type]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(timeout=2)))
        host, port = server.server_address[:2]
        return server, f"http://{host}:{port}"

    def _get_json(self, url: str) -> tuple[int, dict]:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read().decode("utf-8"))

    def _get_text(self, url: str) -> tuple[int, str, str]:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers.get("Content-Type", ""), err.read().decode("utf-8")

    def test_single_file_title_extraction_and_hot_reload_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_file = Path(tmp) / "proto.html"
            html_file.write_text("<html><head><title>看板顶栏 &amp; 状态</title></head><body>v1</body></html>", encoding="utf-8")

            _, base = self._start_server([str(html_file)], title="自定义工作台")

            code, health = self._get_json(f"{base}/api/health")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertTrue(health["ok"])

            code, _, index_html = self._get_text(f"{base}/")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertIn("自定义工作台", index_html)
            self.assertIn("0.0.3-test", index_html)

            code, meta1 = self._get_json(f"{base}/api/meta")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertEqual(len(meta1["items"]), 1)
            item1 = meta1["items"][0]
            self.assertEqual(item1["label"], "看板顶栏 & 状态")
            self.assertTrue(item1["exists"])

            code, ctype, raw_body = self._get_text(f"{base}{item1['raw_url']}")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertIn("text/html", ctype)
            self.assertIn("v1", raw_body)

            # Modify file and confirm mtime/version_token change
            html_file.write_text("<html><head><title>看板顶栏 v2</title></head><body>v2</body></html>", encoding="utf-8")
            os.utime(html_file, ns=(item1["mtime_ns"] + 1_000_000_000, item1["mtime_ns"] + 1_000_000_000))
            code, meta2 = self._get_json(f"{base}/api/meta")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertNotEqual(meta2["version_token"], meta1["version_token"])
            self.assertEqual(meta2["items"][0]["label"], "看板顶栏 v2")

    def test_custom_labels_compare_mode_and_path_with_equals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p_a = Path(tmp) / "a.html"
            p_b = Path(tmp) / "a=b.html"
            p_a.write_text("<title>Inner Title</title><div>A</div>", encoding="utf-8")
            p_b.write_text("<title>Raw B</title><div>B</div>", encoding="utf-8")

            _, base = self._start_server([f"方案A={p_a}", str(p_b)], compare=True)
            code, meta = self._get_json(f"{base}/api/meta")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertTrue(meta["compare_default"])
            self.assertEqual([it["label"] for it in meta["items"]], ["方案A", "Raw B"])

    def test_directory_watch_missing_recovery_and_asset_traversal_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch_dir = root / "protos"
            watch_dir.mkdir()
            secret = root / "secret.txt"
            secret.write_text("TOP_SECRET", encoding="utf-8")

            css = watch_dir / "style.css"
            css.write_text("body { color: red; }", encoding="utf-8")
            page1 = watch_dir / "01-first.html"
            page1.write_text("<link rel='stylesheet' href='style.css'><h1>First</h1>", encoding="utf-8")

            # Also create symlink inside watch_dir escaping outside
            escape_link = watch_dir / "escape.txt"
            escape_link.symlink_to(secret)

            _, base = self._start_server([str(watch_dir)])
            code, meta1 = self._get_json(f"{base}/api/meta")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertEqual([it["filename"] for it in meta1["items"]], ["01-first.html"])
            item_id = meta1["items"][0]["id"]

            # Same-dir asset allowed
            code, ctype, css_body = self._get_text(f"{base}/raw/{item_id}/style.css")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertIn("text/css", ctype)
            self.assertIn("color: red", css_body)

            # Parent traversal blocked with 403
            code, _, body = self._get_text(f"{base}/raw/{item_id}/../secret.txt")
            self.assertEqual(code, HTTPStatus.FORBIDDEN)
            self.assertNotIn("TOP_SECRET", body)

            # Symlink escape blocked with 403
            code, _, body = self._get_text(f"{base}/raw/{item_id}/escape.txt")
            self.assertEqual(code, HTTPStatus.FORBIDDEN)
            self.assertNotIn("TOP_SECRET", body)

            # Dynamically add second HTML file
            page2 = watch_dir / "02-second.html"
            page2.write_text("<title>Second</title><p>Two</p>", encoding="utf-8")
            code, meta2 = self._get_json(f"{base}/api/meta")
            self.assertEqual([it["filename"] for it in meta2["items"]], ["01-first.html", "02-second.html"])

    def test_explicit_file_deletion_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "ephemeral.html"
            page.write_text("<title>Temp</title><p>ok</p>", encoding="utf-8")
            _, base = self._start_server([str(page)])

            _, meta1 = self._get_json(f"{base}/api/meta")
            item_id = meta1["items"][0]["id"]
            self.assertTrue(meta1["items"][0]["exists"])

            page.unlink()
            code, meta2 = self._get_json(f"{base}/api/meta")
            self.assertEqual(code, HTTPStatus.OK)
            self.assertFalse(meta2["items"][0]["exists"])

            code, raw_err = self._get_json(f"{base}/raw/{item_id}")
            self.assertEqual(code, HTTPStatus.NOT_FOUND)
            self.assertIn("error", raw_err)

            page.write_text("<title>Recovered</title><p>back</p>", encoding="utf-8")
            code, meta3 = self._get_json(f"{base}/api/meta")
            self.assertTrue(meta3["items"][0]["exists"])
            self.assertEqual(meta3["items"][0]["label"], "Recovered")

    def test_missing_initial_target_raises_preview_error(self) -> None:
        with self.assertRaises(preview_ui.PreviewError):
            preview_ui.PreviewRegistry(["/path/definitely/missing/proto.html"])

    def test_inline_script_syntax_valid(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available for inline script syntax check")
        match = re.search(r"<script>(.*)</script>", preview_ui.PREVIEW_HTML, re.S)
        self.assertIsNotNone(match)
        script_src = (
            match.group(1)
            .replace("__DEFAULT_COMPARE__", "false")
            .replace("__IDD_VERSION__", "0.0.3")
            .replace("__PREVIEW_TITLE__", "Test")
        )
        with tempfile.TemporaryDirectory() as tmp:
            js_file = Path(tmp) / "preview.js"
            js_file.write_text(script_src, encoding="utf-8")
            proc = subprocess.run([node, "--check", str(js_file)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cli_preview_help_and_missing_target_error(self) -> None:
        idd_bin = SCRIPTS_DIR / "idd"
        help_proc = subprocess.run(
            [sys.executable, str(idd_bin), "preview", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
        self.assertIn("--compare", help_proc.stdout)
        self.assertIn("--no-open", help_proc.stdout)

        err_proc = subprocess.run(
            [sys.executable, str(idd_bin), "preview", "/tmp/definitely-missing-idd-preview-target.html", "--no-open"],
            capture_output=True,
            text=True,
            env={**os.environ, "IDD_NO_AUTO_UPDATE": "1"},
        )
        self.assertNotEqual(err_proc.returncode, 0)
        combined = err_proc.stdout + err_proc.stderr
        self.assertIn("找不到预览目标文件或目录", combined)


if __name__ == "__main__":
    unittest.main()
