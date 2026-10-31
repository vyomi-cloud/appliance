/* Nano: an EC2 instance launched through the console with default values lists with
 * every grid column filled (id, name, type, state, public + private IPv4) and is
 * still there after a console reload. */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const rows = () => page.locator("#main table tr").evaluateAll((trs) => trs.map((tr) => [...tr.children].map((c) => c.innerText.trim())));
try {
  await bootConsole(page, base, "/aws-console.html");
  await page.locator("#rail >> text=EC2").first().click();
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /launch instances/i }).first().click();
  await sleep(1200);
  await page.locator("#main button").filter({ hasText: /^\s*(rocket_launch)?\s*Launch instance\s*$/i }).last().click();
  await sleep(3000);
  const row = (await rows()).find((r) => r.some((c) => /^i-[0-9a-f]{17}$/.test(c)));
  check("launched instance is listed with an i-… id", !!row, JSON.stringify((await rows()).slice(-2)));
  check("no placeholder cells in the row", !!row && row.slice(1).every((c) => c && !/^[-—]$/.test(c)), JSON.stringify(row));
  check("state is running", !!row && row.includes("running"), JSON.stringify(row));
  const id = row && row.find((c) => /^i-/.test(c));
  const det = await page.evaluate(async (id) => { const r = await fetch("/api/ec2/instances/" + id); return { status: r.status, body: await r.json().catch(() => null) }; }, id);
  check("instance detail by its i-… id answers 200 with the same id", det.status === 200 && det.body && det.body.instance_id === id, `status ${det.status}`);
  const sgIds = (det.body && (det.body.security_group_ids || det.body.security_groups)) || [];
  check("instance carries a security group (default, or the launch-wizard one the form creates)", sgIds.length > 0 && /^sg-/.test(sgIds[0].group_id || sgIds[0]), JSON.stringify(sgIds));
  await sleep(1500);
  await page.goto(base + "/aws-console.html");
  await sleep(6000);
  const list = await page.evaluate(async () => (await (await fetch("/api/ec2/instances")).json()).items || []);
  check("instance survives a console reload", list.length === 1 && /^i-/.test(list[0].instance_id || ""), JSON.stringify(list).slice(0, 200));
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
