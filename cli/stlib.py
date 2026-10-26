"""Local task state, snapshot assembly, and the `st` command line.

Stdlib only. Paths and the push target come from the environment:
ST_ROOT, ST_PUSH_URL, ST_TZ, ST_STATS_DAYS, ST_HISTORY_DAYS,
ST_STATS_MAX, ST_CALIBRATE_MIN, ST_LANG, ST_BOTS.
Quota cards: `st claude` (Claude Code) and `st quota --runner NAME`.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import calibration

RUNNER = "Claude Code"
DEFAULT_BOTS = [
    ("Coordinator", "Routes work across agents", "在多个代理之间分派工作"),
    ("Researcher", "Reads and summarizes sources", "阅读资料并整理摘要"),
    ("Coder", "Implements changes and opens PRs", "实现改动并提交合并请求"),
    ("Ops", "Deploy and monitoring", "部署与运行状态"),
]
STATES = ["running", "waiting", "queued", "blocked", "quota", "routine", "done", "cancelled"]
STATE_ZH = {
    "running": "进行中",
    "waiting": "等待中",
    "queued": "排队中",
    "blocked": "卡住了",
    "quota": "额度用完",
    "routine": "例行任务",
    "done": "已完成",
    "cancelled": "已取消",
}
STATE_EN = {
    "running": "running",
    "waiting": "waiting",
    "queued": "queued",
    "blocked": "blocked",
    "quota": "quota",
    "routine": "routine",
    "done": "done",
    "cancelled": "cancelled",
}
ACTIVE_ORDER = {name: index for index, name in enumerate(
    ["blocked", "quota", "running", "waiting", "queued", "routine"]
)}
SCHEMA_VERSION = 1

_clock = None


class CliError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def set_clock(fn):
    """Test hook. `fn` returns an aware datetime, or None restores the wall clock."""
    global _clock
    _clock = fn


def lang():
    value = os.environ.get("ST_LANG", "zh").strip().lower()
    return "en" if value.startswith("en") else "zh"


def zone():
    name = os.environ.get("ST_TZ", "America/New_York").strip() or "America/New_York"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/New_York")


def now():
    if _clock is not None:
        current = _clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=zone())
        else:
            current = current.astimezone(zone())
        return current.replace(microsecond=0)
    return datetime.now(zone()).replace(microsecond=0)


def iso(dt):
    return dt.isoformat() if dt else ""


def int_env(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def root_dir():
    return os.environ.get("ST_ROOT", "").strip() or os.path.expanduser("~/.grokbot-task-dashboard")


def bots_dir():
    return os.path.join(root_dir(), "bots")


def lock_path():
    return os.path.join(root_dir(), ".lock")


def token_path():
    return os.path.join(root_dir(), ".token")


def pending_path():
    return os.path.join(root_dir(), ".push_pending")


def push_url():
    return os.environ.get("ST_PUSH_URL", "").strip()


def stats_days():
    return int_env("ST_STATS_DAYS", 90)


def history_days():
    return int_env("ST_HISTORY_DAYS", 7)


def stats_max():
    return int_env("ST_STATS_MAX", 500)


def calibrate_min():
    return int_env("ST_CALIBRATE_MIN", 3)


def configured_bots():
    raw = os.environ.get("ST_BOTS", "").strip()
    if not raw:
        return list(DEFAULT_BOTS)
    parsed = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, desc = part.split(":", 1)
        else:
            name, desc = part, ""
        name = name.strip()
        if name:
            parsed.append((name, desc.strip(), desc.strip()))
    return parsed or list(DEFAULT_BOTS)


def t(zh, en):
    return en if lang() == "en" else zh


def parse_time(value, field="时间"):
    """Parse an ETA.

    Empty, '待估', '未知', '-', 'none', and 'unknown' mean no deadline.
    Relative: '+30m', '+2h', '+1.5h', '+1d' (optional space before the unit).
    Clock: 'HH:MM' (today, or tomorrow if that time has passed).
    Calendar: 'MM-DD HH:MM' or 'YYYY-MM-DD HH:MM' in ST_TZ, or a full ISO timestamp.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "待估", "未知", "-", "none", "unknown"):
        return None
    relative = re.fullmatch(r"\+(\d+(?:\.\d+)?)\s*([mhd])", text)
    if relative:
        amount = float(relative.group(1))
        unit = relative.group(2)
        if unit == "m":
            return now() + timedelta(minutes=amount)
        if unit == "h":
            return now() + timedelta(hours=amount)
        return now() + timedelta(days=amount)
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(_bad_time(field, text))
        candidate = now().replace(hour=hour, minute=minute, second=0)
        return candidate if candidate > now() else candidate + timedelta(days=1)
    month_day = re.fullmatch(r"(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})", text)
    if month_day:
        try:
            return datetime(
                now().year,
                int(month_day.group(1)),
                int(month_day.group(2)),
                int(month_day.group(3)),
                int(month_day.group(4)),
                tzinfo=zone(),
            )
        except ValueError:
            raise ValueError(_bad_time(field, text)) from None
    iso_text = text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}(:\d{2})?", text):
        iso_text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        raise ValueError(_bad_time(field, text)) from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone())
    return parsed.astimezone(zone())


