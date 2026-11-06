/* "Share feedback" floating button on all three v4 consoles (Nano preview): button visible, text + Submit, POST body, queue when unreachable.
 *   PW=<playwright path> node consoles/tests/feedback-smoke.mjs   (starts consoles/nano_preview.mjs on PORT=8795)   Exit 1 on any FAIL. */
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url); const pw = require(process.env.PW || "playwright");
const here = dirname(fileURLToPath(import.meta.url)); const PORT = Number(process.env.PORT || 8795);
const NANO = `http://127.0.0.1:${PORT}/nano`;
let bad = 0; const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${ok || !d ? "" : " - " + String(d).slice(0, 160)}`); };
const preview = spawn("node", [join(here, "..", "nano_preview.mjs"), "--port", String(PORT)], { stdio: "ignore" });
for (let i = 0; i < 40; i++) { try { if ((await fetch(`${NANO}/`, { redirect: "manual" })).status < 500) break; } catch {} await new Promise((r) => setTimeout(r, 250)); }
const browser = await pw.chromium.launch();
try {
  for (const cloud of ["aws", "gcp", "azure"]) {
    const ctx = await browser.newContext(); const page = await ctx.newPage(); const errors = []; page.on("pageerror", (e) => errors.push(e.message));
    let got = null; let mode = "ok";
    await page.route("**/api/feedback", async (route) => { if (mode === "ok") { got = JSON.parse(route.request().postData() || "{}"); await route.fulfill({ status: 200, body: '{"ok":true}', contentType: "application/json" }); } else await route.fulfill({ status: 404, body: "no" }); });
    await page.goto(`${NANO}/v4/${cloud}/`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".vyfb-btn", { timeout: 60000 });
    check(`${cloud}: floating Share feedback button visible`, await page.isVisible(".vyfb-btn"));
    check(`${cloud}: popup hidden until clicked`, !(await page.isVisible(".vyfb-pop")));
    await page.click(".vyfb-btn");
    check(`${cloud}: text field + Submit shown, Submit disabled while empty`, (await page.isVisible(".vyfb-ta")) && (await page.isDisabled(".vyfb-send")));
    await page.fill(".vyfb-ta", `great ${cloud} console`);
    check(`${cloud}: Submit enables with text`, !(await page.isDisabled(".vyfb-send")));
    await page.click(".vyfb-send"); await page.waitForFunction(() => /sent/i.test(document.querySelector(".vyfb-msg").textContent), null, { timeout: 5000 }).catch(() => {});
    check(`${cloud}: POST body has text + cloud + substrate`, got && got.text === `great ${cloud} console` && got.cloud === cloud && got.substrate === "nano", JSON.stringify(got));
    await page.waitForSelector(".vyfb-pop", { state: "hidden", timeout: 5000 }).catch(() => {});
    mode = "down"; await page.click(".vyfb-btn"); await page.fill(".vyfb-ta", "offline note"); await page.click(".vyfb-send");
    await page.waitForFunction(() => /saved/i.test(document.querySelector(".vyfb-msg").textContent), null, { timeout: 5000 }).catch(() => {});
    const q = await page.evaluate(() => JSON.parse(localStorage.getItem("vyomi.feedback.queue") || "[]"));
    check(`${cloud}: unreachable endpoint queues the note locally`, q.length === 1 && q[0].text === "offline note", JSON.stringify(q));
    check(`${cloud}: no page errors`, errors.length === 0, errors.join(" | "));
    await ctx.close();
  }
} catch (e) { bad++; console.log("FAIL harness - " + (e && e.stack || e)); }
finally { await browser.close(); preview.kill(); }
console.log(bad ? `${bad} FAILED` : "ALL PASS"); process.exit(bad ? 1 : 0);
