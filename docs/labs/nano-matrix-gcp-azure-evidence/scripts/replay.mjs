import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const [cloud, inFile, outFile] = process.argv.slice(2);
const recs = fs.readFileSync(inFile,"utf8").trim().split("\n").map(JSON.parse);
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const page = await (await browser.newContext()).newPage();
await page.goto(`http://127.0.0.1:18431/nano/v4/${cloud}/`, {waitUntil:"load"});
await page.waitForTimeout(9000);
const retry = async (fn) => { for (let i=0;i<6;i++) { try { return await fn(); } catch(e) { if (!/context was destroyed|navigation/.test(String(e))) throw e; await page.waitForTimeout(4000); } } return {status:0, head:'page kept navigating'}; };
const out = []; const MAP = new Map();
const NAMES = (t)=>[...String(t).matchAll(/"(?:name|id|operationId)"\s*:\s*"([^"]+)"/g)].map(m=>m[1].split("/").pop());
for (const r of recs) {
  const u = new URL(r.url);
  const isArm = u.pathname.startsWith("/subscriptions/") && cloud==="azure";
  const target = isArm ? "/nano"+u.pathname+u.search : "/nano/_wire"+u.pathname+u.search;
  let t2 = target, b64x = r.body_b64; { let bt = atob(b64x); let changed=false; for (const [k,v] of MAP) { if (t2.includes(k)) t2 = t2.split(k).join(v); if (bt.includes(k)) { bt = bt.split(k).join(v); changed=true; } } if (changed) b64x = Buffer.from(bt,"binary").toString("base64"); }
  const res = await retry(() => page.evaluate(async ([t, method, headers, b64]) => {
    try {
      const bin = atob(b64); const body = bin.length ? Uint8Array.from(bin, c=>c.charCodeAt(0)) : undefined;
      const h = {}; for (const [k,v] of Object.entries(headers||{})) if(k.toLowerCase()!=="content-length") h[k]=v;
      const x = await Promise.race([fetch(t,{method, headers:h, body: ["GET","HEAD"].includes(method)?undefined:body}), new Promise((_,j)=>setTimeout(()=>j(new Error("timeout 30s")),30000))]);
      const txt = await x.text(); return {status:x.status, head:txt.slice(0,700)};
    } catch(e){ return {status:0, head:String(e)}; }
  }, [t2, r.method, r.headers, b64x]));
  { const a = NAMES(r.rhead), b = NAMES(res.head); for (let i=0;i<Math.min(a.length,b.length);i++) if (a[i]!==b[i] && a[i].length>=6) MAP.set(a[i], b[i]); }
  out.push({tag:r.tag, method:r.method, path:u.pathname+u.search, ref_status:r.status, nano_status:res.status, nano_head:res.head, ref_head:r.rhead});
}
fs.writeFileSync(outFile, JSON.stringify(out,null,1));
console.log("replayed", out.length);
await browser.close();
