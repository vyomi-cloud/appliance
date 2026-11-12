/* Gateway + event-bus backends on the REAL appliance stack (what Mesh runs in a Codespace) — no browser, no dev server: plain HTTP against SIM_URL.
 *
 *   GCP API Gateway   api + config (apiKey + JWT + quota) + gateway + API key, called by Host `<gw>.<region>.gateway.dev` AND by /gcpgw/<id>:
 *                     2xx forwarded to a real backend, 401 (no key) / 400 (wrong key) / 429 (quota), a real RS256 JWT (accepted; wrong audience,
 *                     tampered signature, expired refused), JWKS fetched by the appliance
 *   AWS               HTTP API (v2) invoke URL + REST (v1) invoke URL, forwarded to the backend
 *   Azure             API Management gateway: subscription key (401 without) and forwarding
 *   Eventarc          trigger -> http receiver with retry (fails twice, delivered on the 3rd) and a trigger that dead-letters to a Pub/Sub topic
 *
 * Env:
 *   SIM_URL   the appliance (default http://127.0.0.1:9000; a Mesh Codespace through `vyomi-tunnel forward vyomi-mesh-simulator-1 19000:9000` = http://127.0.0.1:19000)
 *   PROJECT   the GCP project id (default vyomi-project)
 *   LOCAL=1   the appliance is a LOCAL Docker container started with the loopback hooks (see docs/architecture/v4.0/MESH-GATEWAY-EVENTBUS-RUNBOOK.md):
 *               -e VYOMI_GATEWAY_BACKEND_OVERRIDES="https://backend.rt.test=http://host.docker.internal:$BACKEND_PORT,https://issuer.rt.test=http://host.docker.internal:$BACKEND_PORT"
 *             and this script's backend/JWKS/event receiver (BACKEND_PORT, default 9411) is reachable from it as host.docker.internal.
 *             Without LOCAL (a Codespace cannot reach this laptop) every check that needs a backend or the JWKS is an honest SKIP; control-plane,
 *             401/400/429 gateway behaviour and the event bus's retry/dead-letter bookkeeping still run.
 *   BACKEND_PORT (9411)   BACKEND_HOST (host.docker.internal)   OUT (json report)
 * Exit code 1 if any check FAILs; SKIPs are printed with their reason and never counted as PASS. */
import http from "node:http";
import crypto from "node:crypto";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const SIM = (process.env.SIM_URL || "http://127.0.0.1:9000").replace(/\/$/, "");
const P = process.env.PROJECT || "vyomi-project";
const LOCAL = process.env.LOCAL === "1";
const BPORT = Number(process.env.BACKEND_PORT || 9411);
const BHOST = process.env.BACKEND_HOST || "host.docker.internal";
const R = "us-central1";
const sfx = Date.now().toString(36).slice(-6);
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (grp, name, ok, detail = "") => { results.push({ group: grp, name, ok }); console.log(`[${ok ? "PASS" : "FAIL"}] ${grp}: ${name}${ok ? "" : " :: " + String(detail).slice(0, 300)}`); };
const skip = (grp, name, why) => { results.push({ group: grp, name, ok: null, why }); console.log(`[SKIP] ${grp}: ${name} :: ${why}`); };

// ---- raw HTTP (node's fetch cannot set Host) ----
const u = new URL(SIM);
function raw(method, path, { headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? undefined : (typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
    const h = { ...headers }; if (data !== undefined && !h["content-type"]) h["content-type"] = "application/json"; if (data !== undefined) h["content-length"] = Buffer.byteLength(data);
    const rq = http.request({ host: u.hostname, port: u.port || 80, method, path, headers: h }, (rs) => {
      const c = []; rs.on("data", (d) => c.push(d)); rs.on("end", () => { const t = Buffer.concat(c).toString(); let j; try { j = JSON.parse(t); } catch (_) {} resolve({ status: rs.statusCode, headers: rs.headers, text: t, json: j }); });
    });
    rq.on("error", reject); rq.setTimeout(30000, () => rq.destroy(new Error("timeout"))); if (data !== undefined) rq.write(data); rq.end();
  });
}
const rest = (m, p, b, headers) => raw(m, p, { body: b, headers });
const b64 = (o) => Buffer.from(typeof o === "string" ? o : JSON.stringify(o)).toString("base64");

