/* Gateway-backend egress: local relay (mapped only), hosted relay worker (public allow-list), SSRF/abuse hardening, the CLI subcommand.
 * Run: WS_PKG=$PWD/relay-deps/ws node wasm/relay/test-gw-egress.mjs
 */
import assert from "node:assert/strict";
import http from "node:http";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { LIMITS, isPrivateAddress, hostedTargetProblem, serveGwEgress, createRateLimiter } from "./gw-egress.mjs";
import { createLocalGw, parseMapping, nodeTransport } from "./gw-egress-node.mjs";
import worker from "./worker.js";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";

let n = 0; const ok = (m) => { n++; console.log("ok -", m); };
const b64 = (s) => Buffer.from(s).toString("base64");
const listen = (h) => new Promise((r) => { const s = http.createServer(h); s.listen(0, "127.0.0.1", () => r(s)); });
const hits = { backend: 0, trap: 0, headers: null, body: null };
const trap = await listen((q, r) => { hits.trap++; r.end("TRAP"); });               // stands in for a private/metadata service
const trapUrl = `http://127.0.0.1:${trap.address().port}/`;
const backend = await listen((q, r) => {
  hits.backend++; hits.headers = q.headers; const c = []; q.on("data", (d) => c.push(d)); q.on("end", () => { hits.body = Buffer.concat(c).toString();
    if (q.url.startsWith("/redir")) { r.writeHead(302, { location: trapUrl, "set-cookie": "s=1" }); return r.end(); }
    if (q.url.startsWith("/big")) { r.writeHead(200); return r.end(Buffer.alloc(300000, 65)); }
    if (q.url.startsWith("/slow")) return setTimeout(() => r.end("late"), 4000);
    r.writeHead(201, { "content-type": "application/json", "x-backend": "real", connection: "keep-alive", "set-cookie": "a=b" });
    r.end(JSON.stringify({ path: q.url, method: q.method, body: hits.body }));
  });
});
const BASE = `http://127.0.0.1:${backend.address().port}`;
const home = mkdtempSync(join(tmpdir(), "gw-"));
const env = { VYOMI_GW_EGRESS: "1", VYOMI_GATEWAY_BACKENDS_FILE: join(home, "gw.json") };
const MAP = { "https://hello.run.app": BASE, "https://meta.run.app": "http://169.254.169.254", "https://dns.run.app": "http://rebind.example:80" };
writeFileSync(env.VYOMI_GATEWAY_BACKENDS_FILE, JSON.stringify({ version: 1, backends: MAP }));

// ── the real local gate over a real HTTP server ─────────────────────────────
const gw = createLocalGw({ env, resolve: async (h) => (h === "rebind.example" ? ["169.254.169.254"] : ["127.0.0.1"]), log: () => {} });
const relay = await listen((req, res) => { const c = []; req.on("data", (d) => c.push(d)); req.on("end", () => { if (!gw.http(req, res, Buffer.concat(c))) { res.writeHead(404); res.end(); } }); });
const RU = `http://127.0.0.1:${relay.address().port}`;
const ORIGIN = "https://vyomi.cloud";
const post = (body, h = {}) => fetch(RU + "/gw-egress", { method: "POST", headers: { origin: ORIGIN, "x-vyomi-gw-token": gw.token, ...h }, body: typeof body === "string" ? body : JSON.stringify(body) });
const fwd = (url, o = {}) => ({ method: "GET", url, headers: {}, timeout: 5, ...o });

let r = await fetch(RU + "/gw-token", { headers: { origin: "https://evil.example" } }); assert.equal(r.status, 403); assert.equal(r.headers.get("access-control-allow-origin"), "*"); ok("/gw-token refused for a foreign Origin (and never echoes it)");
r = await fetch(RU + "/gw-token"); assert.equal(r.status, 403); ok("/gw-token refused with no Origin header");
r = await fetch(RU + "/gw-token", { headers: { origin: ORIGIN } }); assert.equal(r.status, 200); assert.equal(r.headers.get("access-control-allow-origin"), ORIGIN); assert.equal((await r.json()).token, gw.token); ok("/gw-token handed to the Nano origin only");
r = await fetch(RU + "/gw-token", { headers: { origin: "http://localhost:8099" } }); assert.equal(r.status, 200); ok("localhost portal origin allowed");

