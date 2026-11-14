/* Genuine Nano mode for the GCP v4 round-trip suites: serves the wasm/ bundle (the exact files the portal ships as /nano/) statically and boots the v4 GCP
 * console in Chromium, so the in-browser engines (service worker + Pyodide cores) answer. The "native API" side is the same wire the SDK/gcloud use through the
 * tunnel (/_wire/*), issued from a second page of the same browser context (same service worker + shared store). Enable with NANO=1. */
import { startServer, sleep } from "../../../../wasm/ui-tests/lib.mjs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const WASM = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../wasm");

export async function nanoStart(browser, project) {
  const { server, base } = await startServer(process.env.NANO_DIR || WASM);
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1100 } });
  await ctx.addInitScript(([p, t]) => { try { localStorage.setItem("vyomi.v4.gcp.project", p); localStorage.setItem("vyomi_ci_tier", t); } catch (_) {} }, [project, process.env.NANO_TIER || "max"]);   // vyomi_ci_tier: the runners' tier bypass (nano-boot syncK8sTier) so GKE is reachable; NANO_TIER=free proves the gate
  const apiPage = await ctx.newPage();
  await apiPage.goto(base + "/v4/gcp/index.html");
  await apiPage.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller && document.body.innerText.length > 200, null, { timeout: 300000, polling: 500 });
  // the Pyodide engine boots after the shell paints: the footer flips to "in-browser backend ready" when /_wire can be served
  await apiPage.waitForFunction(() => /in-browser backend ready/.test(document.body.innerText), null, { timeout: 300000, polling: 500 });
  await sleep(500);
  // wire(path, {method, headers, body | bodyB64}) -> {status, text}
  const wire = (path, init = {}) => apiPage.evaluate(async ([p, i]) => {
    const r = await fetch("/_wire" + p, { method: i.method || "GET", headers: i.headers || {}, body: i.bodyB64 ? Uint8Array.from(atob(i.bodyB64), (c) => c.charCodeAt(0)) : i.body });
    return { status: r.status, text: await r.text() };
  }, [path, init]);
  const rest = async (method, path, body) => {
    const hasBody = !(body === undefined || method === "GET" || method === "DELETE");
    const r = await wire(path, { method, headers: hasBody ? { "content-type": "application/json" } : {}, body: hasBody ? JSON.stringify(body) : undefined });
    let j = null; try { j = JSON.parse(r.text); } catch (_) {}
    return { status: r.status, body: j };
  };
  return { server, base, ctx, apiPage, wire, rest };
}
