// The user's vyomi-tunnel opens its ssh link to the Mesh Codespace lazily, on the first Mesh request.
import assert from "node:assert/strict";
import { createLazySshHub } from "./mesh-lazy-hub.mjs";

const resMock = () => { const r = { headersSent: false, status: 0, body: "", writeHead(s) { r.status = s; r.headersSent = true; }, end(b) { r.body = String(b || ""); r.done(); } }; r.p = new Promise((f) => (r.done = f)); return r; };
let t = 0, opens = 0;
const check2 = (name, ok) => { assert.ok(ok, name); console.log("PASS " + name); };
const mk = (openMesh) => createLazySshHub({ WebSocketServer: class {}, WebSocket: class {}, openMesh, retryMs: 1000, now: () => t });

// 1. plain relay traffic (no X-Vyomi-Session-Token) is not the Mesh plane, and never opens a session
{ const h = mk(async () => { opens++; return { error: "x" }; });
  assert.equal(h.http({ headers: {} }, resMock(), Buffer.alloc(0)), false); assert.equal(opens, 0); assert.equal(h.enabled(), false); console.log("PASS no session opened for plain relay traffic"); }

// 2. no key / Free plan -> 403 PlanNotAllowed JSON, and the failure is cached (no hammering of the portal)
{ const h = mk(async () => { opens++; return { error: "Mesh needs a Pro or Max plan.", code: "PlanNotAllowed" }; });
  for (let i = 0; i < 3; i++) { const r = resMock(); assert.equal(h.http({ headers: { "x-vyomi-session-token": "x" } }, r, Buffer.alloc(0)), true); await r.p;
    assert.equal(r.status, 403); assert.equal(JSON.parse(r.body).error.code, "PlanNotAllowed"); }
  assert.equal(opens, 1); console.log("PASS Free plan refused with 403 and the failure is cached");
  t += 2000; const r = resMock(); h.http({ headers: { "x-vyomi-session-token": "x" } }, r, Buffer.alloc(0)); await r.p; assert.equal(opens, 2); console.log("PASS retried after the cache window"); }

// 3. Codespace not running -> 503 MeshUnavailable
{ const h = mk(async () => ({ error: "your Mesh Codespace is stopped.", code: undefined }));
  const r = resMock(); h.http({ headers: { "x-vyomi-session-token": "x" } }, r, Buffer.alloc(0)); await r.p;
  assert.equal(r.status, 503); assert.equal(JSON.parse(r.body).error.code, "MeshUnavailable"); console.log("PASS stopped Codespace -> 503 MeshUnavailable"); }

// 4. /shell and /connect upgrades are refused cleanly (not left hanging) when no Mesh can be opened
{ const h = mk(async () => ({ error: "no", code: "NoCredentials" })); let wrote = "", destroyed = false;
  const sock = { write: (s) => (wrote += s), destroy: () => (destroyed = true) };
  h.shellUpgrade({ headers: {}, url: "/shell" }, sock, Buffer.alloc(0)); await new Promise((r) => setTimeout(r, 20));
  assert.match(wrote, /503 MeshUnavailable/); assert.ok(destroyed); console.log("PASS /shell refused with 503 when no Mesh"); }

// 5. a running relay FOLLOWS the Mesh: a restart makes a new Codespace, a dead one is not kept, an ended session drops the link
{ const REQ = { headers: { "x-vyomi-session-token": "t" }, method: "GET", url: "/mesh/status" };
  const fakeTransport = (cs, mode) => ({ codespace: cs, closed: false, onStop() {}, close() { this.closed = true; },
    httpToSimulator: async (_q, res) => { if (mode === "fail") throw new Error("MeshSimulatorDown"); res.writeHead(200, {}); res.end("ok:" + cs); } });
  const send = async (h) => { const r = resMock(); h.http(REQ, r, Buffer.alloc(0)); await r.p; return r; };
  let n = 0, cur = { codespace: "cs-a" }; const made = [];
  const mk2 = (modeOf = () => "ok") => createLazySshHub({ WebSocketServer: class {}, WebSocket: class {}, recheckMs: 1000, now: () => t,
    openMesh: async () => { n++; const tr = fakeTransport(cur.codespace, modeOf()); made.push(tr); return { transport: tr, sess: { codespace: cur.codespace } }; },
    currentCodespace: async () => cur });
  const h = mk2(); t = 0;
  let r = await send(h); check2("first request opens a link to the current Codespace", r.status === 200 && r.body === "ok:cs-a" && n === 1);
  r = await send(h); check2("same Codespace: the link is reused", n === 1);
  cur = { codespace: "cs-b" }; r = await send(h); check2("Codespace changed but inside the re-check window: not re-read yet", n === 1);
  t += 2000; r = await send(h); check2("after the window the relay follows the new Codespace", r.body === "ok:cs-b" && n === 2 && made[0].closed === true);
  cur = { error: "SessionEnded" }; t += 2000; r = await send(h); check2("Mesh session ended: the old link is dropped (no stale answers)", made[1].closed === true);
  // simulator stream failure drops the link so the next request reopens
  n = 0; made.length = 0; cur = { codespace: "cs-c" }; let mode = "fail"; const h2 = mk2(() => mode); t += 5000;
  r = await send(h2); check2("simulator stream failure answers 502", r.status === 502 && n === 1);
  await new Promise((f) => setTimeout(f, 10)); mode = "ok"; r = await send(h2);
  check2("next request after a failure opens a fresh link", r.status === 200 && n === 2 && made[0].closed === true); }

console.log("\nall passed");
