// Remaining services: API->UI list + tag round trip + UI Delete (type-to-confirm) -> ARM gone, plus per-service extras.
const svc = (id, title, route, ns, type, ver, body, opts = {}) => ({ id, title, fn: async ({ arm, v, go, body: pageBody, click, tab, poll, shows, uiDelete, page, RG, P, SUB, sleep, rec }) => {
  const name = opts.name || `act${id}1`, V = v(ver), rp = `${P}/${ns}/${type}/${name}`, blade = `/${opts.bladeRoute || route}/${RG}/${name}`;
  const mk = await arm("PUT", rp + V, { location: opts.loc || "eastus", ...(typeof body === "function" ? body(P, SUB) : body) });
  if (mk.status >= 300) { rec("API create", mk.status === 403 ? "NOT-AUTOMATED" : "FAIL", `${mk.status} ${mk.text.slice(0, 110)}`); return; }
  rec("API create", "PASS", mk.status);
  if (!opts.noList) { await go("/" + (opts.listRoute || route)); rec("API->UI: resource created over ARM is listed in the console", (await shows(new RegExp(name))) ? "PASS" : "FAIL"); }
  if (!opts.noTags) {
  await arm("PATCH", rp + V, { tags: { viaapi: "ok" } });
  await go(blade); await tab("Tags").catch(() => {});
  { let vals = ""; const okT = await poll(async () => { vals = await page.evaluate(() => [...document.querySelectorAll("input")].map((i) => i.value).join(",")); return /viaapi/.test(vals + (await pageBody())) ? true : null; }, 15000, 1000); rec("API->UI: tag set over ARM shows in the Tags tab", okT ? "PASS" : "FAIL", vals.slice(0, 60)); }
  }
  if (opts.extra) await opts.extra({ uiDelete, arm, v, go, click, tab, poll, shows, page, RG, P, SUB, sleep, rec, rp, V, blade, name, body: pageBody });
  if (opts.noUiDelete) { rec("UI Delete of the resource itself", "NOT-AUTOMATED", opts.noUiDelete); await arm("DELETE", rp + V); return; }
  await uiDelete(name, blade, opts.delBtn);
  rec("UI->API: Delete (type-to-confirm) removes it from ARM", (await poll(async () => (await arm("GET", rp + V)).status === 404, 25000)) ? "PASS" : "FAIL");
} });
export default [
  svc("vnets", "Virtual networks", "vnets", "Microsoft.Network", "virtualNetworks", "2023-11-01", { properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] } } }, { extra: async ({ arm, V, go, tab, click, page, shows, poll, rp, rec, sleep, blade }) => {
    await arm("PUT", `${rp}/subnets/apisub${V}`, { properties: { addressPrefix: "10.0.1.0/24" } });
    await go(blade); await tab("Subnets"); rec("API->UI: subnet created over ARM is listed under Subnets", (await shows(/apisub/)) ? "PASS" : "FAIL");
    try {
      await click(/Subnet/); await sleep(800);
      const dlg = page.getByRole("dialog").last(); await dlg.getByRole("textbox").first().fill("uisub");
      const ip = dlg.getByLabel(/Starting address|Address range|Address prefix/i); if (await ip.count()) await ip.first().fill("10.0.2.0");
      await dlg.getByRole("button", { name: /^(Add|Save|OK|Create)$/ }).first().dispatchEvent("click");
      const ok = await poll(async () => (await arm("GET", `${rp}/subnets/uisub${V}`)).status === 200, 20000);
      rec("UI->API: Add subnet in the console exists in ARM", ok ? "PASS" : "FAIL");
    } catch (e) { rec("UI->API: Add subnet", "FAIL", String(e.message).split("\n")[0]); }
  } }),
  svc("acr", "Container registries", "acr", "Microsoft.ContainerRegistry", "registries", "2023-07-01", { sku: { name: "Basic" } }, { name: "actacr1x" }),
  svc("eventgrid", "Event Grid", "eventgrid/topics", "Microsoft.EventGrid", "topics", "2022-06-15", { properties: {} }, { bladeRoute: "eventgrid/topics", listRoute: "eventgrid/topics" }),
  svc("loganalytics", "Log Analytics workspaces", "loganalytics", "Microsoft.OperationalInsights", "workspaces", "2022-10-01", { properties: { sku: { name: "PerGB2018" } } }),
  svc("appconfiguration", "App Configuration", "appconfiguration", "Microsoft.AppConfiguration", "configurationStores", "2023-03-01", { sku: { name: "standard" } }, { name: "actappconfig1" }),
  svc("cosmos", "Cosmos DB", "cosmos", "Microsoft.DocumentDB", "databaseAccounts", "2023-11-15", { kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }] } }, { delBtn: /^Delete account$/, extra: async ({ arm, V, rp, rec }) => {
    const d = await arm("PUT", `${rp}/sqlDatabases/apidb${V}`, { properties: { resource: { id: "apidb" } } });
    rec("API->ARM: SQL database created under the Cosmos account", d.status < 300 ? "PASS" : "FAIL", d.status);
  } }),
  svc("sql", "SQL servers", "sql/servers", "Microsoft.Sql", "servers", "2021-11-01", { properties: { administratorLogin: "adm", administratorLoginPassword: "Bd-Passw0rd!x" } }, { bladeRoute: "sql/servers", noList: true, noTags: true, noUiDelete: "the SQL server blade has no Delete command in the console (databases are deleted from the database blade)", extra: async ({ arm, V, go, shows, uiDelete, poll, rp, rec, name }) => {
    const d = await arm("PUT", `${rp}/databases/apidb${V}`, { location: "eastus", sku: { name: "Basic" } });
    rec("API create database under the server", d.status < 300 ? "PASS" : "FAIL", d.status);
    await go("/sql"); rec("API->UI: database created over ARM is listed in SQL databases", (await shows(/apidb/)) ? "PASS" : "FAIL");
    await uiDelete("apidb", `/sql/${(rp.match(/resourceGroups\/([^/]+)/) || [])[1]}/${name}/apidb`);
    rec("UI->API: Delete database in the console removes it from ARM", (await poll(async () => (await arm("GET", `${rp}/databases/apidb${V}`)).status === 404, 25000)) ? "PASS" : "FAIL");
  } }),
  svc("aks", "Kubernetes services", "aks", "Microsoft.ContainerService", "managedClusters", "2023-10-01", { identity: { type: "SystemAssigned" }, properties: { dnsPrefix: "x", agentPoolProfiles: [{ name: "np", count: 1, vmSize: "Standard_B2s", mode: "System" }] } }),
];
