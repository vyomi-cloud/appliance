/* EventBridge sweep (AWS-08): bus KMS encryption, bus logs, resource policy, archive-at-create. UI <-> native wire.
 *   BASE=http://127.0.0.1:9110 node consoles/tests/smoke-aws-ebsweep.mjs                                              (offline)
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-ebsweep.mjs  (Nano)
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
const BUS = `ebsw-${N}`, ARCH = `ebsw-arch-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const J = (svc, target, body, acct) => page.evaluate(async ([u, a, t, b, ac]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1", ...(ac ? { "x-amz-account-id": ac } : {}) }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, json: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth(svc), target, body, acct]);
const eb = (op, b, acct) => J("events", `AWSEvents.${op}`, b, acct);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const body = async () => await page.locator("body").innerText();

await page.goto(UI + "#/eventbridge");
await page.getByText("EventBridge").first().waitFor({ timeout: 30000 });
const key = await J("kms", "TrentService.CreateKey", { Description: "ebsw" });
const KID = key.json.KeyMetadata.KeyId;

// create bus through the UI with KMS key + INFO logs + attached archive
await page.goto(UI + "#/eventbridge/create-event-bus");
await page.getByLabel("Name", { exact: true }).first().fill(BUS);
const sels = page.getByRole("button", { name: /Key Management/ });
await sels.click();
await page.getByRole("option", { name: new RegExp(KID) }).click();
await page.getByRole("button", { name: /Log level/ }).click();
await page.getByRole("option", { name: "INFO" }).click();
await page.getByRole("button", { name: /Include execution data/ }).click();
await page.getByRole("option", { name: "Full" }).click();
await page.getByLabel("Archive name").fill(ARCH);
check("create form no longer shows Not simulated for KMS/logs/policy/archive", !/Event bus encryption with a customer KMS key|Delivering bus logs|Resource-based policy enforcement|Attaching an archive/.test(await body()));
await shot("ebsw-create");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("heading", { name: BUS }).first().waitFor({ timeout: 15000 });
const d = await eb("DescribeEventBus", { Name: BUS });
check("UI-created bus carries the KMS key + LogConfig on the wire", d.json.KmsKeyIdentifier?.endsWith(KID) && d.json.LogConfig?.Level === "INFO" && d.json.LogConfig?.IncludeDetail === "FULL", JSON.stringify(d.json).slice(0, 200));
const ar = await eb("DescribeArchive", { ArchiveName: ARCH });
check("archive attached at bus creation exists with the bus key", ar.status === 200 && ar.json.KmsKeyIdentifier?.endsWith(KID), JSON.stringify(ar.json).slice(0, 160));

// encryption tab
await page.getByRole("tab", { name: "Encryption" }).click();
await page.getByText("Customer managed key").first().waitFor({ timeout: 10000 });
check("Encryption tab shows the customer key", (await body()).includes(KID));

// permissions tab: cross-account denied -> allow in UI -> allowed
const put = { Entries: [{ EventBusName: BUS, Source: "ui.test", DetailType: "t", Detail: JSON.stringify({ k: "v" }) }] };
const denied = await eb("PutEvents", put, "444455556666");
check("cross-account PutEvents denied before any statement", denied.json.Entries?.[0]?.ErrorCode === "AccessDeniedException");
await page.getByRole("tab", { name: "Permissions" }).click();
await page.getByLabel("Statement ID").fill("allow4444");
await page.getByLabel("Account ID").fill("444455556666");
await page.getByRole("button", { name: "Add statement" }).click();
await page.getByRole("cell", { name: "allow4444" }).waitFor({ timeout: 10000 }).catch(async (e) => { await shot("ebsw-fail"); console.log((await body()).slice(0, 1500)); throw e; });
const allowed = await eb("PutEvents", put, "444455556666");
check("statement added in the UI lets that account put events", allowed.json.FailedEntryCount === 0);
await shot("ebsw-permissions");
await page.getByRole("button", { name: "Remove" }).first().click();
await page.getByRole("cell", { name: "allow4444" }).waitFor({ state: "detached", timeout: 10000 });
const denied2 = await eb("PutEvents", put, "444455556666");
check("Remove in the UI revokes access", denied2.json.FailedEntryCount === 1);

// logs tab shows the real CloudWatch Logs records
await page.getByRole("tab", { name: "Logs" }).click();
await page.getByText("EVENT_RECEIVED").first().waitFor({ timeout: 15000 });
check("Logs tab lists EVENT_RECEIVED records with detail", (await body()).includes('"k": "v"') || (await body()).includes('"k":"v"'));
const lg = await J("logs", "Logs_20140328.FilterLogEvents", { logGroupName: `/aws/vendedlogs/events/event-bus/${BUS}` });
check("records are really in CloudWatch Logs", (lg.json.events || []).length >= 2);
await shot("ebsw-logs");
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
