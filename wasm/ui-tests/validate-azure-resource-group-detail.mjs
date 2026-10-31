/* Azure console: a resource group opens a detail page with the group's own
 * properties and the resources it holds (GET .../resources), and the page
 * reflects a resource created in that group and a group's tags.
 * Nano: default. Offline: VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/azure. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const offline = process.env.VYOMI_CONSOLE_URL;
let server, base;
if (!offline) ({ server, base } = await startServer());
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (name, ok, note = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + note}`); };
try {
  if (offline) await page.goto(offline, { waitUntil: "domcontentloaded" });
  else await bootConsole(page, base, "/azure-console.html");
  await page.waitForFunction(() => typeof SUB === "string" && SUB && typeof arm === "function", null, { timeout: 120000 });
  const s = Date.now().toString(36), rg = "rgd" + s, vault = "kv" + s;
  await page.evaluate(async ([rg, v]) => {
    const j = (b) => ({ method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    await fetch(`/subscriptions/${SUB}/resourcegroups/${rg}?api-version=2021-04-01`, j({ location: "westeurope", tags: { team: "qa" } }));
    await fetch(`/subscriptions/${SUB}/resourceGroups/${rg}/providers/Microsoft.KeyVault/vaults/${v}?api-version=2023-07-01`, j({ location: "westeurope", properties: {} }));
  }, [rg, vault]);
  await page.locator("#rail .navitem, .navitem", { hasText: "Resource groups" }).first().click();
  await page.locator("#main a.reslink", { hasText: rg }).first().click();
  await page.waitForSelector("#rgResources", { timeout: 15000 });
  await sleep(500);
  const txt = await page.locator("#main").innerText();
  check("heading is the group name", (await page.locator("#main h1").innerText()).trim() === rg);
  check("shows group location", /westeurope/.test(txt), txt.slice(0, 200));
  check("shows group tag", /team : qa/.test(txt));
  check("lists the vault created in the group", (await page.locator("#rgResources").innerText()).includes(vault));
  check("shows the resource type", /Microsoft\.KeyVault\/vaults/i.test(await page.locator("#rgResources").innerText()));
  const st = await page.evaluate(async (rg) => (await fetch(`/subscriptions/${SUB}/resourcegroups/nope-${rg}/resources?api-version=2021-04-01`)).status, rg);
  check("resources of a missing group is 404", st === 404, String(st));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
