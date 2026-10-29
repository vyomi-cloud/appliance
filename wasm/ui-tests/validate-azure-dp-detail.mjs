/* Azure data-plane services (Blob containers, Cosmos databases, Key Vault secrets
 * and keys, Storage queues) have no ARM namespace/type; opening a row's detail used
 * to request /providers/undefined/undefined/<name> and 404. The detail blade must
 * open without any ARM 404 and show the resource's own record.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); if (!ok) failed++; };
const bad = [];
page.on("response", (r) => { if (r.status() >= 400 && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url()}`); });

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(1000);
  const sfx = Date.now().toString(36).slice(-5);
  for (const label of ["Blob containers", "Cosmos databases", "Key Vault secrets", "Key Vault keys"]) {
    const items = page.locator(RAIL_SEL);
    let opened = false;
    for (let i = 0; i < await items.count(); i++) {
      if ((await items.nth(i).innerText()).trim().split("\n").pop() === label) { await items.nth(i).click(); opened = true; break; }
    }
    check(opened, `${label} service opens`);
    if (!opened) continue;
    await sleep(1200);
    const name = `dp${sfx}${label.replace(/[^A-Za-z]/g, "").slice(0, 4).toLowerCase()}`;
    await page.locator("#main button").filter({ hasText: /create/i }).first().click(); await sleep(800);
    await page.locator("#blade .field input").first().fill(name);
    await page.locator("#blade button").filter({ hasText: /^\s*create\s*$/i }).last().click(); await sleep(2000);
    bad.length = 0;
    await page.locator("#main table tr", { hasText: name }).first().locator("td").first().click(); await sleep(1500);
    check(!bad.some((b) => /undefined/.test(b) || b.startsWith("404")), `${label} detail: no 404 / undefined ARM path`, bad.join("; "));
    const blade = await page.locator("#blade").innerText();
    check(blade.includes(name), `${label} detail shows the resource's own record`, blade.slice(0, 120));
    await page.locator("#bladeClose").click().catch(() => {}); await sleep(300);
  }
} catch (e) {
  check(false, "validator ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
process.exit(failed ? 1 : 0);
