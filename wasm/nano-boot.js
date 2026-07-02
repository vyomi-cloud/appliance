/* Vyomi Nano — page-side boot loader.
 *
 * Injected into the real console HTML. Responsibilities:
 *   1. Register the service worker and make sure it CONTROLS this page (a SW
 *      doesn't control the page that first registered it until a reload — so
 *      we reload once; thereafter every /api/* fetch is intercepted).
 *   2. Boot Pyodide and load the SAME wasm/ Python backend that passes the
 *      conformance test.
 *   3. Bridge: when the SW posts a (provider, service, op, params) tuple, run
 *      it through the backend and post the JSON result back.
 *   4. Signal "pyodide-ready" so the SW releases any held /api/* requests.
 *
 * The console's own boot() fires its fetches at parse; the SW holds them until
 * step 4, so there's no race — early calls just wait for the backend.
 */
// BASE = the directory this module is served from, so the bundle works both at
// the web root ("/nano-boot.js" -> "") and under a subpath like the portal's
// /nano/ ("/nano/nano-boot.js" -> "/nano"). All asset loads + the SW
// registration below already prefix BASE; the page's fetch shim handles /api.
const BASE = new URL(".", import.meta.url).pathname.replace(/\/$/, "");
// Capture control state SYNCHRONOUSLY (see nano-sw.js for why): the console's
// inline boot() fetches /api/* at parse, before this module runs.
const wasControlledAtStart = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
// Which cloud this console is — drives the live resource census we persist for
// the dashboard's per-cloud footprint pies (null on non-console pages).
const CONSOLE_PROVIDER = (location.pathname.match(/\/(aws|gcp|azure)-console\.html/) || [])[1] || null;

// Persist one key into the shared "nano-spaces" IndexedDB "meta" store (same DB
// the SW reads). Mirrors sw.js's idb() open so it works whether the SW created
// the DB first or not.
function nbMetaPut(k, v) {
  return new Promise((res, rej) => {
    const r = indexedDB.open("nano-spaces", 1);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains("spaces")) db.createObjectStore("spaces", { keyPath: "space_id" });
      if (!db.objectStoreNames.contains("meta"))   db.createObjectStore("meta",   { keyPath: "k" });
    };
    r.onsuccess = () => {
      try {
        const tx = r.result.transaction("meta", "readwrite");
        tx.objectStore("meta").put({ k, v });
        tx.oncomplete = () => res();
        tx.onerror = () => rej(tx.error);
      } catch (e) { rej(e); }
    };
    r.onerror = () => rej(r.error);
  });
}
const MODULES = [
  "backends/store.py",
  "providers/registry.py", "providers/aws_core_adapter.py", "providers/aws.py",
  "providers/gcp.py", "providers/azure.py", "providers/oracle.py",
  "providers/__init__.py",
];
// The PROVEN conformance cores (vendored into wasm/core/ by build_cores.py).
// aws_core_adapter imports these; they ARE the S3/DynamoDB data-plane.
const CORES = [
  "object_store.py", "s3_object_core.py", "nosql_store.py", "dynamodb_core.py",
  "kms_keystore.py", "kms_core.py", "kv_store.py", "secrets_core.py",
  "sql_store.py", "rds_core.py", "iam_store.py", "iam_core.py",
  "messaging_store.py", "sqs_core.py", "sns_core.py",
  "azure_arm_data.py", "azure_arm_core.py",   // Azure ARM control plane (native /subscriptions/* wire)
];

function banner(text, bad) {
  let b = document.getElementById("nano-banner");
  if (!b) {
    b = document.createElement("div");
    b.id = "nano-banner";
    b.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:99999;font:12px/1.4 ui-monospace,Menlo,monospace;" +
      "padding:6px 12px;text-align:center;color:#fff;background:" + (bad ? "#b91c1c" : "#065f46");
    document.body.appendChild(b);
  }
  b.style.background = bad ? "#b91c1c" : "#065f46";
  b.textContent = text;
}

