/* DynamoDB reserved capacity + RDS capacity reservations: real pages with real utilisation (a provisioned table / running instance moves the numbers).
 *   BASE=http://127.0.0.1:9084 node consoles/tests/smoke-aws-reservations.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9084";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, d = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const sc = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/dynamodb");
const post = (svc, headers, body) => page.evaluate(async ([u, a, h, b]) => { const r = await fetch(`${u}/`, { method: "POST", headers: { authorization: a, ...h }, body: b }); return r.status; }, [WIRE, sc(svc), headers, body]);
const text = () => page.locator("body").innerText();
const dialog = () => page.getByRole("dialog");

// DynamoDB: provisioned table first so utilisation has something to measure
const T = `rc-table-${N}`;
await post("dynamodb", { "x-amz-target": "DynamoDB_20120810.CreateTable", "content-type": "application/x-amz-json-1.0" }, JSON.stringify({ TableName: T, KeySchema: [{ AttributeName: "id", KeyType: "HASH" }], AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], BillingMode: "PROVISIONED", ProvisionedThroughput: { ReadCapacityUnits: 40, WriteCapacityUnits: 60 } }));
await page.goto(UI + "#/dynamodb/reserved-capacity");
await page.getByRole("button", { name: "Purchase reserved capacity" }).first().waitFor();
check("DynamoDB reserved capacity is a real page", !/Not simulated in Vyomi/i.test(await text()));
await page.getByRole("button", { name: "Purchase reserved capacity" }).first().click();
await dialog().getByRole("textbox", { name: "Units" }).fill("50");
await dialog().getByRole("button", { name: "Purchase", exact: true }).click();
await dialog().getByText(/at least 100/i).waitFor({ timeout: 10000 });
check("units below 100 refused", true);
await dialog().getByRole("textbox", { name: "Units" }).fill("100");
await dialog().getByRole("button", { name: "Purchase", exact: true }).click();
await page.getByText(/ddb-rc-/).first().waitFor({ timeout: 10000 });
await page.getByText(/of 100 reserved units used/).first().waitFor({ timeout: 10000 });
check("write utilisation computed from the provisioned table (60 of 100)", /60 of 100 reserved units used/.test(await text()), (await text()).match(/\d+ of \d+ reserved units used/)?.[0]);
await page.screenshot({ path: `${OUT}/reserved-capacity.png`, fullPage: true });
await post("dynamodb", { "x-amz-target": "DynamoDB_20120810.DeleteTable", "content-type": "application/x-amz-json-1.0" }, JSON.stringify({ TableName: T }));

// RDS capacity reservation
const DB = `rcdb-${N}`;
await page.goto(UI + "#/rds/capacity-reservations");
await page.getByRole("button", { name: "Create capacity reservation" }).first().waitFor();
check("RDS capacity reservations is a real page", !/Not simulated in Vyomi/i.test(await text()));
await post("rds", { "content-type": "application/x-www-form-urlencoded" }, new URLSearchParams({ Action: "CreateDBInstance", DBInstanceIdentifier: DB, DBInstanceClass: "db.t3.micro", Engine: "postgres", MasterUsername: "u", MasterUserPassword: "password1", AllocatedStorage: "20", AvailabilityZone: "us-east-1a" }).toString());
await page.getByRole("button", { name: "Create capacity reservation" }).first().click();
await page.getByLabel("Number of instances").fill("2");
await page.getByLabel("DB instance class").fill("m5.large");
await page.getByRole("button", { name: "Create capacity reservation" }).last().click();
await page.getByText(/DBInstanceClass must look like/).first().waitFor({ timeout: 10000 });
check("invalid instance class surfaces the core's error", true);
await page.getByLabel("DB instance class").fill("db.t3.micro");
await page.getByRole("button", { name: "Create capacity reservation" }).last().click();
await page.getByText(/rds-cr-/).first().waitFor({ timeout: 10000 });
await page.getByText(/\d \(\d+(\.\d)?%\)/).first().waitFor({ timeout: 15000 }).catch(() => {});  // Nano: the table loads after the row appears
check("reservation shows 1 of 2 in use (50%) from the running instance", /1 \(50%\)/.test(await text()), (await text()).match(/\d \(\d+(\.\d)?%\)/)?.[0]);
await page.screenshot({ path: `${OUT}/rds-capacity.png`, fullPage: true });
await post("rds", { "content-type": "application/x-www-form-urlencoded" }, new URLSearchParams({ Action: "DeleteDBInstance", DBInstanceIdentifier: DB, SkipFinalSnapshot: "true" }).toString());
await page.getByRole("row", { name: /rds-cr-/ }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Cancel reservation" }).click();
await dialog().getByRole("textbox").fill("cancel");
await dialog().getByRole("button", { name: /Delete|Cancel reservation/ }).last().click();
await page.getByText("cancelled").first().waitFor({ timeout: 10000 });
check("reservation cancelled", true);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
