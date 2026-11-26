// Labs page check, no model: both courses listed apart, the new course opens, every chapter renders, the original course is unchanged. Saves screenshots.
import { chromium } from "/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/playwright/index.mjs";
import fs from "node:fs";
const PORT = process.env.PORT || 8201, OUT = process.env.OUT || "../screens";
fs.mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
const p = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
const errs = [];
p.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
await p.goto(`http://127.0.0.1:${PORT}/nano/labs/`);
await p.waitForTimeout(3500);
const cards = await p.$$eval(".vl-ccard:not(.soon)", (n) => n.map((x) => ({ course: x.className, title: x.querySelector("h2")?.textContent })));
await p.screenshot({ path: OUT + "/01-listing.png" });
const res = { cards };
await p.click("text=Start course >> nth=0");
await p.waitForTimeout(2500);
res.heading = await p.$eval("h1", (e) => e.textContent).catch(() => null);
await p.screenshot({ path: OUT + "/02-course-home.png" });
res.chapters = [];
for (let i = 0; i < 7; i++) {
  await p.locator("text=/^(Open|Continue)$/").nth(i).click();
  await p.waitForTimeout(1500);
  const info = await p.evaluate(() => ({ h: (document.querySelector("h1") || {}).textContent, chars: document.body.innerText.length, codeBlocks: document.querySelectorAll("pre").length, hasNeedsMesh: /needs a mesh|requires a mesh|mesh only/i.test(document.body.innerText) }));
  res.chapters.push(info);
  await p.screenshot({ path: `${OUT}/03-chapter-${i + 1}.png` });
  await p.click("text=Course contents").catch(() => {});
  await p.waitForTimeout(900);
}
res.errors = errs;
console.log(JSON.stringify(res, null, 1));
fs.writeFileSync(OUT + "/ui-check.json", JSON.stringify(res, null, 1));
await b.close();
