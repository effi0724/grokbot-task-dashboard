#!/usr/bin/env python3
"""stnudge - let the dashboard nudge bots whose tasks went stale.

  stnudge scan [--dry-run] | loop [--every 600] [--dry-run] | hooks [--reset BOT]
  stnudge queue list | queue ack <nudge_id>...

Scans $ST_ROOT/bots/*.json. A running, blocked, or past-resume waiting task that has not been
updated for STNUDGE_TTL_MIN minutes (default 90), or is 30+ minutes past an ETA it set before its
last update, gets a nudge. Bots with an entry in .nudge-hooks.json (mode 600) get an HTTP POST;
every other bot's nudge goes to watchers/.nudge-queue.json, which a coordinator bot reads
(`queue list`), forwards, and acks. Each task gets at most 2 nudges (6h apart); after that it is
capped until the bot updates it. Read-only on bots/*.json; never calls st. Hook keys are never printed.

Env: STNUDGE_BASE (default $ST_ROOT or ~/.grokbot-task-dashboard), STNUDGE_BOTS, STNUDGE_HOOKS,
STNUDGE_WATCHERS, STNUDGE_QUEUE, STNUDGE_TTL_MIN (90), STNUDGE_GLOBAL_HOUR (10 nudges per hour)."""
import argparse
import fcntl
import glob
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone


def env(name, default):
    return os.environ.get(name, "").strip() or default


def env_num(name, default, cast):
    try:
        return cast(env(name, str(default)))
    except ValueError:
        return default


BASE = env("STNUDGE_BASE", env("ST_ROOT", os.path.expanduser("~/.grokbot-task-dashboard")))
BOTS = env("STNUDGE_BOTS", os.path.join(BASE, "bots"))
HOOKS = env("STNUDGE_HOOKS", os.path.join(BASE, ".nudge-hooks.json"))
WD = env("STNUDGE_WATCHERS", os.path.join(BASE, "watchers"))
# dot-prefixed so stwatch does not mistake them for watcher records
QUEUE = env("STNUDGE_QUEUE", os.path.join(WD, ".nudge-queue.json"))
STATE = os.path.join(WD, ".stnudge-state.json")
LOG = os.path.join(WD, "stnudge.log")
KEEP_DELIVERED = 7 * 86400
KEEP_UNACKED = 7 * 86400
TTL = env_num("STNUDGE_TTL_MIN", 90.0, float)
ETA_GRACE = 30
PER_TASK_GAP = 6 * 3600
PER_DAY = 2
GLOBAL_HOUR = env_num("STNUDGE_GLOBAL_HOUR", 10, int)
REASONS = {"stale_ttl", "eta_overdue", "pr_merged", "pr_closed", "pr_pushed", "pr_reviewed", "blocked_stale"}


def now():
    return datetime.now(timezone.utc).astimezone()


def ts(s):
    """Parse an ISO time; naive times are taken as local time so comparisons never crash."""
    if not isinstance(s, str) or not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d.replace(tzinfo=now().tzinfo) if d.tzinfo is None else d


def log(msg):
    os.makedirs(WD, exist_ok=True)
    line = f"{now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def jload(p, d):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return d


