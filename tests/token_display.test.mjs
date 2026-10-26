import assert from "node:assert/strict";
import test from "node:test";

import { formatTokens, tokenSummary } from "../site/public/js/format.js";

test("token counts compact", () => {
  assert.equal(formatTokens(0), "0");
  assert.equal(formatTokens(999), "999");
  assert.equal(formatTokens(1234), "1.2K");
  assert.equal(formatTokens(3456789), "3.5M");
  assert.equal(formatTokens(2e9), "2.00B");
  assert.equal(formatTokens("junk"), "0");
});

test("token summary sums in+out and keeps the newest weeks", () => {
  const weeks = Array.from({ length: 8 }, (_, i) => ({ w: `2026-W${String(30 + i).padStart(2, "0")}`, in: 1, out: 2, cr: 3, cw: 4 }));
  const sum = tokenSummary({ total: { in: 10, out: 5, cr: 7, cw: 1 }, weeks, since: "2026-07-20T00:00:00-04:00", updated: "x" });
  assert.deepEqual(sum.total, { io: 15, cr: 7, cw: 1 });
  assert.equal(sum.weeks.length, 6);
  assert.equal(sum.weeks[0].week, "2026-W37");
  assert.equal(sum.weeks[0].io, 3);
});

test("missing token data yields null", () => {
  assert.equal(tokenSummary(undefined), null);
  assert.equal(tokenSummary({ weeks: [] }), null);
});
