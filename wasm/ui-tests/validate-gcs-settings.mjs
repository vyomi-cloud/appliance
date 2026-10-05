import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/gcp-console.html");
  const out = await page.evaluate(async () => {
    await fetch("/api/gcp/storage/v1/b", { method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({ name:"settest" }) });
    const lc = { rule: [{ action:{type:"Delete"}, condition:{age:30} }] };
    const pr = await fetch("/api/gcp/storage/v1/b/settest", { method:"PATCH", headers:{"content-type":"application/json"}, body: JSON.stringify({ lifecycle: lc }) });
    const g = await (await fetch("/api/gcp/storage/v1/b/settest")).json().catch(()=>({}));
    return { patchStatus: pr.status, lifecycleSaved: JSON.stringify(g.lifecycle||{})===JSON.stringify(lc), got: g.lifecycle };
  });
  console.log(JSON.stringify(out, null, 1));
  console.log("\nRESULT:", (out.patchStatus===200 && out.lifecycleSaved) ? "PASS — GCS settings editable: PATCH saves + reads back" : "FAIL");
} catch(e){ console.log("ERR", String(e).split("\n")[0]); }
await browser.close(); server.close();
