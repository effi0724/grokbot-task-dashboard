import assert from "node:assert/strict";
import test from "node:test";

import { applyQuotaToTasks, normalizeQuota, quotaRunners, usageIsStale } from "../site/public/js/format.js";

const NOW = Date.parse("2026-01-15T14:00:00-05:00");
const at = (minutes) => new Date(NOW + minutes * 60000).toISOString();

test("passed resets refill bars and clear quota", () => {
  const info = normalizeQuota({ state: "quota", session_left: 0, reset: at(-5), week_left: 40, weekly_reset: at(-1) }, true, NOW);
  assert.equal(info.session_left, 100);
  assert.equal(info.week_left, 100);
  assert.equal(info.state, "ok");
});

test("an empty bar before its reset means quota", () => {
  const info = normalizeQuota({ state: "ok", week_left: 0, weekly_reset: at(600) }, false, NOW);
  assert.equal(info.state, "quota");
  assert.equal(info.until, at(600));
});

test("manual quota without a reading empties the session bar", () => {
  const info = normalizeQuota({ state: "quota", session_left: 80, reset: at(60) }, true, NOW);
  assert.equal(info.session_left, 0);
  assert.equal(info.session_forced, true);
});

test("tasks follow their runner", () => {
  const state = {
    claude: { state: "quota", reset: at(60), resume: at(90) },
    quotas: { Gemini: { state: "ok" } },
    bots: [{ bot: "Coder", tasks: [
      { id: "a", state: "running", via: "Claude Code" },
      { id: "b", state: "quota", via: "gemini cli" },
      { id: "c", state: "running", via: "human" },
    ] }],
  };
  const out = applyQuotaToTasks(state, NOW);
  const [a, b, c] = out.bots[0].tasks;
  assert.equal(a.state, "quota");
  assert.equal(a.resume, at(90));
  assert.equal(b.state, "queued");
  assert.equal(c.state, "running");
  assert.equal(state.bots[0].tasks[0].state, "running", "input is not mutated");
  assert.deepEqual(quotaRunners(state, NOW).map((r) => r.name), ["Claude Code", "Gemini"]);
});

test("runner names are matched literally", () => {
  const out = applyQuotaToTasks({ quotas: { "a.b": { state: "quota", week_left: 0 } }, bots: [{ bot: "X", tasks: [{ state: "running", via: "axb" }] }] }, NOW);
  assert.equal(out.bots[0].tasks[0].state, "running");
});

test("usage readings older than three hours are stale", () => {
  assert.equal(usageIsStale(at(-200), NOW), true);
  assert.equal(usageIsStale(at(-60), NOW), false);
  assert.equal(usageIsStale("", NOW), false);
});