r = await fetch(RU + "/gw-egress", { method: "POST", headers: { origin: ORIGIN }, body: JSON.stringify(fwd("https://hello.run.app/x")) }); assert.equal(r.status, 401); assert.equal((await r.json()).code, "unauthorized"); ok("no token -> 401");
r = await post(fwd("https://hello.run.app/x"), { "x-vyomi-gw-token": "nope" }); assert.equal(r.status, 401); ok("wrong token -> 401");
r = await post(fwd("https://hello.run.app/x"), { origin: "https://evil.example" }); assert.equal(r.status, 403); assert.equal(hits.backend, 0); ok("foreign Origin with a valid token -> 403, backend untouched");

r = await post(fwd("https://hello.run.app/api/items?x=1", { method: "POST", body: b64("hi"), headers: { "content-type": "text/plain", cookie: "sid=1", "x-vyomi-session": "s", authorization: "Bearer app", connection: "close" } }));
let j = await r.json(); assert.equal(r.status, 200); assert.equal(j.status, 201);
const inner = JSON.parse(Buffer.from(j.body, "base64").toString()); assert.deepEqual([inner.path, inner.method, inner.body], ["/api/items?x=1", "POST", "hi"]);
assert.equal(j.headers["x-backend"], "real"); assert.ok(!("set-cookie" in j.headers) && !("connection" in j.headers)); ok("mapped backend: real 2xx round-trip (path, query, body); set-cookie + hop headers stripped on the way back");
assert.ok(!hits.headers.cookie && !hits.headers["x-vyomi-session"] && hits.headers.authorization === "Bearer app"); ok("cookie / x-vyomi-* not forwarded; backend Authorization kept");

const before = hits.backend + hits.trap;
for (const u of ["https://unmapped.example.com/x", "https://127.0.0.1/x", "http://169.254.169.254/latest/meta-data/", trapUrl, "https://hello.run.app.evil.com/x"]) {
  r = await post(fwd(u)); j = await r.json(); assert.equal(r.status, 502, u); assert.equal(j.code, "not-mapped", u); assert.match(j.error, /vyomi-tunnel gateway-backend/);
}
assert.equal(hits.backend + hits.trap, before); ok("unmapped (incl. private / loopback / metadata / look-alike hosts) -> 502 not-mapped, nothing contacted");
r = await post(fwd("https://meta.run.app/x")); assert.equal(r.status, 403); assert.equal((await r.json()).code, "blocked"); ok("a map entry pointing at the metadata IP is refused at request time");
r = await post(fwd("https://dns.run.app/x")); assert.equal(r.status, 403); ok("a mapped hostname that RESOLVES to a link-local address is refused (DNS check)");

const t0 = hits.trap;
r = await post(fwd("https://hello.run.app/redir")); j = await r.json(); assert.equal(j.status, 302); assert.equal(hits.trap, t0); assert.ok(j.headers.location.startsWith("http://127.0.0.1")); ok("redirect to a private address is NOT followed (3xx returned verbatim, trap never hit)");

const saved = LIMITS.local.respBody; LIMITS.local.respBody = 100000;
r = await post(fwd("https://hello.run.app/big")); assert.equal(r.status, 413); assert.equal((await r.json()).code, "too-large"); LIMITS.local.respBody = saved; ok("oversize response -> 413");
const sr = LIMITS.local.reqBody; LIMITS.local.reqBody = 1000;
r = await post(fwd("https://hello.run.app/x", { method: "POST", body: b64("x".repeat(5000)) })); assert.equal(r.status, 413); LIMITS.local.reqBody = sr; ok("oversize request body -> 413");
r = await post(fwd("https://hello.run.app/slow", { timeout: 1 })); assert.equal(r.status, 504); assert.equal((await r.json()).code, "timeout"); ok("slow backend -> 504 timeout (capped)");
for (const m of ["CONNECT", "TRACE", "BREW"]) { r = await post(fwd("https://hello.run.app/x", { method: m })); assert.equal(r.status, 405, m); } ok("CONNECT / TRACE / unknown methods -> 405");
r = await post(fwd("https://user:pw@hello.run.app/x")); assert.equal(r.status, 400); ok("credentials in the URL refused");
r = await post("not json"); assert.equal(r.status, 400); ok("non-JSON body -> 400");
r = await fetch(RU + "/gw-egress", { method: "GET", headers: { origin: ORIGIN } }); assert.equal(r.status, 405); ok("GET /gw-egress -> 405");

