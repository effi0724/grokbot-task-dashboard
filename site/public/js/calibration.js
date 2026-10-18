import { formatMinutes, formatPercent, formatRatio } from "./format.js";

const BASIS = {
  zh: {
    "bot+type": "该机器人 + 任务类型",
    type: "任务类型",
    bot: "该机器人",
    global: "全部历史",
    none: "样本不足",
  },
  en: {
    "bot+type": "bot + task type",
    type: "task type",
    bot: "this bot",
    global: "all history",
    none: "not enough history",
  },
};

export function basisLabel(basis, lang) {
  const table = lang === "en" ? BASIS.en : BASIS.zh;
  return table[basis] || basis || table.none;
}

/** One line for an active task's calibrated range. */
export function calibrationLine(cal, lang) {
  const english = lang === "en";
  if (!cal) return "";
  const raw = cal.raw_minutes;
  if (raw == null || Number(raw) <= 0) {
    return english
      ? "No original estimate, so there is no calibrated range."
      : "没有原始预估，无法给出校准区间。";
  }
  const range = `${formatMinutes(cal.low_minutes, lang)}–${formatMinutes(cal.high_minutes, lang)}`;
  if (cal.basis === "none" || !cal.n) {
    return english
      ? `Not enough history. Original ${formatMinutes(raw, lang)}; reference range ${range}.`
      : `样本不足，暂用原始预估 ${formatMinutes(raw, lang)}（参考区间 ${range}）。`;
  }
  const basis = basisLabel(cal.basis, lang);
  const confidence = cal.low_confidence
    ? (english ? " · low confidence" : " · 样本偏少，仅供参考")
    : "";
  const median = formatRatio(cal.median_ratio);
  const shrunk = cal.low_confidence
    && cal.applied_ratio != null
    && cal.median_ratio != null
    && Math.abs(Number(cal.applied_ratio) - Number(cal.median_ratio)) > 0.001;
  const ratioText = shrunk
    ? (english ? `median ${median}, shrunk to ${formatRatio(cal.applied_ratio)}` : `中位 ${median}，收缩后 ${formatRatio(cal.applied_ratio)}`)
    : (english ? `median ${median}` : `中位 ${median}`);
  if (english) {
    return `Calibrated ~${formatMinutes(cal.minutes, lang)} (${range}) · ${basis} · n=${cal.n} · ${ratioText} · overrun ${formatPercent(cal.overrun_rate)}${confidence}`;
  }
  return `校准约 ${formatMinutes(cal.minutes, lang)}（${range}）· 依据${basis} · ${cal.n} 个样本 · ${ratioText} · 超期 ${formatPercent(cal.overrun_rate)}${confidence}`;
}
