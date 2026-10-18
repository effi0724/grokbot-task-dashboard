"""ETA calibration math for the GrokBot task dashboard.

Pure functions: no files, no clock, no network. Ratios are actual duration
divided by the original estimate. Cancelled tasks never become samples.
"""

from __future__ import annotations


def percentile(values, p):
    """Linear percentile. `p` is between 0 and 100. `values` is not mutated."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if p < 0 or p > 100:
        raise ValueError("percentile p must be between 0 and 100")
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    rank = (len(xs) - 1) * (p / 100.0)
    lo = int(rank)  # floor; ranks here are never negative
    hi = lo if lo == rank else lo + 1
    if hi >= len(xs):
        hi = len(xs) - 1
    if lo == hi:
        return xs[lo]
    weight = rank - lo
    return xs[lo] * (1.0 - weight) + xs[hi] * weight


def round_minutes(value):
    """Whole minutes at or above 10; otherwise one decimal. Never negative."""
    if value is None:
        return None
    value = float(value)
    if value <= 0:
        return 0
    if value >= 10:
        return int(round(value))
    rounded = round(value, 1)
    if float(rounded).is_integer():
        return int(rounded)
    return rounded


def record_from_task(bot, task):
    """Return a calibration sample, or None when the task should not count."""
    if not isinstance(task, dict):
        return None
    if task.get("state") != "done":
        return None
    try:
        estimate = float(task.get("estimate_minutes"))
        actual = float(task.get("actual_minutes"))
    except (TypeError, ValueError):
        return None
    if estimate <= 0 or actual <= 0:
        return None
    try:
        revisions = int(task.get("eta_revisions") or 0)
    except (TypeError, ValueError):
        revisions = 0
    return {
        "bot": bot or "",
        "task_type": (task.get("task_type") or "").strip(),
        "ratio": actual / estimate,
        "revisions": revisions,
        "estimate": estimate,
        "actual": actual,
    }


def summarize(samples):
    """Median ratio, interquartile spread, and overrun rate. None if empty."""
    if not samples:
        return None
    ratios = [s["ratio"] for s in samples]
    revisions = [s["revisions"] for s in samples]
    n = len(ratios)
    p25 = round(percentile(ratios, 25), 3)
    median = round(percentile(ratios, 50), 3)
    p75 = round(percentile(ratios, 75), 3)
    return {
        "n": n,
        "median_ratio": median,
        "p25_ratio": p25,
        "p75_ratio": p75,
        "mean_ratio": round(sum(ratios) / n, 3),
        "spread": round(p75 - p25, 3),
        "overrun_rate": round(sum(1 for r in ratios if r > 1.0) / n, 3),
        "median_revisions": round(percentile(revisions, 50), 2),
    }


def build_accuracy(records, window_days, min_samples):
    """Group samples by bot, task type, and the pair of both."""
    by_bot = {}
    by_type = {}
    by_both = {}
    for rec in records:
        by_bot.setdefault(rec["bot"], []).append(rec)
        task_type = rec.get("task_type") or ""
        if task_type:
            by_type.setdefault(task_type, []).append(rec)
            by_both.setdefault((rec["bot"], task_type), []).append(rec)

    def rows(mapping, key_fields):
        out = []
        for key in sorted(mapping, key=lambda item: item if isinstance(item, str) else (item[0], item[1])):
            summary = summarize(mapping[key])
            if not summary:
                continue
            row = dict(summary)
            if isinstance(key, tuple):
                for field, value in zip(key_fields, key):
                    row[field] = value
            else:
                row[key_fields[0]] = key
            out.append(row)
        return out

    return {
        "window_days": window_days,
        "min_samples": min_samples,
        "sample_count": len(records),
        "global": summarize(records),
        "bots": rows(by_bot, ("bot",)),
        "types": rows(by_type, ("task_type",)),
        "bot_types": rows(by_both, ("bot", "task_type")),
    }


def _row_matches(rows, **wanted):
    for row in rows or []:
        if all(row.get(key) == value for key, value in wanted.items()):
            return row
    return None


def select_basis(accuracy, bot, task_type, min_samples):
    """Most specific bucket with enough samples.

    Order: bot+type, type, bot, global. If every bucket is below
    `min_samples`, return the most specific non-empty bucket and mark it
    low-confidence. With no samples, basis is ``none``.
    """
    accuracy = accuracy or {}
    task_type = (task_type or "").strip()
    groups = []
    if bot and task_type:
        row = _row_matches(accuracy.get("bot_types"), bot=bot, task_type=task_type)
        if row:
            groups.append(("bot+type", row))
    if task_type:
        row = _row_matches(accuracy.get("types"), task_type=task_type)
        if row:
            groups.append(("type", row))
    if bot:
        row = _row_matches(accuracy.get("bots"), bot=bot)
        if row:
            groups.append(("bot", row))
    if accuracy.get("global"):
        groups.append(("global", accuracy["global"]))

    for basis, row in groups:
        if row["n"] >= min_samples:
            return basis, row, False
    for basis, row in groups:
        if row["n"] > 0:
            return basis, row, True
    return "none", None, True


def suggest_duration(raw_minutes, accuracy, bot, task_type="", min_samples=3):
    """Calibrated duration and range for a new raw estimate, in minutes.

    Enough samples: point estimate is raw * median(actual/estimate), and the
    range is raw * [p25, p75].

    A handful of samples: shrink the median toward 1.0 and widen the range
    toward [0.5, 2.0] so one odd task cannot dominate.

    No usable history: keep the raw estimate and offer a wide reference range.
    """
    try:
        raw = None if raw_minutes is None else float(raw_minutes)
    except (TypeError, ValueError):
        raw = None
    if raw is not None and raw <= 0:
        raw = None

    basis, row, low_confidence = select_basis(accuracy, bot, task_type, min_samples)
    result = {
        "raw_minutes": round_minutes(raw) if raw is not None else None,
        "minutes": None,
        "low_minutes": None,
        "high_minutes": None,
        "basis": basis,
        "n": 0 if row is None else row["n"],
        "median_ratio": None if row is None else row["median_ratio"],
        "p25_ratio": None if row is None else row["p25_ratio"],
        "p75_ratio": None if row is None else row["p75_ratio"],
        "spread": None if row is None else row["spread"],
        "overrun_rate": None if row is None else row["overrun_rate"],
        "low_confidence": True if row is None else low_confidence,
        "bot": bot or "",
        "task_type": (task_type or "").strip(),
        "applied_ratio": None,
        "reason": "missing_estimate" if raw is None else "ok",
    }
    if raw is None:
        result["basis"] = "none" if row is None else basis
        return result

    if row is None:
        ratio, low_r, high_r = 1.0, 0.5, 2.0
        result["basis"] = "none"
        result["low_confidence"] = True
        result["reason"] = "no_history"
    else:
        ratio = float(row["median_ratio"])
        low_r = float(row["p25_ratio"])
        high_r = float(row["p75_ratio"])
        if low_confidence:
            weight = row["n"] / float(min_samples)
            ratio = 1.0 + (ratio - 1.0) * weight
            low_r = (1.0 - weight) * 0.5 + weight * low_r
            high_r = (1.0 - weight) * 2.0 + weight * high_r
            result["reason"] = "low_sample"
        else:
            result["reason"] = "ok"
        ratio = round(ratio, 3)
        low_r = round(low_r, 3)
        high_r = round(high_r, 3)

    if high_r < low_r:
        low_r, high_r = high_r, low_r
    low_r = min(low_r, ratio)
    high_r = max(high_r, ratio)
    if high_r <= low_r:
        low_r = round(ratio * 0.9, 3)
        high_r = round(max(ratio * 1.1, low_r), 3)

    result["applied_ratio"] = ratio
    result["minutes"] = round_minutes(raw * ratio)
    result["low_minutes"] = round_minutes(raw * low_r)
    result["high_minutes"] = round_minutes(raw * high_r)
    if result["high_minutes"] < result["low_minutes"]:
        result["low_minutes"], result["high_minutes"] = result["high_minutes"], result["low_minutes"]
    if result["minutes"] < result["low_minutes"]:
        result["low_minutes"] = result["minutes"]
    if result["minutes"] > result["high_minutes"]:
        result["high_minutes"] = result["minutes"]
    return result


def format_minutes(value, lang="zh"):
    if value is None:
        return "unknown" if lang == "en" else "待估"
    minutes = float(value)
    if minutes <= 0:
        return "0 min" if lang == "en" else "0 分钟"
    if minutes < 60:
        shown = int(round(minutes))
        return f"{shown} min" if lang == "en" else f"{shown} 分钟"
    hours = minutes / 60.0
    if hours < 48:
        shown = f"{hours:.1f}"
        return f"{shown} h" if lang == "en" else f"{shown} 小时"
    days = hours / 24.0
    shown = f"{days:.1f}"
    return f"{shown} d" if lang == "en" else f"{shown} 天"


_BASIS = {
    "zh": {
        "bot+type": "该机器人 + 任务类型",
        "type": "任务类型",
        "bot": "该机器人",
        "global": "全部历史",
        "none": "样本不足",
    },
    "en": {
        "bot+type": "bot + task type",
        "type": "task type",
        "bot": "this bot",
        "global": "all history",
        "none": "not enough history",
    },
}


def format_suggestion(cal, lang="zh"):
    """One human line for `st set` and `st estimate`."""
    lang = "en" if lang == "en" else "zh"
    if not cal or cal.get("raw_minutes") is None:
        if lang == "en":
            return "Calibration: no original estimate, so there is no range. Pass --estimate 2h or --eta +2h."
        return "校准：没有原始工期，无法给出区间（可加 --estimate 2h 或 --eta +2h）。"

    raw = format_minutes(cal.get("raw_minutes"), lang)
    low = format_minutes(cal.get("low_minutes"), lang)
    high = format_minutes(cal.get("high_minutes"), lang)
    point = format_minutes(cal.get("minutes"), lang)
    if cal.get("basis") == "none" or not cal.get("n"):
        if lang == "en":
            return f"Calibration: not enough history. Original {raw}; reference range {low}–{high}."
        return f"校准：样本不足，暂用原始预估 {raw}（参考区间 {low}–{high}）。"

    basis = _BASIS[lang].get(cal.get("basis"), cal.get("basis"))
    ratio = cal.get("median_ratio")
    ratio_txt = "—" if ratio is None else f"{float(ratio):.2f}×"
    applied = cal.get("applied_ratio")
    applied_txt = "—" if applied is None else f"{float(applied):.2f}×"
    overrun = cal.get("overrun_rate")
    overrun_txt = "—" if overrun is None else f"{round(float(overrun) * 100)}%"
    shrunk = bool(cal.get("low_confidence")) and applied is not None and ratio is not None and abs(float(applied) - float(ratio)) > 0.001
    if lang == "en":
        ratio_clause = f"median {ratio_txt}, shrunk to {applied_txt}" if shrunk else f"median {ratio_txt}"
        line = (
            f"Calibration: {raw} → ~{point} ({low}–{high}); "
            f"basis {basis}; n={cal.get('n')}; {ratio_clause}; overrun {overrun_txt}."
        )
        if cal.get("low_confidence"):
            line += " Low confidence — treat the range as a hint."
        return line
    ratio_clause = f"中位倍率 {ratio_txt}，收缩后 {applied_txt}" if shrunk else f"中位倍率 {ratio_txt}"
    line = (
        f"校准：原始 {raw} → 约 {point}（范围 {low}–{high}），"
        f"依据{basis}，样本 {cal.get('n')}，{ratio_clause}，超期率 {overrun_txt}。"
    )
    if cal.get("low_confidence"):
        line += " 样本偏少，仅供参考。"
    return line


def format_outcome(task, lang="zh"):
    """Retrospective line when a task is marked done."""
    lang = "en" if lang == "en" else "zh"
    try:
        estimate = float(task.get("estimate_minutes"))
        actual = float(task.get("actual_minutes"))
    except (TypeError, ValueError):
        return None
    if estimate <= 0 or actual <= 0:
        return None
    ratio = actual / estimate
    revisions = int(task.get("eta_revisions") or 0)
    if lang == "en":
        return (
            f"Outcome: actual {format_minutes(actual, lang)} / estimate {format_minutes(estimate, lang)} "
            f"= {ratio:.2f}× ({revisions} ETA revisions)."
        )
    return (
        f"结果：实际 {format_minutes(actual, lang)} / 原始预估 {format_minutes(estimate, lang)} "
        f"= {ratio:.2f}×（ETA 修订 {revisions} 次）。"
    )
