import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const PORT = 18431, EV = process.argv[2];
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const res = {};
for (const cloud of ["gcp","azure"]) {
  const page = await (await browser.newContext()).newPage();
  await page.goto(`http://127.0.0.1:${PORT}/nano/labs/?cloud=${cloud}`, {waitUntil:"load"});
  await page.waitForTimeout(1500);
  res[cloud] = await page.evaluate(async (cloud) => {
    const course = await (await fetch("data/"+cloud+".json")).json();
    const w = new Worker("pyrun-worker.js", {type:"module"}); let seq=0, pend={};
    w.onmessage = e => { const p = pend[e.data.id]; if(!p) return; if(e.data.type==="log") p.t.push(e.data.text); else { delete pend[e.data.id]; p.r(e.data.ok); } };
    const run = (files, runcmd, env) => new Promise(r => { const id=++seq; pend[id]={t:[],r:(ok)=>r({ok,text:pend0.t.join("\n")})}; var pend0=pend[id]; pend[id].r = (ok)=>r({ok,text:pend0.t.join("\n")}); w.postMessage({id,files,run:runcmd,env}); });
    const env = { AWS_ENDPOINT_URL: location.origin+"/nano/_wire", AWS_DEFAULT_REGION:"us-east-1", AWS_ACCESS_KEY_ID:"test", AWS_SECRET_ACCESS_KEY:"test", VYOMI_ENDPOINT: location.origin+"/nano/_wire", GOOGLE_CLOUD_PROJECT:"vyomi-project", GOOGLE_CLOUD_REGION:"us-central1" };
    const files = {}; const out = [];
    for (const l of course.layers) {
      (l.lab||[]).forEach(b => files[b.file]=b.code);
      for (const b of l.lab) {
        if (!b.run) { out.push({chapter:l.order,file:b.file,run:null,status:"saved"}); continue; }
        const t0=Date.now();
        const r = await Promise.race([run(files, b.run, env), new Promise(x=>setTimeout(()=>x({ok:false,text:"TIMEOUT 90s"}),90000))]);
        out.push({chapter:l.order,file:b.file,run:b.run,rt:!!b.needs_runtime,ok:r.ok,expect:b.expect,text:r.text.slice(-700),ms:Date.now()-t0});
      }
    }
    return out;
  }, cloud);
  console.log(cloud, res[cloud].length, "records");
}
fs.writeFileSync(`${EV}/nano-worker-run-as-written.json`, JSON.stringify(res,null,1));
await browser.close();