// rate limit: 240/min local; drive the limiter directly to keep the test fast
const lim = createRateLimiter(3); assert.deepEqual([1, 2, 3, 4].map(() => lim.take("k")), [true, true, true, false]); assert.ok(lim.take("other"));
const rl = await serveGwEgress({ mode: "local", payload: fwd("https://hello.run.app/"), map: MAP, transport: async () => ({ status: 200, headers: {}, body: new Uint8Array() }), limiter: { take: () => false } });
assert.equal(rl.status, 429); ok("per-session rate limit -> 429");
const off = createLocalGw({ env: {}, log: () => {} }); const fake = { writeHead(s) { this.s = s; }, end() {}, }; off.http({ url: "/gw-token", method: "GET", headers: { origin: ORIGIN } }, fake, Buffer.alloc(0));
assert.equal(fake.s, 501); ok("relay copy without sign-in (appliance-bundled) has gateway egress OFF (501)");

// ── logging: every egress logs ─────────────────────────────────────────────
const logs = []; await serveGwEgress({ mode: "local", payload: fwd("https://nope.example/p?secret=1"), map: MAP, transport: async () => ({}), log: (e) => logs.push(e) });
assert.equal(logs.length, 1); assert.equal(logs[0].status, 502); assert.ok(!JSON.stringify(logs).includes("secret=1")); ok("each egress is logged (origin + path, never the query)");

// ── address classification ─────────────────────────────────────────────────
for (const ip of ["127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.1", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "::1", "fe80::1", "fd00:ec2::254", "::ffff:127.0.0.1", "::ffff:7f00:1", "224.0.0.1"]) assert.ok(isPrivateAddress(ip), ip);
for (const ip of ["8.8.8.8", "142.250.1.1", "172.32.0.1", "2607:f8b0::1"]) assert.ok(!isPrivateAddress(ip), ip); ok("private / loopback / link-local / metadata / mapped-v6 classification");

// ── hosted relay policy ────────────────────────────────────────────────────
const P = (u, a) => hostedTargetProblem(new URL(u), a);
assert.equal(P("https://hello-abc-uc.a.run.app/x"), null); assert.equal(P("https://abc.execute-api.us-east-1.amazonaws.com/p"), null); assert.equal(P("https://x.azurewebsites.net"), null);
assert.match(P("http://hello.run.app/"), /https only/); assert.match(P("https://hello.run.app:8443/"), /443/); assert.match(P("https://127.0.0.1/"), /private/); assert.match(P("https://169.254.169.254/"), /private/);
assert.match(P("https://[::1]/"), /private/); assert.match(P("https://2130706433/"), /private/); assert.match(P("https://localhost/"), /private/); assert.match(P("https://svc.internal/"), /private/);
assert.match(P("https://metadata.google.internal/"), /private/); assert.match(P("https://example.com/"), /allow-list/); assert.match(P("https://evilrun.app/"), /allow-list/); assert.match(P("https://u:p@x.run.app/"), /credentials/);
assert.equal(P("https://api.example.com/", ["api.example.com"]), null); ok("hosted policy: https/443 only, no IP literals / internal names, allow-list (+ override)");
const hostedCalls = []; const hostedT = async (o) => { hostedCalls.push(o); return { status: 200, headers: { "set-cookie": "x", "x-a": "1" }, body: new Uint8Array([104, 105]) }; };
let h = await serveGwEgress({ mode: "hosted", payload: fwd("https://hello.run.app/p"), transport: hostedT, who: "s" }); assert.equal(h.status, 200); assert.equal(hostedCalls[0].redirect, "manual"); assert.equal(JSON.parse(h.body).headers["x-a"], "1"); assert.ok(!("set-cookie" in JSON.parse(h.body).headers)); ok("hosted: allowed public host served, redirects set to manual, cookies stripped");
hostedCalls.length = 0;
for (const u of ["http://hello.run.app/", "https://10.0.0.1/", "https://example.com/"]) { h = await serveGwEgress({ mode: "hosted", payload: fwd(u), transport: hostedT }); assert.equal(h.status, 403, u); } assert.equal(hostedCalls.length, 0); ok("hosted: blocked targets never reach the transport");
LIMITS.hosted.respBody = 10; let big = await serveGwEgress({ mode: "hosted", payload: fwd("https://hello.run.app/"), transport: async () => { throw Object.assign(new Error("x"), { code: "too-large" }); } }); assert.equal(big.status, 413); LIMITS.hosted.respBody = 4 * 1024 * 1024; ok("hosted: oversize response -> 413");

