#!/usr/bin/env python3
"""stcount - count tokens your AI CLI runners used, per ISO week (read-only on local logs).

  stcount scan [--dry-run] [--no-push]   incrementally scan Claude Code logs, write .token-usage.json
  stcount loop --every 1800              keep scanning (run it under stwatch); st push on change
  stcount ingest-codex [file|-]          merge weekly totals from scripts/codex-tokens.py
  stcount show                           print the current totals

Claude Code writes several usage lines per reply; each (message.id, requestId) counts once.
Weekly totals live in $ST_ROOT/watchers/.token-weeks.json, so history survives log cleanup.
Env: ST_ROOT, ST_TZ (week boundaries), STCOUNT_CLAUDE_GLOB.
"""
import datetime as dt, fcntl, glob, json, os, re, sys, time, subprocess, tempfile, contextlib
from zoneinfo import ZoneInfo

ROOT = os.environ.get("ST_ROOT", "").strip() or os.path.expanduser("~/.grokbot-task-dashboard")
ST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "st")
CLAUDE_GLOB = os.path.expanduser(os.environ.get("STCOUNT_CLAUDE_GLOB", "").strip() or "~/.claude/projects/**/*.jsonl")
OFFS = os.path.join(ROOT, "watchers", ".token-offsets.json")
WEEKS = os.path.join(ROOT, "watchers", ".token-weeks.json")
OUT = os.path.join(ROOT, ".token-usage.json")
LOCK = os.path.join(ROOT, "watchers", ".token.lock")
MAX_WEEK = 10**13       # per-week, per-field ceiling so one bad push cannot pin the max forever
try:
    TZ = ZoneInfo(os.environ.get("ST_TZ", "").strip() or "America/New_York")
except (ValueError, KeyError):  # bad zone name: fall back like stlib.zone()
    TZ = ZoneInfo("America/New_York")
SEEN_DAYS = 40          # longer than Claude Code's default 30-day log cleanup, so a re-read file is not double counted
FIELDS = ("in", "out", "cr", "cw")


def jload(p, d):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return d


@contextlib.contextmanager
def locked():
    """scan and ingest-codex both rewrite .token-weeks.json; hold one lock for the whole read-modify-write."""
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".tmp-")
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def iso_ok(v):
    if not isinstance(v, str) or len(v) > 40:
        return False
    try:
        dt.datetime.fromisoformat(v.replace("Z", "+00:00")); return True
    except ValueError:
        return False


def week_of(t):
    y, w, _ = t.astimezone(TZ).isocalendar()
    return f"{y}-W{w:02d}"


