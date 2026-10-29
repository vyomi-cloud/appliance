/* Nano: a VPC created through the console wizard with default values lists with
 * every grid column filled (VPC ID, name, CIDR, state, subnets) and survives a reload. */
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
  await page.locator("#rail >> text=VPC").first().click();
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /^\s*add\s*Create VPC/i }).first().click();
  await sleep(1200);
  await page.locator("#main button").filter({ hasText: /Create resource/ }).first().click();
  await sleep(3000);
  const cells = await page.locator("#main table tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((c) => c.innerText.trim())));
  const row = cells.find((r) => r.includes("my-vpc"));
  check("created VPC is listed by name", !!row, JSON.stringify(cells.slice(-2)));
  check("no placeholder cells in the row", !!row && row.slice(1).every((c) => c && !/^[-—]$/.test(c)), JSON.stringify(row));
  await sleep(1500);   // let the store snapshot persist
  await page.goto(base + "/aws-console.html");
  await sleep(6000);
  const names = await page.evaluate(async () => (await (await fetch("/api/vpc/vpcs")).json()).items.map((f) => f.name));
  check("VPC survives a console reload", names.includes("my-vpc"), JSON.stringify(names));
  const lists = await page.evaluate(async () => {
    const o = {};
    for (const k of ["subnets", "route-tables", "internet-gateways"]) { const r = await fetch("/api/vpc/" + k); o[k] = [r.status, r.ok ? await r.json() : null]; }
    return o;
  });
  check("GET /api/vpc/subnets answers 200", lists["subnets"][0] === 200, String(lists["subnets"][0]));
  check("GET /api/vpc/internet-gateways answers 200", lists["internet-gateways"][0] === 200, String(lists["internet-gateways"][0]));
  const rts = (lists["route-tables"][1] || {}).route_tables || [];
  check("GET /api/vpc/route-tables lists the new VPC's main route table", lists["route-tables"][0] === 200 && rts.some((r) => r.is_main && r.name && r.routes.length), JSON.stringify(rts).slice(0, 200));
  check("no page error while opening the create wizard", errors.length === 0, errors.join(";"));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