// ---- local backend + JWKS + event receiver (one server) ----
const seen = []; const eventHits = {}; const flaky = {};
const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "rt-k1", alg: "RS256", use: "sig" };
const b64u = (b) => Buffer.from(b).toString("base64url");
function jwt(claims, { key = privateKey, kid = "rt-k1", tamper = false } = {}) {
  const h = b64u(JSON.stringify({ alg: "RS256", typ: "JWT", kid })), p = b64u(JSON.stringify(claims));
  let sig = crypto.sign("RSA-SHA256", Buffer.from(`${h}.${p}`), key).toString("base64url");
  if (tamper) sig = sig.slice(0, -4) + (sig.slice(-4) === "AAAA" ? "BBBB" : "AAAA");
  return `${h}.${p}.${sig}`;
}
const srv = http.createServer((rq, rs) => {
  const c = []; rq.on("data", (d) => c.push(d)); rq.on("end", () => {
    const url = new URL(rq.url, "http://x");
    if (url.pathname === "/jwks") { rs.writeHead(200, { "content-type": "application/json" }); return rs.end(JSON.stringify({ keys: [jwk] })); }
    if (url.pathname.startsWith("/events/")) {   // event receiver: /events/<name>?fail=<n> fails n times (500) then 200; fail=all always 500
      const name = url.pathname.split("/")[2], fail = url.searchParams.get("fail") || "0";
      eventHits[name] = (eventHits[name] || 0) + 1; const n = eventHits[name];
      const ok = fail !== "all" && n > Number(fail); rs.writeHead(ok ? 200 : 500, { "content-type": "application/json" }); return rs.end(JSON.stringify({ attempt: n, ok }));
    }
    seen.push({ method: rq.method, url: rq.url, headers: rq.headers, body: Buffer.concat(c).toString() });
    rs.writeHead(200, { "content-type": "application/json", "x-rt-backend": "1" }); rs.end(JSON.stringify({ hit: rq.url, method: rq.method }));
  });
});
await new Promise((res, rej) => { srv.once("error", rej); srv.listen(BPORT, "0.0.0.0", res); });
const backendUp = (path) => seen.some((s) => s.url.split("?")[0] === path);

console.log(`SIM_URL=${SIM} PROJECT=${P} LOCAL=${LOCAL ? 1 : 0} backend :${BPORT}`);
const health = await raw("GET", "/healthz").catch((e) => ({ status: 0, text: String(e) }));
if (health.status !== 200) { console.log("appliance not reachable: " + health.text); process.exit(2); }

// ---- stale-image probe: the routes this suite needs ----
const probeKeys = await rest("GET", `/v2/projects/${P}/locations/global/keys`);
const probeGw = await raw("GET", "/gcpgw/ghost/x");
if (!probeKeys.json || !probeGw.json || probeGw.json.code !== 404 || /NoSuchBucket|<Error>/.test(probeGw.text)) {
  console.log("STALE IMAGE: the appliance does not serve the v4.0.0 gateway/event-bus routes (GET /v2/projects/P/locations/global/keys and GET /gcpgw/ghost/x must answer JSON). Rebuild/pull the image (see the runbook).");
  console.log(`  keys -> ${probeKeys.status} ${probeKeys.text.slice(0, 120)}\n  gcpgw -> ${probeGw.status} ${probeGw.text.slice(0, 120)}`);
  srv.close(); process.exit(3);
}

