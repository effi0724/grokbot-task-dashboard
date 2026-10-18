// Bearer-token checks for POST /api/push.
// The raw token stays on the machine that runs `st`. The Pages project stores
// only TOKEN_SHA256 (hex, any letter case, surrounding whitespace ignored).

export async function sha256hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Constant-time compare of two hex digests. Length mismatches fail closed. */
export function tokensEqual(actual, expected) {
  const left = String(actual || "");
  const right = String(expected || "").trim().toLowerCase();
  const length = Math.max(left.length, right.length);
  let diff = left.length ^ right.length;
  for (let i = 0; i < length; i++) {
    diff |= (left.charCodeAt(i) || 0) ^ (right.charCodeAt(i) || 0);
  }
  return diff === 0;
}

export async function authorizeBearer(authHeader, expectedSha) {
  if (!expectedSha || !String(expectedSha).trim()) return "unauthorized";
  const header = authHeader || "";
  if (!header.startsWith("Bearer ")) return "unauthorized";
  const token = header.slice("Bearer ".length).trim();
  if (!token) return "unauthorized";
  const actual = await sha256hex(token);
  if (!tokensEqual(actual, expectedSha)) return "unauthorized";
  return null;
}

export function validateSnapshot(bodyText) {
  if (typeof bodyText !== "string") return { error: "bad json", status: 400 };
  if (bodyText.length > 1_000_000) return { error: "too large", status: 413 };
  let parsed;
  try {
    parsed = JSON.parse(bodyText);
  } catch {
    return { error: "bad json", status: 400 };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || !Array.isArray(parsed.bots)) {
    return { error: "bad json", status: 400 };
  }
  return { value: parsed };
}
