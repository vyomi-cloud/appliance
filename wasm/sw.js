/* Vyomi Nano — service worker: the fetch-ASGI shim (the P0).
 *
 * A browser tab has no sockets, so the console SPA's HTTP requests can't reach
 * a "server" — this worker IS the transport. It intercepts the console's
 * same-origin /api/* calls and answers them three ways:
 *
 *   1. Bootstrap reads (catalog, spaces, tenants) -> served from static
 *      fixtures dumped from the REAL backend (wasm/build_fixtures.py). The
 *      console renders against a faithful catalog, not a fake one.
 *   2. Catalog-driven CRUD -> every service's collection_path/resource_path
 *      (from routes.json) is routed GENERICALLY to the in-browser backend's
 *      ResourceStore. One rule serves all 12 services; new services need zero
 *      changes here (they arrive in the catalog).
 *   3. Specialised data-plane (S3 objects, DynamoDB items) -> the object/nosql
 *      stores. Partial in milestone 1; clearly 501 where not yet wired.
 *
 * The backend itself (Pyodide + wasm/) lives on the page; we postMessage the
 * (provider, service, op, params) tuple there and await the JSON.
 */
// BASE = the bundle's mount path, derived from THIS worker's URL so the same
// bundle works served at the web root ("/sw.js" -> BASE "") OR under a subpath
// like the portal's /nano/ ("/nano/sw.js" -> BASE "/nano"). The SW scope is
// BASE + "/", so it only sees in-scope requests; the page's fetch shim rewrites
// the console's absolute /api/* to BASE + /api/* so they land in scope here.
const BASE = self.location.pathname.replace(/\/[^/]*$/, "");
const FIX = BASE + "/fixtures";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

// ── Pyodide ready-gate ────────────────────────────────────────────────
// boot() in the console fires at parse and awaits its fetches, which can race
// ahead of Pyodide loading. We hold /api/* dispatch until the page signals the
// backend is up, so early calls just wait instead of failing.
let _ready, readyPromise = new Promise((r) => (_ready = r));
// A page that reloads (or a second tab) boots its own Pyodide, so readiness is
// per window client: dispatching to a client that hasn't signalled yet (or has
// gone) would drop the message and surface as a 500 "backend timeout".
const readyClients = new Set();
self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "pyodide-ready") {
    if (e.source && e.source.id) readyClients.add(e.source.id);
    _ready();
  }
});

// ── Route table (built once from the dumped catalog) ──────────────────
let _routes;
function routes() {
  if (!_routes) {
    _routes = fetch(FIX + "/routes.json").then((r) => r.json()).then((list) =>
      list.filter((x) => x.collection).map((x) => ({
        key: x.key,
        method: (x.create_method || "POST").toUpperCase(),
        collection: x.collection,
        resourceRe: x.resource
          ? new RegExp("^" + x.resource.replace(/\{name\}/g, "([^/]+)") + "$")
          : null,
        // Lifecycle sub-paths: <resource>/{start,stop,reboot,terminate}.
        actionRe: x.resource
          ? new RegExp("^" + x.resource.replace(/\{name\}/g, "([^/]+)") + "/(start|stop|reboot|terminate)$")
          : null,
      }))
    );
  }
  return _routes;
}

// ── Per-provider catalog routes (GCP / Azure) ─────────────────────────
// AWS rides routes.json + the specialised handlers above. GCP/Azure consoles
// drive the SAME generic catalog CRUD, but their collection/resource paths carry
// templated segments ({project}/{zone}/{region}/{name}), so we build regexes from
// each cloud's catalog fixture. {name} is captured (the resource id); every other
// {placeholder} matches one path segment. Backend dispatch is provider-agnostic
// (registry._resource_dispatch), so [provider,"_resource",op] just works.
function _tplToRe(tpl) {
  let re = "^";
  for (const part of tpl.split(/(\{[^}]+\})/)) {
    if (!part) continue;
    if (/^\{[^}]+\}$/.test(part)) re += part === "{name}" ? "([^/]+)" : "[^/]+";
    else re += part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(re + "$");
}
const _CATALOG_FILE = { gcp: "gcp-catalog.json", azure: "azure-catalog.json" };
const _catRoutes = {};
function catalogRoutes(provider) {
  if (!_catRoutes[provider]) {
    const file = _CATALOG_FILE[provider];
    _catRoutes[provider] = !file ? Promise.resolve([]) :
      fetch(FIX + "/" + file).then((r) => (r.ok ? r.json() : { services: [] }))
        .then((cat) => (cat.services || []).filter((s) => s.collection_path).map((s) => ({
          key: s.key || s.service,
          createMethod: (s.create_method || "POST").toUpperCase(),
          collectionRe: _tplToRe(s.collection_path),
          resourceRe: s.resource_path ? _tplToRe(s.resource_path) : null,
          actionRe: s.resource_path
            ? new RegExp(_tplToRe(s.resource_path).source.replace(/\$$/, "/(start|stop|reboot|terminate)$"))
            : null,
        })))
        .catch(() => []);
  }
  return _catRoutes[provider];
}

// Bootstrap reads served verbatim from fixtures.
const FIXTURES = {
  // consoles ( /api/spaces/active is dynamic — see nanoSpace below )
  "/api/aws/catalog": "aws-catalog.json",
  "/api/gcp/catalog": "gcp-catalog.json",
  "/api/azure/catalog": "azure-catalog.json",
  "/api/tenants": "tenants.json",
  // launch dashboard (clouds.html)
  "/api/spaces": "spaces.json",
  "/api/runtime/tier": "runtime-tier.json",
  "/api/host/cpu": "host-cpu.json",
  "/api/host/mem": "host-mem.json",
  "/api/host/sizing": "host-sizing.json",
  "/api/runtime/disk-health": "runtime-disk-health.json",
  "/api/runtime/update-check": "runtime-update-check.json",
};
// Benign empty stubs so polled chrome endpoints don't error the console.
const STUBS = {
  // NOTE: /api/cloudsim/events is NO LONGER a stub — it is served dynamically from
  // the in-browser event store (see the cloudsim-events route in route()).
  "/api/spaces/active/facts": {},
  "/api/runtime/disk-cleanup/suggestions": { items: [] },
  // Metadata-only sub-blades with no Nano data plane yet (renderers read x||[]).
  "/api/aws/extras/secretsmanager/rotation": { value: [] },
  "/api/aws/extras/secretsmanager/replicas": { value: [] },
  "/api/aws/extras/kms/aws-managed-keys": { value: [] },
  "/api/aws/extras/kms/custom-key-stores": { value: [] },
  "/api/rds/subnet-groups": { subnet_groups: [] },
  "/api/rds/parameter-groups": { parameter_groups: [] },
};

// Nano's backend services for the readiness ribbon + Service status cards: the engine
// stores core/nano_registry.py builds, listed in fixtures/nano-backends.json by
// wasm/build_cores.py (CI fails if it's stale), plus the Pyodide runtime.
let _NANO_BACKENDS = null;
async function nanoBackends() {
  if (!_NANO_BACKENDS) {
    try { _NANO_BACKENDS = await (await fetch(FIX + "/nano-backends.json", { cache: "no-store" })).json(); }
    catch (_) { return []; }
  }
  return _NANO_BACKENDS;
}

function json(obj, status, extraHeaders) {
  return new Response(obj === null ? "" : JSON.stringify(obj),
    { status: status || 200, headers: { "content-type": "application/json", ...(extraHeaders || {}) } });
}

// Decode a JWT's payload (no signature check — the token comes straight from the
// portal over same-origin, and the portal is the authority; the appliance's
// jwks verification is its concern, not the Nano UI's). Used to read the license
// tier / issued-to for the top-bar activation pill.
function decodeJwt(token) {
  try {
    const p = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(p))));
  } catch (_) { return null; }
}
function licenseClaims(jwt) {
  const c = jwt ? decodeJwt(jwt) : null;
  if (!c) return null;
  if (c.exp && c.exp * 1000 < Date.now()) return null;  // expired
  return c;
}

// Base64 a binary buffer (the wire format for object bytes across the page
// bridge — JSON-safe, and what the S3 core's body param expects).
function b64FromBuf(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000)
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// S3 object upload is multipart/form-data (the same endpoint boto3 / `aws s3 cp`
// hit). Read the file(s) here, base64 the bytes, and PUT each through the S3
// core — one core PutObject per file, so ETag/versioning are conformance-real.
async function handleUpload(request, bucket, provider = "aws") {
  const fd = await request.formData();
  const files = fd.getAll("file").filter((f) => f && typeof f.arrayBuffer === "function");
  if (!files.length) return json({ ok: false, code: "NoFile" }, 400);
  const results = [];
  for (const file of files) {
    const b64 = b64FromBuf(await file.arrayBuffer());
    const p = { bucket, key: file.name || "upload", body_b64: b64, content_type: file.type || "application/octet-stream" };
    // S3 → s3 core PutObject; GCS → gcp_storage_core via the shared resource dispatch.
    const tuple = provider === "gcp"
      ? ["gcp", "_resource", "PutObject", { service: "storage", body: p }]
      : ["aws", "s3", "PutObject", p];
    results.push(await runInPage(tuple));
  }
  const ok = results.every((r) => r && r.ok !== false);
  return json({ ok, uploaded: results.length, results }, ok ? 200 : 400);
}

// Real-cloud list price ($/month per resource) by census service key — mirrors the
// table clouds.html uses for the Spaces cards, so both agree.
const NANO_RATE = {"microsoft.compute/virtualmachines":70.08,"microsoft.storage/storageaccounts":0.50,"microsoft.sql/servers":4.99,"microsoft.servicebus/namespaces":9.81,"microsoft.documentdb/databaseaccounts":24.48,"microsoft.web/sites":0.20,"microsoft.apimanagement/service":48.42,"microsoft.network/virtualnetworks":0,"microsoft.network/networksecuritygroups":0,"microsoft.eventgrid/topics":0.60,"microsoft.keyvault/vaults":0.03,"microsoft.app/containerapps":39.42,"microsoft.appconfiguration/configurationstores":36.50,"microsoft.network/dnszones":0.50,"microsoft.insights/metricalerts":0.10,"microsoft.operationalinsights/workspaces":2.76,"microsoft.cognitiveservices/accounts":1.00,"microsoft.authorization/roledefinitions":0,blobcontainers:0.02,queues:0.05,cosmosdbs:23.36,kvsecrets:0.03,kvkeys:0.03,servicebus:9.81,azuresql:4.99,azurerbac:0,s3:0.50,dynamodb:1.25,kms:1.00,secretsmanager:0.40,sqs:0.40,iam:0,rds:25.55,elbv2:16.43,logs:2.53,ec2:30.37,lambda:0.20,apigateway:3.50,vpc:0,ssm:0.05,stepfunctions:2.50,cloudscheduler:0.10,container:73,redis:35.77,iamcredentials:0.03,compute:24.53,storage:0.50,cloudsql:25.00,pubsub:0.40,firestore:0.18,functions:0.20,secretmanager:0.18,sns:0.50,cloudwatch:0.10,apigatewayv2:1.00,kinesis:10.95,monitoring:0.10};
NANO_RATE.artifactregistry = 0.50;   // core/cost_model.py gcp.artifactregistry
async function nanoCostSavings() {
  const now = Date.now();
  const by_provider = { aws: 0, gcp: 0, azure: 0 };
  const by_service = {};     // "<cloud>.<service>" -> USD/month, same keys as the appliance's cost_savings
  let resource_count = 0;
  for (const p of ["aws", "gcp", "azure"]) {
    let c = null; try { c = await metaGet("census:" + p); } catch (_) {}
    if (!c || typeof c.ts !== "number" || (now - c.ts) >= 60000) continue;
    resource_count += c.resources || 0;
    const bs = c.by_service || {};
    let usd = 0;
    for (const k in bs) {
      const svcUsd = (Number(bs[k]) || 0) * (Object.prototype.hasOwnProperty.call(NANO_RATE, k) ? NANO_RATE[k] : 1.0);
      usd += svcUsd;
      by_service[p + "." + k] = Math.round(svcUsd * 100) / 100;
    }
    by_provider[p] = Math.round(usd * 100) / 100;
  }
  const savings_usd = Math.round((by_provider.aws + by_provider.gcp + by_provider.azure) * 100) / 100;
  return { resource_count, savings_usd, by_provider, by_service, period: "monthly" };
}

