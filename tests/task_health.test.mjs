import assert from "node:assert/strict";
import test from "node:test";

import { formatSpan, taskHealth } from "../site/public/js/format.js";

const NOW = Date.parse("2026-01-15T14:00:00-05:00");
const ago = (minutes) => new Date(NOW - minutes * 60000).toISOString();

test("only running tasks are checked", () => {
  assert.equal(taskHealth({ state: "waiting", updated: ago(500) }, NOW), null);
});

test("no watcher: stale after 60 minutes, lost after 3 hours", () => {
  assert.equal(taskHealth({ state: "running", updated: ago(59) }, NOW), null);
  assert.deepEqual(taskHealth({ state: "running", updated: ago(61) }, NOW), { kind: "stale", reason: "update", minutes: 61 });
  assert.equal(taskHealth({ state: "running", updated: ago(181) }, NOW).kind, "lost");
});

test("a watcher heartbeat counts as a signal with a 30 minute limit", () => {
  assert.equal(taskHealth({ state: "running", updated: ago(120), heartbeat: ago(5), watcher: { alive: true } }, NOW), null);
  assert.equal(taskHealth({ state: "running", updated: ago(120), heartbeat: ago(31), watcher: { alive: true } }, NOW).reason, "heartbeat");
});

test("a watcher that reported itself lost is lost", () => {
  const out = taskHealth({ state: "running", updated: ago(1), heartbeat: ago(1), watcher: { alive: false, note: "gave up" } }, NOW);
  assert.equal(out.kind, "lost");
  assert.equal(out.note, "gave up");
});

test("passing the ETA without an update is stale", () => {
  assert.equal(taskHealth({ state: "running", updated: ago(40), eta: ago(20) }, NOW).reason, "eta");
  assert.equal(taskHealth({ state: "running", updated: ago(5), eta: ago(20) }, NOW), null);
  assert.equal(taskHealth({ state: "running", updated: ago(40), eta: ago(10) }, NOW), null);
});

test("spans read in both languages", () => {
  assert.equal(formatSpan(45, "en"), "45 min");
  assert.equal(formatSpan(125, "zh"), "2 小时 5 分");
});