// =============================== GCP API Gateway ===============================
const G = `rtg-${sfx}`;
const BACKEND = "https://backend.rt.test", ISS = "https://issuer.rt.test", AUD = "rt-aud";
const spec = {
  swagger: "2.0", info: { title: "rt-real", version: "1" },
  securityDefinitions: { api_key: { type: "apiKey", name: "key", in: "query" }, jwt: { type: "oauth2", "x-google-issuer": ISS, "x-google-jwks_uri": ISS + "/jwks", "x-google-audiences": AUD } },
  "x-google-management": { metrics: [{ name: "reads", displayName: "Reads", valueType: "INT64", metricKind: "DELTA" }], quota: { limits: [{ name: "reads-per-min", metric: "reads", unit: "1/min/{project}", values: { STANDARD: 2 } }] } },
  "x-google-backend": { address: BACKEND, path_translation: "APPEND_PATH_TO_ADDRESS" },
  paths: {
    "/open": { get: { operationId: "open", responses: { 200: { description: "ok" } } } },
    "/secure": { get: { operationId: "secure", security: [{ api_key: [] }], "x-google-quota": { metricCosts: { reads: 1 } }, responses: { 200: { description: "ok" } } } },
    "/jwt": { get: { operationId: "jwtroute", security: [{ jwt: [] }], responses: { 200: { description: "ok" } } } },
  },
};
let gwHost = "", keyString = "";
{
  const g = "GCP API Gateway";
  const a = await rest("POST", `/v1/projects/${P}/locations/global/apis?apiId=${G}`, { displayName: "rt real" });
  check(g, "create API", a.status < 300, a.text);
  const c = await rest("POST", `/v1/projects/${P}/locations/global/apis/${G}/configs?apiConfigId=c1`, { openapiDocuments: [{ document: { path: "o.json", contents: b64(spec) } }] });
  check(g, "create API config (OpenAPI 2.0 with apiKey + JWT + quota + https backend)", c.status < 300, c.text);
  const gw = await rest("POST", `/v1/projects/${P}/locations/${R}/gateways?gatewayId=${G}`, { apiConfig: `projects/${P}/locations/global/apis/${G}/configs/c1` });
  check(g, "create gateway", gw.status < 300, gw.text);
  const gv = (await rest("GET", `/v1/projects/${P}/locations/${R}/gateways/${G}`)).json || {};
  gwHost = gv.defaultHostname || ""; console.log("  gateway defaultHostname:", gwHost);
  check(g, "gateway has a *.gateway.dev hostname", /\.gateway\.dev$/.test(gwHost), gwHost);
  const k = await rest("POST", `/v2/projects/${P}/locations/global/keys?keyId=k-${sfx}`, { displayName: "rt" });
  check(g, "API Keys v2: create key", k.status < 300, k.text);
  keyString = ((await rest("GET", `/v2/projects/${P}/locations/global/keys/k-${sfx}/keyString`)).json || {}).keyString || "";
  check(g, "API Keys v2: keyString retrievable", keyString.startsWith("AIza"), keyString);

  const byHost = (path) => raw("GET", path, { headers: { host: gwHost } });
  const byPath = (path) => raw("GET", `/gcpgw/${G}${path}`);
  const unknownHost = await raw("GET", "/x", { headers: { host: "nope-0000.uc.gateway.dev" } });
  check(g, "unknown *.gateway.dev host -> JSON 404, not the S3 handler", unknownHost.status === 404 && !!unknownHost.json, unknownHost.text);
  const nr = await byHost("/nope");
  check(g, "Host-style: undefined route -> 404 'not defined by this API'", nr.status === 404 && /not defined/i.test(nr.text), `${nr.status} ${nr.text}`);

  if (LOCAL) {
    seen.length = 0; const r1 = await byHost("/open");
    check(g, "Host-style: open route forwarded to the real backend (2xx + backend body)", r1.status === 200 && r1.json?.hit === "/open" && r1.headers["x-rt-backend"] === "1", `${r1.status} ${r1.text}`);
    const r2 = await byPath("/open");
    check(g, "/gcpgw/<id> path-style: open route forwarded to the real backend", r2.status === 200 && r2.json?.hit === "/open", `${r2.status} ${r2.text}`);
  } else skip(g, "open route forwarded to the real backend", "the appliance cannot reach this machine's loopback backend (needs LOCAL=1 on a local container)");

  const nk = await byHost("/secure"); check(g, "apiKey route without a key -> 401", nk.status === 401, `${nk.status} ${nk.text}`);
  const bk = await byHost("/secure?key=AIzaNotARealKey"); check(g, "wrong key -> 400 API key not valid", bk.status === 400 && /API key not valid/i.test(bk.text), `${bk.status} ${bk.text}`);
  const q1 = await byHost(`/secure?key=${keyString}`), q2 = await byPath(`/secure?key=${keyString}`), q3 = await byHost(`/secure?key=${keyString}`);
  check(g, "valid key passes the key check (Host-style and /gcpgw/ share one quota counter), 3rd call in the minute -> 429", ![401, 400].includes(q1.status) && ![401, 400, 429].includes(q2.status) && q3.status === 429 && /RESOURCE_EXHAUSTED/.test(q3.text), `${q1.status} ${q2.status} ${q3.status} ${q3.text}`);
  if (LOCAL) check(g, "valid key forwarded (backend saw /secure, key stripped)", q1.status === 200 && seen.some((s) => s.url.startsWith("/secure") && !/key=/.test(s.url)), `${q1.status} ${JSON.stringify(seen.slice(-2))}`);
  else skip(g, "valid key forwarded to the backend", "backend unreachable from the appliance (LOCAL=1 needed); got " + q1.status);

  // JWT
  const now = Math.floor(Date.now() / 1000), claims = { iss: ISS, aud: AUD, sub: "rt-user", exp: now + 600, iat: now };
  const nj = await byHost("/jwt"); check(g, "JWT route without a token -> 401", nj.status === 401, `${nj.status} ${nj.text}`);
  const bearer = (t) => ({ host: gwHost, authorization: "Bearer " + t });
  const bad = [["wrong audience", jwt({ ...claims, aud: "other" })], ["expired", jwt({ ...claims, exp: now - 3600 })], ["wrong issuer", jwt({ ...claims, iss: "https://evil.test" })],
    ["tampered signature", jwt(claims, { tamper: true })], ["signed by an unknown key", jwt(claims, { key: crypto.generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey })]];
  for (const [nm, t] of bad) { const r = await raw("GET", "/jwt", { headers: bearer(t) }); check(g, `JWT ${nm} -> 401`, r.status === 401, `${r.status} ${r.text}`); }
  if (LOCAL) {
    const okj = await raw("GET", "/jwt", { headers: bearer(jwt(claims)) });
    check(g, "real RS256 JWT (JWKS fetched by the appliance) accepted and forwarded", okj.status === 200 && okj.json?.hit === "/jwt", `${okj.status} ${okj.text}`);
    const okp = await raw("GET", `/gcpgw/${G}/jwt`, { headers: { authorization: "Bearer " + jwt(claims) } });
    check(g, "same JWT accepted on /gcpgw/<id>", okp.status === 200, `${okp.status} ${okp.text}`);
  } else skip(g, "valid RS256 JWT accepted", "the appliance cannot fetch a JWKS from this machine (LOCAL=1 needed); refusals above ran and need no JWKS");
}