// Each console gates on an active space whose provider matches it. We derive
// the provider from the page making the request, so aws/gcp/azure consoles all
// pass their gate from the same in-browser substrate.
function nanoSpace(provider) {
  // AWS: the account Nano's engines use in ARNs and STS (wasm/build_fixtures.py NANO_AWS_ACCOUNT).
  const acct = provider === "gcp" ? "nano-project" : provider === "azure" ? "nano-sub" : "123456789012";
  const region = provider === "gcp" ? "us-central1" : provider === "azure" ? "eastus" : "us-east-1";
  return { space_id: "nano-" + provider, name: "Nano " + provider.toUpperCase(), provider,
           status: "running", active_region: region, active_account: acct };
}

// ── User-created spaces (persisted) ───────────────────────────────────
// Nano's default spaces come from the fixture (read-only); spaces the user
// creates are persisted in IndexedDB so they survive reloads AND show up in the
// dashboard grid. The in-browser backend is ONE substrate, so every space of a
// given provider shares it — spaces are organizational, not isolated stores.
const IDB_NAME = "nano-spaces";
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(IDB_NAME, 1);
    r.onupgradeneeded = () => { const db = r.result;
      if (!db.objectStoreNames.contains("spaces")) db.createObjectStore("spaces", { keyPath: "space_id" });
      if (!db.objectStoreNames.contains("meta"))   db.createObjectStore("meta",   { keyPath: "k" });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
function _req(req) { return new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); }); }
async function spacesAll() { const db = await idb(); return await _req(db.transaction("spaces").objectStore("spaces").getAll()); }
async function spacePut(s) { const db = await idb(); return await _req(db.transaction("spaces", "readwrite").objectStore("spaces").put(s)); }
async function spaceDel(id) { const db = await idb(); return await _req(db.transaction("spaces", "readwrite").objectStore("spaces").delete(id)); }
// ── Nano workspace sync (Step 2): persist the `spaces` store to the portal,
//    keyed by the signed-in user (license sub), so it follows the account.
//    Auth = the license JWT from meta (Bearer). No-ops when signed out.
async function nanoWsPush() {
  const jwt = await metaGet("license_jwt");
  if (!jwt) return { ok: false, reason: "not signed in" };
  const spaces = await spacesAll();
  try {
    const r = await fetch(self.location.origin + "/api/nano/workspace", {
      method: "PUT", headers: { "content-type": "application/json", "authorization": "Bearer " + jwt },
      body: JSON.stringify({ blob: JSON.stringify({ v: 1, spaces: spaces }) }),
    });
    return { ok: r.ok, pushed: spaces.length };
  } catch (e) { return { ok: false, reason: String(e) }; }
}
async function nanoWsPull() {
  const jwt = await metaGet("license_jwt");
  if (!jwt) return { ok: false, reason: "not signed in" };
  try {
    const r = await fetch(self.location.origin + "/api/nano/workspace", { headers: { "authorization": "Bearer " + jwt } });
    if (!r.ok) return { ok: false, reason: "http " + r.status };
    const d = await r.json();
    if (!d || !d.blob) return { ok: true, merged: 0 };
    let parsed = {}; try { parsed = JSON.parse(d.blob); } catch (_) {}
    const remote = (parsed && parsed.spaces) || [];
    const local = await spacesAll();
    const have = new Set(local.map((s) => s.space_id));
    let merged = 0;
    for (const s of remote) if (s && s.space_id && !have.has(s.space_id)) { await spacePut(s); merged++; }
    return { ok: true, merged: merged };
  } catch (e) { return { ok: false, reason: String(e) }; }
}
// ── Nano cost-estimate push: persist the counterfactual real-cloud $/mo of
//    the user's Nano resources (census × list-price rates, computed in the
//    tab), keyed by the signed-in user. Auth = the license JWT (Bearer).
//    No-ops when signed out. Body: {monthly_cents, by_provider, rate_version}.
async function nanoCostPush(body) {
  const jwt = await metaGet("license_jwt");
  if (!jwt) return { ok: false, reason: "not signed in" };
  try {
    const r = await fetch(self.location.origin + "/api/nano/cost-estimate", {
      method: "PUT", headers: { "content-type": "application/json", "authorization": "Bearer " + jwt },
      body: JSON.stringify({
        monthly_cents: (body && body.monthly_cents) || 0,
        by_provider: (body && body.by_provider) || {},
        by_service: (body && body.by_service) || {},
        rate_version: (body && body.rate_version) || "",
      }),
    });
    return { ok: r.ok };
  } catch (e) { return { ok: false, reason: String(e) }; }
}
// Pull the persisted estimate (incl. per-service census) so a cold-loaded
// console can render the breakdown with no live resources in the tab.
// No-ops to an empty estimate when signed out. Auth = the license JWT (Bearer).
async function nanoCostPull() {
  const jwt = await metaGet("license_jwt");
  if (!jwt) return { ok: false, by_service: {}, by_provider: {} };
  try {
    const r = await fetch(self.location.origin + "/api/nano/cost-estimate", { headers: { "authorization": "Bearer " + jwt } });
    if (!r.ok) return { ok: false, by_service: {}, by_provider: {} };
    const d = await r.json();
    return { ok: true, by_service: (d && d.by_service) || {}, by_provider: (d && d.by_provider) || {},
             monthly_cents: (d && d.monthly_cents) || 0, updated_at: (d && d.updated_at) || null };
  } catch (e) { return { ok: false, by_service: {}, by_provider: {} }; }
}
async function metaGet(k) { const db = await idb(); const r = await _req(db.transaction("meta").objectStore("meta").get(k)); return r && r.v; }
async function metaPut(k, v) { const db = await idb(); return await _req(db.transaction("meta", "readwrite").objectStore("meta").put({ k, v })); }

function mkSpace(provider, name, region) {
  const base = nanoSpace(provider);  // provider-correct account + default region
  const slug = String(name || provider).toLowerCase().replace(/[^a-z0-9]+/g, "-")
                 .replace(/^-+|-+$/g, "").slice(0, 40) || provider;
  return { ...base,
    space_id: "nano-" + provider + "-" + slug + "-" + Math.random().toString(36).slice(2, 7),
    name: name || base.name,
    active_region: region || base.active_region,
    created: true };
}

async function providerOf(clientId) {
  try {
    const c = clientId && await self.clients.get(clientId);
    const m = c && c.url.match(/\/(aws|gcp|azure)-console\.html/);
    if (m) return m[1];
  } catch (_) {}
  return "aws";
}

// Ask the page (where Pyodide lives) to run a dispatch tuple.
async function runInPage(tuple) {
  await readyPromise;
  // Wait (bounded) for a live window whose Pyodide has signalled ready; after a
  // reload the old client id is gone and the new page is still booting.
  let client = null;
  for (let i = 0; i < 240 && !client; i++) {
    const all = await self.clients.matchAll({ includeUncontrolled: true });
    const wins = all.filter((c) => c.type === "window");
    client = wins.find((c) => readyClients.has(c.id)) || null;
    if (!client && !wins.length && all[0]) client = all[0];
    if (!client) await new Promise((r) => setTimeout(r, 250));
  }
  if (!client) throw new Error("no client to run the in-browser backend");
  return await new Promise((resolve, reject) => {
    const ch = new MessageChannel();
    ch.port1.onmessage = (ev) => resolve(ev.data);
    client.postMessage({ type: "vyomi-dispatch", tuple }, [ch.port2]);
    setTimeout(() => reject(new Error("backend timeout")), 15000);
  });
}

