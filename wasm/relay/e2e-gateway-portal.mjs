/* Browser e2e on the LOCAL PORTAL (:8099 style) for the two Nano paths that e2e-gateway.mjs (nano-endpoint.html) does not cover:
 *   MODE=sw      console + service worker + in-page Pyodide (nano-boot.js)   -> wire calls are page fetches to <portal>/nano/_wire
 *   MODE=shared  SharedWorker relay (relay-shared-worker.js) started from a portal page, served to the outside via the local relay
 * In both: API + config + gateway created in the Nano GCP wire, a gateway call reaches a REAL local backend through the local relay's backend map (2xx),
 * an unmapped backend is refused, the API key is enforced, quota counts once, and an Eventarc trigger retries (tick-on-API-call) and dead-letters.
 *   PORTAL=http://localhost:8099 COOKIE=<cl_session value> MODE=sw|shared PLAYWRIGHT_BROWSERS_PATH=... NODE_PATH=<dir with playwright + ws> WS_PKG=<ws dir> node wasm/relay/e2e-gateway-portal.mjs
 * Use a portal started on a COPY of the DB (DATABASE_URL=...) and a throwaway CLOUDLEARN_STATE_DIR. */
import { createRequire } from "node:module";
import http from "node:http";
import net from "node:net";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";
const { chromium } = createRequire(import.meta.url)("playwright");
const HERE = dirname(fileURLToPath(import.meta.url));
const MODE = process.env.MODE || "sw", PORTAL = (process.env.PORTAL || "http://localhost:8099").replace(/\/$/, ""), COOKIE = process.env.COOKIE || "";
const free = () => new Promise((r) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => r(p)); }); });
let fails = 0; const check = (n, ok, x) => { console.log(`  [${ok ? "PASS" : "FAIL"}] [${MODE}] ${n}${ok ? "" : " :: " + String(x).slice(0, 400)}`); if (!ok) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const seen = [];
const backend = http.createServer((q, r) => { const c = []; q.on("data", (d) => c.push(d)); q.on("end", () => { seen.push({ m: q.method, u: q.url }); r.writeHead(200, { "content-type": "application/json", "x-real-backend": "yes" }); r.end(JSON.stringify({ hello: "from-real-backend", url: q.url })); }); });
await new Promise((r) => backend.listen(0, "127.0.0.1", r)); const BP = backend.address().port;
const home = mkdtempSync(join(tmpdir(), "gwpe2e-")); const portal = await startStubPortal({});
const RP = await free();
const relay = spawn(process.execPath, [join(HERE, "local-relay.mjs")], { env: { ...process.env, WS_PKG: process.env.WS_PKG || join(HERE, "../../relay-deps/ws"), VYOMI_HOME: home, HOME: home, VYOMI_PORTAL_URL: portal.url, VYOMI_ACCESS_KEY_ID: "VYKAFREE", VYOMI_SECRET_ACCESS_KEY: "free-secret",
  VYOMI_RELAY_AUTH: "1", RELAY_PORT: String(RP), RELAY_AMQP_PORT: "0", VYOMI_GATEWAY_BACKENDS_FILE: join(home, "gw.json"), VYOMI_GATEWAY_BACKENDS: `https://hello-e2e-uc.a.run.app=http://127.0.0.1:${BP}` } });
let rlog = ""; relay.stdout.on("data", (d) => rlog += d); relay.stderr.on("data", (d) => rlog += d);
for (let i = 0; i < 60 && !/health/.test(rlog); i++) await sleep(250);
const R = `http://127.0.0.1:${RP}`;
const done = async () => { try { relay.kill(); backend.close(); portal.close(); } catch {} process.exit(fails ? 1 : 0); };
const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext();
  await ctx.addInitScript((r) => { try { localStorage.setItem("nano_local_ext", r); } catch (_) {} }, R);
  if (COOKIE) await ctx.addCookies([{ name: "cl_session", value: COOKIE, url: PORTAL }]);
  const page = await ctx.newPage(); const perr = [];
  page.on("console", (m) => { if (/gateway|bridge|boot failed/i.test(m.text())) console.log("  [page]", m.text().slice(0, 200)); });
  page.on("pageerror", (e) => perr.push(e.message));
  let call;
  if (MODE === "sw") {
    await page.goto(`${PORTAL}/nano/v4/gcp/`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 300000, polling: 500 });
    check("console loaded on the portal, service worker controls it, Nano backend ready", true);
    call = (m, p, b, h) => page.evaluate(async ([m, p, b, h]) => { const r = await fetch("/nano/_wire" + p, { method: m, headers: { "content-type": "application/json", ...(h || {}) }, body: b === undefined ? undefined : JSON.stringify(b) });
      const t = await r.text(); let j; try { j = JSON.parse(t); } catch { j = t; } return { s: r.status, j, bk: r.headers.get("x-real-backend") }; }, [m, p, b, h]);
  } else {
    await page.goto(`${PORTAL}/nano/APPLIANCE_SYNC.json`, { waitUntil: "domcontentloaded" });
    await page.evaluate(([R, RP]) => { const w = new SharedWorker("/nano/relay/relay-shared-worker.js?v=4", { type: "module", name: "nano-relay-v4" }); w.port.start(); window.__w = w;
      w.port.postMessage({ type: "start", session: "e2e-" + Math.random().toString(36).slice(2), noIdle: true, config: { localHealth: R + "/health", localWs: `ws://127.0.0.1:${RP}/register`, localExternal: R, cloudWsBase: "wss://relay.invalid/register", cloudExternal: "https://relay.invalid" } }); }, [R, RP]);
    let tab = false; for (let i = 0; i < 300 && !tab; i++) { try { tab = (await (await fetch(R + "/health")).json()).tab; } catch {} if (!tab) await sleep(1000); }
    check("SharedWorker booted (Pyodide + cores) and registered with the local relay", tab, rlog.slice(-300));
    if (!tab) await done();
    await sleep(3000);
    call = async (m, p, b, h) => { const r = await fetch(R + p, { method: m, headers: { "content-type": "application/json", ...(h || {}) }, body: b === undefined ? undefined : JSON.stringify(b) }); const t = await r.text(); let j; try { j = JSON.parse(t); } catch { j = t; } return { s: r.status, j, bk: r.headers.get("x-real-backend") }; };
  }
  const N = Date.now() % 100000, P = "/v1/projects/nano-project/locations", api = `e2eapi${N}`, gw = `gw${N}`;
  const spec = { swagger: "2.0", info: { title: "t", version: "1" }, "x-google-backend": { address: "https://hello-e2e-uc.a.run.app", path_translation: "APPEND_PATH_TO_ADDRESS" },
    "x-google-management": { metrics: [{ name: "reads", valueType: "INT64", metricKind: "DELTA" }], quota: { limits: [{ name: "rl", metric: "reads", unit: "1/min/{project}", values: { STANDARD: 2 } }] } },
    securityDefinitions: { key: { type: "apiKey", name: "key", in: "query" } },
    paths: { "/hello": { get: { operationId: "hello", responses: { 200: { description: "ok" } } } },
             "/guarded": { get: { operationId: "guarded", security: [{ key: [] }], "x-google-quota": { metricCosts: { reads: 1 } }, responses: { 200: { description: "ok" } } } },
             "/other": { get: { operationId: "other", "x-google-backend": { address: "https://unmapped-e2e.run.app", path_translation: "APPEND_PATH_TO_ADDRESS" }, responses: { 200: { description: "ok" } } } } } };
  await call("POST", `${P}/global/apis?apiId=${api}`, {});
  let r = await call("POST", `${P}/global/apis/${api}/configs?apiConfigId=c1`, { openapiDocuments: [{ document: { path: "o.json", contents: Buffer.from(JSON.stringify(spec)).toString("base64") } }] });
  check("API + config created in the Nano GCP wire", r.s === 200, JSON.stringify(r.j));
  r = await call("POST", `${P}/us-central1/gateways?gatewayId=${gw}`, { apiConfig: `projects/nano-project/locations/global/apis/${api}/configs/c1` });
  check("gateway created", r.s === 200, JSON.stringify(r.j));
  await call("POST", "/v2/projects/nano-project/locations/global/keys?keyId=k1", { displayName: "k" });
  const KEY = (await call("GET", "/v2/projects/nano-project/locations/global/keys/k1/keyString")).j.keyString;
  r = await call("GET", `/gcpgw/${gw}/hello?x=1`);
  check("mapped backend: a REAL 200 comes back through the Nano gateway", r.s === 200 && r.j.hello === "from-real-backend" && r.bk === "yes", `${r.s} ${JSON.stringify(r.j)}`);
  check("backend saw the translated path + query", seen.some((s) => s.u === "/hello?x=1"), JSON.stringify(seen));
  r = await call("GET", `/gcpgw/${gw}/guarded`);
  check("no API key -> 401 and the backend is not called", r.s === 401 && !seen.some((s) => s.u.startsWith("/guarded")), r.s);
  const n0 = seen.length, codes = []; for (let i = 0; i < 3; i++) codes.push((await call("GET", `/gcpgw/${gw}/guarded?key=${KEY}`)).s);
  check("quota counted once per request across the async hop (200,200,429)", JSON.stringify(codes) === "[200,200,429]" && seen.length === n0 + 2, JSON.stringify(codes) + " " + (seen.length - n0));
  r = await call("GET", `/gcpgw/${gw}/other`);
  check("unmapped backend REFUSED (503 naming vyomi-tunnel gateway-backend)", r.s === 503 && /gateway-backend/.test(JSON.stringify(r.j)), `${r.s} ${JSON.stringify(r.j)}`);
  check("relay logged the egress calls", /gw-egress/.test(rlog));

  // ---- Eventarc with retries in Nano: failing http destination -> RETRYING -> (tick on later API calls) -> DEAD_LETTERED to a Pub/Sub topic
  const PR = "nano-project", L = "us-central1", dlq = `dlq${N}`, tid = `t${N}`, bkt = `evk${N}`;
  r = await call("POST", `/v1/projects/${PR}/topics/${dlq}`.replace("/topics", "/topics"), {}); // Pub/Sub create topic (PUT in real API)
  if (r.s >= 400) r = await call("PUT", `/v1/projects/${PR}/topics/${dlq}`, {});
  check("dead-letter Pub/Sub topic created", r.s === 200, `${r.s} ${JSON.stringify(r.j)}`);
  r = await call("POST", `/v1/projects/${PR}/locations/${L}/triggers?triggerId=${tid}`, { eventFilters: [{ attribute: "type", value: "google.cloud.pubsub.topic.v1.messagePublished" }],
    destination: { httpEndpoint: { uri: "https://sink-e2e.invalid/hook" } }, retryPolicy: { maxAttempts: 3, minRetryDelay: "1s", maxRetryDelay: "2s" }, deadLetterTopic: `projects/${PR}/topics/${dlq}` });
  check("Eventarc trigger (http destination, retryPolicy, deadLetterTopic) created", r.s === 200, `${r.s} ${JSON.stringify(r.j)}`);
  const topic = r.j.response && r.j.response.transport && r.j.response.transport.pubsub && r.j.response.transport.pubsub.topic;
  r = await call("POST", `/v1/${topic}:publish`, { messages: [{ data: Buffer.from("hi").toString("base64") }] });
  check("event published", r.s === 200, `${r.s} ${JSON.stringify(r.j)}`);
  const dl = async () => (await call("GET", `${P}/${L}/triggers/${tid}/deliveries`)).j;
  let d = await dl(); let it = (d.deliveries || [])[0] || {};
  check("first attempt failed, delivery is RETRYING with a next-attempt time", it.status === "RETRYING" && it.attemptCount === 1 && !!it.nextAttemptTime, JSON.stringify(it).slice(0, 300));
  let last = it; for (let i = 0; i < 12 && last.status !== "DEAD_LETTERED"; i++) { await sleep(1500); last = ((await dl()).deliveries || [])[0] || {}; }
  check("retries advanced by API-call ticks (no timer) and the event was DEAD_LETTERED after maxAttempts", last.status === "DEAD_LETTERED" && last.attemptCount === 3, JSON.stringify(last).slice(0, 400));
  check("attempt history recorded (3 attempts)", (last.attempts || []).length === 3, JSON.stringify(last.attempts));
  console.log("  [info] http destination attempt error in Nano:", JSON.stringify((last.attempts || [])[0] || {}).slice(0, 200));
  check("no page errors", perr.length === 0, perr.join(" | "));
} catch (e) { check("e2e ran", false, e && e.stack || e); }
await browser.close(); console.log(fails ? "\nFAIL" : `\nPASS — Nano gateway + eventarc e2e (${MODE})`); await done();
