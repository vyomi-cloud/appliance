import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const PORT = 18431, EV = process.argv[2];
const ids = {gcp:[10,3,7,12,6,11,9,4,5,1,2,8,13], azure:[10,3,7,12,6,11,9,4,5,1,2,8,13]};
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const out = {};
for (const cloud of ["gcp","azure"]) {
  out[cloud] = [];
  const ctx = await browser.newContext(); const page = await ctx.newPage();
  const logs = []; page.on("console", m => logs.push(m.type()+": "+m.text())); page.on("pageerror", e => logs.push("pageerror: "+e.message));
  for (let i=0;i<13;i++) {
    const id = ids[cloud][i];
    await page.goto(`http://127.0.0.1:${PORT}/nano/labs/?cloud=${cloud}&layer=${id}`, {waitUntil:"load"});
    await page.waitForSelector(".vl-deploybtn", {timeout:20000});
    const btnText = await page.locator(".vl-deploybtn").first().innerText();
    await page.locator(".vl-deploybtn").first().click();
    await page.waitForTimeout(2500);
    const panel = await page.locator(".vl-deploystrip").first().innerText().catch(()=>"(no panel)");
    const res = await page.locator(".vl-dout").first().innerText().catch(()=>"");
    const chips = await page.locator(".vl-dchip").allInnerTexts();
    out[cloud].push({chapter:i+1,id,btnText,result:res,chips});
    console.log(cloud,i+1,id,JSON.stringify(res), chips.join(","));
  }
  fs.writeFileSync(`${EV}/browser-console-${cloud}.log`, logs.join("\n"));
  await ctx.close();
}
fs.writeFileSync(`${EV}/ui-deploy-nano-nomesh.json`, JSON.stringify(out,null,1));
await browser.close();
