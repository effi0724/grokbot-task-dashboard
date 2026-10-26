"""cli/stnudge end to end: temp bots dir, a local fake webhook, and the queue path."""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "cli" / "stnudge"
PAYLOAD_KEYS = {"v", "nudge_id", "bot", "task_id", "reason", "sent_at"}


class Hook(http.server.BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ok = self.headers.get("Authorization") == "Bearer good"
        Hook.got.append(body)
        self.send_response(200 if ok else 401)
        self.end_headers()

    def log_message(self, *args):
        pass


def iso(value):
    return value.isoformat(timespec="seconds")


class StnudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.bots = os.path.join(self.dir, "bots")
        os.makedirs(self.bots)
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        Hook.got = []
        url = f"http://127.0.0.1:{self.server.server_port}/"
        hooks = os.path.join(self.dir, ".nudge-hooks.json")
        with open(hooks, "w") as handle:
            json.dump({"Alpha": {"url": url, "key": "good"}, "Gamma": {"url": url, "key": "bad"}}, handle)
        os.chmod(hooks, 0o600)
        self.queue = os.path.join(self.dir, "watchers", ".nudge-queue.json")
        self.state = os.path.join(self.dir, "watchers", ".stnudge-state.json")
        self.env = dict(os.environ, STNUDGE_BASE=self.dir, STNUDGE_GLOBAL_HOUR="50")
        self.env.pop("STNUDGE_TTL_MIN", None)
        self.now = datetime.now(timezone.utc).astimezone()
        self.old = iso(self.now - timedelta(hours=10))
        old = self.old
        self.bot("Alpha", {
            "stale": {"state": "running", "updated": old},
            "fresh": {"state": "running", "updated": iso(self.now)},
            "eta": {"state": "running", "updated": iso(self.now - timedelta(hours=8)), "eta": iso(self.now - timedelta(hours=1))},
            "r": {"state": "routine", "updated": old},
            "q": {"state": "quota", "updated": old},
            "b": {"state": "blocked", "updated": old},
            "w": {"state": "waiting", "updated": old, "resume": iso(self.now + timedelta(hours=1))},
            "w2": {"state": "waiting", "updated": old, "resume": iso(self.now - timedelta(hours=2))},
            "w3": {"state": "waiting", "updated": old, "resume": iso(self.now - timedelta(minutes=10))},
            "eta2": {"state": "running", "updated": iso(self.now - timedelta(minutes=20)), "eta": iso(self.now - timedelta(hours=1))},
            "naive": {"state": "running", "updated": "2020-01-01T00:00:00"},
            "junk": "not a dict",
        })
        self.bot("Beta", {"x": {"state": "running", "updated": old}})
        self.bot("Gamma", {"y": {"state": "running", "updated": old}})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def bot(self, name, tasks):
        with open(os.path.join(self.bots, name + ".json"), "w", encoding="utf-8") as handle:
            json.dump({"bot": name, "tasks": tasks}, handle)

    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, str(CLI), *args], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        return proc.stdout

    def alpha(self):
        return [item for item in Hook.got if item["bot"] == "Alpha"]

    def test_full_cycle(self):
        out = self.run_cli("scan", "--dry-run")
        for line in ("Alpha/stale reason=stale_ttl", "Alpha/eta reason=eta_overdue", "Alpha/w2 ", "Alpha/b reason=blocked_stale", "Alpha/naive "):
            self.assertIn(line, out)
        for skipped in ("fresh", "r", "q", "w", "w3", "eta2"):
            self.assertNotIn(f"Alpha/{skipped} ", out)
        self.assertIn("Beta/x reason=stale_ttl via=queue", out)
        self.assertEqual(Hook.got, [])
        self.assertFalse(os.path.exists(self.queue), "dry-run must not enqueue")

        out = self.run_cli("scan")
        self.assertEqual(len(self.alpha()), 5)
        self.assertTrue(all(set(item) == PAYLOAD_KEYS for item in self.alpha()))
        self.assertIn("BROKEN hook for Gamma", out)
        entries = json.load(open(self.queue))["entries"]
        self.assertEqual([(e["bot"], e["task_id"]) for e in entries], [("Beta", "x")])
        self.assertEqual(set(entries[0]), PAYLOAD_KEYS)

        listed = self.run_cli("queue", "list")
        self.assertEqual([e["task_id"] for e in json.loads(listed)], ["x"])
        self.assertNotIn("good", listed)

        self.bot("Beta", {"x": {"state": "running", "updated": iso(datetime.now(timezone.utc).astimezone() + timedelta(seconds=5))}})
        self.assertEqual(json.loads(self.run_cli("queue", "list")), [], "updated after sent_at hides the entry")
        self.bot("Beta", {"x": {"state": "running", "updated": self.old}})

        self.assertIn("acked 1/1", self.run_cli("queue", "ack", entries[0]["nudge_id"]))
        self.assertEqual(json.loads(self.run_cli("queue", "list")), [])
        self.assertTrue(json.load(open(self.queue))["entries"][0].get("delivered_at"))

        data = json.load(open(self.queue))
        data["entries"][0]["delivered_at"] = iso(self.now - timedelta(days=8))
        json.dump(data, open(self.queue, "w"))
        self.run_cli("queue", "ack", "nonexistent")
        self.assertEqual(json.load(open(self.queue))["entries"], [], "delivered entries are pruned after 7 days")

        Hook.got = []
        out = self.run_cli("scan")
        self.assertEqual(self.alpha(), [], "no repeat within 6 hours")
        self.assertIn("Gamma/y: hook marked broken", out)

        state = json.load(open(self.state))
        for key in state["tasks"]:
            state["tasks"][key]["nudges"] = [x - 7 * 3600 for x in state["tasks"][key]["nudges"]]
        json.dump(state, open(self.state, "w"))
        Hook.got = []
        self.run_cli("scan")
        self.assertEqual(len(Hook.got), 5, "second nudge after 6 hours")

        Hook.got = []
        out = self.run_cli("scan")
        self.assertEqual(Hook.got, [])
        self.assertIn("CAP Alpha/stale", out, "2 per task per day")

        hooks = self.run_cli("hooks")
        self.assertNotIn("good", hooks)
        self.assertNotIn("bad", hooks)
        self.assertIn("Gamma\tconfigured (BROKEN)", hooks)
        self.assertIn("Beta\tno hook", hooks)
        self.assertIn("Gamma: reset", self.run_cli("hooks", "--reset", "Gamma"))
        self.assertNotIn("BROKEN", self.run_cli("hooks"))

        data = json.load(open(self.queue))
        data["entries"] = [{"nudge_id": "old", "bot": "Beta", "task_id": "x", "sent_at": iso(self.now - timedelta(days=8))}]
        json.dump(data, open(self.queue, "w"))
        self.run_cli("queue", "ack", "nonexistent")
        self.assertEqual(json.load(open(self.queue))["entries"], [], "unacked entries are pruned after 7 days")


if __name__ == "__main__":
    unittest.main()
