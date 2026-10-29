/* Azure flat create blades (Network Security Group, Role Definition) must create
 * a row. Role Definition has no name field (ARM keys it by GUID; the form asks for
 * Role Name only) and used to refuse with "Name is required"; required fields are
 * starred and a missing one is reported by name.
 * Nano by default; set VYOMI_CONSOLE_URL (e.g. http://localhost:9000/console/azure) to drive the offline console.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const OFFLINE = process.env.VYOMI_CONSOLE_URL;
const { server, base } = OFFLINE ? { server: null, base: "" } : await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); if (!ok) failed++; };

async function open(label) {
  const items = page.locator(RAIL_SEL);
  for (let i = 0; i < await items.count(); i++) {
    const t = (await items.nth(i).innerText()).trim().split("\n").pop();
    if (t === label) { await items.nth(i).click(); await sleep(1500); return true; }
  }
  return false;
}
const openCreate = async () => { await page.locator("#main button").filter({ hasText: /create/i }).first().click(); await sleep(1000); };
const submit = async () => { await page.locator("#blade button").filter({ hasText: /^\s*create\s*$/i }).last().click(); await sleep(2500); };

try {
  if (OFFLINE) { await page.goto(OFFLINE); await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 }); }
  else await bootConsole(page, base, "/azure-console.html");
  await sleep(1000);
  const sfx = Date.now().toString(36).slice(-5);

  check(await open("Network Security Group"), "Network Security Group service opens");
  await openCreate();
  const nameInp = page.locator("#blade .field input").first();
  await submit();
  check(await page.locator("#blade.open").count() > 0, "NSG create with empty name is refused (blade stays open)");
  await nameInp.fill(`nsg-${sfx}`);
  await submit();
  check((await page.locator("#main").innerText()).includes(`nsg-${sfx}`), "NSG row appears after create");

  check(await open("Role Definition"), "Role Definition service opens");
  await openCreate();
  check(await page.locator("#blade .field:has(.req)").count() > 0, "Role Name is marked required");
  await submit();
  check(await page.locator("#blade.open").count() > 0, "Role Definition create without Role Name is refused");
  await page.locator("#blade .field:has(.req) input").first().fill(`crawl-role-${sfx}`);
  await submit();
  const main = await page.locator("#main").innerText();
  check(main.includes(`crawl-role-${sfx}`), "Role Definition row (Role Name) appears after create");
  check(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/.test(main), "Role Definition is keyed by a GUID name");
} catch (e) {
  check(false, "validator ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
server?.close();
process.exit(failed ? 1 : 0);
