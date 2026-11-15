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
 * - Request headers are forwarded from an allowlist. Client-supplied X-API-Key,
 *   cookies (including the Access session cookie), Authorization and Access
 *   assertion headers never reach the upstream.
 * - Nothing is logged: no body, file name, path or query string (job tokens
 *   travel in the query string; patient data in bodies, see platform#51).
 * - Errors never echo the key or upstream details.
 */

interface Env {
  /** Pages secret: the API key the orchestrator expects in X-API-Key. */
  DOCTORFILL_API_KEY?: string;
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
];
const DROPPED_RESPONSE_HEADERS = ["set-cookie"];

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
  if (!apiKey) return jsonError(500, "API proxy is not configured.");

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