def parse_duration_minutes(value):
    """Duration for --estimate. '90', '90m', '2h', '1.5h', '1d', '+45m'."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("", "待估", "未知", "-", "none", "unknown"):
        return None
    matched = re.fullmatch(
        r"\+?(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?",
        text,
    )
    if not matched:
        raise ValueError(_bad_duration(value))
    amount = float(matched.group(1))
    unit = matched.group(2) or "m"
    if unit.startswith("h"):
        minutes = amount * 60.0
    elif unit.startswith("d"):
        minutes = amount * 1440.0
    else:
        minutes = amount
    if minutes <= 0:
        return None
    return minutes


def _bad_time(field, value):
    if lang() == "en":
        return (
            f"st: could not parse {field} '{value}'. "
            "Try '2026-10-18 03:30', '03:30', '+45m', '+2h', or 'unknown'."
        )
    return (
        f"st: 看不懂的{field}「{value}」。"
        "可用：'2026-10-18 03:30'、'03:30'、'+45m'、'+2h'、'待估'。"
    )


def _bad_duration(value):
    if lang() == "en":
        return f"st: could not parse duration '{value}'. Try '90m', '2h', '1.5h', or '1d'."
    return f"st: 看不懂的工期「{value}」。可用：'90m'、'2h'、'1.5h'、'1d'。"


def fmt(isostr):
    if not isostr:
        return "unknown" if lang() == "en" else "待估"
    return datetime.fromisoformat(isostr).astimezone(zone()).strftime("%m-%d %H:%M")


def bot_path(bot):
    safe = re.sub(r"[/\\\x00]", "_", bot).strip().lstrip(".") or "unknown"
    return os.path.join(bots_dir(), safe + ".json")


def load(bot):
    path = bot_path(bot)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.setdefault("bot", bot)
        data.setdefault("tasks", {})
        data.setdefault("history", [])
        data.setdefault("updated", "")
        return data
    return {"bot": bot, "tasks": {}, "history": [], "updated": ""}


def _parse_finished(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone())
    return parsed.astimezone(zone())


def trim_history(history, days, limit, now_dt):
    cutoff = now_dt - timedelta(days=days)
    kept = []
    for item in history or []:
        finished = _parse_finished(item.get("finished"))
        if finished is not None and finished >= cutoff:
            kept.append(item)
    kept.sort(key=lambda item: item.get("finished") or "")
    if len(kept) > limit:
        kept = kept[-limit:]
    return kept


def save(data):
    os.makedirs(bots_dir(), exist_ok=True)
    data["history"] = trim_history(data.get("history", []), stats_days(), stats_max(), now())
    data["updated"] = iso(now())
    path = bot_path(data["bot"])
    fd, tmp = tempfile.mkstemp(dir=bots_dir(), prefix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.chmod(tmp, 0o664)
    os.replace(tmp, path)


class Locked:
    def __enter__(self):
        os.makedirs(root_dir(), exist_ok=True)
        self.handle = open(lock_path(), "a")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def all_bots():
    names = [item[0] for item in configured_bots()]
    directory = bots_dir()
    if os.path.isdir(directory):
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".json") or filename.startswith("."):
                continue
            path = os.path.join(directory, filename)
            try:
                with open(path, encoding="utf-8") as handle:
                    bot = json.load(handle).get("bot")
            except (OSError, json.JSONDecodeError):
                continue
            if bot and bot not in names and bot != RUNNER:
                names.append(bot)
    return names


def _descriptions():
    desc = {}
    desc_zh = {}
    for name, en, zh in configured_bots():
        desc[name] = en
        desc_zh[name] = zh
    return desc, desc_zh


def _in_stats_window(item, cutoff):
    finished = _parse_finished(item.get("finished"))
    return finished is not None and finished >= cutoff


def records_on_disk():
    records = []
    cutoff = now() - timedelta(days=stats_days())
    for name in all_bots():
        data = load(name)
        for item in data.get("history") or []:
            if not _in_stats_window(item, cutoff):
                continue
            rec = calibration.record_from_task(name, item)
            if rec:
                records.append(rec)
    runner = load(RUNNER)
    for item in runner.get("history") or []:
        if not _in_stats_window(item, cutoff):
            continue
        rec = calibration.record_from_task(RUNNER, item)
        if rec:
            records.append(rec)
    return records


def current_accuracy():
    return calibration.build_accuracy(records_on_disk(), stats_days(), calibrate_min())


def display_history(history, now_dt, limit=30):
    cutoff = now_dt - timedelta(days=history_days())
    rows = []
    for item in history or []:
        finished = _parse_finished(item.get("finished"))
        if finished is not None and finished >= cutoff:
            rows.append(item)
    rows.sort(key=lambda item: item.get("finished") or "", reverse=True)
    return rows[:limit]


def _raw_minutes(task):
    raw = task.get("estimate_minutes")
    try:
        raw = float(raw)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    return raw


def _with_calibration(task, bot_name, accuracy):
    view = dict(task)
    view["calibration"] = calibration.suggest_duration(
        _raw_minutes(task), accuracy, bot_name, task.get("task_type") or "", calibrate_min()
    )
    return view


def token_usage():
    """Token totals written by cli/stcount (keyed by runner name: total / weeks / since / updated)."""
    try:
        with open(os.path.join(root_dir(), ".token-usage.json"), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def snapshot():
    desc, desc_zh = _descriptions()
    accuracy = current_accuracy()
    current = now()
    bots = []
    for name in all_bots():
        data = load(name)
        tasks = [
            _with_calibration(task, name, accuracy)
            for task in data.get("tasks", {}).values()
        ]
        tasks.sort(key=lambda task: (ACTIVE_ORDER.get(task.get("state"), 9), task.get("eta") or "9999"))
        bots.append({
            "bot": name,
            "desc": data.get("desc") or desc.get(name, ""),
            "desc_zh": data.get("desc_zh") or desc_zh.get(name, "") or data.get("desc") or desc.get(name, ""),
            "updated": data.get("updated", ""),
            "tasks": tasks,
            "history": display_history(data.get("history"), current),
        })
    runner = load(RUNNER)
    runner_tasks = [
        _with_calibration(task, RUNNER, accuracy)
        for task in runner.get("tasks", {}).values()
    ]
    runner_tasks.sort(key=lambda task: task.get("eta") or "9999")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso(current),
        "tz": str(zone()),
        "stats_window_days": stats_days(),
        "history_window_days": history_days(),
        "bots": bots,
        "claude": runner.get("claude", {}),
        "quotas": runner.get("quotas", {}),
        "claude_tasks": runner_tasks,
        "tokens": token_usage(),
        "accuracy": accuracy,
    }


def push_retries():
    """ST_PUSH_RETRIES: total attempts per push (default 2). Watchers may raise it."""
    return min(int_env("ST_PUSH_RETRIES", 2), 6)


def _sleep(seconds):
    import time
    time.sleep(seconds)


def push(quiet=False):
    url = push_url()
    if not url:
        if not quiet:
            print(t(
                "st: 未设置 ST_PUSH_URL，只更新了本地状态",
                "st: ST_PUSH_URL is unset; local state only",
            ), file=sys.stderr)
        return False
    try:
        with open(token_path(), encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        if not quiet:
            print(t(
                "st: 没有推送令牌文件，只更新了本地状态",
                "st: no push token file; local state only",
            ), file=sys.stderr)
        return False
    if not token:
        print(t(
            "st: 推送令牌文件是空的，只更新了本地状态",
            "st: push token file is empty; local state only",
        ), file=sys.stderr)
        return False
    with Locked():
        body = json.dumps(snapshot(), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "grokbot-task-dashboard-st/1.0",
    })
    err = t("看板返回的状态码异常", "dashboard returned an unexpected status")
    ok = False
    tries = push_retries()
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                ok = response.status == 200
                if not ok:
                    err = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            ok = False
            err = f"HTTP {exc.code}"
            if exc.code in (401, 403):
                break  # a bad token will not fix itself
        except Exception as exc:
            ok = False
            err = exc.__class__.__name__
        if ok:
            break
        if attempt + 1 < tries:
            _sleep(min(30, 2 * 3 ** attempt))
    if ok:
        pending = pending_path()
        if os.path.exists(pending):
            os.remove(pending)
        if not quiet:
            print(t("st: 已同步到看板", "st: synced to the dashboard"))
        return True
    try:
        with open(pending_path(), "w", encoding="utf-8") as handle:
            handle.write(iso(now()))
    except OSError:
        pass
    print(t(
        f"st: 本地已更新，但同步看板失败（{err[:120]}）。下次调用会自动重试，也可手动 st push",
        f"st: saved locally, but dashboard sync failed ({err[:120]}). The next command retries, or run st push",
    ), file=sys.stderr)
    return False


def _clean_bot(name):
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise CliError(t("st: 需要有效的 --bot 名称", "st: --bot must be a non-empty name up to 80 characters"))
    return name


def _clean_task_id(task_id):
    task_id = (task_id or "").strip()
    if not task_id or len(task_id) > 80 or any(ch in task_id for ch in "/\\\x00"):
        raise CliError(t(
            "st: --task-id 需要稳定的短 id（不含斜杠，最长 80）",
            "st: --task-id must be a stable id without slashes (max 80 characters)",
        ))
    return task_id


def _clip(value, limit):
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit]


def _duration_from_eta(eta_dt, started_dt):
    if eta_dt is None:
        return None
    minutes = (eta_dt - started_dt).total_seconds() / 60.0
    if minutes <= 0:
        return None
    return minutes


def _apply_task_fields(task, args, started_dt):
    if args.title:
        task["title"] = _clip(args.title, 200)
    if args.stage is not None:
        task["stage"] = _clip(args.stage, 200)
    if args.pct is not None:
        task["pct"] = max(0, min(100, int(args.pct)))
    if args.note is not None:
        task["note"] = _clip(args.note, 2000)
    if getattr(args, "via", None) is not None:
        task["via"] = _clip(args.via, 80)
    if getattr(args, "task_type", None) is not None:
        task["task_type"] = _clip(args.task_type.strip(), 40)
    if getattr(args, "resume", None) is not None:
        task["resume"] = iso(parse_time(args.resume, t("恢复时间", "resume time")))
    explicit = None
    if getattr(args, "estimate", None) is not None:
        explicit = parse_duration_minutes(args.estimate)
        if explicit is None and str(args.estimate).strip() not in ("", "待估", "未知", "-", "none", "unknown"):
            raise ValueError(_bad_duration(args.estimate))
    eta_dt = None
    if args.eta is not None:
        eta_dt = parse_time(args.eta, "ETA")
        eta_iso = iso(eta_dt)
        if eta_iso != task.get("eta"):
            if task.get("eta"):
                task["eta_revisions"] = int(task.get("eta_revisions") or 0) + 1
            task["eta"] = eta_iso
            if not task.get("eta_first"):
                task["eta_first"] = eta_iso
    if not task.get("estimate_minutes"):
        if explicit:
            task["estimate_minutes"] = calibration.round_minutes(explicit)
            task["estimate_source"] = "flag"
        elif eta_dt is not None:
            derived = _duration_from_eta(eta_dt, started_dt)
            if derived:
                task["estimate_minutes"] = calibration.round_minutes(derived)
                task["estimate_source"] = "eta"
    if args.state:
        # Only the first queued -> running move resets the clock. Returning
        # from waiting keeps the original start so calibration stays honest.
        if task["state"] != args.state and args.state == "running" and task["state"] == "queued" and not task.get("ran"):
            task["started"] = iso(now())
        if args.state == "running":
            task["ran"] = True
        task["state"] = args.state


def cmd_set(args, finishing=False):
    bot = _clean_bot(args.bot)
    task_id = _clean_task_id(args.task_id)
    outcome = None
    with Locked():
        data = load(bot)
        prior = current_accuracy()
        task = data["tasks"].get(task_id)
        stamp = iso(now())
        created = task is None
        if task is None and finishing:
            raise CliError(t(f"st: 没有进行中的任务 {task_id}", f"st: no open task {task_id}"))
        if task is None:
            if not args.title:
                raise CliError(t("st: 新任务需要 --title", "st: a new task needs --title"))
            task = {
                "id": task_id,
                "title": _clip(args.title, 200) or task_id,
                "task_type": "",
                "stage": "",
                "pct": 0,
                "eta": "",
                "eta_first": "",
                "estimate_minutes": None,
                "estimate_source": "",
                "state": "running",
                "note": "",
                "via": "",
                "started": stamp,
                "updated": stamp,
                "eta_revisions": 0,
            }
        _apply_task_fields(task, args, _parse_finished(task.get("started")) or now())
        task["updated"] = stamp
        closing = finishing or task.get("state") in ("done", "cancelled")
        if closing:
            task["state"] = "cancelled" if args.state == "cancelled" else "done"
            if task["state"] == "done":
                task["pct"] = 100
            task["finished"] = stamp
            started = _parse_finished(task.get("started")) or now()
            task["actual_minutes"] = calibration.round_minutes(
                max(0.0, (now() - started).total_seconds() / 60.0)
            )
            data["tasks"].pop(task_id, None)
            data["history"].append(task)
            if task["state"] == "done":
                outcome = calibration.format_outcome(task, lang())
        else:
            data["tasks"][task_id] = task
        save(data)
        suggestion = calibration.suggest_duration(
            _raw_minutes(task), prior, bot, task.get("task_type") or "", calibrate_min()
        )
    state_label = STATE_EN[task["state"]] if lang() == "en" else STATE_ZH[task["state"]]
    print(t(
        f"st: [{bot}] {task['title']} → {state_label} {task.get('pct', 0)}%  ETA {fmt(task.get('eta'))}",
        f"st: [{bot}] {task['title']} → {state_label} {task.get('pct', 0)}%  ETA {fmt(task.get('eta'))}",
    ))
    print(calibration.format_suggestion(suggestion, lang()))
    if outcome:
        print(outcome)
    if not args.no_push:
        push()
    return task


def cmd_rm(args):
    bot = _clean_bot(args.bot)
    task_id = _clean_task_id(args.task_id)
    with Locked():
        data = load(bot)
        if data["tasks"].pop(task_id, None) is None:
            raise CliError(t(
                f"st: [{bot}] 没有任务 {task_id}",
                f"st: [{bot}] has no task {task_id}",
            ))
        save(data)
    print(t(
        f"st: 已删除 [{bot}] {task_id}（不进历史；正常结束请用 st done）",
        f"st: removed [{bot}] {task_id} (not added to history; use st done to finish a task)",
    ))
    if not args.no_push:
        push()


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}


def parse_usage_reset(text, current=None):
    """Parse 'Resets 9:59am (America/New_York)' or 'Resets Oct 19, 7:59pm (UTC)'.

    Returns an aware datetime in the configured zone, or None.
    """
    match = re.search(
        r"Resets\s+(?:([A-Za-z]{3})[a-z]*\s+(\d{1,2}),?\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)(?:\s*\(([^)]+)\))?",
        text, re.I,
    )
    if not match:
        return None
    month, day, hour, minute, ampm, zone_name = match.groups()
    try:
        tz = ZoneInfo(zone_name) if zone_name else zone()
    except Exception:
        tz = zone()
    hour = int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)
    base = (current or now()).astimezone(tz)
    if month:
        value = datetime(base.year, _MONTHS.get(month.lower()[:3], base.month), int(day),
                         hour, int(minute or 0), tzinfo=tz)
        if value < base - timedelta(days=180):
            value = value.replace(year=base.year + 1)
    else:
        value = base.replace(hour=hour, minute=int(minute or 0), second=0, microsecond=0)
        if value <= base - timedelta(minutes=1):
            value += timedelta(days=1)
    return value.astimezone(zone())


def parse_usage_text(text, current=None):
    """Read 'Current session' and 'Current week' blocks from a Claude Code /usage capture."""
    out = {}
    for key, label in (("session", r"Current session"), ("week", r"Current week[^\n]*")):
        match = re.search(label + r"\s*\n(.*?\n.*?\n)", text + "\n\n")
        if not match:
            continue
        block = match.group(1)
        used = re.search(r"(\d{1,3}(?:\.\d+)?)%\s*used", block)
        if used:
            out[key + "_left"] = round(max(0.0, 100.0 - float(used.group(1))), 1)
        reset = parse_usage_reset(block, current)
        if reset:
            out[key + "_reset"] = reset
    return out


def _clamp_pct(value):
    return max(0.0, min(100.0, float(value)))


def quota_consistent(info, explicit_state=None, reading=False, has_session=True):
    """Keep state and the remaining-quota bars consistent.

    Any bar at ~0 means quota. A fresh reading with room on both bars leaves
    quota. A manual quota without a reading empties the session bar.
    """
    session_left, week_left = info.get("session_left"), info.get("week_left")
    week_out = week_left is not None and week_left <= 0.5
    session_out = session_left is not None and session_left <= 0.5
    if week_out or session_out:
        info["state"] = "quota"
        info["limit_scope"] = "week" if week_out and not session_out else "session"
        reset = info.get("weekly_reset") if week_out and not session_out else info.get("reset")
        if reset and (reading or not info.get("resume") or info["resume"] < reset):
            info["resume"] = iso(datetime.fromisoformat(reset) + timedelta(minutes=30))
    elif explicit_state == "quota":
        if has_session:
            info["session_left"] = 0.0
        info["limit_scope"] = "session"
    elif info.get("state") == "quota" and reading:
        info["state"] = "ok"
        info.pop("limit_scope", None)
    elif info.get("state") != "quota":
        info.pop("limit_scope", None)
    return info


def _apply_quota_args(info, args):
    if args.state:
        info["state"] = args.state
    for key, label in (("reset", t("重置时间", "reset time")),
                       ("weekly_reset", t("每周重置时间", "weekly reset time")),
                       ("resume", t("恢复时间", "resume time"))):
        value = getattr(args, key, None)
        if value is not None:
            info[key] = iso(parse_time(value, label))
    for key, size in (("model", 80), ("plan", 80), ("note", 2000), ("used", 40), ("limit", 80), ("tool", 80)):
        value = getattr(args, key, None)
        if value is not None:
            info[key] = _clip(value, size)
    reading = False
    for key in ("session_left", "week_left"):
        value = getattr(args, key, None)
        if value is not None:
            info[key] = _clamp_pct(value)
            reading = True
    return reading


def _pct_text(value):
    return "?" if value is None else str(round(value))


def cmd_claude(args):
    usage = None
    if getattr(args, "from_usage", None):
        try:
            with open(args.from_usage, encoding="utf-8", errors="replace") as handle:
                usage = parse_usage_text(handle.read())
        except OSError as exc:
            raise CliError(t(f"st: 读不到 {args.from_usage}：{exc}", f"st: cannot read {args.from_usage}: {exc}"))
        if "session_left" not in usage and "week_left" not in usage:
            raise CliError(t(
                f"st: {args.from_usage} 里没有 /usage 数据，未改动看板",
                f"st: no /usage data in {args.from_usage}; nothing changed",
            ))
    with Locked():
        data = load(RUNNER)
        info = data.setdefault("claude", {})
        reading = _apply_quota_args(info, args)
        if usage:
            reading = True
            if "session_left" in usage:
                info["session_left"] = usage["session_left"]
            if "session_reset" in usage:
                info["reset"] = iso(usage["session_reset"])
            if "week_left" in usage:
                info["week_left"] = usage["week_left"]
            if "week_reset" in usage:
                info["weekly_reset"] = iso(usage["week_reset"])
        if reading:
            info["usage_read"] = iso(now())
        quota_consistent(info, args.state, reading)
        info["updated"] = iso(now())
        save(data)
    print(t(
        f"st: Claude Code → {info.get('state', '')}  5 小时剩 {_pct_text(info.get('session_left'))}%（刷新 {fmt(info.get('reset'))}）"
        f"  本周剩 {_pct_text(info.get('week_left'))}%（重置 {fmt(info.get('weekly_reset'))}）",
        f"st: Claude Code → {info.get('state', '')}  session {_pct_text(info.get('session_left'))}% left (reset {fmt(info.get('reset'))})"
        f"  week {_pct_text(info.get('week_left'))}% left (reset {fmt(info.get('weekly_reset'))})",
    ))
    if not args.no_push:
        push()


def _clean_runner(name):
    name = (name or "").strip()
    if not name or len(name) > 40 or name == RUNNER or "/" in name or name.startswith("."):
        raise CliError(t(f"st: 无效的执行者名称 {name!r}", f"st: invalid runner name {name!r}"))
    return name


def cmd_quota(args):
    name = _clean_runner(args.runner)
    with Locked():
        data = load(RUNNER)
        quotas = data.setdefault("quotas", {})
        info = quotas.setdefault(name, {})
        reading = _apply_quota_args(info, args)
        if reading:
            info["usage_read"] = iso(now())
        quota_consistent(info, args.state, reading, has_session=False)
        info["updated"] = iso(now())
        save(data)
    print(t(
        f"st: {name} → {info.get('state', '')}  用量 {info.get('used', '?')}/{info.get('limit', '?')}  "
        f"本周剩 {_pct_text(info.get('week_left'))}%  重置 {fmt(info.get('reset'))}",
        f"st: {name} → {info.get('state', '')}  used {info.get('used', '?')}/{info.get('limit', '?')}  "
        f"week {_pct_text(info.get('week_left'))}% left  reset {fmt(info.get('reset'))}",
    ))
    if not args.no_push:
        push()


def cmd_beat(args):
    """Watcher heartbeat: touch heartbeat/watcher only, never `updated` or progress.

    Exit code 3 when the task is no longer open, so a supervisor can stop.
    """
    bot = _clean_bot(args.bot)
    task_id = _clean_task_id(args.task_id)
    with Locked():
        data = load(bot)
        task = data["tasks"].get(task_id)
        if task is None:
            raise CliError(t(
                f"st: [{bot}] 没有进行中的任务 {task_id}，心跳忽略",
                f"st: [{bot}] no open task {task_id}; heartbeat ignored",
            ), code=3)
        stamp = iso(now())
        task["heartbeat"] = stamp
        watcher = dict(task.get("watcher") or {})
        if args.watcher is not None:
            watcher["name"] = _clip(args.watcher, 60)
        if args.alive is not None:
            watcher["alive"] = args.alive == "1"
        if args.restarts is not None:
            watcher["restarts"] = max(0, args.restarts)
        if args.wnote is not None:
            watcher["note"] = _clip(args.wnote, 300)
        watcher["checked"] = stamp
        task["watcher"] = watcher
        save(data)
    if not args.quiet:
        lost = "" if watcher.get("alive", True) else t("（盯任务进程已失联）", " (watcher lost)")
        print(t(f"st: [{bot}] {task['title']} 心跳 {fmt(stamp)}", f"st: [{bot}] {task['title']} heartbeat {fmt(stamp)}") + lost)
    if not args.no_push:
        push(quiet=args.quiet)


def _print_accuracy(accuracy):
    global_row = accuracy.get("global")
    if not global_row:
        print(t(
            "校准：统计窗口内还没有已完成且带原始预估的任务。",
            "Calibration: no completed tasks with an original estimate in the stats window.",
        ))
        return
    print(t(
        f"校准窗口 {accuracy.get('window_days')} 天，样本 {accuracy.get('sample_count')}，"
        f"最少样本 {accuracy.get('min_samples')}。全局中位倍率 {global_row['median_ratio']:.2f}×，"
        f"四分位距 {global_row['spread']:.2f}，超期率 {round(global_row['overrun_rate'] * 100)}%。",
        f"Window {accuracy.get('window_days')} days, n={accuracy.get('sample_count')}, "
        f"min samples {accuracy.get('min_samples')}. Global median {global_row['median_ratio']:.2f}×, "
        f"IQR {global_row['spread']:.2f}, overrun {round(global_row['overrun_rate'] * 100)}%.",
    ))
    header = t(
        f"{'范围':<28} {'n':>4} {'中位':>8} {'P25':>8} {'P75':>8} {'超期':>6}",
        f"{'scope':<28} {'n':>4} {'median':>8} {'p25':>8} {'p75':>8} {'over':>6}",
    )
    print(header)
    def line(label, row):
        print(
            f"{label:<28} {row['n']:>4} {row['median_ratio']:>7.2f}× "
            f"{row['p25_ratio']:>7.2f}× {row['p75_ratio']:>7.2f}× {round(row['overrun_rate'] * 100):>5}%"
        )
    for row in accuracy.get("bots") or []:
        line(row["bot"], row)
    for row in accuracy.get("types") or []:
        line(t(f"类型:{row['task_type']}", f"type:{row['task_type']}"), row)
    for row in accuracy.get("bot_types") or []:
        line(f"{row['bot']}/{row['task_type']}", row)


def cmd_list(args):
    with Locked():
        data = snapshot()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return data
    for bot in data["bots"]:
        if args.bot and bot["bot"] != args.bot:
            continue
        idle = t("（空闲）", " (idle)") if not bot["tasks"] else ""
        print(f"■ {bot['bot']}{idle}")
        for task in bot["tasks"]:
            via = f" ⇢{task['via']}" if task.get("via") else ""
            kind = f" [{task['task_type']}]" if task.get("task_type") else ""
            label = STATE_EN.get(task["state"], task["state"]) if lang() == "en" else STATE_ZH.get(task["state"], task["state"])
            print(
                f"   {task['id']:<22} {label:<8} {task.get('pct', 0):>3}%  "
                f"ETA {fmt(task.get('eta')):<11} {task['title']}{kind} · {task.get('stage', '')}{via}"
            )
            if task.get("calibration"):
                print("   " + calibration.format_suggestion(task["calibration"], lang()))
        if args.history:
            for item in bot["history"][:10]:
                mark = "✗" if item.get("state") == "cancelled" else "✓"
                print(f"   {mark} {fmt(item.get('finished'))} {item.get('title', '')}")
    info = data.get("claude") or {}
    if not args.bot or args.bot == RUNNER:
        print(t(
            f"■ Claude Code：{info.get('state', '未登记')}  重置 {fmt(info.get('reset'))}  {info.get('note', '')}",
            f"■ Claude Code: {info.get('state', 'unset')}  reset {fmt(info.get('reset'))}  {info.get('note', '')}",
        ))
        for task in data.get("claude_tasks") or []:
            label = STATE_EN.get(task["state"], task["state"]) if lang() == "en" else STATE_ZH.get(task["state"], task["state"])
            print(
                f"   {task['id']:<22} {label:<8} {task.get('pct', 0):>3}%  "
                f"ETA {fmt(task.get('eta')):<11} {task['title']}"
            )
    for name, quota in sorted((data.get("quotas") or {}).items()):
        if args.bot and args.bot != name:
            continue
        print(t(
            f"■ {name}：{quota.get('state', '未登记')}  本周剩 {_pct_text(quota.get('week_left'))}%  重置 {fmt(quota.get('reset'))}  {quota.get('note', '')}",
            f"■ {name}: {quota.get('state', 'unset')}  week {_pct_text(quota.get('week_left'))}% left  reset {fmt(quota.get('reset'))}  {quota.get('note', '')}",
        ))
    if os.path.exists(pending_path()):
        print(t("（有未同步到看板的更新，运行 st push）", "(dashboard sync is pending; run st push)"))
    if not args.bot:
        print()
        _print_accuracy(data.get("accuracy") or {})
    return data


def cmd_stats(args):
    with Locked():
        accuracy = current_accuracy()
    if getattr(args, "json", False):
        print(json.dumps(accuracy, ensure_ascii=False, indent=1))
    else:
        _print_accuracy(accuracy)
    return accuracy


def cmd_estimate(args):
    bot = _clean_bot(args.bot)
    task_type = (args.task_type or "").strip()
    if args.estimate:
        raw = parse_duration_minutes(args.estimate)
    elif args.eta:
        eta_dt = parse_time(args.eta, "ETA")
        raw = None if eta_dt is None else _duration_from_eta(eta_dt, now())
    else:
        raise CliError(t(
            "st: estimate 需要 --estimate 或 --eta",
            "st: estimate needs --estimate or --eta",
        ))
    if not raw:
        raise CliError(t(
            "st: 原始工期需要是未来的一段时间",
            "st: the original estimate has to be a duration in the future",
        ))
    with Locked():
        accuracy = current_accuracy()
    suggestion = calibration.suggest_duration(raw, accuracy, bot, task_type, calibrate_min())
    if args.json:
        print(json.dumps(suggestion, ensure_ascii=False, indent=1))
    else:
        print(calibration.format_suggestion(suggestion, lang()))
    return suggestion


def _add_task_args(parser, estimate=False):
    parser.add_argument("--bot", required=True, help="bot name, e.g. Coder / 机器人名称")
    parser.add_argument("--task-id", required=not estimate, help="stable id, e.g. site-tests / 稳定短 id")
    parser.add_argument("--title", help="task title / 任务标题")
    parser.add_argument("--task-type", help="optional type such as coding, research, ops / 任务类型")
    parser.add_argument("--stage", help="current step / 当前步骤")
    parser.add_argument("--pct", type=int, help="percent complete, 0-100 / 完成百分比")
    parser.add_argument("--eta", help="deadline: '2026-10-18 03:30', '03:30', '+45m', '+2h', '待估'")
    parser.add_argument("--estimate", help="original duration: '90m', '2h', '1d' / 原始工期，用于校准")
    parser.add_argument("--note", help="note / 备注")
    parser.add_argument("--via", help="who is doing the work, e.g. 'Claude Code' / 执行者")
    parser.add_argument("--resume", help="expected resume time when quota or waiting / 预计恢复时间")
    parser.add_argument("--no-push", action="store_true", help="write local state only / 只写本地")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="st",
        description="Record bot task progress and sync a snapshot. 登记任务进度并同步到看板。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    set_cmd = sub.add_parser("set", help="create or update a task / 新建或更新任务")
    _add_task_args(set_cmd)
    set_cmd.add_argument("--state", choices=STATES, help="running|waiting|queued|blocked|quota|routine|done|cancelled")

    done = sub.add_parser("done", help="finish a task and keep it in history / 完成并记入历史")
    _add_task_args(done)
    done.add_argument("--state", choices=["done", "cancelled"], default="done")

    remove = sub.add_parser("rm", help="delete a mistaken task; it is not kept in history / 删除错误登记")
    remove.add_argument("--bot", required=True)
    remove.add_argument("--task-id", required=True)
    remove.add_argument("--no-push", action="store_true")

    runner = sub.add_parser("claude", help="record Claude Code quota status / 登记 Claude Code 额度")
    runner.add_argument("--state", choices=["ok", "running", "quota", "unknown"])
    runner.add_argument("--reset", help="quota reset time / 额度重置时间")
    runner.add_argument("--resume", help="when queued work should resume / 计划恢复时间")
    runner.add_argument("--model")
    runner.add_argument("--plan")
    runner.add_argument("--note")
    runner.add_argument("--weekly-reset", dest="weekly_reset", help="weekly limit reset / 每周额度重置时间")
    runner.add_argument("--session-left", dest="session_left", type=float, help="5-hour quota left, 0-100 / 5 小时额度剩余百分比")
    runner.add_argument("--week-left", dest="week_left", type=float, help="weekly quota left, 0-100 / 本周额度剩余百分比")
    runner.add_argument("--from-usage", dest="from_usage", metavar="FILE",
                        help="read a captured /usage panel (scripts/claude-usage.sh) / 从抓取的 /usage 文本读取额度")
    runner.add_argument("--no-push", action="store_true")

    quota = sub.add_parser("quota", help="record another subscription runner's quota, e.g. Gemini / 登记其他订阅执行者的额度")
    quota.add_argument("--runner", required=True, help="runner name; tasks with a matching --via follow it / 执行者名称")
    quota.add_argument("--state", choices=["ok", "running", "quota", "login", "unknown"], help="login = not signed in / 未登录")
    quota.add_argument("--reset", help="next quota refresh / 下次额度刷新")
    quota.add_argument("--weekly-reset", dest="weekly_reset", help="weekly limit reset / 每周额度重置")
    quota.add_argument("--resume", help="when queued work should resume / 计划恢复时间")
    quota.add_argument("--week-left", dest="week_left", type=float, help="weekly quota left, 0-100 / 本周额度剩余百分比")
    quota.add_argument("--used", help="free text, e.g. '35%%' / 已用量")
    quota.add_argument("--limit", help="free text, e.g. 'rolling 5h window' / 上限说明")
    for flag in ("--model", "--plan", "--tool", "--note"):
        quota.add_argument(flag)
    quota.add_argument("--no-push", action="store_true")

    beat = sub.add_parser("beat", help="watcher heartbeat; does not change progress or updated / 盯任务进程心跳")
    beat.add_argument("--bot", required=True)
    beat.add_argument("--task-id", required=True)
    beat.add_argument("--watcher", help="watcher name / 名称")
    beat.add_argument("--alive", choices=["0", "1"], help="1 = running, 0 = lost / 在线或失联")
    beat.add_argument("--restarts", type=int, help="automatic restarts so far / 已自动重启次数")
    beat.add_argument("--wnote", help="watcher note / 备注")
    beat.add_argument("--quiet", action="store_true")
    beat.add_argument("--no-push", action="store_true")

    listing = sub.add_parser("list", help="show current status / 查看当前状态")
    listing.add_argument("--bot")
    listing.add_argument("--history", action="store_true")
    listing.add_argument("--json", action="store_true")

    stats = sub.add_parser("stats", help="show estimate accuracy / 查看预估准确度")
    stats.add_argument("--json", action="store_true")

    estimate = sub.add_parser("estimate", help="suggest a calibrated ETA without writing / 只给出校准建议")
    estimate.add_argument("--bot", required=True)
    estimate.add_argument("--task-type")
    estimate.add_argument("--estimate")
    estimate.add_argument("--eta")
    estimate.add_argument("--json", action="store_true")

    sub.add_parser("push", help="sync local state to the dashboard / 把本地状态同步到看板")
    sub.add_parser("token-sha256", help="print the SHA-256 of the local push token / 打印本地令牌的 SHA-256")
    return parser


def cmd_token_sha():
    try:
        with open(token_path(), encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError as exc:
        raise CliError(t(
            f"st: 读不到令牌文件（{token_path()}）",
            f"st: cannot read token file ({token_path()})",
        )) from exc
    if not token:
        raise CliError(t("st: 令牌文件是空的", "st: token file is empty"))
    print(hashlib.sha256(token.encode("utf-8")).hexdigest())


def dispatch(args):
    if args.cmd == "set":
        cmd_set(args)
    elif args.cmd == "done":
        cmd_set(args, finishing=True)
    elif args.cmd == "rm":
        cmd_rm(args)
    elif args.cmd == "claude":
        cmd_claude(args)
    elif args.cmd == "beat":
        cmd_beat(args)
    elif args.cmd == "quota":
        cmd_quota(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "stats":
        cmd_stats(args)
    elif args.cmd == "estimate":
        cmd_estimate(args)
    elif args.cmd == "push":
        if not push():
            raise CliError(t("st: 同步失败", "st: sync failed"))
    elif args.cmd == "token-sha256":
        cmd_token_sha()
    else:
        raise CliError(f"st: unknown command {args.cmd}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        dispatch(args)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0
