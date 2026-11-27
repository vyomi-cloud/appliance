import {launch,SP} from "./lib.mjs"; import fs from "node:fs";
const EV="/Users/sudhirganti/Applications/simulator/appliance-labsmx-aws/docs/labs/nano-matrix-aws-evidence";
const ctx=await launch(SP+"/m/prof-ui"); const A=await ctx.newPage();
await A.goto("http://localhost:8913/nano/v4/aws/"); await A.waitForFunction(()=>typeof globalThis.vyomiLlmStatus==="function",null,{timeout:120000}); await A.waitForTimeout(3000);
const p=await ctx.newPage(); await p.goto("http://localhost:8913/nano/labs/"); await p.waitForTimeout(2500);
const out=[];
for(const n of [1,2,3,10]){
  await p.goto("http://localhost:8913/nano/labs/"); await p.waitForTimeout(1500);
  await p.getByRole("button",{name:/Start course/i}).click(); await p.waitForTimeout(1000);
  await p.locator(".vl-tile",{hasText:"Chapter "+String(n).padStart(2,"0")}).first().click(); await p.waitForTimeout(1000);
  const btn=p.locator(".vl-deploybtn").first(); await btn.scrollIntoViewIfNeeded(); await btn.click();
  const t0=Date.now(); let txt="";
  while(Date.now()-t0<150000){ await p.waitForTimeout(3000); txt=await p.locator(".vl-dres").first().innerText().catch(()=>""); const chips=await p.locator(".vl-dchip").allInnerTexts(); if(txt && !/Starting|continues inside/.test(txt)) {break;} if(await p.locator(".vl-dstatus").count()){} }
  const chips=await p.locator(".vl-dchip").allInnerTexts(); const rows=await p.locator(".vl-dt").allInnerTexts();
  await p.screenshot({path:EV+`/ui-deploy-ch${n}.png`,fullPage:false});
  out.push({chapter:n,result:txt,chips,rows,panelHead:await p.locator(".vl-dhead p").first().innerText().catch(()=>"")}); console.log(JSON.stringify(out.at(-1)));
}
fs.writeFileSync(EV+"/ui-deploy-nomesh.json",JSON.stringify(out,null,1)); await ctx.close();
