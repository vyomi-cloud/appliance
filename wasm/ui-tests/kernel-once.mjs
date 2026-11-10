// Regression: the Nano boot screen ("nano kernel") shows once per launch — the first
// Nano page — and never again on space clicks, consoles, reloads or new tabs while
// Nano stays open. Serve wasm/ on :8731 first:  (cd wasm && python3 -m http.server 8731)
//   node wasm/ui-tests/kernel-once.mjs
import { chromium } from "playwright";
const B = process.env.NANO_URL || "http://localhost:8731";
const b = await chromium.launch({ args: ["--disable-blink-features=AutomationControlled"] });
const shown = async (p, url) => { await p.goto(B + url, { waitUntil: "domcontentloaded" }); await p.waitForTimeout(400); return await p.evaluate(() => !!document.getElementById("nano-kernel")); };
const ctx = await b.newContext(); const p = await ctx.newPage();
const r = {};
r["1 first launch: dashboard"] = await shown(p, "/clouds.html");
r["2 space click: AWS console"] = await shown(p, "/aws-console.html");
r["3 back to dashboard"] = await shown(p, "/clouds.html");
r["4 GCP console"] = await shown(p, "/gcp-console.html");
r["5 reload"] = await shown(p, "/gcp-console.html");
const p2 = await ctx.newPage(); r["6 new tab, Nano still open"] = await shown(p2, "/azure-console.html");
await p.evaluate(() => { sessionStorage.setItem("nano-kernel-log", JSON.stringify({at: Date.now(), elapsed: 500, lines: []})); });
r["7 first boot's SW reload (carried)"] = await shown(p, "/clouds.html");
await p2.close(); await p.close();
const p3 = await ctx.newPage(); await p3.evaluate(() => 0);
await new Promise((res) => setTimeout(res, 11000));      // Nano closed > 10 s = a new launch
r["8 Nano closed, reopened 11s later"] = await shown(p3, "/clouds.html");
const ctx2 = await b.newContext(); r["9 fresh browser profile"] = await shown(await ctx2.newPage(), "/clouds.html");
const want = { "1": true, "2": false, "3": false, "4": false, "5": false, "6": false, "7": true, "8": true, "9": true };
let bad = 0; for (const [k, v] of Object.entries(r)) { const ok = v === want[k[0]]; bad += !ok; console.log(`${ok ? "PASS" : "FAIL"}  ${k}: boot screen ${v ? "shown" : "skipped"}`); }
await b.close(); process.exit(bad ? 1 : 0);
