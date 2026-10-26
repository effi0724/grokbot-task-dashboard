import hashlib
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from types import SimpleNamespace

from support import ROOT, StateCase, stlib


def ns(**kwargs):
    base = dict(
        bot="Coder",
        task_id="site-tests",
        title="[示例] 解析工期",
        stage=None,
        pct=None,
        eta=None,
        note=None,
        via=None,
        resume=None,
        no_push=True,
        state=None,
        task_type=None,
        estimate=None,
        json=False,
        history=False,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class StateTests(StateCase):
    def test_create_revise_and_finish(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(eta="+2h", task_type="coding", pct=10, stage="写解析"))
        task = stlib.load("Coder")["tasks"]["site-tests"]
        self.assertEqual(task["estimate_minutes"], 120)
        self.assertEqual(task["estimate_source"], "eta")
        self.assertEqual(task["eta_revisions"], 0)
        self.assertEqual(task["task_type"], "coding")
        self.assertEqual(task["pct"], 10)

        self.advance(minutes=30)
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(eta="+3h", title=None))
        task = stlib.load("Coder")["tasks"]["site-tests"]
        self.assertEqual(task["eta_revisions"], 1)
        self.assertEqual(task["estimate_minutes"], 120)

        same = task["eta"]
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(eta=same, title=None))
        self.assertEqual(stlib.load("Coder")["tasks"]["site-tests"]["eta_revisions"], 1)

        self.frozen = self.start + timedelta(minutes=150)
        buf = io.StringIO()
        with redirect_stdout(buf):
            stlib.cmd_set(ns(title=None), finishing=True)
        done = stlib.load("Coder")["history"][0]
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["pct"], 100)
        self.assertEqual(done["actual_minutes"], 150)
        self.assertNotIn("site-tests", stlib.load("Coder")["tasks"])
        self.assertIn("1.25×", buf.getvalue())

        suggestion = None
        with redirect_stdout(io.StringIO()):
            suggestion = stlib.cmd_estimate(ns(estimate="2h", task_type="coding"))
        self.assertEqual(suggestion["basis"], "bot+type")
        self.assertEqual(suggestion["n"], 1)
        self.assertTrue(suggestion["low_confidence"])

    def test_explicit_estimate_is_frozen(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(estimate="90m", eta="+2h", task_type="research"))
        task = stlib.load("Coder")["tasks"]["site-tests"]
        self.assertEqual(task["estimate_minutes"], 90)
        self.assertEqual(task["estimate_source"], "flag")
        self.advance(hours=1)
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(estimate="8h", eta="+4h", title=None))
        task = stlib.load("Coder")["tasks"]["site-tests"]
        self.assertEqual(task["estimate_minutes"], 90)
        self.assertEqual(task["eta_revisions"], 1)

    def test_new_task_requires_title_and_rm_skips_history(self):
        with self.assertRaises(stlib.CliError):
            stlib.cmd_set(ns(title=None))
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(eta="+1h"))
            stlib.cmd_rm(ns())
        data = stlib.load("Coder")
        self.assertEqual(data["tasks"], {})
        self.assertEqual(data["history"], [])

    def test_cancelled_is_stored_but_not_a_sample(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(estimate="1h", task_type="coding"))
        self.advance(minutes=20)
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(title=None, state="cancelled"), finishing=True)
        history = stlib.load("Coder")["history"]
        self.assertEqual(history[0]["state"], "cancelled")
        self.assertEqual(stlib.snapshot()["accuracy"]["sample_count"], 0)

    def test_display_window_is_shorter_than_stats_window(self):
        old = (self.start - timedelta(days=20)).isoformat()
        recent = (self.start - timedelta(days=2)).isoformat()
        data = stlib.load("Coder")
        data["history"] = [
            {
                "id": "old", "title": "[示例] 旧任务", "state": "done", "finished": old,
                "started": old, "estimate_minutes": 100, "actual_minutes": 200,
                "eta_revisions": 1, "task_type": "coding",
            },
            {
                "id": "new", "title": "[示例] 新任务", "state": "done", "finished": recent,
                "started": recent, "estimate_minutes": 100, "actual_minutes": 100,
                "eta_revisions": 0, "task_type": "coding",
            },
        ]
        stlib.save(data)
        snap = stlib.snapshot()
        coder = next(bot for bot in snap["bots"] if bot["bot"] == "Coder")
        self.assertEqual([item["id"] for item in coder["history"]], ["new"])
        self.assertEqual(snap["accuracy"]["sample_count"], 2)

        os.environ["ST_STATS_DAYS"] = "10"
        stlib.save(stlib.load("Coder"))
        snap = stlib.snapshot()
        self.assertEqual(snap["accuracy"]["sample_count"], 1)

    def test_snapshot_attaches_calibration_to_active_tasks(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(estimate="2h", eta="+2h", task_type="coding", pct=5))
        snap = stlib.snapshot()
        coder = next(bot for bot in snap["bots"] if bot["bot"] == "Coder")
        cal = coder["tasks"][0]["calibration"]
        self.assertEqual(cal["raw_minutes"], 120)
        self.assertEqual(cal["basis"], "none")
        self.assertEqual(cal["low_minutes"], 60)
        self.assertEqual(cal["high_minutes"], 240)
        self.assertIn("desc_zh", coder)

    def test_bot_filename_is_sanitized_and_lock_creates_a_file(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(bot="Coder/Ops", task_id="t-1", eta="+1h"))
        self.assertTrue(os.path.exists(os.path.join(stlib.bots_dir(), "Coder_Ops.json")))
        with stlib.Locked():
            self.assertTrue(os.path.exists(stlib.lock_path()))

    def test_push_without_url_is_local_only(self):
        with redirect_stderr(io.StringIO()):
            self.assertFalse(stlib.push(quiet=True))

    def test_token_sha256_prints_hash_only(self):
        os.makedirs(stlib.root_dir(), exist_ok=True)
        with open(stlib.token_path(), "w", encoding="utf-8") as handle:
            handle.write("example-push-token\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = stlib.main(["token-sha256"])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue().strip(), hashlib.sha256(b"example-push-token").hexdigest())
        self.assertNotIn("example-push-token", buf.getvalue())

    def test_cli_estimate_json(self):
        env = os.environ.copy()
        proc = subprocess.run(
            [sys.executable, str(ROOT / "cli" / "st"), "estimate", "--bot", "Coder", "--estimate", "2h", "--json"],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["minutes"], 120)
        self.assertEqual(payload["basis"], "none")
        self.assertNotIn("example-push-token", proc.stdout + proc.stderr)

    def test_help_exits_cleanly(self):
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                stlib.main(["--help"])
        self.assertEqual(caught.exception.code, 0)


class AuditRegressionTests(StateCase):
    def test_waiting_then_running_keeps_started(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(estimate="60m"))
            started = stlib.load("Coder")["tasks"]["site-tests"]["started"]
            self.advance(minutes=30)
            stlib.cmd_set(ns(state="waiting"))
            self.advance(minutes=60)
            stlib.cmd_set(ns(state="running"))
            self.assertEqual(stlib.load("Coder")["tasks"]["site-tests"]["started"], started)
            self.advance(minutes=40)
            stlib.cmd_set(ns(), finishing=True)
        done = stlib.load("Coder")["history"][-1]
        self.assertEqual(done["actual_minutes"], 130)

    def test_queued_first_run_resets_started_once(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns(state="queued"))
            self.advance(minutes=20)
            stlib.cmd_set(ns(state="running"))
            first = stlib.load("Coder")["tasks"]["site-tests"]["started"]
            self.advance(minutes=10)
            stlib.cmd_set(ns(state="queued"))
            self.advance(minutes=10)
            stlib.cmd_set(ns(state="running"))
        self.assertEqual(stlib.load("Coder")["tasks"]["site-tests"]["started"], first)

    def test_done_with_unknown_id_errors_and_writes_nothing(self):
        with self.assertRaises(stlib.CliError):
            stlib.cmd_set(ns(task_id="typo-id", title=None), finishing=True)
        self.assertEqual(stlib.load("Coder")["history"], [])

    def test_empty_st_root_falls_back_to_default(self):
        old = os.environ.get("ST_ROOT")
        os.environ["ST_ROOT"] = "  "
        try:
            self.assertEqual(stlib.root_dir(), os.path.expanduser("~/.grokbot-task-dashboard"))
        finally:
            if old is None:
                os.environ.pop("ST_ROOT", None)
            else:
                os.environ["ST_ROOT"] = old

    def test_wrangler_toml_has_no_build_output_dir(self):
        text = (ROOT / "site" / "wrangler.toml").read_text(encoding="utf-8")
        self.assertNotIn("\npages_build_output_dir", "\n" + text)


class PushRetryTests(StateCase):
    def test_push_retries_then_records_pending(self):
        import urllib.error
        os.environ["ST_PUSH_URL"] = "https://example.invalid/api/push"
        os.environ["ST_PUSH_RETRIES"] = "3"
        with open(stlib.token_path(), "w", encoding="utf-8") as handle:
            handle.write("example-token")
        calls, sleeps = [], []
        original_open, original_sleep = stlib.urllib.request.urlopen, stlib._sleep

        def failing(*args, **kwargs):
            calls.append(1)
            raise urllib.error.URLError("down")
        stlib.urllib.request.urlopen = failing
        stlib._sleep = sleeps.append
        try:
            with redirect_stderr(io.StringIO()):
                self.assertFalse(stlib.push(quiet=True))
        finally:
            stlib.urllib.request.urlopen = original_open
            stlib._sleep = original_sleep
            os.environ.pop("ST_PUSH_RETRIES", None)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [2, 6])
        self.assertTrue(os.path.exists(stlib.pending_path()))

    def test_beat_keeps_updated_and_sets_watcher(self):
        with redirect_stdout(io.StringIO()):
            stlib.cmd_set(ns())
            before = stlib.load("Coder")["tasks"]["site-tests"]["updated"]
            self.advance(minutes=10)
            stlib.cmd_beat(SimpleNamespace(bot="Coder", task_id="site-tests", watcher="w", alive="0",
                                           restarts=2, wnote="gave up", quiet=False, no_push=True))
        task = stlib.load("Coder")["tasks"]["site-tests"]
        self.assertEqual(task["updated"], before)
        self.assertNotEqual(task["heartbeat"], before)
        self.assertEqual(task["watcher"], {"name": "w", "alive": False, "restarts": 2, "note": "gave up",
                                           "checked": task["heartbeat"]})


class TokenSnapshotTests(StateCase):
    def test_snapshot_includes_token_usage(self):
        import json as _json
        path = os.path.join(self.tmp.name, ".token-usage.json")
        with open(path, "w", encoding="utf-8") as handle:
            _json.dump({"Claude Code": {"total": {"in": 1, "out": 2, "cr": 3, "cw": 4}, "weeks": []}}, handle)
        self.assertEqual(stlib.snapshot()["tokens"]["Claude Code"]["total"]["out"], 2)

    def test_snapshot_tokens_default_empty(self):
        self.assertEqual(stlib.snapshot()["tokens"], {})