// =============================== AWS HTTP API (v2) ===============================
{
  const g = "AWS API Gateway v2";
  const api = await rest("POST", "/v2/apis", { name: "rt-http-" + sfx, protocolType: "HTTP" });
  const id = api.json?.apiId; check(g, "create HTTP API", !!id, api.text);
  if (id) {
    const integ = await rest("POST", `/v2/apis/${id}/integrations`, { integrationType: "HTTP_PROXY", integrationMethod: "ANY", payloadFormatVersion: "1.0", integrationUri: `http://${BHOST}:${BPORT}/{proxy}` });
    const rt = await rest("POST", `/v2/apis/${id}/routes`, { routeKey: "ANY /p/{proxy+}", target: `integrations/${integ.json?.integrationId}` });
    const mock = await rest("POST", `/v2/apis/${id}/routes`, { routeKey: "GET /none" });
    check(g, "create integration + route", integ.status < 300 && rt.status < 300, integ.text + rt.text);
    await rest("POST", `/v2/apis/${id}/stages`, { stageName: "$default", autoDeploy: true });
    const nf = await raw("GET", `/apigw/${id}/zzz`); check(g, "path-style /apigw/<id>: unrouted path -> 404 JSON", nf.status === 404, `${nf.status} ${nf.text}`);
    if (LOCAL) {
      seen.length = 0; const r = await raw("POST", `/apigw/${id}/p/a/b?q=1`, { body: "hello", headers: { "content-type": "text/plain" } });
      check(g, "path-style invoke URL forwards method/path/query/body to the backend", r.status === 200 && r.json?.hit === "/a/b?q=1" && seen[0]?.body === "hello", `${r.status} ${r.text}`);
      const rh = await raw("GET", "/p/c", { headers: { host: `${id}.execute-api.localhost:9443` } });
      check(g, "host-style <id>.execute-api.* invoke URL forwards to the backend", rh.status === 200 && rh.json?.hit === "/c", `${rh.status} ${rh.text}`);
    } else skip(g, "invoke URL forwards to the backend", "backend unreachable from the appliance (LOCAL=1 needed)");
  }
}

