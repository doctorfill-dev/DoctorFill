/**
 * Cloudflare Pages Function: same-origin relay from /api/* to the DoctorFill API.
 *
 * Why: the API key used to be baked into the frontend bundle (VITE_API_KEY), so
 * anyone able to load the bundle could call the API directly. The key now lives
 * only in the Pages secret DOCTORFILL_API_KEY and is added here, server side.
 * The browser calls /api/<route> on its own origin, which sits behind
 * Cloudflare Access (doctorfill.ch and www.doctorfill.ch).
 *
 * Constraints this code keeps on purpose:
 * - Fixed upstream: the target origin is a constant, the client only chooses
 *   the path and query string under it. This is not an open relay.
 * - Only the production hostnames (protected by Access) are served; any other
 *   host that reaches this function (deployment URLs, pages.dev) gets a 404.
 * - Bodies are streamed both ways, never buffered: uploads (multipart PDFs),
 *   the downloaded PDF and the chat event stream pass through as streams.
 * - The Cloudflare Access assertion (Cf-Access-Jwt-Assertion) is verified here:
 *   RS256 signature against the team's public keys, audience, issuer and
 *   expiry. Without a valid assertion the key is never added: a misconfigured
 *   Access rule no longer opens the API (issue 36, audit S2). Transitional:
 *   this relay goes away when the frontend and the API share one origin.
 * - Request headers are forwarded from an allowlist. Client-supplied X-API-Key,
 *   cookies (including the Access session cookie), Authorization and Access
 *   assertion headers never reach the upstream.
 * - Nothing is logged: no body, file name, path or query string (patient data
 *   in bodies, see platform#51; job tokens travel in the X-Job-Token header).
 * - Errors never echo the key or upstream details.
 */

interface Env {
  /** Pages secret: the API key the orchestrator expects in X-API-Key. */
  DOCTORFILL_API_KEY?: string;
  /** Access team domain, `https://<team>.cloudflareaccess.com`: issuer and key source. */
  CF_ACCESS_TEAM_DOMAIN?: string;
  /** Application Audience (AUD) tag of the Access application. */
  CF_ACCESS_AUD?: string;
}

const UPSTREAM_ORIGIN = "https://api.doctorfill.ch";
const ROUTE_PREFIX = "/api/";
const ALLOWED_HOSTS = new Set(["doctorfill.ch", "www.doctorfill.ch"]);
// The orchestrator only accepts GET and POST (see its CORS settings).
const ALLOWED_METHODS = new Set(["GET", "HEAD", "POST"]);
const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "content-length",
  // Job token: a header, never the query string, which ends up in access logs.
  "x-job-token",
];
const DROPPED_RESPONSE_HEADERS = ["set-cookie"];

const ACCESS_ASSERTION_HEADER = "cf-access-jwt-assertion";
const ACCESS_KEYS_TTL_MS = 10 * 60 * 1000;
const CLOCK_SKEW_SECONDS = 60;

interface AccessJwk {
  kid?: string;
  kty?: string;
  n?: string;
  e?: string;
}

/** The team's public keys, cached per isolate; refetched on an unknown key id (rotation). */
let accessKeysCache: { url: string; fetchedAt: number; keys: AccessJwk[] } | null = null;

class AccessKeysUnavailable extends Error {}

