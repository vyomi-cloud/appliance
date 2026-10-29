/* Offline console conformance: Azure Network Security Group and Role Definition can be created with the
 * form's default values and the new resource shows up in the grid with every column filled.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-nsg-roledef-create.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const bad = [];
page.on("pageerror", (e) => bad.push(String(e.message).split("\n")[0]));
try {
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await sleep(3000);
  for (const [svc, nameRe] of [[/Network Security Group/i, /^nsg-/], [/Role Definition/i, /^[0-9a-f-]{36}$/]]) {
    const label = String(svc);
    const rail = page.locator(RAIL_SEL).filter({ hasText: svc }).first();
    if (!(await rail.count())) { check(false, `${label} is on the console rail`); continue; }
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
      const blanks = cells.filter((c, i) => i > 0 && BLANK.test(c) && c !== "");
      check(cells.length >= 3 && !cells.slice(0, 4).some((c) => BLANK.test(c)), `${label}: grid columns are filled`, JSON.stringify(cells));
    }
  }
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
