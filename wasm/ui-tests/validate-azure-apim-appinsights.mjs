/* Azure API Management > Application Insights tab lists the service's own
 * Application Insights loggers, a logger added in the tab persists through the
 * API and survives a reload, and the tab is distinct from Metrics.
 * Nano: default. Offline: VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/azure. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const offline = process.env.VYOMI_CONSOLE_URL;
let server, base;
if (!offline) ({ server, base } = await startServer());
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (name, ok, note = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + note}`); };
const boot = async () => {
  if (offline) await page.goto(offline, { waitUntil: "domcontentloaded" });
  else await bootConsole(page, base, "/azure-console.html");
  await page.waitForFunction(() => typeof SUB === "string" && SUB && typeof arm === "function", null, { timeout: 120000 });
};
const open = async (apim, tab) => {
  await page.locator(".navitem", { hasText: "API Management" }).first().click();
  await page.locator("#main tr.row", { hasText: apim }).first().click();
  await page.locator(".top-tabs button, .sub-nav .nav-item, .sub-nav a, .sub-nav-item, #main [role=tab], #main .tabs button", { hasText: tab }).first().click();
  await sleep(1500);
};
try {
  await boot();
  const av = "2023-05-01-preview";
  // The free tier allows one API Management service per space: create one only
  // if the space has none, otherwise use the existing one.
  const [apim, svc] = await page.evaluate(async (av) => {
    const coll = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service`;
    const j = (b) => ({ method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    let list = ((await (await fetch(`${coll}?api-version=${av}`)).json()).value) || [];
    if (!list.length) {
      await fetch(`${coll}/apimai${Date.now().toString(36)}?api-version=${av}`, j({ location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "qa" } }));
      list = ((await (await fetch(`${coll}?api-version=${av}`)).json()).value) || [];
    }
    const path = `${coll}/${list[0].name}`;
    await fetch(`${path}/loggers/seeded?api-version=${av}`, j({ properties: { loggerType: "applicationInsights", description: "seeded-logger", credentials: { instrumentationKey: "11111111-1111-1111-1111-111111111111" } } }));
    return [list[0].name, path];
  }, av);
  await open(apim, "Application Insights");
  let txt = await page.locator("#blade").innerText();
  check("tab lists the seeded logger", /seeded-logger/.test(txt), txt.slice(-200));
  check("tab shows the logger type", /applicationInsights/.test(txt));
  check("instrumentation key is not shown", !/11111111-1111/.test(txt));
  // Add through the tab's form.
  await page.locator("#blade button", { hasText: /add logger/i }).click();
  const lg = "added" + Date.now().toString(36);
  await page.locator("#blade .essentials input").nth(0).fill(lg);
  await page.locator("#blade .essentials input").nth(1).fill("added-by-ui");
  await page.locator("#blade button", { hasText: /^Create$/ }).click();
  await sleep(1500);
  const api = await page.evaluate(async ([p, av, lg]) => (await (await fetch(`${p}/loggers/${lg}?api-version=${av}`)).json()), [svc, av, lg]);
  check("logger added in the tab persists through the API", api.properties && api.properties.description === "added-by-ui", JSON.stringify(api).slice(0, 160));
  await boot();
  await open(apim, "Application Insights");
  txt = await page.locator("#blade").innerText();
  check("added logger is listed after reload", new RegExp(lg).test(txt));
  await page.locator(".sub-nav-item", { hasText: /^\s*(show_chart)?\s*Metrics/ }).first().click();
  await sleep(1500);
  const m = await page.locator("#blade").innerText();
  check("Metrics tab is distinct (no logger table)", !/seeded-logger/.test(m));
} catch (e) { check("run", false, String(e.stack).split("\n").slice(0,4).join(" | ")); }
await browser.close(); server?.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