// ── the Worker route ───────────────────────────────────────────────────────
const doStub = (has) => ({ idFromName: (s) => s, get: (s) => ({ fetch: async () => (has.includes(s) ? new Response("yes") : new Response("no", { status: 404 })) }) });
const wenv = (extra = {}) => ({ ALLOWED_ORIGIN: "https://vyomi.cloud", RELAY: doStub(["sess1"]), ...extra });
const wreq = (body, h = {}, method = "POST") => new Request("https://relay.vyomi.cloud/gw-egress", { method, headers: { Origin: ORIGIN, "x-vyomi-session": "sess1", ...h }, body: method === "POST" ? JSON.stringify(body) : undefined });
const realFetch = globalThis.fetch;
const upstream = []; globalThis.fetch = async (u, o) => { upstream.push([String(u), o]); return new Response("pong", { status: 200, headers: { "x-up": "1" } }); };
let w = await worker.fetch(wreq(fwd("https://hello.run.app/p")), wenv()); assert.equal(w.status, 200); const wj = await w.json(); assert.equal(wj.status, 200); assert.equal(Buffer.from(wj.body, "base64").toString(), "pong"); assert.equal(upstream[0][1].redirect, "manual"); assert.equal(upstream[0][0], "https://hello.run.app/p"); ok("worker: allowed backend -> 200 envelope, upstream fetch with redirect:manual");
upstream.length = 0;
w = await worker.fetch(wreq(fwd("https://hello.run.app/p"), { Origin: "https://evil.example" }), wenv()); assert.equal(w.status, 403);
w = await worker.fetch(wreq(fwd("https://hello.run.app/p"), { Origin: "" }), wenv()); assert.equal(w.status, 403); ok("worker: foreign / missing Origin -> 403");
w = await worker.fetch(wreq(fwd("https://hello.run.app/p"), { "x-vyomi-session": "" }), wenv()); assert.equal(w.status, 401);
w = await worker.fetch(wreq(fwd("https://hello.run.app/p"), { "x-vyomi-session": "ghost" }), wenv()); assert.equal(w.status, 401); ok("worker: no session / no registered tab -> 401 (auth required)");
for (const u of ["http://hello.run.app/", "https://127.0.0.1/", "https://169.254.169.254/latest", "https://localhost/", "https://example.com/"]) { w = await worker.fetch(wreq(fwd(u)), wenv()); assert.equal(w.status, 403, u); } assert.equal(upstream.length, 0); ok("worker: http, loopback, metadata, localhost, off-allow-list all blocked before any fetch");
globalThis.fetch = async () => new Response(null, { status: 302, headers: { location: "http://169.254.169.254/" } }); upstream.length = 0;
w = await worker.fetch(wreq(fwd("https://hello.run.app/redir")), wenv()); assert.equal((await w.json()).status, 302); ok("worker: backend redirect to a private address returned, not followed");
globalThis.fetch = async () => new Response(new Uint8Array(LIMITS.hosted.respBody + 10)); w = await worker.fetch(wreq(fwd("https://hello.run.app/big")), wenv()); assert.equal(w.status, 413); ok("worker: oversize streamed response -> 413");
w = await worker.fetch(wreq(fwd("https://hello.run.app/p", { body: b64("x".repeat(2 * 1024 * 1024)) })), wenv()); assert.equal(w.status, 413); ok("worker: oversize request -> 413");
w = await worker.fetch(wreq(fwd("https://hello.run.app/p"), {}, "GET"), wenv()); assert.equal(w.status, 405);
w = await worker.fetch(wreq(fwd("https://hello.run.app/p", { method: "CONNECT" })), wenv()); assert.equal(w.status, 405); ok("worker: GET route / CONNECT method -> 405");
w = await worker.fetch(wreq(fwd("https://hello.run.app/p")), wenv({ GW_LIMIT: { limit: async () => ({ success: false }) } })); assert.equal(w.status, 429); ok("worker: GW_LIMIT binding -> 429");
w = await worker.fetch(new Request("https://relay.vyomi.cloud/gw-egress", { method: "OPTIONS", headers: { Origin: ORIGIN } }), wenv()); assert.equal(w.status, 204); assert.equal(w.headers.get("access-control-allow-origin"), ORIGIN); ok("worker: CORS preflight");

