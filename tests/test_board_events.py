"""Behavior of the shared board SSE feed through its HTTP and subscriber interfaces."""

from __future__ import annotations

from functools import partial
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from board_events import BoardEvents, sample_interval
from board_ui import BoardRequestHandler
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
    while True:
        frame = read_frame(response)
        if not frame.startswith(b":"):
            event, data = frame.decode().splitlines()
            return event.removeprefix("event: "), json.loads(data.removeprefix("data: "))


class TestBoardEvents(unittest.TestCase):
    def test_shared_http_stream_deduplicates_and_recovers(self):
        clock = 100
        stage = "运行中"
        fail = False

        def collect():
            if fail:
                raise ValueError("读取失败\n稍后重试")
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
        def collect():
            nonlocal calls
            calls += 1
            return json.dumps({"forge_syncing": False, "summary": {}, "step": calls}).encode()

        feed = BoardEvents(collect, heartbeat=2)
        first = feed.frames()
        self.assertIn(b'"step": 1', next(first))
        first.close()
        feed.invalidate()
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