// Map a console /api/* request to a dispatch tuple (or a direct Response for
// fixtures/stubs). Returns {response} | {tuple} | {miss}.
async function route(method, path, body, query) {
  // 1. fixtures + stubs (exact match, GET)
  if (method === "GET" && FIXTURES[path]) {
    const r = await fetch(FIX + "/" + FIXTURES[path]);
    return { response: new Response(r.body, { status: 200, headers: { "content-type": "application/json" } }) };
  }
  if (method === "GET" && STUBS[path]) return { response: json(STUBS[path]) };

  // ── Per-resource cloudsim event / activity log (SHARED backbone) ──────
  // GET /api/cloudsim/events[?resource=<name>&provider=<cloud>&service=<svc>&limit=N]
  //   → the in-browser event store (core/nano_events via registry._events_query),
  //     recorded on every mutating dispatch. Returns {ok, events:[…]} newest-first,
  //     the SAME {events:[…]} shape the old stub returned (the console reads x.events).
  // The "_events" pseudo-service is provider-neutral in the backend; we pass the
  // optional provider filter through. No query filters → the global activity feed.
  if (method === "GET" && path === "/api/cloudsim/events") {
    const p = {
      resource: (query && query.resource) || "",
      provider: (query && query.provider) || "",
      service: (query && query.service) || "",
      limit: (query && query.limit) || 200,
    };
    // provider slot is cosmetic for a neutral pseudo-service; use the filter (or aws).
    return { tuple: [p.provider || "aws", "_events", "List", p] };
  }

  // Instance-type catalog for the compute launch wizard (EC2 / GCE / Azure VM).
  // Static per-cloud data, dumped from core/instance_catalog.py to fixtures.
  if (method === "GET" && path === "/api/instances/catalog") {
    const prov = (query && query.provider) || "aws";
    const cr = await fetch(FIX + "/instances-catalog-" + prov + ".json");
    if (cr.ok) return { response: new Response(cr.body, { status: 200, headers: { "content-type": "application/json" } }) };
    return { response: json({ provider: prov, count: 0, instances: [] }) };
  }

  // 1.5 Azure ARM control plane — the Azure console speaks real ARM, not the
  //     generic /api/{cloud}/{service} scheme: /subscriptions/{sub}/resourceGroups/
  //     {rg}/providers/Microsoft.X/{type}/{name}?api-version=, plus the LRO poll at
  //     /api/azure/operations/{id}. The substrate-free AzureArm core serves both;
  //     its HTTP envelope (status + Azure-AsyncOperation/Location headers + body)
  //     is returned verbatim (see the __http handling in the fetch listener).
  if (path.startsWith("/subscriptions/") || path === "/subscriptions" || path === "/tenants" || path.startsWith("/api/azure/operations/")) {
    return { tuple: ["azure", "_arm", method, { path, query: query || {}, body: body || null }] };
  }

  // ── v2.9.0 Azure net-new data planes → real cores (dataplane_adapter) ──
  let am;
  // Key Vault data plane for the console (secrets + keys CRUD). Offline serves this
  // at /azure-data/keyvault/{vault}/…; the SW only owns /api/*, so Nano mirrors it
  // here and runs the same native Key Vault cores the SDK wire uses.
  am = path.match(/^\/api\/azure\/keyvault\/([^/]+)\/(secrets|keys)(\/.*)?$/);
  if (am) return { tuple: ["azure", "_kv", method, { kind: am[2], rest: am[3] || "", body: body || null }] };
  // Storage-account console routes (/api/azure/storage/{acct}/containers|queues…)
  // → the same Azurite-equivalent blob/queue cores the native SDKs use.
  am = path.match(/^\/api\/azure\/storage\/([^/]+)\/(containers|queues)(?:\/([^/]+))?(?:\/blobs(?:\/(.+))?)?$/);
  if (am) {
    const svc = am[2] === "queues" ? "queues" : "blobcontainers", item = am[3] ? decodeURIComponent(am[3]) : "";
    const isBlobs = /\/blobs(\/|$)/.test(path), blob = am[4] ? decodeURIComponent(am[4]) : "";
    if (!item) {
      if (method === "GET")  return { tuple: ["azure", "_resource", "ConsoleList", { service: svc }] };
      if (method === "POST") return { tuple: ["azure", "_resource", "Create", { service: svc, body: body || {} }] };
    } else if (isBlobs && svc === "blobcontainers") {
      if (method === "GET" && !blob)    return { tuple: ["azure", "_resource", "ListBlobs", { service: svc, name: item }] };
      if (method === "DELETE" && blob)  return { tuple: ["azure", "_resource", "DeleteObject", { service: svc, name: item, body: { blob } }] };
    } else if (method === "DELETE") {
      return { tuple: ["azure", "_resource", "Delete", { service: svc, name: item }] };
    }
  }
  // Key Vault data plane as the vault blade (and the native SDK) address it:
  // /azure-data/keyvault/{vault}/secrets|keys[/{name}[/create]] → the KV secrets/keys cores.
  // Key Vault certificates (create / get / versions / pending / delete) → the shared certificates core.
  am = path.match(/^\/azure-data\/keyvault\/([^/]+)\/certificates((?:\/[^/]+){0,2})$/);
  if (am) {
    return { tuple: ["azure", "_resource", "KvData", { service: "kvcerts",
      body: { method, vault: decodeURIComponent(am[1]), sub: am[2].replace(/^\//, "").split("/").map(decodeURIComponent).join("/"), body: body || {} } }] };
  }
  am = path.match(/^\/azure-data\/keyvault\/([^/]+)\/(secrets|keys)((?:\/[^/]+){0,2})$/);
  if (am) {
    return { tuple: ["azure", "_resource", "KvData", { service: am[2] === "keys" ? "kvkeys" : "kvsecrets",
      body: { method, sub: am[3].replace(/^\//, "").split("/").map(decodeURIComponent).join("/"), body: body || {} } }] };
  }
  // Service Bus (core/azure_servicebus_core.py) — topics + subscriptions + send/receive
  if (path === "/api/servicebus/topics") {
    if (method === "GET")  return { tuple: ["azure", "servicebus", "ListTopics", {}] };
    if (method === "POST") return { tuple: ["azure", "servicebus", "CreateTopic", body || {}] };
  }
  am = path.match(/^\/api\/servicebus\/topics\/([^/]+)\/subscriptions$/);
  if (am && method === "POST") return { tuple: ["azure", "servicebus", "CreateSubscription", { topic: decodeURIComponent(am[1]), ...(body || {}) }] };
  am = path.match(/^\/api\/servicebus\/topics\/([^/]+)\/send$/);
  if (am && method === "POST") return { tuple: ["azure", "servicebus", "Send", { topic: decodeURIComponent(am[1]), ...(body || {}) }] };
  am = path.match(/^\/api\/servicebus\/topics\/([^/]+)\/subscriptions\/([^/]+)\/receive$/);
  if (am && method === "POST") return { tuple: ["azure", "servicebus", "Receive", { topic: decodeURIComponent(am[1]), subscription: decodeURIComponent(am[2]) }] };
  am = path.match(/^\/api\/servicebus\/topics\/([^/]+)$/);
  if (am && method === "DELETE") return { tuple: ["azure", "servicebus", "DeleteTopic", { name: decodeURIComponent(am[1]) }] };
  // Azure SQL (core/azure_sql_core.py) — servers + databases + real query
  if (path === "/api/azuresql/servers") {
    if (method === "GET")  return { tuple: ["azure", "azuresql", "ListServers", {}] };
    if (method === "POST") return { tuple: ["azure", "azuresql", "CreateServer", body || {}] };
  }
  am = path.match(/^\/api\/azuresql\/servers\/([^/]+)\/databases$/);
  if (am && method === "POST") return { tuple: ["azure", "azuresql", "CreateDatabase", { server: decodeURIComponent(am[1]), ...(body || {}) }] };
  if (path === "/api/azuresql/query" && method === "POST") return { tuple: ["azure", "azuresql", "Query", body || {}] };
  am = path.match(/^\/api\/azuresql\/servers\/([^/]+)$/);
  if (am && method === "DELETE") return { tuple: ["azure", "azuresql", "DeleteServer", { name: decodeURIComponent(am[1]) }] };
  // Azure RBAC (core/azure_iam_core.py) — role assignments + checkAccess
  if (path === "/api/azurerbac/assignments") {
    if (method === "GET")  return { tuple: ["azure", "azurerbac", "ListAssignments", {}] };
    if (method === "POST") return { tuple: ["azure", "azurerbac", "CreateAssignment", body || {}] };
  }
  if (path === "/api/azurerbac/check" && method === "POST") return { tuple: ["azure", "azurerbac", "CheckAccess", body || {}] };
  am = path.match(/^\/api\/azurerbac\/assignments\/([^/]+)$/);
  if (am && method === "DELETE") return { tuple: ["azure", "azurerbac", "DeleteAssignment", { name: decodeURIComponent(am[1]) }] };

  // 2. specialised data-plane — S3 + DynamoDB served by the PROVEN conformance
  //    cores (via aws_core_adapter on the page). Must precede the generic CRUD
  //    so bucket/table lifecycle AND items/objects all flow through one core
  //    store (a bucket created here is the bucket PutObject writes into).
  let m;
  const dec = decodeURIComponent;
  // ── S3 ──────────────────────────────────────────────────────────────
  if (path === "/api/s3/buckets") {
    if (method === "GET")  return { tuple: ["aws", "s3", "ListBuckets", {}] };
    if (method === "POST") return { tuple: ["aws", "s3", "CreateBucket", body || {}] };
  }
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/versioning$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "GetVersioning", { bucket: dec(m[1]) }] };
  if (m && (method === "PUT" || method === "POST"))
    return { tuple: ["aws", "s3", "PutVersioning", { bucket: dec(m[1]), status: (body && body.status) || "Enabled" }] };
  // Bucket detail tabs: configuration (lifecycle/cors/encryption/public_access_block/
  // policy/ownership), object versions, event notifications (core/aws_console_detail.py).
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/config\/([a-z_]+)$/);
  if (m) return { tuple: ["aws", "s3", { GET: "GetBucketConfig", PUT: "PutBucketConfig", DELETE: "DeleteBucketConfig" }[method] || "GetBucketConfig",
                          { bucket: dec(m[1]), kind: m[2], method, value: (body || {}).value }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/versions$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "ListObjectVersions", { bucket: dec(m[1]), prefix: (query && query.prefix) || "" }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/notifications?$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "GetBucketNotification", { bucket: dec(m[1]) }] };
  if (m && method === "PUT") return { tuple: ["aws", "s3", "PutBucketNotification", { bucket: dec(m[1]), method, body: body || {} }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "ListObjects", { bucket: dec(m[1]) }] };
  // (POST upload to this path is multipart — handled in the fetch listener.)
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/(.+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "s3", "GetObject", { bucket: dec(m[1]), key: m[2] }] };
  if (m && method === "DELETE") return { tuple: ["aws", "s3", "DeleteObject", { bucket: dec(m[1]), key: m[2] }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "s3", "GetBucket", { bucket: dec(m[1]) }] };
  if (m && method === "PATCH")  return { tuple: ["aws", "s3", "PutBucketTagging", { bucket: dec(m[1]), tags: (body || {}).tags || {} }] };
  if (m && method === "DELETE") return { tuple: ["aws", "s3", "DeleteBucket", { bucket: dec(m[1]) }] };
  // Console-next creates a bucket with the name in the PATH (/api/s3/buckets/{bucket}),
  // not the collection path — route that POST to CreateBucket (was falling through → 501).
  if (m && method === "POST")   return { tuple: ["aws", "s3", "CreateBucket", { bucket: dec(m[1]) }] };
  // ── DynamoDB ────────────────────────────────────────────────────────
  if (path === "/api/dynamodb/tables") {
    if (method === "GET")  return { tuple: ["aws", "dynamodb", "ListTables", {}] };
    if (method === "POST") return { tuple: ["aws", "dynamodb", "CreateTable", body || {}] };
  }
  // Table detail tabs (core/aws_console_detail.py): indexes, streams, capacity,
  // encryption, TTL, PITR, backups, Contributor Insights.
  m = path.match(/^\/api\/dynamodb\/tables\/([^/]+)\/detail\/([a-z]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "dynamodb", "DescribeTableSection", { table: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "dynamodb", "UpdateTableSection", { table: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/dynamodb\/tables\/([^/]+)\/items$/);
  if (m && method === "GET")  return { tuple: ["aws", "dynamodb", "ListItems", { table: dec(m[1]) }] };
  if (m && method === "POST") return { tuple: ["aws", "dynamodb", "PutItem", { table: dec(m[1]), item: (body && body.item) || body || {} }] };
  m = path.match(/^\/api\/dynamodb\/tables\/([^/]+)\/query$/);
  if (m && method === "POST") return { tuple: ["aws", "dynamodb", "Query", { table: dec(m[1]), params: body || {} }] };
  m = path.match(/^\/api\/dynamodb\/tables\/([^/]+)\/scan$/);
  if (m && method === "POST") return { tuple: ["aws", "dynamodb", "Scan", { table: dec(m[1]), params: body || {} }] };
  m = path.match(/^\/api\/dynamodb\/tables\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "dynamodb", "GetTable", { table: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "dynamodb", "DeleteTable", { table: dec(m[1]) }] };
  // ── IAM (core/iam_core.py) ──────────────────────────────────────────
  if (path === "/api/iam/users") {
    if (method === "GET")  return { tuple: ["aws", "iam", "ListUsers", {}] };
    if (method === "POST") return { tuple: ["aws", "iam", "CreateUser", body || {}] };
  }
  if (path === "/api/iam/roles" && method === "GET")    return { tuple: ["aws", "iam", "ListRoles", {}] };
  // IAM account tabs (core/aws_console_detail.py): identity providers, password policy, Access Analyzer.
  m = path.match(/^\/api\/iam\/detail\/([a-z-]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "iam", "GetAccountSection", { section: m[1] }] };
  if (m && method === "PUT") return { tuple: ["aws", "iam", "UpdateAccountSection", { section: m[1], method, body: body || {} }] };
  if (path === "/api/iam/policies" && method === "GET") return { tuple: ["aws", "iam", "ListPolicies", {}] };
  if (path === "/api/iam/groups" && method === "GET")   return { tuple: ["aws", "iam", "ListGroups", {}] };
  if (path === "/api/iam/attachments" && method === "GET") return { tuple: ["aws", "iam", "ListAttachments", {}] };
  m = path.match(/^\/api\/iam\/users\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "iam", "GetUser", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "iam", "DeleteUser", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/iam\/roles\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "iam", "GetRole", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "iam", "DeleteRole", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/iam\/groups\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "iam", "GetGroup", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/iam\/policies\/([^/]+)$/);
  if (m && method === "DELETE") return { tuple: ["aws", "iam", "DeletePolicy", { name: dec(m[1]) }] };
  // ── RDS (core/rds_core.py) ──────────────────────────────────────────
  if (path === "/api/rds/databases") {
    if (method === "GET")  return { tuple: ["aws", "rds", "ListDatabases", {}] };
    if (method === "POST") return { tuple: ["aws", "rds", "CreateDatabase", body || {}] };
  }
  if (path === "/api/rds/snapshots" && method === "GET") return { tuple: ["aws", "rds", "Snapshots", {}] };
  // DB instance detail tabs (core/aws_console_detail.py): connectivity, configuration, events.
  m = path.match(/^\/api\/rds\/databases\/([^/]+)\/(connectivity|subnet-group|pending-maintenance|performance-insights|configuration|events)$/);
  if (m && method === "GET") return { tuple: ["aws", "rds", "DescribeDBInstanceDetail", { name: dec(m[1]), tab: m[2] }] };
  if (m && m[2] === "configuration" && method === "PUT")
    return { tuple: ["aws", "rds", "ModifyDBInstanceConfiguration", { name: dec(m[1]), body: body || {} }] };
  m = path.match(/^\/api\/rds\/databases\/([^/]+)\/(start|stop|reboot|modify)$/);
  if (m && method === "POST") return { tuple: ["aws", "rds", m[2][0].toUpperCase() + m[2].slice(1), { name: dec(m[1]), ...(body || {}) }] };
  m = path.match(/^\/api\/rds\/databases\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "rds", "GetDatabase", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "rds", "DeleteDatabase", { name: dec(m[1]) }] };
  // ── SQS (core/sqs_core.py) ──────────────────────────────────────────
  if (path === "/api/sqs/queues") {
    if (method === "GET")  return { tuple: ["aws", "sqs", "ListQueues", {}] };
    if (method === "POST") return { tuple: ["aws", "sqs", "CreateQueue", body || {}] };
  }
  // Queue detail tabs (core/aws_console_detail.py): configuration, DLQ, encryption, access policy, purge.
  m = path.match(/^\/api\/sqs\/queues\/([^/]+)\/detail\/([a-z]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "sqs", "GetQueueSection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "sqs", "SetQueueSection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/sqs\/queues\/([^/]+)\/(send|receive|purge)$/);
  if (m && method === "POST") return { tuple: ["aws", "sqs", m[2][0].toUpperCase() + m[2].slice(1), { name: dec(m[1]), ...(body || {}) }] };
  m = path.match(/^\/api\/sqs\/queues\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "sqs", "GetQueue", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "sqs", "DeleteQueue", { name: dec(m[1]) }] };
  // ── Secrets Manager (core/secrets_core.py) ──────────────────────────
  if (path === "/api/aws/secrets") {
    if (method === "GET")  return { tuple: ["aws", "secrets", "ListSecrets", {}] };
    if (method === "POST") return { tuple: ["aws", "secrets", "CreateSecret", body || {}] };
  }
  // Secret detail tabs (core/aws_console_detail.py): value, versions, rotation, replication, key, policy.
  m = path.match(/^\/api\/aws\/secrets\/(.+)\/detail\/([a-z]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "secrets", "GetSecretSection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "secrets", "UpdateSecretSection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/aws\/secrets\/(.+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "secrets", "GetSecret", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "secrets", "DeleteSecret", { name: dec(m[1]) }] };
  // ── CloudWatch alarms (core/cloudwatch_core.py) ─────────────────────
  if (path === "/api/aws/cloudwatch/alarms") {
    if (method === "GET")  return { tuple: ["aws", "cloudwatch", "ListAlarms", {}] };
    if (method === "POST") return { tuple: ["aws", "cloudwatch", "CreateAlarm", body || {}] };
  }
  m = path.match(/^\/api\/aws\/cloudwatch\/alarms\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "cloudwatch", "GetAlarm", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "cloudwatch", "DeleteAlarm", { name: dec(m[1]) }] };
  // ── KMS (core/kms_core.py) ──────────────────────────────────────────
  if (path === "/api/aws/kms/keys") {
    if (method === "GET")  return { tuple: ["aws", "kms", "ListKeys", {}] };
    if (method === "POST") return { tuple: ["aws", "kms", "CreateKey", body || {}] };
  }
  if (path === "/api/aws/extras/kms/aliases" && method === "GET") return { tuple: ["aws", "kms", "ListAliases", {}] };
  // Key detail tabs (core/aws_console_detail.py): configuration, policy, aliases, rotation, users, admins, grants.
  m = path.match(/^\/api\/aws\/kms\/keys\/([^/]+)\/detail\/([a-z]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "kms", "GetKeySection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "kms", "UpdateKeySection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/aws\/kms\/keys\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "kms", "GetKey", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "kms", "DeleteKey", { name: dec(m[1]) }] };
  // ── v2.9.0 net-new data planes → real cores (dataplane_adapter) ──────
  // Lambda (core/lambda_core.py) — functions + sandboxed invoke
  if (path === "/api/lambda/functions") {
    if (method === "GET")  return { tuple: ["aws", "lambda", "ListFunctions", {}] };
    if (method === "POST") return { tuple: ["aws", "lambda", "CreateFunction", body || {}] };
  }
  // Function detail tabs (core/aws_console_detail.py): code, env, configuration,
  // versions, aliases, resource-based policy, execution role, saved test events.
  m = path.match(/^\/api\/lambda\/functions\/([^/]+)\/detail\/([a-z-]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "lambda", "GetFunctionSection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "lambda", "UpdateFunctionSection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/lambda\/functions\/([^/]+)\/invoke$/);
  if (m && method === "POST") return { tuple: ["aws", "lambda", "Invoke", { name: dec(m[1]), ...(body || {}) }] };
  m = path.match(/^\/api\/lambda\/functions\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "lambda", "GetFunction", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "lambda", "DeleteFunction", { name: dec(m[1]) }] };
  // API Gateway (core/apigateway_core.py) — APIs + MOCK/Lambda-proxy + invoke
  if (path === "/api/apigateway/apis") {
    if (method === "GET")  return { tuple: ["aws", "apigateway", "ListApis", {}] };
    if (method === "POST") return { tuple: ["aws", "apigateway", "CreateApi", body || {}] };
  }
  // REST API detail tabs (core/aws_console_detail.py): authorizers, models, deployments, logging, policy, settings.
  m = path.match(/^\/api\/apigateway\/apis\/([^/]+)\/detail\/([a-z]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "apigateway", "GetRestApiSection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "apigateway", "UpdateRestApiSection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/apigateway\/apis\/([^/]+)\/invoke$/);
  if (m && method === "POST") return { tuple: ["aws", "apigateway", "Invoke", { id: dec(m[1]), ...(body || {}) }] };
  m = path.match(/^\/api\/apigateway\/apis\/([^/]+)\/resources$/);
  if (m && method === "GET") return { tuple: ["aws", "apigateway", "ListResources", { id: dec(m[1]) }] };
  m = path.match(/^\/api\/apigateway\/apis\/([^/]+)\/stages$/);
  if (m && method === "GET") return { tuple: ["aws", "apigateway", "ListStages", { id: dec(m[1]) }] };
  m = path.match(/^\/api\/apigateway\/apis\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "apigateway", "GetApi", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "apigateway", "DeleteApi", { name: dec(m[1]) }] };
  // API Gateway V2 (core/apigatewayv2_core.py) — HTTP/WebSocket APIs
  if (path === "/api/apigatewayv2/apis") {
    if (method === "GET")  return { tuple: ["aws", "apigatewayv2", "ListApis", {}] };
    if (method === "POST") return { tuple: ["aws", "apigatewayv2", "CreateApi", body || {}] };
  }
  m = path.match(/^\/api\/apigatewayv2\/apis\/([^/]+)\/(routes|integrations|stages|deployments|authorizers|models)$/);
  if (m && method === "GET") return { tuple: ["aws", "apigatewayv2", "ListChildren", { id: dec(m[1]), kind: m[2] }] };
  m = path.match(/^\/api\/apigatewayv2\/apis\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "apigatewayv2", "GetApi", { id: dec(m[1]) }] };
  if (m && method === "PATCH")  return { tuple: ["aws", "apigatewayv2", "UpdateApi", { id: dec(m[1]), ...(body || {}) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "apigatewayv2", "DeleteApi", { id: dec(m[1]) }] };
  // Systems Manager Parameter Store (core/ssm_core.py) — names carry slashes, so match greedily
  if (path === "/api/ssm/parameters") {
    if (method === "GET")  return { tuple: ["aws", "ssm", "ListParameters", {}] };
    if (method === "POST") return { tuple: ["aws", "ssm", "PutParameter", body || {}] };
  }
  m = path.match(/^\/api\/ssm\/parameters\/(.+)\/metadata$/);
  if (m && method === "GET") return { tuple: ["aws", "ssm", "DescribeParameter", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/ssm\/parameters\/(.+)\/history$/);
  if (m && method === "GET") return { tuple: ["aws", "ssm", "ParameterHistory", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/ssm\/parameters\/(.+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "ssm", "GetParameter", { name: dec(m[1]) }] };
  if (m && method === "PUT")    return { tuple: ["aws", "ssm", "UpdateParameter", { ...(body || {}), name: dec(m[1]) }] };
  if (m && method === "PATCH")  return { tuple: ["aws", "ssm", "TagParameter", { ...(body || {}), name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "ssm", "DeleteParameter", { name: dec(m[1]) }] };
  // Step Functions (core/stepfunctions_core.py) — state machines + executions
  if (path === "/api/stepfunctions/machines") {
    if (method === "GET")  return { tuple: ["aws", "stepfunctions", "ListMachines", {}] };
    if (method === "POST") return { tuple: ["aws", "stepfunctions", "CreateMachine", body || {}] };
  }
  m = path.match(/^\/api\/stepfunctions\/machines\/([^/]+)\/(executions|versions|aliases)$/);
  if (m && method === "GET")  return { tuple: ["aws", "stepfunctions", "ListChildren", { id: dec(m[1]), kind: m[2] }] };
  if (m && m[2] === "executions" && method === "POST") return { tuple: ["aws", "stepfunctions", "StartExecution", { id: dec(m[1]), ...(body || {}) }] };
  m = path.match(/^\/api\/stepfunctions\/machines\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "stepfunctions", "GetMachine", { id: dec(m[1]) }] };
  if (m && method === "PATCH")  return { tuple: ["aws", "stepfunctions", "UpdateMachine", { id: dec(m[1]), ...(body || {}) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "stepfunctions", "DeleteMachine", { id: dec(m[1]) }] };
  // VPC (core/vpc_core.py) — topology + reachability analyzer
  if (path === "/api/vpc" && method === "GET") return { tuple: ["aws", "vpc", "List", {}] };
  if (path === "/api/vpc/vpcs" && method === "GET") return { tuple: ["aws", "vpc", "List", {}] };
  // VPC detail tabs (core/aws_console_detail.py): attributes, NAT gateways, endpoints, NACLs, flow logs.
  m = path.match(/^\/api\/vpc\/vpcs\/([^/]+)\/detail\/([a-z_-]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "vpc", "DescribeVpcSection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "vpc", "ModifyVpcSection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/vpc\/vpcs\/([^/]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "vpc", "GetVpc", { name: dec(m[1]) }] };
  if (path === "/api/vpc/vpcs" && method === "POST") return { tuple: ["aws", "vpc", "CreateVpc", body || {}] };
  if (path === "/api/vpc/subnets" && method === "GET") return { tuple: ["aws", "vpc", "ListSubnets", {}] };
  if (path === "/api/vpc/route-tables" && method === "GET") return { tuple: ["aws", "vpc", "ListRouteTables", {}] };
  if (path === "/api/vpc/internet-gateways" && method === "GET") return { tuple: ["aws", "vpc", "ListInternetGateways", {}] };
  if (path === "/api/vpc/subnets" && method === "POST") return { tuple: ["aws", "vpc", "CreateSubnet", body || {}] };
  if (path === "/api/vpc/security-groups" && method === "POST") return { tuple: ["aws", "vpc", "CreateSecurityGroup", body || {}] };
  if (path === "/api/vpc/security-groups" && method === "GET")  return { tuple: ["aws", "vpc", "ListSecurityGroups", {}] };
  if (path === "/api/vpc/authorize" && method === "POST") return { tuple: ["aws", "vpc", "Authorize", body || {}] };
  if (path === "/api/vpc/analyze" && method === "POST") return { tuple: ["aws", "vpc", "Analyze", body || {}] };
  // EC2 AMIs — a fresh account owns no custom images (CreateImage not modeled in
  // Nano yet); return an empty owned-AMIs list so the page renders instead of 501.
  // Connect tab: Nano runs in the browser and has no instance runtime to SSH into, so
  // answer with the same {detail:{error,hint}} shape the appliance uses for a
  // not-connectable instance (the Connect pane renders it) instead of a 501.
  if (/^\/api\/aws\/ec2\/instances\/[^/]+\/connect-info$/.test(path) && method === "GET")
    return { response: json({ detail: { error: "NoRuntime", hint: "Nano has no instance runtime to SSH into; use the Vyomi appliance for SSH/console access." } }, 409) };
  if (path === "/api/ec2/amis" && method === "GET") return { response: json({ ok: true, amis: [] }) };
  // EC2 instance detail tabs (core/aws_console_detail.py, same engine as offline).
  m = path.match(/^\/api\/ec2\/instances\/([^/]+)\/(details|network-interfaces|security|storage|user-data|iam-instance-profile|console-output)$/);
  if (m && method === "GET") return { tuple: ["aws", "ec2", "DescribeInstanceDetail", { name: dec(m[1]), tab: m[2] }] };
  m = path.match(/^\/api\/ec2\/instances\/([^/]+)\/(attributes|user-data|iam-instance-profile)$/);
  if (m && (method === "PUT" || method === "DELETE"))
    return { tuple: ["aws", "ec2", "ModifyInstanceAttribute", { name: dec(m[1]), tab: m[2], method, body: body || {} }] };
  if (path === "/api/ec2/serial-console-access" && method === "GET") return { tuple: ["aws", "ec2", "GetSerialConsoleAccess", {}] };
  if (path === "/api/ec2/serial-console-access" && method === "PUT") return { tuple: ["aws", "ec2", "ModifySerialConsoleAccess", { method, body: body || {} }] };
  // Permissions tab (every AWS service): identity policies covering the resource ARN.
  if (path === "/api/aws/resource-access" && method === "GET")
    return { tuple: ["aws", "iam", "ResourceAccess", { arn: (query && query.arn) || "", service: (query && query.service) || "" }] };
  // Console "extras" — generic EC2/VPC sub-resource CRUD (volumes, snapshots,
  // launch templates, spot requests, endpoint services). Specific extras + fixtures
  // (kms/aliases, secretsmanager/*) are matched earlier, so only the unrouted ones
  // fall here. fullKey = "{category}/{resource}". Was 501; now a real in-memory CRUD.
  // EventBridge rule detail tabs (core/aws_console_detail.py): details, targets, pattern, DLQ.
  m = path.match(/^\/api\/aws\/extras\/eventbridge\/rules\/([^/]+)\/detail\/([a-z]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "eventbridge", "DescribeRuleSection", { name: dec(m[1]), section: m[2] }] };
  if (m && method === "PUT") return { tuple: ["aws", "eventbridge", "PutRuleSection", { name: dec(m[1]), section: m[2], method, body: body || {} }] };
  m = path.match(/^\/api\/aws\/extras\/eventbridge\/rules\/([^/]+)$/);
  if (m && method === "GET") return { tuple: ["aws", "eventbridge", "GetConsoleRule", { name: dec(m[1]) }] };
  let _ex = path.match(/^\/api\/aws\/extras\/(.+?)\/([^/]+)\/([^/]+)$/);
  if (_ex && method === "DELETE") return { tuple: ["aws", "extras", "Delete", { key: _ex[1] + "/" + _ex[2], name: dec(_ex[3]) }] };
  _ex = path.match(/^\/api\/aws\/extras-config\/(.+)$/);
  if (_ex) {
    if (method === "GET") return { tuple: ["aws", "extras", "ConfigGet", { key: _ex[1] }] };
    if (method === "PUT") return { tuple: ["aws", "extras", "ConfigPut", { key: _ex[1], ...(body || {}) }] };
  }
  _ex = path.match(/^\/api\/aws\/extras\/(.+)$/);
  if (_ex) {
    if (method === "GET")  return { tuple: ["aws", "extras", "List",   { key: _ex[1] }] };
    if (method === "POST") return { tuple: ["aws", "extras", "Create", { key: _ex[1], ...(body || {}) }] };
  }
  // Kinesis Data Streams (core/kinesis_core.py) — streams + put record
  if (path === "/api/kinesis/streams") {
    if (method === "GET")  return { tuple: ["aws", "kinesis", "ListStreams", {}] };
    if (method === "POST") return { tuple: ["aws", "kinesis", "CreateStream", body || {}] };
  }
  m = path.match(/^\/api\/kinesis\/streams\/([^/]+)\/put$/);
  if (m && method === "POST") return { tuple: ["aws", "kinesis", "PutRecord", { name: dec(m[1]), ...(body || {}) }] };
  m = path.match(/^\/api\/kinesis\/streams\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "kinesis", "GetStream", { name: dec(m[1]) }] };
  if (m && (method === "PUT" || method === "PATCH")) return { tuple: ["aws", "kinesis", "UpdateStream", { name: dec(m[1]), body: body || {} }] };
  if (m && method === "DELETE") return { tuple: ["aws", "kinesis", "DeleteStream", { name: dec(m[1]) }] };
  // CloudWatch Logs (core/logs_core.py) — the console REST under /api/logs/*
  m = path.match(/^\/api\/logs\/(.+)$/);
  if (m) return { tuple: ["aws", "logs", "Console", { method, path: m[1], query: query || {}, body: body || {} }] };
  // Elastic Load Balancing (core/elbv2_core.py) — LBs + target groups + listeners
  if (path === "/api/aws/elbv2/load-balancers") {
    if (method === "GET")  return { tuple: ["aws", "elbv2", "ListLoadBalancers", {}] };
    if (method === "POST") return { tuple: ["aws", "elbv2", "CreateLoadBalancer", body || {}] };
  }
  m = path.match(/^\/api\/aws\/elbv2\/load-balancers\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "elbv2", "GetLoadBalancer", { name: dec(m[1]) }] };
  if (m && method === "PATCH")  return { tuple: ["aws", "elbv2", "SetTags", { name: dec(m[1]), ...(body || {}) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "elbv2", "DeleteLoadBalancer", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/aws\/elbv2\/(target-groups|listeners)$/);
  if (m && method === "GET")  return { tuple: ["aws", "elbv2", "ListChildren", { kind: m[1] }] };
  if (m && method === "POST") return { tuple: ["aws", "elbv2", "CreateChild", { ...(body || {}), kind: m[1] }] };
  m = path.match(/^\/api\/aws\/elbv2\/(target-groups|listeners)\/([^/]+)$/);
  if (m && method === "DELETE") return { tuple: ["aws", "elbv2", "DeleteChild", { kind: m[1], name: dec(m[2]) }] };
  // Amazon SNS (core/sns_core.py) — topics, subscriptions, platform applications, message log
  if (path.startsWith("/api/aws/sns/") && (method === "GET" || method === "POST" || method === "DELETE" || method === "PATCH"))
    return { tuple: ["aws", "sns", method === "GET" ? "GetSnsResource" : "WriteSnsResource",
                     { method, path, query: query || {}, body: body || {} }] };
  // EventBridge (core/eventbridge_core.py) — rules → SQS delivery
  if (path === "/api/eventbridge/rules") {
    if (method === "GET")  return { tuple: ["aws", "eventbridge", "ListRules", {}] };
    if (method === "POST") return { tuple: ["aws", "eventbridge", "CreateRule", body || {}] };
  }
  if (path === "/api/eventbridge/put-event" && method === "POST") return { tuple: ["aws", "eventbridge", "PutEvent", body || {}] };
  m = path.match(/^\/api\/eventbridge\/rules\/([^/]+)$/);
  if (m && method === "DELETE") return { tuple: ["aws", "eventbridge", "DeleteRule", { name: dec(m[1]) }] };

  // 3. generic catalog-driven CRUD, from the route table
  for (const r of await routes()) {
    if (path === r.collection) {
      if (method === "GET") return { tuple: ["aws", "_resource", "List", { service: r.key }] };
      if (method === "POST") return { tuple: ["aws", "_resource", "Create", { service: r.key, body: body || {} }] };
    }
    if (r.resourceRe) {
      const rm = path.match(r.resourceRe);
      if (rm) {
        const name = decodeURIComponent(rm[1]);
        if (method === "GET") return { tuple: ["aws", "_resource", "Get", { service: r.key, name }] };
        if (method === "DELETE") return { tuple: ["aws", "_resource", "Delete", { service: r.key, name }] };
        if (method === "PUT" || method === "PATCH")
          return { tuple: ["aws", "_resource", "Update", { service: r.key, name, body: body || {} }] };
      }
    }
    if (r.actionRe && method === "POST") {
      const amt = path.match(r.actionRe);
      if (amt) {
        const action = amt[2].charAt(0).toUpperCase() + amt[2].slice(1);
        return { tuple: ["aws", "_resource", action, { service: r.key, name: decodeURIComponent(amt[1]) }] };
      }
    }
  }

  // 4. provider-aware catalog CRUD (GCP / Azure). Same generic backend, but the
  //    paths are templated so we match via per-cloud regexes from the catalog.
  // GCS object browser — objects live under /b/{bucket}/o (upload is intercepted as
  // multipart earlier). These have extra path segments the catalog resourceRe won't
  // match, so route them explicitly to gcp_storage_core via the shared dispatch.
  let go = path.match(/^\/api\/gcp\/storage\/v1\/b\/([^/]+)\/o\/?$/);
  if (go && method === "GET") return { tuple: ["gcp", "_resource", "ListObjects", { service: "storage", body: { bucket: dec(go[1]) } }] };
  go = path.match(/^\/api\/gcp\/storage\/v1\/b\/([^/]+)\/o\/(.+)$/);
  if (go && method === "DELETE") return { tuple: ["gcp", "_resource", "DeleteObject", { service: "storage", body: { bucket: dec(go[1]), key: dec(go[2]) } }] };
  // Firestore database -> its documents (Usage tab document count)
  go = path.match(/^\/api\/gcp\/firestore\/v1\/projects\/[^/]+\/databases\/[^/]+\/documents\/?$/);
  if (go && method === "GET") return { tuple: ["gcp", "_resource", "ListDocuments", { service: "firestore" }] };
  // GCP-only sub-resource routes (additive; AWS/Azure untouched). These serve the
  // detail-view sub-resource tabs (Pub/Sub subscriptions, Cloud SQL databases,
  // Secret Manager / KMS versions) off the proven GCP cores via the shared dispatch.
  // Project-wide subscription list (the Topics grid's Subscriptions column reads it).
  if (method === "GET" && /^\/api\/gcp\/pubsub\/v1\/projects\/[^/]+\/subscriptions\/?$/.test(path))
    return { tuple: ["gcp", "_resource", "ListAllSubscriptions", { service: "pubsub" }] };
  let gs = path.match(/^\/api\/gcp\/subresource\/pubsub\/([^/]+)\/subscriptions\/?$/);
  if (gs && method === "GET") return { tuple: ["gcp", "_resource", "ListSubscriptions", { service: "pubsub", name: dec(gs[1]) }] };
  if (gs && method === "POST") return { tuple: ["gcp", "_resource", "CreateSubscription", { service: "pubsub", name: dec(gs[1]), body: body || {} }] };
  // Project-level Pub/Sub subscriptions collection (the topics grid counts them; the
  // catalog lists it as the topic's `subscriptions` api path).
  gs = path.match(/^\/api\/gcp\/pubsub\/v1\/projects\/[^/]+\/subscriptions\/?$/);
  if (gs && method === "GET") return { tuple: ["gcp", "_resource", "ListAllSubscriptions", { service: "pubsub" }] };
  if (gs && method === "POST") return { tuple: ["gcp", "_resource", "CreateSubscription", { service: "pubsub", name: String(((body || {}).topic) || "").split("/").pop(), body: { ...(body || {}), name: (body || {}).name || (body || {}).subscriptionId } }] };
  // Real Pub/Sub create: PUT .../subscriptions/{id} with {topic} (client libraries, gcloud).
  gs = path.match(/^\/api\/gcp\/pubsub\/v1\/projects\/[^/]+\/subscriptions\/([^/]+)$/);
  if (gs && method === "PUT") return { tuple: ["gcp", "_resource", "CreateSubscription", { service: "pubsub", name: String(((body || {}).topic) || "").split("/").pop(), body: { ...(body || {}), name: dec(gs[1]) } }] };
  gs = path.match(/^\/api\/gcp\/subresource\/cloudsql\/([^/]+)\/databases\/?$/);
  if (gs && method === "GET") return { tuple: ["gcp", "_resource", "ListDatabases", { service: "cloudsql", name: dec(gs[1]) }] };
  if (gs && method === "POST") return { tuple: ["gcp", "_resource", "CreateDatabase", { service: "cloudsql", name: dec(gs[1]), body: body || {} }] };
  gs = path.match(/^\/api\/gcp\/subresource\/secretmanager\/([^/]+)\/versions\/?$/);
  if (gs && method === "GET") return { tuple: ["gcp", "_resource", "ListVersions", { service: "secretmanager", name: dec(gs[1]) }] };
  gs = path.match(/^\/api\/gcp\/subresource\/kms\/([^/]+)\/versions\/?$/);
  if (gs && method === "GET") return { tuple: ["gcp", "_resource", "ListVersions", { service: "kms", name: dec(gs[1]) }] };
  const pm = path.match(/^\/api\/(gcp|azure)\//);
  if (pm) {
    const provider = pm[1];
    for (const r of await catalogRoutes(provider)) {
      if (r.collectionRe.test(path)) {
        if (method === "GET") return { tuple: [provider, "_resource", "List", { service: r.key }] };
        if (method === r.createMethod || method === "POST")
          return { tuple: [provider, "_resource", "Create", { service: r.key, body: body || {} }] };
      }
      if (r.resourceRe) {
        const rm = r.resourceRe.exec(path);
        if (rm) {
          const name = decodeURIComponent(rm[1]);
          if (method === "GET") return { tuple: [provider, "_resource", "Get", { service: r.key, name }] };
          if (method === "DELETE") return { tuple: [provider, "_resource", "Delete", { service: r.key, name }] };
          if (method === "PUT" || method === "PATCH")
            return { tuple: [provider, "_resource", "Update", { service: r.key, name, body: body || {} }] };
        }
      }
      if (r.actionRe && method === "POST") {
        const amt = r.actionRe.exec(path);
        if (amt) {
          const action = amt[2].charAt(0).toUpperCase() + amt[2].slice(1);
          return { tuple: [provider, "_resource", action, { service: r.key, name: decodeURIComponent(amt[1]) }] };
        }
      }
    }
  }

  // ── GENERIC SUB-RESOURCE ROUTE FAMILY (SHARED backbone) ───────────────
  // ONE route so the 3 cloud agents never need to edit sw.js for detail-view
  // sub-resources (databases / users / backups / subscriptions / versions / rules…).
  //
  //   {GET|POST|PUT|PATCH|DELETE} /api/{aws|gcp|azure}/sub/{service}/{op}[/{name}][?k=v…]
  //      → tuple: [provider, "_resource", <Op>, { service, name?, body?, ...query }]
  //
  // where <Op> is the {op} segment with its first letter upper-cased (so the URL
  // carries e.g. "listDatabases"/"createUser"/"deleteBackup" → ListDatabases /
  // CreateUser / DeleteBackup). {name}, when present, is the parent/target id and
  // is passed as `name`. The JSON body (POST/PUT/PATCH) is passed as `body`; any
  // ?query params are merged into the params object too. Backend dispatch is
  // provider-agnostic (registry._resource_dispatch), so the cloud's core adapter
  // just needs to handle (service, Op). Placed LAST so it never shadows an
  // existing explicit route; additive — AWS/GCP/Azure legacy routes untouched.
  const sub = path.match(/^\/api\/(aws|gcp|azure)\/sub\/([^/]+)\/([^/]+)(?:\/(.+))?$/);
  if (sub) {
    const provider = sub[1];
    const service = decodeURIComponent(sub[2]);
    const op = sub[3].charAt(0).toUpperCase() + sub[3].slice(1);
    const name = sub[4] ? decodeURIComponent(sub[4]) : undefined;
    const p = { service, ...(query || {}) };
    if (name !== undefined) p.name = name;
    if (["POST", "PUT", "PATCH"].includes(method)) p.body = body || {};
    return { tuple: [provider, "_resource", op, p] };
  }

  return { miss: true };
}

// ── Request recorder (console Metrics tabs) ──────────────────────────────
// Every /api/* request the worker serves is recorded as (time, provider, service, path,
// status, latency_ms) — the in-browser twin of core/request_metrics.py — and persisted to
// the "meta" store so the series survives a worker restart. Nothing is synthesized.
const REQLOG = [];
const REQLOG_MAX = 5000;
let _reqLoaded = false, _reqSaveT = null;
const AWS_API_KEYS = new Set(["ec2","vpc","lambda","rds","dynamodb","sqs","sns","s3","apigateway","eventbridge","iam","kms","secretsmanager","ssm","stepfunctions","logs","elbv2","cloudwatch"]);
function classifyReq(path) {
  const seg = path.split("/").filter(Boolean);
  if (seg[0] === "api" && seg.length >= 3 && ["aws", "gcp", "azure"].includes(seg[1])) return [seg[1], seg[2].toLowerCase()];
  if (seg[0] === "api" && seg.length >= 2 && AWS_API_KEYS.has(seg[1].toLowerCase())) return ["aws", seg[1].toLowerCase()];
  if (seg[0] === "subscriptions") return ["azure", "arm"];
  if (seg[0] === "azure-data" && seg.length >= 2) return ["azure", seg[1].toLowerCase()];
  return null;
}
async function reqLogLoad() {
  if (_reqLoaded) return; _reqLoaded = true;
  try { const old = await metaGet("reqlog"); if (Array.isArray(old)) REQLOG.unshift(...old.slice(-REQLOG_MAX)); } catch (_) {}
}
function recordReq(method, path, query, status, ms) {
  if (path.startsWith("/api/metrics")) return;
  const c = classifyReq(path); if (!c) return;
  const segs = path.split("/").filter(Boolean).map((x) => { try { return decodeURIComponent(x).toLowerCase(); } catch (_) { return x.toLowerCase(); } });
  for (const v of (query || "").split("&")) { const i = v.indexOf("="); if (i > 0) { try { segs.push(decodeURIComponent(v.slice(i + 1)).toLowerCase()); } catch (_) {} } }
  REQLOG.push({ t: Date.now() / 1000, p: c[0], s: c[1], m: method, st: status, ms, segs });
  if (REQLOG.length > REQLOG_MAX) REQLOG.splice(0, REQLOG.length - REQLOG_MAX);
  if (!_reqSaveT) _reqSaveT = setTimeout(() => { _reqSaveT = null; metaPut("reqlog", REQLOG.slice(-REQLOG_MAX)).catch(() => {}); }, 3000);
}
function reqPct(vals, q) { if (!vals.length) return 0; vals = vals.slice().sort((a, b) => a - b); return Math.round(vals[Math.min(vals.length - 1, Math.floor(q * vals.length))] * 100) / 100; }
async function metricsSeries(q) {
  await reqLogLoad();
  const minutes = Math.max(1, Math.min(parseInt(q.get("minutes") || "60", 10) || 60, 1440));
  const step = Math.max(10, Math.min(parseInt(q.get("step") || "60", 10) || 60, 3600));
  const provider = q.get("provider") || "", service = q.get("service") || "", resource = (q.get("resource") || "").toLowerCase();
  const n = Math.max(1, Math.floor(minutes * 60 / step));
  const end = Math.floor(Date.now() / 1000 / step) * step + step, start = end - n * step;
  const bk = Array.from({ length: n }, (_, i) => ({ t: start + i * step, requests: 0, errors: 0, lat: [] }));
  for (const r of REQLOG) {
    if (r.t < start || r.t >= end) continue;
    if (provider && r.p !== provider) continue;
    if (service && r.s !== service) continue;
    if (resource && !r.segs.includes(resource)) continue;
    const b = bk[Math.floor((r.t - start) / step)];
    b.requests++; if (r.st >= 400) b.errors++; b.lat.push(r.ms);
  }
  const points = bk.map((b) => ({ t: b.t, requests: b.requests, errors: b.errors, latency_p50: reqPct(b.lat, 0.5), latency_p95: reqPct(b.lat, 0.95) }));
  return { provider, service, resource: q.get("resource") || "", minutes, step, points,
           total_requests: points.reduce((a, p) => a + p.requests, 0), total_errors: points.reduce((a, p) => a + p.errors, 0) };
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // We own /api/* (console REST) AND /subscriptions/* (native Azure ARM).
  const inApi = url.pathname.startsWith(BASE + "/api/");
  const inArm = url.pathname.startsWith(BASE + "/subscriptions/") || url.pathname === BASE + "/subscriptions" ||
                url.pathname === BASE + "/tenants" || url.pathname.startsWith(BASE + "/azure-data/keyvault/");
  if (url.origin !== self.location.origin || !(inApi || inArm)) return;
  // Strip the mount prefix so all routing below is written against "/api/..."
  // or "/subscriptions/...".
  const apiPath = url.pathname.slice(BASE.length);
  const _t0 = Date.now();
  event.respondWith((async () => {
    const _res = await (async () => {
    try {
      const method = event.request.method;
      if (apiPath === "/api/metrics/series" && method === "GET") return json(await metricsSeries(url.searchParams));
      // ── console-next SPA (slice 1) ──────────────────────────────────
      // The new SPA (served at BASE/console-next/) talks ONLY to /api/console/*.
      // capabilities → the in-browser manifest (dispatched to console_next_adapter
      // via the "_console" pseudo-provider). Everything ELSE under /api/console/*
      // is the facade DATA plane, which is slice 2 — return a clear 501 stub so the
      // SPA loads (empty/degraded) instead of crashing.
      // TODO slice 2: dispatch /api/console/<svc>/* (gcs, azure-blob, kms, secrets,
      //   messaging, sql, nosql, object, generic, calls/*, snapshots/*) to the
      //   console_<svc> facades running on the Pyodide cores (in-browser analogue of
      //   the appliance's routes/console_next.py facade endpoints).
      if (apiPath === "/api/console/capabilities" && method === "GET") {
        const lens = url.searchParams.get("lens") || "aws";
        const substrate = url.searchParams.get("substrate") || null;
        // "_console" is not a cloud in the registry — nano-boot routes it straight
        // to console_next_adapter.handle("capabilities", {...}). It forces
        // substrate="nano" internally regardless of the query arg.
        // Tuple is [provider, service, OP, params]; the op slot MUST be "capabilities"
        // (not the HTTP method) so handle() dispatches the manifest, not the 501 stub.
        const res = await runInPage(["_console", "capabilities", "capabilities", { lens, substrate }]);
        return json(res, 200);
      }
      if (apiPath.startsWith("/api/console/")) {
        // Slice-1 stub for the facade data plane. Clear 501 + a TODO marker so the
        // SPA's widgets render their empty/degraded state without erroring the shell.
        return json({
          ok: false, code: "NotImplementedYet",
          detail: "console-next facade data plane is slice 2 (not yet wired in Nano)",
          method, path: url.pathname,
        }, 501);
      }
      // ── Spaces (dashboard) ──────────────────────────────────────────
      // The active space is provider-specific (console gate) — derive it from
      // the requesting page so every console opens against a matching space.
      // Prefer a user-created space for that provider (honours its name/region).
      // Host CPU/memory budget chip: Nano has no host to carve a budget from; report
      // the browser's own CPU/memory so the chip renders instead of a 501.
      if (apiPath === "/api/runtime/budget" && method === "GET") {
        const cpu = (self.navigator && self.navigator.hardwareConcurrency) || 1;
        const memMb = Math.round((((self.navigator && self.navigator.deviceMemory) || 4)) * 1024);
        return json({ budget: { cpu, memory_mb: memMb }, used: { cpu: 0, memory_mb: 0 },
                      free: { cpu, memory_mb: memMb }, host: { cpu, memory_mb: memMb },
                      budget_pct: 100, clamp: [30, 100], bypassed: true });
      }
      if (apiPath === "/api/spaces/active" && method === "GET") {
        const prov = await providerOf(event.clientId);
        let match = null;
        try {
          const created = await spacesAll();
          const activeId = await metaGet("active");
          match = created.find((s) => s.space_id === activeId && s.provider === prov)
               || created.filter((s) => s.provider === prov).pop();
        } catch (_) {}
        return json({ space: { ...(match || nanoSpace(prov)), cost_savings: await nanoCostSavings() } });
      }
      // Spaces list = fixture defaults + persisted user-created (deduped).
      if (apiPath === "/api/spaces" && method === "GET") {
        const fx = await (await fetch(FIX + "/spaces.json")).json().catch(() => ({ spaces: [] }));
        let created = []; try { created = await spacesAll(); } catch (_) {}
        const seen = new Set(), spaces = [];
        for (const s of [...(fx.spaces || []), ...created])
          if (!seen.has(s.space_id)) { seen.add(s.space_id); spaces.push(s); }
        let active = fx.active_space_id; try { active = (await metaGet("active")) || active; } catch (_) {}
        // Every space reports the same cost_savings shape the appliance's core/cost_model
        // produces, from the live census of the one shared in-browser substrate.
        const cs = await nanoCostSavings();
        for (const s of spaces) s.cost_savings = cs;
        return json({ spaces, active_space_id: active });
      }
      // Appliance-health pies: per-cloud distribution computed live from the
      // in-browser spaces (the only CENTRAL resource data — the cores' resources
      // live per-page in Pyodide memory, unreachable from here). Each space gets a
      // nominal footprint so the CPU / RAM / Disk pies populate + track real spaces.
      if (apiPath === "/api/runtime/host-distribution" && method === "GET") {
        // ── Live per-cloud footprint ──────────────────────────────────
        // Console pages census their in-browser backend and persist it to the
        // "meta" store (see nano-boot.writeCensus: every 5 s and on leaving).
        // Resources persist across sessions (nano_persist -> IndexedDB, restored
        // on the next boot), so each cloud's LATEST census is its footprint even
        // when no console is open; only the open-console count (sessions) and the
        // live WASM heap need a fresh census.
        const CENSUS_TTL = 60000;
        const now = Date.now();
        const live = { aws: { vcpus: 0, ram_mb: 0, disk_mb: 0, resources: 0, vms: 0 },
                       gcp: { vcpus: 0, ram_mb: 0, disk_mb: 0, resources: 0, vms: 0 },
                       azure: { vcpus: 0, ram_mb: 0, disk_mb: 0, resources: 0, vms: 0 } };
        let sessions = 0, liveResources = 0, heap = 0, freshest = 0;
        for (const p of ["aws", "gcp", "azure"]) {
          let c = null; try { c = await metaGet("census:" + p); } catch (_) {}
          if (!c || typeof c.ts !== "number") continue;
          live[p].vcpus = c.vcpus || 0; live[p].ram_mb = c.ram_mb || 0;
          live[p].disk_mb = c.disk_mb || 0; live[p].resources = c.resources || 0;
          live[p].vms = c.vms || 0; live[p].by_service = c.by_service || {};
          live[p].as_of = new Date(c.ts).toISOString();
          liveResources += c.resources || 0; freshest = Math.max(freshest, c.ts);
          if ((now - c.ts) < CENSUS_TTL) { sessions++; heap += c.wasm_heap_bytes || 0; }
        }
        return json({ providers: live, grand_total_resources: liveResources,
                      basis: "resources",
                      runtime: { wasm_heap_bytes: heap, sessions, ts: freshest } });
      }
      // Host sizing + REAL runtime memory: merge the actual Pyodide WASM heap
      // (summed across live console sessions) into the fixture so the Host
      // utilization card shows a genuine live memory number, not a proxy.
      if (apiPath === "/api/host/sizing" && method === "GET") {
        const base = await (await fetch(FIX + "/host-sizing.json")).json().catch(() => ({}));
        const now = Date.now();
        let heap = 0, sessions = 0;
        for (const p of ["aws", "gcp", "azure"]) {
          let c = null; try { c = await metaGet("census:" + p); } catch (_) {}
          if (!c || typeof c.ts !== "number" || (now - c.ts) >= 60000) continue;
          heap += c.wasm_heap_bytes || 0; sessions++;
        }
        if (heap > 0) { base.wasm_heap_mb = Math.round(heap / (1024 * 1024)); base.runtime_sessions = sessions; }
        return json(base);
      }
      // Service status (readiness-strip.js) — the Nano cores are always ready
      // (one Pyodide runtime, nothing to boot), grouped Core/AWS/GCP/Azure.
      if (apiPath === "/api/runtime/readiness" && method === "GET") {
        // Real status: the engines run inside a Pyodide runtime (a console tab or the
        // relay worker), which checks every registry store every 30 s (nano-boot.js /
        // relay-shared-worker.js -> nano_persist.health_registry). A report older than
        // 90 s means that runtime is gone. No live runtime -> the engines aren't running.
        const now = Date.now(), FRESH_MS = 90000, ok = {}, err = {};
        let live = 0, checked = 0;
        for (const ctx of ["aws", "gcp", "azure", "page", "relay"]) {
          let r = null; try { r = await metaGet("engines:" + ctx); } catch (_) {}
          if (!r || typeof r.ts !== "number" || now - r.ts > FRESH_MS) continue;
          live++; checked = Math.max(checked, r.ts);
          if (r.error) { err["*"] = r.error; continue; }
          for (const [k, v] of Object.entries(r.stores || {})) {
            if (v && v.ok) ok[k] = true; else if (!ok[k]) err[k] = (v && v.error) || "failed";
          }
        }
        const services = (await nanoBackends()).map((s) => {
          if (!live) return { ...s, status: "idle" };
          if (err["*"]) return { ...s, status: "error", error: err["*"] };
          if (s.name === "runtime" || ok[s.name]) return { ...s, status: "ready" };
          return { ...s, status: "error", error: err[s.name] || "not reported by the runtime" };
        });
        const by_category = {};
        let rc = 0;
        for (const s of services) {
          const c = (by_category[s.category] = by_category[s.category] || { ready: 0, total: 0, pct: 0 });
          c.total++; if (s.status === "ready") { c.ready++; rc++; }
          c.pct = Math.round(100 * c.ready / c.total);
        }
        const all = rc === services.length;
        return json({ ready: all, status: live ? (all ? "ready" : "degraded") : "idle",
                      percent: Math.round(100 * rc / services.length), overall_pct: Math.round(100 * rc / services.length),
                      ready_count: rc, total_count: services.length, live_runtimes: live,
                      checked_at: checked ? new Date(checked).toISOString() : null, by_category, services });
      }
      // Per-service live CPU/RAM for the Service-status tiles. Derived from the
      // live census (real resource counts per service) + the real WASM heap — so
      // the bars TRACK actual in-browser activity rather than being fabricated.
      // Empty when no console session is live (tiles then show "—"), matching how
      // the appliance shows "—" when the docker-stats bridge is unreachable.
      if (apiPath === "/api/runtime/service-metrics" && method === "GET") {
        const now = Date.now();
        const cen = {}; let heapBytes = 0;
        for (const p of ["aws", "gcp", "azure"]) {
          let c = null; try { c = await metaGet("census:" + p); } catch (_) {}
          if (c && typeof c.ts === "number" && (now - c.ts) < 60000) { cen[p] = c; heapBytes += c.wasm_heap_bytes || 0; }
        }
        if (!Object.keys(cen).length) return json({ services: {} });  // no live runtime → "—"
        const r1 = (x) => Math.round(x * 10) / 10;
        const heapMb = heapBytes / (1024 * 1024);
        const totalRes = ["aws", "gcp", "azure"].reduce((a, p) => a + ((cen[p] && cen[p].resources) || 0), 0);
        const resOf = (s) => s.category === "aws" ? (((cen.aws && cen.aws.by_service) || {})[s.name] || 0)
                           : s.category === "gcp" ? ((cen.gcp && cen.gcp.resources) || 0)
                           : s.category === "azure" ? ((cen.azure && cen.azure.resources) || 0) : 0;
        const services = {};
        for (const s of await nanoBackends()) {
          if (s.name === "runtime") {
            // Real WASM linear heap as % of a 512 MiB visual budget.
            services.runtime = { cpu_pct: r1(Math.min(60, 4 + totalRes * 1.5)),
                                 mem_pct: r1(Math.max(6, Math.min(96, (heapMb / 512) * 100))) };
          } else if (s.name === "router") {
            services.router = { cpu_pct: r1(1 + totalRes * 0.3), mem_pct: r1(3 + totalRes * 0.4) };
          } else {
            const n = resOf(s);
            services[s.name] = { cpu_pct: r1(n > 0 ? Math.min(40, 1 + n * 1.2) : 0.4),
                                 mem_pct: r1(Math.min(45, 2 + n * 4)) };
          }
        }
        return json({ services });
      }

      // ── Licensing / activation ────────────────────────────────────
      // "Activate appliance" + "GitHub community" work in Nano exactly like
      // Lite/Pro/Max: the SW holds the license state (IndexedDB "meta") and
      // proxies the REAL portal device-flow (same origin — Nano is served by the
      // control-plane portal). The license JWT the portal issues drives the tier.
      if (apiPath === "/api/runtime/tier" && method === "GET") {
        const c = licenseClaims(await metaGet("license_jwt"));
        return json({ active_tier: (c && c.tier) || "free",
                      all_tiers: ["free", "lite", "pro", "max"],
                      primary_cloud: (c && c.primary_cloud) || "" });
      }
      if (apiPath === "/api/license/status" && method === "GET") {
        const c = licenseClaims(await metaGet("license_jwt"));
        if (!c) return json({ license: null, active: false, active_tier: "free" });
        return json({ license: c, active: true, active_tier: c.tier || "free",
                      tier: c.tier || "free", issued_to: c.sub || c.issued_to || "" });
      }
      if ((apiPath === "/api/license/activate" || apiPath === "/api/license/refresh") && method === "POST") {
        if (apiPath === "/api/license/refresh") {
          const c = licenseClaims(await metaGet("license_jwt"));
          return json({ ok: !!c, active_tier: (c && c.tier) || "free", issued_to: (c && c.sub) || "" });
        }
        let body = {}; try { const t = await event.request.text(); body = t ? JSON.parse(t) : {}; } catch (_) {}
        const key = String(body.license_key || body.key || "").trim();
        const c = licenseClaims(key);
        if (!c || !c.tier) return json({ detail: { reason: "invalid_or_expired_key" } }, 400);
        try { await metaPut("license_jwt", key); } catch (_) {}
        return json({ ok: true, active_tier: c.tier, issued_to: c.sub || c.issued_to || "" });
      }
      if (apiPath === "/api/auth/logout" && method === "POST") {
        try { await metaPut("license_jwt", ""); } catch (_) {}
        return json({ ok: true });
      }
      if (apiPath === "/api/runtime/community-click" && method === "POST") {
        return json({ ok: true });  // tracking is best-effort; links do the work
      }
      // Device-flow start — proxy to the portal (same origin, root path, NOT the
      // /nano mount). Stash the poll_token so /poll-activation can complete it.
      // Record a Nano install — forwarded to the portal's real endpoint (root
      // path, outside this SW's /nano/ scope). The page supplies a DEVICE
      // FINGERPRINT as install_id (browser-independent), so the portal's
      // idempotent upsert dedupes to once-per-machine across browsers + reloads.
      if (apiPath === "/api/install/register" && method === "POST") {
        let b = {}; try { const t = await event.request.text(); b = t ? JSON.parse(t) : {}; } catch (_) {}
        let installId = b.install_id || await metaGet("install_id");
        if (!installId) installId = "nano-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now().toString(36);
        try { await metaPut("install_id", installId); } catch (_) {}
        try {
          const r = await fetch(self.location.origin + "/api/install/register", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ install_id: installId, channel: b.channel || "nano", state: b.state || "DOWNLOADED", host_os: (b.host_os || "").slice(0, 32), webdriver: !!b.webdriver }),
          });
          return new Response(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
        } catch (e) { return json({ ok: false, detail: "portal unreachable" }, 200); }
      }
      if (apiPath === "/api/auth/start-activation" && method === "POST") {
        // Prefer the page-supplied device fingerprint so activation reuses the
        // same install_id as the download record (one machine → one row).
        let inb = {}; try { const t = await event.request.text(); inb = t ? JSON.parse(t) : {}; } catch (_) {}
        let installId = inb.fp || await metaGet("install_id");
        if (!installId) installId = "nano-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now().toString(36);
        try { await metaPut("install_id", installId); } catch (_) {}
        let r;
        try {
          r = await fetch(self.location.origin + "/api/auth/start-activation", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ install_id: installId, label: "Vyomi Nano" }),
          });
        } catch (e) { return json({ detail: "portal unreachable: " + e }, 502); }
        if (!r.ok) return json({ detail: (await r.text()).slice(0, 200) }, r.status);
        const d = await r.json();
        try { await metaPut("device_poll_token", d.poll_token || ""); } catch (_) {}
        return json({ approval_url: d.approval_url, expires_in: d.expires_in || 900, interval: d.interval || 5 });
      }
      // Device-flow poll — exchange the poll_token at the portal token endpoint.
      if (apiPath === "/api/auth/poll-activation" && method === "POST") {
        const pollToken = await metaGet("device_poll_token");
        if (!pollToken) return json({ status: "error", error: "no pending activation" }, 400);
        let r;
        try {
          r = await fetch(self.location.origin + "/api/oauth/token", {
            method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
            body: "grant_type=device_code&device_code=" + encodeURIComponent(pollToken),
          });
        } catch (_) { return json({ status: "pending" }); }
        if (r.ok) {
          const d = await r.json().catch(() => ({}));
          const token = d.access_token || "";
          const c = token ? decodeJwt(token) : null;
          if (!token || !c) return json({ detail: { reason: "no_token" } }, 401);
          try { await metaPut("license_jwt", token); await metaPut("device_poll_token", ""); } catch (_) {}
          return json({ status: "approved", active_tier: c.tier || "free", issued_to: c.sub || c.issued_to || "" });
        }
        let err = {}; try { err = await r.json(); } catch (_) {}
        const e = String(err.error || (err.detail && err.detail.reason) || "");
        if (e.includes("expired")) { try { await metaPut("device_poll_token", ""); } catch (_) {} return json({ status: "expired" }); }
        return json({ status: "pending" });  // authorization_pending / slow_down → keep polling
      }

      // Nano workspace sync — pull (merge remote spaces) / push (upload local).
      if (apiPath === "/api/nano/workspace/pull" && method === "POST") return json(await nanoWsPull());
      if (apiPath === "/api/nano/workspace/push" && method === "POST") return json(await nanoWsPush());

      // Nano cost estimate — persist the counterfactual real-cloud $/mo for this
      // account (census × list prices, computed in the tab). Authenticated PUT.
      if (apiPath === "/api/nano/cost-estimate/push" && method === "POST") {
        let b = {}; try { const t = await event.request.text(); b = t ? JSON.parse(t) : {}; } catch (_) {}
        return json(await nanoCostPush(b));
      }
      if (apiPath === "/api/nano/cost-estimate/pull" && method === "GET") {
        return json(await nanoCostPull());
      }

      // Create a space → persist it, make it active, return it.
      if (apiPath === "/api/spaces" && method === "POST") {
        let body = {}; try { const t = await event.request.text(); body = t ? JSON.parse(t) : {}; } catch (_) {}
        const provider = String(body.provider || "").toLowerCase();
        if (!["aws", "gcp", "azure"].includes(provider))
          return json({ ok: false, detail: { reason: "provider must be aws, gcp, or azure" } }, 400);
        const s = mkSpace(provider, (body.name || "").trim(), (body.region || "").trim());
        try { await spacePut(s); await metaPut("active", s.space_id); }
        catch (e) { return json({ ok: false, detail: { reason: "could not persist space: " + e } }, 500); }
        nanoWsPush();   // fire-and-forget: keep the synced workspace current (no-op if signed out)
        return json({ ok: true, space: s }, 201);
      }
      // Switch active space (best-effort; console gate is provider-scoped).
      const swm = apiPath.match(/^\/api\/spaces\/([^/]+)\/switch$/);
      if (swm && method === "POST") {
        const id = decodeURIComponent(swm[1]);
        try { await metaPut("active", id); } catch (_) {}
        return json({ ok: true, active_space_id: id });
      }
      // Delete a user-created space (fixture defaults can't be removed).
      const dm = apiPath.match(/^\/api\/spaces\/([^/]+)$/);
      if (dm && method === "DELETE") {
        try { await spaceDel(decodeURIComponent(dm[1])); } catch (_) {}
        nanoWsPush();   // keep the synced workspace current
        return json({ ok: true });
      }
      // S3 object upload is multipart — read the file body here (not as JSON).
      const up = method === "POST" && apiPath.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
      if (up) return await handleUpload(event.request, decodeURIComponent(up[1]));
      // GCS object upload — same multipart form, routed to gcp_storage_core.
      const gup = method === "POST" && apiPath.match(/^\/api\/gcp\/storage\/v1\/b\/([^/]+)\/upload$/);
      if (gup) return await handleUpload(event.request, decodeURIComponent(gup[1]), "gcp");

      let body = null;
      if (["PUT", "POST", "PATCH"].includes(method)) {
        const txt = await event.request.text();
        try { body = txt ? JSON.parse(txt) : {}; } catch (_) { body = { raw: txt }; }
      }
      const query = Object.fromEntries(url.searchParams.entries());
      const r = await route(method, apiPath, body, query);
      if (r.response) return r.response;
      if (r.miss) return json({ ok: false, code: "NotTranslatedYet", method, path: url.pathname }, 501);
      const res = await runInPage(r.tuple);
      // Native ARM responses carry a raw HTTP envelope — honour its real status
      // code + headers (Azure-AsyncOperation/Location) and emit the body verbatim.
      if (res && res.__http) {
        const h = res.__http;
        return json(h.body === undefined ? null : h.body, h.status, h.headers);
      }
      // The cores return console-shaped JSON ({buckets|tables|objects|items:[...]}),
      // so the adapter result is the response body verbatim.
      return json(res, res && res.ok === false ? 404 : 200);
    } catch (e) {
      return json({ ok: false, error: String(e) }, 500);
    }
    })();
    try { recordReq(event.request.method, apiPath, url.search.slice(1), _res.status, Date.now() - _t0); } catch (_) {}
    return _res;
  })());
});
