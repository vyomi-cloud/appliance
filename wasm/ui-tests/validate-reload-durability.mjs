// Reload-durability browser check (capped, self-killing). Proves a generic-path
// AWS sub-resource created via /api/aws/sub/* survives a FULL PAGE RELOAD through
// the real SW -> Pyodide -> nano_persist -> IndexedDB -> restore cycle.
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000);
_k.unref && _k.unref();

import { chromium, startServer, bootConsole } from "./lib.mjs";

const NS = "secretsmanager~reloadtest-secret~versions";
const ITEM = "RELOAD-DURABLE-" + Date.now();

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
    await bootConsole(page, base, "/aws-console.html");
    // create via the generic sub-resource route
    const c = await apiInPage(page, "POST", `/api/aws/sub/${encodeURIComponent(NS)}/create`,
      { name: ITEM, description: "created before reload" });
    note += `create=${JSON.stringify(c.json || c)}; `;
    // let the debounced nano_persist save flush to IndexedDB
    await page.waitForTimeout(1500);

    // FULL PAGE RELOAD
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction((sel) => navigator.serviceWorker && navigator.serviceWorker.controller
      && document.querySelectorAll(sel).length > 0,
      "#rail a, #rail button, #rail li, #rail [data-service]", { timeout: 60000, polling: 500 });

    // nano-boot self-reloads 1-4x to regain SW control before Pyodide re-boots +
    // restores the IndexedDB snapshot, so the SW-controller gate above can resolve
    // on a transient cycle BEFORE restore. POLL the list until the item reappears
    // (restore landed) or a deadline — this is a timing gate, NOT a data assertion.
    let names = [];
    for (let i = 0; i < 40; i++) {
      const l = await apiInPage(page, "GET", `/api/aws/sub/${encodeURIComponent(NS)}/list`);
      names = ((l.json && l.json.items) || []).map((x) => x.name);
      if (names.includes(ITEM)) break;
      await page.waitForTimeout(500);
    }
    note += `afterReloadList=${JSON.stringify(names)}; `;
    ok = names.includes(ITEM);
  } catch (e) {
    note += "ERROR:" + String(e.message || e);
  } finally {
    await browser.close();
    server.close();
    clearTimeout(_k);
  }
  console.log((ok ? "BROWSER-RELOAD-DURABLE-PASS " : "BROWSER-RELOAD-DURABLE-FAIL ") + note);
  process.exit(ok ? 0 : 1);
})();
