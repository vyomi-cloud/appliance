/* Console widget logic for the tunnel-credentials strip (wasm/mesh-widget.js): what it shows, Reset flow, auto-reset limits.
 * Run: node wasm/relay/test-tunnel-creds-widget.mjs */
import fs from "node:fs"; import vm from "node:vm"; import assert from "node:assert/strict"; import { fileURLToPath } from "node:url"; import { dirname, join } from "node:path";
const src = fs.readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../mesh-widget.js"), "utf8");
const a = src.indexOf("  // ── tunnel credentials sync"), b = src.indexOf("  function boot() {");
assert(a > 0 && b > a);
const calls = []; let script = []; const toasts = []; const store = {};
const fetch = (url, opt) => { calls.push([url, (opt && opt.method) || "GET", opt && opt.body]); const r = script.shift() || { status: 200, j: {} };
  if (r.fail) return Promise.reject(new Error("net")); return Promise.resolve({ ok: r.status < 300, status: r.status, json: () => Promise.resolve(r.j) }); };
const tcEl = { isConnected: false, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, remove() { this.isConnected = false; }, set innerHTML(v) { this._h = v; }, get innerHTML() { return this._h; } };
const ctx = { fetch, toast: (t) => toasts.push(t), esc: (s) => String(s), osKind: () => "mac", instOpen: () => (ctx.opened = true), place: () => {}, setInterval: () => 0, setTimeout, clearTimeout, Date, JSON, Promise, encodeURIComponent,
  AbortController, localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => (store[k] = v) } };
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + "\nthis.t = { decide: tcDecide, reset: tcReset, refresh: tcRefresh, view: () => tcView, setEl: (e) => { tc = e; }, busy: () => tcBusy };", ctx);
const T = ctx.t; T.setEl(tcEl);
const H = (state, key_id = "VYKAX") => ({ ok: true, version: "1.2.2", credentials: { state, key_id } });
const ok = (n) => console.log("PASS " + n);

assert.equal(T.decide(null, null).kind, "hide"); assert.equal(T.decide({ ok: true, version: "1.2.1" }, null).kind, "old"); assert.match(T.decide({ ok: true }, null).text, /^Access Key revocation detected\. Reset the tunnel\.$/); ok("no tunnel: hidden; old tunnel (no credentials field): 'Access Key revocation detected. Reset the tunnel.'");
assert.equal(T.decide(H("ok"), { state: "active" }).kind, "ok"); ok("same account + active key: green");
assert.equal(T.decide(H("ok"), { state: "not_yours" }).action, "Reset tunnel"); assert.match(T.decide(H("ok"), { state: "not_yours" }).text, /different account/); ok("key of another account: alert + Reset");
assert.equal(T.decide(H("ok"), { state: "revoked" }).kind, "bad"); assert.equal(T.decide(H("revoked"), null).kind, "bad"); assert.equal(T.decide(H("invalid"), null).kind, "bad"); assert.equal(T.decide(H("none", ""), null).kind, "bad"); ok("revoked / invalid / missing key: alert");
assert.equal(T.decide(H("ok"), null).kind, "hide"); assert.equal(T.decide(H("unreachable"), null).kind, "grey"); ok("signed out of the portal: hidden; tunnel cannot reach portal: grey (never a false alarm)");

// Reset: pairing code from the portal, then POST to the LOCAL tunnel only (never sends the code anywhere else)
script = [{ status: 200, j: { code: "C".repeat(24) } }, { status: 200, j: { ok: true } }, { status: 200, j: H("ok", "VYKAN") }, { status: 200, j: { state: "active" } }];
await T.reset(); await new Promise((r) => setTimeout(r, 20));
assert.deepEqual(calls.slice(0, 2).map((c) => [c[0], c[1]]), [["/api/tunnel/pair/start", "POST"], ["http://127.0.0.1:8090/reset", "POST"]]);
assert.equal(JSON.parse(calls[1][2]).code, "C".repeat(24)); assert.ok(toasts.some((t) => /Tunnel reset/.test(t))); assert.equal(T.view().kind, "ok"); ok("Reset: code from portal -> local /reset -> re-check shows green");

// failures: toast + re-enable
calls.length = 0; script = [{ status: 401, j: {} }, { status: 200, j: H("revoked") }];
await T.reset(); await new Promise((r) => setTimeout(r, 20)); assert.ok(toasts.some((t) => /Could not reset/.test(t))); assert.equal(T.busy(), false); ok("Reset failure: friendly message, button usable again");

// auto reset: runs once when enabled and a problem is detected, then waits 5 minutes
calls.length = 0; store["vyomi.tunnelAutoReset"] = "1";
script = [{ status: 200, j: H("revoked") }, { status: 200, j: { code: "D".repeat(24) } }, { status: 200, j: { ok: true } }, { status: 200, j: H("ok", "VYKAN2") }, { status: 200, j: { state: "active" } }];
await T.refresh(); await new Promise((r) => setTimeout(r, 40));
assert.ok(calls.some((c) => c[0].endsWith("/reset")), "auto reset ran");
const n1 = calls.filter((c) => c[0].endsWith("/reset")).length; script = [{ status: 200, j: H("revoked") }]; await T.refresh(); await new Promise((r) => setTimeout(r, 20));
assert.equal(calls.filter((c) => c[0].endsWith("/reset")).length, n1, "not again within 5 minutes"); ok("auto-reset toggle: resets once, then rate-limited");
console.log("\nall passed");
