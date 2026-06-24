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
const BASE = "";  // wasm/ is the web root (see sw.js)
// Capture control state SYNCHRONOUSLY (see nano-sw.js for why): the console's
// inline boot() fetches /api/* at parse, before this module runs.
const wasControlledAtStart = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
const MODULES = [
  "backends/store.py",
  "providers/registry.py", "providers/aws.py", "providers/gcp.py",
  "providers/azure.py", "providers/oracle.py", "providers/__init__.py",
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
  py.runPython(`
import sys; sys.path.insert(0, "/")
from wasm.backends.store import Backends
from wasm import providers as P
import json
_B = Backends()
def _disp(provider, service, op, params):
    return json.dumps(P.dispatch(_B, provider, service, op, params=dict(params)))
import builtins; builtins._disp = _disp
`);
  const dispatch = (prov, svc, op, params) =>
    JSON.parse(py.runPython(
      `_disp(${JSON.stringify(prov)}, ${JSON.stringify(svc)}, ${JSON.stringify(op)}, ${JSON.stringify(params)})`));

  // Bridge: SW -> page dispatch -> SW
  navigator.serviceWorker.addEventListener("message", (ev) => {
    if (!ev.data || ev.data.type !== "vyomi-dispatch") return;
    const port = ev.ports[0];
    try {
      const [prov, svc, op, params] = ev.data.tuple;
      port.postMessage(dispatch(prov, svc, op, params || {}));
    } catch (e) {
      port.postMessage({ ok: false, error: String(e) });
    }
  });

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