def parse_ts(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def add(wk, cli, week, vals, first=None):
    c = wk.setdefault(cli, {"weeks": {}, "since": None})
    a = c["weeks"].setdefault(week, {k: 0 for k in FIELDS})
    for k in FIELDS:
        a[k] += int(vals.get(k) or 0)
    if first and (not c["since"] or first < c["since"]):
        c["since"] = first


def scan_claude(offs, wk):
    """Return the number of new messages. offs: {"files": {path: [ino, offset]}, "seen": {key: [...]}}"""
    files, seen = offs.setdefault("files", {}), offs.setdefault("seen", {})
    inited = bool(offs.get("initialized_at"))   # the first scan imports all history
    cut = time.time() - SEEN_DAYS * 86400
    n = 0
    for p in sorted(glob.glob(CLAUDE_GLOB, recursive=True)):
        try:
            st = os.stat(p)
        except OSError:
            continue
        ino, off = files.get(p, [st.st_ino, 0])
        if ino != st.st_ino or st.st_size < off:   # file replaced or truncated: reread, dedupe via seen
            off = 0
        if st.st_size == off:
            files[p] = [st.st_ino, off]
            continue
        with open(p, "rb") as f:
            f.seek(off)
            data = f.read()
        end = data.rfind(b"\n") + 1               # only complete lines; a partial line waits for the next scan
        for line in data[:end].splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            m = r.get("message")
            if r.get("type") != "assistant" or not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
                continue
            if not m.get("id") and not r.get("requestId"):
                continue                          # no stable id: cannot dedupe, skip
            key = f"{m.get('id')}|{r.get('requestId')}"
            if not isinstance(r.get("timestamp"), str):
                continue
            try:
                t = parse_ts(r["timestamp"])
                u = m["usage"]
                cur = [max(0, int(u.get(x) or 0)) for x in
                       ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
            except (KeyError, ValueError, TypeError):
                continue
            if inited and t.timestamp() < cut and key not in seen:
                continue                          # old message outside the dedupe window (resume / moved dir): skip
            # several usage lines per reply: streaming lines undercount output, so take the per-field max and add the delta
            prev = seen.get(key)
            if prev:
                week, old = prev[1], prev[2:]
            else:
                week, old = week_of(t), [0, 0, 0, 0]
            new = [max(a, b) for a, b in zip(old, cur)]
            if prev and new == old:
                continue
            seen[key] = [prev[0] if prev else int(t.timestamp()), week] + new
            add(wk, "Claude Code", week, dict(zip(FIELDS, [b - a for a, b in zip(old, new)])),
                first=t.astimezone(TZ).isoformat(timespec="seconds"))
            if not prev:
                n += 1
        files[p] = [st.st_ino, off + end]
    for p in list(files):                          # stop tracking deleted logs (totals stay in .token-weeks.json)
        if not os.path.exists(p):
            del files[p]
    for k in [k for k, v in seen.items() if v[0] < cut]:
        del seen[k]
    offs.setdefault("initialized_at", int(time.time()))
    return n


def ingest_codex(obj, wk):
    """Each push is the full weekly summary the sender can compute from its current logs. Merge per week and
    field by max: repeated pushes never double count, and old weeks never shrink after log cleanup."""
    weeks = obj.get("token_weeks")
    if not isinstance(weeks, dict):
        raise ValueError("missing token_weeks")
    c = wk.setdefault("Codex", {"weeks": {}, "since": None})
    for w, v in weeks.items():
        if not (isinstance(w, str) and re.fullmatch(r"\d{4}-W(0[1-9]|[1-4]\d|5[0-3])", w) and isinstance(v, dict)):
            raise ValueError(f"bad week key: {w!r}")
        for k in FIELDS:
            x = v.get(k) or 0
            if not isinstance(x, int) or isinstance(x, bool) or not 0 <= x <= MAX_WEEK:
                raise ValueError(f"{w} {k} invalid value: {x!r}")
    for w, v in weeks.items():
        a = c["weeks"].setdefault(w, {k: 0 for k in FIELDS})
        for k in FIELDS:
            a[k] = max(a[k], int(v.get(k) or 0))
    s = obj.get("since")
    if s is not None and not iso_ok(s):
        raise ValueError("since is not an ISO time")
    norm = lambda v: parse_ts(v).astimezone(TZ).isoformat(timespec="seconds")   # one zone, so string order is time order
    if s:
        s = norm(s)
        if not c["since"] or s < c["since"]:
            c["since"] = s
    g = obj.get("generated")
    c["source"] = "~/.codex/sessions"
    c["pushed"] = norm(g) if iso_ok(g) else dt.datetime.now(TZ).isoformat(timespec="seconds")


def build(wk):
    now = dt.datetime.now(TZ).isoformat(timespec="seconds")
    out = {}
    for cli, c in wk.items():
        weeks = sorted(c["weeks"].items(), reverse=True)
        tot = {k: sum(v[k] for _, v in weeks) for k in FIELDS}
        out[cli] = {"total": tot, "weeks": [dict(w=w, **v) for w, v in weeks],
                    "since": c.get("since"), "updated": c.get("pushed") or now}
    return out


def scan(dry=False):
    """Return (new messages, summary, needs push). Always refreshes updated (proof the scanner is alive)."""
    with locked():
        offs, wk = jload(OFFS, {}), jload(WEEKS, {})
        n = scan_claude(offs, wk)
        out = build(wk)
        changed = False
        if not dry:
            jsave(OFFS, offs); jsave(WEEKS, wk)
            old = jload(OUT, {})
            strip = lambda d: {k: {kk: vv for kk, vv in v.items() if kk != "updated"} for k, v in d.items()}
            changed = strip(old) != strip(out)
            jsave(OUT, out)
    return n, out, changed


def push():
    try:
        return subprocess.run([sys.executable, ST, "push"],
                              stdout=subprocess.DEVNULL, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def fmt(out):
    for cli, c in out.items():
        t = c["total"]
        print(f"{cli}: total in+out {t['in']+t['out']:,} · cache read {t['cr']:,} · cache write {t['cw']:,} (since {c.get('since')})")
        for w in c["weeks"][:6]:
            print(f"  {w['w']}  {w['in']+w['out']:>14,} {w['cr']:>16,} {w['cw']:>14,}")


def main(a):
    cmd = a[0] if a else "show"
    if cmd == "scan":
        dry = "--dry-run" in a
        n, out, changed = scan(dry)
        print(f"stcount: {n} new{' (dry-run, nothing written)' if dry else ''}")
        fmt(out)
        if changed and "--no-push" not in a:
            push()
    elif cmd == "loop":
        try:
            every = int(a[a.index("--every") + 1]) if "--every" in a else 1800
        except (IndexError, ValueError):
            print("stcount: --every needs a number of seconds", file=sys.stderr)
            return 2
        last_push, pending = 0, False
        while True:
            try:
                n, _, changed = scan()
                pending = pending or changed
                if pending or time.time() - last_push > 2 * 3600:   # push at least every 2 hours to refresh "updated"
                    if push():
                        pending, last_push = False, time.time()
                print(time.strftime("%F %T"), f"stcount: {n} new", flush=True)
            except Exception as e:
                print(time.strftime("%F %T"), "stcount error:", e, flush=True)
            time.sleep(every)
    elif cmd == "ingest-codex":
        pos = [x for x in a[1:] if not x.startswith("--")]
        src = pos[0] if pos and pos[0] != "-" else None
        if src:
            with open(src, encoding="utf-8") as f:
                obj = json.load(f)
        else:
            obj = json.load(sys.stdin)
        with locked():
            wk = jload(WEEKS, {})
            ingest_codex(obj, wk)
            jsave(WEEKS, wk)
            out = build(wk); old = jload(OUT, {})
            for k, v in old.items():          # keep the other CLIs' previous updated time
                if k != "Codex" and k in out:
                    out[k]["updated"] = v.get("updated", out[k]["updated"])
            jsave(OUT, out)
        print("stcount: merged Codex weekly totals"); fmt({"Codex": out["Codex"]})
        if "--no-push" not in a:
            push()
    elif cmd == "show":
        fmt(jload(OUT, {}))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
