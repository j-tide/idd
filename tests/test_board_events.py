"""Behavior of the shared board SSE feed through its HTTP and subscriber interfaces."""

from __future__ import annotations

from functools import partial
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from board_events import BoardEvents, sample_interval
from board_ui import BOARD_HTML, BoardRequestHandler
from local_http import LocalHTTPServer
from monitor import ForgeSnapshotCache


def read_frame(response):
    lines = []
    while True:
        line = response.readline()
        if not line:
            raise EOFError("SSE closed")
        if line == b"\n":
            return b"".join(lines)
        lines.append(line)


def read_event(response):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        frame = read_frame(response)
        if not frame.startswith(b":"):
            event, data = frame.decode().splitlines()
            return event.removeprefix("event: "), json.loads(data.removeprefix("data: "))
    raise TimeoutError("no SSE data event")


class TestBoardEvents(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for EventSource lifecycle checks")
    def test_browser_reconnect_does_not_revive_a_closed_or_hidden_subscription(self):
        handlers = BOARD_HTML[BOARD_HTML.index("      function stopStream()"):BOARD_HTML.index("      async function fetchSnapshot(")]
        lifecycle = BOARD_HTML[BOARD_HTML.index('      document.addEventListener("visibilitychange"'):BOARD_HTML.index('      window.addEventListener("pagehide"')]
        harness = r"""
const assert = require("node:assert/strict");
const state = { snapshot: {}, stream: null };
const sources = [], timers = new Map(), snapshots = [];
let timerId = 0;
const document = { hidden: false, documentElement: { classList: {toggle() {}} },
  addEventListener(type, cb) { this[type] = cb; } };
function setTimeout(cb) { timers.set(++timerId, cb); return timerId; }
function clearTimeout(id) { timers.delete(id); }
function updateConnectionBadge() {}
function updateActivityTimes() {}
function tr(zh) { return zh; }
function applySnapshot(snap) { snapshots.push(snap); return true; }
class EventSource {
  static CLOSED = 2;
  constructor(url) { assert.equal(url, "/api/events"); sources.push(this); this.readyState = 1; }
  addEventListener(name, fn) { this[name] = fn; }
  close() { this.readyState = EventSource.CLOSED; }
}
"""
        checks = r"""
connectStream();
connectStream();
assert.equal(sources.length, 1);
const first = sources[0];
first.snapshot({data: '{"step":1}'});
assert.equal(state.streamStatus, "live");
first.readyState = 0; // Native EventSource is already reconnecting.
first.onerror();
assert.equal(state.streamStatus, "reconnecting");
assert.equal(timers.size, 0);
first.readyState = EventSource.CLOSED;
first.onerror();
assert.equal(timers.size, 1);
document.hidden = true;
document.visibilitychange();
assert.equal(timers.size, 0);
first.snapshot({data: '{"step":2}'});
state.paused = true;
document.hidden = false;
document.visibilitychange();
assert.equal(sources.length, 1);
state.paused = false;
connectStream();
sources[1].snapshot({data: '{"step":3}'});
assert.deepEqual(snapshots, [{step:1}, {step:3}]);
"""
        result = subprocess.run(["node", "-"], input=harness + handlers + lifecycle + checks,
                                capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_http_stream_deduplicates_and_recovers(self):
        clock = 100
        stage = "运行中"
        fail = False
        resampled = threading.Event()

        def collect():
            if fail:
                raise ValueError("读取失败\n稍后重试")
            if clock == 101:
                resampled.set()
            snapshot = {
                "summary": {}, "generated_at": clock, "forge_syncing": clock == 101,
                "repos": [{"forge_fetched_at": clock, "last_seen_at": clock}],
                "issues": [{"stage": stage, "pulse": {"idle_seconds": clock, "last_active_ago": str(clock),
                                                      "pulse_summary": str(clock), "activity_state": "warm"}}],
                "forge_connections": {"github": {"last_synced_at": clock, "syncing_repos": int(clock == 101)}},
            }
            return json.dumps(snapshot, ensure_ascii=False).encode()

        sampler = mock.Mock(side_effect=collect)
        feed = BoardEvents(sampler, heartbeat=0.1)
        handler = partial(BoardRequestHandler, cache=ForgeSnapshotCache(), root=None, global_mode=True,
                          local_only=True, version="test", events=feed)
        with LocalHTTPServer(("127.0.0.1", 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = "http://127.0.0.1:%d/api/events" % server.server_port
            try:
                with urllib.request.urlopen(url, timeout=4) as first, urllib.request.urlopen(url, timeout=4) as second:
                    self.assertEqual(first.headers.get_content_type(), "text/event-stream")
                    self.assertIsNone(first.headers.get("Content-Length"))
                    self.assertEqual(read_event(first), read_event(second))
                    self.assertEqual(sampler.call_count, 1)
                    clock = 101
                    feed.invalidate()
                    self.assertTrue(resampled.wait(timeout=2))
                    self.assertTrue(read_frame(first).startswith(b":"))
                    self.assertGreaterEqual(sampler.call_count, 2)
                    self.assertTrue(read_frame(second).startswith(b":"))
                    stage = "已通过"
                    feed.invalidate()
                    for client in (first, second):
                        name, snap = read_event(client)
                        self.assertEqual(name, "snapshot")
                        self.assertEqual(snap["issues"][0]["stage"], stage)

                    fail = True
                    feed.invalidate()
                    self.assertEqual(read_event(first), ("snapshot-error", "读取失败\n稍后重试"))
                    fail = False
                    feed.invalidate()
                    self.assertEqual(read_event(first)[0], "snapshot")
                request = urllib.request.Request(url, headers={"Last-Event-ID": "old-session"})
                with urllib.request.urlopen(request, timeout=4) as resumed:
                    self.assertEqual(read_event(resumed)[1]["issues"][0]["stage"], stage)
            finally:
                feed.close()
                server.shutdown()
                thread.join(timeout=2)

    def test_last_subscriber_stops_collection_and_resume_reads_fresh(self):
        calls = 0
        sampled = threading.Event()

        def collect():
            nonlocal calls
            calls += 1
            sampled.set()
            return json.dumps({"forge_syncing": False, "summary": {}, "step": calls}).encode()

        feed = BoardEvents(collect, heartbeat=2)
        first = feed.frames()
        self.assertIn(b'"step": 1', next(first))
        first.close()
        sampled.clear()
        feed.invalidate()
        self.assertFalse(sampled.wait(timeout=0.1))
        second = feed.frames()
        self.assertIn(b'"step": 2', next(second))
        second.close()
        feed.close()
        self.assertEqual(list(feed.frames()), [])
        self.assertEqual(calls, 2)

    def test_adaptive_sampling(self):
        for syncing, summary, expected in [
            (True, {}, 1.2), (False, {"coding_now_count": 1}, 4), (False, {"dirty_worktrees": 1}, 4),
            (False, {"active_worktrees": 1}, 8), (False, {}, 15),
        ]:
            with self.subTest(syncing=syncing, summary=summary):
                self.assertEqual(sample_interval({"forge_syncing": syncing, "summary": summary}), expected)

    def test_manual_refresh_joins_pending_remote_scan_and_reports_failure(self):
        cache = ForgeSnapshotCache()
        repo = Path("/repo")
        entered = threading.Event()
        release = threading.Event()

        def fail(*args, **kwargs):
            entered.set()
            release.wait(timeout=3)
            raise ValueError("remote unavailable")

        with (
            mock.patch("monitor.resolve_main_worktree", return_value=repo),
            mock.patch("monitor.has_remote_origin", return_value=True),
            mock.patch.object(cache, "_query_and_store", side_effect=fail) as query,
        ):
            self.assertFalse(cache.refresh_now([repo], timeout=0))
            self.assertTrue(entered.wait(timeout=2))
            # Release the shared in-flight fetch only once the second call joined it.
            schedule = cache._schedule_refresh
            def join(*args):
                task = schedule(*args)
                release.set()
                return task

            with mock.patch.object(cache, "_schedule_refresh", side_effect=join):
                with self.assertRaisesRegex(ValueError, "remote unavailable"):
                    cache.refresh_now([repo], timeout=2)
            self.assertEqual(query.call_count, 1)
