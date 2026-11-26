// generic driver: node drv.mjs  (env: PORT, MODEL, SRC=dir with files, RUNS="a.py b.py", PROF, CLEAR, OUT)
import {launch} from "./lib.mjs"; import fs from "node:fs"; import path from "node:path";
const PORT=process.env.PORT||8201, MODEL=process.env.MODEL||"", SRC=process.env.SRC, RUNS=(process.env.RUNS||"").split(/\s+/).filter(Boolean);
const prof=process.env.PROF||process.cwd()+"/prof1"; const OUT=process.env.OUT||"";
const ctx=await launch(prof);
if(process.env.HF_VIA_NODE){ await ctx.route(/huggingface\.co\/mlc-ai\/.*\/resolve\//,async route=>{ try{ const r=await route.fetch({maxRedirects:10,timeout:600000}); await route.fulfill({response:r,headers:{...r.headers(),"access-control-allow-origin":"*"}}); }catch(e){ await route.abort(); } }); }
const A=await ctx.newPage(); A.on("console",m=>{const t=m.text(); if(process.env.CONSOLE&&/error|fail|warn/i.test(t)) console.log("[console]",t.slice(0,300));});
if(process.env.CLEAR){ await A.goto(`http://127.0.0.1:${PORT}/nano/labs/`);
  await A.evaluate(async()=>{ for(const d of (await indexedDB.databases())){ await new Promise(res=>{const q=indexedDB.deleteDatabase(d.name); q.onsuccess=q.onerror=q.onblocked=()=>res();}); } try{ const root=await navigator.storage.getDirectory(); for await (const [n] of root.entries()){ await root.removeEntry(n,{recursive:true}); } }catch(e){} try{localStorage.clear();sessionStorage.clear();}catch(e){} const rs=await navigator.serviceWorker.getRegistrations(); for(const x of rs) await x.unregister(); }); }
await A.goto(`http://127.0.0.1:${PORT}/nano/v4/aws/`); await A.waitForFunction(()=>typeof globalThis.vyomiLlmStatus==="function",null,{timeout:180000}); await A.waitForTimeout(3000);
if(MODEL){ const r=await A.evaluate(async(m)=>{ const t0=performance.now(); try{ const id=await globalThis.vyomiEnableWebLLM(m,(p)=>{globalThis.__lp=p.text||""}); return {ok:true,id,ms:Math.round(performance.now()-t0)}; }catch(e){ return {ok:false,err:String(e).slice(0,400)}; } },MODEL); console.log("model:",JSON.stringify(r)); if(!r.ok) process.exit(2); }
const P=await ctx.newPage(); await P.goto(`http://127.0.0.1:${PORT}/nano/labs/`); await P.waitForTimeout(3000);
await P.evaluate(()=>{ window.__seq=0; window.__pend={}; window.__w=new Worker("pyrun-worker.js",{type:"module"});
  window.__w.onmessage=e=>{const q=window.__pend[e.data.id]; if(!q)return; if(e.data.type==="log") q.text+=e.data.text+"\n"; else {q.ok=e.data.ok; delete window.__pend[e.data.id]; q.res(q);} };
  window.__run=(files,run,env,ms)=>new Promise(res=>{const id=++window.__seq; const t=setTimeout(()=>{delete window.__pend[id];res({ok:false,text:(window.__pend[id]?.text||"")+"\n[TIMEOUT]"});},ms); const q={text:"",res:(x)=>{clearTimeout(t);res({ok:x.ok,text:x.text});}}; window.__pend[id]=q; window.__w.postMessage({id,files,run,env,route:null}); }); });
const env={AWS_ENDPOINT_URL:`http://127.0.0.1:${PORT}/nano/_wire`,AWS_DEFAULT_REGION:"us-east-1",AWS_ACCESS_KEY_ID:"test",AWS_SECRET_ACCESS_KEY:"test",...JSON.parse(process.env.EXTRA_ENV||"{}")};
const files={}; for(const f of fs.readdirSync(SRC)){ const fp=path.join(SRC,f); if(fs.statSync(fp).isFile()) files[f]=fs.readFileSync(fp,"utf8"); }
let outAll=""; for(const r of RUNS){ const t0=Date.now(); const res=await P.evaluate(([f,run,e])=>window.__run(f,run,e,Number(globalThis.__to||1500000)),[files,"python "+r,env]); const line=`=== ${r} ok=${res.ok} ${Date.now()-t0}ms\n${res.text}`; console.log(line); outAll+=line+"\n"; }
if(OUT) fs.writeFileSync(OUT,outAll);
setTimeout(()=>process.exit(0),4000); await ctx.close().catch(()=>{}); process.exit(0);
