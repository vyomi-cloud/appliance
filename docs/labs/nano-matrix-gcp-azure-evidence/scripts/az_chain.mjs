import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const fx = JSON.parse(fs.readFileSync(process.argv[2]+"/fx-azure.json","utf8"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const page = await (await browser.newContext()).newPage();
await page.goto("http://127.0.0.1:18431/nano/v4/azure/", {waitUntil:"load"}); await page.waitForTimeout(12000);
const retry = async (fn) => { for (let i=0;i<5;i++){ try { return await fn(); } catch(e){ if(!/destroyed|navigation/.test(String(e))) throw e; await page.waitForTimeout(4000);} } };
const out = await retry(() => page.evaluate(async (fx) => {
  const S="00000000-0000-0000-0000-cloudlearn01", RG="rg-facilities", log=[];
  const f = async (label, m, u, b, h, raw) => { try { const r = await Promise.race([fetch("/nano/_wire"+u,{method:m,headers:Object.assign(raw?{}:{"content-type":"application/json"},h||{}),body:b===undefined?undefined:(raw?b:JSON.stringify(b))}), new Promise((_,j)=>setTimeout(()=>j(new Error("timeout 40s")),40000))]); const t = await r.text(); log.push({label,m,u:u.slice(0,120),status:r.status,head:t.slice(0,280)}); try{return {status:r.status,j:JSON.parse(t),t}}catch(_){return {status:r.status,t}} } catch(e){ log.push({label,m,u,status:0,head:String(e)}); return {status:0,t:""}; } };
  const bin = b64 => Uint8Array.from(atob(b64), c=>c.charCodeAt(0));
  const P = `/subscriptions/${S}/resourceGroups/${RG}/providers`;
  await f("arm-rg","PUT",`/subscriptions/${S}/resourcegroups/${RG}?api-version=2025-04-01`,{location:"eastus"});
  // models + openai
  const ms = await f("openai","GET",`/subscriptions/${S}/providers/Microsoft.CognitiveServices/locations/eastus/models?api-version=2026-11-01`);
  const list = (ms.j&&ms.j.value)||[]; const names = list.map(x=>x.model&&x.model.name).filter(Boolean);
  log.push({label:"openai-models",m:"",u:"",status:0,head:JSON.stringify(names.slice(0,12))});
  await f("openai","PUT",`${P}/Microsoft.CognitiveServices/accounts/facilities-openai?api-version=2026-11-01`,{location:"eastus",kind:"OpenAI",sku:{name:"S0"},properties:{customSubDomainName:"facilities-openai"}});
  const chatM = list.find(x=>x.model&&!/embed/i.test(x.model.name)); const embM = list.find(x=>x.model&&/embed/i.test(x.model.name));
  if (chatM) await f("openai","PUT",`${P}/Microsoft.CognitiveServices/accounts/facilities-openai/deployments/chat?api-version=2026-11-01`,{sku:{name:"Standard",capacity:1},properties:{model:{format:chatM.model.format,name:chatM.model.name,version:chatM.model.version}}});
  if (embM) await f("openai","PUT",`${P}/Microsoft.CognitiveServices/accounts/facilities-openai/deployments/embed?api-version=2026-11-01`,{sku:{name:"Standard",capacity:1},properties:{model:{format:embM.model.format,name:embM.model.name,version:embM.model.version}}});
  await f("openai-chat","POST",`/openai/deployments/chat/chat/completions?api-version=2024-10-21`,{messages:[{role:"user",content:"Reply OK"}],max_tokens:20});
  await f("openai-embed","POST",`/openai/deployments/embed/embeddings?api-version=2024-10-21`,{input:["boiler pressure"]});
  await f("openai-unknown","POST",`/openai/deployments/nope/chat/completions?api-version=2024-10-21`,{messages:[{role:"user",content:"x"}]});
  // key vault data plane with SDK-era api-versions
  await f("keyvault-arm","PUT",`${P}/Microsoft.KeyVault/vaults/facilities-kv?api-version=2024-11-01`,{location:"eastus",properties:{tenantId:"00000000-0000-0000-0000-000000000000",sku:{family:"A",name:"standard"},accessPolicies:[]}});
  await f("keyvault-7.5","POST",`/keys/ledger-key/create?api-version=7.5`,{kty:"RSA",key_size:2048});
  await f("keyvault-dated","POST",`/keys/ledger-key2/create?api-version=2026-04-01`,{kty:"RSA",key_size:2048});
  // entra
  const app = await f("entra","POST",`/v1.0/applications`,{displayName:"facilities-users",identifierUris:["api://facilities-api"]});
  const aid = app.j&&app.j.id; const cid = app.j&&app.j.appId;
  const pw = aid ? await f("entra","POST",`/v1.0/applications/${aid}/addPassword`,{passwordCredential:{displayName:"x"}}) : {};
  if (cid && pw.j) await f("entra-token","POST",`/facilities-tenant/oauth2/v2.0/token`,`grant_type=client_credentials&client_id=${cid}&client_secret=${encodeURIComponent(pw.j.secretText||"")}&scope=api://facilities-api/.default`,{"content-type":"application/x-www-form-urlencoded"},true);
  // functions (v1 layout zip from the lab) on a function app
  await f("functions-arm","PUT",`${P}/Microsoft.Web/serverfarms/facilities-tools-plan?api-version=2025-05-01`,{location:"eastus",sku:{name:"Y1",tier:"Dynamic"},kind:"functionapp"});
  await f("functions-arm","PUT",`${P}/Microsoft.Web/sites/facilities-tools?api-version=2025-05-01`,{location:"eastus",kind:"functionapp,linux",properties:{serverFarmId:`${P}/Microsoft.Web/serverfarms/facilities-tools-plan`}});
  await f("functions-zip","POST",`/azure-data/functions/facilities-tools/api/zipdeploy`,bin(fx.zip),{"content-type":"application/zip"},true);
  await f("functions-list","GET",`${P}/Microsoft.Web/sites/facilities-tools/functions?api-version=2025-05-01`);
  await f("functions-call","POST",`/azure-data/functions/facilities-tools/api/asset-status`,{asset_id:"B-12"});
  // trivial v2-model function using only allowed modules
  await f("functions-trivial","POST",`/azure-data/functions/facilities-tools/api/zipdeploy`,new TextEncoder().encode("PK"),{"content-type":"application/zip"},true);
  // others
  await f("search-arm","PUT",`${P}/Microsoft.Search/searchServices/facilities-search?api-version=2024-06-01-preview`,{location:"eastus",sku:{name:"basic"}});
  await f("search-data","PUT",`/azure-data/search/facilities-search/indexes('facilities-kb')?api-version=2024-07-01`,{name:"facilities-kb",fields:[{name:"id",type:"Edm.String",key:true}]},{"api-key":"x"});
  await f("loganalytics-query","POST",`/azure-data/loganalytics/v1/workspaces/abc/query`,{query:"print 1"});
  await f("appinsights-track","POST",`/v2.1/track`,[{name:"Microsoft.ApplicationInsights.Message",time:new Date().toISOString(),iKey:"00000000-0000-0000-0000-000000000000",data:{baseType:"MessageData",baseData:{message:"hi",ver:2}}}]);
  await f("servicebus-arm","PUT",`${P}/Microsoft.ServiceBus/namespaces/facilities-bus?api-version=2024-01-01`,{location:"eastus",sku:{name:"Standard",tier:"Standard"}});
  await f("servicebus-arm","PUT",`${P}/Microsoft.ServiceBus/namespaces/facilities-bus/topics/work-order-approval?api-version=2024-01-01`,{});
  await f("frontdoor-waf","PUT",`${P}/Microsoft.Network/FrontDoorWebApplicationFirewallPolicies/facilitieswaf?api-version=2024-02-01`,{location:"global",sku:{name:"Premium_AzureFrontDoor"},properties:{policySettings:{mode:"Prevention"}}});
  await f("containerapps","PUT",`${P}/Microsoft.App/managedEnvironments/facilities-env?api-version=2025-01-01`,{location:"eastus",properties:{}});
  await f("monitor-activitylog","GET",`/subscriptions/${S}/providers/Microsoft.Insights/eventtypes/management/values?api-version=2015-04-01&$filter=eventTimestamp ge '2026-11-24T00:00:00Z'`);
  return log;
}, fx));
for (const r of out) console.log(r.label.padEnd(20), r.m, r.u.slice(0,64).padEnd(64), r.status, r.head.slice(0,150).replace(/\n/g," "));
fs.writeFileSync(process.argv[3], JSON.stringify(out,null,1));
await browser.close();
