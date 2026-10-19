"""Integration tests for cli/stwatch (Linux: uses setsid, /proc, flock)."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from support import ROOT

ST = str(ROOT / "cli" / "st")
STWATCH = str(ROOT / "cli" / "stwatch")


@unittest.skipUnless(sys.platform.startswith("linux"), "stwatch integration tests need Linux")
class StwatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, ST_ROOT=self.tmp.name, ST_PUSH_URL="", ST_LANG="en",
                        STWATCH_BACKOFF_SEC="0", STWATCH_LOCAL_SEC="1", STWATCH_BEAT_SEC="1")
        self.run_st("set", "--bot", "Coder", "--task-id", "w1", "--title", "[example] watcher", "--no-push")

    def tearDown(self):
        wd = os.path.join(self.tmp.name, "watchers")
        if os.path.isdir(wd):
            for name in os.listdir(wd):
                if name.endswith(".json") and not name.startswith("."):
                    subprocess.run([sys.executable, STWATCH, "stop", name[:-5]], env=self.env,
                                   capture_output=True, timeout=30)
        self.tmp.cleanup()

    def run_st(self, *args):
        return subprocess.run([sys.executable, ST, *args], env=self.env, capture_output=True, text=True, timeout=30)

    def stwatch(self, *args):
        return subprocess.run([sys.executable, STWATCH, *args], env=self.env, capture_output=True, text=True, timeout=60)

    def record(self, name):
        with open(os.path.join(self.tmp.name, "watchers", name + ".json"), encoding="utf-8") as handle:
            return json.load(handle)

    def task(self):
        with open(os.path.join(self.tmp.name, "bots", "Coder.json"), encoding="utf-8") as handle:
            return json.load(handle)["tasks"].get("w1")

    def wait_for(self, predicate, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if predicate():
                    return True
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.2)
        return False

    def start(self, name, *cmd, restarts=5):
        out = self.stwatch("start", "--name", name, "--bot", "Coder", "--task-id", "w1",
                           "--max-restarts", str(restarts), "--", *cmd)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_failing_command_gives_up_and_marks_lost(self):
        self.start("fail", sys.executable, "-c", "import sys; sys.exit(2)", restarts=1)
        self.assertTrue(self.wait_for(lambda: self.record("fail")["status"] == "dead"))
        self.assertEqual(self.record("fail")["restarts"], 1)
        self.assertTrue(self.wait_for(lambda: self.task()["watcher"]["alive"] is False))
        self.assertIn("updated", self.task())

    def test_clean_exit_is_not_restarted(self):
        self.start("ok", sys.executable, "-c", "pass")
        self.assertTrue(self.wait_for(lambda: self.record("ok")["status"] == "exited"))
        self.assertEqual(self.record("ok")["restarts"], 0)

    def test_heartbeat_does_not_touch_updated(self):
        before = self.task()["updated"]
        self.start("beat", sys.executable, "-c", "import time; time.sleep(60)")
        self.assertTrue(self.wait_for(lambda: self.task().get("heartbeat")))
        self.assertEqual(self.task()["updated"], before)
        self.assertEqual(self.task()["watcher"]["name"], "beat")

    def test_done_task_stops_watcher(self):
        self.start("done", sys.executable, "-c", "import time; time.sleep(60)")
        self.assertTrue(self.wait_for(lambda: self.record("done").get("pid")))
        pid = self.record("done")["pid"]
        self.run_st("done", "--bot", "Coder", "--task-id", "w1", "--no-push")
        self.assertTrue(self.wait_for(lambda: self.record("done")["status"] == "done"))
        self.assertTrue(self.wait_for(lambda: not os.path.exists(f"/proc/{pid}") or
                                      open(f"/proc/{pid}/stat").read().split(") ")[1][0] == "Z"))

    def test_watchdog_adopts_after_supervisor_is_killed(self):
        self.start("adopt", sys.executable, "-c", "import time; time.sleep(60)")
        self.assertTrue(self.wait_for(lambda: self.record("adopt").get("pid")))
        rec = self.record("adopt")
        os.kill(rec["runner_pid"], signal.SIGKILL)
        time.sleep(0.5)
        out = self.stwatch("watchdog")
        self.assertIn("adopt", out.stdout)
        self.assertTrue(self.wait_for(lambda: self.record("adopt")["runner_pid"] != rec["runner_pid"]))
        self.assertEqual(self.record("adopt")["pid"], rec["pid"])
        daemon = os.path.join(self.tmp.name, "watchers", ".daemon")
        if os.path.exists(daemon):
            with open(daemon, encoding="utf-8") as handle:
                pid = int(handle.read().split()[0])
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def test_beat_on_closed_task_exits_3(self):
        out = self.run_st("beat", "--bot", "Coder", "--task-id", "nope", "--no-push")
        self.assertEqual(out.returncode, 3)


if __name__ == "__main__":
    unittest.main()
