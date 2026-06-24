/* Vyomi Nano — service worker: the fetch-ASGI shim (the P0).
 *
 * A browser tab has no sockets, so the SDK/SPA's HTTP requests can't reach a
 * "server" — the service worker IS the transport. It intercepts same-origin
 * /api/* requests, translates the SPA's console REST path to a
 * (provider, service, operation, params) tuple, and asks the controlling page
 * (where Pyodide + the wasm/ backend live) to run it, then returns the JSON.
 *
 * Milestone 0 (today): the loop + a couple of S3 endpoints, proving the SPA's
 * fetch is served fully in-browser.
 * Milestone 1: complete the path<->handler translation for the full console
 * API (or, better, route to the REAL server.py handlers running in Pyodide so
 * there's ONE handler set + true conformance — no per-endpoint translation).
 */
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

// SPA console REST -> (provider, service, operation, params). Extend per service.
function translate(method, path, body) {
  // /api/s3/buckets/{bucket}/objects/{key}
  let m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/(.+)$/);
  if (m && method === "PUT")  return ["aws", "s3", "PutObject", { bucket: m[1], key: m[2], body: body || "" }];
  if (m && method === "GET")  return ["aws", "s3", "GetObject", { bucket: m[1], key: m[2] }];
  m = path.match(/^\/api\/s3\/buckets\/([^/]+)\/objects\/?$/);
  if (m && method === "GET")  return ["aws", "s3", "ListObjects", { bucket: m[1] }];
  // ... add gcp/azure/oci + the rest of the console surface here (milestone 1) ...
  return null;
}

// Ask the page to run the dispatch in Pyodide (the backend lives on the main
// thread). Round-trips via postMessage + a MessageChannel.
async function runInPage(tuple) {
  const all = await self.clients.matchAll({ includeUncontrolled: true });
  const client = all[0];
  if (!client) throw new Error("no client to run the in-browser backend");
  return await new Promise((resolve, reject) => {
    const ch = new MessageChannel();
    ch.port1.onmessage = (ev) => (ev.data && ev.data.ok !== false ? resolve(ev.data) : resolve(ev.data));
    client.postMessage({ type: "vyomi-dispatch", tuple }, [ch.port2]);
    setTimeout(() => reject(new Error("backend timeout")), 10000);
  });
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/api/")) return; // let the SPA's own assets through
  event.respondWith((async () => {
    try {
      const body = ["PUT", "POST"].includes(event.request.method) ? await event.request.text() : null;
      const tuple = translate(event.request.method, url.pathname, body);
      if (!tuple) {
        return new Response(JSON.stringify({ ok: false, code: "NotTranslatedYet", path: url.pathname }),
          { status: 501, headers: { "content-type": "application/json" } });
      }
      const res = await runInPage(tuple);
      return new Response(JSON.stringify(res),
        { status: res.ok === false ? 404 : 200, headers: { "content-type": "application/json" } });
    } catch (e) {
      return new Response(JSON.stringify({ ok: false, error: String(e) }),
        { status: 500, headers: { "content-type": "application/json" } });
    }
  })());
});
