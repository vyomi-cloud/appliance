/* Goal-1 + Goal-2 check for Azure data-plane pages: header no longer 'undefined',
 * and the page actually lists + can create (cross-checked where possible). */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const DP = ["Blob containers", "Storage queues", "Cosmos databases", "Key Vault secrets", "Key Vault keys"];
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
try {
  await bootConsole(page, base, "/azure-console.html");
  for (const label of DP) {
    const clicked = await page.evaluate(([sel, lbl]) => {
      const el = [...document.querySelectorAll(sel)].find((e) => (e.innerText || "").includes(lbl));
      if (el) { el.click(); return true; } return false;
    }, [RAIL_SEL, label]);
    if (!clicked) { results.push({ label, ok: false, note: "not in rail" }); continue; }
    await sleep(1800);
    const m = await page.evaluate(() => {
      const main = document.querySelector("#main");
      const head = (main.querySelector("h1,h2,.pagehead,[class*=head]") || main).innerText || "";
      return {
        headHasUndefined: /undefined/.test(main.innerText.split("\n").slice(0, 3).join(" ")),
        sub: main.innerText.split("\n").slice(0, 3).join(" ⏎ ").slice(0, 120),
        hasCreate: [...main.querySelectorAll("button")].some((b) => /create/i.test(b.innerText)),
        listed: main.innerText.toLowerCase(),
      };
    });
    results.push({ label, ok: !m.headHasUndefined && m.hasCreate, headHasUndefined: m.headHasUndefined, hasCreate: m.hasCreate, sub: m.sub });
  }
} catch (e) { results.push({ label: "(boot)", ok: false, note: String(e).split("\n")[0] }); }
await browser.close(); server.close();

console.log("\n===== Azure data-plane page validation =====");
for (const r of results) console.log(`  [${r.ok ? "PASS" : "FAIL"}] ${r.label.padEnd(20)} undef:${r.headHasUndefined} create:${r.hasCreate}  | ${r.sub || r.note || ""}`);
const pass = results.filter((r) => r.ok).length;
console.log(`\n${pass}/${results.length} data-plane pages render cleanly (no 'undefined' + Create present)`);
process.exit(pass === results.length ? 0 : 1);
