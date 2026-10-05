// Capped, self-killing: proves the Azure sub-resource route + durable settings +
// activity events work IN A REAL BROWSER (SW -> Pyodide -> azure_core_adapter ->
// azure_subresource_core). Drives the SAME /api/azure/sub/... endpoints the console
// engine calls, then reloads to prove persistence.
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000);
_k.unref && _k.unref();

import { chromium, startServer, bootConsole } from "./lib.mjs";

const J = (page, url, opts) => page.evaluate(async ([u, o]) => {
  const r = await fetch(u, o || {});
  let j = null; try { j = await r.json(); } catch {}
  return { status: r.status, j };
}, [url, opts]);

(async () => {
  const srv = await startServer();
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const results = {};
  try {
    await bootConsole(page, srv.base, "/azure-console.html");
    const O = srv.base;

    // 1) SQL databases: create x2, list, delete one, list.
    await J(page, O + "/api/azure/sub/sql/createDatabase/srv1", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "db1", sku: "S0" }) });
    await J(page, O + "/api/azure/sub/sql/createDatabase/srv1", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "db2", sku: "S1" }) });
    let list = await J(page, O + "/api/azure/sub/sql/listDatabases/srv1");
    results.sql_databases_after_create = (list.j.items || []).map(i => i.name);
    await J(page, O + "/api/azure/sub/sql/deleteDatabase/srv1/db2", { method: "DELETE" });
    list = await J(page, O + "/api/azure/sub/sql/listDatabases/srv1");
    results.sql_databases_after_delete = (list.j.items || []).map(i => i.name);

    // 2) SQL firewall rule + Service Bus queue (second service).
    await J(page, O + "/api/azure/sub/sql/createFirewallRule/srv1", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "r1", startIpAddress: "1.1.1.1", endIpAddress: "1.1.1.9" }) });
    results.sql_firewall = ((await J(page, O + "/api/azure/sub/sql/listFirewallRules/srv1")).j.items || []).map(i => i.name);
    await J(page, O + "/api/azure/sub/servicebus/createQueue/ns1", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "q1", maxSizeInMegabytes: 1024 }) });
    results.sb_queues = ((await J(page, O + "/api/azure/sub/servicebus/listQueues/ns1")).j.items || []).map(i => i.name);

    // 3) Durable editable settings: update -> readback.
    await J(page, O + "/api/azure/sub/sql/updateSettings/srv1/identity", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ systemAssigned: "true", userAssigned: "mi1" }) });
    results.identity_settings = (await J(page, O + "/api/azure/sub/sql/getSettings/srv1/identity")).j.settings;

    // 4) Activity: the parent's events via the server-side resource filter.
    const ev = await J(page, O + "/api/cloudsim/events?resource=srv1&provider=azure&limit=50");
    results.srv1_event_actions = (ev.j.events || []).map(e => e.action);

    // 5) Persistence across a RELOAD (fresh Pyodide context; restored from IndexedDB).
    // Let the debounced 400ms save flush to IndexedDB BEFORE reloading.
    await page.waitForTimeout(1500);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, { timeout: 120000, polling: 500 });
    // Poll the restored list (boot-time restoreStores rehydrates from IndexedDB).
    await page.waitForFunction(async () => {
      try { const r = await fetch("/api/azure/sub/sql/listDatabases/srv1"); const j = await r.json(); return (j.items || []).length > 0; } catch { return false; }
    }, { timeout: 90000, polling: 800 }).catch(() => {});
    const afterReload = await J(page, O + "/api/azure/sub/sql/listDatabases/srv1");
    results.sql_databases_after_reload = (afterReload.j.items || []).map(i => i.name);
    const idAfter = await J(page, O + "/api/azure/sub/sql/getSettings/srv1/identity");
    results.identity_after_reload = idAfter.j.settings;

    console.log("RESULT " + JSON.stringify(results));
  } catch (e) {
    console.log("ERROR " + String(e && e.message || e));
    console.log("PARTIAL " + JSON.stringify(results));
  } finally {
    await browser.close(); srv.server.close(); clearTimeout(_k);
  }
})();
