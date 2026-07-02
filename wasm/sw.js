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
self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "pyodide-ready") _ready();
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
  "/api/cloudsim/events": { events: [] },
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

// Nano's in-WASM "backends" — the analogue of the appliance's OSS services
// (MinIO/DynamoDB-Local/Vault/... → in-browser cores). Grouped by the same
// Core/AWS/GCP/Azure categories the readiness strip tiles by. All are always
// "ready" (one Pyodide runtime, nothing to boot). service-metrics maps live
// CPU/RAM onto these `name`s from the census + WASM heap.
const NANO_SERVICES = [
  { name: "runtime",        label: "Pyodide runtime",     category: "core" },
  { name: "router",         label: "Conformance router",  category: "core" },
  { name: "s3",             label: "ObjectStore (S3)",    category: "aws" },
  { name: "dynamodb",       label: "NoSQL (DynamoDB)",    category: "aws" },
  { name: "kms",            label: "KMS engine",          category: "aws" },
  { name: "secretsmanager", label: "Secrets (KV)",        category: "aws" },
  { name: "sqs",            label: "Messaging (SQS/SNS)", category: "aws" },
  { name: "iam",            label: "IAM",                 category: "aws" },
  { name: "rds",            label: "SqlStore (RDS)",      category: "aws" },
  { name: "gcp",            label: "ResourceStore (GCP)", category: "gcp" },
  { name: "azure",          label: "ARM (Azure)",         category: "azure" },
];

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
async function handleUpload(request, bucket) {
  const fd = await request.formData();
  const files = fd.getAll("file").filter((f) => f && typeof f.arrayBuffer === "function");
  if (!files.length) return json({ ok: false, code: "NoFile" }, 400);
  const results = [];
  for (const file of files) {
    const b64 = b64FromBuf(await file.arrayBuffer());
    results.push(await runInPage(["aws", "s3", "PutObject", {
      bucket, key: file.name || "upload",
      body_b64: b64, content_type: file.type || "application/octet-stream",
    }]));
  }
  const ok = results.every((r) => r && r.ok !== false);
  return json({ ok, uploaded: results.length, results }, ok ? 200 : 400);
}

