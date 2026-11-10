// The user's vyomi-tunnel opens its ssh link to the Mesh Codespace lazily, on the first Mesh request.
import assert from "node:assert/strict";
import { createLazySshHub } from "./mesh-lazy-hub.mjs";

const resMock = () => { const r = { headersSent: false, status: 0, body: "", writeHead(s) { r.status = s; r.headersSent = true; }, end(b) { r.body = String(b || ""); r.done(); } }; r.p = new Promise((f) => (r.done = f)); return r; };
let t = 0, opens = 0;
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

console.log("\nall passed");
