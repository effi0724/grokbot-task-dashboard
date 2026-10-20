import { calibrationLine } from "./calibration.js";
import { STRINGS, initialLang } from "./i18n.js";
import {
  escapeHtml,
  formatAgo,
  formatMinutes,
  formatPercent,
  formatRatio,
  formatRemaining,
  formatSpread,
  formatWhen,
  ratioClass,
  sampleRatio,
  applyQuotaToTasks,
  quotaRunners,
  usageIsStale,
  taskHealth,
  formatSpan,
} from "./format.js";

const COLOR = {
  running: "var(--run)",
  waiting: "var(--wait)",
  queued: "var(--queue)",
  blocked: "var(--block)",
  quota: "var(--quota)",
  routine: "var(--routine)",
  done: "var(--ok)",
};
const ORDER = ["blocked", "quota", "running", "waiting", "queued", "routine"];
const STATE_CLASS = {
  running: "s-running",
  waiting: "s-waiting",
  queued: "s-queued",
  blocked: "s-blocked",
  quota: "s-quota",
  routine: "s-routine",
  done: "s-done",
  cancelled: "s-cancelled",
};

function wrap(lang, text) {
  return lang === "en" ? `(${text})` : `（${text}）`;
}

function badge(state, strings) {
  const cls = STATE_CLASS[state] || "s-queued";
  const label = strings.states[state] || state;
  return `<span class="badge ${cls}" data-f="${escapeHtml(state)}" title="${escapeHtml(strings.filterHint)}">${escapeHtml(label)}</span>`;
}

function matches(task, filter, nowMs) {
  return filter === "stale" ? Boolean(taskHealth(task, nowMs)) : task.state === filter;
}

function healthBadge(health, strings, lang) {
  const span = formatSpan(health.minutes, lang);
  const text = strings.health[health.reason](span);
  const tip = health.note ? `${text} · ${health.note}` : text;
  return `<span class="badge s-${health.kind}" data-f="stale" title="${escapeHtml(tip)} · ${escapeHtml(strings.filterHint)}">${escapeHtml(text)}</span>`;
}

function taskCard(task, strings, lang, timeZone, nowMs) {
  const state = task.state || "running";
  const color = COLOR[state] || "var(--run)";
  const showBar = !["routine", "queued"].includes(state) || (task.pct || 0) > 0;
  let eta = "";
  if (task.eta) {
    const left = formatRemaining(task.eta, lang, nowMs);
    const when = formatWhen(task.eta, lang, timeZone);
    eta = left
      ? `${strings.eta} ${when} ${wrap(lang, left)}`
      : `<span class="late">${strings.eta} ${when} · ${strings.overdue}</span>`;
    if (task.eta_revisions) eta += ` · ${escapeHtml(strings.revisions(Number(task.eta_revisions) || 0))}`;
  } else if (state !== "routine") {
    eta = strings.etaUnknown;
  }
  const health = taskHealth(task, nowMs);
  const stale = Boolean(health);
  const watcher = task.watcher || null;
  const kind = task.task_type ? `<span class="via">${escapeHtml(task.task_type)}</span>` : "";
  const via = task.via ? `<span class="via">⇢ ${escapeHtml(task.via)}</span>` : "";
  const cal = calibrationLine(task.calibration, lang);
  return `<div class="task">
    <div class="tt"><div class="title">${escapeHtml(task.title)}${kind}${via}</div><span class="badges">${health ? healthBadge(health, strings, lang) : ""}${badge(state, strings)}</span></div>
    ${task.stage ? `<div class="stage">${escapeHtml(task.stage)}</div>` : ""}
    ${showBar ? `<div class="bar"><i style="width:${Math.max(2, Math.min(100, Number(task.pct) || 0))}%;background:${color}"></i></div>` : ""}
    <div class="meta">
      ${showBar ? `<span>${Number(task.pct) || 0}%</span>` : ""}
      ${eta ? `<span>${eta}</span>` : ""}
      ${task.resume ? `<span>${strings.resume}${lang === "en" ? ": " : "："}${formatWhen(task.resume, lang, timeZone)}</span>` : ""}
      <span class="${stale ? "stale" : ""}">${strings.updatedAt} ${formatAgo(task.updated, lang, nowMs)}</span>
      ${watcher ? `<span class="${watcher.alive === false ? "late" : ""}">${escapeHtml(strings.watcherLine(watcher.alive !== false, task.heartbeat ? formatAgo(task.heartbeat, lang, nowMs) : "", Number(watcher.restarts) || 0))}</span>` : ""}
    </div>
    ${cal ? `<div class="cal">${escapeHtml(cal)}</div>` : ""}
    ${task.auto === "paused" ? `<div class="note">${escapeHtml(strings.autoPaused(task.auto_runner))}</div>` : ""}
    ${task.auto === "recovered" ? `<div class="note">${escapeHtml(strings.autoRecovered)}</div>` : ""}
    ${task.note ? `<div class="note">${escapeHtml(task.note)}</div>` : ""}
  </div>`;
}

