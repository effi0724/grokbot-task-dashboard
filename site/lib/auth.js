// Cloudflare Access JWT verification (RS256, WebCrypto, no dependencies).
// Pages Functions must pass `env`. Team domain, audience, and allowlist are not hardcoded.

const CERT_TTL_MS = 3600e3;
const certCache = new Map();

const b64u = (segment) => {
  let text = segment.replace(/-/g, "+").replace(/_/g, "/");
  while (text.length % 4) text += "=";
  const binary = atob(text);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
};

const decodeJson = (segment) => JSON.parse(new TextDecoder().decode(b64u(segment)));

export function resolveAccessConfig(env) {
  const source = env || {};
  let domain = String(source.ACCESS_TEAM_DOMAIN || "").trim().replace(/\/+$/, "");
  if (!domain || domain.startsWith("http://") || /your_team/i.test(domain)) {
    return { error: "access not configured" };
  }
  if (!domain.startsWith("https://")) domain = `https://${domain}`;
  let host = "";
  try {
    host = new URL(domain).host;
  } catch {
    return { error: "access not configured" };
  }
  if (!host || host.includes("YOUR_TEAM")) return { error: "access not configured" };
  const teamUrl = `https://${host}`;
  const auds = String(source.ACCESS_AUD || "")
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item && item !== "YOUR_ACCESS_APPLICATION_AUD");
  if (!auds.length) return { error: "access not configured" };
  const emails = String(source.ACCESS_ALLOWED_EMAILS || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  if (!emails.length) return { error: "email allowlist not configured" };
  return { teamUrl, auds, emails };
}

async function signingKeys(teamUrl, force) {
  const cached = certCache.get(teamUrl);
  if (!force && cached && cached.keys.length && Date.now() - cached.at < CERT_TTL_MS) return cached.keys;
  const response = await fetch(`${teamUrl}/cdn-cgi/access/certs`);
  if (!response.ok) throw new Error("certs " + response.status);
  const keys = (await response.json()).keys || [];
  certCache.set(teamUrl, { at: Date.now(), keys });
  return keys;
}

export async function verifyAccess(request, env) {
  const config = resolveAccessConfig(env);
  if (config.error) return config.error;
  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) return "missing Access token";
  const parts = token.split(".");
  if (parts.length !== 3) return "bad token format";
  let header;
  let payload;
  try {
    header = decodeJson(parts[0]);
    payload = decodeJson(parts[1]);
  } catch {
    return "unparseable token";
  }
  if (header.alg !== "RS256") return "unsupported alg";
  let keys;
  try {
    keys = await signingKeys(config.teamUrl, false);
  } catch {
    return "could not load Access certs";
  }
  let jwk = keys.find((key) => key.kid === header.kid);
  if (!jwk) {
    try {
      keys = await signingKeys(config.teamUrl, true);
    } catch {
      return "could not load Access certs";
    }
    jwk = keys.find((key) => key.kid === header.kid);
  }
  if (!jwk) return "unknown signing key";
  let cryptoKey;
  try {
    cryptoKey = await crypto.subtle.importKey(
      "jwk",
      { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
  } catch {
    return "bad signing key";
  }
  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", cryptoKey, b64u(parts[2]), signed);
  if (!valid) return "bad signature";
  const nowSec = Date.now() / 1000;
  if (typeof payload.exp !== "number" || payload.exp < nowSec - 30) return "token expired";
  if (payload.iss !== config.teamUrl) return "issuer mismatch";
  const audience = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!audience.some((item) => config.auds.includes(item))) return "audience mismatch";
  if (!config.emails.includes(String(payload.email || "").toLowerCase())) return "email not allowlisted";
  return null;
}

export function resetCertCache() {
  certCache.clear();
}
