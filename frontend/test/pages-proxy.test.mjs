// Tests of the Pages Function functions/api/[[path]].ts, run on Node's fetch
// implementation with a fake upstream. `npm run test:functions` compiles the
// function into .functions-test/ first.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { onRequest } from "../.functions-test/api/[[path]].js";

const KEY = "test-upstream-key";
const realFetch = globalThis.fetch;
let calls = [];

function fakeUpstream(respond) {
  calls = [];
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ url: String(input), init });
    return respond(String(input), init);
  };
}

afterEach(() => {
  globalThis.fetch = realFetch;
});

function call(url, init = {}, env = { DOCTORFILL_API_KEY: KEY }) {
  return onRequest({ request: new Request(url, init), env });
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
  await call("https://www.doctorfill.ch/api/forms", {
    headers: {
      "x-api-key": "client-supplied",
      cookie: "CF_Authorization=secret",
      authorization: "Bearer x",
      "cf-access-jwt-assertion": "jwt",
      "x-forwarded-host": "evil.example",
    },
  });
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
  const request = new Request("https://doctorfill.ch/api/process-form", { method: "POST", body: form });
  const res = await onRequest({ request, env: { DOCTORFILL_API_KEY: KEY } });
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
