// Worker /egress route: Origin rule, CORS preflight, allow-list, https upgrade, rate limit, and that
// "egress" is never treated as a session id. Run: node wasm/relay/test-worker-egress.mjs
import worker from "./worker.js";
import assert from "node:assert/strict";

const env = (extra = {}) => ({ ALLOWED_ORIGIN: "https://vyomi.cloud",
  RELAY: { get() { throw new Error("RELAY must not be touched by /egress"); }, idFromName() { return "x"; } }, ...extra });
const req = (u, o = {}) => new Request("https://relay.vyomi.cloud/egress?u=" + encodeURIComponent(u),
  { method: o.method || "GET", headers: { Origin: "https://vyomi.cloud", ...(o.headers || {}) } });
const seen = [];
globalThis.fetch = async (target) => { seen.push(String(target)); return new Response("pkg-bytes", { status: 200, headers: { "content-type": "application/octet-stream" } }); };

let n = 0; const ok = (name) => { n++; console.log("ok -", name); };

let r = await worker.fetch(new Request("https://relay.vyomi.cloud/egress", { method: "OPTIONS", headers: { Origin: "https://vyomi.cloud" } }), env());
assert.equal(r.status, 204); assert.equal(r.headers.get("access-control-allow-origin"), "https://vyomi.cloud"); ok("preflight 204 + CORS");

r = await worker.fetch(req("http://pypi.org/simple/pip/", { headers: { Origin: "https://evil.example" } }), env());
assert.equal(r.status, 403); assert.equal(seen.length, 0); ok("foreign Origin refused, no upstream fetch");

r = await worker.fetch(req("http://pypi.org/simple/pip/"), env());
assert.equal(r.status, 200); assert.equal(await r.text(), "pkg-bytes");
assert.equal(seen[0], "https://pypi.org/simple/pip/"); assert.equal(r.headers.get("access-control-allow-origin"), "https://vyomi.cloud"); ok("allowed host: http upgraded to https upstream, CORS set");

seen.length = 0;
r = await worker.fetch(req("http://example.com/x"), env());
assert.equal(r.status, 403); assert.equal(seen.length, 0); ok("host off the allow-list blocked");
r = await worker.fetch(req("http://127.0.0.1:8080/"), env());
assert.equal(r.status, 403); ok("localhost/IP blocked");
r = await worker.fetch(req("http://169.254.169.254/latest/meta-data/"), env());
assert.equal(r.status, 403); ok("metadata IP blocked");

r = await worker.fetch(req("http://pypi.org/x", { method: "DELETE" }), env());
assert.equal(r.status, 405); ok("DELETE refused");

let calls = 0;
const limited = env({ EGRESS_LIMIT: { limit: async ({ key }) => { calls++; assert.equal(key, "9.9.9.9"); return { success: false }; } } });
r = await worker.fetch(req("http://pypi.org/x", { headers: { "CF-Connecting-IP": "9.9.9.9" } }), limited);
assert.equal(r.status, 429); assert.equal(calls, 1); ok("rate limit -> 429 (keyed by CF-Connecting-IP)");

r = await worker.fetch(req("http://pypi.org/x"), env({ ALLOWED_ORIGIN: "https://vyomi.cloud" }));
assert.equal(r.status, 200); ok("no EGRESS_LIMIT binding: still works");

console.log(`\n${n} checks passed`);
