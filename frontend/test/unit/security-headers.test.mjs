// En-têtes de sécurité (issue 33, audit S5) : public/_headers pour Cloudflare
// Pages, et la CSP de l'application de bureau (src-tauri/tauri.conf.json).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("../../", import.meta.url);
const headersFile = readFileSync(new URL("public/_headers", root), "utf-8");
const tauriConf = JSON.parse(readFileSync(new URL("src-tauri/tauri.conf.json", root), "utf-8"));

/** En-têtes de la règle `/*` du fichier _headers. */
function pagesHeaders() {
  const headers = new Map();
  let inRule = false;
  for (const line of headersFile.split(/\r?\n/)) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    if (!/^\s/.test(line)) {
      inRule = line.trim() === "/*";
      continue;
    }
    if (!inRule) continue;
    const at = line.indexOf(":");
    headers.set(line.slice(0, at).trim().toLowerCase(), line.slice(at + 1).trim());
  }
  return headers;
}

function parseCsp(policy) {
  const directives = new Map();
  for (const part of policy.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/);
    if (name) directives.set(name.toLowerCase(), sources);
  }
  return directives;
}

function assertSubset(actual, allowed, label) {
  assert.ok(actual, `${label} manquant`);
  for (const source of actual) assert.ok(allowed.includes(source), `${label} : ${source} non autorisé`);
}

function assertStrictCsp(csp, connectAllowed) {
  assert.deepEqual(csp.get("default-src"), ["'self'"]);
  assert.deepEqual(csp.get("script-src"), ["'self'"]);
  assert.deepEqual(csp.get("object-src"), ["'none'"]);
  assert.deepEqual(csp.get("base-uri"), ["'self'"]);
  assert.deepEqual(csp.get("frame-ancestors"), ["'none'"]);
  // Une image vers un site extérieur emporterait des données dans son URL.
  assertSubset(csp.get("img-src"), ["'self'", "blob:", "data:"], "img-src");
  assertSubset(csp.get("connect-src"), connectAllowed, "connect-src");
  for (const [name, sources] of csp) {
    for (const source of sources) {
      assert.ok(!["*", "https:", "http:", "'unsafe-eval'"].includes(source), `${name} : ${source}`);
    }
  }
}

test("Pages serves a strict content security policy", () => {
  const csp = pagesHeaders().get("content-security-policy");
  assert.ok(csp, "Content-Security-Policy absent de public/_headers");
  assertStrictCsp(parseCsp(csp), ["'self'", "blob:", "https://formspree.io"]);
});

test("Pages serves the other security headers", () => {
  const headers = pagesHeaders();
  assert.equal(headers.get("x-content-type-options"), "nosniff");
  assert.equal(headers.get("referrer-policy"), "no-referrer");
  assert.equal(headers.get("x-frame-options"), "DENY");
  assert.match(headers.get("strict-transport-security") ?? "", /max-age=\d{7,}/);
});

test("the desktop app has the same policy", () => {
  const csp = tauriConf.app.security.csp;
  assert.equal(typeof csp, "string", "CSP Tauri absente (null)");
  assertStrictCsp(parseCsp(csp), ["'self'", "blob:", "ipc:", "http://ipc.localhost"]);
});
