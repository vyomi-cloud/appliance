import { createRequire } from "node:module";
const require = createRequire("/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/");
const { chromium } = require("playwright");
import fs from "node:fs";
const fx = JSON.parse(fs.readFileSync(process.argv[2]+"/fixtures.json","utf8"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN, headless: true });
const page = await (await browser.newContext()).newPage();
await page.goto("http://127.0.0.1:18431/nano/v4/gcp/", {waitUntil:"load"}); await page.waitForTimeout(9000);
const out = await page.evaluate(async (fx) => {
  const P="vyomi-project", L="us-central1", log=[];
  const f = async (label, m, u, b, h, raw) => { try { const r = await fetch("/nano/_wire"+u,{method:m,headers:Object.assign(raw?{}:{"content-type":"application/json"},h||{}),body:b===undefined?undefined:(raw?b:JSON.stringify(b))}); const t = await r.text(); log.push({label,m,u:u.slice(0,110),status:r.status,head:t.slice(0,260)}); try{return {status:r.status,j:JSON.parse(t),t}}catch(_){return {status:r.status,t}} } catch(e){ log.push({label,m,u,status:0,head:String(e)}); return {status:0,t:""}; } };
  const bin = b64 => Uint8Array.from(atob(b64), c=>c.charCodeAt(0));
  // A. GCS + RAG
  await f("gcs","POST",`/storage/v1/b?project=${P}`,{name:"facilities-docs"});
  await f("gcs","POST",`/upload/storage/v1/b/facilities-docs/o?uploadType=media&name=docs%2Fboiler-sop.md`,"# Boiler SOP\nCheck pressure daily. Relief valve test monthly.",{"content-type":"text/markdown"},true);
  await f("gcs","GET",`/storage/v1/b/facilities-docs/o?prefix=docs/`);
  const corp = await f("rag","POST",`/v1/projects/${P}/locations/${L}/ragCorpora`,{displayName:"facilities-kb"});
  const cname = (corp.j&&corp.j.name||"").split("/operations")[0];
  await f("rag","POST",`/v1/${cname}/ragFiles:import`,{importRagFilesConfig:{gcsSource:{uris:["gs://facilities-docs/docs/"]}}});
  await f("rag","GET",`/v1/${cname}/ragFiles`);
  await f("rag","POST",`/v1/projects/${P}/locations/${L}:retrieveContexts`,{vertexRagStore:{ragResources:[{ragCorpus:cname}]},query:{text:"boiler pressure check",ragRetrievalConfig:{topK:3}}});
  // B. Functions
  const up = await f("functions","POST",`/v2/projects/${P}/locations/${L}/functions:generateUploadUrl`,{});
  const url = new URL((up.j&&up.j.uploadUrl)||"http://x/"); const so=up.j&&up.j.storageSource||{};
  await f("functions","PUT",url.pathname+url.search, bin(fx.zip),{"content-type":"application/zip"},true);
  const fn = await f("functions","POST",`/v2/projects/${P}/locations/${L}/functions?functionId=facilities-asset-status`,{name:`projects/${P}/locations/${L}/functions/facilities-asset-status`,buildConfig:{runtime:"python312",entryPoint:"handler",source:{storageSource:{bucket:so.bucket,object:so.object,generation:so.generation||"1"}}},serviceConfig:{timeoutSeconds:120,environmentVariables:{GOOGLE_CLOUD_PROJECT:P}}});
  await f("functions","GET",`/v2/projects/${P}/locations/${L}/functions/facilities-asset-status`);
  await f("functions","POST",`/gcf/${P}/${L}/facilities-asset-status`,{asset_id:"B-12"});
  // C. API gateway (exact doc from the lab)
  await f("apigw","POST",`/v1/projects/${P}/locations/global/apis?apiId=facilities-api`,{displayName:"facilities-api"});
  await f("apigw","POST",`/v1/projects/${P}/locations/global/apis/facilities-api/configs?apiConfigId=cfg1`, JSON.parse(atob(fx.apicfg)));
  const ym = "info:\n  title: t\n  version: 1.0.0\npaths:\n  /search:\n    post:\n      operationId: search\n      responses:\n        '200':\n          description: ok\n      x-google-backend:\n        address: https://x.example.com/f\nswagger: '2.0'\n";
  await f("apigw-minimal","POST",`/v1/projects/${P}/locations/global/apis/facilities-api/configs?apiConfigId=cfg2`,{displayName:"cfg2",openapiDocuments:[{document:{path:"openapi.yaml",contents:btoa(ym)}}]});
  // D. identity / IAM
  await f("identity","POST",`/v1/accounts:signUp`,{email:"a@b.co",password:"pw123456",returnSecureToken:true});
  await f("iam","POST",`/v1/projects/${P}/serviceAccounts`,{accountId:"agent-sa",serviceAccount:{displayName:"agent"}});
  await f("iam","POST",`/v1/projects/-/serviceAccounts/agent-sa%40${P}.iam.gserviceaccount.com:generateIdToken`,{audience:"https://x"});
  // E. agent gateway
  await f("agentgw","POST",`/v1/projects/${P}/locations/${L}/agentGateways?agentGatewayId=facilities-gateway`,{displayName:"Facilities gateway",authorization:{type:"NONE"}});
  const g = await f("agentgw","GET",`/v1/projects/${P}/locations/${L}/agentGateways/facilities-gateway`);
  // F. REST equivalents of the gRPC-only paths (what a REST-transport rewrite would hit)
  await f("pubsub","PUT",`/v1/projects/${P}/topics/t1`,{});
  await f("pubsub","POST",`/v1/projects/${P}/topics/t1:publish`,{messages:[{data:btoa("hi")}]});
  await f("pubsub","PUT",`/v1/projects/${P}/subscriptions/s1`,{topic:`projects/${P}/topics/t1`});
  await f("pubsub","POST",`/v1/projects/${P}/subscriptions/s1:pull`,{maxMessages:5});
  await f("firestore","PATCH",`/v1/projects/${P}/databases/(default)/documents/assets/B-12`,{fields:{status:{stringValue:"RUNNING"}}});
  await f("firestore","GET",`/v1/projects/${P}/databases/(default)/documents/assets/B-12`);
  await f("kms","POST",`/v1/projects/${P}/locations/${L}/keyRings?keyRingId=kr`,{});
  await f("kms","POST",`/v1/projects/${P}/locations/${L}/keyRings/kr/cryptoKeys?cryptoKeyId=k1`,{purpose:"ENCRYPT_DECRYPT"});
  const enc = await f("kms","POST",`/v1/projects/${P}/locations/${L}/keyRings/kr/cryptoKeys/k1:encrypt`,{plaintext:btoa("secret")});
  await f("kms","POST",`/v1/projects/${P}/locations/${L}/keyRings/kr/cryptoKeys/k1:decrypt`,{ciphertext:enc.j&&enc.j.ciphertext});
  await f("logging","POST",`/v2/entries:write`,{logName:`projects/${P}/logs/agent`,resource:{type:"global"},entries:[{textPayload:"hello"}]});
  await f("logging","POST",`/v2/entries:list`,{resourceNames:[`projects/${P}`],filter:'logName="projects/'+P+'/logs/agent"'});
  await f("monitoring","POST",`/v3/projects/${P}/timeSeries`,{timeSeries:[{metric:{type:"custom.googleapis.com/x"},resource:{type:"global"},points:[{interval:{endTime:new Date().toISOString()},value:{int64Value:"1"}}]}]});
  await f("trace","POST",`/v2/projects/${P}/traces:batchWrite`,{spans:[{name:`projects/${P}/traces/0123456789abcdef0123456789abcdef/spans/0123456789abcdef`,spanId:"0123456789abcdef",displayName:{value:"s"},startTime:new Date().toISOString(),endTime:new Date().toISOString()}]});
  await f("armor","POST",`/compute/v1/projects/${P}/global/securityPolicies`,{name:"p1",rules:[]});
  await f("modelarmor","POST",`/v1/projects/${P}/locations/${L}/templates?templateId=t1`,{filterConfig:{}});
  await f("discoveryengine","POST",`/v1/projects/${P}/locations/global/collections/default_collection/dataStores?dataStoreId=ds1`,{displayName:"ds1",industryVertical:"GENERIC",solutionTypes:["SOLUTION_TYPE_SEARCH"]});
  return log;
}, fx);
for (const r of out) console.log(r.label.padEnd(14), r.m, r.u.slice(0,70).padEnd(70), r.status, r.head.slice(0,110).replace(/\n/g," "));
fs.writeFileSync(process.argv[3], JSON.stringify(out,null,1));
await browser.close();
