/* GCP detail sub-resource tabs show REAL core data (create one → see it listed). */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
try {
  await bootConsole(page, base, "/gcp-console.html");
  const out = await page.evaluate(async () => {
    const PROJ = "demo";
    const J = async (m, p, b) => {
      const o = { method: m, headers: {} };
      if (b !== undefined) { o.headers["content-type"] = "application/json"; o.body = JSON.stringify(b); }
      const r = await fetch(p, o); let j = null; try { j = await r.json(); } catch(_){}
      return { status: r.status, json: j };
    };
    const res = {};

    // ---- Pub/Sub subscriptions ---- (topic via collection POST, as the console does)
    await J("POST", `/api/gcp/pubsub/v1/projects/${PROJ}/topics`, { name: "orders" });
    const subCreate = await J("POST", `/api/gcp/subresource/pubsub/orders/subscriptions`, { name: "orders-sub" });
    const subList = await J("GET", `/api/gcp/subresource/pubsub/orders/subscriptions`);
    res.pubsub = { createOk: subCreate.json && subCreate.json.ok !== false, listed: (subList.json.items||[]).some(s => (s.name||"").includes("orders-sub")), items: subList.json.items };

    // ---- Cloud SQL databases ----
    await J("POST", `/api/gcp/rds/databases`, { name: "pg1", databaseVersion: "POSTGRES_15" });
    const dbCreate = await J("POST", `/api/gcp/subresource/cloudsql/pg1/databases`, { name: "appdb" });
    const dbList = await J("GET", `/api/gcp/subresource/cloudsql/pg1/databases`);
    res.cloudsql = { createOk: dbCreate.json && dbCreate.json.ok !== false, listed: (dbList.json.items||[]).some(d => (d.name||"") === "appdb"), items: dbList.json.items };

    // ---- Secret Manager versions (create secret seeds a version) ----
    await J("POST", `/api/gcp/secrets`, { name: "apikey" });
    const secList = await J("GET", `/api/gcp/subresource/secretmanager/apikey/versions`);
    res.secretmanager = { listed: (secList.json.items||[]).length >= 1, items: secList.json.items };

    // ---- KMS versions (create key seeds version 1) ----
    await J("POST", `/api/gcp/kms/keys`, { name: "mykey" });
    const kmsList = await J("GET", `/api/gcp/subresource/kms/mykey/versions`);
    res.kms = { listed: (kmsList.json.items||[]).length >= 1, items: kmsList.json.items };

    return res;
  });
  results.push(["pubsub subscriptions (create+list)", out.pubsub.createOk && out.pubsub.listed, out.pubsub]);
  results.push(["cloudsql databases (create+list)",  out.cloudsql.createOk && out.cloudsql.listed, out.cloudsql]);
  results.push(["secretmanager versions (list)",     out.secretmanager.listed, out.secretmanager]);
  results.push(["kms versions (list)",               out.kms.listed, out.kms]);
} catch(e){ results.push(["(err)", false, String(e).split("\n")[0]]); }
await browser.close(); server.close();

console.log("===== GCP detail sub-resource tabs — real-data check =====");
let allPass = true;
for (const [label, pass, detail] of results) {
  if (!pass) allPass = false;
  console.log(`  [${pass ? "PASS" : "FAIL"}] ${label}`);
  if (!pass) console.log("        ", JSON.stringify(detail));
}
console.log("\nRESULT:", allPass ? "PASS — all GCP sub-resource tabs render real core data" : "FAIL");
process.exit(allPass ? 0 : 1);
