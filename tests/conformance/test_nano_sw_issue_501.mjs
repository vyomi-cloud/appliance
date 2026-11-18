/* Nano service worker (wasm/sw.js, the real file): a 501 "NotTranslatedYet" (action not simulated
 * yet) and an adapter 5xx are now REPORTED (they used to be silently returned); the response is
 * unchanged; resource ids never reach the report; repeats dedupe; the page-side fetch wrapper does
 * not double-report what the worker already reported; the 4 issue-reporter copies stay identical.
 *   node tests/conformance/test_nano_sw_issue_501.mjs */
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
let failed = false;
const check = (n, ok, x = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + x}`); failed ||= !ok; };
const swSrc = readFileSync(join(ROOT, "wasm/sw.js"), "utf8");

// ── real worker: an unsimulated EC2 action is reported as 501 NotTranslatedYet ─────────────
const listeners = {}, fetches = [];
const sw = {
  location: new URL("https://vyomi.cloud/nano/sw.js"),
  addEventListener: (t, f) => { listeners[t] = f; },
  skipWaiting() {}, clients: { claim() {}, matchAll: async () => [], get: async () => null },
  indexedDB: { open() { throw new Error("no idb"); } },
  // route fixtures (routes.json + catalogs) answer an empty list so route() finds no match and misses
  fetch: async (u, o) => { fetches.push({ u: String(u), o }); return new Response(/\.json(\?|$)/.test(String(u)) ? "[]" : "{}", { status: 200 }); },
  importScripts: (f) => vm.runInContext(readFileSync(join(ROOT, "wasm", f.replace("./", "")), "utf8"), ctx),
  Response, Request, URL, URLSearchParams, JSON, console, setTimeout, Promise, atob, escape, decodeURIComponent,
  registration: {},
};
sw.self = sw;
const ctx = vm.createContext(sw);
vm.runInContext(swSrc, ctx);
async function fire(path, method) {
  let p;
  listeners.fetch({ request: { url: "https://vyomi.cloud" + path, method, text: async () => "" }, respondWith: (x) => { p = x; } });
  return await p;
}
const reports = () => fetches.filter((f) => f.u.endsWith("/api/issues/report")).map((f) => JSON.parse(f.o.body).report);

const miss = "/nano/api/zzsvc/zz-not-simulated-yet/i-0abc123def4567890/reboot";
const r1 = await fire(miss, "POST");
await new Promise((r) => setTimeout(r, 30));
const b1 = await r1.json();
check("501 NotTranslatedYet is still the response, now tagged as already reported",
  r1.status === 501 && b1.code === "NotTranslatedYet" && r1.headers.get("X-Vyomi-Reported") === "1", JSON.stringify([r1.status, b1]));
const rep = reports();
check("the not-simulated 501 files exactly one report", rep.length === 1, JSON.stringify(fetches.map((f) => f.u)));
if (rep.length) {
  const r = rep[0], raw = JSON.stringify(r);
  check("report: kind http, status 501, code NotTranslatedYet, nano surface",
    r.kind === "http" && r.status === 501 && r.code === "NotTranslatedYet" && r.surface === "nano", raw);
  check("report: service from the path, action names the collection + verb (distinct per action)",
    r.cloud === "unknown" && r.service === "zzsvc" && /^POST zzsvc zz-not-simulated-yet reboot$/.test(r.action), raw);
  check("report: the instance id never leaves the browser", !raw.includes("i-0abc123def4567890"), raw);
}
await fire(miss, "POST");
await fire("/nano/api/zzsvc/zz-not-simulated-yet/i-0ffff111122223333/reboot", "POST");
await new Promise((r) => setTimeout(r, 30));
check("repeats (also on a different instance id) add no second report", reports().length === 1, String(reports().length));
await fire("/nano/api/zzsvc/zz-other-thing/i-0abc/start", "POST");
await new Promise((r) => setTimeout(r, 30));
check("a different unsimulated action files its own report", reports().length === 2, String(reports().length));

// ── regression: the adapter-5xx report must come BEFORE the early `return json(...h.status...)` ──
const iHttp = swSrc.indexOf("if (res && res.__http) {");
const iRet = swSrc.indexOf("return json(h.body === undefined ? null : h.body, h.status", iHttp);
const iRep = swSrc.indexOf("reportFailure(\"http\", apiPath, method, h.status", iHttp);
check("adapter 5xx is reported before the early return (it used to be dead code after it)", iHttp > 0 && iRep > iHttp && iRep < iRet, [iHttp, iRep, iRet].join(","));
check("the old unreachable report block is gone", !/res\.__http\.status >= 500/.test(swSrc));
check("explicit http_status 5xx adapter failures are reported too", /res\.ok === false && res\.http_status >= 500/.test(swSrc));
check("the exception path still reports", /reportFailure\("exception", apiPath/.test(swSrc));

// ── shouldReport rules in the shared reporter (offline + Nano) ──────────────────────────────
const irSrc = readFileSync(join(ROOT, "wasm/issue-reporter.js"), "utf8");
const rc = { location: { pathname: "/console/aws" }, fetch: async () => ({ ok: true, status: 200 }), console };
rc.self = rc; vm.createContext(rc); vm.runInContext(irSrc, rc);
const R = rc.VyomiIssueReporter;
check("shouldReport: 501 yes, 404 no, tier 403 no",
  R.shouldReport({ kind: "http", status: 501, code: "NotTranslatedYet" }) && !R.shouldReport({ kind: "http", status: 404 })
  && !R.shouldReport({ kind: "http", status: 403, code: "tier_locked" }));

// ── page-side wrapper does not double-report what the worker already reported ───────────────
function pageCtx(headers) {
  const calls = [];
  const c = {
    location: { pathname: "/console/aws" }, console, document: { readyState: "loading", addEventListener() {} },   // never boots the consent dialog
    addEventListener() {},
    fetch: async (u, o) => {
      calls.push(String(u));
      if (String(u).includes("/api/issues/")) return { ok: true, status: 200 };
      return { ok: false, status: 501, headers: { get: (k) => headers[k] || null }, clone() { return { json: async () => ({ code: "NotTranslatedYet" }) }; } };
    },
  };
  c.self = c; c.window = c; vm.createContext(c); vm.runInContext(irSrc, c);
  return { c, calls };
}
for (const [label, hdr, expectSent] of [["worker already reported (header present) -> no page report", { "X-Vyomi-Reported": "1" }, false],
                                        ["no worker report (offline appliance) -> page reports once", {}, true]]) {
  const { c, calls } = pageCtx(hdr);
  await c.fetch("/api/ec2/instances", { method: "POST" });
  await new Promise((r) => setTimeout(r, 30));
  check(label, calls.some((u) => u.includes("/api/issue")) === expectSent, JSON.stringify(calls));
}

// ── copies stay identical, cache-buster matches the file ───────────────────────────────────
import { createHash } from "node:crypto";
const copies = ["wasm/issue-reporter.js", ...["aws", "gcp", "azure"].map((c) => `wasm/v4/${c}/issue-reporter.js`)].map((f) => readFileSync(join(ROOT, f), "utf8"));
check("the four issue-reporter.js copies are byte-identical", copies.every((x) => x === copies[0]));
const h = createHash("sha256").update(readFileSync(join(ROOT, "wasm/issue-reporter.js"))).digest("hex").slice(0, 12);
check("each v4 page's ?v= cache-buster equals the file's sha256[:12]",
  ["aws", "gcp", "azure"].every((c) => readFileSync(join(ROOT, `wasm/v4/${c}/index.html`), "utf8").includes(`issue-reporter.js?v=${h}`)), h);
process.exit(failed ? 1 : 0);
