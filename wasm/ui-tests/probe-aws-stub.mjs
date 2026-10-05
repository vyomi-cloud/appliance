import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const LABEL = process.env.STUB || "Volumes";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const net = [];
page.on("response", (r) => { const u = r.url(); if (u.includes("/api/")) net.push(`${r.status()} ${r.request().method()} ${u.replace(base, "")}`); });
try {
  await bootConsole(page, base, "/aws-console.html");
  // open EC2 (expands sub-nav into the rail)
  await page.evaluate((sel) => { const e = [...document.querySelectorAll(sel)].find((x) => /ec2/i.test((x.innerText || "") + (x.getAttribute("data-service") || ""))); e && e.click(); }, RAIL_SEL);
  await sleep(1200);
  const clicked = await page.evaluate(([sel, lbl]) => { const e = [...document.querySelectorAll(sel)].find((x) => (x.innerText || "").includes(lbl)); if (e) { e.click(); return true; } return false; }, [RAIL_SEL, LABEL]);
  await sleep(1800);
  const m = await page.evaluate(() => {
    const el = document.querySelector("#main");
    return { text: (el.innerText || "").replace(/\n/g, " ⏎ ").slice(0, 260),
      createBtns: [...el.querySelectorAll("button")].map((b) => b.innerText.trim().replace(/\n/g, " ")).filter(Boolean) };
  });
  console.log("clicked:", clicked);
  console.log("#main:", JSON.stringify(m, null, 1));
  // click Create + dump the form/blade
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button, #bladeBody button, dialog button")].find((x) => /create/i.test(x.innerText)); b && b.click(); });
  await sleep(1000);
  const form = await page.evaluate(() => {
    const scopes = ["#bladeBody", "dialog", "[role=dialog]", ".modal", "#main"];
    for (const s of scopes) { const d = document.querySelector(s); if (d && d.querySelector("input,select")) return { scope: s, inputs: [...d.querySelectorAll("input,select,textarea")].map((i) => i.placeholder || i.name || i.id || i.type), buttons: [...d.querySelectorAll("button")].map((b) => b.innerText.trim()).filter(Boolean).slice(0, 6) }; }
    return { scope: "none" };
  });
  console.log("CREATE form:", JSON.stringify(form, null, 1));
} catch (e) { console.log("ERR", String(e).split("\n")[0]); }
console.log("\n/api net:", net.slice(0, 12));
await browser.close(); server.close();