// =============================== AWS REST API (v1) ===============================
{
  const g = "AWS API Gateway v1 (REST)";
  const sig = { authorization: "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260101/us-east-1/apigateway/aws4_request, SignedHeaders=host, Signature=00" };
  const api = await rest("POST", "/restapis", { name: "rt-rest-" + sfx }, sig); const id = api.json?.id; check(g, "create REST API", !!id, api.text);
  if (id) {
    const root = ((await rest("GET", `/restapis/${id}/resources`, undefined, sig)).json?.item || [])[0]?.id;
    const res = await rest("POST", `/restapis/${id}/resources/${root}`, { pathPart: "items" }, sig); const rid = res.json?.id;
    await rest("PUT", `/restapis/${id}/resources/${rid}/methods/GET`, { authorizationType: "NONE" }, sig);
    const ig = await rest("PUT", `/restapis/${id}/resources/${rid}/methods/GET/integration`, { type: "HTTP_PROXY", httpMethod: "GET", uri: `http://${BHOST}:${BPORT}/items` }, sig);
    check(g, "create resource + method + HTTP_PROXY integration", !!rid && ig.status < 300, res.text + ig.text);
    const dep = await rest("POST", `/restapis/${id}/deployments`, { stageName: "prod" }, sig); check(g, "deploy stage prod", dep.status < 300, dep.text);
    const miss = await raw("GET", `/restapis/${id}/prod/_user_request_/nothing`); check(g, "invoke an unrouted path -> 403/404 'Missing Authentication Token'-style JSON", [403, 404].includes(miss.status), `${miss.status} ${miss.text}`);
    if (LOCAL) {
      const r = await raw("GET", `/restapis/${id}/prod/_user_request_/items`); check(g, "/restapis/<id>/<stage>/_user_request_/ invoke URL forwards to the backend", r.status === 200 && r.json?.hit === "/items", `${r.status} ${r.text}`);
      const r2 = await raw("GET", `/apigw/${id}/prod/items`); check(g, "/apigw/<id>/<stage>/ invoke URL forwards to the backend", r2.status === 200 && r2.json?.hit === "/items", `${r2.status} ${r2.text}`);
    } else skip(g, "invoke URL forwards to the backend", "backend unreachable from the appliance (LOCAL=1 needed)");
  }
}

