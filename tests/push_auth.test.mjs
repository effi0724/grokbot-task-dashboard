import assert from "node:assert/strict";
import test from "node:test";

import { resolveAccessConfig, verifyAccess } from "../site/lib/auth.js";
import { onRequest, onRequestPost } from "../site/functions/api/push.js";
import { authorizeBearer, sha256hex, tokensEqual, validateSnapshot } from "../site/lib/push_auth.js";

const EXAMPLE_TOKEN = "example-push-token";
const EXAMPLE_HASH = "7810dfb0f36973fa8e0262804c4e5ec4b41fc78fd1c7b34e88c3f075df784ffc";

test("sha256 of the example token matches the documented digest", async () => {
  assert.equal(await sha256hex(EXAMPLE_TOKEN), EXAMPLE_HASH);
  assert.equal(await sha256hex("hello"), "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
});

test("digest compare is case-insensitive and fails closed on length mismatch", async () => {
  const actual = await sha256hex(EXAMPLE_TOKEN);
  assert.equal(tokensEqual(actual, EXAMPLE_HASH.toUpperCase()), true);
  assert.equal(tokensEqual(actual, EXAMPLE_HASH.slice(0, -1)), false);
  assert.equal(tokensEqual("", EXAMPLE_HASH), false);
  assert.equal(await authorizeBearer("Bearer " + EXAMPLE_TOKEN, "  " + EXAMPLE_HASH.toUpperCase()), null);
  assert.equal(await authorizeBearer("Bearer wrong-token", EXAMPLE_HASH), "unauthorized");
  assert.equal(await authorizeBearer("", EXAMPLE_HASH), "unauthorized");
  assert.equal(await authorizeBearer("Bearer " + EXAMPLE_TOKEN, ""), "unauthorized");
});

test("snapshot validation rejects non-objects and oversized bodies", () => {
  assert.equal(validateSnapshot('{"bots":[]}').value.bots.length, 0);
  assert.equal(validateSnapshot("[]").error, "bad json");
  assert.equal(validateSnapshot('{"nope":1}').error, "bad json");
  assert.equal(validateSnapshot("{").error, "bad json");
  assert.equal(validateSnapshot("x".repeat(1_000_001)).status, 413);
});

function fakeDb() {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      const statement = {
        args: [],
        bind(...args) {
          this.args = args;
          return this;
        },
        async run() {
          calls.push({ sql, args: this.args });
          return { success: true };
        },
      };
      return statement;
    },
  };
}

test("push stores a snapshot only after the bearer hash matches", async () => {
  const db = fakeDb();
  const env = { TOKEN_SHA256: EXAMPLE_HASH, DB: db };
  const ok = await onRequestPost({
    request: new Request("https://example.com/api/push", {
      method: "POST",
      headers: { authorization: "Bearer " + EXAMPLE_TOKEN },
      body: JSON.stringify({ bots: [{ bot: "Coder" }], generated_at: "" }),
    }),
    env,
  });
  assert.equal(ok.status, 200);
  assert.deepEqual(await ok.json(), { ok: true });
  assert.equal(db.calls.length, 2);
  assert.match(db.calls[0].sql, /CREATE TABLE IF NOT EXISTS kv/);
  assert.match(db.calls[1].sql, /INSERT INTO kv/);
  const stored = JSON.parse(db.calls[1].args[0]);
  assert.equal(stored.bots[0].bot, "Coder");
  assert.equal(typeof db.calls[1].args[1], "number");

  const denied = await onRequestPost({
    request: new Request("https://example.com/api/push", {
      method: "POST",
      headers: { authorization: "Bearer nope" },
      body: JSON.stringify({ bots: [] }),
    }),
    env,
  });
  assert.equal(denied.status, 401);

  const missingDb = await onRequestPost({
    request: new Request("https://example.com/api/push", {
      method: "POST",
      headers: { authorization: "Bearer " + EXAMPLE_TOKEN },
      body: JSON.stringify({ bots: [] }),
    }),
    env: { TOKEN_SHA256: EXAMPLE_HASH },
  });
  assert.equal(missingDb.status, 500);

  const wrongMethod = await onRequest({
    request: new Request("https://example.com/api/push", { method: "GET" }),
    env,
  });
  assert.equal(wrongMethod.status, 405);
});

test("access config comes from env and placeholders stay unconfigured", async () => {
  assert.equal(resolveAccessConfig({}).error, "access not configured");
  assert.equal(resolveAccessConfig({
    ACCESS_TEAM_DOMAIN: "YOUR_TEAM.cloudflareaccess.com",
    ACCESS_AUD: "aud",
    ACCESS_ALLOWED_EMAILS: "you@example.com",
  }).error, "access not configured");
  assert.equal(resolveAccessConfig({
    ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
    ACCESS_AUD: "YOUR_ACCESS_APPLICATION_AUD",
    ACCESS_ALLOWED_EMAILS: "you@example.com",
  }).error, "access not configured");
  const config = resolveAccessConfig({
    ACCESS_TEAM_DOMAIN: "https://example.cloudflareaccess.com/",
    ACCESS_AUD: "aud-one, aud-two",
    ACCESS_ALLOWED_EMAILS: "You@Example.com",
  });
  assert.equal(config.teamUrl, "https://example.cloudflareaccess.com");
  assert.deepEqual(config.auds, ["aud-one", "aud-two"]);
  assert.deepEqual(config.emails, ["you@example.com"]);
  assert.equal(
    await verifyAccess(new Request("https://example.com/"), {
      ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
      ACCESS_AUD: "aud",
      ACCESS_ALLOWED_EMAILS: "you@example.com",
    }),
    "missing Access token",
  );
  assert.equal(await verifyAccess(new Request("https://example.com/"), {}), "access not configured");
});
