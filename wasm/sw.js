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
// Served with the wasm/ folder as the web root, so assets live at "/" (the
// repo source is never exposed). Scope "/" lets the SW intercept /api/* too.
const BASE = "";
const FIX = "/fixtures";

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

// Bootstrap reads served verbatim from fixtures.
const FIXTURES = {
  // consoles ( /api/spaces/active is dynamic — see nanoSpace below )
  "/api/aws/catalog": "aws-catalog.json",
  "/api/gcp/catalog": "gcp-catalog.json",
  "/api/tenants": "tenants.json",
  // launch dashboard (clouds.html)
  "/api/spaces": "spaces.json",
  "/api/runtime/tier": "runtime-tier.json",
  "/api/host/cpu": "host-cpu.json",
  "/api/host/mem": "host-mem.json",
  "/api/host/sizing": "host-sizing.json",
  "/api/runtime/disk-health": "runtime-disk-health.json",
  "/api/runtime/host-distribution": "runtime-host-distribution.json",
  "/api/runtime/update-check": "runtime-update-check.json",
};
// Benign empty stubs so polled chrome endpoints don't error the console.
const STUBS = {
  "/api/cloudsim/events": { events: [] },
  "/api/spaces/active/facts": {},
  "/api/runtime/disk-cleanup/suggestions": { items: [] },
  // Nano is always "ready" — no appliance to boot, so the readiness strip hides.
  "/api/runtime/readiness": { ready: true, status: "ready", percent: 100 },
};

function json(obj, status) {
  return new Response(JSON.stringify(obj),
    { status: status || 200, headers: { "content-type": "application/json" } });
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
async function route(method, path, body) {
  // 1. fixtures + stubs (exact match, GET)
  if (method === "GET" && FIXTURES[path]) {
    const r = await fetch(FIX + "/" + FIXTURES[path]);
    return { response: new Response(r.body, { status: 200, headers: { "content-type": "application/json" } }) };
  }
  if (method === "GET" && STUBS[path]) return { response: json(STUBS[path]) };

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
  return { miss: true };
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/api/")) return;
  event.respondWith((async () => {
    try {
      // The active space is provider-specific (console gate) — derive it from
      // the requesting page so every console opens against a matching space.
      if (url.pathname === "/api/spaces/active" && event.request.method === "GET") {
        return json({ space: nanoSpace(await providerOf(event.clientId)) });
      }
      const method = event.request.method;
      // S3 object upload is multipart — read the file body here (not as JSON).
      const up = method === "POST" && url.pathname.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
      if (up) return await handleUpload(event.request, decodeURIComponent(up[1]));

      let body = null;
      if (["PUT", "POST", "PATCH"].includes(method)) {
        const txt = await event.request.text();
        try { body = txt ? JSON.parse(txt) : {}; } catch (_) { body = { raw: txt }; }
      }
      const r = await route(method, url.pathname, body);
      if (r.response) return r.response;
      if (r.miss) return json({ ok: false, code: "NotTranslatedYet", method, path: url.pathname }, 501);
      // The cores return console-shaped JSON ({buckets|tables|objects|items:[...]}),
      // so the adapter result is the response body verbatim.
      const res = await runInPage(r.tuple);
      return json(res, res && res.ok === false ? 404 : 200);
    } catch (e) {
      return json({ ok: false, error: String(e) }, 500);
    }
  })());
});
