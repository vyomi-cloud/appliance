/* Goal: "no detail sub-screen left unimplemented" for the Azure Nano console.
 * Creates a resource (ARM PUT), opens its detail blade, clicks EACH sub-nav tab,
 * and asserts the .sub-content pane renders >25 chars — so no tab is ever blank.
 * The VM service carries the most stub tabs (diagnose/identity/backup/extensions/
 * runCommand/alerts); we also sweep storage + sql + keyvault for breadth.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const allResults = [];

// Create a resource via the console's own ARM helper, then open its detail and
// walk every sub-nav tab, recording each tab's rendered content length.
async function sweepService(svcKey, resName) {
  return page.evaluate(async ({ svcKey, resName }) => {
    const svc = (CATALOG.services || []).find((s) => s.key === svcKey);
    if (!svc) return { svcKey, error: "service not in catalog" };

    // Build a minimal valid body from createFields defaults (ARM PUT).
    const body = { location: LOCATION, properties: {} };
    (svc.createFields || []).forEach((f) => {
      if (!f.name || f.name === "name") return;
      const def = f.default;
      if (def === undefined) return;
      setPath(body, f.name, def);
    });
    const put = await arm("PUT", resPath(svc, resName), body, svc.apiVersion);
    const full = (put.ok && put.json) ? put.json : { id: resPath(svc, resName), name: resName, ...body };

    await openDetail(svc, full);
    // openDetail refetches async; wait for the sub-nav to populate.
    const t0 = Date.now();
    while (Date.now() - t0 < 5000) {
      if (document.querySelectorAll(".sub-nav-item").length) break;
      await new Promise((r) => setTimeout(r, 120));
    }

    const items = [...document.querySelectorAll(".sub-nav-item")];
    const tabs = [];
    for (let i = 0; i < items.length; i++) {
      const el = [...document.querySelectorAll(".sub-nav-item")][i];
      const label = (el.querySelector(".lbl")?.innerText || el.innerText || "").trim();
      el.click();
      await new Promise((r) => setTimeout(r, 180));
      const c = document.querySelector(".sub-content");
      const text = (c ? c.innerText : "").trim();
      tabs.push({ tab: label, len: text.length, blank: text.length < 25 });
    }
    // close blade for next service
    const cb = document.getElementById("bladeClose"); cb && cb.click();
    return { svcKey, putStatus: put.status, tabs };
  }, { svcKey, resName });
}

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(500);
  for (const [svcKey, name] of [["vm", "vm-tabtest"], ["storage", "sttabtest01"], ["sql", "sql-tabtest"], ["keyvault", "kv-tabtest"]]) {
    const r = await sweepService(svcKey, name);
    allResults.push(r);
    await sleep(300);
  }
} catch (e) {
  allResults.push({ svcKey: "(err)", error: String(e).split("\n")[0] });
}

await browser.close();
server.close();

let total = 0, blanks = 0;
console.log("===== Azure detail sub-screens — content check =====");
for (const svc of allResults) {
  if (svc.error) { console.log(`  !! ${svc.svcKey}: ${svc.error}`); blanks++; total++; continue; }
  console.log(`\n  [${svc.svcKey}] PUT ${svc.putStatus} — ${svc.tabs.length} tabs`);
  for (const t of svc.tabs) {
    total++;
    if (t.blank) blanks++;
    console.log(`    [${t.blank ? "BLANK" : "OK   "}] ${String(t.tab).padEnd(28)} len:${t.len}`);
  }
}
console.log(`\n${total - blanks}/${total} tabs render content` + (blanks ? ` — ${blanks} BLANK` : " — NO blank tabs"));
process.exit(blanks ? 1 : 0);
