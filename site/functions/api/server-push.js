// Servers (server-1 / server-2 / box ...)每 5 分钟上报资源快照。每台机器一个只写令牌，这里只存 SHA-256（SERVER_TOKEN_SHA256 / SERVER_TOKENS_JSON）
// 省 D1 读量：最新快照 + 24 小时曲线同时写进 kv 行 'srv:<host>'，/api/state 只读 kv；建表/建索引只在首次失败时补建；过期清理约每小时一次
const J = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
async function sha256hex(s) { const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)); return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join(""); }
const num = (v) => (typeof v === "number" && isFinite(v) ? v : null);
const r1 = (v) => (v == null ? null : Math.round(v * 10) / 10);
const MIGRATIONS = [
  "CREATE TABLE IF NOT EXISTS server_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT NOT NULL, received INTEGER NOT NULL, cpu REAL, gpu REAL, vram REAL, ram REAL, data TEXT NOT NULL)",
  "CREATE INDEX IF NOT EXISTS server_metrics_recv ON server_metrics (received)",
  "CREATE INDEX IF NOT EXISTS server_metrics_host_recv ON server_metrics (host, received)",
  "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, updated INTEGER NOT NULL)",
];
async function migrate(env) { for (const q of MIGRATIONS) await env.DB.prepare(q).run(); }
export async function onRequestPost({ request, env }) {
  const auth = request.headers.get("authorization") || "";
  if (!auth.startsWith("Bearer ")) return J({ error: "unauthorized" }, 401);
  const h = await sha256hex(auth.slice(7).trim());
  const map = {}; if (env.SERVER_TOKEN_SHA256) map[env.SERVER_TOKEN_SHA256] = "server-1";
  try { Object.assign(map, JSON.parse(env.SERVER_TOKENS_JSON || "{}")); } catch {}
  let tokenHost = null;
  for (const [want, hn] of Object.entries(map)) { let diff = h.length ^ want.length; for (let i = 0; i < h.length; i++) diff |= h.charCodeAt(i) ^ (want.charCodeAt(i) || 0); if (!diff) tokenHost = hn; }
  if (!tokenHost) return J({ error: "unauthorized" }, 401);
  const body = await request.text(); if (body.length > 200_000) return J({ error: "too large" }, 413);
  let o; try { o = JSON.parse(body); if (!o || typeof o !== "object" || !o.cpu) throw 0; } catch { return J({ error: "bad json" }, 400); }
  const host = tokenHost, now = Date.now();
  const gpus = Array.isArray(o.gpus) ? o.gpus : [];
  const gpu = gpus.length ? Math.max(...gpus.map((g) => num(g.util) ?? 0)) : null;
  const vram = gpus.length ? Math.max(...gpus.map((g) => (num(g.mem_total) ? (100 * (num(g.mem_used) ?? 0)) / g.mem_total : 0))) : null;
  const ram = o.mem && num(o.mem.total) ? (100 * (num(o.mem.used) ?? 0)) / o.mem.total : null;
  const cpu = num(o.cpu.pct), key = "srv:" + host;
  const run = async () => {
    // 读上一条 kv 快照（1 行）拿曲线；没有就从带 (host, received) 索引的明细表回填一次
    const prev = await env.DB.prepare("SELECT v, updated FROM kv WHERE k = ?1").bind(key).first();
    let hist = null; try { hist = prev ? JSON.parse(prev.v).history : null; } catch {}
    if (!Array.isArray(hist)) {
      const { results } = await env.DB.prepare("SELECT received, cpu, gpu, vram, ram FROM server_metrics WHERE host = ?1 AND received >= ?2 ORDER BY received").bind(host, now - 86400e3).all();
      hist = (results || []).map((x) => [x.received, r1(x.cpu), r1(x.gpu), r1(x.vram), r1(x.ram)]);
    }
    hist = hist.filter((x) => x[0] >= now - 86400e3); hist.push([now, r1(cpu), r1(gpu), r1(vram), r1(ram)]);
    const stmts = [
      env.DB.prepare("INSERT INTO server_metrics (host, received, cpu, gpu, vram, ram, data) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)").bind(host, now, cpu, gpu, vram, ram, body),
      env.DB.prepare("INSERT INTO kv (k, v, updated) VALUES (?1, ?2, ?3) ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated = excluded.updated")
        .bind(key, JSON.stringify({ host, received: now, data: body, history: hist }), now),
    ];
    // 约每小时清理一次 7 天前的明细（本机进入新的小时才执行）
    if (!prev || Math.floor(prev.updated / 3600e3) !== Math.floor(now / 3600e3)) stmts.push(env.DB.prepare("DELETE FROM server_metrics WHERE received < ?1").bind(now - 7 * 86400e3));
    await env.DB.batch(stmts);
  };
  try { await run(); } catch (e) {
    if (!/no such table/i.test(String(e && e.message))) throw e;
    await migrate(env); await run(); // 一次性迁移：仅在表不存在时执行
  }
  return J({ ok: true });
}
export const onRequest = () => J({ error: "method not allowed" }, 405);
