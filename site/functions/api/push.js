// `st` posts a full snapshot. The raw bearer token is never stored here.
import { authorizeBearer, validateSnapshot } from "../../lib/push_auth.js";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

export const json = (payload, status = 200) =>
  new Response(JSON.stringify(payload), { status, headers: JSON_HEADERS });

export async function onRequestPost({ request, env }) {
  const denied = await authorizeBearer(request.headers.get("authorization"), env && env.TOKEN_SHA256);
  if (denied) return json({ error: denied }, 401);
  const verdict = validateSnapshot(await request.text());
  if (verdict.error) return json({ error: verdict.error }, verdict.status);
  if (!env || !env.DB) return json({ error: "database not configured" }, 500);
  await env.DB.prepare(
    "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, updated INTEGER NOT NULL)",
  ).run();
  await env.DB.prepare(
    "INSERT INTO kv (k, v, updated) VALUES ('state', ?1, ?2) ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated = excluded.updated",
  )
    .bind(JSON.stringify(verdict.value), Date.now())
    .run();
  return json({ ok: true });
}

export async function onRequest(ctx) {
  if (ctx.request.method === "POST") return onRequestPost(ctx);
  return json({ error: "method not allowed" }, 405);
}
