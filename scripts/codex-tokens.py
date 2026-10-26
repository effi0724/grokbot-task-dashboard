#!/usr/bin/env python3
"""codex-tokens - weekly Codex CLI token totals from local session logs (read-only).

Run it on the machine where Codex CLI runs. It reads ~/.codex/sessions/**/*.jsonl (override with
CODEX_SESSIONS), sends no requests, and never touches auth.json. It prints one JSON line; feed it to
`cli/stcount ingest-codex -` on the machine that runs st, for example:
    python3 scripts/codex-tokens.py | ssh dashboard-host 'cli/stcount ingest-codex -'

Counting: token_count events carry total_token_usage, a running total for the session. Within each
file, the delta between consecutive totals is booked to the week of the later event (a smaller total
means the counter restarted). The first event of a file, or one after a reset, counts only its
last_token_usage, because a resumed or forked session starts with the parent's running total.
Events copied verbatim into a resumed/forked file (same timestamp and totals) are baselines only.
Fields: in = input_tokens - cached_input_tokens, cr = cached_input_tokens,
out = output_tokens (includes reasoning tokens), cw = 0 (Codex reports no cache writes).
Week boundaries use ST_TZ (default America/New_York).
"""
import datetime as dt, glob, json, os, sys
from zoneinfo import ZoneInfo
TZ = ZoneInfo(os.environ.get("ST_TZ", "").strip() or "America/New_York")
ROOT = os.path.expanduser(os.environ.get("CODEX_SESSIONS", "").strip() or "~/.codex/sessions")

def week(t):
    y, w, _ = t.astimezone(TZ).isocalendar(); return f"{y}-W{w:02d}"

def main():
    weeks, since, files, seen_ev = {}, None, 0, set()
    for p in sorted(glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True)):
        files += 1; prev = None
        try:
            lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            pl = r.get("payload") if isinstance(r.get("payload"), dict) else r
            if pl.get("type") != "token_count":
                continue
            info = pl.get("info")
            tot = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(tot, dict):
                continue
            try:
                cur = {k: max(0, int(tot.get(k) or 0)) for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
            except (TypeError, ValueError):
                continue
            ek = (str(r.get("timestamp")), tuple(cur.values()))
            if ek in seen_ev:          # event copied from a resumed/forked session: baseline only
                prev = cur; continue
            seen_ev.add(ek)
            if prev and all(cur[k] >= prev[k] for k in cur):
                d = {k: cur[k] - prev[k] for k in cur}
            else:
                # first event or counter reset: total may include the parent session, so count only last_token_usage
                lt = info.get("last_token_usage")
                lt = lt if isinstance(lt, dict) else {}
                try:
                    d = {k: min(cur[k], max(0, int(lt.get(k) or 0))) for k in cur}
                except (TypeError, ValueError):
                    d = {k: 0 for k in cur}
            prev = cur
            if not any(d.values()):
                continue
            try:
                t = dt.datetime.fromisoformat(str(r.get("timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            a = weeks.setdefault(week(t), {"in": 0, "out": 0, "cr": 0, "cw": 0})
            a["in"] += max(0, d["input_tokens"] - d["cached_input_tokens"]); a["cr"] += d["cached_input_tokens"]; a["out"] += d["output_tokens"]
            s = t.astimezone(TZ).isoformat(timespec="seconds"); since = min(since or s, s)
    print(json.dumps({"token_weeks": weeks, "since": since, "files": files,
                      "generated": dt.datetime.now(TZ).isoformat(timespec="seconds")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