function statRows(rows, labelFor) {
  return (rows || []).map((row) => {
    const hot = ratioClass(row.median_ratio);
    return `<tr>
      <td>${escapeHtml(labelFor(row))}</td>
      <td>${Number(row.n) || 0}</td>
      <td class="${hot}">${formatRatio(row.median_ratio)}</td>
      <td>${formatRatio(row.p25_ratio)}</td>
      <td>${formatRatio(row.p75_ratio)}</td>
      <td>${formatSpread(row.spread)}</td>
      <td>${formatPercent(row.overrun_rate)}</td>
      <td>${row.median_revisions == null ? "—" : Number(row.median_revisions)}</td>
    </tr>`;
  }).join("");
}

function statTable(title, rows, labelFor, strings) {
  if (!rows || !rows.length) return "";
  const head = ["colScope", "colN", "colMedian", "colP25", "colP75", "colSpread", "colOverrun", "colRevisions"]
    .map((key) => `<th>${strings[key]}</th>`).join("");
  return `<div class="card"><h4>${escapeHtml(title)}</h4>
    <div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${statRows(rows, labelFor)}</tbody></table></div></div>`;
}

function accuracyBlock(state, strings) {
  const accuracy = state.accuracy;
  if (!accuracy || !accuracy.sample_count) return `<div class="empty">${strings.accuracyEmpty}</div>`;
  const globalRow = accuracy.global
    ? statTable(strings.global, [{ ...accuracy.global, bot: strings.global }], () => strings.global, strings)
    : "";
  return `<p class="sub window">${strings.window(accuracy.window_days, accuracy.sample_count, accuracy.min_samples)}</p>
    <div class="acc-grid">
      ${globalRow}
      ${statTable(strings.byBot, accuracy.bots, (row) => row.bot, strings)}
      ${statTable(strings.byType, accuracy.types, (row) => row.task_type, strings)}
    </div>
    ${statTable(strings.byBoth, accuracy.bot_types, (row) => `${row.bot} / ${row.task_type}`, strings)}`;
}

function pctBar(label, value, suffix) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  const color = pct > 50 ? "var(--ok)" : pct > 20 ? "var(--wait)" : "var(--block)";
  return `<div class="qrow"><span>${escapeHtml(label)}</span><b>${Math.round(pct)}%${suffix ? ` ${escapeHtml(suffix)}` : ""}</b></div>
    <div class="bar"><i style="width:${Math.max(2, pct)}%;background:${color}"></i></div>`;
}

