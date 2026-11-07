/* Redshift cluster + Data API SQL + the Secrets Manager Redshift picker (Nano or offline).
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-redshiftcluster.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const ID = `wh${Date.now() % 100000}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/secretsmanager/listsecrets");
await page.waitForFunction(() => !/booting Pyodide/.test(document.body.innerText), null, { timeout: 120000 });
const Q = (p) => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body }); return await r.text();
}, [WIRE, auth("redshift"), new URLSearchParams({ Version: "2012-12-01", ...p }).toString()]);
const D = (op, b) => page.evaluate(async ([u, a, t, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(body) });
  const tx = await r.text(); return tx ? JSON.parse(tx) : {};
}, [WIRE, auth("redshift-data"), "RedshiftData." + op, b]);
const x = await Q({ Action: "CreateCluster", ClusterIdentifier: ID, NodeType: "dc2.large", MasterUsername: "admin", MasterUserPassword: "Passw0rdX" });
check("CreateCluster", x.includes(`<ClusterIdentifier>${ID}</ClusterIdentifier>`), x.slice(0, 160));
const run = async (sql) => { const s = await D("ExecuteStatement", { ClusterIdentifier: ID, Database: "dev", Sql: sql }); return { d: await D("DescribeStatement", { Id: s.Id }), r: await D("GetStatementResult", { Id: s.Id }) }; };
await run("CREATE TABLE t (a INTEGER, b TEXT)"); await run("INSERT INTO t VALUES (1,'x'),(2,'y')");
const q = await run("SELECT SUM(a) FROM t");
check("Data API runs real SQL on the cluster", q.r.Records?.[0]?.[0]?.longValue === 3, JSON.stringify(q.r).slice(0, 160));
await page.goto(UI + "#/secretsmanager/newsecret"); await page.waitForTimeout(2500);
await page.getByText("Credentials for Amazon Redshift data warehouse", { exact: true }).click(); await page.waitForTimeout(1500);
check("wizard's Redshift picker lists the cluster", await page.getByText(ID).count() >= 1);
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
