import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const EV = process.argv[2];
const T = [["google-genai","google.genai"],["google-cloud-firestore","google.cloud.firestore"],["google-cloud-pubsub","google.cloud.pubsub_v1"],["google-cloud-aiplatform","vertexai"],["google-cloud-kms","google.cloud.kms"],["google-cloud-storage","google.cloud.storage"],["google-cloud-functions","google.cloud.functions_v2"],["langgraph","langgraph.graph"],["functions-framework","functions_framework"],["azure-keyvault-keys","azure.keyvault.keys"],["openai","openai"],["fastapi","fastapi"],["azure-monitor-opentelemetry-exporter","azure.monitor.opentelemetry.exporter"]];
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const page = await (await browser.newContext()).newPage();
await page.goto("http://127.0.0.1:18431/nano/labs/?cloud=gcp", {waitUntil:"load"});
const res = await page.evaluate(async (T) => {
  const { loadPyodide } = await import("https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.mjs");
  const py = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/" });
  await py.loadPackage("micropip"); for (const p of ["ssl","urllib3","requests","protobuf","cryptography","pydantic","httpx","typing-extensions","anyio","pyyaml","packaging","attrs","certifi","idna","sniffio"]) { try { await py.loadPackage(p); } catch(e){} }
  const out=[];
  for (const [pkg,mod] of T) {
    const steps=[]; let status="IMPORT OK";
    try { await py.runPythonAsync(`import micropip\nawait micropip.install(${JSON.stringify(pkg)}, deps=False)`); steps.push("install "+pkg+" deps=False: ok"); } catch(e){ steps.push("install failed: "+String(e.message).split("\n").slice(-2)[0].slice(0,150)); }
    for (let i=0;i<14;i++) {
      try { await py.runPythonAsync(`import importlib\nimportlib.import_module(${JSON.stringify(mod)})`); status="IMPORT OK"; break; }
      catch(e){ const m=String(e.message); const mm=m.match(/No module named '([\w\.]+)'/); const last=m.split("\n").filter(x=>x.trim()).slice(-1)[0].slice(0,160);
        if(!mm){ status="IMPORT FAIL: "+last; break; }
        const top=mm[1].split(".")[0]; if(mm[1]==="google"||mm[1]==="azure"){status="IMPORT FAIL namespace: "+last; break;} const map={google:"google-auth",proto:"proto-plus",grpc:"grpcio",googleapiclient:"google-api-python-client"}; 
        const dist = mm[1].startsWith("google.") ? ("google-"+mm[1].split(".").slice(1,3).join("-").replace(/_/g,"-")) : (map[top]||top.replace(/_/g,"-"));
        let tryd=[dist, map[top]||top.replace(/_/g,"-")];
        let ok=false; for (const d of tryd){ try{ await py.runPythonAsync(`import micropip\nawait micropip.install(${JSON.stringify(d)}, deps=False)`); steps.push("auto-installed "+d); ok=true; break;}catch(_){} }
        if(!ok){ status="BLOCKED: no pure-python wheel for module '"+mm[1]+"' (tried "+tryd.join(",")+")"; break; }
      }
    }
    out.push({pkg,mod,status,steps});
  }
  return out;
}, T);
for (const r of res) console.log(r.pkg,"=>",r.status);
fs.writeFileSync(`${EV}/pyodide-sdk-install-probe-deps-false.json`, JSON.stringify(res,null,1));
await browser.close();
