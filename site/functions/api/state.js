const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

const EMPTY = {
  schema_version: 1,
  bots: [],
  claude: {},
  claude_tasks: [],
  tokens: {},
  generated_at: "",
  accuracy: null,
  _example: false,
};

export async function onRequestGet({ env }) {
  let row = null;
  try {
    row = await env.DB.prepare("SELECT v, updated FROM kv WHERE k = 'state'").first();
  } catch {
    row = null;
  }
  return new Response(row && row.v ? row.v : JSON.stringify(EMPTY), { headers: JSON_HEADERS });
}

export async function onRequest(ctx) {
  if (ctx.request.method === "GET") return onRequestGet(ctx);
  return new Response(JSON.stringify({ error: "method not allowed" }), {
    status: 405,
    headers: JSON_HEADERS,
  });
}
