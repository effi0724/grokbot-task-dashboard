// Every request except the push endpoint needs a Cloudflare Access JWT.
// /api/push and /api/server-push authenticate themselves with bearer tokens.
import { verifyAccess } from "../lib/auth.js";

export async function onRequest(ctx) {
  const url = new URL(ctx.request.url);
  if (url.pathname === "/api/push" || url.pathname === "/api/server-push") return ctx.next();
  let why;
  try {
    why = await verifyAccess(ctx.request, ctx.env || {});
  } catch {
    why = "Access verification failed";
  }
  if (why) {
    return new Response("403 Forbidden: " + why, {
      status: 403,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
        "x-robots-tag": "noindex",
      },
    });
  }
  const upstream = await ctx.next();
  const response = new Response(upstream.body, upstream);
  response.headers.set("cache-control", "no-store");
  response.headers.set("x-robots-tag", "noindex");
  return response;
}