// Each console gates on an active space whose provider matches it. We derive
// the provider from the page making the request, so aws/gcp/azure consoles all
// pass their gate from the same in-browser substrate.
function nanoSpace(provider) {
  const acct = provider === "gcp" ? "nano-project" : provider === "azure" ? "nano-sub" : "000000000000";
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
  const all = await self.clients.matchAll({ includeUncontrolled: true });
  const client = all.find((c) => c.type === "window") || all[0];
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

  // 1.5 Azure ARM control plane — the Azure console speaks real ARM, not the
  //     generic /api/{cloud}/{service} scheme: /subscriptions/{sub}/resourceGroups/
  //     {rg}/providers/Microsoft.X/{type}/{name}?api-version=, plus the LRO poll at
  //     /api/azure/operations/{id}. The substrate-free AzureArm core serves both;
  //     its HTTP envelope (status + Azure-AsyncOperation/Location headers + body)
  //     is returned verbatim (see the __http handling in the fetch listener).
  if (path.startsWith("/subscriptions/") || path.startsWith("/api/azure/operations/")) {
    return { tuple: ["azure", "_arm", method, { path, query: query || {}, body: body || null }] };
  }

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
  if (m && (method === "PUT" || method === "POST"))
    return { tuple: ["aws", "s3", "PutVersioning", { bucket: dec(m[1]), status: (body && body.status) || "Enabled" }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "ListObjects", { bucket: dec(m[1]) }] };
  // (POST upload to this path is multipart — handled in the fetch listener.)
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/(.+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "s3", "GetObject", { bucket: dec(m[1]), key: m[2] }] };
  if (m && method === "DELETE") return { tuple: ["aws", "s3", "DeleteObject", { bucket: dec(m[1]), key: m[2] }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "s3", "GetBucket", { bucket: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "s3", "DeleteBucket", { bucket: dec(m[1]) }] };
  // ── DynamoDB ────────────────────────────────────────────────────────
  if (path === "/api/dynamodb/tables") {
    if (method === "GET")  return { tuple: ["aws", "dynamodb", "ListTables", {}] };
    if (method === "POST") return { tuple: ["aws", "dynamodb", "CreateTable", body || {}] };
  }
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
  if (path === "/api/iam/policies" && method === "GET") return { tuple: ["aws", "iam", "ListPolicies", {}] };
  if (path === "/api/iam/groups" && method === "GET")   return { tuple: ["aws", "iam", "ListGroups", {}] };
  if (path === "/api/iam/attachments" && method === "GET") return { tuple: ["aws", "iam", "ListAttachments", {}] };
  m = path.match(/^\/api\/iam\/users\/([^/]+)$/);
  if (m && method === "DELETE") return { tuple: ["aws", "iam", "DeleteUser", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/iam\/roles\/([^/]+)$/);
  if (m && method === "DELETE") return { tuple: ["aws", "iam", "DeleteRole", { name: dec(m[1]) }] };
  m = path.match(/^\/api\/iam\/policies\/([^/]+)$/);
  if (m && method === "DELETE") return { tuple: ["aws", "iam", "DeletePolicy", { name: dec(m[1]) }] };
  // ── RDS (core/rds_core.py) ──────────────────────────────────────────
  if (path === "/api/rds/databases") {
    if (method === "GET")  return { tuple: ["aws", "rds", "ListDatabases", {}] };
    if (method === "POST") return { tuple: ["aws", "rds", "CreateDatabase", body || {}] };
  }
  if (path === "/api/rds/snapshots" && method === "GET") return { tuple: ["aws", "rds", "Snapshots", {}] };
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
  m = path.match(/^\/api\/aws\/secrets\/(.+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "secrets", "GetSecret", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "secrets", "DeleteSecret", { name: dec(m[1]) }] };
  // ── KMS (core/kms_core.py) ──────────────────────────────────────────
  if (path === "/api/aws/kms/keys") {
    if (method === "GET")  return { tuple: ["aws", "kms", "ListKeys", {}] };
    if (method === "POST") return { tuple: ["aws", "kms", "CreateKey", body || {}] };
  }
  if (path === "/api/aws/extras/kms/aliases" && method === "GET") return { tuple: ["aws", "kms", "ListAliases", {}] };
  m = path.match(/^\/api\/aws\/kms\/keys\/([^/]+)$/);
  if (m && method === "GET")    return { tuple: ["aws", "kms", "GetKey", { name: dec(m[1]) }] };
  if (m && method === "DELETE") return { tuple: ["aws", "kms", "DeleteKey", { name: dec(m[1]) }] };

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
  }

  // 4. provider-aware catalog CRUD (GCP / Azure). Same generic backend, but the
  //    paths are templated so we match via per-cloud regexes from the catalog.
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
    }
  }
  return { miss: true };
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // We own /api/* (console REST) AND /subscriptions/* (native Azure ARM).
  const inApi = url.pathname.startsWith(BASE + "/api/");
  const inArm = url.pathname.startsWith(BASE + "/subscriptions/");
  if (url.origin !== self.location.origin || !(inApi || inArm)) return;
  // Strip the mount prefix so all routing below is written against "/api/..."
  // or "/subscriptions/...".
  const apiPath = url.pathname.slice(BASE.length);
  event.respondWith((async () => {
    try {
      const method = event.request.method;
      // ── Spaces (dashboard) ──────────────────────────────────────────
      // The active space is provider-specific (console gate) — derive it from
      // the requesting page so every console opens against a matching space.
      // Prefer a user-created space for that provider (honours its name/region).
      if (apiPath === "/api/spaces/active" && method === "GET") {
        const prov = await providerOf(event.clientId);
        let match = null;
        try {
          const created = await spacesAll();
          const activeId = await metaGet("active");
          match = created.find((s) => s.space_id === activeId && s.provider === prov)
               || created.filter((s) => s.provider === prov).pop();
        } catch (_) {}
        return json({ space: match || nanoSpace(prov) });
      }
      // Spaces list = fixture defaults + persisted user-created (deduped).
      if (apiPath === "/api/spaces" && method === "GET") {
        const fx = await (await fetch(FIX + "/spaces.json")).json().catch(() => ({ spaces: [] }));
        let created = []; try { created = await spacesAll(); } catch (_) {}
        const seen = new Set(), spaces = [];
        for (const s of [...(fx.spaces || []), ...created])
          if (!seen.has(s.space_id)) { seen.add(s.space_id); spaces.push(s); }
        let active = fx.active_space_id; try { active = (await metaGet("active")) || active; } catch (_) {}
        return json({ spaces, active_space_id: active });
      }
      // Appliance-health pies: per-cloud distribution computed live from the
      // in-browser spaces (the only CENTRAL resource data — the cores' resources
      // live per-page in Pyodide memory, unreachable from here). Each space gets a
      // nominal footprint so the CPU / RAM / Disk pies populate + track real spaces.
      if (apiPath === "/api/runtime/host-distribution" && method === "GET") {
        // ── Live per-cloud footprint ──────────────────────────────────
        // Console pages census their in-browser backend and persist it to the
        // "meta" store (see nano-boot.writeCensus). A census is "fresh" only
        // while its console is open (rewritten every 5s); after TTL we drop it
        // so the pies reflect LIVE sessions, not stale ghosts.
        const CENSUS_TTL = 60000;
        const now = Date.now();
        const live = { aws: { vcpus: 0, ram_mb: 0, disk_mb: 0, resources: 0, vms: 0 },
                       gcp: { vcpus: 0, ram_mb: 0, disk_mb: 0, resources: 0, vms: 0 },
                       azure: { vcpus: 0, ram_mb: 0, disk_mb: 0, resources: 0, vms: 0 } };
        let sessions = 0, liveResources = 0, heap = 0, freshest = 0;
        for (const p of ["aws", "gcp", "azure"]) {
          let c = null; try { c = await metaGet("census:" + p); } catch (_) {}
          if (!c || typeof c.ts !== "number" || (now - c.ts) >= CENSUS_TTL) continue;
          live[p].vcpus = c.vcpus || 0; live[p].ram_mb = c.ram_mb || 0;
          live[p].disk_mb = c.disk_mb || 0; live[p].resources = c.resources || 0;
          live[p].vms = c.vms || 0; live[p].by_service = c.by_service || {};
          sessions++; liveResources += c.resources || 0;
          heap += c.wasm_heap_bytes || 0; freshest = Math.max(freshest, c.ts);
        }
        // Always report the live footprint so the three CPU/RAM/Disk pies stay
        // visible. Only FRESH censuses count (a closed console's resources are
        // ephemeral) — so with no live console the pies honestly show an empty
        // state ("open a console…") rather than ghosts or a misleading estimate.
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
        const services = NANO_SERVICES.map((s) => ({ ...s, status: "ready" }));
        const by_category = {};
        for (const s of services) {
          const c = (by_category[s.category] = by_category[s.category] || { ready: 0, total: 0, pct: 100 });
          c.ready++; c.total++;
        }
        return json({ ready: true, status: "ready", percent: 100, overall_pct: 100,
                      ready_count: services.length, total_count: services.length,
                      by_category, services });
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
        for (const s of NANO_SERVICES) {
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
      if (apiPath === "/api/auth/start-activation" && method === "POST") {
        let installId = await metaGet("install_id");
        if (!installId) {
          installId = "nano-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now().toString(36);
          try { await metaPut("install_id", installId); } catch (_) {}
        }
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

      // Create a space → persist it, make it active, return it.
      if (apiPath === "/api/spaces" && method === "POST") {
        let body = {}; try { const t = await event.request.text(); body = t ? JSON.parse(t) : {}; } catch (_) {}
        const provider = String(body.provider || "").toLowerCase();
        if (!["aws", "gcp", "azure"].includes(provider))
          return json({ ok: false, detail: { reason: "provider must be aws, gcp, or azure" } }, 400);
        const s = mkSpace(provider, (body.name || "").trim(), (body.region || "").trim());
        try { await spacePut(s); await metaPut("active", s.space_id); }
        catch (e) { return json({ ok: false, detail: { reason: "could not persist space: " + e } }, 500); }
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
        return json({ ok: true });
      }
      // S3 object upload is multipart — read the file body here (not as JSON).
      const up = method === "POST" && apiPath.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
      if (up) return await handleUpload(event.request, decodeURIComponent(up[1]));

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
  })());
});
