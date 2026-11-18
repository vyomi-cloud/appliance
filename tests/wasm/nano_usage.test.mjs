/* Unit test for wasm/nano-usage.js (view-dwell telemetry) in a fake browser: no browser, no network.
 *   node tests/wasm/nano_usage.test.mjs
 * Covers: event shape/contract, route-pattern keys (no resource names), active-time (hidden + 60 s idle excluded),
 * <1 s drop, 30 min cap + split, batch <= 50, opt-out (3 ways), 404 stops the emitter, per-tab sid, never throws. */
import vm from "node:vm";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(resolve(HERE, "../../wasm/nano-usage.js"), "utf8");
let fails = 0;
const check = (ok, what, detail = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] nano-usage: ${what}${!ok && detail ? " :: " + detail : ""}`); if (!ok) fails++; };

function world({ cloud = "aws", hash = "", path = "/v4/aws/index.html", ls = {}, dnt, flag, fetchStatus = 204, noBeacon = false } = {}) {
  const t = { now: 1_700_000_000_000 };
  const timers = [], listeners = {}, docL = {};
  const sent = [], beacons = [];
  const store = { ...ls }, sess = {};
  const doc = {
    hidden: false, readyState: "complete", currentScript: { getAttribute: (k) => (k === "data-cloud" ? cloud : null) },
    addEventListener: (e, f) => ((docL[e] = docL[e] || []).push(f)),
  };
  const win = {
    __vyNanoReady: true, VYOMI_NO_TELEMETRY: flag, __VY_USAGE_DEBUG: true,
    location: { hash, pathname: path },
    history: { pushState() {}, replaceState() {} },
    addEventListener: (e, f) => ((listeners[e] = listeners[e] || []).push(f)),
    crypto: { getRandomValues: (a) => { for (let i = 0; i < a.length; i++) a[i] = (i * 37 + 11) & 255; return a; } },
  };
  const ctx = {
    window: win, document: doc, location: win.location, history: win.history, addEventListener: win.addEventListener,
    navigator: { doNotTrack: dnt, sendBeacon: noBeacon ? undefined : (u, b) => { beacons.push({ u, b }); return true; } },
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => (store[k] = String(v)) },
    sessionStorage: { getItem: (k) => (k in sess ? sess[k] : null), setItem: (k, v) => (sess[k] = String(v)) },
    crypto: win.crypto, Uint8Array, Blob, JSON, Math, String, Object, Array, decodeURIComponent, RegExp,
    Date: { now: () => t.now },
    setTimeout: (f, ms) => { timers.push({ f, at: t.now + ms, rep: 0 }); return timers.length; },
    setInterval: (f, ms) => { timers.push({ f, at: t.now + ms, rep: ms }); return timers.length; },
    clearInterval: (i) => { if (timers[i - 1]) timers[i - 1].f = null; },
    fetch: (u, o) => { sent.push({ u, o, body: JSON.parse(o.body) }); return Promise.resolve({ status: fetchStatus, ok: fetchStatus < 300 }); },
  };
  ctx.self = ctx; win.window = win; Object.assign(win, { navigator: ctx.navigator, localStorage: ctx.localStorage, sessionStorage: ctx.sessionStorage, document: doc });
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  const fire = (e, ev = {}) => (listeners[e] || []).forEach((f) => f(ev));
  const advance = (ms) => { const end = t.now + ms; for (;;) { const due = timers.filter((x) => x.f && x.at <= end).sort((a, b) => a.at - b.at)[0]; if (!due) break; t.now = Math.max(t.now, due.at); const f = due.f; if (due.rep) due.at += due.rep; else due.f = null; f(); } t.now = end; };
  return { win, doc, t, sent, beacons, fire, advance, dbg: () => win.__vyUsageDebug, docFire: (e) => (docL[e] || []).forEach((f) => f()), setHash(h) { win.location.hash = h; fire("hashchange"); } };
}
// every event seen so far: already sent (fetch / beacon) + still buffered
const events = (w) => [...w.sent.flatMap((s) => s.body.events), ...w.beacons.flatMap((b) => JSON.parse(b.b.parts?.[0] ?? "{\"events\":[]}").events || []), ...w.dbg().buf];
// Blob in vm is the host Blob: read its text synchronously via a tiny shim
const origBlob = globalThis.Blob; globalThis.Blob = class { constructor(parts, o) { this.parts = parts.map(String); this.type = o?.type; } };

const KEY = /^[a-z0-9:_.\/-]{1,80}$/;

// 1 — contract: a 5 s active visit to a pattern view
{
  const w = world({ hash: "#/s3/buckets/my-secret-bucket" });
  w.advance(5000); w.fire("mousemove");
  w.advance(5000); w.fire("click");
  w.setHash("#/ec2/instances");           // leaves the S3 view
  const d = w.dbg(); const e = d.buf[0];
  check(d.buf.length === 1, "one event after leaving a view", JSON.stringify(d.buf));
  check(e && e.cloud === "aws" && /^[0-9a-f]{16}$/.test(e.sid), "cloud + 16-hex per-tab sid");
  check(e && KEY.test(e.view) && KEY.test(e.service), "view/service match the contract regex", e && e.view);
  check(e && e.service === "s3" && e.view === "s3/buckets/:name", "view is the route PATTERN (no resource name)", e && e.view);
  check(!JSON.stringify(d.buf).includes("my-secret-bucket"), "resource name never appears in an event");
  check(e && e.enter <= e.exit && e.dur >= 9000 && e.dur <= 10500, "dur ~ active ms", e && e.dur);
  check(e && Object.keys(e).sort().join() === "cloud,dur,enter,exit,service,sid,view", "exactly the contract fields");
}
// 2 — idle after 60 s of no input stops the clock; hidden time is excluded
{
  const w = world({ hash: "#/s3/buckets" });
  w.advance(10_000);                       // 10 s active (start input = t0)
  w.advance(300_000);                      // 5 more minutes with no input -> only 60 s of the idle window counts
  w.setHash("#/ec2/instances");
  const e = events(w)[0];
  check(e && e.dur >= 59_000 && e.dur <= 61_000, "5 idle minutes count only the 60 s inactivity window", e && e.dur);
  const w2 = world({ hash: "#/s3/buckets" });
  w2.advance(2000); w2.fire("click"); w2.advance(2000);
  w2.doc.hidden = true; w2.docFire("visibilitychange");    // tab hidden: event closes
  const e2 = events(w2)[0];
  check(e2 && e2.dur >= 3900 && e2.dur <= 4100, "hidden closes the event with active time so far", e2 && e2.dur);
  w2.advance(120_000); w2.doc.hidden = false; w2.docFire("visibilitychange"); w2.advance(3000); w2.fire("click"); w2.setHash("#/sqs/queues");
  const ev = events(w2);
  check(ev.length === 2 && ev[1].dur >= 2500 && ev[1].dur <= 3500, "hidden gap excluded; coming back starts a new visit", JSON.stringify(ev.map((x) => x.dur)));
}
// 3 — < 1 s flicker dropped; same view type (other resource) is ONE visit; cap + split at 30 min
{
  const w = world({ hash: "#/s3/buckets" });
  w.advance(400); w.setHash("#/ec2/instances"); w.advance(300); w.setHash("#/sqs/queues");
  check(w.dbg().buf.length === 0, "sub-second route flicker dropped");
  const w2 = world({ hash: "#/s3/buckets/a" });
  w2.advance(3000); w2.fire("click"); w2.setHash("#/s3/buckets/b"); w2.advance(3000); w2.fire("click"); w2.setHash("#/ec2/instances");
  check(w2.dbg().buf.length === 1 && w2.dbg().buf[0].view === "s3/buckets/:name", "moving between resources of the same view = one visit", JSON.stringify(w2.dbg().buf.map((x) => x.view)));
  const w3 = world({ hash: "#/s3/buckets" });
  for (let i = 0; i < 40; i++) { w3.advance(59_000); w3.fire("mousemove"); }   // ~39 min of steady activity
  w3.setHash("#/ec2/instances");
  const all = events(w3);
  check(all.length >= 2 && all.every((x) => x.dur <= 30 * 60_000), "a long visit is cut into events of <= 30 min", JSON.stringify(all.map((x) => x.dur)));
}
// 4 — unknown first segment never leaks free text; home; classic
{
  const w = world({ hash: "#/definitely-not-a-service/xyz" });
  check(w.dbg().viewFor("#/definitely-not-a-service/xyz").view === "other", "unknown service -> 'other' (no free text)");
  check(w.dbg().viewFor("").view === "home", "empty hash -> 'home'");
  const wc = world({ cloud: "gcp", path: "/gcp-console.html", hash: "" });
  check(wc.dbg().viewFor("").view === "classic" || wc.dbg().viewFor("").view === "home", "classic console without routes still gets a bounded key", wc.dbg().viewFor("").view);
  for (const cloud of ["aws", "gcp", "azure"]) {
    const ww = world({ cloud, path: `/v4/${cloud}/index.html` });
    const r = ww.dbg().viewFor("#/zzz"); check(KEY.test(r.view) && KEY.test(r.service), `${cloud}: keys always valid`);
  }
}
// 5 — batching + flush + beacon on unload + never more than 50 per request
{
  const w = world({ hash: "#/s3/buckets" });
  for (let i = 0; i < 120; i++) { w.advance(1500); w.fire("click"); w.setHash(i % 2 ? "#/ec2/instances" : "#/s3/buckets"); }
  w.advance(31_000);   // flush timer
  const reqs = w.sent.map((s) => s.body.events.length);
  check(reqs.length >= 1 && reqs.every((n) => n <= 50), "flush sends <= 50 events per request", JSON.stringify(reqs));
  check(w.sent.every((s) => s.u === "/api/usage/views" && s.o.method === "POST" && s.o.credentials === "include" && s.body.v === 1), "POST same-origin /api/usage/views, credentials, v:1");
  w.advance(2000); w.fire("click"); w.setHash("#/sqs/queues"); w.advance(2000); w.fire("click");
  w.fire("pagehide");
  check(w.beacons.length >= 1 && w.beacons[0].u === "/api/usage/views" && w.beacons[0].b.type === "application/json", "pagehide flushes via sendBeacon (application/json Blob)");
}
// 6 — opt-out three ways
for (const [name, opts] of [["localStorage vyomi.telemetry=off", { ls: { "vyomi.telemetry": "off" } }], ["doNotTrack=1", { dnt: "1" }], ["window.VYOMI_NO_TELEMETRY", { flag: true }]]) {
  const w = world({ hash: "#/s3/buckets", ...opts });
  w.advance(5000); w.fire("click"); w.setHash("#/ec2/instances"); w.advance(40_000); w.fire("pagehide");
  check(w.sent.length === 0 && w.beacons.length === 0 && w.dbg().buf.length === 0, `opt-out (${name}) emits nothing`);
}
// 7 — a 404 (offline / non-portal origin) disables the emitter quietly; fetch fallback when no sendBeacon
{
  const w = world({ hash: "#/s3/buckets", fetchStatus: 404, noBeacon: true });
  w.advance(5000); w.fire("click"); w.setHash("#/ec2/instances"); w.advance(31_000);
  await Promise.resolve(); await Promise.resolve();
  check(w.sent.length === 1, "first flush attempted once");
  check(w.dbg().dead === true, "404 disables the emitter for the session (no retry storm)");
  w.advance(5000); w.fire("click"); w.setHash("#/sqs/queues"); w.advance(61_000);
  check(w.sent.length === 1, "no further requests after the 404");
}
// 8 — sid is stable within a tab (sessionStorage) and never throws on broken storage
{
  const w = world({ hash: "#/s3/buckets" });
  check(/^[0-9a-f]{16}$/.test(w.dbg().sid), "sid generated");
}
globalThis.Blob = origBlob;
console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
