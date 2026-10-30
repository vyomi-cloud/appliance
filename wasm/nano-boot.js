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
// The console-next SPA is served at BASE/console-next/ — detect it so bootBackend
// imports the SPA after Pyodide + the SW are ready (slice 1). CONSOLE_PROVIDER
// stays null on this page (its census is provider-scoped, N/A for the SPA shell).
const IS_CONSOLE_NEXT = /\/console-next(\/|$)/.test(location.pathname);

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
// Read one key from the shared "nano-spaces" IndexedDB "meta" store (→ value or null).
function nbMetaGet(k) {
  return new Promise((res) => {
    const r = indexedDB.open("nano-spaces", 1);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains("spaces")) db.createObjectStore("spaces", { keyPath: "space_id" });
      if (!db.objectStoreNames.contains("meta"))   db.createObjectStore("meta",   { keyPath: "k" });
    };
    r.onsuccess = () => {
      try {
        const g = r.result.transaction("meta", "readonly").objectStore("meta").get(k);
        g.onsuccess = () => res(g.result ? g.result.v : null);
        g.onerror = () => res(null);
      } catch (_) { res(null); }
    };
    r.onerror = () => res(null);
  });
}
const MODULES = [
  "backends/store.py",
  "providers/registry.py", "providers/aws_core_adapter.py",
  "providers/gcp_core_adapter.py", "providers/azure_core_adapter.py",
  "providers/dataplane_adapter.py",   // v2.9.0 — net-new data planes (loaded before aws/azure which import it)
  "providers/aws.py", "providers/gcp.py", "providers/azure.py", "providers/oracle.py",
  "providers/__init__.py",
  // console-next SPA capability manifest (slice 1): the pure manifest builder +
  // its Pyodide adapter. console_next_manifest imports `from core import
  // console_conformance` (vendored under /core, see CORES), NO FastAPI.
  "console_next_manifest.py", "providers/console_next_adapter.py",
  "providers/wire_adapter.py",   // v4 /_wire/* native-wire prefix → AwsWireRouter on the shared registry
];
// The PROVEN conformance cores (vendored into wasm/core/ by build_cores.py).
// aws_core_adapter imports these; they ARE the S3/DynamoDB data-plane.
const CORES = [
  "object_store.py", "s3_object_core.py", "nosql_store.py", "dynamodb_expr.py", "dynamodb_core.py",
  "kms_keystore.py", "kms_core.py", "kv_store.py", "secrets_core.py",
  "sql_store.py", "rds_core.py", "iam_store.py", "iam_core.py",
  "messaging_store.py", "sqs_core.py", "sns_core.py", "elbv2_core.py",
  "azure_cognitiveservices_core.py",  // Azure AI services engine (Microsoft.CognitiveServices) — loaded before azure_arm_core which delegates to it
  "azure_monitor_core.py",   // Azure Monitor engine (Microsoft.Insights) — loaded before azure_arm_core which delegates to it
  "azure_dns_core.py",   // Azure DNS engine (Microsoft.Network/dnsZones) — loaded before azure_arm_core which delegates to it
  "azure_operationalinsights_core.py",   // Azure Log Analytics engine (Microsoft.OperationalInsights) — loaded before azure_arm_core which delegates to it
  "azure_appconfiguration_core.py",   // Azure App Configuration engine — loaded before azure_arm_core which delegates to it
  "azure_app_core.py",   // Azure Container Apps engine (Microsoft.App) — loaded before azure_arm_core which delegates to it
  "azure_cost_core.py",   // Azure Cost Management + Consumption engine — loaded before azure_arm_core which delegates to it
  "azure_webapp_core.py",   // Azure App Service engine (Microsoft.Web: web apps + function apps, plans) — loaded before azure_arm_core which delegates to it
  "azure_eventgrid_core.py",   // Azure Event Grid event subscriptions (Microsoft.EventGrid, topic-scoped) — loaded before azure_arm_core which delegates to it
  "azure_locks_core.py",   // Management locks (Microsoft.Authorization/locks, scoped to ANY resource) — loaded before azure_arm_core which delegates to it
  "azure_arm_data.py", "azure_arm_core.py",   // Azure ARM control plane (native /subscriptions/* wire)
  // GCP conformance cores — the gcp_core_adapter data-plane (console CRUD).
  "gcp_storage_core.py", "gcp_firestore_core.py", "gcp_kms_core.py",
  "gcp_secretmanager_core.py", "gcp_pubsub_core.py", "gcp_iam_core.py", "gcp_cloudsql_core.py", "gcp_artifactregistry_core.py", "gcp_logging_core.py", "gcp_compute_core.py", "instance_catalog.py", "gcp_compute_instances_core.py", "gcp_resourcemanager_core.py", "gcp_pam_core.py", "gcp_run_core.py",
  // Azure data-plane cores — the azure_core_adapter data-plane (console CRUD).
  "azure_blob_core.py", "azure_cosmos_core.py", "azure_keyvault_secrets_core.py",
  "azure_keyvault_keys_core.py", "azure_queue_core.py",
  // Generic child/sub-resource store (SQL databases+firewall rules, SB queues) +
  // durable editable settings — azure_core_adapter imports it. Pure stdlib; its
  // state rides az_cosmos's public `nano_sub` attr so nano_persist persists it.
  "azure_subresource_core.py",
  // v2.5.0–2.8.0 net-new service cores — loaded so the console backend is in
  // lock-step with the relay + build_cores (usable now via the Nano relay;
  // dedicated console UI pages are a follow-up). Deps (messaging_store, sql_store,
  // iam_store, lambda_core) are already listed above.
  "azure_servicebus_core.py", "eventbridge_core.py", "lambda_core.py",
  "apigateway_core.py", "apigatewayv2_core.py", "apigatewayv2_gateway.py", "vpc_core.py", "kinesis_core.py", "cost_model.py", "cloudwatch_core.py", "azure_sql_core.py", "azure_iam_core.py", "logs_core.py", "ssm_core.py", "stepfunctions_core.py", "gcp_cloudscheduler_core.py", "gcp_container_core.py", "gcp_redis_core.py", "gcp_iamcredentials_core.py", "gcp_monitoring_core.py",
  // console-next capability manifest dependency (slice 1): the pure conformance
  // signal module (only imports `os` — safe in Pyodide, no FastAPI).
  "console_conformance.py",
  // Store persistence + shared registry (Fix #1/#2): aws_core_adapter imports
  // nano_registry, so these MUST load. nano_persist serializes the registry →
  // IndexedDB (survives reload) + powers console↔SDK convergence.
  // nano_events (per-resource cloudsim activity log) MUST precede nano_registry,
  // which imports `from core.nano_events import EventStore`.
  "nano_events.py", "nano_registry.py", "nano_persist.py",
  // v4 /_wire/*: the relay's native-wire front door (+ its rds_data dep), imported lazily by wire_adapter.
  "rds_data_core.py", "aws_wire_router.py",
];

