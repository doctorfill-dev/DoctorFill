// Tests of the Pages Function functions/api/[[path]].ts, run on Node's fetch
// implementation with a fake upstream. `npm run test:functions` compiles the
// function into .functions-test/ first.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { onRequest } from "../.functions-test/api/[[path]].js";

const KEY = "test-upstream-key";
// Fictitious Access team and application: the tests play the Access side too.
const TEAM = "https://team.example.org";
const AUD = "test-access-audience";
const CERTS_URL = `${TEAM}/cdn-cgi/access/certs`;
const ENV = { DOCTORFILL_API_KEY: KEY, CF_ACCESS_TEAM_DOMAIN: TEAM, CF_ACCESS_AUD: AUD };

const realFetch = globalThis.fetch;
let calls = [];
let certCalls = 0;

const RSA = { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" };
const signing = await crypto.subtle.generateKey(RSA, true, ["sign", "verify"]);
const other = await crypto.subtle.generateKey(RSA, true, ["sign", "verify"]);
const publicJwk = async (pair, kid) => ({ ...(await crypto.subtle.exportKey("jwk", pair.publicKey)), kid });
let publishedKeys = [await publicJwk(signing, "k1")];

const b64url = (data) => Buffer.from(data).toString("base64url");

/** An Access assertion; every claim can be spoiled for the negative tests. */
async function assertion({ key = signing.privateKey, kid = "k1", alg = "RS256", aud = [AUD], iss = TEAM, expIn = 300 } = {}) {
  const now = Math.floor(Date.now() / 1000);
  const head = b64url(JSON.stringify({ alg, kid, typ: "JWT" }));
  const body = b64url(JSON.stringify({ aud, iss, iat: now, exp: now + expIn, email: "medecin-test@example.org" }));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${body}`));
  return `${head}.${body}.${b64url(new Uint8Array(sig))}`;
}
const VALID = await assertion();

function fakeUpstream(respond, certs = () => Response.json({ keys: publishedKeys })) {
  calls = [];
  certCalls = 0;
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    if (url.endsWith("/cdn-cgi/access/certs")) {
      certCalls += 1;
      return certs(url);
    }
    calls.push({ url, init });
    return respond(url, init);
  };
}

afterEach(() => {
  globalThis.fetch = realFetch;
});

/** A request as Access forwards it: with a valid assertion unless told otherwise. */
function call(url, init = {}, env = ENV, token = VALID) {
  const headers = new Headers(init.headers);
  if (token && !headers.has("cf-access-jwt-assertion")) headers.set("cf-access-jwt-assertion", token);
  return onRequest({ request: new Request(url, { ...init, headers }), env });
}

test("relays to the fixed upstream with the server-side key", async () => {
  fakeUpstream(() => new Response('{"forms":[]}', { headers: { "content-type": "application/json" } }));
  const res = await call("https://doctorfill.ch/api/fields/abc?token=t%2B1", {
    headers: { accept: "application/json" },
  });
  assert.equal(res.status, 200);
  assert.equal(await res.text(), '{"forms":[]}');
  assert.equal(res.headers.get("cache-control"), "no-store");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.doctorfill.ch/fields/abc?token=t%2B1");
  assert.equal(calls[0].init.headers.get("x-api-key"), KEY);
  assert.equal(calls[0].init.headers.get("accept"), "application/json");
  assert.equal(calls[0].init.redirect, "manual");
});

test("never forwards client credentials or cookies", async () => {
  fakeUpstream(() => new Response("ok"));
  const res = await call("https://www.doctorfill.ch/api/forms", {
    headers: {
      "x-api-key": "client-supplied",
      cookie: "CF_Authorization=secret",
      authorization: "Bearer x",
      "x-forwarded-host": "evil.example",
    },
  });
  assert.equal(res.status, 200);
  const sent = calls[0].init.headers;
  assert.equal(sent.get("x-api-key"), KEY);
  for (const name of ["cookie", "authorization", "cf-access-jwt-assertion", "x-forwarded-host"]) {
    assert.equal(sent.get(name), null, name);
  }
});

test("streams the request body without reading it", async () => {
  fakeUpstream(() => new Response('{"job_id":"j"}'));
  const form = new FormData();
  form.append("form_id", "Form_X");
  form.append("report_files", new Blob(["%PDF-1.7"], { type: "application/pdf" }), "a.pdf");
  const request = new Request("https://doctorfill.ch/api/process-form", {
    method: "POST",
    body: form,
    headers: { "cf-access-jwt-assertion": VALID },
  });
  const res = await onRequest({ request, env: ENV });
  assert.equal(res.status, 200);
  const init = calls[0].init;
  assert.equal(init.method, "POST");
  assert.equal(init.body, request.body);
  assert.match(init.headers.get("content-type"), /^multipart\/form-data; boundary=/);
});

test("streams the response body and keeps upstream status and errors", async () => {
  const stream = new ReadableStream({
    start(c) {
      c.enqueue(new TextEncoder().encode("data: {}\n\n"));
      c.close();
    },
  });
  fakeUpstream(() => new Response(stream, { status: 503, headers: { "set-cookie": "a=b", "x-other": "1" } }));
  const res = await call("https://doctorfill.ch/api/chat", { method: "POST", body: "{}" });
  assert.equal(res.status, 503);
  assert.equal(res.body instanceof ReadableStream, true);
  assert.equal(await res.text(), "data: {}\n\n");
  assert.equal(res.headers.get("set-cookie"), null);
  assert.equal(res.headers.get("x-other"), "1");
});

test("path tricks stay on the fixed upstream origin", async () => {
  fakeUpstream(() => new Response("ok"));
  for (const path of ["/api//evil.example/x", "/api/%2e%2e/%2e%2e/x", "/api/../../x", "/api/@evil.example"]) {
    const res = await call("https://doctorfill.ch" + path);
    if (res.status === 200) {
      assert.equal(new URL(calls.at(-1).url).origin, "https://api.doctorfill.ch", path);
    } else {
      assert.equal(res.status, 404, path);
    }
  }
  assert.ok(calls.length > 0);
});

test("refuses other hosts, methods and a missing secret without calling upstream", async () => {
  fakeUpstream(() => assert.fail("upstream must not be called"));
  assert.equal((await call("https://doctorfill.pages.dev/api/forms")).status, 404);
  assert.equal((await call("https://abc123.doctorfill.pages.dev/api/forms")).status, 404);
  assert.equal((await call("https://doctorfill.ch/api/forms", { method: "PUT", body: "x" })).status, 405);
  assert.equal((await call("https://doctorfill.ch/api/forms", { method: "DELETE" })).status, 405);
  const res = await call("https://doctorfill.ch/api/forms", {}, {});
  assert.equal(res.status, 500);
  assert.equal(calls.length, 0);
});

test("an unreachable upstream gives a 502 without details", async () => {
  fakeUpstream(() => {
    throw new TypeError(`connect failed with key ${KEY}`);
  });
  const res = await call("https://doctorfill.ch/api/health");
  assert.equal(res.status, 502);
  const body = await res.text();
  assert.ok(!body.includes(KEY));
  assert.deepEqual(JSON.parse(body), { detail: "API injoignable." });
});

// --- Cloudflare Access assertion (issue 36, audit S2) ---------------------------------------

test("forwards the job token header", async () => {
  fakeUpstream(() => new Response("{}"));
  await call("https://doctorfill.ch/api/fields/abc", { headers: { "x-job-token": "jeton-test" } });
  assert.equal(calls[0].init.headers.get("x-job-token"), "jeton-test");
});

test("without an Access assertion the key is never added", async () => {
  fakeUpstream(() => assert.fail("upstream must not be called"));
  const res = await call("https://doctorfill.ch/api/forms", {}, ENV, null);
  assert.equal(res.status, 403);
  assert.equal(calls.length, 0);
});

const spoiled = {
  "signed by another key": () => assertion({ key: other.privateKey }),
  "other audience": () => assertion({ aud: ["other-application"] }),
  "other issuer": () => assertion({ iss: "https://other-team.example.org" }),
  expired: () => assertion({ expIn: -3600 }),
  "unknown key id": () => assertion({ kid: "unknown" }),
  "alg none": async () => `${b64url(JSON.stringify({ alg: "none", kid: "k1" }))}.${VALID.split(".")[1]}.`,
  "HMAC algorithm": () => assertion({ alg: "HS256" }),
  "not a JWT": async () => "not-a-jwt",
  "tampered payload": async () => {
    const [head, , sig] = VALID.split(".");
    const forged = b64url(JSON.stringify({ aud: [AUD], iss: TEAM, exp: 4102444800, email: "x@example.org" }));
    return `${head}.${forged}.${sig}`;
  },
};

for (const [name, make] of Object.entries(spoiled)) {
  test(`refuses an Access assertion: ${name}`, async () => {
    fakeUpstream(() => assert.fail("upstream must not be called"));
    const res = await call("https://doctorfill.ch/api/forms", {}, ENV, await make());
    assert.equal(res.status, 403, name);
    assert.equal(calls.length, 0, name);
  });
}

test("a rotated key is fetched again", async () => {
  const rotated = await crypto.subtle.generateKey(RSA, true, ["sign", "verify"]);
  publishedKeys = [await publicJwk(signing, "k1"), await publicJwk(rotated, "k2")];
  try {
    fakeUpstream(() => new Response("ok"));
    const res = await call("https://doctorfill.ch/api/forms", {}, ENV,
      await assertion({ key: rotated.privateKey, kid: "k2" }));
    assert.equal(res.status, 200);
    assert.equal(certCalls, 1);
  } finally {
    publishedKeys = [await publicJwk(signing, "k1")];
  }
});

test("unreachable Access keys fail closed with a 503", async () => {
  fakeUpstream(() => assert.fail("upstream must not be called"), () => {
    throw new TypeError("network down");
  });
  // Another team domain: nothing cached for it.
  const env = { ...ENV, CF_ACCESS_TEAM_DOMAIN: "https://down.example.org" };
  const res = await call("https://doctorfill.ch/api/forms", {}, env,
    await assertion({ iss: "https://down.example.org" }));
  assert.equal(res.status, 503);
  assert.equal(calls.length, 0);
});

test("refuses to relay without the Access configuration", async () => {
  fakeUpstream(() => assert.fail("upstream must not be called"));
  for (const env of [{ DOCTORFILL_API_KEY: KEY }, { ...ENV, CF_ACCESS_AUD: "" }, { ...ENV, CF_ACCESS_TEAM_DOMAIN: "" }]) {
    assert.equal((await call("https://doctorfill.ch/api/forms", {}, env)).status, 500);
  }
  assert.equal(calls.length, 0);
});