def jsave(p, obj):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    t = f"{p}.{os.getpid()}.tmp"
    with open(t, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(t, p)


class flock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.f = open(self.path, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def qlock():
    return flock(QUEUE + ".lock")


def load_hooks():
    h = jload(HOOKS, {})
    if os.path.exists(HOOKS) and os.stat(HOOKS).st_mode & 0o077:
        log("WARN .nudge-hooks.json is not mode 600")
    return h if isinstance(h, dict) else {}


def bots():
    for p in sorted(glob.glob(os.path.join(BOTS, "*.json"))):
        d = jload(p, None)
        if isinstance(d, dict) and isinstance(d.get("tasks"), dict):
            yield d.get("bot") or os.path.basename(p)[:-5], d["tasks"]


def classify(t, t0):
    """Return (updated, reason) for a task that needs a nudge, else None."""
    if not isinstance(t, dict):
        return None
    st, up = t.get("state"), ts(t.get("updated"))
    if not up:
        return None
    since = up
    if st == "waiting":
        r = ts(t.get("resume"))
        if not r or r > t0:
            return None
        since = max(up, r)               # give the bot a full TTL after its resume time
    elif st not in ("running", "blocked"):
        return None
    eta = ts(t.get("eta"))
    if eta and up < eta and t0 - eta > timedelta(minutes=ETA_GRACE):
        reason = "eta_overdue"           # an update after the ETA counts as a response
    elif t0 - since > timedelta(minutes=TTL):
        reason = "stale_ttl"
    else:
        return None
    return up, "blocked_stale" if st == "blocked" else reason


def candidates(t0):
    for bot, tasks in bots():
        for tid, t in tasks.items():
            try:
                c = classify(t, t0)
            except Exception as e:       # one malformed task must not stop the scan
                log(f"SKIP {bot}/{tid}: {type(e).__name__}")
                continue
            if c:
                yield bot, tid, t, c[0], c[1]


def q_read():
    q = jload(QUEUE, {"entries": []})
    if not (isinstance(q, dict) and isinstance(q.get("entries"), list)):
        return {"entries": []}
    q["entries"] = [e for e in q["entries"] if isinstance(e, dict)]
    return q


def q_write(q):
    t0 = now().timestamp()

    def keep(e):
        d = ts(e.get("delivered_at"))
        if d:
            return t0 - d.timestamp() < KEEP_DELIVERED
        s = ts(e.get("sent_at"))
        return not s or t0 - s.timestamp() < KEEP_UNACKED

    q["entries"] = [e for e in q["entries"] if keep(e)]
    jsave(QUEUE, q)


def enqueue(payload):
    with qlock():
        q = q_read()
        q["entries"].append(dict(payload))
        q_write(q)


def task_updated(bot, tid):
    for b, tasks in bots():
        if b == bot:
            t = tasks.get(tid)
            return (ts(t.get("updated")), t) if isinstance(t, dict) else (None, None)
    return None, None


def queue_list():
    out = []
    with qlock():
        for e in q_read()["entries"]:
            if e.get("delivered_at"):
                continue
            up, t = task_updated(e.get("bot"), e.get("task_id"))
            sa = ts(e.get("sent_at"))
            if t is None or (up and sa and up > sa) or t.get("state") == "done":
                continue
            out.append({k: e.get(k) for k in ("v", "nudge_id", "bot", "task_id", "reason", "sent_at")})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def queue_ack(ids):
    n = 0
    t = now().isoformat(timespec="seconds")
    with qlock():
        q = q_read()
        for e in q["entries"]:
            if e.get("nudge_id") in ids and not e.get("delivered_at"):
                e["delivered_at"] = t
                n += 1
        q_write(q)
    print(f"acked {n}/{len(ids)}")
    log(f"ACK {n} nudge(s) via queue")
    return n


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: it would resend the Bearer key to another URL."""

    def redirect_request(self, *a, **k):
        return None


def hook_url_ok(url):
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1"))


def post(hook, payload):
    req = urllib.request.Request(
        hook["url"], data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {hook['key']}"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=10) as r:
        return r.status


def scan(dry):
    with flock(STATE + ".lock"):
        return _scan(dry)


def _scan(dry):
    t0 = now()
    s = jload(STATE, {})
    if not isinstance(s, dict):
        s = {}
    for k, d in (("tasks", {}), ("broken", {}), ("sent", [])):
        if not isinstance(s.get(k), type(d)):
            s[k] = d
    s["sent"] = [x for x in s["sent"] if isinstance(x, (int, float)) and t0.timestamp() - x < 3600]
    hooks = load_hooks()
    n = 0
    for bot, tid, t, up, reason in candidates(t0):
        rec = s["tasks"].setdefault(f"{bot}\t{tid}", {"nudges": []})
        last = rec["nudges"][-1] if rec["nudges"] else None
        if last and up.timestamp() > last:  # bot updated since the last nudge: reset
            rec["nudges"] = []
            rec.pop("capped", None)
            last = None
        if len(rec["nudges"]) >= PER_DAY:   # capped until the bot updates the task
            if not rec.get("capped"):
                rec["capped"] = True
                log(f"CAP {bot}/{tid} nudged {PER_DAY} times, no response")
            continue
        if last and t0.timestamp() - last < PER_TASK_GAP:
            continue
        if len(s["sent"]) >= GLOBAL_HOUR:
            log("GLOBAL CAP reached for this hour, stopping")
            break
        hook = hooks.get(bot)
        has_hook = bool(isinstance(hook, dict) and hook.get("url") and hook.get("key"))
        if has_hook and bot in s["broken"]:
            log(f"SKIP {bot}/{tid}: hook marked broken ({s['broken'][bot]}); `stnudge hooks --reset {bot}` to retry")
            continue
        payload = {"v": 1, "nudge_id": uuid.uuid4().hex, "bot": bot, "task_id": tid, "reason": reason,
                   "sent_at": t0.isoformat(timespec="seconds")}
        assert reason in REASONS
        if dry:
            log(f"DRY would nudge {bot}/{tid} reason={reason} via={'webhook' if has_hook else 'queue'}")
            n += 1
            continue
        if not has_hook:
            enqueue(payload)
            log(f"QUEUED {bot}/{tid} reason={reason} nudge_id={payload['nudge_id']}")
        else:
            if not hook_url_ok(hook["url"]):
                log(f"WARN hook for {bot} is not https; the key is sent in clear text")
            try:
                code = post(hook, payload)
                log(f"SENT {bot}/{tid} reason={reason} nudge_id={payload['nudge_id']} http={code}")
            except urllib.error.HTTPError as e:
                log(f"FAIL {bot}/{tid} http={e.code}")
                if e.code in (401, 403, 404) or 300 <= e.code < 400:
                    s["broken"][bot] = f"http {e.code} @ {t0.isoformat(timespec='seconds')}"
                    log(f"BROKEN hook for {bot}")
                continue
            except Exception as e:
                log(f"FAIL {bot}/{tid} {type(e).__name__}")
                continue
        rec["nudges"].append(t0.timestamp())
        s["sent"].append(t0.timestamp())
        n += 1
    if not dry:
        jsave(STATE, s)
    return n


def hooks_cmd(reset):
    if reset:
        with flock(STATE + ".lock"):
            s = jload(STATE, {})
            had = isinstance(s, dict) and isinstance(s.get("broken"), dict) and s["broken"].pop(reset, None)
            if had:
                jsave(STATE, s)
        print(f"{reset}: {'reset' if had else 'was not marked broken'}")
        return
    h = load_hooks()
    br = jload(STATE, {}).get("broken", {})
    names = [b for b, _ in bots()]
    for b in names + [x for x in h if x not in names]:
        ok = isinstance(h.get(b), dict) and h[b].get("url") and h[b].get("key")
        print(f"{b}\t{'configured' if ok else 'no hook (queue)'}{' (BROKEN)' if b in br else ''}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("scan")
    a.add_argument("--dry-run", action="store_true")
    b = sp.add_parser("loop")
    b.add_argument("--every", type=int, default=600)
    b.add_argument("--dry-run", action="store_true")
    h = sp.add_parser("hooks")
    h.add_argument("--reset", metavar="BOT", help="clear the broken mark for BOT")
    q = sp.add_parser("queue")
    qs = q.add_subparsers(dest="qcmd", required=True)
    qs.add_parser("list")
    qa = qs.add_parser("ack")
    qa.add_argument("ids", nargs="+")
    o = ap.parse_args(argv)
    if o.cmd == "queue":
        queue_list() if o.qcmd == "list" else queue_ack(set(o.ids))
    elif o.cmd == "scan":
        scan(o.dry_run)
    elif o.cmd == "loop":
        while True:
            try:
                scan(o.dry_run)
            except Exception as e:
                log(f"ERROR scan {type(e).__name__}: {e}")
            time.sleep(o.every)
    else:
        hooks_cmd(o.reset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
