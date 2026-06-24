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
const BASE = "/wasm";
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

// Bootstrap reads served verbatim from fixtures.
const FIXTURES = {
  "/api/aws/catalog": "aws-catalog.json",
  "/api/spaces/active": "spaces-active.json",
  "/api/spaces": "spaces.json",
  "/api/tenants": "tenants.json",
};
// Benign empty stubs so polled chrome endpoints don't error the console.
const STUBS = {
  "/api/cloudsim/events": { events: [] },
  "/api/spaces/active/facts": {},
};

function json(obj, status) {
  return new Response(JSON.stringify(obj),
    { status: status || 200, headers: { "content-type": "application/json" } });
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

  // 2. specialised data-plane (must precede generic — longer paths)
  let m;
  // S3 objects: /api/s3/buckets/{bucket}/objects[/{key...}]
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "ListObjects", { bucket: m[1] }] };
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/(.+)$/);
  if (m && method === "GET") return { tuple: ["aws", "s3", "GetObject", { bucket: m[1], key: m[2] }] };
  if (m && method === "DELETE") return { tuple: ["aws", "s3", "DeleteObject", { bucket: m[1], key: m[2] }] };
  // DynamoDB items: /api/dynamodb/tables/{t}/items|query|scan
  m = path.match(/^\/api\/dynamodb\/tables\/([^/]+)\/(items|scan|query)$/);
  if (m) return { tuple: ["aws", "dynamodb", "Scan", { table: m[1] }] };

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
      const method = event.request.method;
      let body = null;
      if (["PUT", "POST", "PATCH"].includes(method)) {
        const txt = await event.request.text();
        try { body = txt ? JSON.parse(txt) : {}; } catch (_) { body = { raw: txt }; }
      }
      const r = await route(method, url.pathname, body);
      if (r.response) return r.response;
      if (r.miss) return json({ ok: false, code: "NotTranslatedYet", method, path: url.pathname }, 501);
      let res = await runInPage(r.tuple);
      // Normalise specialised list shapes to the console's {items:[...]}.
      if (res && res.Contents) res = { ok: true, items: res.Contents.map((k) => ({ key: k, name: k })) };
      else if (res && res.Items) res = { ok: true, items: res.Items };
      return json(res, res && res.ok === false ? 404 : 200);
    } catch (e) {
      return json({ ok: false, error: String(e) }, 500);
    }
  })());
});
