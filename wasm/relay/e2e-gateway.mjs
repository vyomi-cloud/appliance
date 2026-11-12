/* Browser e2e: a Nano API Gateway reaches a REAL local backend through the local relay (docs/architecture/v4.0/GATEWAY-NANO-FORWARDING.md).
 *   curl-like client -> local relay -> Nano tab (Pyodide: AwsWireRouter.ahandle -> plan -> awaited JS bridge) -> relay /gw-egress -> local backend
 * Starts: a static server over wasm/, the local relay (signed-in stub portal), a backend. Chromium via Playwright.
 *   PLAYWRIGHT_BROWSERS_PATH=... NODE_PATH=<dir with playwright + ws> WS_PKG=<ws dir> node wasm/relay/e2e-gateway.mjs
 * Needs network for Pyodide (jsdelivr) unless wasm/vendor/pyodide exists.
 */
import { createRequire } from "node:module";
import http from "node:http";
import net from "node:net";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, extname, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { startStubPortal } from "./test-fixtures/stub-portal.mjs";
const { chromium } = createRequire(import.meta.url)("playwright");
const HERE = dirname(fileURLToPath(import.meta.url)), WASM = resolve(HERE, "..");
const free = () => new Promise((r) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => r(p)); }); });
let fails = 0; const check = (n, ok, x) => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${n}${ok ? "" : " :: " + String(x).slice(0, 300)}`); if (!ok) fails++; };
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".py": "text/plain", ".json": "application/json", ".wasm": "application/wasm" };
const stat = http.createServer((q, r) => { const p = join(WASM, decodeURIComponent(new URL(q.url, "http://x").pathname)); if (!p.startsWith(WASM) || !existsSync(p)) { r.writeHead(404); return r.end(); }
  try { const b = readFileSync(p); r.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" }); r.end(b); } catch { r.writeHead(404); r.end(); } });
await new Promise((r) => stat.listen(0, "127.0.0.1", r)); const SP = stat.address().port;
const seen = [];
const backend = http.createServer((q, r) => { const c = []; q.on("data", (d) => c.push(d)); q.on("end", () => { seen.push({ m: q.method, u: q.url, h: q.headers, b: Buffer.concat(c).toString() }); r.writeHead(200, { "content-type": "application/json", "x-real-backend": "yes" }); r.end(JSON.stringify({ hello: "from-real-backend", url: q.url })); }); });
await new Promise((r) => backend.listen(0, "127.0.0.1", r)); const BP = backend.address().port;
const home = mkdtempSync(join(tmpdir(), "gwe2e-")); const portal = await startStubPortal({});
const RP = await free();
const relay = spawn(process.execPath, [join(HERE, "local-relay.mjs")], { env: { ...process.env, WS_PKG: process.env.WS_PKG || join(HERE, "../../relay-deps/ws"), VYOMI_HOME: home, HOME: home, VYOMI_PORTAL_URL: portal.url, VYOMI_ACCESS_KEY_ID: "VYKAFREE", VYOMI_SECRET_ACCESS_KEY: "free-secret",
  VYOMI_RELAY_AUTH: "1", RELAY_PORT: String(RP), RELAY_AMQP_PORT: "0", VYOMI_GATEWAY_BACKENDS_FILE: join(home, "gw.json"), VYOMI_GATEWAY_BACKENDS: `https://hello-e2e-uc.a.run.app=http://127.0.0.1:${BP},https://aws-e2e.example.com=http://127.0.0.1:${BP},https://azure-e2e.example.net=http://127.0.0.1:${BP}` } });