// =============================== Azure API Management ===============================
{
  const g = "Azure APIM";
  const subs = await rest("GET", "/subscriptions?api-version=2022-12-01"); const sub = subs.json?.value?.[0]?.subscriptionId || "00000000-0000-0000-0000-000000000000";
  const Q = "?api-version=2022-08-01", S = `/subscriptions/${sub}/resourceGroups/rt-gw-${sfx}`, base = `${S}/providers/Microsoft.ApiManagement/service/rtapim${sfx}`;
  const rg = await rest("PUT", S + "?api-version=2022-09-01", { location: "eastus" }); check(g, "create resource group", rg.status < 300, rg.text);
  const sv = await rest("PUT", base + Q, { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "rt" } }); check(g, "create APIM service", sv.status < 300, sv.text);
  const ap = await rest("PUT", base + "/apis/echo" + Q, { properties: { displayName: "Echo", path: "echo", serviceUrl: `http://${BHOST}:${BPORT}/base`, protocols: ["https"], subscriptionRequired: true } }); check(g, "create API", ap.status < 300, ap.text);
  const op = await rest("PUT", base + "/apis/echo/operations/get1" + Q, { properties: { displayName: "get1", method: "GET", urlTemplate: "/r/{id}" } }); check(g, "create operation", op.status < 300, op.text);
  const sb = await rest("PUT", base + "/subscriptions/s1" + Q, { properties: { scope: `${base}/apis`, displayName: "s1" } }); check(g, "create subscription", sb.status < 300, sb.text);
  const sec = await rest("POST", base + "/subscriptions/s1/listSecrets" + Q); const key = sec.json?.primaryKey || ""; check(g, "listSecrets returns a primary key", !!key, sec.text);
  const gw = `/azure-data/apim/rtapim${sfx}`;
  const n = await raw("GET", gw + "/echo/r/7"); check(g, "gateway: no subscription key -> 401", n.status === 401, `${n.status} ${n.text}`);
  const b = await raw("GET", gw + "/echo/r/7", { headers: { "ocp-apim-subscription-key": "nope" } }); check(g, "gateway: wrong key -> 401", b.status === 401, `${b.status} ${b.text}`);
  const nf = await raw("GET", `/azure-data/apim/does-not-exist/echo/r/1`); check(g, "gateway: unknown service -> JSON 404", nf.status === 404 && !!nf.json, `${nf.status} ${nf.text}`);
  if (LOCAL) { seen.length = 0; const r = await raw("GET", gw + "/echo/r/7", { headers: { "ocp-apim-subscription-key": key } });
    check(g, "gateway: valid key forwarded to serviceUrl (/base/r/7)", r.status === 200 && seen.some((s) => s.url === "/base/r/7"), `${r.status} ${r.text} ${JSON.stringify(seen.slice(-1))}`); }
  else { const r = await raw("GET", gw + "/echo/r/7", { headers: { "ocp-apim-subscription-key": key } });
    check(g, "gateway: valid key passes the key check (reaches the backend step; backend itself unreachable from here)", r.status !== 401, `${r.status} ${r.text}`);
    skip(g, "valid key forwarded to serviceUrl", "backend unreachable from the appliance (LOCAL=1 needed)"); }
}