globalThis.fetch = realFetch;
// ── the CLI + a real relay process (signed in via the stub portal) ───────────
const portal = await startStubPortal({});
const WS_PKG = process.env.WS_PKG || new URL("../../relay-deps/ws", import.meta.url).pathname;
const cli = new URL("./local-relay.mjs", import.meta.url).pathname;
const cenv = { ...process.env, WS_PKG, VYOMI_HOME: home, HOME: home, VYOMI_PORTAL_URL: portal.url, VYOMI_ACCESS_KEY_ID: "VYKAFREE", VYOMI_SECRET_ACCESS_KEY: "free-secret", VYOMI_GATEWAY_BACKENDS_FILE: join(home, "cli.json") };
delete cenv.VYOMI_GW_EGRESS;
const run = (args, e = {}) => new Promise((res) => { const c = spawn(process.execPath, [cli, ...args], { env: { ...cenv, ...e } }); let out = "", err = ""; c.stdout.on("data", (d) => out += d); c.stderr.on("data", (d) => err += d); c.on("close", (code) => res({ code, out, err })); });
let c = await run(["gateway-backend", `https://cli.run.app=${BASE}`], { VYOMI_ACCESS_KEY_ID: "", VYOMI_SECRET_ACCESS_KEY: "", HOME: mkdtempSync(join(tmpdir(), "nohome-")), VYOMI_HOME: mkdtempSync(join(tmpdir(), "nohome-")) }); assert.equal(c.code, 2); assert.match(c.err, /No Vyomi credentials/); ok("CLI: gateway-backend needs credentials like every command");
c = await run(["gateway-backend", `https://cli.run.app=${BASE}`]); assert.equal(c.code, 0, c.err); assert.deepEqual(JSON.parse(readFileSync(join(home, "cli.json"), "utf8")).backends, { "https://cli.run.app": BASE }); ok("CLI: gateway-backend <origin>=<local> writes the map");
c = await run(["gateway-backend", "--list"]); assert.match(c.out, /cli\.run\.app/); ok("CLI: --list");
for (const bad of ["http://x.run.app=http://127.0.0.1:1", "https://x.run.app", "https://x.run.app/p=http://127.0.0.1:1", "https://x.run.app=http://169.254.169.254", "https://x.run.app=ftp://h", "https://x.run.app=http://[fe80::1]"]) { c = await run(["gateway-backend", bad]); assert.equal(c.code, 2, bad); } ok("CLI: bad mappings rejected (http left side, no target, paths, metadata/link-local, non-http target)");
assert.ok(parseMapping("https://a.run.app=http://127.0.0.1:3000").from);
// a real relay process, started the way a user does, serving the mapped backend
const port = 18700 + Math.floor(Math.random() * 200);
const relayP = spawn(process.execPath, [cli], { env: { ...cenv, RELAY_PORT: String(port), RELAY_AMQP_PORT: "0", VYOMI_RELAY_AUTH: "1" } });
let rout = ""; relayP.stdout.on("data", (d) => rout += d); relayP.stderr.on("data", (d) => rout += d);
for (let i = 0; i < 60 && !/health/.test(rout); i++) await new Promise((r) => setTimeout(r, 250));
const RP = `http://127.0.0.1:${port}`;
try {
  const hr = await fetch(RP + "/health"); const ht = await hr.text(); if (hr.status !== 200 || ht[0] !== "{") console.log("HEALTH", hr.status, JSON.stringify(ht.slice(0, 60)), rout.slice(-600)); const health = JSON.parse(ht); assert.ok(health.features.includes("gw-egress"));
  const tok = (await (await fetch(RP + "/gw-token", { headers: { origin: ORIGIN } })).json()).token;
  const pre = await fetch(RP + "/gw-egress", { method: "OPTIONS", headers: { origin: ORIGIN, "access-control-request-method": "POST", "access-control-request-headers": "x-vyomi-gw-token,content-type", "access-control-request-private-network": "true" } });
  assert.equal(pre.status, 204); assert.equal(pre.headers.get("access-control-allow-private-network"), "true");
  const go = (url) => fetch(RP + "/gw-egress", { method: "POST", headers: { origin: ORIGIN, "x-vyomi-gw-token": tok }, body: JSON.stringify(fwd(url)) });
  let g = await go("https://cli.run.app/live"); const gj = await g.json(); assert.equal(g.status, 200); assert.equal(gj.status, 201);
  g = await go("https://other.run.app/live"); assert.equal(g.status, 502); assert.equal((await g.json()).code, "not-mapped");
  c = await run(["gateway-backend", `https://other.run.app=${BASE}`]); g = await go("https://other.run.app/live"); assert.equal(g.status, 200);   // picked up without restart
  assert.match(rout, /gw-egress/); ok("real relay process: preflight (PNA) ok, mapped 2xx, unmapped 502, map change picked up live, egress logged");
} finally { relayP.kill(); portal.close(); }
console.log(`\n${n} checks passed`); process.exit(0);
