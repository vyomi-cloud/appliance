// Cross-service v4 console checks: Home, every detail tab renders, measured Metrics.
export default [
  { id: "home", title: "Home", fn: async ({ page, base, go, body, shows, arm, v, P, SUB, rec, sleep }) => {
    const bad = []; const on = (r) => { const u = r.url(); if ((r.status() >= 500 || r.status() === 404) && /_wire|subscriptions/.test(u)) bad.push(`${r.status()} ${u.replace(base, "").slice(0, 90)}`); };
    await arm("PUT", `${P}/Microsoft.KeyVault/vaults/acthomekv${v("2023-07-01")}`, { location: "eastus", properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } });
    page.on("response", on);
    await go("/"); await sleep(2500);
    page.off("response", on);
    const t = await body();
    rec("Home shows the Azure services strip (Storage accounts, Virtual machines, Key vaults)", /Storage accounts/.test(t) && /Virtual machines/.test(t) && /Key vaults/.test(t) ? "PASS" : "FAIL", t.slice(0, 160));
    rec("Home has no 'undefined' / '[object Object]' text", !/\bundefined\b|\[object Object\]/.test(t) ? "PASS" : "FAIL");
    rec("Home loads without a 404 / 5xx from the ARM wire", bad.length === 0 ? "PASS" : "FAIL", bad.slice(0, 3).join(" | "));
    rec("Home lists a resource created over ARM under Recent/Resources", (await shows(/acthomekv/, 8000)) ? "PASS" : "NOTE", "Recent is per-browser: only resources opened in this browser are listed");
    await go("/resourcegroups"); const rt = await body();
    rec("Resource groups from Home replaces the Home dashboard at once", /Resource groups/.test(rt) && !/Create a resource\s+Recent/.test(rt) ? "PASS" : "FAIL");
  } },
  { id: "tabs", title: "Detail tabs", fn: async ({ page, go, body, arm, v, P, RG, rec, sleep, base }) => {
    const mk = [
      ["keyvaults", "kv", `${P}/Microsoft.KeyVault/vaults/acttabskv`, v("2023-07-01"), { location: "eastus", properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } }, "acttabskv"],
      ["storage", "storage", `${P}/Microsoft.Storage/storageAccounts/acttabssa1`, v("2023-01-01"), { location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2" }, "acttabssa1"],
      ["vnets", "vnet", `${P}/Microsoft.Network/virtualNetworks/acttabsvn`, v("2023-11-01"), { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.5.0.0/16"] } } }, "acttabsvn"],
      ["nsgs", "nsg", `${P}/Microsoft.Network/networkSecurityGroups/acttabsnsg`, v("2023-11-01"), { location: "eastus", properties: {} }, "acttabsnsg"],
    ];
    const errs = []; page.on("pageerror", (e) => errs.push(String(e.message).split("\n")[0]));
    for (const [route, label, path, ver, b, name] of mk) {
      const r = await arm("PUT", path + ver, b); if (r.status >= 300) { rec(`${label}: create`, "FAIL", r.status); continue; }
      await go(`/${route}/${RG}/${name}`);
      const hrefs = await page.evaluate((n) => [...new Set([...document.querySelectorAll("a[href^='#/']")].map((a) => a.getAttribute("href")).filter((h) => h.includes("/" + n + "/") && h.split("/").length >= 5))], name);
      let blank = [], notSim = [], bad = [];
      for (const h of hrefs) {
        await page.goto(`${base}/v4/azure/index.html${h}`, { waitUntil: "domcontentloaded" }); await sleep(1100);
        const t = (await page.locator("body").innerText()).replace(/\s+/g, " ");
        const main = t.split(name).slice(-1)[0] || t;
        if (main.length < 25) blank.push(h.split("/").pop());
        else if (/isn't backed by a Vyomi backend|Not simulated/i.test(t)) notSim.push(h.split("/").pop());
        if (/\bundefined\b|\[object Object\]|Cannot read prop/.test(t)) bad.push(h.split("/").pop());
      }
      rec(`${label}: found detail tabs to open`, hrefs.length >= 8 ? "PASS" : "FAIL", `${hrefs.length} tabs`);
      rec(`${label}: no tab is blank (<25 chars)`, blank.length === 0 ? "PASS" : "FAIL", blank.join(","));
      rec(`${label}: no tab shows 'undefined' / '[object Object]'`, bad.length === 0 ? "PASS" : "FAIL", bad.join(","));
      if (notSim.length) rec(`${label}: tabs that render the honest Not-simulated panel`, "NOTE", notSim.join(","));
    }
    rec("no uncaught page errors while sweeping the tabs", errs.length === 0 ? "PASS" : "FAIL", errs.slice(0, 2).join(" | "));
  } },
  { id: "metrics", title: "Metrics (measured)", fn: async ({ page, go, body, arm, v, P, RG, rec, sleep, tab }) => {
    const a = "actmxa", b = "actmxb", rp = (n) => `${P}/Microsoft.KeyVault/vaults/${n}`, props = { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } };
    for (const n of [a, b]) await arm("PUT", rp(n) + v("2023-07-01"), { location: "eastus", properties: props });
    for (let i = 0; i < 3; i++) await arm("PATCH", rp(a) + v("2023-07-01"), { tags: { i: String(i) } });
    const now = Date.now(), ts = `${new Date(now - 3600e3).toISOString().slice(0, 19)}Z/${new Date(now + 300e3).toISOString().slice(0, 19)}Z`;
    const total = async (n) => { const r = await arm("GET", `${rp(n)}/providers/Microsoft.Insights/metrics?metricnames=ActivityOperations&aggregation=Total&interval=PT1M&timespan=${ts}&api-version=2018-01-01`); return r.status === 200 ? (r.json.value[0]?.timeseries?.[0]?.data || []).reduce((s, d) => s + (d.total || 0), 0) : -1; };
    const ta = await total(a), tb = await total(b);
    rec("Measured: 1 create + 3 writes on vault A -> ActivityOperations total >= 4", ta >= 4 ? "PASS" : "FAIL", `A=${ta}`);
    rec("Measured: vault B (create only) shows a different, smaller series", tb >= 1 && tb < ta ? "PASS" : "FAIL", `B=${tb} A=${ta}`);
    const idle = await arm("GET", `${rp(a)}/providers/Microsoft.Insights/metrics?metricnames=ActivityOperations&aggregation=Total&interval=PT1M&timespan=${new Date(now - 7200e3).toISOString().slice(0, 19)}Z/${new Date(now - 3600e3).toISOString().slice(0, 19)}Z&api-version=2018-01-01`);
    const idleSum = (idle.json?.value?.[0]?.timeseries?.[0]?.data || []).reduce((s, d) => s + (d.total || 0), 0);
    rec("Measured: a window with no activity is empty (no seeded series)", idle.status === 200 && idleSum === 0 ? "PASS" : "FAIL", `status ${idle.status} sum ${idleSum}`);
    await go(`/keyvaults/${RG}/${a}/metrics`); await sleep(2500);
    const t = await body();
    rec("Key vault Metrics tab opens a real chart page (Activity operations offered, no Not-simulated panel)", /Activity operations|ActivityOperations/i.test(t) && !/isn't backed by a Vyomi backend/.test(t) ? "PASS" : "FAIL", t.slice(0, 140));
  } },
  { id: "tags", title: "Tags tab", fn: async ({ page, go, arm, v, poll, shows, tab, P, RG, rec, sleep }) => {
    const items = [
      ["vnets", `${P}/Microsoft.Network/virtualNetworks/acttagvn`, v("2023-11-01"), { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.6.0.0/16"] } } }, "acttagvn"],
      ["loganalytics", `${P}/Microsoft.OperationalInsights/workspaces/acttagws`, v("2022-10-01"), { location: "eastus", properties: { sku: { name: "PerGB2018" } } }, "acttagws"],
      ["appconfiguration", `${P}/Microsoft.AppConfiguration/configurationStores/acttagappcfg`, v("2023-03-01"), { location: "eastus", sku: { name: "standard" } }, "acttagappcfg"],
    ];
    for (const [route, path, ver, b, name] of items) {
      const mk = await arm("PUT", path + ver, b); if (mk.status >= 300) { rec(`${route}: create`, "FAIL", mk.status); continue; }
      await go(`/${route}/${RG}/${name}/tags`);
      try {
        await page.getByLabel("Tag name 1").fill("uitag"); await page.getByLabel("Tag value 1").fill("fromui");
        await page.getByRole("button", { name: /^Apply$/ }).dispatchEvent("click");
        const ok = await poll(async () => (await arm("GET", path + ver)).json?.tags?.uitag === "fromui", 20000);
        rec(`${route}: UI->API: tag added in the Tags tab and applied is stored on the resource (readable over ARM)`, ok ? "PASS" : "FAIL", JSON.stringify((await arm("GET", path + ver)).json?.tags));
        await go(`/${route}/${RG}/${name}/tags`);
        const shown = await poll(async () => /uitag/.test(await page.evaluate(() => [...document.querySelectorAll("input")].map((i) => i.value).join(","))) || null, 15000, 1000);
        rec(`${route}: the applied tag is shown again when the tab is re-opened`, shown ? "PASS" : "FAIL");
      } catch (e) { rec(`${route}: UI tag edit`, "FAIL", String(e.message).split("\n")[0]); }
    }
  } },
];