function quotaCard(runner, strings, lang, timeZone, nowMs) {
  const info = runner.info;
  const label = strings.claudeStates[info.state] || strings.claudeUnset;
  const badgeClass = info.state === "quota" ? "s-quota" : info.state === "running" ? "s-running" : info.state === "ok" ? "s-done" : "s-queued";
  const when = (iso) => {
    const left = formatRemaining(iso, lang, nowMs);
    return `${formatWhen(iso, lang, timeZone)} ${wrap(lang, left || strings.passed)}`;
  };
  let bars = "";
  if (runner.session && info.session_left != null) {
    const suffix = info.session_auto ? wrap(lang, strings.refilled) : info.session_forced ? wrap(lang, strings.hitLimit) : "";
    bars += pctBar(strings.sessionLeft, info.session_left, suffix);
    if (info.reset && !info.session_auto) bars += `<div class="note">${escapeHtml(strings.refresh)}${lang === "en" ? ": " : "："}${escapeHtml(when(info.reset))}</div>`;
  }
  bars += info.week_left == null
    ? `<div class="note">${escapeHtml(strings.weekUnknown)}</div>`
    : pctBar(strings.weekLeft, info.week_left, info.week_auto ? wrap(lang, strings.refilled) : "");
  const read = info.usage_read || (runner.session ? "" : info.updated);
  const stale = usageIsStale(read, nowMs);
  const kv = [
    !runner.session && info.reset ? [strings.reset, when(info.reset)] : null,
    info.weekly_reset ? [strings.weeklyReset, when(info.weekly_reset)] : null,
    info.state === "quota" && info.until ? [strings.quotaBack, when(info.until)] : null,
    info.resume ? [strings.resumeRun, formatWhen(info.resume, lang, timeZone)] : null,
    info.used ? [strings.used, info.limit ? `${info.used} / ${info.limit}` : info.used] : null,
    info.model ? [strings.model, info.model] : null,
    info.plan ? [strings.plan, info.plan] : null,
    info.tool ? [strings.tool, info.tool] : null,
    [strings.updatedLabel, formatAgo(info.updated, lang, nowMs) || "—"],
  ].filter(Boolean);
  const readRow = `<span>${escapeHtml(strings.usageRead)}</span><span class="${stale ? "stale" : ""}">${read ? escapeHtml(formatAgo(read, lang, nowMs) + (stale ? ` · ${strings.maybeStale}` : "")) : escapeHtml(strings.notRead)}</span>`;
  const note = info.recovered ? strings.recoveredNote : info.note;
  return `<div class="card ${info.state === "quota" ? "alert" : ""}"><div class="ch"><h2>${escapeHtml(strings.quotaOf(runner.name))}</h2><span class="badge ${badgeClass}">${escapeHtml(label)}</span></div>
      ${bars}
      <div class="kv">${kv.map(([key, value]) => `<span>${escapeHtml(key)}</span><span>${escapeHtml(value)}</span>`).join("")}${readRow}</div>
      ${note ? `<div class="note">${escapeHtml(note)}</div>` : ""}</div>`;
}

function claudeBlock(state, strings, lang, timeZone, nowMs) {
  const runners = quotaRunners(state, nowMs);
  const handed = [];
  (state.bots || []).forEach((bot) => {
    (bot.tasks || []).forEach((task) => {
      if (runners.some((runner) => runner.match.test(task.via || ""))) handed.push([bot.bot, task]);
    });
  });
  (state.claude_tasks || []).forEach((task) => handed.push(["Claude Code", task]));
  const handedHtml = handed.length
    ? handed.map(([bot, task]) => `<div class="task"><div class="tt"><div class="title">${escapeHtml(task.title)}<span class="via">${escapeHtml(bot)}${task.via ? ` ⇢ ${escapeHtml(task.via)}` : ""}</span></div>${badge(task.state, strings)}</div>
        <div class="meta">${task.eta ? `<span>${strings.eta} ${formatWhen(task.eta, lang, timeZone)}</span>` : ""}${task.resume ? `<span>${strings.start}${lang === "en" ? ": " : "："}${formatWhen(task.resume, lang, timeZone)}</span>` : ""}</div></div>`).join("")
    : `<div class="empty">${strings.claudeEmpty}</div>`;
  return runners.map((runner) => quotaCard(runner, strings, lang, timeZone, nowMs)).join("")
    + `<div class="card"><div class="ch"><h2>${strings.claudeTasks}</h2></div>${handedHtml}</div>`;
}

