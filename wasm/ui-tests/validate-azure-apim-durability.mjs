// Reload-durability browser check for the NEW Azure APIM child CRUD (apis), capped
// + self-killing. Proves an ARM child created via PUT .../service/{n}/apis/{a}
// survives a FULL PAGE RELOAD through the real SW -> Pyodide -> AzureArm.state ->
// nano_persist -> IndexedDB -> restore cycle.
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 150000);
_k.unref && _k.unref();

import { chromium, startServer, bootConsole } from "./lib.mjs";

const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "cloudlearn-rg";
const APIM = "apim-reload-" + Date.now();
const API = "orders-api";
const APIV = "2023-05-01-preview";
const SVC = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}`;

async function apiInPage(page, method, path, body) {
  return page.evaluate(async ([m, p, b]) => {
    const r = await fetch(p, {
      method: m,
      headers: b ? { "content-type": "application/json" } : undefined,
      body: b ? JSON.stringify(b) : undefined,
    });
    const t = await r.text();
    try { return { status: r.status, json: JSON.parse(t) }; } catch { return { status: r.status, text: t }; }
  }, [method, path, body]);
}

(async () => {
  const { server, base } = await startServer();
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  let ok = false, note = "";
  try {
    await bootConsole(page, base, "/azure-console.html");
    // create the APIM service, then the API child, both via ARM PUT
    const s = await apiInPage(page, "PUT", `${SVC}?api-version=${APIV}`, { location: "eastus" });
    note += `svc=${s.status}; `;
    const a = await apiInPage(page, "PUT", `${SVC}/apis/${API}?api-version=${APIV}`,
      { properties: { displayName: "Orders API", path: "orders", serviceUrl: "https://httpbin.org" } });
    note += `api=${a.status}; `;
    await page.waitForTimeout(1500);  // let debounced nano_persist flush to IndexedDB

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction((sel) => navigator.serviceWorker && navigator.serviceWorker.controller
      && document.querySelectorAll(sel).length > 0,
      "#rail a, #rail button, #rail li, #rail [data-service]", { timeout: 120000, polling: 500 });

    let found = false;
    for (let i = 0; i < 40; i++) {
      const g = await apiInPage(page, "GET", `${SVC}/apis/${API}?api-version=${APIV}`);
      if (g.status === 200 && g.json && g.json.name === API) { found = true; break; }
      await page.waitForTimeout(500);
    }
    note += `afterReloadApiGet=${found ? "200/" + API : "missing"}; `;
    ok = found;
  } catch (e) {
    note += "ERROR:" + String(e.message || e);
  } finally {
    await browser.close();
    server.close();
    clearTimeout(_k);
  }
  console.log((ok ? "AZURE-APIM-RELOAD-DURABLE-PASS " : "AZURE-APIM-RELOAD-DURABLE-FAIL ") + note);
  process.exit(ok ? 0 : 1);
})();