async function accessKeys(teamDomain: string, refresh: boolean): Promise<AccessJwk[]> {
  const url = `${teamDomain}/cdn-cgi/access/certs`;
  const cached = accessKeysCache;
  if (!refresh && cached && cached.url === url && Date.now() - cached.fetchedAt < ACCESS_KEYS_TTL_MS) {
    return cached.keys;
  }
  let body: { keys?: AccessJwk[] };
  try {
    const res = await fetch(url, { redirect: "manual" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    body = (await res.json()) as { keys?: AccessJwk[] };
  } catch {
    throw new AccessKeysUnavailable();
  }
  const keys = Array.isArray(body.keys) ? body.keys : [];
  accessKeysCache = { url, fetchedAt: Date.now(), keys };
  return keys;
}

function base64UrlDecode(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

function decodeJson(part: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(new TextDecoder().decode(base64UrlDecode(part)));
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * True when `token` is an Access assertion for this application: RS256 signed
 * by one of the team's keys, right audience and issuer, not expired.
 * Throws AccessKeysUnavailable when the keys cannot be fetched.
 */
async function verifyAccessAssertion(token: string, teamDomain: string, audience: string): Promise<boolean> {
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const header = decodeJson(parts[0]);
  const payload = decodeJson(parts[1]);
  if (!header || !payload) return false;
  // Only RS256: "none", HMAC and anything else are refused before any key lookup.
  if (header.alg !== "RS256" || typeof header.kid !== "string") return false;

  let jwk = (await accessKeys(teamDomain, false)).find((k) => k.kid === header.kid);
  if (!jwk) jwk = (await accessKeys(teamDomain, true)).find((k) => k.kid === header.kid);
  if (!jwk || jwk.kty !== "RSA" || !jwk.n || !jwk.e) return false;

  let signatureOk = false;
  try {
    const key = await crypto.subtle.importKey(
      "jwk",
      { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    signatureOk = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      base64UrlDecode(parts[2]),
      new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
    );
  } catch {
    return false;
  }
  if (!signatureOk) return false;

  const now = Math.floor(Date.now() / 1000);
  const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!audiences.includes(audience)) return false;
  if (payload.iss !== teamDomain) return false;
  if (typeof payload.exp !== "number" || payload.exp + CLOCK_SKEW_SECONDS < now) return false;
  if (typeof payload.nbf === "number" && payload.nbf - CLOCK_SKEW_SECONDS > now) return false;
  return true;
}

function jsonError(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  const url = new URL(request.url);

  if (!ALLOWED_HOSTS.has(url.hostname)) return jsonError(404, "Not found.");
  if (!ALLOWED_METHODS.has(request.method)) return jsonError(405, "Method not allowed.");

  const apiKey = env.DOCTORFILL_API_KEY;
  const teamDomain = (env.CF_ACCESS_TEAM_DOMAIN ?? "").replace(/\/+$/, "");
  const audience = env.CF_ACCESS_AUD ?? "";
  if (!apiKey || !teamDomain || !audience) return jsonError(500, "API proxy is not configured.");

  // Second lock, independent of the Access rule: no valid assertion, no key.
  const assertion = request.headers.get(ACCESS_ASSERTION_HEADER);
  let allowed = false;
  try {
    allowed = !!assertion && (await verifyAccessAssertion(assertion, teamDomain, audience));
  } catch (err) {
    if (err instanceof AccessKeysUnavailable) return jsonError(503, "Vérification d'accès indisponible.");
    allowed = false;
  }
  if (!allowed) return jsonError(403, "Accès refusé.");

  // The URL parser has already resolved dot segments, so the path cannot climb
  // above /api/. Whatever it contains, it stays a path on the fixed origin.
  if (!url.pathname.startsWith(ROUTE_PREFIX)) return jsonError(404, "Not found.");
  const target = new URL(UPSTREAM_ORIGIN);
  target.pathname = "/" + url.pathname.slice(ROUTE_PREFIX.length);
  target.search = url.search;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set("x-api-key", apiKey);

  const hasBody = request.method === "POST";
  let upstream: Response;
  try {
    upstream = await fetch(target.toString(), {
      method: request.method,
      headers,
      body: hasBody ? request.body : null,
      redirect: "manual",
    });
  } catch {
    // The orchestrator's own error shape, so the UI shows the message as is.
    return jsonError(502, "API injoignable.");
  }

  const responseHeaders = new Headers(upstream.headers);
  for (const name of DROPPED_RESPONSE_HEADERS) responseHeaders.delete(name);
  // Responses carry patient data (fields, synthesis, filled PDF): never cache.
  responseHeaders.set("cache-control", "no-store");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
};
