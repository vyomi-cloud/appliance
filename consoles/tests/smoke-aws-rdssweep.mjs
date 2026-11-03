/* RDS sweep (AWS-09): IAM role association, CloudWatch alarms tab, dashboard + service-quota pages. UI <-> native wire.
 *   BASE=http://127.0.0.1:9110 node consoles/tests/smoke-aws-rdssweep.mjs
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-rdssweep.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9110";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const DB = `rdssw-${N}`, ROLE = `rdssw-role-${N}`, ALARM = `rdssw-alarm-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const Q = (svc, action, params = {}, version = "2014-10-31") => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body });
  return { status: r.status, text: await r.text() };
}, [WIRE, auth(svc), new URLSearchParams({ Action: action, Version: version, ...params }).toString()]);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const body = async () => await page.locator("body").innerText();

await page.goto(UI + "#/rds");
await page.getByText("Aurora and RDS").first().waitFor({ timeout: 30000 });
const trust = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: "rds.amazonaws.com" }, Action: "sts:AssumeRole" }] });
await Q("iam", "CreateRole", { RoleName: ROLE, AssumeRolePolicyDocument: trust }, "2010-05-08");
const mk = await Q("rds", "CreateDBInstance", { DBInstanceIdentifier: DB, Engine: "postgres", DBInstanceClass: "db.t3.micro", MasterUsername: "u", MasterUserPassword: "pw12345678", AllocatedStorage: "25" });
check("fixture DB created", mk.status === 200);

// dashboard + service quota routes
await page.goto(UI + "#/rds/dashboard");
await page.getByText("Welcome to Aurora and RDS").waitFor({ timeout: 15000 });
check("/rds/dashboard renders the dashboard", true);
await page.goto(UI + "#/rds/service-quota");
await page.getByRole("heading", { name: "Service quotas" }).first().waitFor({ timeout: 15000 });
await page.getByRole("cell", { name: "AllocatedStorage" }).waitFor({ timeout: 15000 });
check("/rds/service-quota lists the real quotas with live usage", (await body()).includes("DBInstances") && (await body()).includes("100000"));
await shot("rdssw-quota");

// IAM role association on the Configuration tab
await page.goto(UI + `#/rds/databases/${DB}`);
await page.getByRole("tab", { name: "Configuration" }).click();
await page.getByRole("button", { name: "Add IAM role" }).click();
await page.getByRole("button", { name: /Feature/ }).first().click();
await page.getByRole("option", { name: "s3Export" }).click();
await page.getByRole("button", { name: /IAM role/ }).last().click();
await page.getByRole("option", { name: new RegExp(ROLE) }).click();
await page.getByRole("button", { name: "Add role" }).click();
await page.getByRole("cell", { name: ROLE }).waitFor({ timeout: 15000 }).catch(async (e) => { await shot("rdssw-fail"); throw e; });
const d = await Q("rds", "DescribeDBInstances", { DBInstanceIdentifier: DB });
check("role associated in the UI is on the instance via the native wire", d.text.includes(`role/${ROLE}`) && d.text.includes("s3Export"));
await shot("rdssw-roles");

// CloudWatch alarms
await page.getByRole("tab", { name: "Logs & events" }).click();
await page.getByRole("button", { name: "Create CloudWatch alarm" }).click();
await page.getByLabel("Alarm name").fill(ALARM);
await page.getByLabel("Threshold").fill("5");
await page.getByRole("button", { name: "Create alarm" }).click();
await page.getByText(ALARM).first().waitFor({ timeout: 15000 });
const al = await page.evaluate(async ([u, a, n]) => { const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": "GraniteServiceVersion20100801.DescribeAlarms", "content-type": "application/x-amz-json-1.0" }, body: JSON.stringify({ AlarmNames: [n] }) }); return r.json(); }, [WIRE, auth("monitoring"), ALARM]);
check("alarm created in the UI exists in CloudWatch with the DB dimension", al.MetricAlarms?.[0]?.Dimensions?.some((x) => x.Value === DB) && al.MetricAlarms[0].Threshold === 5);
check("Logs & events tab no longer shows Not simulated for alarms", !/RDS CloudWatch alarms isn't backed/.test(await body()));
await shot("rdssw-alarms");

// create-database IAM section
await page.goto(UI + "#/rds/create-database");
await page.getByRole("heading", { name: /IAM roles - optional/ }).waitFor({ timeout: 15000 });
check("create-database IAM roles section has no Not-simulated note", !/IAM role association isn't backed/.test(await body()));
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