// Boot screen (wasm/nano-kernel.js): the page paints it first thing in <body>;
// these steps report the real work + timings to it, then close it when ready.
const K = window.__nk || (window.NanoKernel ? window.NanoKernel.start(CONSOLE_PROVIDER ? CONSOLE_PROVIDER.toUpperCase() + " console" : "console") : null)
  || { step: () => ({ ok() {}, fail() {} }), info() {}, carry() {}, ready() {}, fail() {} };

function banner(text, bad) {
  let b = document.getElementById("nano-banner");
  if (!b) {
    b = document.createElement("div");
    b.id = "nano-banner";
    b.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:99999;pointer-events:none;font:12px/1.4 ui-monospace,Menlo,monospace;" +
      "padding:6px 12px;text-align:center;color:#fff;background:" + (bad ? "#b91c1c" : "#065f46");
    document.body.appendChild(b);
  }
  b.style.background = bad ? "#b91c1c" : "#065f46";
  b.textContent = text;
}

async function bootBackend() {
  banner("Nano: booting Pyodide (in-browser cloud backend)…");
  let st = K.step("kernel", "loading Pyodide 0.26.2: CPython on WebAssembly");
  // Same-origin runtime first (wasm/fetch_pyodide.py vendors it) — a CDN stall would leave Nano
  // stuck here; the public CDN stays as the fallback when the bundle doesn't carry it.
  const PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
  const PYODIDE_LOCAL = new URL(BASE + "/vendor/pyodide/", location.origin).href;
  const pyodideBase = await fetch(PYODIDE_LOCAL + "pyodide.mjs", { method: "HEAD" })
    .then((r) => (r.ok ? PYODIDE_LOCAL : PYODIDE_CDN), () => PYODIDE_CDN);
  const { loadPyodide } = await import(pyodideBase + "pyodide.mjs");
  const py = await loadPyodide({ indexURL: pyodideBase });
  let pyv = ""; try { pyv = py.runPython("import sys; sys.version.split()[0]"); } catch (_) {}
  st.ok("Python " + (pyv || "3") + " · Pyodide " + (py.version || "0.26.2"));
  st = K.step("fs", "mounting /wasm: " + MODULES.length + " console modules");
  py.FS.mkdir("/wasm"); py.FS.mkdir("/wasm/backends"); py.FS.mkdir("/wasm/providers");
  py.FS.writeFile("/wasm/__init__.py", "");
  py.FS.writeFile("/wasm/backends/__init__.py", "");
  for (const m of MODULES) {
    const src = await (await fetch(BASE + "/" + m)).text();
    py.FS.writeFile("/wasm/" + m, src);
  }
  // The vendored cores live under /core (their own `core` package) so their
  // `from core.object_store import ...` imports resolve, exactly as in the repo.
  st.ok();
  st = K.step("fs", "mounting /core: " + CORES.length + " cloud engines (AWS · GCP · Azure)");
  py.FS.mkdir("/core"); py.FS.writeFile("/core/__init__.py", "");
  for (const c of CORES)
    py.FS.writeFile("/core/" + c, await (await fetch(BASE + "/core/" + c)).text());
  st.ok();
  st = K.step("kernel", "importing the engines and wiring the console router");
  py.runPython(`
import sys; sys.path.insert(0, "/")
from wasm.backends.store import Backends
from wasm import providers as P
from wasm.providers import console_next_adapter as _CN
import json
_B = Backends()
def _disp(payload_json):
    # ONE JSON-string arg (parsed here), so params with booleans/null/nested
    # objects survive — embedding JSON.stringify(params) as Python source would
    # turn true/false/null into NameErrors. (Same pattern as relay/nano-endpoint.)
    d = json.loads(payload_json)
    prov = d["provider"]
    # console-next SPA (slice 1): the "_console" pseudo-provider is NOT a cloud in
    # the registry — it serves /api/console/* (capabilities now; facade data plane
    # is slice 2). Route it straight to the console_next adapter.
    if prov == "_console":
        return json.dumps(_CN.handle(d["op"], d.get("params") or {}))
    if prov == "_wire":   # v4 consoles: native wire via the relay's AwsWireRouter (same stores)
        from wasm.providers import wire_adapter as _W
        return json.dumps(_W.handle(d.get("params") or {}))
    return json.dumps(P.dispatch(_B, prov, d["service"], d["op"],
                                 params=d.get("params") or {}))
import builtins; builtins._disp = _disp
`);
  st.ok();
  // ── Live engine status (Dashboard > Service status) ─────────────────
  // This runtime checks every registry store (built + state reads back) and
  // records the result; the SW's /api/runtime/readiness builds the cards from
  // the fresh reports, so a card is "ready" only when an engine really is.
  async function writeEngines() {
    const key = "engines:" + (CONSOLE_PROVIDER || "page");
    try {
      const stores = JSON.parse(py.runPython("import json\nfrom core import nano_persist as _np\njson.dumps(_np.health_registry())"));
      await nbMetaPut(key, { ts: Date.now(), stores });
    } catch (e) {
      try { await nbMetaPut(key, { ts: Date.now(), error: String(e && e.message || e).slice(0, 200) }); } catch (_) {}
    }
  }
  writeEngines(); setInterval(writeEngines, 30000);

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

  // ── Store persistence + cross-context sync (Fix #1 persistence / #2 parity) ──
  // The shared registry is snapshotted to IndexedDB after each mutation and
  // rehydrated on boot (survives logout/login), and a BroadcastChannel tells the
  // other context (console ↔ relay page) to reload so an SDK/console create shows
  // up on the other side. All guarded — persistence NEVER blocks the console.
  const STORE_KEY = "nano:stores";
  let _bc = null; try { _bc = new BroadcastChannel("nano-stores"); } catch (_) {}
  let _restoring = false, _storeTimer = null;
  function captureStores() {
    try { return py.runPython("import json; from core import nano_persist; json.dumps(nano_persist.capture_registry())"); }
    catch (_) { return null; }
  }
  function restoreStores(blobJson) {
    if (!blobJson) return;
    try {
      py.globals.set("_vy_blob", blobJson);
      py.runPython("import json; from core import nano_persist; nano_persist.restore_registry(json.loads(_vy_blob))");
    } catch (_) {}
  }
  async function writeStores(notify) {
    try {
      const j = captureStores(); if (!j) return;
      await nbMetaPut(STORE_KEY, j);
      if (notify && _bc) { try { _bc.postMessage({ k: STORE_KEY, t: Date.now() }); } catch (_) {} }
    } catch (_) { /* best-effort */ }
  }
  // Reads batch their (no-op) saves on a 400 ms debounce; a WRITE saves on the next tick, so a
  // reload / tab close right after creating something no longer drops it (the 400 ms window
  // used to lose writes made just before a reload).
  const scheduleStoresSave = (write) => {
    if (_storeTimer && !write) return;
    if (_storeTimer) clearTimeout(_storeTimer);
    _storeTimer = setTimeout(() => { _storeTimer = null; writeStores(true); }, write ? 0 : 400);
  };
  const isWrite = (tuple) => tuple[0] === "_wire"
    ? !["GET", "HEAD", "OPTIONS"].includes(String(tuple[2]).toUpperCase())
    : !/^(get|list|describe|head|query|search|read)/i.test(String(tuple[2] || ""));
  if (_bc) _bc.onmessage = async (e) => {
    if (!e.data || e.data.k !== STORE_KEY || _restoring) return;
    _restoring = true;
    try { restoreStores(await nbMetaGet(STORE_KEY)); } finally { _restoring = false; }
  };
  // Boot: rehydrate the persisted dataset into the shared registry BEFORE releasing
  // /api/* requests, so the console opens with its previous resources intact.
  st = K.step("store", "restoring your resources from IndexedDB");
  try { restoreStores(await nbMetaGet(STORE_KEY)); st.ok(); } catch (e) { st.ok("starting fresh"); }

  // Bridge: SW -> page dispatch -> SW
  navigator.serviceWorker.addEventListener("message", async (ev) => {
    if (!ev.data || ev.data.type !== "vyomi-dispatch") return;
    const port = ev.ports[0];
    try {
      // Rehydrate from the SHARED snapshot before serving, so this op sees resources
      // created in the OTHER context (the SDK/relay worker) even if a boot-time
      // restore or a BroadcastChannel notification was missed — this is what makes
      // console<->CLI reads consistent regardless of timing. Guarded: skip when a
      // save is pending (_storeTimer) so we never clobber a just-created local
      // resource before it has been flushed to the shared snapshot — the stale
      // snapshot's shallow dict-merge would otherwise REPLACE a parent record
      // (e.g. a Cloud SQL instance) and drop a sub-resource just added to it
      // (a database) before the debounced save landed.
      if (!_restoring && !_storeTimer) {
        _restoring = true;
        try { restoreStores(await nbMetaGet(STORE_KEY)); } catch (_) {} finally { _restoring = false; }
      }
      const [prov, svc, op, params] = ev.data.tuple;
      port.postMessage(dispatch(prov, svc, op, params || {}));
      scheduleCensus();       // any op may have mutated state — refresh the footprint
      scheduleStoresSave(isWrite(ev.data.tuple));   // …and persist + notify the other context (Fix #1/#2)
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
  K.ready((CONSOLE_PROVIDER ? CONSOLE_PROVIDER.toUpperCase() + " console" : "console") + " ready: running entirely in your browser");
  // Public readiness signal (tests, embedding pages): the in-browser backend now answers.
  window.__vyomiNanoReady = true;
  try { dispatchEvent(new Event("vyomi-nano-ready")); } catch (_) {}
  banner("Nano: in-browser backend ready — this console runs with no server.");
  setTimeout(() => { const b = document.getElementById("nano-banner"); if (b) b.style.display = "none"; }, 4000);

  // console-next SPA (slice 1): this bundle also serves the new SPA at
  // BASE/console-next/. When THIS page is that SPA, boot it now — the SW is
  // controlling + Pyodide is up, so its first /api/console/capabilities read is
  // served in-browser (dispatched to console_next_adapter). The SPA reads its
  // asset/API base from the __VY_* globals its index.html already set.
  if (IS_CONSOLE_NEXT && window.__VY_ASSET_BASE) {
    try { await import(window.__VY_ASSET_BASE + "boot.js"); }
    catch (e) { banner("Nano: console-next SPA failed to load: " + e, true); }
  }
}

(async () => {
  if (!("serviceWorker" in navigator)) { banner("Nano needs a service-worker-capable browser.", true); return; }
  try {
    const sw = K.step("service", "service worker: registering " + BASE + "/sw.js");
    const reg = await navigator.serviceWorker.register(BASE + "/sw.js", { scope: BASE + "/", updateViaCache: "none" });
    try { await reg.update(); } catch (_) {}
    await navigator.serviceWorker.ready;
    sw.ok(wasControlledAtStart ? "active, controlling this page" : "installed");
    // Arriving from the dashboard we're already CONTROLLED. If a console URL is
    // opened cold/directly, it started uncontrolled (boot()'s /api reads went to
    // the network) — reload once to a controlled load before booting Pyodide.
    if (!wasControlledAtStart) {
      const n = Number(sessionStorage.getItem("nano-boot-reload") || "0");
      if (n < 4) { K.info("service", "reloading once under the service worker"); K.carry(); sessionStorage.setItem("nano-boot-reload", String(n + 1)); location.reload(); return; }
    }
    sessionStorage.removeItem("nano-boot-reload");
    await bootBackend();
  } catch (e) {
    K.fail(e);
    banner("Nano boot failed: " + e, true);
  }
})();
