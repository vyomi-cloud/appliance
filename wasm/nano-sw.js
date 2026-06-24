/* Vyomi Nano — lightweight service-worker bootstrap for pages that need the
 * SW to serve their /api/* reads but DON'T need the Pyodide backend (the launch
 * dashboard: spaces/host/runtime are all served from fixtures). Registers the
 * SW and, on first load, reloads once so the SW controls the page (a SW doesn't
 * control the page that registered it until a reload). No Pyodide, so it's
 * instant — unlike nano-boot.js, which the consoles use.
 */
(async () => {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      const n = Number(sessionStorage.getItem("nano-sw-reload") || "0");
      if (n < 4) { sessionStorage.setItem("nano-sw-reload", String(n + 1)); location.reload(); return; }
      return; // gave up — page still renders, just without served /api reads
    }
    sessionStorage.removeItem("nano-sw-reload");
  } catch (_) { /* page still renders */ }
})();
