import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/aws-console.html");
  // open S3
  await page.evaluate((sel) => { const e = [...document.querySelectorAll(sel)].find((x) => /storage|s3/i.test((x.innerText || "") + (x.getAttribute("data-service") || ""))); e && e.click(); }, RAIL_SEL);
  await sleep(1500);
  // click Create bucket
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /create/i.test(x.innerText)); b && b.click(); });
  await sleep(1000);
  const dump = await page.evaluate(() => {
    const scopes = ["dialog", "[role=dialog]", ".modal", ".drawer", ".sheet", ".panel", "#bladeBody", "form", "[class*=modal]", "[class*=dialog]", "[class*=create]"];
    let d = null, which = "none";
    for (const s of scopes) { const c = document.querySelector(s); if (c && c.querySelector("input,select,textarea")) { d = c; which = s; break; } }
    if (!d) d = document.querySelector("#main");
    return {
      scope: which,
      inputs: [...d.querySelectorAll("input,select,textarea")].map((i) => ({ tag: i.tagName, type: i.type || "", ph: i.placeholder || "", name: i.name || i.id || "", vis: i.offsetParent !== null })),
      buttons: [...d.querySelectorAll("button")].map((b) => b.innerText.trim().replace(/\n/g, " ")).filter(Boolean).slice(0, 10),
      sampleHTML: d.innerHTML.slice(0, 300),
    };
  });
  console.log(JSON.stringify(dump, null, 1));
} catch (e) { console.log("ERR", String(e).split("\n")[0]); }
await browser.close(); server.close();
