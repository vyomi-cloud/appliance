/* Vyomi Nano — lightweight service-worker bootstrap for pages that need the
 * SW to serve their /api/* reads but DON'T need the Pyodide backend (the launch
 * dashboard: spaces/host/runtime come from fixtures). No Pyodide, so instant.
 *
 * The page's inline scripts (e.g. clouds.html's loadSpaces) fetch /api/* at
 * parse — BEFORE this deferred script runs. If the page wasn't controlled at
 * that point, those fetches hit the network (404 HTML) and fail. So we capture
 * control state SYNCHRONOUSLY at the top: if the page started uncontrolled, we
 * reload once to a controlled load where the SW intercepts from the first call.
 * (Just checking `controller` after registering is racy — clients.claim() can
 * flip it to true mid-script, masking that the initial fetches already failed.)
 */
const wasControlledAtStart = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
// BASE = the bundle's mount path (from the page URL), so the dashboard works at
// the web root AND under a subpath like the portal's /nano/. (Deferred classic
// script -> no import.meta/currentScript, so derive from location.)
const NANO_BASE = location.pathname.replace(/\/[^/]*$/, "");

(async () => {
  if (!("serviceWorker" in navigator)) return;
  try {
    const reg = await navigator.serviceWorker.register(NANO_BASE + "/sw.js", { scope: NANO_BASE + "/", updateViaCache: "none" });
    try { await reg.update(); } catch (_) {}
    await navigator.serviceWorker.ready;
    if (wasControlledAtStart) { sessionStorage.removeItem("nano-sw-reload"); return; }
    // Started uncontrolled -> the page's initial /api reads failed -> reload to
    // a controlled load (guarded against an infinite loop).
    const n = Number(sessionStorage.getItem("nano-sw-reload") || "0");
    if (n < 4) { sessionStorage.setItem("nano-sw-reload", String(n + 1)); location.reload(); }
  } catch (_) { /* page still renders, just without served /api reads */ }
})();
