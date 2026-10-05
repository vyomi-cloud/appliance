/* Goal-2 (deep): every detail sub-screen renders content — no blank tabs.
 * Opens a Cloud Storage bucket, clicks each tab, asserts the sub-content isn't empty. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
try {
  await bootConsole(page, base, "/gcp-console.html");
  await page.evaluate((sel) => { const e = [...document.querySelectorAll(sel)].find((x) => /storage/i.test((x.innerText || "") + (x.getAttribute("data-service") || ""))); e && e.click(); }, RAIL_SEL);
  await sleep(1200);
  await page.evaluate(async () => { await fetch("/api/gcp/storage/v1/b", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "tabtest" }) }); });
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /refresh/i.test(x.innerText)); b && b.click(); });
  await sleep(1500);
  const opened = await page.evaluate(() => { const e = [...document.querySelectorAll("#main a.id, #main a")].find((x) => (x.innerText || "").trim().includes("tabtest")); if (e) { e.click(); return true; } return false; });
  await sleep(1500);
  const tabs = await page.evaluate(() => [...document.querySelectorAll(".sub-nav .nav-item, .sub-nav a")].map((e) => (e.innerText || "").trim()).filter(Boolean));
  for (let i = 0; i < tabs.length; i++) {
    await page.evaluate((i) => { const items = [...document.querySelectorAll(".sub-nav .nav-item, .sub-nav a")]; items[i] && items[i].click(); }, i);
    await sleep(500);
    const content = await page.evaluate(() => { const c = document.querySelector(".sub-content"); return (c ? c.innerText : "").trim(); });
    results.push({ tab: tabs[i], len: content.length, blank: content.length < 25 });
  }
  if (!opened) results.push({ tab: "(open bucket)", len: 0, blank: true, note: "could not open bucket detail" });
} catch (e) { results.push({ tab: "(err)", blank: true, note: String(e).split("\n")[0] }); }
await browser.close(); server.close();

console.log("===== Cloud Storage detail tabs — content check =====");
for (const r of results) console.log(`  [${r.blank ? "BLANK" : "OK   "}] ${String(r.tab).padEnd(16)} contentLen:${r.len ?? "-"} ${r.note || ""}`);
const blanks = results.filter((r) => r.blank);
console.log(`\n${results.length - blanks.length}/${results.length} tabs render content` + (blanks.length ? ` — BLANK: ${blanks.map((b) => b.tab).join(", ")}` : " — NO blank tabs ✓"));
process.exit(blanks.length ? 1 : 0);
