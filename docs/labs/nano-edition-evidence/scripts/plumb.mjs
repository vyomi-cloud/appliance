import {launch,SP} from "./lib.mjs"; import fs from "node:fs";
const EV=SP+"/ev/out";
const MODEL=process.env.MODEL||""; const prof=process.env.PROF||SP+"/m/prof-plumb"; const out=process.env.OUT||EV+"/nano-plumbing-nomodel.jsonl";
const only=(process.env.CH||"").split(",").filter(Boolean).map(Number);
fs.writeFileSync(out,"");
const ctx=await launch(prof); const p=await ctx.newPage();
const A=p; A.on("console",m=>{const t=m.text(); if(/error|fail/i.test(t)&&!/Failed to load resource/.test(t)) fs.appendFileSync(out+".console",t.slice(0,300)+"\n");});
await A.goto("http://localhost:8931/nano/v4/aws/"); await A.waitForFunction(()=>typeof globalThis.vyomiLlmStatus==="function",null,{timeout:120000}); await A.waitForTimeout(3000);
console.log("kernel up, llm:",JSON.stringify(await A.evaluate(()=>globalThis.vyomiLlmStatus())));
if(MODEL&&process.env.PREWARM){ const pw=await A.evaluate(async(mlc)=>{ const base="https://huggingface.co/mlc-ai/"+mlc+"/resolve/main/"; const c=await caches.open("webllm/model"); const t0=performance.now(); const cfg=await (await fetch(base+"ndarray-cache.json")).json(); let n=0; for(const rec of cfg.records){ const u=base+rec.dataPath; if(await c.match(u)) continue; let ok=false; for(let k=0;k<3&&!ok;k++){ try{ const r=await fetch(u); if(r.ok){ await c.put(u,r); ok=true; n++; } }catch(e){ await new Promise(r=>setTimeout(r,2000)); } } if(!ok) return {ok:false,u,n}; } return {ok:true,shards:n,ms:Math.round(performance.now()-t0)}; },process.env.PREWARM); fs.writeFileSync(out+".prewarm.json",JSON.stringify(pw)); console.log("prewarm",JSON.stringify(pw)); }
if(MODEL){ const t0=Date.now(); let last=""; const r=await A.evaluate(async(m)=>{ const t0=performance.now(); try{ const id=await globalThis.vyomiEnableWebLLM(m,(p)=>{globalThis.__lp=p.text||""}); return {ok:true,id,ms:Math.round(performance.now()-t0),status:globalThis.vyomiLlmStatus()}; }catch(e){ return {ok:false,err:String(e).slice(0,400),ms:Math.round(performance.now()-t0)}; } },MODEL); fs.writeFileSync(out+".model.json",JSON.stringify(r,null,1)); console.log("model load:",JSON.stringify(r).slice(0,300)); if(!r.ok) process.exit(2); }
const p2=await ctx.newPage(); await p2.goto("http://localhost:8931/nano/labs/"); await p2.waitForTimeout(3000);
globalThis.PG=p2;
await p2.evaluate(()=>{ window.__seq=0; window.__pend={};
  window.__w=new Worker("pyrun-worker.js",{type:"module"});
  window.__w.onmessage=e=>{const q=window.__pend[e.data.id]; if(!q)return; if(e.data.type==="log") q.text+=e.data.text+"\n"; else {delete window.__pend[e.data.id]; q.res(q);} };
  window.__w.onerror=e=>{ for(const k in window.__pend){window.__pend[k].text+="Runner error: "+e.message; window.__pend[k].res(window.__pend[k]);} };
  window.__run=(files,run,env,ms)=>new Promise(res=>{const id=++window.__seq; const q={text:"",res:(x)=>{clearTimeout(t);res({ok:x.ok,text:x.text});}}; window.__pend[id]=q; const t=setTimeout(()=>{delete window.__pend[id];res({ok:false,text:q.text+"\n[TIMEOUT "+ms+"ms]",timeout:true});},ms); const orig=window.__w.onmessage; window.__w.postMessage({id,files,run,env,route:null}); const h=window.__w.onmessage; window.__w.onmessage=e=>{ if(e.data.id===id&&e.data.type==="done") q.ok=e.data.ok; h(e); }; });
});
const course=await p2.evaluate(()=>fetch("data/aws.json").then(r=>r.json()));
const env={...JSON.parse(process.env.EXTRA_ENV||"{}"),AWS_ENDPOINT_URL:"http://localhost:8931/nano/_wire",AWS_DEFAULT_REGION:"us-east-1",AWS_ACCESS_KEY_ID:"test",AWS_SECRET_ACCESS_KEY:"test"};
const files={};
for(const l of course.layers){
  for(const b of l.lab||[]) files[b.file]=b.code;  // all files exist for every chapter (superset; harmless)
}
// Faithful: only files up to this chapter. Rebuild per chapter:
const acc={};
const PRE=process.env.PRELUDE?fs.readFileSync(process.env.PRELUDE,'utf8')+'\n':'';
for(const l of course.layers){
  for(const b of l.lab||[]) acc[b.file]=(b.file.endsWith('.py')&&b.run?PRE:'')+(process.env.PATCH_ZIP&&b.file==='deploy_runtime.py'?b.code.replace('z.write("agents.py", "agents.py")','z.write("agents.py", "agents.py"); z.write("models.py", "models.py")'):b.code);
  if(only.length && !only.includes(l.order)) continue;
  for(const [i,b] of (l.lab||[]).entries()){
    const rec={chapter:l.order,layer:l.id,i:i+1,file:b.file,run:b.run,needs_runtime:!!b.needs_runtime,expect:b.expect||""};
    const t0=Date.now();
    if(!b.run){ await p2.evaluate(([f,e])=>window.__run(f,"",e,60000),[acc,env]); rec.status="SAVED"; }
    else{
      const r=await p2.evaluate(([f,run,e])=>window.__run(f,run,e,600000),[acc,b.run,env]);
      rec.text=r.text.slice(-3000); rec.ok=r.ok; rec.timeout=!!r.timeout;
      rec.matched=!b.expect||r.text.includes(b.expect);
      rec.status=(r.ok&&rec.matched)?"PASS":"FAIL";
    }
    rec.ms=Date.now()-t0; fs.appendFileSync(out,JSON.stringify(rec)+"\n");
    console.log(rec.chapter,rec.file,rec.status,rec.ms+"ms",(rec.text||"").trim().split("\n").slice(-1)[0]?.slice(0,140));
  }
}
if(process.env.PROBE){ const code=fs.readFileSync(process.env.PROBE,'utf8'); const f={...acc,"probe.py":PRE+code}; const t0=Date.now(); const r=await p2.evaluate(([f,e])=>window.__run(f,"python probe.py",e,900000),[f,env]); fs.writeFileSync(out+".probe.txt",r.text); console.log("probe done",Date.now()-t0,"ms"); }
await ctx.close();
