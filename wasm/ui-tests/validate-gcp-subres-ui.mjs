/* UI-level: open a Pub/Sub topic + Cloud SQL instance detail, click the
 * sub-resource tab, create via the in-tab form, confirm the list renders it. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];

async function openService(rx) {
  await page.evaluate((r) => { const e = [...document.querySelectorAll(r.sel)].find((x) => new RegExp(r.rx, "i").test((x.innerText || "") + (x.getAttribute("data-service") || ""))); e && e.click(); }, { sel: RAIL_SEL, rx });
  await sleep(1200);
}
async function clickTab(label) {
  return page.evaluate((lbl) => { const items = [...document.querySelectorAll(".sub-nav .nav-item, .sub-nav a")]; const t = items.find((x) => (x.innerText || "").toLowerCase().includes(lbl.toLowerCase())); if (t) { t.click(); return true; } return false; }, label);
}

try {
  await bootConsole(page, base, "/gcp-console.html");

  // ----- Pub/Sub → topic → Subscriptions tab -----
  await openService("pubsub|pub/sub");
  await page.evaluate(async () => { await fetch("/api/gcp/pubsub/v1/projects/demo/topics", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "uitopic" }) }); });
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /refresh/i.test(x.innerText)); b && b.click(); });
  await sleep(1200);
  await page.evaluate(() => { const e = [...document.querySelectorAll("#main a.id, #main a")].find((x) => (x.innerText || "").trim().includes("uitopic")); e && e.click(); });
  await sleep(1000);
  const subTab = await clickTab("Subscriptions");
  await sleep(600);
  // use the in-tab create form
  const created = await page.evaluate(async () => {
    const inp = document.querySelector(".sub-content input"); const btn = [...document.querySelectorAll(".sub-content button")].find((b) => /create/i.test(b.innerText));
    if (!inp || !btn) return false; inp.value = "uisub"; inp.dispatchEvent(new Event("input", { bubbles: true })); btn.click(); return true;
  });
  await sleep(1200);
  const subText = await page.evaluate(() => (document.querySelector(".sub-content")?.innerText || ""));
  results.push(["pubsub Subscriptions tab", subTab && created && /uisub/.test(subText)]);

  // ----- Cloud SQL → instance → Databases tab -----
  await openService("cloud sql|cloudsql|sql");
  await page.evaluate(async () => { await fetch("/api/gcp/rds/databases", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "uipg", databaseVersion: "POSTGRES_15" }) }); });
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /refresh/i.test(x.innerText)); b && b.click(); });
  await sleep(1200);
  await page.evaluate(() => { const e = [...document.querySelectorAll("#main a.id, #main a")].find((x) => (x.innerText || "").trim().includes("uipg")); e && e.click(); });
  await sleep(1000);
  const dbTab = await clickTab("Databases");
  await sleep(600);
  const dbCreated = await page.evaluate(async () => {
    const inp = document.querySelector(".sub-content input"); const btn = [...document.querySelectorAll(".sub-content button")].find((b) => /create/i.test(b.innerText));
    if (!inp || !btn) return false; inp.value = "uidb"; inp.dispatchEvent(new Event("input", { bubbles: true })); btn.click(); return true;
  });
  await sleep(1200);
  const dbText = await page.evaluate(() => (document.querySelector(".sub-content")?.innerText || ""));
  results.push(["cloudsql Databases tab", dbTab && dbCreated && /uidb/.test(dbText)]);
} catch (e) { results.push(["(err)", false, String(e).split("\n")[0]]); }
await browser.close(); server.close();

console.log("===== GCP sub-resource tabs — UI render + create =====");
let ok = true;
for (const [label, pass, note] of results) { if (!pass) ok = false; console.log(`  [${pass ? "PASS" : "FAIL"}] ${label}${note ? " " + note : ""}`); }
console.log("\nRESULT:", ok ? "PASS — sub-resource tabs render real data in the UI + create works" : "FAIL");
process.exit(ok ? 0 : 1);
