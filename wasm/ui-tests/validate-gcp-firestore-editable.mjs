/* GCP firestore made editable: Data tab PATCHes typed fields → reads back. */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
try {
  await bootConsole(page, base, "/gcp-console.html");
  const out = await page.evaluate(async () => {
    const PROJ = "demo";
    // create a firestore document via the console collection path
    await fetch(`/api/gcp/firestore/v1/projects/${PROJ}/databases`, { method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({ name:"fsdoc" }) });
    const fields = { color: { stringValue: "blue" }, count: { integerValue: "7" } };
    const pr = await fetch(`/api/gcp/firestore/v1/projects/${PROJ}/databases/fsdoc`, { method:"PATCH", headers:{"content-type":"application/json"}, body: JSON.stringify({ fields }) });
    const g = await (await fetch(`/api/gcp/firestore/v1/projects/${PROJ}/databases/fsdoc`)).json().catch(()=>({}));
    const gf = g.fields || {};
    const saved = (gf.color && gf.color.stringValue === "blue") && (gf.count && gf.count.integerValue === "7");
    return { patchStatus: pr.status, fieldsSaved: saved, got: gf };
  });
  console.log(JSON.stringify(out, null, 1));
  console.log("\nRESULT:", (out.patchStatus === 200 && out.fieldsSaved) ? "PASS — Firestore editable: document fields PATCH saves + reads back" : "FAIL");
} catch(e){ console.log("ERR", String(e).split("\n")[0]); }
await browser.close(); server.close();
