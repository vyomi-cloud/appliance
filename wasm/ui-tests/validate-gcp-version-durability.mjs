// GCP version-lifecycle reload-durability (capped, self-killing). Proves that a
// Secret Manager secret + an ADDED secret version created via /api/gcp/sub/*
// survive a FULL PAGE RELOAD through the real SW -> Pyodide -> nano_persist ->
// IndexedDB -> restore cycle. Mirrors validate-reload-durability.mjs.
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000);
_k.unref && _k.unref();

import { chromium, startServer, bootConsole } from "./lib.mjs";

const SECRET = "durable-secret-" + Date.now();

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
    await bootConsole(page, base, "/gcp-console.html");
    // create the parent secret (catalog route) + add a 2nd version (sub route)
    const c = await apiInPage(page, "POST", `/api/gcp/secrets`, { name: SECRET });
    note += `create=${c.status}; `;
    const av = await apiInPage(page, "POST", `/api/gcp/sub/secretmanager/addVersion/${encodeURIComponent(SECRET)}`,
      { value: "before-reload" });
    note += `addVersion=${av.status}; `;
    await page.waitForTimeout(1500); // let debounced nano_persist flush to IndexedDB

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction((sel) => navigator.serviceWorker && navigator.serviceWorker.controller
      && document.querySelectorAll(sel).length > 0,
      "#rail a, #rail button, #rail li, #rail [data-service]", { timeout: 60000, polling: 500 });

    let vers = [];
    for (let i = 0; i < 40; i++) {
      const l = await apiInPage(page, "GET", `/api/gcp/sub/secretmanager/listVersions/${encodeURIComponent(SECRET)}`);
      vers = ((l.json && l.json.items) || []).map((x) => x.name);
      if (vers.length >= 2) break;
      await page.waitForTimeout(500);
    }
    note += `afterReloadVersions=${JSON.stringify(vers)}; `;
    ok = vers.length >= 2;   // the seeded v1 + the added v2 both survived
  } catch (e) {
    note += "ERROR:" + String(e.message || e);
  } finally {
    console.log((ok ? "PASS" : "FAIL") + " gcp-version-durability :: " + note);
    await browser.close();
    server.close();
    process.exit(ok ? 0 : 1);
  }
})();
