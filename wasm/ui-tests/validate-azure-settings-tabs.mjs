/* SQL / Cosmos / Virtual network / Key Vault settings tabs are backed by the resource's ARM
 * properties: Save PATCHes them and the saved value is shown again when the tab is reopened.
 * Works against Nano (default) or offline (VYOMI_CONSOLE_URL).
 */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
const srv = url ? null : await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); if (!ok) failed++; };
const S = Date.now().toString(36);

const render = (svcKey, name, key, act) => page.evaluate(async ([svcKey, name, key, act]) => {
  const svc = svcByKey(svcKey);
  const r = await arm("GET", resPath(svc, name), undefined, svc.apiVersion);
  const host = document.createElement("div"); document.body.append(host);
  await SUB_RENDERERS[key](svc, r.json, host);
  await new Promise((x) => setTimeout(x, 800));
  if (act) {
    for (const [i, v] of Object.entries(act.fill || {})) host.querySelectorAll("input,select")[i].value = v;
    if (act.click) { [...host.querySelectorAll("button")].find((b) => b.innerText.trim() === act.click).click(); await new Promise((x) => setTimeout(x, 1200)); }
  }
  const t = host.innerText + " " + [...host.querySelectorAll("input,select")].map((e) => e.value).join(" ");
  host.remove(); return t;
}, [svcKey, name, key, act]);
const create = (svcKey, name, body) => page.evaluate(async ([svcKey, name, body]) => {
  const svc = svcByKey(svcKey);
  return (await arm("PUT", resPath(svc, name), body, svc.apiVersion)).status;
}, [svcKey, name, body]);

try {
  if (url) { await page.goto(url, { waitUntil: "domcontentloaded" }); await page.waitForSelector("#navItems .navitem", { timeout: 60000 }); }
  else await bootConsole(page, srv.base, "/azure-console.html");
  await sleep(1500);
  const cases = [
    ["sql", "sqlsrv" + S, { location: "eastus", properties: { administratorLogin: "sqladmin", administratorLoginPassword: "P@ssw0rd-123456" } },
      [["tde", { 0: "Disabled" }, /Disabled/], ["auditing", { 0: "Enabled", 1: "stauditlogs" }, /stauditlogs/], ["defender", { 0: "Enabled" }, /Enabled/]]],
    ["cosmos", "cosmos" + S, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard" } },
      [["consistency", { 0: "Strong" }, /Strong/], ["defender", { 0: "Enabled" }, /Enabled/]]],
    ["vnet", "vnet" + S, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] } } },
      [["dnsservers", { 0: "10.0.0.4,10.0.0.5" }, /10\.0\.0\.4,10\.0\.0\.5/], ["ddos", { 0: "true" }, /true/]]],
    ["keyvault", "kv" + S, { location: "eastus", properties: { sku: { family: "A", name: "standard" }, tenantId: "00000000-0000-0000-0000-000000000000" } },
      [["accessconfig", { 0: "true" }, /true/]]],
  ];
  for (const [svcKey, name, body, tabs] of cases) {
    const st = await create(svcKey, name, body);
    check(st === 200 || st === 201, `${svcKey}: resource created`, String(st));
    for (const [key, fill, re] of tabs) {
      let t = await render(svcKey, name, key, { fill, click: "Save" });
      check(re.test(t), `${svcKey}/${key}: saved value shown`, t.slice(-300));
      t = await render(svcKey, name, key);
      check(re.test(t) && !/simulated/i.test(t), `${svcKey}/${key}: value survives re-open`, t.slice(0, 200));
    }
  }
  const t = await render("sql", "sqlsrv" + S, "failover", { fill: { 0: "fog-1", 1: "partner-srv" }, click: "Add" });
  check(/fog-1/.test(t) && /partner-srv/.test(t) && /20\d\d-\d\d-\d\dT/.test(t), "sql/failover: group recorded with timestamp", t.slice(0, 200));
  check(/fog-1/.test(await render("sql", "sqlsrv" + S, "failover")), "sql/failover: survives re-open");
  const c = await render("keyvault", "kv" + S, "certificates", { fill: { 0: "web-cert" }, click: "Add" });
  check(/web-cert/.test(c) && /CN=contoso\.com/.test(c), "keyvault/certificates: certificate recorded");
  check(/web-cert/.test(await render("keyvault", "kv" + S, "certificates")), "keyvault/certificates: survives re-open");
} catch (e) {
  check(false, "validator ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
srv?.server.close();
process.exit(failed ? 1 : 0);
