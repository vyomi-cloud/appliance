/* Nano: an API Gateway API created through the console with default values
 * lists with every grid column filled (API ID, name, endpoint type, created)
 * created) — no "—" cells. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await bootConsole(page, base, "/aws-console.html");
  await page.locator("#rail >> text=API Gateway").first().click();
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /^\s*add\s*Create/i }).first().click();
  await sleep(1200);
  await page.locator("#main button").filter({ hasText: /Create resource|^\s*(rocket_launch)?\s*Create\s*$/ }).first().click();
  await sleep(3000);
  const cells = await page.locator("#main table tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((c) => c.innerText.trim())));
  const row = cells.find((r) => r.includes("MyApi"));
  check("created API is listed by name", !!row, JSON.stringify(cells.slice(-2)));
  check("no placeholder cells in the row", !!row && row.slice(1).every((c) => c && !/^[-—]$/.test(c)), JSON.stringify(row));
  await sleep(1500);   // let the store snapshot persist
  await page.goto(base + "/aws-console.html");
  await sleep(6000);
  const names = await page.evaluate(async () => (await (await fetch("/api/apigateway/apis")).json()).apis.map((f) => f.name));
  check("API survives a console reload", names.includes("MyApi"), JSON.stringify(names));
  const sub = await page.evaluate(async () => {
    const apis = (await (await fetch("/api/apigateway/apis")).json()).apis;
    const id = (apis.find((f) => f.name === "MyApi") || {}).id;
    const out = {};
    for (const k of ["resources", "stages"]) { const r = await fetch(`/api/apigateway/apis/${id}/${k}`); out[k] = [r.status, r.ok ? await r.json() : null]; }
    return out;
  });
  const res = (sub.resources[1] || {}).resources || [], stg = (sub.stages[1] || {}).stages || [];
  check("GET .../resources lists the API's resource tree with methods", sub.resources[0] === 200 && res.some((r) => r.path === "/hello" && Object.keys(r.resource_methods).length), JSON.stringify(res).slice(0, 200));
  check("GET .../stages lists the deployed stage with an invoke URL", sub.stages[0] === 200 && stg.some((s) => s.stage_name && s.invoke_url), JSON.stringify(stg).slice(0, 200));
  check("no page error while opening the create wizard", errors.length === 0, errors.join(";"));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