async function bootBackend() {
  banner("Nano: booting Pyodide (in-browser cloud backend)…");
  const { loadPyodide } = await import("https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.mjs");
  const py = await loadPyodide();
  py.FS.mkdir("/wasm"); py.FS.mkdir("/wasm/backends"); py.FS.mkdir("/wasm/providers");
  py.FS.writeFile("/wasm/__init__.py", "");
  py.FS.writeFile("/wasm/backends/__init__.py", "");
  for (const m of MODULES) {
    const src = await (await fetch(BASE + "/" + m)).text();
    py.FS.writeFile("/wasm/" + m, src);
  }
  // The vendored cores live under /core (their own `core` package) so their
  // `from core.object_store import ...` imports resolve, exactly as in the repo.
  py.FS.mkdir("/core"); py.FS.writeFile("/core/__init__.py", "");
  for (const c of CORES)
    py.FS.writeFile("/core/" + c, await (await fetch(BASE + "/core/" + c)).text());
  py.runPython(`
import sys; sys.path.insert(0, "/")
from wasm.backends.store import Backends
from wasm import providers as P
import json
_B = Backends()
def _disp(payload_json):
    # ONE JSON-string arg (parsed here), so params with booleans/null/nested
    # objects survive — embedding JSON.stringify(params) as Python source would
    # turn true/false/null into NameErrors. (Same pattern as relay/nano-endpoint.)
    d = json.loads(payload_json)
    return json.dumps(P.dispatch(_B, d["provider"], d["service"], d["op"],
                                 params=d.get("params") or {}))
import builtins; builtins._disp = _disp
`);
  const dispatch = (prov, svc, op, params) =>
    JSON.parse(py.runPython(
      `_disp(${JSON.stringify(JSON.stringify({ provider: prov, service: svc, op, params: params || {} }))})`));

  // ── Live resource census ──────────────────────────────────────────
  // The dashboard page has no Pyodide, so it can't see the resources THIS
  // page's backend holds. We count them here (registry._census_dispatch) and
  // persist to IndexedDB; the SW's /api/runtime/host-distribution reads the
  // fresh censuses to draw REAL per-cloud footprint pies. Includes the actual
  // WASM linear-memory size — a genuine live runtime-utilization number.
  const heapBytes = () => {
    try { return (py._module && py._module.HEAP8 && py._module.HEAP8.byteLength) || 0; }
    catch (_) { return 0; }
  };
  async function writeCensus() {
    if (!CONSOLE_PROVIDER) return;
    try {
      const c = dispatch(CONSOLE_PROVIDER, "_census", "GET", {});
      c.wasm_heap_bytes = heapBytes();
      c.ts = Date.now();
      await nbMetaPut("census:" + CONSOLE_PROVIDER, c);
    } catch (_) { /* best-effort — never disturb the console */ }
  }
  let _censusTimer = null;
  const scheduleCensus = () => {
    if (_censusTimer) return;
    _censusTimer = setTimeout(() => { _censusTimer = null; writeCensus(); }, 400);
  };

  // Bridge: SW -> page dispatch -> SW
  navigator.serviceWorker.addEventListener("message", (ev) => {
    if (!ev.data || ev.data.type !== "vyomi-dispatch") return;
    const port = ev.ports[0];
    try {
      const [prov, svc, op, params] = ev.data.tuple;
      port.postMessage(dispatch(prov, svc, op, params || {}));
      scheduleCensus();  // any op may have mutated state — refresh the footprint
    } catch (e) {
      port.postMessage({ ok: false, error: String(e) });
    }
  });

  writeCensus();                              // initial (heap + any seeded state)
  setInterval(writeCensus, 5000);             // heartbeat: keeps the census "fresh"
  addEventListener("pagehide", writeCensus);  // best-effort final snapshot

  // Release any held /api/* requests.
  const reg = await navigator.serviceWorker.ready;
  (reg.active || navigator.serviceWorker.controller).postMessage({ type: "pyodide-ready" });
  banner("Nano: in-browser backend ready — this console runs with no server.");
  setTimeout(() => { const b = document.getElementById("nano-banner"); if (b) b.style.display = "none"; }, 4000);
}

(async () => {
  if (!("serviceWorker" in navigator)) { banner("Nano needs a service-worker-capable browser.", true); return; }
  try {
    const reg = await navigator.serviceWorker.register(BASE + "/sw.js", { scope: BASE + "/", updateViaCache: "none" });
    try { await reg.update(); } catch (_) {}
    await navigator.serviceWorker.ready;
    // Arriving from the dashboard we're already CONTROLLED. If a console URL is
    // opened cold/directly, it started uncontrolled (boot()'s /api reads went to
    // the network) — reload once to a controlled load before booting Pyodide.
    if (!wasControlledAtStart) {
      const n = Number(sessionStorage.getItem("nano-boot-reload") || "0");
      if (n < 4) { sessionStorage.setItem("nano-boot-reload", String(n + 1)); location.reload(); return; }
    }
    sessionStorage.removeItem("nano-boot-reload");
    await bootBackend();
  } catch (e) {
    banner("Nano boot failed: " + e, true);
  }
})();
