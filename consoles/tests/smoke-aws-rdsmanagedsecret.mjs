/* RDS "Managed in AWS Secrets Manager" credentials: the console create form makes an RDS-owned Secrets Manager secret.
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-rdsmanagedsecret.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const ID = `mdb${Date.now() % 100000}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/secretsmanager/listsecrets");
await page.waitForFunction(() => !/booting Pyodide/.test(document.body.innerText), null, { timeout: 120000 });
const RDS = (action, p) => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body }); return await r.text();
}, [WIRE, auth("rds"), new URLSearchParams({ Action: action, Version: "2014-10-31", ...p }).toString()]);
const SM = (op, b) => page.evaluate(async ([u, a, t, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(body) });
  const tx = await r.text(); return { status: r.status, body: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth("secretsmanager"), "secretsmanager." + op, b]);
const x = await RDS("CreateDBInstance", { DBInstanceIdentifier: ID, Engine: "postgres", MasterUsername: "app", ManageMasterUserPassword: "true" });
const arn = (x.match(/<SecretArn>(.*?)</) || [])[1];
check("CreateDBInstance returns a MasterUserSecret", !!arn, x.slice(0, 200));
const d = await SM("DescribeSecret", { SecretId: arn });
check("the secret is owned by rds", d.body.OwningService === "rds", JSON.stringify(d.body).slice(0, 160));
const put = await SM("PutSecretValue", { SecretId: arn, SecretString: "{}" });
check("user writes are rejected", put.status === 400);
await page.goto(UI + "#/secretsmanager/newsecret"); await page.waitForTimeout(2500);
await page.getByText("Managed external secret", { exact: true }).first().click(); await page.waitForTimeout(1500);
check("wizard lists the managed secret with its owner", await page.getByText(`rds!db-`).count() >= 1 && await page.getByText("rds", { exact: true }).count() >= 1);
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
