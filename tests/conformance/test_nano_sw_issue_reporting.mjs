/* Nano service worker (wasm/sw.js, the real file): an unhandled exception while serving /api/*
 * files ONE scrubbed report to the portal; /api/issues/* is forwarded to the portal with the
 * session; reports from the SW are deduped. node tests/conformance/test_nano_sw_issue_reporting.mjs */
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
let failed = false;
const check = (n, ok, x = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " " + x}`); failed ||= !ok; };

const listeners = {}, fetches = [];
const sw = {
  location: new URL("https://vyomi.cloud/nano/sw.js"),
  addEventListener: (t, f) => { listeners[t] = f; },
  skipWaiting() {}, clients: { claim() {}, matchAll: async () => [], get: async () => null },
  indexedDB: { open() { throw new Error("no idb"); } },
  fetch: async (u, o) => { fetches.push({ u: String(u), o }); return new Response("{}", { status: 200 }); },
  importScripts: (f) => vm.runInContext(readFileSync(join(ROOT, "wasm", f.replace("./", "")), "utf8"), ctx),
  Response, Request, URL, URLSearchParams, JSON, console, setTimeout, Promise, atob, escape, decodeURIComponent,
  registration: {},
};
sw.self = sw;
const ctx = vm.createContext(sw);
vm.runInContext(readFileSync(join(ROOT, "wasm/sw.js"), "utf8"), ctx);

async function fire(path, method, bodyFn) {
  let p;
  const req = { url: "https://vyomi.cloud" + path, method, text: bodyFn || (async () => "") };
  listeners.fetch({ request: req, respondWith: (x) => { p = x; } });
  return await p;
}

const r1 = await fire("/nano/api/issues/settings", "GET");
check("/api/issues/* is forwarded to the portal (not the in-browser backend)",
  fetches.length === 1 && fetches[0].u === "https://vyomi.cloud/api/issues/settings" && fetches[0].o.credentials === "include" && r1.status === 200, JSON.stringify(fetches));

fetches.length = 0;
const boom = async () => { throw new Error("engine blew up for bucket 'payroll-2026' at 10.0.0.9"); };
const r2 = await fire("/nano/api/aws/s3/buckets", "POST", boom);
await new Promise((r) => setTimeout(r, 20));
check("the failing request still answers 500", r2.status === 500);
const rep = fetches.filter((f) => f.u.endsWith("/api/issues/report"));
check("exactly one report filed to the portal", rep.length === 1, JSON.stringify(fetches));
if (rep.length) {
  const body = JSON.parse(rep[0].o.body);
  check("report is scrubbed and tagged nano", body.report.surface === "nano" && body.report.kind === "exception" && body.report.service === "s3"
    && !rep[0].o.body.includes("payroll-2026") && !rep[0].o.body.includes("10.0.0.9"), rep[0].o.body);
}
await fire("/nano/api/aws/s3/buckets", "POST", boom);
await new Promise((r) => setTimeout(r, 20));
check("a repeat adds no second report", fetches.filter((f) => f.u.endsWith("/api/issues/report")).length === 1);
process.exit(failed ? 1 : 0);
