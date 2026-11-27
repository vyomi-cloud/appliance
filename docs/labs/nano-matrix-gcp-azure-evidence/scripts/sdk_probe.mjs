import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const EV = process.argv[2];
const SETS = {
 gcp: [["google-genai","google.genai"],["google-auth","google.auth"],["google-api-core","google.api_core"],["google-cloud-aiplatform","vertexai"],["google-cloud-pubsub","google.cloud.pubsub_v1"],["google-cloud-firestore","google.cloud.firestore"],["google-cloud-storage","google.cloud.storage"],["google-cloud-kms","google.cloud.kms"],["google-cloud-logging","google.cloud.logging"],["google-cloud-monitoring","google.cloud.monitoring_v3"],["google-cloud-trace","google.cloud.trace_v2"],["google-cloud-functions","google.cloud.functions_v2"],["google-cloud-eventarc","google.cloud.eventarc_v1"],["google-cloud-api-gateway","google.cloud.apigateway_v1"],["google-cloud-compute","google.cloud.compute_v1"],["google-cloud-iam","google.cloud.iam_admin_v1"],["google-cloud-modelarmor","google.cloud.modelarmor_v1"],["google-cloud-discoveryengine","google.cloud.discoveryengine_v1"],["pyyaml","yaml"],["cryptography","cryptography.fernet"],["langgraph","langgraph.graph"],["functions-framework","functions_framework"]],
 azure: [["azure-core","azure.core"],["azure-identity","azure.identity"],["azure-mgmt-resource","azure.mgmt.resource"],["azure-mgmt-cognitiveservices","azure.mgmt.cognitiveservices"],["azure-mgmt-apimanagement","azure.mgmt.apimanagement"],["azure-mgmt-frontdoor","azure.mgmt.frontdoor"],["azure-mgmt-network","azure.mgmt.network"],["azure-mgmt-servicebus","azure.mgmt.servicebus"],["azure-mgmt-search","azure.mgmt.search"],["azure-mgmt-web","azure.mgmt.web"],["azure-mgmt-storage","azure.mgmt.storage"],["azure-mgmt-eventgrid","azure.mgmt.eventgrid"],["azure-mgmt-appcontainers","azure.mgmt.appcontainers"],["azure-mgmt-loganalytics","azure.mgmt.loganalytics"],["azure-mgmt-applicationinsights","azure.mgmt.applicationinsights"],["azure-mgmt-monitor","azure.mgmt.monitor"],["azure-mgmt-keyvault","azure.mgmt.keyvault"],["azure-ai-agents","azure.ai.agents"],["azure-ai-contentsafety","azure.ai.contentsafety"],["azure-servicebus","azure.servicebus"],["azure-data-tables","azure.data.tables"],["azure-storage-blob","azure.storage.blob"],["azure-search-documents","azure.search.documents"],["azure-keyvault-keys","azure.keyvault.keys"],["azure-monitor-opentelemetry-exporter","azure.monitor.opentelemetry.exporter"],["azure-monitor-query","azure.monitor.query"],["azure-functions","azure.functions"],["openai","openai"],["PyJWT","jwt"],["cryptography","cryptography.hazmat.primitives.ciphers.aead"],["langgraph","langgraph.graph"],["fastapi","fastapi"],["uvicorn","uvicorn"],["requests","requests"]],
};
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const res = {};
for (const cloud of ["gcp","azure"]) {
  const page = await (await browser.newContext()).newPage();
  await page.goto("http://127.0.0.1:18431/nano/labs/?cloud="+cloud, {waitUntil:"load"});
  res[cloud] = await page.evaluate(async (set) => {
    const { loadPyodide } = await import("https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.mjs");
    const py = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/" });
    await py.loadPackage(["micropip","ssl","urllib3","requests"]);
    const out = [];
    for (const [pkg, mod] of set) {
      let inst="ok", imp="ok";
      try { await py.runPythonAsync(`import micropip\nawait micropip.install(${JSON.stringify(pkg)})`); } catch(e){ inst=String(e.message).split("\n").filter(x=>x.trim()).slice(-1)[0].slice(0,220); }
      try { await py.runPythonAsync(`import importlib\nimportlib.import_module(${JSON.stringify(mod)})`); } catch(e){ imp=String(e.message).split("\n").filter(x=>x.trim()).slice(-1)[0].slice(0,220); }
      out.push({pkg,mod,install:inst,import:imp});
    }
    return out;
  }, SETS[cloud]);
  for (const r of res[cloud]) console.log(cloud, r.pkg, "| install:", r.install.slice(0,70), "| import:", r.import.slice(0,70));
}
fs.writeFileSync(`${EV}/pyodide-sdk-install-probe.json`, JSON.stringify(res,null,1));
await browser.close();
