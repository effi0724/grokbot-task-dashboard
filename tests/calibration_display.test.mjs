import assert from "node:assert/strict";
import test from "node:test";

import { basisLabel, calibrationLine } from "../site/public/js/calibration.js";
import {
  escapeHtml,
  formatAgo,
  formatMinutes,
  formatRatio,
  ratioClass,
  sampleRatio,
} from "../site/public/js/format.js";

test("formats durations, ratios, and escaped text", () => {
  assert.equal(formatMinutes(100, "zh"), "1.7 小时");
  assert.equal(formatMinutes(50, "zh"), "50 分钟");
  assert.equal(formatMinutes(200, "en"), "3.3 h");
  assert.equal(formatMinutes(null, "en"), "unknown");
  assert.equal(formatRatio(1.3), "1.30×");
  assert.equal(formatRatio(null), "—");
  assert.equal(ratioClass(1.4), "ratio-hot");
  assert.equal(ratioClass(0.5), "ratio-good");
  assert.equal(ratioClass(1), "");
  assert.equal(escapeHtml(`<b class="x">a&b</b>`), "&lt;b class=&quot;x&quot;&gt;a&amp;b&lt;/b&gt;");
  assert.equal(sampleRatio({ estimate_minutes: 100, actual_minutes: 150 }), 1.5);
  assert.equal(sampleRatio({ estimate_minutes: 100 }), null);
  assert.equal(sampleRatio({ state: "cancelled", estimate_minutes: 10, actual_minutes: 0 }), null);
});

test("calibration line for an empty history and a trusted bucket", () => {
  assert.equal(
    calibrationLine({
      raw_minutes: 100,
      minutes: 100,
      low_minutes: 50,
      high_minutes: 200,
      basis: "none",
      n: 0,
      low_confidence: true,
    }, "zh"),
    "样本不足，暂用原始预估 1.7 小时（参考区间 50 分钟–3.3 小时）。",
  );
  assert.equal(
    calibrationLine({
      raw_minutes: 120,
      minutes: 150,
      low_minutes: 120,
      high_minutes: 180,
      basis: "bot+type",
      n: 8,
      median_ratio: 1.3,
      overrun_rate: 0.625,
      low_confidence: false,
    }, "zh"),
    "校准约 2.5 小时（2.0 小时–3.0 小时）· 依据该机器人 + 任务类型 · 8 个样本 · 中位 1.30× · 超期 63%",
  );
  const low = calibrationLine({
    raw_minutes: 60,
    minutes: 70,
    low_minutes: 40,
    high_minutes: 120,
    basis: "bot",
    n: 2,
    median_ratio: 1.4,
    overrun_rate: 0.5,
    low_confidence: true,
  }, "en");
  assert.match(low, /low confidence/);
  assert.equal(basisLabel("type", "en"), "task type");
  assert.match(calibrationLine(null, "zh"), /^$/);
  assert.match(calibrationLine({ raw_minutes: null }, "en"), /No original estimate/);
});

test("relative time uses the injected clock", () => {
  const now = Date.parse("2026-10-18T13:00:00Z");
  const five = new Date(now - 5 * 60000).toISOString();
  assert.equal(formatAgo(five, "zh", now), "5 分钟前");
  assert.equal(formatAgo(five, "en", now), "5 min ago");
  assert.equal(formatAgo(null, "zh", now), "");
});