// =============================== Eventarc ===============================
{
  const g = "Eventarc";
  const topic = `rt-ev-${sfx}`, dlq = `rt-dlq-${sfx}`, dsub = `rt-dlq-sub-${sfx}`;
  for (const t of [topic, dlq]) { const r = await rest("PUT", `/v1/projects/${P}/topics/${t}`, {}); check(g, `create topic ${t}`, r.status < 300, r.text); }
  const ds = await rest("PUT", `/v1/projects/${P}/subscriptions/${dsub}`, { topic: `projects/${P}/topics/${dlq}` }); check(g, "subscription on the dead-letter topic", ds.status < 300, ds.text);
  const mk = (id, uri, extra) => rest("POST", `/v1/projects/${P}/locations/${R}/triggers?triggerId=${id}`, {
    eventFilters: [{ attribute: "type", value: "google.cloud.pubsub.topic.v1.messagePublished" }], transport: { pubsub: { topic: `projects/${P}/topics/${topic}` } },
    destination: { httpEndpoint: { uri } }, retryPolicy: { maxAttempts: 4, minRetryDelay: "1s", maxRetryDelay: "2s" }, ...extra });
  const tRetry = `rt-retry-${sfx}`, tDlq = `rt-dlq-${sfx}`;
  const a = await mk(tRetry, `http://${BHOST}:${BPORT}/events/${tRetry}?fail=2`, {}); check(g, "create trigger with retryPolicy -> http receiver", a.status < 300, a.text);
  const b = await mk(tDlq, `http://${BHOST}:${BPORT}/events/${tDlq}?fail=all`, { deadLetterTopic: `projects/${P}/topics/${dlq}`, retryPolicy: { maxAttempts: 2, minRetryDelay: "1s", maxRetryDelay: "1s" } }); check(g, "create trigger with deadLetterTopic", b.status < 300, b.text);
  const pub = await rest("POST", `/v1/projects/${P}/topics/${topic}:publish`, { messages: [{ data: Buffer.from("hello-event").toString("base64"), attributes: { k: "v" } }] }); check(g, "publish an event to the trigger's topic", pub.status < 300, pub.text);
  const deliveries = async (t) => ((await rest("GET", `/v1/projects/${P}/locations/${R}/triggers/${t}/deliveries`)).json) || {};
  let dRetry = {}, dDlq = {};
  for (let i = 0; i < 40; i++) {   // retries run lazily on API calls (and on the engine's own timer): keep calling
    dRetry = await deliveries(tRetry); dDlq = await deliveries(tDlq);
    if ((dDlq.deadLettered || 0) >= 1 && (LOCAL ? (dRetry.delivered || 0) >= 1 : (dRetry.attempts || 0) >= 3)) break; await sleep(1000);
  }
  console.log("  retry trigger:", JSON.stringify({ ...dRetry, deliveries: undefined }), " dlq trigger:", JSON.stringify({ ...dDlq, deliveries: undefined }));
  if (LOCAL) {
    check(g, "receiver was hit 3 times (500, 500, then 200) and the delivery is recorded as delivered", eventHits[tRetry] === 3 && (dRetry.delivered || 0) >= 1, `hits=${eventHits[tRetry]} ${JSON.stringify(dRetry).slice(0, 200)}`);
  } else {
    check(g, "failed deliveries are retried with backoff (>= 3 attempts recorded against an unreachable receiver)", (dRetry.attempts || 0) >= 3, JSON.stringify(dRetry).slice(0, 200));
    skip(g, "delivery succeeds after retries", "receiver unreachable from the appliance (LOCAL=1 needed)");
  }
  check(g, "retries exhausted -> dead-lettered (recorded on the trigger)", (dDlq.deadLettered || 0) >= 1, JSON.stringify(dDlq).slice(0, 200));
  const pull = await rest("POST", `/v1/projects/${P}/subscriptions/${dsub}:pull`, { maxMessages: 5, returnImmediately: true });
  const got = (pull.json?.receivedMessages || []).map((m) => { try { return JSON.parse(Buffer.from(m.message.data, "base64").toString()); } catch (_) { return null; } }).filter(Boolean);
  check(g, "the dead-lettered CloudEvent is on the dead-letter Pub/Sub topic", got.length >= 1 && /messagePublished/.test(got[0]?.type || ""), `${pull.status} ${pull.text.slice(0, 200)}`);
}

srv.close();
const pass = results.filter((r) => r.ok === true).length, fail = results.filter((r) => r.ok === false).length, sk = results.filter((r) => r.ok === null).length;
console.log(`RESULT ${pass} passed, ${fail} failed, ${sk} skipped`);
if (process.env.OUT) { mkdirSync(dirname(process.env.OUT), { recursive: true }); writeFileSync(process.env.OUT, JSON.stringify({ sim: SIM, project: P, local: LOCAL, pass, fail, skipped: sk, results }, null, 1)); }
process.exit(fail ? 1 : 0);
