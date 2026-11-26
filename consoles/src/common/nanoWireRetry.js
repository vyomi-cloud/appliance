/* Nano: a console call that reaches the service worker BEFORE the in-browser backend (Pyodide) is up is held by the worker for ~60 s and then
 * answered HTTP 500 {"ok":false,"error":"Error: no client to run the in-browser backend"}. Pages load their catalog once (AMI list, instance
 * types, ...) so that single 500 left the pickers empty for good ("AMI is not loading"). This wrapper recognises exactly that answer, waits for
 * the backend (backendReady, 4 min cap) and repeats the call (max 3 times). Any other response, and every non-Nano page, passes through untouched. */
import { backendReady } from "./wire.js";

const NO_CLIENT = /no client to run the in-browser backend/;
if (typeof window !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano" && !window.__vyomiWireRetry) {
  window.__vyomiWireRetry = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input?.url || "";
    if (!/\/_wire(\/|$|\?)/.test(url)) return orig(input, init);
    let req = input;
    for (let i = 0; ; i++) {
      const res = await orig(typeof req === "string" ? req : req.clone(), init);
      if (res.status !== 500 || i >= 3) return res;
      const txt = await res.clone().text().catch(() => "");
      if (!NO_CLIENT.test(txt)) return res;
      await backendReady();
      if (!window.__vyomiNanoReady) await new Promise((r) => setTimeout(r, 1500));
    }
  };
}
