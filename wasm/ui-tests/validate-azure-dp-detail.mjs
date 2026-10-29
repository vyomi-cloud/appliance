/* Azure data-plane services (Blob containers, Cosmos DBs, Key Vault secrets/keys, queues):
 * opening a row's detail blade must not call a bogus ARM path (providers/undefined/undefined → 404)
 * and must show the resource's own record.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-dp-detail.mjs
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const DP = ["Blob containers", "Storage queues", "Cosmos databases", "Key Vault secrets", "Key Vault keys"];
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const bad = [];
page.on("response", (r) => { if (r.status() === 404 || r.status() >= 500) bad.push(`${r.status()} ${r.url().replace(base, "")}`); });
page.on("dialog", (d) => d.accept().catch(() => {}));
try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2000);
  for (const label of DP) {
    bad.length = 0;
    const name = "dpd" + Math.random().toString(36).slice(2, 7);
    await page.evaluate(([sel, lbl]) => [...document.querySelectorAll(sel)].find((e) => (e.innerText || "").includes(lbl))?.click(), [RAIL_SEL, label]);
    await sleep(1500);
    await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
    await sleep(800);
    await page.locator("#blade input").first().fill(name);
    await page.locator("#blade button").filter({ hasText: /^\s*create\s*$/i }).first().click({ timeout: 5000 });
    await sleep(2000);
    const row = page.locator("#main tr, #main .row").filter({ hasText: name }).first();
    check((await row.count()) > 0, `${label}: created resource is listed`);
    await row.locator("a, td").first().click({ timeout: 5000 }).catch(() => {});
    await sleep(1500);
    const blade = await page.locator("#blade").innerText();
    check(blade.includes(name), `${label}: detail blade shows the resource`, blade.slice(0, 80));
    await page.evaluate(() => (typeof closeBlade === "function" ? closeBlade() : document.querySelector("#blade .close, #blade [onclick*=close]")?.click()));
    await sleep(400);
    check(!bad.some((b) => /undefined/.test(b)) && bad.length === 0, `${label}: opening detail makes no failing/undefined API call`, bad.join("; "));
  }
} catch (e) { check(false, "flow completed", String(e).split("\n")[0]); }
await browser.close(); server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
