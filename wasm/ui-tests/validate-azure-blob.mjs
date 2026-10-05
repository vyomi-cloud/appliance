/* Goal-1: drive the Azure Blob-containers UI create, assert the UI list reflects it
 * AND the data-plane API agrees (UI wiring, not just API). */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const NAME = "ui-container-1";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let apiHasIt = false;
page.on("response", async (r) => {
  if (r.url().endsWith("/api/azure/blobcontainers") && r.request().method() === "GET") {
    try { const j = await r.json(); if ((j.items || []).some((i) => i.name === NAME)) apiHasIt = true; } catch (_) {}
  }
});
const out = {};
try {
  await bootConsole(page, base, "/azure-console.html");
  await page.evaluate((sel) => { const el = [...document.querySelectorAll(sel)].find((e) => (e.innerText || "").includes("Blob containers")); el && el.click(); }, RAIL_SEL);
  await sleep(1500);
  // Open create blade
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /create/i.test(x.innerText)); b && b.click(); });
  await sleep(800);
  out.bladeOpen = await page.evaluate(() => { const b = document.querySelector("#bladeBody"); return !!b && b.querySelectorAll("input").length > 0; });
  // Fill the name field + submit
  await page.evaluate((name) => {
    const body = document.querySelector("#bladeBody");
    const inp = body.querySelector("input"); if (inp) { inp.value = name; inp.dispatchEvent(new Event("input", { bubbles: true })); }
    const btn = [...body.querySelectorAll("button")].find((b) => /^create$/i.test(b.innerText.trim()));
    if (btn) btn.click();
  }, NAME);
  await sleep(2500);
  // Assert the UI list now shows it
  out.uiListed = await page.evaluate((name) => (document.querySelector("#main").innerText || "").includes(name), NAME);
  // Force a fresh list fetch (refresh) to confirm the API agrees
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /refresh/i.test(x.innerText)); b && b.click(); });
  await sleep(1500);
} catch (e) { out.err = String(e).split("\n")[0]; }
await browser.close(); server.close();

out.apiHasIt = apiHasIt;
const pass = out.bladeOpen && out.uiListed && out.apiHasIt;
console.log("Azure Blob data-plane UI create:", JSON.stringify(out, null, 1));
console.log("\nRESULT:", pass ? "PASS — UI create → blade → listed in UI AND data-plane API agrees" : "FAIL");
process.exit(pass ? 0 : 1);
