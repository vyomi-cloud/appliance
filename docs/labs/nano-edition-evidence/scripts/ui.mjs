import {launch,SP} from "./lib.mjs"; import fs from "node:fs";
const PORT=process.env.PORT||8931, MODEL=process.env.MODEL||"", NOGPU=process.env.NOGPU;
const prof=process.env.PROF||SP+"/profui"; const out=process.env.OUT||SP+"/ev/out/ui-all.json";
const ctx=await launch(prof); const A=await ctx.newPage();
if(NOGPU) await A.addInitScript(()=>{ try{ Object.defineProperty(navigator,"gpu",{get:()=>undefined,configurable:true}); delete Navigator.prototype.gpu; }catch(e){} });
await A.goto(`http://localhost:${PORT}/nano/v4/aws/`); await A.waitForFunction(()=>typeof globalThis.vyomiLlmStatus==="function",null,{timeout:120000}); await A.waitForTimeout(3000);

const LAYERS=(process.env.LAYERS||"10").split(","); const all={};
for(const LAYER of LAYERS){
await A.evaluate((L)=>{ document.getElementById("labsfr")?.remove(); const f=document.createElement("iframe"); f.id="labsfr"; f.style.cssText="position:fixed;inset:0;width:100vw;height:100vh;z-index:99999;background:#fff;border:0"; f.src=`/nano/labs/index.html?embed=1&cloud=aws&layer=${L}`; document.body.append(f); },LAYER);
await A.waitForTimeout(2500);
const fr=A.frames().find(x=>x.url().includes("/labs/"));
await fr.waitForSelector(".vl-deploybtn",{timeout:60000});
await fr.evaluate(()=>document.querySelector(".vl-deploybtn").click());
const res={layer:LAYER,events:[]}; const t0=Date.now(); let pickerSeen=false; let n=0;
while(Date.now()-t0<1500000){
  await A.waitForTimeout(2000);
  const st=await fr.evaluate(()=>({btn:document.querySelector(".vl-deploybtn").textContent, dis:document.querySelector(".vl-deploybtn").disabled, picker:!!document.querySelector(".vl-modelpick"), pickText:(document.querySelector(".vl-modelpick")||{}).innerText||"", btns:[...document.querySelectorAll(".vl-modelpick button")].map(b=>b.innerText.replace(/\n/g," ")+(b.disabled?" [disabled]":""))}));
  if(st.picker && !pickerSeen){ pickerSeen=true; res.pickerText=st.pickText; res.pickerButtons=st.btns; await A.screenshot({path:`${SP}/ev/out/ui-${LAYER}-picker.png`});
    if(MODEL){ await fr.evaluate((m)=>{ const b=[...document.querySelectorAll(".vl-modelpick button")].find(x=>x.innerText.includes(m)); b&&b.click(); },MODEL); res.events.push("picked "+MODEL); }
    else { await fr.evaluate(()=>{ const b=[...document.querySelectorAll(".vl-modelpick button")].find(x=>/Skip/.test(x.innerText)); b&&b.click(); }); res.events.push("skipped"); } }
  if(!st.dis && /Deploy again/.test(st.btn)) break;
}
res.ms=Date.now()-t0;
res.rows=await fr.evaluate(()=>[...document.querySelectorAll(".vl-drow")].map(r=>r.innerText.replace(/\n/g," | ")));
res.logs=await fr.evaluate(()=>[...document.querySelectorAll(".vl-dlog")].map(r=>r.innerText.slice(-700)));
res.summary=await fr.evaluate(()=>(document.querySelector(".vl-dres")||{}).innerText||"");
await A.screenshot({path:`${SP}/ev/out/ui-${LAYER}.png`}); all[LAYER]=res; console.log(LAYER,res.summary.replace(/\n/g," / ").slice(0,300));
fs.writeFileSync(out,JSON.stringify(all,null,1));
}
await ctx.close();
