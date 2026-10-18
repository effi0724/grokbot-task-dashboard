/** Display helpers shared by the dashboard and the node:test suite. */

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

export function formatMinutes(value, lang) {
  const english = lang === "en";
  if (value == null || value === "" || Number.isNaN(Number(value))) {
    return english ? "unknown" : "待估";
  }
  const minutes = Number(value);
  if (minutes <= 0) return english ? "0 min" : "0 分钟";
  if (minutes < 60) {
    const shown = Math.round(minutes);
    return english ? `${shown} min` : `${shown} 分钟`;
  }
  const hours = minutes / 60;
  if (hours < 48) {
    const shown = (Math.round(hours * 10) / 10).toFixed(1);
    return english ? `${shown} h` : `${shown} 小时`;
  }
  const shown = (Math.round((hours / 24) * 10) / 10).toFixed(1);
  return english ? `${shown} d` : `${shown} 天`;
}

export function formatRatio(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(2)}×`;
}

export function formatPercent(rate) {
  if (rate == null || rate === "" || Number.isNaN(Number(rate))) return "—";
  return `${Math.round(Number(rate) * 100)}%`;
}

export function formatSpread(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(2);
}

export function ratioClass(value) {
  if (value == null || Number.isNaN(Number(value))) return "";
  if (Number(value) > 1.25) return "ratio-hot";
  if (Number(value) < 0.85) return "ratio-good";
  return "";
}

export function formatWhen(iso, lang, timeZone = "America/New_York") {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  if (lang === "en") {
    return new Intl.DateTimeFormat("en-US", {
      timeZone,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("month")}月${get("day")}日 ${get("hour")}:${get("minute")}`;
}

export function formatAgo(iso, lang, nowMs = Date.now()) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((nowMs - then) / 60000);
  const english = lang === "en";
  if (minutes < 1) return english ? "just now" : "刚刚";
  if (minutes < 60) return english ? `${minutes} min ago` : `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    if (english) return rest ? `${hours} h ${rest} min ago` : `${hours} h ago`;
    return rest ? `${hours} 小时${rest} 分前` : `${hours} 小时前`;
  }
  const days = Math.floor(hours / 24);
  return english ? `${days} d ago` : `${days} 天前`;
}

export function formatRemaining(iso, lang, nowMs = Date.now()) {
  if (!iso) return null;
  const minutes = Math.round((new Date(iso).getTime() - nowMs) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return null;
  const english = lang === "en";
  if (minutes < 60) return english ? `about ${minutes} min left` : `还剩约 ${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (english) return rest ? `about ${hours} h ${rest} min left` : `about ${hours} h left`;
  return rest ? `还剩约 ${hours} 小时${rest} 分` : `还剩约 ${hours} 小时`;
}

export function sampleRatio(task) {
  if (!task) return null;
  const estimate = Number(task.estimate_minutes);
  const actual = Number(task.actual_minutes);
  if (!Number.isFinite(estimate) || !Number.isFinite(actual) || estimate <= 0 || actual <= 0) return null;
  return actual / estimate;
}