function historyBlock(state, strings, lang, timeZone) {
  const rows = [];
  (state.bots || []).forEach((bot) => {
    (bot.history || []).forEach((task) => rows.push([bot.bot, task]));
  });
  rows.sort((a, b) => String(b[1].finished || "").localeCompare(String(a[1].finished || "")));
  if (!rows.length) return `<div class="empty">${strings.histEmpty}</div>`;
  const body = rows.slice(0, 40).map(([bot, task]) => {
    const minutes = task.actual_minutes != null ? Number(task.actual_minutes) : null;
    const duration = minutes == null || Number.isNaN(minutes)
      ? "—"
      : formatMinutes(minutes, lang);
    const ratio = sampleRatio(task);
    const cancelled = task.state === "cancelled" ? ` ${wrap(lang, strings.states.cancelled)}` : "";
    return `<tr>
      <td>${formatWhen(task.finished, lang, timeZone)}</td>
      <td>${escapeHtml(bot)}</td>
      <td>${escapeHtml(task.title)}${cancelled}${task.note ? `<div class="note">${escapeHtml(task.note)}</div>` : ""}</td>
      <td>${escapeHtml(task.task_type || "—")}</td>
      <td>${duration}</td>
      <td class="${ratioClass(ratio)}">${formatRatio(ratio)}</td>
    </tr>`;
  }).join("");
  return `<div class="tbl-wrap"><table><thead><tr>
      <th>${strings.colFinished}</th><th>${strings.colBot}</th><th>${strings.colTask}</th>
      <th>${strings.colType}</th><th>${strings.colDuration}</th><th>${strings.colRatio}</th>
    </tr></thead><tbody>${body}</tbody></table></div>`;
}

export function render(rawState, lang, options = {}) {
  const strings = STRINGS[lang] || STRINGS.zh;
  const filter = options.filter || "";
  // Example snapshots use a fixed clock; render them relative to that clock.
  const exampleClock = rawState && rawState._example && rawState.generated_at ? Date.parse(rawState.generated_at) : NaN;
  const nowMs = options.nowMs || (Number.isFinite(exampleClock) ? exampleClock : Date.now());
  const state = applyQuotaToTasks(rawState, nowMs);
  const timeZone = state.tz || "America/New_York";
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  document.title = strings.title;
  const title = document.getElementById("title");
  const subtitle = document.getElementById("subtitle");
  if (title) title.textContent = strings.title;
  if (subtitle) subtitle.textContent = strings.subtitle;
  const banner = document.getElementById("banner");
  if (banner) {
    const show = Boolean(options.example || state._example);
    banner.hidden = !show;
    banner.textContent = show ? strings.exampleBanner : "";
  }
  const gen = document.getElementById("gen");
  if (gen) {
    gen.textContent = state.generated_at
      ? strings.updated(formatWhen(state.generated_at, lang, timeZone), formatAgo(state.generated_at, lang, nowMs))
      : strings.noData;
  }
  const counts = {};
  let idle = 0;
  const bots = document.getElementById("bots");
  if (bots) {
    bots.innerHTML = (state.bots || []).filter((bot) => {
      const all = bot.tasks || [];
      all.forEach((task) => {
        counts[task.state] = (counts[task.state] || 0) + 1;
        if (taskHealth(task, nowMs)) counts.stale = (counts.stale || 0) + 1;
      });
      if (!all.length) idle += 1;
      if (!filter) return true;
      return filter === "idle" ? !all.length : all.some((task) => matches(task, filter, nowMs));
    }).map((bot) => {
      const tasks = (bot.tasks || []).filter((task) => !filter || filter === "idle" || matches(task, filter, nowMs));
      const active = tasks.filter((task) => task.state !== "routine");
      const cls = tasks.some((task) => task.state === "blocked")
        ? "bad"
        : tasks.some((task) => task.state === "quota")
          ? "alert"
          : tasks.length ? "" : "idle";
      const label = !tasks.length ? strings.idle : active.length ? strings.taskCount(active.length) : strings.routineOnly;
      const desc = lang === "en" ? (bot.desc || bot.desc_zh || "") : (bot.desc_zh || bot.desc || "");
      const last = bot.history && bot.history[0];
      const colon = lang === "en" ? ": " : "：";
      const empty = `${strings.emptyBot}${last ? ` · ${strings.lastDone}${colon}${escapeHtml(last.title)} ${wrap(lang, formatWhen(last.finished, lang, timeZone))}` : ""}`;
      return `<div class="card ${cls}"><div class="ch"><h2>${escapeHtml(bot.bot)}</h2><span class="sub">${label}</span></div>
        ${desc ? `<p class="desc">${escapeHtml(desc)}</p>` : ""}
        ${tasks.length ? tasks.map((task) => taskCard(task, strings, lang, timeZone, nowMs)).join("") : `<div class="empty">${empty}</div>`}
      </div>`;
    }).join("") || (filter ? `<div class="empty">${strings.filterEmpty}</div>` : "");
  }
  const sum = document.getElementById("sum");
  if (sum) {
    const on = (key) => (filter === key ? " on" : "");
    sum.innerHTML = `<span class="chip${on("")}" data-f="">${strings.all}</span>`
      + ORDER.filter((key) => counts[key] || filter === key).map((key) =>
        `<span class="chip${on(key)}" data-f="${key}" style="border-color:${COLOR[key]}">${strings.states[key]} <b>${counts[key] || 0}</b></span>`,
      ).join("")
      + (counts.stale || filter === "stale" ? `<span class="chip${on("stale")}" data-f="stale" style="border-color:var(--block)">${strings.staleChip} <b>${counts.stale || 0}</b></span>` : "")
      + `<span class="chip${on("idle")}" data-f="idle">${strings.idleBots} <b>${idle}</b></span>`;
  }
  const accuracyTitle = document.getElementById("accuracy-title");
  const accuracyNote = document.getElementById("accuracy-note");
  const accuracyBody = document.getElementById("accuracy-body");
  if (accuracyTitle) accuracyTitle.textContent = strings.accuracyTitle;
  if (accuracyNote) accuracyNote.textContent = strings.accuracyNote;
  if (accuracyBody) accuracyBody.innerHTML = accuracyBlock(state, strings);
  const claudeTitle = document.getElementById("claude-title");
  const claude = document.getElementById("claude");
  if (claudeTitle) claudeTitle.textContent = strings.claudeTitle;
  if (claude) claude.innerHTML = claudeBlock(state, strings, lang, timeZone, nowMs);
  const histTitle = document.getElementById("hist-title");
  const hist = document.getElementById("hist");
  if (histTitle) histTitle.textContent = state.history_window_days
    ? `${strings.histTitle} ${wrap(lang, `${state.history_window_days} ${lang === "en" ? "days" : "天"}`)}`
    : strings.histTitle;
  if (hist) hist.innerHTML = historyBlock(state, strings, lang, timeZone);
  const foot = document.getElementById("foot");
  if (foot) foot.textContent = strings.footer;
}

