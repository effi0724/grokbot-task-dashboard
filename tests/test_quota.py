import io
import os
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace

from support import StateCase, stlib

USAGE = """
 Current session
 ███████████████████          38% used
 Resets 4:59pm (America/New_York)

 Current week (all models)
 ████                         100% used
 Resets Jan 20, 9:59am (America/New_York)
"""


def claude_ns(**kwargs):
    base = dict(state=None, reset=None, resume=None, model=None, plan=None, note=None,
                weekly_reset=None, session_left=None, week_left=None, from_usage=None, no_push=True)
    base.update(kwargs)
    return SimpleNamespace(**base)


def quota_ns(**kwargs):
    base = dict(runner="Gemini", state=None, reset=None, weekly_reset=None, resume=None, week_left=None,
                used=None, limit=None, model=None, plan=None, tool=None, note=None, no_push=True)
    base.update(kwargs)
    return SimpleNamespace(**base)


class QuotaTests(StateCase):
    def test_parse_usage_text(self):
        out = stlib.parse_usage_text(USAGE, self.frozen)
        self.assertEqual(out["session_left"], 62.0)
        self.assertEqual(out["week_left"], 0.0)
        self.assertEqual(out["session_reset"].hour, 16)
        self.assertEqual((out["week_reset"].month, out["week_reset"].day), (1, 20))

    def test_from_usage_marks_quota_and_resume(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write(USAGE)
        try:
            with redirect_stdout(io.StringIO()):
                stlib.cmd_claude(claude_ns(from_usage=handle.name))
        finally:
            os.unlink(handle.name)
        info = stlib.load(stlib.RUNNER)["claude"]
        self.assertEqual(info["state"], "quota")
        self.assertEqual(info["limit_scope"], "week")
        self.assertTrue(info["resume"] > info["weekly_reset"])
        self.assertTrue(info["usage_read"])

    def test_from_usage_without_data_changes_nothing(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("please log in")
        try:
            with self.assertRaises(stlib.CliError):
                stlib.cmd_claude(claude_ns(from_usage=handle.name))
        finally:
            os.unlink(handle.name)
        self.assertNotIn("claude", stlib.load(stlib.RUNNER))

    def test_reading_with_room_leaves_quota(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_claude(claude_ns(state="quota", reset="+1h"))
            self.assertEqual(stlib.load(stlib.RUNNER)["claude"]["session_left"], 0.0)
            stlib.cmd_claude(claude_ns(session_left=70, week_left=50))
        info = stlib.load(stlib.RUNNER)["claude"]
        self.assertEqual(info["state"], "ok")
        self.assertNotIn("limit_scope", info)

    def test_quota_runner_is_stored_and_snapshotted(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_quota(quota_ns(state="ok", week_left=140, used="20%", limit="100%", reset="+3h"))
        snap = stlib.snapshot()
        info = snap["quotas"]["Gemini"]
        self.assertEqual(info["week_left"], 100.0)
        self.assertEqual(info["used"], "20%")
        self.assertNotIn("session_left", info)
        self.assertNotIn("Gemini", [bot["bot"] for bot in snap["bots"]])

    def test_quota_runner_name_is_validated(self):
        for bad in ("", "Claude Code", "../x", ".hidden"):
            with self.assertRaises(stlib.CliError):
                stlib.cmd_quota(quota_ns(runner=bad))
