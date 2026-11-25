import { chromium } from "/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/playwright/index.mjs";
const SP=process.argv[2];
for (const [name,args,headless] of [["headless-new",["--headless=new","--enable-unsafe-webgpu","--use-angle=metal","--enable-features=Vulkan"],true],["headed",["--enable-unsafe-webgpu","--use-angle=metal"],false]]) {
  const ctx = await chromium.launchPersistentContext(SP+"/m/prof-gpu-"+name,{executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",headless:false,args:args.concat(headless?[]:[]),ignoreDefaultArgs:headless?["--headless"]:[]}).catch(e=>({err:e}));
  if(ctx.err){console.log(name,"launch fail",String(ctx.err).slice(0,200));continue;}
  const p = await ctx.newPage(); await p.goto("http://localhost:8913/nano/labs/");
  const r = await p.evaluate(async()=>{ if(!navigator.gpu) return {gpu:false}; const a=await navigator.gpu.requestAdapter(); if(!a) return {gpu:true,adapter:null}; const i=a.info||{}; return {gpu:true,adapter:{vendor:i.vendor,arch:i.architecture,desc:i.description,f16:a.features.has("shader-f16"),maxBuf:a.limits.maxBufferSize}}; });
  console.log(name, JSON.stringify(r)); await ctx.close();
}
