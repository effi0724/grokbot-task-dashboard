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
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
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
  const stale = state === "running" && task.updated && (nowMs - new Date(task.updated).getTime()) > 2 * 3600e3;
  const kind = task.task_type ? `<span class="via">${escapeHtml(task.task_type)}</span>` : "";
  const via = task.via ? `<span class="via">⇢ ${escapeHtml(task.via)}</span>` : "";
  const cal = calibrationLine(task.calibration, lang);
  return `<div class="task">
    <div class="tt"><div class="title">${escapeHtml(task.title)}${kind}${via}</div>${badge(state, strings)}</div>
    ${task.stage ? `<div class="stage">${escapeHtml(task.stage)}</div>` : ""}
    ${showBar ? `<div class="bar"><i style="width:${Math.max(2, Math.min(100, task.pct || 0))}%;background:${color}"></i></div>` : ""}
    <div class="meta">
      ${showBar ? `<span>${task.pct || 0}%</span>` : ""}
      ${eta ? `<span>${eta}</span>` : ""}
      ${task.resume ? `<span>${strings.resume}${lang === "en" ? ": " : "："}${formatWhen(task.resume, lang, timeZone)}</span>` : ""}
      <span class="${stale ? "stale" : ""}">${strings.updatedAt} ${formatAgo(task.updated, lang, nowMs)}${stale ? ` · ${strings.stale}` : ""}</span>
    </div>
    ${cal ? `<div class="cal">${escapeHtml(cal)}</div>` : ""}
    ${task.note ? `<div class="note">${escapeHtml(task.note)}</div>` : ""}
  </div>`;
}

function statRows(rows, labelFor) {
  return (rows || []).map((row) => {
    const hot = ratioClass(row.median_ratio);
    return `<tr>
      <td>${escapeHtml(labelFor(row))}</td>
      <td>${row.n}</td>
      <td class="${hot}">${formatRatio(row.median_ratio)}</td>
      <td>${formatRatio(row.p25_ratio)}</td>
      <td>${formatRatio(row.p75_ratio)}</td>
      <td>${formatSpread(row.spread)}</td>
      <td>${formatPercent(row.overrun_rate)}</td>
      <td>${row.median_revisions ?? "—"}</td>
    </tr>`;
  }).join("");
}

function statTable(title, rows, labelFor, strings) {
  if (!rows || !rows.length) return "";
  const head = ["colScope", "colN", "colMedian", "colP25", "colP75", "colSpread", "colOverrun", "colRevisions"]
    .map((key) => `<th>${strings[key]}</th>`).join("");
  return `<div class="card"><h4>${escapeHtml(title)}</h4>
    <table><thead><tr>${head}</tr></thead><tbody>${statRows(rows, labelFor)}</tbody></table></div>`;
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

function claudeBlock(state, strings, lang, timeZone, nowMs) {
  const info = state.claude || {};
  const label = strings.claudeStates[info.state] || strings.claudeUnset;
  const badgeClass = info.state === "quota" ? "s-quota" : info.state === "running" ? "s-running" : "s-done";
  const cardClass = info.state === "quota" ? "alert" : "";
  let reset = "";
  if (info.reset) {
    const left = formatRemaining(info.reset, lang, nowMs);
    reset = `${formatWhen(info.reset, lang, timeZone)} ${wrap(lang, left || strings.passed)}`;
  }
  const kv = [
    info.model ? [strings.model, info.model] : null,
    reset ? [strings.reset, reset] : null,
    info.resume ? [strings.resumeRun, formatWhen(info.resume, lang, timeZone)] : null,
    info.plan ? [strings.plan, info.plan] : null,
    [strings.updatedLabel, formatAgo(info.updated, lang, nowMs) || "—"],
  ].filter(Boolean);
  const handed = [];
  (state.bots || []).forEach((bot) => {
    (bot.tasks || []).forEach((task) => {
      if (/claude/i.test(task.via || "")) handed.push([bot.bot, task]);
    });
  });
  (state.claude_tasks || []).forEach((task) => handed.push(["Claude Code", task]));
  const handedHtml = handed.length
    ? handed.map(([bot, task]) => `<div class="task"><div class="tt"><div class="title">${escapeHtml(task.title)}<span class="via">${escapeHtml(bot)}</span></div>${badge(task.state, strings)}</div>
        <div class="meta">${task.eta ? `<span>${strings.eta} ${formatWhen(task.eta, lang, timeZone)}</span>` : ""}${task.resume ? `<span>${strings.start}${lang === "en" ? ": " : "："}${formatWhen(task.resume, lang, timeZone)}</span>` : ""}</div></div>`).join("")
    : `<div class="empty">${strings.claudeEmpty}</div>`;
  return `<div class="card ${cardClass}"><div class="ch"><h2>${strings.quotaTitle}</h2><span class="badge ${badgeClass}">${escapeHtml(label)}</span></div>
      <div class="kv">${kv.map(([key, value]) => `<span>${escapeHtml(key)}</span><span>${escapeHtml(value)}</span>`).join("")}</div>
      ${info.note ? `<div class="note">${escapeHtml(info.note)}</div>` : ""}</div>
    <div class="card"><div class="ch"><h2>${strings.claudeTasks}</h2></div>${handedHtml}</div>`;
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
  return `<table><thead><tr>
      <th>${strings.colFinished}</th><th>${strings.colBot}</th><th>${strings.colTask}</th>
      <th>${strings.colType}</th><th>${strings.colDuration}</th><th>${strings.colRatio}</th>
    </tr></thead><tbody>${body}</tbody></table>`;
}

export function render(state, lang, options = {}) {
  const strings = STRINGS[lang] || STRINGS.zh;
  const nowMs = options.nowMs || Date.now();
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
    bots.innerHTML = (state.bots || []).map((bot) => {
      const tasks = bot.tasks || [];
      tasks.forEach((task) => { counts[task.state] = (counts[task.state] || 0) + 1; });
      const active = tasks.filter((task) => task.state !== "routine");
      if (!tasks.length) idle += 1;
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
    }).join("");
  }
  const sum = document.getElementById("sum");
  if (sum) {
    sum.innerHTML = ORDER.filter((key) => counts[key]).map((key) =>
      `<span class="chip" style="border-color:${COLOR[key]}">${strings.states[key]} <b>${counts[key]}</b></span>`,
    ).join("") + `<span class="chip">${strings.idleBots} <b>${idle}</b></span>`;
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
  const button = document.getElementById("lang");
  const paint = () => {
    if (button) button.textContent = lang === "en" ? "中文" : "EN";
    if (last) render(last, lang, { example });
  };
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
  setInterval(load, 60000);
  setInterval(() => last && render(last, lang, { example }), 20000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) load();
  });
}

boot();
