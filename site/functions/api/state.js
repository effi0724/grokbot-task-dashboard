const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

const EMPTY = {
  schema_version: 1,
  bots: [],
  claude: {},
  claude_tasks: [],
  generated_at: "",
  accuracy: null,
  _example: false,
};

// Cache the response for 60 s with the Cache API so many open tabs cost at most one D1 read per minute.
// Requests only reach this function after the auth middleware; the cache key is a fixed internal URL.
const CACHE_TTL = 60;

export async function onRequestGet({ request, env, waitUntil }) {
  const cache = typeof caches !== "undefined" ? caches.default : null;
  const cacheKey = new Request(new URL("/__cache/api-state-v1", request.url).toString());
  if (cache) {
    const hit = await cache.match(cacheKey);
    if (hit) return new Response(hit.body, { headers: { ...JSON_HEADERS, "x-state-cache": "HIT" } });
  }
  const body = await readState(env);
  if (cache && waitUntil) {
    waitUntil(cache.put(cacheKey, new Response(body, {
      headers: { "content-type": JSON_HEADERS["content-type"], "cache-control": `public, max-age=${CACHE_TTL}` },
    })));
  }
  return new Response(body, { headers: { ...JSON_HEADERS, "x-state-cache": "MISS" } });
}

async function readState(env) {
  let row = null;
  try {
    row = await env.DB.prepare("SELECT v, updated FROM kv WHERE k = 'state'").first();
  } catch {
    row = null;
  }
  return row && row.v ? row.v : JSON.stringify(EMPTY);
}

export async function onRequest(ctx) {
  if (ctx.request.method === "GET") return onRequestGet(ctx);
  return new Response(JSON.stringify({ error: "method not allowed" }), {
    status: 405,
    headers: JSON_HEADERS,
  });
}
