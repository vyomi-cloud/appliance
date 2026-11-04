/* AWS Backup console: vault create, on-demand backup of a real DynamoDB table, restore wizard, plan + assignment, vault lock.
 *   BASE=http://127.0.0.1:9075 node consoles/tests/smoke-aws-backup.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9075";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const T = `bk${Date.now() % 100000}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/backup");
const call = (svc, path, init, headers = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, { ...init, headers: { authorization: auth(svc), ...headers, ...(init.headers || {}) } }]);
const ddb = (a, p) => call("dynamodb", "/", { method: "POST", body: JSON.stringify(p), headers: { "x-amz-target": `DynamoDB_20120810.${a}`, "content-type": "application/x-amz-json-1.0" } });
const bkp = async (m, path, p) => { const r = await call("backup", path, { method: m, body: p ? JSON.stringify(p) : undefined, headers: { "content-type": "application/json" } }); return { status: r.status, body: r.text ? JSON.parse(r.text) : {} }; };

await ddb("CreateTable", { TableName: T, KeySchema: [{ AttributeName: "id", KeyType: "HASH" }], AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], BillingMode: "PAY_PER_REQUEST" });
await ddb("PutItem", { TableName: T, Item: { id: { S: "a" } } });

await page.getByText("AWS Backup dashboard").first().waitFor({ timeout: 15000 });
check("dashboard renders", await page.getByText("Protected resources").first().isVisible());

// vaults: create via UI
await page.goto(UI + "#/backup/vaults");
await page.getByRole("button", { name: "Create backup vault" }).first().click();
await page.getByRole("dialog").getByRole("textbox").fill("ui-vault");
await page.getByRole("dialog").getByRole("button", { name: "Create backup vault" }).click();
await page.getByText("ui-vault").first().waitFor({ timeout: 15000 });
check("vault created via UI", (await bkp("GET", "/backup-vaults")).body.BackupVaultList.some((v) => v.BackupVaultName === "ui-vault"));

// on-demand backup via UI
await page.goto(UI + "#/backup/vaults/view?name=ui-vault");
await page.getByRole("button", { name: "Create on-demand backup" }).click();
await page.getByRole("dialog").getByRole("textbox").first().fill(`arn:aws:dynamodb:us-east-1:123456789012:table/${T}`);
await page.getByRole("dialog").getByRole("button", { name: "Create on-demand backup" }).click();
await page.getByText("DynamoDB").first().waitFor({ timeout: 15000 });
const rps = (await bkp("GET", "/backup-vaults/ui-vault/recovery-points")).body.RecoveryPoints || [];
check("recovery point created for the real table", rps.length === 1 && rps[0].ResourceType === "DynamoDB", rps[0]?.RecoveryPointArn);

// restore via UI
await page.getByRole("row", { name: /DynamoDB/ }).getByRole("radio").check();
await page.getByRole("button", { name: "Restore", exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: "Restore backup" }).waitFor();
await page.getByRole("dialog").getByRole("textbox").first().fill(`${T}-restored`);
await page.getByRole("dialog").getByRole("button", { name: "Restore backup" }).click();
await page.getByText("COMPLETED").first().waitFor({ timeout: 15000 });
const d = JSON.parse((await ddb("DescribeTable", { TableName: `${T}-restored` })).text);
check("restore job created a real table", !!d.Table, JSON.stringify(d).slice(0, 80));

// plan create via UI
await page.goto(UI + "#/backup/create-plan");
await page.getByLabel("Backup plan name").fill("ui-plan");
await page.getByRole("button", { name: "Create plan" }).click();
await page.getByText("Resource assignments").first().waitFor({ timeout: 15000 });
check("plan created via UI", (await bkp("GET", "/backup/plans")).body.BackupPlansList.some((p) => p.BackupPlanName === "ui-plan"));
await page.getByRole("button", { name: "Assign resources" }).first().click();
await page.getByRole("dialog").getByRole("textbox").nth(0).fill("all-tables");
await page.getByRole("dialog").getByRole("textbox").nth(1).fill(`arn:aws:dynamodb:us-east-1:123456789012:table/${T}`);
await page.getByRole("dialog").getByRole("button", { name: "Assign resources" }).click();
await page.getByText("all-tables").first().waitFor({ timeout: 15000 });
check("resource assignment listed", true);

// vault lock governance
await page.goto(UI + "#/backup/vaults/view?name=ui-vault");
await page.getByRole("tab", { name: "Vault Lock" }).click();
await page.getByRole("button", { name: "Create Vault Lock" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
await page.getByText(/Locked\./).first().waitFor({ timeout: 15000 });
check("vault lock applied", (await bkp("GET", "/backup-vaults/ui-vault")).body.Locked === true);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
