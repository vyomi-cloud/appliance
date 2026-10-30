/* API Management detail tabs are backed by the service's ARM properties: Named values,
 * Custom domains and Backup list what is stored on the resource, Add/Delete persist via
 * PATCH, and the data is still there when the tab is rendered again. Diagnose shows the
 * resource's own health. Works against Nano (default) or offline (VYOMI_CONSOLE_URL).
 */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
const srv = url ? null : await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); if (!ok) failed++; };
const NAME = "apim-tabs-" + Date.now().toString(36);

// Render tab `key` for the service in a fresh host (as when the tab is reopened); returns its text.
const render = (key, act) => page.evaluate(async ([name, key, act]) => {
  const svc = svcByKey("apim");
  const r = await arm("GET", resPath(svc, name), undefined, svc.apiVersion);
  const host = document.createElement("div"); document.body.append(host);
  await SUB_RENDERERS[key](svc, r.json, host);
  await new Promise((x) => setTimeout(x, 800));
  if (act) {
    for (const [i, v] of Object.entries(act.fill || {})) {
      const el = host.querySelectorAll("input,select")[i]; el.value = v;
    }
    if (act.click) { [...host.querySelectorAll("button")].find((b) => b.innerText.trim() === act.click).click(); await new Promise((x) => setTimeout(x, 1200)); }
  }
  const t = host.innerText; host.remove(); return t;
}, [NAME, key, act]);

try {
  if (url) { await page.goto(url, { waitUntil: "domcontentloaded" }); await page.waitForSelector("#navItems .navitem", { timeout: 60000 }); }
  else await bootConsole(page, srv.base, "/azure-console.html");
  await sleep(1500);
  const made = await page.evaluate(async (name) => {
    const svc = svcByKey("apim");
    const r = await arm("PUT", resPath(svc, name), { location: "eastus", sku: { name: "Developer", capacity: 1 },
      properties: { publisherEmail: "a@b.co", publisherName: "T" } }, svc.apiVersion);
    return r.status;
  }, NAME);
  check(made === 200 || made === 201, "APIM service created", String(made));

  let t = await render("namedvalues");
  check(/No named values/i.test(t), "Named values: empty state before adding", t.slice(0, 150));
  t = await render("namedvalues", { fill: { 0: "backend-url", 1: "https://orders.example.com" }, click: "Add" });
  check(/backend-url/.test(t) && /orders\.example\.com/.test(t), "Named values: added row shown", t.slice(0, 200));
  t = await render("namedvalues");
  check(/backend-url/.test(t), "Named values: row survives re-open", t.slice(0, 200));

  t = await render("customdomains", { fill: { 1: "api.contoso.com" }, click: "Add" });
  check(/api\.contoso\.com/.test(t), "Custom domains: added hostname shown", t.slice(0, 200));
  t = await render("customdomains");
  check(/api\.contoso\.com/.test(t), "Custom domains: hostname survives re-open", t.slice(0, 200));

  t = await render("backups", { fill: { 0: "stbackups", 2: "nightly-1" }, click: "Add" });
  check(/nightly-1/.test(t) && /stbackups/.test(t) && /20\d\d-\d\d-\d\dT/.test(t), "Backup: backup recorded with timestamp", t.slice(0, 250));
  t = await render("backups");
  check(/nightly-1/.test(t), "Backup: survives re-open", t.slice(0, 200));

  t = await render("networking", { fill: { 0: "Disabled" }, click: "Save" });
  check(/Public network access/.test(t) && /Disabled/.test(t), "Virtual network: public access saved on the resource", t.slice(0, 200));
  t = await render("networking");
  check(/Disabled/.test(t) && /Resource\s+apim-tabs-/.test(t), "Virtual network: shows this resource's saved setting on re-open", t.slice(0, 200));

  t = await render("diagnose");
  check(new RegExp("Resource health").test(t) && /Availability\s+Available/.test(t) && !/simulated/i.test(t), "Diagnose: shows this resource's health, not a simulated notice", t.slice(0, 250));
  // Leave no APIM behind (free tier allows one per space).
  await page.evaluate(async (name) => { const svc = svcByKey("apim"); await arm("DELETE", resPath(svc, name), undefined, svc.apiVersion); }, NAME);
} catch (e) {
  check(false, "validator ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
srv?.server.close();
process.exit(failed ? 1 : 0);