let rlog = ""; relay.stdout.on("data", (d) => rlog += d); relay.stderr.on("data", (d) => rlog += d);
for (let i = 0; i < 60 && !/health/.test(rlog); i++) await new Promise((r) => setTimeout(r, 250));
const R = `http://127.0.0.1:${RP}`;
const done = async () => { try { relay.kill(); stat.close(); backend.close(); portal.close(); } catch {} process.exit(fails ? 1 : 0); };
const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext(); await ctx.addInitScript((r) => { try { localStorage.setItem("nano_local_ext", r); } catch (_) {} }, R);
  const page = await ctx.newPage(); page.on("console", (m) => { if (/error|gateway|bridge/i.test(m.text())) console.log("  [page]", m.text().slice(0, 200)); });
  await page.goto(`http://localhost:${SP}/relay/nano-endpoint.html?relay=ws://127.0.0.1:${RP}/register&core=/core`);
  let tab = false; for (let i = 0; i < 240 && !tab; i++) { tab = (await (await fetch(R + "/health")).json()).tab; if (!tab) await new Promise((r) => setTimeout(r, 1000)); }
  check("Nano tab booted (Pyodide + cores) and registered with the local relay", tab, rlog.slice(-300));
  if (!tab) await done();
  await new Promise((r) => setTimeout(r, 3000));          // let the endpoint's gateway bridge import finish
  const call = async (m, p, b) => { const r = await fetch(R + p, { method: m, headers: { "content-type": "application/json" }, body: b === undefined ? undefined : JSON.stringify(b) }); const t = await r.text(); let j; try { j = JSON.parse(t); } catch { j = t; } return { s: r.status, j, h: r.headers }; };
  const P = "/v1/projects/nano-project/locations";
  const spec = { swagger: "2.0", info: { title: "t", version: "1" }, "x-google-backend": { address: "https://hello-e2e-uc.a.run.app", path_translation: "APPEND_PATH_TO_ADDRESS" },
    "x-google-management": { metrics: [{ name: "reads", valueType: "INT64", metricKind: "DELTA" }], quota: { limits: [{ name: "rl", metric: "reads", unit: "1/min/{project}", values: { STANDARD: 2 } }] } },
    securityDefinitions: { key: { type: "apiKey", name: "key", in: "query" } },
    paths: { "/hello": { get: { operationId: "hello", responses: { 200: { description: "ok" } } } },
             "/guarded": { get: { operationId: "guarded", security: [{ key: [] }], "x-google-quota": { metricCosts: { reads: 1 } }, responses: { 200: { description: "ok" } } } },
             "/other": { get: { operationId: "other", "x-google-backend": { address: "https://unmapped-e2e.run.app", path_translation: "APPEND_PATH_TO_ADDRESS" }, responses: { 200: { description: "ok" } } } } } };
  await call("POST", P + "/global/apis?apiId=e2eapi", {});
  let r = await call("POST", P + "/global/apis/e2eapi/configs?apiConfigId=c1", { openapiDocuments: [{ document: { path: "o.json", contents: Buffer.from(JSON.stringify(spec)).toString("base64") } }] });
  check("API + config created in the Nano tab", r.s === 200, JSON.stringify(r.j));
  r = await call("POST", P + "/us-central1/gateways?gatewayId=gw1", { apiConfig: "projects/nano-project/locations/global/apis/e2eapi/configs/c1" });
  check("gateway created", r.s === 200, JSON.stringify(r.j));
  await call("POST", "/v2/projects/nano-project/locations/global/keys?keyId=k1", { displayName: "k" });
  const KEY = (await call("GET", "/v2/projects/nano-project/locations/global/keys/k1/keyString")).j.keyString;
  r = await call("GET", "/gcpgw/gw1/hello?x=1");
  check("mapped backend: a REAL 200 comes back through the Nano gateway", r.s === 200 && r.j.hello === "from-real-backend" && r.h.get("x-real-backend") === "yes", `${r.s} ${JSON.stringify(r.j)}`);
  check("backend saw the translated path + query", seen.some((s) => s.u === "/hello?x=1"), JSON.stringify(seen));
  r = await call("GET", "/gcpgw/gw1/guarded");
  check("auth still enforced in the tab: no key -> 401 and the backend is not called", r.s === 401 && !seen.some((s) => s.u.startsWith("/guarded")), r.s);
  const n0 = seen.length; const codes = []; for (let i = 0; i < 3; i++) codes.push((await call("GET", `/gcpgw/gw1/guarded?key=${KEY}`)).s);
  check("quota counted once per request across the async hop (200,200,429)", JSON.stringify(codes) === "[200,200,429]" && seen.length === n0 + 2, JSON.stringify(codes) + " " + (seen.length - n0));
  r = await call("GET", "/gcpgw/gw1/other");
  check("unmapped backend is REFUSED (503 naming vyomi-tunnel gateway-backend)", r.s === 503 && /gateway-backend/.test(JSON.stringify(r.j)), `${r.s} ${JSON.stringify(r.j)}`);
  // ── AWS API Gateway v2 (HTTP_PROXY) and v1 (HTTP_PROXY) through the SAME bridge ──
  let n1 = seen.length;
  const a2 = (await call("POST", "/v2/apis", { name: "e2e", protocolType: "HTTP" })).j;
  const hp = (await call("POST", `/v2/apis/${a2.apiId}/integrations`, { integrationType: "HTTP_PROXY", integrationMethod: "ANY", payloadFormatVersion: "1.0", integrationUri: "https://aws-e2e.example.com/svc/{proxy}" })).j;
  await call("POST", `/v2/apis/${a2.apiId}/routes`, { routeKey: "ANY /p/{proxy+}", target: `integrations/${hp.integrationId}` });
  await call("POST", `/v2/apis/${a2.apiId}/routes`, { routeKey: "GET /lim", target: `integrations/${hp.integrationId}` });
  await call("POST", `/v2/apis/${a2.apiId}/stages`, { stageName: "$default", autoDeploy: true, routeSettings: { "GET /lim": { throttlingRateLimit: 0.0001, throttlingBurstLimit: 2 } } });
  await call("POST", `/v2/apis/${a2.apiId}/deployments`, { stageName: "$default" });
  r = await call("GET", `/apigw/${a2.apiId}/p/a/b?x=1`);
  check("AWS API Gateway v2 HTTP_PROXY: a REAL 200 from the mapped backend on Nano", r.s === 200 && r.j.hello === "from-real-backend" && r.h.get("x-real-backend") === "yes", `${r.s} ${JSON.stringify(r.j)}`);
  check("v2 backend saw the translated path + query", seen.some((x) => x.u === "/svc/a/b?x=1"), JSON.stringify(seen.slice(n1)));
  n1 = seen.length; const c2 = []; for (let i = 0; i < 3; i++) c2.push((await call("GET", `/apigw/${a2.apiId}/lim`)).s);
  check("v2 route throttle consumed once per request across the async hop (200,200,429)", JSON.stringify(c2) === "[200,200,429]" && seen.length === n1 + 2, JSON.stringify(c2) + " " + (seen.length - n1));
  const hq = (await call("POST", `/v2/apis/${a2.apiId}/integrations`, { integrationType: "HTTP_PROXY", integrationMethod: "ANY", payloadFormatVersion: "1.0", integrationUri: "https://unmapped-aws.example.org/x" })).j;
  await call("POST", `/v2/apis/${a2.apiId}/routes`, { routeKey: "GET /unm", target: `integrations/${hq.integrationId}` });
  await call("POST", `/v2/apis/${a2.apiId}/deployments`, { stageName: "$default" });
  r = await call("GET", `/apigw/${a2.apiId}/unm`);
  check("v2 unmapped backend REFUSED (502 naming vyomi-tunnel gateway-backend in x-vyomi-backend-error)", r.s === 502 && /gateway-backend/.test(r.h.get("x-vyomi-backend-error") || ""), `${r.s} ${r.h.get("x-vyomi-backend-error")}`);
  const a1 = (await call("POST", "/restapis", { name: "e2e1" })).j;
  const rp = (await call("POST", `/restapis/${a1.id}/resources/${a1.rootResourceId}`, { pathPart: "{proxy+}" })).j.id;
  await call("PUT", `/restapis/${a1.id}/resources/${rp}/methods/ANY`, { authorizationType: "NONE" });
  await call("PUT", `/restapis/${a1.id}/resources/${rp}/methods/ANY/integration`, { type: "HTTP_PROXY", uri: "https://aws-e2e.example.com/v1/{proxy}", httpMethod: "ANY" });
  await call("POST", `/restapis/${a1.id}/deployments`, { stageName: "prod" });
  r = await call("GET", `/restapis/${a1.id}/prod/_user_request_/k/l`);
  check("AWS API Gateway v1 HTTP_PROXY: a REAL 200 from the mapped backend on Nano", r.s === 200 && r.j.hello === "from-real-backend" && seen.some((x) => x.u === "/v1/k/l"), `${r.s} ${JSON.stringify(r.j)}`);
  // ── Azure APIM ──
  const AZ = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/e2e-rg", AB = "/providers/Microsoft.ApiManagement/service/e2esvc", AQ = "?api-version=2022-08-01";
  await call("PUT", AZ + AQ, { location: "eastus" });
  await call("PUT", AZ + AB + AQ, { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "x" } });
  await call("PUT", `${AZ}${AB}/apis/open${AQ}`, { properties: { displayName: "Open", path: "open", serviceUrl: "https://azure-e2e.example.net/base", protocols: ["https"], subscriptionRequired: false } });
  await call("PUT", `${AZ}${AB}/apis/open/operations/g${AQ}`, { properties: { displayName: "g", method: "GET", urlTemplate: "/r/{id}" } });
  await call("PUT", `${AZ}${AB}/apis/keyed${AQ}`, { properties: { displayName: "Keyed", path: "keyed", serviceUrl: "https://azure-e2e.example.net/base", protocols: ["https"], subscriptionRequired: true } });
  await call("PUT", `${AZ}${AB}/apis/keyed/operations/g${AQ}`, { properties: { displayName: "g", method: "GET", urlTemplate: "/r/{id}" } });
  await call("PUT", `${AZ}${AB}/apis/open/operations/g/policies/policy${AQ}`, { properties: { format: "xml", value: '<policies><inbound><base /><rate-limit calls="2" renewal-period="60" /></inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>' } });
  n1 = seen.length; const c3 = []; for (let i = 0; i < 3; i++) c3.push(await call("GET", `/azure-data/apim/e2esvc/open/r/${i}?z=1`));
  check("Azure APIM: a REAL 200 from the mapped backend on Nano", c3[0].s === 200 && c3[0].j.hello === "from-real-backend" && seen.some((x) => x.u === "/base/r/0?z=1"), `${c3[0].s} ${JSON.stringify(c3[0].j)}`);
  check("APIM rate-limit consumed once per request across the async hop (200,200,429)", JSON.stringify(c3.map((x) => x.s)) === "[200,200,429]" && seen.length === n1 + 2, JSON.stringify(c3.map((x) => x.s)) + " " + (seen.length - n1));
  n1 = seen.length; r = await call("GET", "/azure-data/apim/e2esvc/keyed/r/1");
  check("APIM subscription key still enforced in the tab: 401 and the backend is not called", r.s === 401 && seen.length === n1, `${r.s} ${seen.length - n1}`);
  check("relay logged the egress calls", /gw-egress/.test(rlog));
} catch (e) { check("e2e ran", false, e && e.stack || e); }
await browser.close(); console.log(fails ? "\nFAIL" : "\nPASS — Nano gateway e2e"); await done();
