/* DynamoDB Backups page: backups really live in the simulator's S3, Copy runs a real AWS Backup copy job, and the
 * "Turn off AWS Backup integration" toggle gates it. Cross-checks over the native wire.
 *   BASE=http://127.0.0.1:9031 node consoles/tests/smoke-aws-ddbbackup.mjs                                      (offline)
 *   BASE=http://127.0.0.1:8743 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-ddbbackup.mjs   (Nano) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9031";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || ""}`;
const OUT = process.env.OUT || "smoke-out";
const T = `bkt${Date.now() % 100000}`;
const results = [];
const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1500 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/dynamodb");
const call = (svc, path, init, headers = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, { ...init, headers: { authorization: auth(svc), ...headers, ...(init.headers || {}) } }]);
const ddb = async (a, p) => { const r = await call("dynamodb", "/", { method: "POST", body: JSON.stringify(p), headers: { "x-amz-target": `DynamoDB_20120810.${a}`, "content-type": "application/x-amz-json-1.0" } }); return { status: r.status, body: r.text ? JSON.parse(r.text) : {} }; };
const bkp = async (m, path, p) => { const r = await call("backup", path, { method: m, body: p ? JSON.stringify(p) : undefined, headers: { "content-type": "application/json" } }); return { status: r.status, body: r.text ? JSON.parse(r.text) : {} }; };
const s3list = async () => (await call("s3", "/vyomi-dynamodb-backups?list-type=2", { method: "GET" })).text;

await ddb("CreateTable", { TableName: T, KeySchema: [{ AttributeName: "id", KeyType: "HASH" }], AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], BillingMode: "PAY_PER_REQUEST" });
for (let i = 0; i < 3; i++) await ddb("PutItem", { TableName: T, Item: { id: { S: `k${i}` } } });

await page.goto(UI + "#/dynamodb/backups");
await page.getByRole("button", { name: "Create backup" }).first().waitFor();
await page.getByText("Activated").first().waitFor({ timeout: 15000 }).catch(() => {});
check("Backups page loads real settings", await page.getByText("Activated").first().isVisible());
check("no Not-simulated badge on the page", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));

// create backup via the UI
await page.getByRole("button", { name: "Create backup" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Create backup" }).waitFor();
const tableSel = page.getByRole("dialog").getByRole("button", { name: /Choose a table|table/i }).first();
await tableSel.click().catch(() => {});
await page.getByRole("option", { name: T }).click().catch(() => {});
await page.getByRole("dialog").getByRole("button", { name: "Create backup" }).click();
await page.getByText(new RegExp(`${T}-backup`)).first().waitFor({ timeout: 15000 });
const lb = (await ddb("ListBackups", { TableName: T })).body.BackupSummaries || [];
check("backup created via UI", lb.length === 1 && lb[0].BackupSizeBytes > 0);
const id = lb[0]?.BackupArn.split("/").pop();
check("backup data exists as objects in the simulator's S3", (await s3list()).includes(`AWSDynamoDB/backups/${T}/${id}/data/1.json`));

// copy via UI
await page.getByRole("row", { name: new RegExp(T) }).getByRole("radio").check();
await page.getByRole("button", { name: "Copy", exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: "Copy", exact: true }).click();
await page.getByText("COMPLETED").first().waitFor({ timeout: 15000 });
const jobs = (await bkp("GET", "/copy-jobs")).body.CopyJobs || [];
check("copy job completed, destination backup in eu-west-1", jobs.length === 1 && jobs[0].State === "COMPLETED" && /:eu-west-1:/.test(jobs[0].DestinationRecoveryPointArn || ""), jobs[0]?.DestinationRecoveryPointArn);
check("copy has its own S3 objects", (await s3list()).includes("backup-copies/123456789012/eu-west-1/Default/"));
await page.screenshot({ path: `${OUT}/ddb-backups.png`, fullPage: true });

// toggle off -> Copy disabled, wire refuses; toggle on -> allowed
await page.getByRole("button", { name: "Turn off" }).click();
await page.getByText("Not activated").waitFor({ timeout: 10000 });
check("settings reflect OFF on the wire", (await bkp("GET", "/account-settings")).body.ResourceTypeManagementPreference?.DynamoDB === false);
await page.getByRole("row", { name: new RegExp(T) }).first().getByRole("radio").check();
check("Copy disabled while integration is off", await page.getByRole("button", { name: "Copy", exact: true }).isDisabled());
await page.getByRole("button", { name: "Turn on" }).click();
await page.getByText("Activated").first().waitFor({ timeout: 10000 });
let on = false;
for (let i = 0; i < 20 && !on; i++) { on = (await bkp("GET", "/account-settings")).body.ResourceTypeManagementPreference?.DynamoDB === true; if (!on) await page.waitForTimeout(500); }  // Nano: UI can show "Activated" (still from before) ahead of the wire write
check("settings back ON", on);

// restore from S3-backed backup via wire + delete cleans S3
await ddb("DeleteTable", { TableName: T });
const rs = await ddb("RestoreTableFromBackup", { BackupArn: lb[0].BackupArn, TargetTableName: `${T}r` });
const sc = await ddb("Scan", { TableName: `${T}r` });
check("restore from the S3 backup returns all items", rs.status === 200 && (sc.body.Items || []).length === 3);
await ddb("DeleteBackup", { BackupArn: lb[0].BackupArn });
check("DeleteBackup removes the S3 objects", !(await s3list()).includes(`AWSDynamoDB/backups/${T}/${id}/`));
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r).length;
console.log(`\n${results.length - bad}/${results.length} passed`);
process.exit(bad ? 1 : 0);
