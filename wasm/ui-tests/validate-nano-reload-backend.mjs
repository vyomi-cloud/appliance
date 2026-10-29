/* Nano: after the console page reloads, /api/* reads must wait for the NEW page's
 * Pyodide instead of being posted to a not-yet-ready client (was HTTP 500
 * "backend timeout" on every ARM read after a navigation). */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const ARM = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/Microsoft.Sql/servers?api-version=2023-05-01-preview";
const read = () => page.evaluate(async (u) => {
  const t = Date.now(); const r = await fetch(u);
  return { status: r.status, ms: Date.now() - t, body: (await r.text()).slice(0, 120) };
}, ARM);
try {
  await bootConsole(page, base, "/azure-console.html");
  const a = await read();
  check("ARM list OK on first load", a.status === 200, `status ${a.status}`);
  for (let i = 1; i <= 2; i++) {
    await page.goto(base + "/azure-console.html", { waitUntil: "domcontentloaded" });
    await sleep(300);
    const b = await read();
    check(`ARM list OK right after reload #${i}`, b.status === 200, `status ${b.status} ${b.ms}ms ${b.status === 200 ? "" : b.body}`);
  }
} catch (e) { check("boot", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
