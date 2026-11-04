/* DynamoDB provisioned-capacity auto scaling: the Create table form registers a scalable target + target-tracking policy
 * through Application Auto Scaling, and Edit capacity shows/changes it. Cross-checks over the native wire.
 *   BASE=http://127.0.0.1:9050 node consoles/tests/smoke-aws-ddbautoscaling.mjs                                 (dev server / offline)
 *   BASE=http://127.0.0.1:8743 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-ddbautoscaling.mjs   (Nano) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9050";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const T = `asc${Date.now() % 100000}`;
const results = [];
const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1600 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/dynamodb");
const aas = async (op, p) => { const r = await page.evaluate(async ([u, i]) => { const x = await fetch(u, i); return { status: x.status, text: await x.text() }; },
  [WIRE + "/", { method: "POST", body: JSON.stringify(p), headers: { authorization: auth("application-autoscaling"), "x-amz-target": `AnyScaleFrontendService.${op}`, "content-type": "application/x-amz-json-1.1" } }]);
  return { status: r.status, body: r.text ? JSON.parse(r.text) : {} }; };

await page.goto(UI + "#/dynamodb/create-table");
await page.getByLabel("Table name").fill(T);
await page.getByLabel("Partition key", { exact: false }).first().fill("id");
await page.getByText("Customize settings").click();
await page.getByText("Provisioned", { exact: true }).first().click();
check("auto scaling section is not the Not-simulated panel", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
await page.getByText("Write capacity auto scaling").click();
await page.getByLabel("Write minimum capacity units").fill("5");
await page.getByLabel("Write maximum capacity units").fill("50");
await page.getByLabel("Write target utilization").fill("60");
await page.getByRole("button", { name: "Create table" }).last().click();
await page.waitForURL(/#\/dynamodb\/tables/, { timeout: 15000 }).catch(() => {});
const t = (await aas("DescribeScalableTargets", { ServiceNamespace: "dynamodb", ResourceIds: [`table/${T}`] })).body.ScalableTargets || [];
check("scalable target registered for write capacity", t.length === 1 && t[0].MinCapacity === 5 && t[0].MaxCapacity === 50 && t[0].ScalableDimension.endsWith("WriteCapacityUnits"), JSON.stringify(t));
const p = (await aas("DescribeScalingPolicies", { ServiceNamespace: "dynamodb", ResourceId: `table/${T}` })).body.ScalingPolicies || [];
check("target-tracking policy at 60%", p.length === 1 && p[0].TargetTrackingScalingPolicyConfiguration.TargetValue === 60);

await page.goto(UI + `#/dynamodb/tables/${T}`);
await page.getByText("Additional settings").first().click().catch(() => {});
await page.waitForTimeout(1500);
check("Settings tab shows auto scaling on", /On: 5 - 50 units, target 60%/.test(await page.locator("body").innerText()));
check("no page errors", errors.length === 0, errors.join("; "));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
