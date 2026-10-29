/* Nano console conformance: Azure Network Security Group and Role Definition can be created with the
 * form's default values and show up in the grid with every column filled.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-nsg-roledef-create.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const bad = [];
page.on("pageerror", (e) => bad.push(String(e.message).split("\n")[0]));
try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  for (const [svc, nameRe] of [[/Network Security Group/i, /^nsg-/], [/Role Definition/i, /^[0-9a-f-]{36}$/]]) {
    const label = String(svc);
    const rail = page.locator(RAIL_SEL).filter({ hasText: svc }).first();
    if (!(await rail.count())) { check(false, `${label} is on the Nano console rail`); continue; }
    await rail.click({ timeout: 5000 });
    await sleep(1500);
    await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
    await sleep(1000);
    const name = (await page.locator("#blade input").first().inputValue()) || "";
    check(nameRe.test(name), `${label}: create form has a realistic default name`, `name="${name}"`);
    await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
    const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
    for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
    check((await rowFor().count()) > 0, `${label}: created resource appears in the list`, name);
    if (await rowFor().count()) {
      const cells = (await rowFor().locator("td").allInnerTexts()).map((c) => c.trim());
      check(cells.length >= 3 && !cells.slice(0, 4).some((c) => BLANK.test(c)), `${label}: grid columns are filled`, JSON.stringify(cells));
    }
  }
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
process.exit(fails ? 1 : 0);
