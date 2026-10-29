/* Nano: a Lambda function created through the console wizard with default values
 * lists with every grid column filled (name, runtime, handler, memory, timeout,
 * last modified) — no "—" cells. */
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
  await page.locator("#rail >> text=Lambda").first().click();
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /create function/i }).first().click();
  await sleep(1200);
  await page.locator("#main button").filter({ hasText: /Create resource/ }).first().click();
  await sleep(3000);
  const cells = await page.locator("#main table tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((c) => c.innerText.trim())));
  const row = cells.find((r) => r.includes("my-function"));
  check("created function is listed by name", !!row, JSON.stringify(cells.slice(-2)));
  check("no placeholder cells in the row", !!row && row.slice(1).every((c) => c && !/^[-—]$/.test(c)), JSON.stringify(row));
  await sleep(1500);   // let the store snapshot persist
  await page.goto(base + "/aws-console.html");
  await sleep(6000);
  const names = await page.evaluate(async () => (await (await fetch("/api/lambda/functions")).json()).functions.map((f) => f.name));
  check("function survives a console reload", names.includes("my-function"), JSON.stringify(names));
  check("no page error while opening the create wizard", errors.length === 0, errors.join(";"));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
