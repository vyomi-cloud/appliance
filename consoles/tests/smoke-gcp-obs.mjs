/* Smoke: GCP Trace explorer latency percentiles/heatmap (from OTLP spans), Memorystore INFO series, Ops Agent host metrics.
 *   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-gcp-obs.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); let j = null; try { j = t ? JSON.parse(t) : null; } catch {} return { status: r.status, body: j };
}, [m, url, body]);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
const ready = async () => { if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 }); };
/* Re-open the current page. Nano keeps request telemetry (OTLP spans, request counters) in the in-page recorder only - it does
 * not survive a document reload - so on Nano re-navigate inside the SPA instead of reloading. */
const refresh = async () => { if (process.env.NANO) { const u = pg.url(); await pg.goto(UI + "#/"); await pg.waitForTimeout(300); await pg.goto(u); } else await refresh(); };
await ready();
const project = await pg.evaluate(() => (window.__vyomiProject || localStorage.getItem("vyomi.gcp.project") || "vyomi-project"));
// ── Trace explorer
await pg.goto(`${UI}#/monitoring/trace-explorer`); await pg.waitForTimeout(1500);
ok("idle: percentiles 0 and honest empty heatmap", (await pg.getByTestId("trace-heatmap-empty").count()) === 1);
const now = Date.now() * 1e6;
const spans = [5, 8, 12, 20, 40, 90, 250].map((ms, i) => ({ traceId: String(i + 1).padStart(32, "a"), spanId: String(i + 1).padStart(16, "b"), name: "op" + i, kind: 2, startTimeUnixNano: String(now - ms * 1e6 - i * 2e9), endTimeUnixNano: String(now - i * 2e9), status: { code: 0 } }));
await call("POST", `${WIRE}/_obs/v1/traces`, { resourceSpans: [{ resource: { attributes: [{ key: "service.name", value: { stringValue: "checkout" } }] }, scopeSpans: [{ spans }] }] });
await refresh(); await pg.waitForTimeout(2000);
ok("percentiles shown from 7 spans", (await pg.getByTestId("trace-spans").innerText()).trim() === "7");
ok("p99 is the slow span", Number((await pg.getByTestId("trace-p99").innerText()).trim()) >= 200);
ok("heatmap drawn", (await pg.getByTestId("trace-heatmap").count()) === 1);
// ── Ops Agent + Memorystore via the push endpoints (what a runtime does)
const blob = (rx, tx, cpu, rb, wb) => `Inter-|\n face |\n  eth0: ${rx} ${rx / 100} 0 0 0 0 0 0 ${tx} ${tx / 100} 0 0 0 0 0 0\n---CPU\nusage_usec ${cpu}\n---IO\n254:0 rbytes=${rb} wbytes=${wb} rios=1 wios=1\n`;
const t0 = Date.now() / 1000;
const zone = "us-central1-a", vm = `obsvm${Date.now() % 100000}`;
const mk = await call("POST", `${WIRE}/compute/v1/projects/${project}/zones/${zone}/instances`, { name: vm, machineType: `zones/${zone}/machineTypes/e2-micro`, disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }], networkInterfaces: [{ network: "global/networks/default" }] });
const inst = (await call("GET", `${WIRE}/compute/v1/projects/${project}/zones/${zone}/instances/${vm}`)).body;
ok("VM created over the compute wire", mk.status < 300 && !!inst?.id, JSON.stringify(mk.body).slice(0, 200));
const iid = String(inst?.id || vm);
await call("POST", `${WIRE}/_obs/gce-counters`, { project, instance: iid, zone, ts: t0 - 20, counters: blob(1000, 500, 1_000_000, 0, 0) });
await call("POST", `${WIRE}/_obs/gce-counters`, { project, instance: iid, zone, ts: t0, counters: blob(5000, 2500, 2_000_000, 4096, 8192) });
await pg.goto(`${UI}#/compute/instances/${zone}/${vm}`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Observability" }).click();
await pg.getByTestId("opsagent-row").first().waitFor({ timeout: 15000 }); await pg.waitForTimeout(3000);
const rows = await pg.getByTestId("opsagent-row").allInnerTexts();
ok("Ops Agent CPU sample shown (5.0 %)", rows.some((r) => /CPU utilization/.test(r) && /5/.test(r) && !/No samples/.test(r)), rows.join("|"));
ok("Ops Agent disk write sample shown", rows.some((r) => /Disk write/.test(r) && /8192/.test(r)), rows.join("|"));
// ── Memorystore: INFO pushed by the Valkey collector
const rid = `obsredis${Date.now() % 100000}`;
const rc = await call("POST", `${WIRE}/v1/projects/${project}/locations/us-central1/instances?instanceId=${rid}`, { tier: "BASIC", memorySizeGb: 1, displayName: rid });
await pg.waitForTimeout(500);
const INFO = "# Clients\r\nconnected_clients:4\r\n# Memory\r\nused_memory:2097152\r\n# Stats\r\ntotal_commands_processed:100\r\nkeyspace_hits:30\r\nkeyspace_misses:10\r\n";
await call("POST", `${WIRE}/_obs/redis-info`, { project, instance: rid, region: "us-central1", info: INFO });
await pg.goto(`${UI}#/memorystore/instances/us-central1/${rid}/overview`); await pg.waitForTimeout(3000);
const txt = await pg.locator("body").innerText();
ok("Memorystore shows measured clients/memory/hit ratio", /2\.0 MiB/.test(txt) && /0\.75/.test(txt), String(rc.status));
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