export function boot() {
  const params = new URLSearchParams(location.search);
  const example = params.get("example") === "1";
  let lang = initialLang();
  let last = null;
  let filter = decodeURIComponent((location.hash.match(/f=([^&]*)/) || [])[1] || "");
  const button = document.getElementById("lang");
  const paint = () => {
    if (button) button.textContent = lang === "en" ? "中文" : "EN";
    if (last) render(last, lang, { example, filter });
  };
  document.addEventListener("click", (event) => {
    const el = event.target.closest("[data-f]");
    if (!el) return;
    filter = filter === el.dataset.f ? "" : el.dataset.f;
    history.replaceState(null, "", filter ? `#f=${encodeURIComponent(filter)}` : location.pathname + location.search);
    paint();
  });
  if (button) {
    button.addEventListener("click", () => {
      lang = lang === "en" ? "zh" : "en";
      try { localStorage.setItem("gtd-lang", lang); } catch { /* ignore */ }
      paint();
    });
  }
  async function load() {
    try {
      const url = example ? "example-state.json" : "/api/state";
      const response = await fetch(url, { cache: "no-store", credentials: "same-origin" });
      if (!example && (response.status === 401 || response.status === 403 || response.redirected)) {
        location.reload();
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);
      last = await response.json();
      paint();
      const err = document.getElementById("err");
      if (err) err.style.display = "none";
    } catch (error) {
      const err = document.getElementById("err");
      if (err) {
        const strings = STRINGS[lang] || STRINGS.zh;
        err.textContent = strings.refreshFail(error.message);
        err.style.display = "block";
      }
    }
  }
  const gen = document.getElementById("gen");
  if (gen && !last) gen.textContent = (STRINGS[lang] || STRINGS.zh).loading;
  load();
  // Snapshots change every few minutes; poll every 5 min and skip hidden tabs to save D1 reads.
  setInterval(() => {
    if (!document.hidden) load();
  }, 300000);
  setInterval(() => last && render(last, lang, { example, filter }), 20000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) load();
  });
}

boot();
