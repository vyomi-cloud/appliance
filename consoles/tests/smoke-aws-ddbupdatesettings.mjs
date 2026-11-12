/* DynamoDB Settings > Update settings: saved defaults drive the Create table form's "Default settings" (Nano or offline).
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-aws-ddbupdatesettings.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const T = `defaults${Date.now() % 100000}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/dynamodb/update-settings"); await page.waitForTimeout(2500);
check("Update settings is a real form, not a not-simulated panel", await page.locator("[data-vyomi-not-simulated]").count() === 0 && await page.getByText("Default settings for new tables").count() >= 1);
await page.getByText("Provisioned", { exact: true }).click();
await page.getByText("DynamoDB Standard-IA").click();
await page.getByRole("button", { name: "Save changes" }).click(); await page.waitForTimeout(1200);
check("Settings page shows the saved defaults", await page.getByText("Provisioned (5 RCU / 5 WCU)").count() >= 1);
await page.goto(UI + "#/dynamodb/create-table"); await page.waitForTimeout(2000);
await page.getByLabel("Table name").fill(T);
await page.getByLabel("Partition key").first().fill("pk");
await page.getByRole("button", { name: "Create table" }).last().click(); await page.waitForTimeout(3500);
const d = await page.evaluate(async ([u, a, t]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": "DynamoDB_20120810.DescribeTable", "content-type": "application/x-amz-json-1.0" }, body: JSON.stringify({ TableName: t }) });
  return (await r.json()).Table || {};
}, [WIRE, auth, T]);
check("the table was created PROVISIONED 5/5 per the saved defaults", d.ProvisionedThroughput?.ReadCapacityUnits === 5 && d.BillingModeSummary?.BillingMode !== "PAY_PER_REQUEST", JSON.stringify(d.BillingModeSummary) + JSON.stringify(d.ProvisionedThroughput));
check("table class Standard-IA applied", d.TableClassSummary?.TableClass === "STANDARD_INFREQUENT_ACCESS", JSON.stringify(d.TableClassSummary));
console.log(`${results.filter(Boolean).length} passed, ${results.filter((x) => !x).length} failed`);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
