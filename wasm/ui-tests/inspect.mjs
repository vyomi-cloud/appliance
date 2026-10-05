/* Tolerant inspector — goto a page, wait, dump diagnostics (no strict ready gate).
 * Use to debug boot failures: UI_PATH=/azure-console.html node inspect.mjs */
import { startServer, chromium, sleep } from "./lib.mjs";
const PATH = process.env.UI_PATH || "/azure-console.html";
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const errs = []; page.on("pageerror", (e) => errs.push(String(e.message)));
const cons = []; page.on("console", (m) => { if (m.type() === "error") cons.push(m.text().slice(0, 160)); });
await page.goto(base + PATH, { waitUntil: "domcontentloaded" });
for (let i = 0; i < 8; i++) {
  await sleep(5000);
  const st = await page.evaluate(() => ({
    sw: !!(navigator.serviceWorker && navigator.serviceWorker.controller),
    rail: document.querySelector("#rail") ? document.querySelector("#rail").children.length : "no #rail",
    railSel: document.querySelector("#rail") ? document.querySelector("#rail").querySelectorAll("a,button,li,[data-service],.svc,.service").length : "-",
    railHTML: document.querySelector("#rail") ? document.querySelector("#rail").innerHTML.slice(0, 300) : "",
    mainLen: document.querySelector("#main") ? document.querySelector("#main").innerText.length : "no #main",
    bodyLen: document.body ? document.body.innerText.length : 0,
    banner: (document.querySelector("#nano-banner") || {}).innerText || "",
  })).catch((e) => ({ evalErr: String(e).split("\n")[0] }));
  console.log(`t+${(i + 1) * 5}s`, JSON.stringify(st).slice(0, 400));
  if (st.sw && typeof st.railSel === "number" && st.railSel > 0) { console.log("READY"); break; }
}
console.log("\npageerrors:", errs.slice(0, 8));
console.log("console.errors:", cons.slice(0, 8));
await browser.close(); server.close();
