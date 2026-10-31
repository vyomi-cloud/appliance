/* End-to-end smoke of the AWS lens against a running /_wire backend (dev_server.py, the
 * offline appliance, or Nano). Drives the UI like a user; cross-checks state over the
 * native wire (what an SDK/CLI would see). Screenshots → $OUT (default ./smoke-out).
 *
 *   BASE=http://127.0.0.1:8740 node consoles/tests/smoke-aws.mjs
 */
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:8740";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const B = `v4-smoke-${Date.now() % 100000}`;
const T = `v4smoke${Date.now() % 100000}`;
const T2 = `v4smokelsi${Date.now() % 100000}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;
// Native-wire cross-checks run INSIDE the page (same origin) — on Nano only the service
// worker answers /_wire, and it only sees requests from pages it controls.
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return r.text(); }, [WIRE + path, init]);
const ddb = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `DynamoDB_20120810.${target}`, "content-type": "application/x-amz-json-1.0", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const kms = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `TrentService.${target}`, "content-type": "application/x-amz-json-1.1", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/kms/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const sm = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `secretsmanager.${target}`, "content-type": "application/x-amz-json-1.1", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/secretsmanager/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const sqs = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `AmazonSQS.${target}`, "content-type": "application/x-amz-json-1.0", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/sqs/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const sns = async (action, body) => wire("/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/sns/aws4_request, SignedHeaders=host, Signature=0" }, body: new URLSearchParams({ Action: action, ...body }).toString() });
const events = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `AWSEvents.${target}`, "content-type": "application/x-amz-json-1.1", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/events/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const scheduler = async (method, path, body) => { const t = await wire(path, { method, headers: { "content-type": "application/json", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/scheduler/aws4_request, SignedHeaders=host, Signature=0" }, body: body === undefined ? undefined : JSON.stringify(body) }); try { return JSON.parse(t); } catch { return t; } };
const kinesis = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `Kinesis_20131202.${target}`, "content-type": "application/x-amz-json-1.1", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/kinesis/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const sfn = async (target, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `AWSStepFunctions.${target}`, "content-type": "application/x-amz-json-1.0", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/states/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const lam = async (method, path, body) => { const t = await wire(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }); try { return JSON.parse(t); } catch { return t; } };
const rds = async (action, body = {}) => wire("/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/rds/aws4_request, SignedHeaders=host, Signature=0" }, body: new URLSearchParams({ Action: action, ...body }).toString() });
const iamXml = async (body) => wire("/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=0" }, body: new URLSearchParams(body).toString() });
// EC2 Query protocol: form-encoded Action=..., XML response — extract tags with a small regex (no DOMParser in this context).
const ec2 = async (action, params = {}) => wire("/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0" }, body: new URLSearchParams({ Action: action, ...params }).toString() });
const cw = async (op, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `GraniteServiceVersion20100801.${op}`, "content-type": "application/x-amz-json-1.0", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/monitoring/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const cwlogs = async (op, body) => JSON.parse(await wire("/", { method: "POST", headers: { "x-amz-target": `Logs_20140328.${op}`, "content-type": "application/x-amz-json-1.1", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/logs/aws4_request, SignedHeaders=host, Signature=0" }, body: JSON.stringify(body) }));
const cfn = async (action, params = {}) => wire("/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/cloudformation/aws4_request, SignedHeaders=host, Signature=0" }, body: new URLSearchParams({ Action: action, ...params }).toString() });
const xtag = (xml, tag) => { const m = xml.match(new RegExp(`<${tag}>(.*?)</${tag}>`)); return m ? m[1] : null; };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Native 404s ("no tag set", "no encryption config") and the deliberate 400 from
// GetSecretValue against a disabled CMK (below) are expected answers, not page errors.
page.on("console", (m) => m.type() === "error" && !/status of (400|403|404)/.test(m.text()) && errors.push(m.text()));   // 403 = an expected denial (Object Lock, IAM)
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });

try {
  // Nano keeps fetching its in-browser runtime after load, so "networkidle" can take minutes
  // there; wait for the page, then (below) for the backend to be ready.
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  // Nano: the service worker must control the page (nano-boot reloads once) before /_wire works.
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Console Home" }).waitFor({ timeout: 120000 });
  await shot("01-home");
  check("home renders", true);

  // S3: create bucket through the form
  await page.goto(UI + "#/s3/create");
  await page.getByLabel("Bucket name", { exact: true }).fill(B);
  await page.getByRole("radio", { name: "Enable", exact: true }).first().check();   // Bucket Versioning
  await shot("02-s3-create-filled");
  await page.getByRole("button", { name: "Create bucket" }).last().click();
  await page.getByRole("heading", { name: B }).waitFor({ timeout: 10000 });
  const list = await wire("/", { headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0" } });
  check("S3 create bucket → visible over native wire", list.includes(`<Name>${B}</Name>`));
  const ver = await wire(`/${B}?versioning=`);
  check("S3 versioning applied (native GetBucketVersioning)", /<Status>Enabled<\/Status>/.test(ver), ver.slice(0, 120));
  await shot("03-s3-bucket-objects");

  // Upload via its own page, verify via wire
  await page.getByRole("link", { name: "Upload" }).first().click();
  await page.getByRole("heading", { name: "Upload", exact: true }).waitFor({ timeout: 10000 });
  await page.locator('input[type=file]:not([webkitdirectory])').setInputFiles({ name: "hello.txt", mimeType: "text/plain", buffer: Buffer.from("hello v4") });
  await page.getByRole("button", { name: "Upload" }).click();
  await page.getByRole("link", { name: "hello.txt" }).waitFor({ timeout: 10000 });
  const obj = await wire(`/${B}/hello.txt`);
  check("S3 upload → object readable over native wire", obj === "hello v4", obj);
  await shot("04-s3-uploaded");
  for (const tab of ["Properties", "Permissions", "Management"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(800);
    await shot(`05-s3-tab-${tab.toLowerCase()}`);
  }
  check("S3 detail tabs render", true);

  // Object detail: HeadObject-backed Properties + a real ListObjectVersions round-trip
  await page.getByRole("tab", { name: "Objects" }).click();
  await page.getByRole("link", { name: "hello.txt" }).click();
  await page.getByRole("heading", { name: "hello.txt" }).waitFor({ timeout: 10000 });
  await page.getByText("8 B").waitFor({ timeout: 10000 });
  await page.getByRole("tab", { name: "Versions" }).click();
  await page.getByRole("cell", { name: "Latest version" }).waitFor({ timeout: 10000 });
  await shot("04b-s3-object-detail");
  check("S3 object detail shows real HeadObject + ListObjectVersions data", true);
  await page.goBack();

  // W1 Permissions tab: every edit must land in the backend (native GET) and carry its badge.
  await page.goto(UI + `#/s3/buckets/${B}`);
  await page.getByRole("tab", { name: "Permissions" }).click();
  await page.getByText("Object Ownership", { exact: true }).first().waitFor({ timeout: 10000 });
  // DEPTH pass: encryption/PAB/policy/lifecycle/cors/ownership moved config_only → limited
  // (real enforcement — see core/capabilities/aws/s3.json), so the badges on this tab are
  // now "limited" rather than "config_only".
  check("Permissions: limited badges rendered from the registry", (await page.locator('[data-vyomi-capability="limited"]').count()) >= 3);
  const editIn = async (title) => page.getByRole("heading", { name: title }).first()
    .locator('xpath=ancestor::*[.//button[normalize-space()="Edit"]][1]').getByRole("button", { name: "Edit" }).first().click();
  await editIn("Object Ownership");
  await page.getByText("ACLs enabled — Object writer").click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.getByText("ObjectWriter").first().waitFor({ timeout: 10000 });
  check("Permissions: Object Ownership saved (native GetBucketOwnershipControls)", /ObjectWriter/.test(await wire(`/${B}?ownershipControls=`)));
  await editIn("Cross-origin resource sharing (CORS)");
  await page.getByRole("dialog").locator("textarea").fill('[{"AllowedMethods":["GET","PUT"],"AllowedOrigins":["https://app.example"]}]');
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.waitForTimeout(800);
  const corsXml = await wire(`/${B}?cors=`);
  check("Permissions: CORS saved (native GetBucketCors)", /https:\/\/app\.example/.test(corsXml) && /<AllowedMethod>PUT<\/AllowedMethod>/.test(corsXml), corsXml.slice(0, 120));
  await editIn("Bucket policy");
  await page.getByRole("dialog").locator("textarea").fill(JSON.stringify({ Version: "2012-10-17", Statement: [{ Sid: "v4", Effect: "Deny", Principal: "*", Action: "s3:DeleteBucket", Resource: `arn:aws:s3:::${B}` }] }));
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.waitForTimeout(800);
  check("Permissions: bucket policy saved (native GetBucketPolicy)", /"Sid":\s*"v4"/.test(await wire(`/${B}?policy=`)));
  await editIn("Block public access (bucket settings)");
  await page.getByRole("dialog").getByText("Block all public access").click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.waitForTimeout(800);
  check("Permissions: Block Public Access saved (native GetPublicAccessBlock)", /<BlockPublicPolicy>false<\/BlockPublicPolicy>/.test(await wire(`/${B}?publicAccessBlock=`)));
  // DEPTH pass: canned-ACL grants now round-trip for real (Block Public Access was just
  // disabled above, so a public-read canned ACL is no longer rejected).
  await editIn("Access control list (ACL)");
  await page.getByText("Public read", { exact: true }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.waitForTimeout(800);
  const aclXml = await wire(`/${B}?acl=`);
  check("Permissions: canned ACL saved → real grant on native GetBucketAcl (DEPTH)", /AllUsers/.test(aclXml) && /<Permission>READ<\/Permission>/.test(aclXml), aclXml.slice(0, 200));
  await shot("05b-s3-permissions-edited");

  // DEPTH pass: lifecycle rules are now a real create/enforce round trip, not a static list.
  await page.getByRole("tab", { name: "Management" }).click();
  await page.getByRole("button", { name: "Create lifecycle rule" }).click();
  await page.getByLabel("Lifecycle rule name").fill("v4-smoke-rule");
  await page.getByLabel("Prefix").fill("logs/");
  await page.getByRole("radio", { name: "On a specific date" }).check();
  await page.getByLabel("Expiration date").fill("2020-01-01T00:00:00.000Z");
  await page.getByRole("button", { name: "Create rule" }).click();
  await page.getByRole("cell", { name: "v4-smoke-rule" }).waitFor({ timeout: 10000 });
  const lcXml = await wire(`/${B}?lifecycle=`);
  check("Management: lifecycle rule created (native GetBucketLifecycleConfiguration)", /v4-smoke-rule/.test(lcXml) && /logs\//.test(lcXml), lcXml.slice(0, 200));
  await shot("05c-s3-lifecycle-created");

  // WAVE 5 DEPTH: Object Lock DefaultRetention is now ENFORCED (stamped onto every new
  // object version), not just stored — create a bucket with Object Lock enabled, set a
  // default retention rule through the UI, then prove a freshly uploaded object actually
  // inherits it (DeleteObject on its version id is rejected).
  const LB = `v4-smoke-lock-${Date.now() % 100000}`;
  await wire(`/${LB}`, { method: "PUT", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0", "x-amz-bucket-object-lock-enabled": "true" } });
  await page.goto(UI + `#/s3/buckets/${LB}`);
  await page.getByRole("heading", { name: LB }).waitFor({ timeout: 10000 });
  await page.getByRole("tab", { name: "Properties" }).click();
  await page.getByRole("button", { name: "Edit default retention" }).click();
  await page.getByRole("dialog").getByRole("radio", { name: "Enabled" }).check();
  await page.getByRole("dialog").getByRole("radio", { name: "Governance mode" }).check();
  await page.getByRole("dialog").locator('input[type=number]').fill("10");
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.getByText("GOVERNANCE mode, 10 days").waitFor({ timeout: 10000 });
  const lockXml = await wire(`/${LB}?object-lock=`);
  check("Properties: Object Lock default retention saved (native GetObjectLockConfiguration)", /<Mode>GOVERNANCE<\/Mode>/.test(lockXml) && /<Days>10<\/Days>/.test(lockXml), lockXml.slice(0, 200));
  // Through the page: on Nano only the page's service worker answers /_wire (a Node fetch would
  // never reach Vyomi). The deliberate 403 is an expected answer (see the console filter).
  const lockedVid = await page.evaluate(async (u) => (await fetch(u, { method: "PUT", body: "locked" })).headers.get("x-amz-version-id"), `${WIRE}/${LB}/locked.txt`);
  const lockedDelete = await wire(`/${LB}/locked.txt?versionId=${lockedVid}`, { method: "DELETE" });
  check("Object Lock default retention is enforced on a newly uploaded object (DELETE rejected)", /AccessDenied/.test(lockedDelete), lockedDelete.slice(0, 200));
  await shot("05e-s3-object-lock-default-retention");

  // Back to bucket B — the rest of the S3 flow continues on it.
  await page.goto(UI + `#/s3/buckets/${B}`);
  await page.getByRole("heading", { name: B }).waitFor({ timeout: 10000 });

  // DEPTH pass 2: Requester pays (config_only — stored+returned, UI → native wire).
  await page.getByRole("tab", { name: "Properties" }).click();
  await editIn("Requester pays");
  await page.getByRole("dialog").getByRole("radio", { name: "Enable" }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.waitForTimeout(800);
  check("Properties: Requester pays saved (native GetBucketRequestPayment)", /<Payer>Requester<\/Payer>/.test(await wire(`/${B}?requestPayment=`)));

  // DEPTH pass 2: Replication rules are now ENFORCED (synchronous same-appliance copy),
  // not a static panel — create a destination bucket over the wire, a rule through the UI,
  // then prove a matching PutObject lands in the destination for real.
  // Named independently of B (not a superstring of it) — the final "bucket list shows it"
  // check below does a substring-name lookup that must resolve to exactly one bucket.
  const DEST = `v4-repldest-${Date.now() % 100000}`;
  await wire(`/${DEST}`, { method: "PUT", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0" } });
  await page.getByRole("tab", { name: "Management" }).click();
  await page.getByRole("button", { name: "Create replication rule" }).click();
  await page.getByLabel("Replication rule name").fill("v4-smoke-repl");
  await page.getByLabel("Destination bucket").fill(DEST);
  await page.getByLabel("Prefix").fill("repl/");
  await page.getByRole("button", { name: "Create rule" }).click();
  await page.getByRole("cell", { name: "v4-smoke-repl" }).waitFor({ timeout: 10000 });
  await wire(`/${B}/repl/x.txt`, { method: "PUT", body: "replicate me" });
  const replicated = await wire(`/${DEST}/repl/x.txt`);
  check("Management: replication rule enforced (matching PutObject lands in destination bucket)", replicated === "replicate me", replicated);
  await shot("05d-s3-replication-created");

  // Bucket list shows it
  await page.goto(UI + "#/s3");
  // The list paginates (as the native console does), so find it the way a user would.
  await page.getByPlaceholder("Find buckets by name").fill(B);
  await page.getByRole("link", { name: B }).waitFor({ timeout: 10000 });
  await shot("06-s3-buckets");
  check("S3 bucket list shows new bucket", true);

  // DynamoDB: create table via UI
  await page.goto(UI + "#/dynamodb/create-table");
  await page.getByLabel("Table name").fill(T);
  await page.getByRole("textbox", { name: "Partition key", exact: true }).fill("pk");
  await shot("07-ddb-create-filled");
  await page.getByRole("button", { name: "Create table" }).last().click();
  await page.getByPlaceholder("Find tables by table name").fill(T);   // the list paginates
  await page.getByRole("link", { name: T }).waitFor({ timeout: 10000 });
  const tables = await ddb("ListTables", {});
  check("DynamoDB create table → visible over native wire", (tables.TableNames || []).includes(T));
  await shot("08-ddb-tables");

  // Item created over the wire shows in Explore items (CLI → UI direction)
  await ddb("PutItem", { TableName: T, Item: { pk: { S: "order-1" }, total: { N: "42" } } });
  await page.goto(UI + `#/dynamodb/tables/${T}/items`);
  await page.getByText("order-1").first().waitFor({ timeout: 10000 });
  check("DynamoDB item put over wire → shown in Explore items", true);
  await shot("09-ddb-items");
  await page.goto(UI + `#/dynamodb/tables/${T}`);
  await page.getByRole("tab", { name: "Overview" }).waitFor();
  await shot("10-ddb-overview");

  // PartiQL editor: INSERT through the UI, verify over the wire (UI → CLI direction)
  await page.goto(UI + "#/dynamodb/partiql");
  await page.getByLabel("PartiQL").fill(`INSERT INTO "${T}" VALUE {'pk': 'partiql-1', 'total': 7}`);
  await page.getByRole("button", { name: "Run" }).click();
  await page.waitForTimeout(800);
  const got = await ddb("GetItem", { TableName: T, Key: { pk: { S: "partiql-1" } } });
  check("DynamoDB PartiQL INSERT (UI) → readable over native wire", got.Item?.total?.N === "7", JSON.stringify(got));
  await shot("11-ddb-partiql");

  // Backups: create on-demand backup through the UI, verify over the wire (CLI direction)
  await page.goto(UI + "#/dynamodb/backups");
  await page.getByRole("button", { name: "Create backup" }).first().click();
  await page.getByLabel("Source table").first().click();
  await page.getByRole("option", { name: T }).click();
  await page.getByRole("button", { name: "Create backup" }).last().click();
  await page.waitForTimeout(800);
  const backups = await ddb("ListBackups", { TableName: T });
  check("DynamoDB create backup (UI) → visible over native wire", (backups.BackupSummaries || []).some((b) => b.TableName === T), JSON.stringify(backups));
  await shot("12-ddb-backups");

  // Exports to S3: real backend (DEPTH wave 5) — export the table through the UI, verify
  // the actual DynamoDB-JSON bytes landed in the destination S3 bucket (UI → wire direction)
  const EXB = `v4-ddbexport-${Date.now() % 100000}`;
  await wire(`/${EXB}`, { method: "PUT", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0" } });
  await page.goto(UI + "#/dynamodb/exports");
  await page.getByRole("link", { name: "Export to S3" }).click();
  await page.getByLabel("Source table").first().click();
  await page.getByRole("option", { name: T }).click();
  await page.getByLabel("Destination S3 bucket").fill(`s3://${EXB}/nightly`);
  await page.getByRole("button", { name: "Export" }).last().click();
  await page.getByPlaceholder("Find exports").fill(EXB).catch(() => {});
  await page.getByText(EXB).first().waitFor({ timeout: 10000 });
  const ddbExports = await ddb("ListExports", { TableName: T });
  const ddbExp = (ddbExports.ExportSummaries || [])[0];
  check("DynamoDB export table (UI) → COMPLETED over native wire", ddbExp?.ExportStatus === "COMPLETED", JSON.stringify(ddbExports));
  const exportListing = await wire(`/${EXB}?prefix=nightly/`);
  check("DynamoDB export table (UI) → real data file landed in the destination bucket", /data\/1\.json/.test(exportListing), exportListing.slice(0, 300));
  await shot("12b-ddb-exports");

  // Local secondary index: create a table with a sort key + LSI through the UI, verify over the wire
  await page.goto(UI + "#/dynamodb/create-table");
  await page.getByLabel("Table name").fill(T2);
  await page.getByRole("textbox", { name: "Partition key", exact: true }).fill("cust");
  await page.getByRole("textbox", { name: "Sort key - optional", exact: true }).fill("id");
  await page.getByRole("radio", { name: "Customize settings" }).check();
  await page.getByRole("button", { name: "Create local index" }).first().click();
  const lsiDialog = page.getByRole("dialog", { name: "Create local index" });
  await lsiDialog.getByLabel("Index name").fill("by-status");
  await lsiDialog.getByRole("textbox", { name: "Sort key", exact: true }).fill("status");
  await lsiDialog.getByRole("button", { name: "Create local index" }).click();
  await page.getByRole("button", { name: "Create table" }).last().click();
  await page.getByPlaceholder("Find tables by table name").fill(T2);
  await page.getByRole("link", { name: T2 }).waitFor({ timeout: 10000 });
  const t2 = await ddb("DescribeTable", { TableName: T2 });
  check("DynamoDB local secondary index (UI) → visible over native wire",
        (t2.Table?.LocalSecondaryIndexes || []).some((l) => l.IndexName === "by-status"), JSON.stringify(t2.Table?.LocalSecondaryIndexes));
  await page.goto(UI + `#/dynamodb/tables/${T2}`);
  await page.getByRole("tab", { name: "Indexes" }).click();
  await page.getByText("by-status").first().waitFor({ timeout: 10000 });
  check("DynamoDB local secondary index → shown on table detail Indexes tab", true);
  await shot("12b-ddb-lsi");

  // KMS: create a customer managed key through the wizard (UI → CLI direction)
  const K = `v4smoke-key-${Date.now() % 100000}`;
  await page.goto(UI + "#/kms/create-key");
  await page.getByRole("radio", { name: "Asymmetric", exact: true }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Alias", { exact: true }).fill(K);
  for (let i = 0; i < 4; i++) await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Finish" }).click();
  await page.getByRole("heading", { level: 1 }).filter({ hasText: /^[0-9a-f]{32}$/ }).waitFor({ timeout: 10000 });
  const aliases = await kms("ListAliases", {});
  const createdAlias = (aliases.Aliases || []).find((a) => a.AliasName === `alias/${K}`);
  check("KMS create key (UI wizard) → visible over native wire", !!createdAlias, JSON.stringify(aliases.Aliases?.slice(-1)));
  const createdMd = createdAlias && (await kms("DescribeKey", { KeyId: createdAlias.TargetKeyId })).KeyMetadata;
  check("KMS created key is asymmetric (RSA/ECC) as configured in the wizard", /^(RSA_|ECC_)/.test(createdMd?.KeySpec || ""), createdMd?.KeySpec);
  await shot("13-kms-key-detail");

  // KMS: Encrypt against an unseen alias/aws/<service> over the wire auto-provisions the
  // AWS-managed key (CLI → UI direction) — the AWS-managed-key liveness goal.
  const svc = `v4smokesvc${Date.now() % 100000}`;
  await kms("Encrypt", { KeyId: `alias/aws/${svc}`, Plaintext: Buffer.from("x").toString("base64") });
  await page.goto(UI + "#/kms/aws-managed-keys");
  await page.getByPlaceholder("Filter keys by properties or tags").fill(`aws/${svc}`);   // the list paginates
  await page.getByText(`aws/${svc}`).waitFor({ timeout: 10000 });
  check("KMS Encrypt over wire against an unseen aws/ alias → AWS managed key shown in UI", true);
  await shot("14-kms-aws-managed-keys");

  // Secrets Manager: store a secret through the UI wizard (UI → CLI direction)
  const S = `v4smoke-secret-${Date.now() % 100000}`;
  await page.goto(UI + "#/secretsmanager/newsecret");
  await page.getByRole("radio", { name: "Other type of secret", exact: true }).check();
  await page.getByRole("button", { name: "Plaintext", exact: true }).click();
  await page.getByRole("textbox", { name: "Plaintext", exact: true }).fill("v4-smoke-value");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Secret name", { exact: true }).fill(S);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Store" }).click();
  await page.getByRole("heading", { name: S }).waitFor({ timeout: 10000 });
  const storedVal = await sm("GetSecretValue", { SecretId: S });
  check("Secrets Manager store secret (UI wizard) → readable over native wire", storedVal.SecretString === "v4-smoke-value", JSON.stringify(storedVal));
  await shot("15-secretsmanager-detail");

  // Secrets Manager: CreateSecret over the wire → shown in the Secrets list (CLI → UI direction)
  const S2 = `v4smoke-secret2-${Date.now() % 100000}`;
  await sm("CreateSecret", { Name: S2, SecretString: "v4-smoke-wire" });
  await page.goto(UI + "#/secretsmanager/listsecrets");
  await page.getByPlaceholder(/^Filter secrets by name/).fill(S2);   // the list paginates
  await page.getByText(S2).first().waitFor({ timeout: 10000 });
  check("Secrets Manager CreateSecret over wire → shown in Secrets list", true);
  await shot("16-secretsmanager-list");

  // Secrets Manager (DEPTH): a schedule really fires on its own — RotateSecret over the
  // wire schedules an already-due rotation (RotateImmediately false), then just loading the
  // UI detail page (DescribeSecret) lazily fires it, no Lambda/scheduler involved.
  const S3 = `v4smoke-secret3-${Date.now() % 100000}`;
  await sm("CreateSecret", { Name: S3, SecretString: "v4-smoke-rotate" });
  await sm("RotateSecret", { SecretId: S3, RotationRules: { AutomaticallyAfterDays: 0 }, RotateImmediately: false });
  const beforeAutoRotate = await sm("ListSecretVersionIds", { SecretId: S3 });
  await page.goto(UI + `#/secretsmanager/secret/${S3}`);
  await page.getByRole("heading", { name: S3 }).waitFor({ timeout: 10000 });
  const afterAutoRotate = await sm("ListSecretVersionIds", { SecretId: S3 });
  check("Secrets Manager: loading the detail page lazily fires a due rotation schedule",
    afterAutoRotate.Versions.length === beforeAutoRotate.Versions.length + 1,
    JSON.stringify({ before: beforeAutoRotate.Versions.length, after: afterAutoRotate.Versions.length }));

  // Secrets Manager (DEPTH): Resource permissions on an EXISTING secret is a real editor now
  // (Overview tab), not a blanket "not simulated" panel — Edit permissions → Save round-trips
  // through PutResourcePolicy over the native wire.
  const policyText = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow",
    Principal: { AWS: "arn:aws:iam::123456789012:root" }, Action: "secretsmanager:GetSecretValue", Resource: "*" }] });
  await page.getByRole("button", { name: "Edit permissions" }).click();
  await page.getByLabel("Resource policy", { exact: true }).fill(policyText);
  const putPolicyResp = page.waitForResponse((r) => /PutResourcePolicy$/.test(r.request().headers()["x-amz-target"] || ""), { timeout: 15000 });
  await page.getByRole("button", { name: "Save changes" }).click();
  await putPolicyResp;
  await page.getByRole("button", { name: "Edit permissions" }).waitFor({ timeout: 10000 });
  const putPolicy = await sm("GetResourcePolicy", { SecretId: S3 });
  check("Secrets Manager: detail page Resource permissions editor → PutResourcePolicy over native wire",
    putPolicy.ResourcePolicy === policyText, JSON.stringify(putPolicy));
  await shot("16b-secretsmanager-rotation-policy");

  // Secrets Manager (DEPTH wave 5): a customer KMS key really encrypts the secret —
  // create a CMK + alias over the wire, pick it in the Store-a-secret wizard, confirm the
  // value still round-trips, then prove it's genuinely encrypted under that key (not just
  // labeled with it) by disabling the key and watching GetSecretValue fail over the wire.
  const kmsAlias = `v4smoke-sm-cmk-${Date.now() % 100000}`;
  const smKeyId = (await kms("CreateKey", {})).KeyMetadata.KeyId;
  await kms("CreateAlias", { AliasName: `alias/${kmsAlias}`, TargetKeyId: smKeyId });
  const S4 = `v4smoke-secret4-${Date.now() % 100000}`;
  await page.goto(UI + "#/secretsmanager/newsecret");
  await page.getByRole("radio", { name: "Other type of secret", exact: true }).check();
  await page.getByRole("button", { name: "Plaintext", exact: true }).click();
  await page.getByRole("textbox", { name: "Plaintext", exact: true }).fill("v4-smoke-cmk-value");
  await page.getByLabel("Encryption key", { exact: true }).click();
  await page.getByRole("option", { name: kmsAlias }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Secret name", { exact: true }).fill(S4);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Store" }).click();
  await page.getByRole("heading", { name: S4 }).waitFor({ timeout: 10000 });
  const cmkVal = await sm("GetSecretValue", { SecretId: S4 });
  check("Secrets Manager: CMK-encrypted secret (UI wizard) → readable over native wire",
    cmkVal.SecretString === "v4-smoke-cmk-value", JSON.stringify(cmkVal));
  await kms("DisableKey", { KeyId: smKeyId });
  const blockedCmk = await sm("GetSecretValue", { SecretId: S4 });
  check("Secrets Manager: disabling the CMK really blocks GetSecretValue over native wire",
    blockedCmk.__type === "InvalidRequestException", JSON.stringify(blockedCmk));
  await shot("16c-secretsmanager-cmk-encryption");

  // SQS: create a queue through the UI, verify over native wire (UI → CLI direction)
  const Q = `v4smoke-queue-${Date.now() % 100000}`;
  await page.goto(UI + "#/sqs/create-queue");
  await page.getByLabel("Name", { exact: true }).fill(Q);
  await page.getByRole("button", { name: "Create queue" }).last().click();
  await page.getByRole("heading", { name: Q }).waitFor({ timeout: 10000 });
  const queues = await sqs("ListQueues", {});
  check("SQS create queue (UI) → visible over native wire", (queues.QueueUrls || []).some((u) => u.endsWith(`/${Q}`)), JSON.stringify(queues));
  await shot("15-sqs-queue-detail");

  // SQS: send a message over the wire (CLI direction), poll for it in the UI (CLI → UI direction)
  const qUrl = (await sqs("GetQueueUrl", { QueueName: Q })).QueueUrl;
  await sqs("SendMessage", { QueueUrl: qUrl, MessageBody: `v4smoke-msg-${Date.now() % 100000}` });
  await page.goto(UI + `#/sqs/queues/${Q}/send-receive`);
  await page.getByRole("button", { name: "Poll for messages" }).click();
  await page.waitForTimeout(800);
  const afterPoll = await sqs("GetQueueAttributes", { QueueUrl: qUrl, AttributeNames: ["All"] });
  check("SQS SendMessage over wire → received via UI poll (now in-flight)", afterPoll.Attributes?.ApproximateNumberOfMessagesNotVisible === "1", JSON.stringify(afterPoll.Attributes));
  await shot("16-sqs-send-receive");

  // SQS: dead-letter a message onto a DLQ over the wire (maxReceiveCount redrive), then
  // redrive it back to its source queue through the console's "Dead-letter queue redrive
  // tasks" tab (StartMessageMoveTask) — verify the move really happened over the native wire.
  const RDLQ = `v4smoke-redrive-dlq-${Date.now() % 100000}`;
  const RMAIN = `v4smoke-redrive-main-${Date.now() % 100000}`;
  const rdlqUrl = (await sqs("CreateQueue", { QueueName: RDLQ })).QueueUrl;
  const rdlqArn = (await sqs("GetQueueAttributes", { QueueUrl: rdlqUrl, AttributeNames: ["QueueArn"] })).Attributes.QueueArn;
  const rmainUrl = (await sqs("CreateQueue", { QueueName: RMAIN, Attributes: {
    VisibilityTimeout: "1", RedrivePolicy: JSON.stringify({ deadLetterTargetArn: rdlqArn, maxReceiveCount: 1 }) } })).QueueUrl;
  await sqs("SendMessage", { QueueUrl: rmainUrl, MessageBody: "poison-for-redrive" });
  await sqs("ReceiveMessage", { QueueUrl: rmainUrl, MaxNumberOfMessages: 1 });
  await page.waitForTimeout(1500);   // let the 1s visibility timeout lapse
  await sqs("ReceiveMessage", { QueueUrl: rmainUrl, MaxNumberOfMessages: 1 });   // triggers the redrive
  const beforeRedrive = await sqs("GetQueueAttributes", { QueueUrl: rdlqUrl, AttributeNames: ["ApproximateNumberOfMessages"] });
  check("SQS poison message landed on the DLQ after maxReceiveCount", beforeRedrive.Attributes?.ApproximateNumberOfMessages === "1", JSON.stringify(beforeRedrive.Attributes));

  await page.goto(UI + `#/sqs/queues/${RDLQ}?tab=redrive-tasks`);
  await page.getByRole("tabpanel").getByRole("button", { name: "Start DLQ redrive" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Start DLQ redrive" }).click();
  await page.waitForTimeout(800);
  const afterRedrive = await sqs("GetQueueAttributes", { QueueUrl: rdlqUrl, AttributeNames: ["ApproximateNumberOfMessages"] });
  const backOnMain = await sqs("ReceiveMessage", { QueueUrl: rmainUrl, MaxNumberOfMessages: 1 });
  check("SQS Start DLQ redrive (UI) → DLQ emptied and message moved back to its source queue over native wire",
    afterRedrive.Attributes?.ApproximateNumberOfMessages === "0" && (backOnMain.Messages || [])[0]?.Body === "poison-for-redrive",
    JSON.stringify({ afterRedrive: afterRedrive.Attributes, backOnMain }));
  await shot("17-sqs-dlq-redrive");

  // SNS: create a topic through the UI, subscribe an SQS queue through the UI, publish
  // through the UI — then verify the queue really received the fanned-out notification
  // over the native wire (the P2 queue's mandatory real SNS→SQS fan-out).
  const SN = `v4smoke-topic-${Date.now() % 100000}`;
  const SQ = `v4smoke-sns-queue-${Date.now() % 100000}`;
  const q = await sqs("CreateQueue", { QueueName: SQ });
  const qAttrs = await sqs("GetQueueAttributes", { QueueUrl: q.QueueUrl, AttributeNames: ["QueueArn"] });
  const queueArn = qAttrs.Attributes.QueueArn;

  await page.goto(UI + "#/sns/create-topic");
  await page.getByLabel("Name", { exact: true }).fill(SN);
  await page.getByRole("button", { name: "Create topic" }).click();
  await page.getByRole("heading", { name: SN }).first().waitFor({ timeout: 10000 });
  const topicsXml = await sns("ListTopics", {});
  check("SNS create topic (UI) → visible over native wire", topicsXml.includes(`:${SN}</TopicArn>`));
  await shot("15-sns-topic-detail");

  await page.goto(UI + `#/sns/create-subscription?topic=${encodeURIComponent(SN)}`);
  await page.getByLabel("Protocol", { exact: true }).click();
  await page.getByRole("option", { name: "Amazon SQS" }).click();
  await page.getByLabel("Endpoint", { exact: true }).fill(queueArn);
  await page.getByRole("button", { name: "Create subscription" }).click();
  await page.getByRole("heading", { name: /^Subscription:/ }).waitFor({ timeout: 10000 });
  await shot("16-sns-subscription-detail");

  await page.goto(UI + `#/sns/topics/${SN}/publish`);
  await page.getByLabel("Message body to send to the endpoint", { exact: true }).fill("hello from v4 smoke");
  await page.getByRole("button", { name: "Publish message" }).click();
  await page.getByRole("heading", { name: SN }).first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(500);
  const received = await sqs("ReceiveMessage", { QueueUrl: q.QueueUrl, MaxNumberOfMessages: 1 });
  const fanned = (received.Messages || [])[0]?.Body || "";
  check("SNS Publish (UI) → fanned out to the subscribed SQS queue over native wire", fanned.includes("hello from v4 smoke"), fanned.slice(0, 160));
  await shot("17-sns-fanout-sqs");

  // API Gateway: create a REST API through the UI (UI → CLI direction)
  const G = `v4smoke-api-${Date.now() % 100000}`;
  await page.goto(UI + "#/apigateway/create-rest-api");
  await page.getByLabel("API name", { exact: true }).fill(G);
  await page.getByRole("button", { name: "Create API" }).click();
  await page.getByRole("heading", { level: 1, name: G }).waitFor({ timeout: 10000 });
  const gwAuth = { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/apigateway/aws4_request, SignedHeaders=host, Signature=0" };
  const restApis = JSON.parse(await wire("/restapis", { headers: gwAuth }));
  const createdApi = (restApis.item || []).find((a) => a.name === G);
  check("API Gateway create REST API (UI) → visible over native wire", !!createdApi, JSON.stringify(restApis.item?.slice(-1)));
  await shot("15-apigateway-rest-api");

  // API Gateway: create an HTTP API over the wire (CLI → UI direction)
  const H = `v4smoke-http-${Date.now() % 100000}`;
  await page.evaluate(([u, a, name]) => fetch(u, { method: "POST", headers: { ...a, "content-type": "application/json" }, body: JSON.stringify({ name, protocolType: "HTTP" }) }),
    [WIRE + "/v2/apis", gwAuth, H]);
  await page.goto(UI + "#/apigateway/apis");
  await page.getByText(H).waitFor({ timeout: 10000 });
  check("API Gateway create HTTP API (wire) → shown in UI APIs list", true);
  await shot("16-apigateway-apis-list");

  // EventBridge: create a rule + SQS target through the UI (UI → CLI direction), then
  // PutEvents over the wire and confirm it was really delivered (not a log line).
  const EBQ = `v4smoke-eb-q-${Date.now() % 100000}`;
  const ebQueueUrl = (await sqs("CreateQueue", { QueueName: EBQ })).QueueUrl;
  const R = `v4smoke-rule-${Date.now() % 100000}`;
  await page.goto(UI + "#/eventbridge/create-rule");
  await page.getByRole("tab", { name: "Build" }).click();
  await page.getByRole("button", { name: "Add target" }).click();
  await page.getByLabel("Select a target 1").first().click();
  await page.getByRole("option", { name: new RegExp(`SQS queue: ${EBQ}$`) }).click();
  await page.getByRole("tab", { name: "Configure" }).click();
  await page.getByLabel("Rule name").fill(R);
  await page.getByRole("button", { name: "Create rule" }).click();
  await page.getByRole("heading", { name: "Rules", level: 1 }).waitFor({ timeout: 10000 });
  const rules = await events("ListRules", { EventBusName: "default" });
  check("EventBridge create rule (UI) → visible over native wire", (rules.Rules || []).some((r) => r.Name === R), JSON.stringify(rules.Rules?.slice(-1)));
  const ebTargets = await events("ListTargetsByRule", { Rule: R, EventBusName: "default" });
  check("EventBridge rule's SQS target attached (UI) → visible over native wire", (ebTargets.Targets || []).some((t) => t.Arn.endsWith(`:${EBQ}`)), JSON.stringify(ebTargets));
  await shot("17-eventbridge-create-rule");

  // PutEvents over the wire (CLI direction) must really deliver to the UI-created rule's target.
  await events("PutEvents", { Entries: [{ Source: "my.app", DetailType: "x", Detail: "{}", EventBusName: "default" }] });
  const ebMsgs = await sqs("ReceiveMessage", { QueueUrl: ebQueueUrl, MaxNumberOfMessages: 10 });
  check("EventBridge PutEvents over wire → really delivered to the UI-created rule's SQS target", (ebMsgs.Messages || []).length > 0, JSON.stringify(ebMsgs));

  // EventBridge: Step Functions + Kinesis targets — the depth-pass addition beyond the
  // SQS/SNS/Lambda targets proven above. A second rule, built entirely through the UI,
  // with both target types; PutEvents over the wire must really invoke both.
  const EBSTREAM = `v4smoke-eb-stream-${Date.now() % 100000}`;
  await kinesis("CreateStream", { StreamName: EBSTREAM, ShardCount: 1 });
  const EBSM = `v4smoke-eb-sm-${Date.now() % 100000}`;
  const smDef = JSON.stringify({ StartAt: "Pass", States: { Pass: { Type: "Pass", End: true } } });
  const smCreated = await sfn("CreateStateMachine", { name: EBSM, roleArn: "arn:aws:iam::000000000000:role/smoke", definition: smDef });
  const smArn = smCreated.stateMachineArn;
  const R2 = `v4smoke-rule2-${Date.now() % 100000}`;
  await page.goto(UI + "#/eventbridge/create-rule");
  await page.getByRole("tab", { name: "Build" }).click();
  await page.getByRole("button", { name: "Add target" }).click();
  await page.getByLabel("Select a target 1").first().click();
  await page.getByRole("option", { name: new RegExp(`Kinesis stream: ${EBSTREAM}$`) }).click();
  await page.getByRole("button", { name: "Add target" }).click();
  await page.getByLabel("Select a target 2").first().click();
  await page.getByRole("option", { name: new RegExp(`Step Functions state machine: ${EBSM}$`) }).click();
  await page.getByRole("tab", { name: "Configure" }).click();
  await page.getByLabel("Rule name").fill(R2);
  await page.getByRole("button", { name: "Create rule" }).click();
  await page.getByRole("heading", { name: "Rules", level: 1 }).waitFor({ timeout: 10000 });
  const ebTargets2 = await events("ListTargetsByRule", { Rule: R2, EventBusName: "default" });
  check("EventBridge rule's Step Functions + Kinesis targets attached (UI) → visible over native wire",
    (ebTargets2.Targets || []).some((t) => t.Arn.endsWith(`stream/${EBSTREAM}`)) && (ebTargets2.Targets || []).some((t) => t.Arn === smArn),
    JSON.stringify(ebTargets2));
  await events("PutEvents", { Entries: [{ Source: "my.app", DetailType: "x", Detail: "{}", EventBusName: "default" }] });
  const ebShards = await kinesis("ListShards", { StreamName: EBSTREAM });
  const ebIter = (await kinesis("GetShardIterator", { StreamName: EBSTREAM, ShardId: ebShards.Shards[0].ShardId, ShardIteratorType: "TRIM_HORIZON" })).ShardIterator;
  const ebKinRecs = await kinesis("GetRecords", { ShardIterator: ebIter });
  check("EventBridge PutEvents over wire → really delivered to the UI-created rule's Kinesis target", (ebKinRecs.Records || []).length > 0, JSON.stringify(ebKinRecs));
  const ebExecs = await sfn("ListExecutions", { stateMachineArn: smArn });
  check("EventBridge PutEvents over wire → really started a Step Functions execution on the UI-created rule's target", (ebExecs.executions || []).length > 0, JSON.stringify(ebExecs));

  // Custom event bus created over the wire (CLI direction) must show up in the UI (wire → UI).
  const EBUS = `v4smoke-bus-${Date.now() % 100000}`;
  await events("CreateEventBus", { Name: EBUS });
  await page.goto(UI + "#/eventbridge/event-buses");
  await page.getByText(EBUS).first().waitFor({ timeout: 10000 });
  check("EventBridge CreateEventBus over wire → shown in UI (CLI → UI direction)", true);
  await shot("18-eventbridge-event-buses");

  // EventBridge Scheduler: create a one-time schedule due in the past through the UI
  // (UI → CLI direction). Vyomi has no background timer — the schedule fires the next
  // time the Scheduler API is polled, which the Schedules list's own GET does on load.
  const SCHEDQ = `v4smoke-sched-q-${Date.now() % 100000}`;
  const schedQueueUrl = (await sqs("CreateQueue", { QueueName: SCHEDQ })).QueueUrl;
  const SCH = `v4smoke-schedule-${Date.now() % 100000}`;
  const dueAt = new Date(Date.now() - 5 * 60000).toISOString().slice(0, 19);
  await page.goto(UI + "#/eventbridge/create-schedule");
  await page.getByLabel("Schedule name").fill(SCH);
  await page.getByRole("radio", { name: "One-time schedule" }).check();
  await page.getByLabel("Date and time").fill(dueAt);
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Target API").first().click();
  await page.getByRole("option", { name: new RegExp(`SQS queue: ${SCHEDQ}$`) }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Submit" }).click();
  await page.getByRole("heading", { name: "Schedules", level: 1 }).waitFor({ timeout: 10000 });
  const scheds = await scheduler("GET", "/schedules?GroupName=default");
  check("Scheduler create schedule (UI) → visible over native wire", (scheds.Schedules || []).some((s) => s.Name === SCH), JSON.stringify(scheds.Schedules?.slice(-1)));
  await shot("18b-eventbridge-schedule-created");
  const schedMsgs = await sqs("ReceiveMessage", { QueueUrl: schedQueueUrl, MaxNumberOfMessages: 10 });
  check("Scheduler due schedule fires on next poll (UI list's own GET) → delivered to its SQS target", (schedMsgs.Messages || []).length > 0, JSON.stringify(schedMsgs));

  // Lambda: create a function through the UI (UI → CLI direction), invoke it for real via
  // the Test tab, then prove a function created directly over the wire (CLI → UI direction)
  // shows up in the Functions list.
  const FN = `v4smoke-fn-${Date.now() % 100000}`;
  await page.goto(UI + "#/lambda/create/function");
  await page.getByLabel("Function name").fill(FN);
  await page.getByRole("button", { name: "Create Event Function" }).last().click();
  await page.getByRole("heading", { name: FN }).waitFor({ timeout: 10000 });
  const fns = await lam("GET", "/2015-03-31/functions");
  check("Lambda create function (UI) → visible over native wire", (fns.Functions || []).some((f) => f.FunctionName === FN));
  await shot("15-lambda-create");

  await page.getByRole("tab", { name: "Test" }).click();
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await page.getByText("Execution result").waitFor({ timeout: 10000 });
  await shot("16-lambda-test");
  const inv = await lam("GET", `/2015-03-31/functions/${FN}/invocations`);
  check("Lambda Test tab Invoke (UI) → recorded over native wire", (inv.Metrics?.Invocations || 0) >= 1, JSON.stringify(inv.Metrics));

  const FN2 = `v4smoke-fn2-${Date.now() % 100000}`;
  await lam("POST", "/2015-03-31/functions", { FunctionName: FN2, Runtime: "python3.12", Code: { Source: "def handler(e,c):\n    return {'ok': True}\n" } });
  await page.goto(UI + "#/lambda/functions");
  await page.getByPlaceholder("Search by attributes or search by keyword").fill(FN2);
  await page.getByRole("link", { name: FN2 }).waitFor({ timeout: 10000 });
  check("Lambda function created over wire (CLI) → shown in Functions list", true);
  await shot("17-lambda-functions");

  // Lambda: an async (Event) Test invoke really delivers to the function's configured
  // OnSuccess destination — the "Asynchronous" radio used to be wired to nothing.
  const DESTQ = `v4smoke-lambda-dest-${Date.now() % 100000}`;
  const destQ = await sqs("CreateQueue", { QueueName: DESTQ });
  const destAttrs = await sqs("GetQueueAttributes", { QueueUrl: destQ.QueueUrl });
  await lam("PUT", `/2015-03-31/functions/${FN2}/event-invoke-config`,
    { DestinationConfig: { OnSuccess: { Destination: destAttrs.Attributes.QueueArn } } });
  await page.goto(UI + `#/lambda/functions/${FN2}`);
  await page.getByRole("tab", { name: "Test" }).click();
  await page.getByRole("radio", { name: "Asynchronous" }).check();
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await page.getByText("Asynchronous invocation accepted").first().waitFor({ timeout: 10000 });
  // async really is async offline (the function runs off the request) — poll like a consumer would
  let destMsgs = {};
  for (let i = 0; i < 20 && !(destMsgs.Messages || []).length; i++) {
    if (i) await page.waitForTimeout(500);
    destMsgs = await sqs("ReceiveMessage", { QueueUrl: destQ.QueueUrl, MaxNumberOfMessages: 10 });
  }
  check("Lambda async Test invoke (UI) → really delivered to the OnSuccess destination over the wire",
    (destMsgs.Messages || []).length > 0, JSON.stringify(destMsgs));
  await shot("17b-lambda-async-destination");
  // RDS: create a database through the UI (UI → CLI direction)
  const RDB = `v4smoke-db-${Date.now() % 100000}`;
  await page.goto(UI + "#/rds/create-database");
  await page.getByRole("radio", { name: "PostgreSQL", exact: true }).check();
  await page.getByLabel("DB instance identifier").fill(RDB);
  await page.getByLabel("Master username").fill("admin");
  await page.getByRole("button", { name: "Create database" }).last().click();
  await page.getByRole("heading", { name: RDB }).waitFor({ timeout: 10000 });
  const desc = await rds("DescribeDBInstances", { DBInstanceIdentifier: RDB });
  check("RDS create database (UI) → visible over native wire", desc.includes(`<DBInstanceIdentifier>${RDB}</DBInstanceIdentifier>`), desc.slice(0, 160));
  await shot("15-rds-database-detail");

  // RDS: a snapshot created over the wire shows in the console (CLI → UI direction)
  const SNAP = `${RDB}-snap`;
  await rds("CreateDBSnapshot", { DBInstanceIdentifier: RDB, DBSnapshotIdentifier: SNAP });
  await page.goto(UI + "#/rds/snapshots");
  await page.getByText(SNAP).first().waitFor({ timeout: 10000 });
  check("RDS snapshot created over wire → shown in Snapshots list", true);
  await shot("16-rds-snapshots");
  // IAM: create a user through the 3-step wizard (UI → CLI direction)
  const U = `v4smoke-user-${Date.now() % 100000}`;
  await page.goto(UI + "#/iam/create-user");
  await page.getByLabel("User name").fill(U);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Create user" }).last().click();
  await page.getByRole("heading", { name: U }).waitFor({ timeout: 10000 });
  const usersXml = await iamXml({ Action: "ListUsers" });
  check("IAM create user (UI wizard) → visible over native wire", usersXml.includes(`<UserName>${U}</UserName>`), usersXml.slice(0, 200));
  await shot("15-iam-user-detail");

  // IAM: role created over the wire shows in the Roles list (CLI → UI direction)
  const ROLE = `v4smoke-role-${Date.now() % 100000}`;
  await iamXml({ Action: "CreateRole", RoleName: ROLE, AssumeRolePolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: "ec2.amazonaws.com" }, Action: "sts:AssumeRole" }] }) });
  await page.goto(UI + "#/iam/roles");
  await page.getByText(ROLE).first().waitFor({ timeout: 10000 });
  check("IAM role created over wire → shown in Roles list", true);
  await shot("17-iam-roles");

  // IAM: assign a virtual MFA device to the smoke user through the console wizard,
  // verify it shows over the native wire (UI → CLI direction). MFA codes are
  // format-checked, not cryptographically verified (core/iam_core.py _check_mfa_codes).
  const MFA = `v4smoke-mfa-${Date.now() % 100000}`;
  await page.goto(UI + `#/iam/users/${U}`);
  await page.getByRole("tab", { name: "Security credentials" }).click();
  await page.getByRole("button", { name: "Assign MFA device" }).click();
  await page.getByLabel("Device name").fill(MFA);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("MFA code 1").fill("111111");
  await page.getByLabel("MFA code 2").fill("222222");
  await page.getByRole("button", { name: "Assign MFA", exact: true }).click();
  await page.getByText(`mfa/${MFA}`).waitFor({ timeout: 10000 });
  const mfaXml = await iamXml({ Action: "ListMFADevices", UserName: U });
  check("IAM assign MFA device (UI) → visible over native wire", mfaXml.includes(`mfa/${MFA}`), mfaXml.slice(0, 200));
  await shot("17b-iam-user-mfa");

  // EC2: launch an instance through the wizard (UI → CLI direction)
  const EN = `v4-smoke-instance-${Date.now() % 100000}`;
  await page.goto(UI + "#/ec2/launch-instance");
  await page.getByLabel("Name", { exact: true }).fill(EN);
  await page.getByRole("button", { name: "Launch instance", exact: true }).click();
  await page.getByRole("heading", { name: "Instances" }).first().waitFor({ timeout: 10000 });
  const described = await ec2("DescribeInstances", {});
  const nameIdx = described.indexOf(`<value>${EN}</value>`);
  check("EC2 launch instance (UI wizard) → visible over native wire", nameIdx >= 0, described.slice(0, 200));
  const before = described.slice(0, nameIdx);
  const instanceId = nameIdx >= 0 ? xtag(before.slice(before.lastIndexOf("<instanceId>")), "instanceId") : null;
  await shot("15-ec2-instances");

  // EC2 monitoring/alarms: visiting "Status and alarms" polls DescribeInstanceStatus, which
  // really publishes a StatusCheckFailed datapoint into CloudWatch (UI → CLI direction).
  if (instanceId) {
    await page.goto(UI + `#/ec2/instances/${instanceId}`);
    await page.getByRole("tab", { name: "Status and alarms" }).click();
    await page.getByText("2/2 checks passed").first().waitFor({ timeout: 10000 });
    const end = new Date(), start = new Date(end - 30 * 60_000);
    const stats = await cw("GetMetricStatistics", {
      Namespace: "AWS/EC2", MetricName: "StatusCheckFailed", Dimensions: [{ Name: "InstanceId", Value: instanceId }],
      StartTime: start.toISOString(), EndTime: end.toISOString(), Period: 60, Statistics: ["Maximum"],
    });
    check("EC2 Status and alarms tab (UI) → real StatusCheckFailed datapoint over native CloudWatch wire",
          (stats.Datapoints || []).some((d) => d.Maximum === 0), JSON.stringify(stats).slice(0, 200));

    // EC2 monitoring/alarms: an alarm on that same metric, created over the wire, shows up in
    // the instance's Alarms table (CLI → UI direction).
    const ALM = `v4-smoke-ec2-alarm-${Date.now() % 100000}`;
    await cw("PutMetricAlarm", {
      AlarmName: ALM, Namespace: "AWS/EC2", MetricName: "StatusCheckFailed", Dimensions: [{ Name: "InstanceId", Value: instanceId }],
      Statistic: "Maximum", Period: 60, EvaluationPeriods: 1, Threshold: 1, ComparisonOperator: "GreaterThanOrEqualToThreshold",
    });
    await page.reload({ waitUntil: "load" });
    await page.getByRole("tab", { name: "Status and alarms" }).click();
    await page.getByText(ALM).waitFor({ timeout: 10000 });
    check("EC2 status-check alarm created over wire → shown in instance's Alarms table", true, ALM);
    await shot("15b-ec2-alarms");
    await cw("DeleteAlarms", { AlarmNames: [ALM] });
  }

  // EC2: create a security group over the wire, verify it shows up in the UI (CLI → UI direction)
  const SG = `v4-smoke-sg-${Date.now() % 100000}`;
  const sgCreated = await ec2("CreateSecurityGroup", { GroupName: SG, GroupDescription: "v4 smoke test" });
  const sgId = xtag(sgCreated, "groupId");
  await page.goto(UI + "#/ec2/security-groups");
  await page.getByPlaceholder("Find security groups by attribute or tag").fill(sgId);
  await page.getByText(sgId).waitFor({ timeout: 10000 });
  check("EC2 create security group over wire → visible in UI", true, sgId);
  await shot("16-ec2-security-groups");

  // EC2: launch template created over the wire, a new version created through the UI's
  // "Manage versions" modal (UI → CLI direction), verified back over the native wire.
  const LTN = `v4-smoke-lt-${Date.now() % 100000}`;
  const ltCreated = await ec2("CreateLaunchTemplate", { LaunchTemplateName: LTN, "LaunchTemplateData.InstanceType": "t3.micro" });
  const ltId = xtag(ltCreated, "launchTemplateId");
  await page.goto(UI + "#/ec2/launch-templates");
  await page.getByRole("row", { name: new RegExp(ltId) }).getByRole("radio").check();
  await page.getByRole("button", { name: "Actions" }).click();
  await page.getByRole("menuitem", { name: "Manage versions" }).click();
  await page.getByRole("button", { name: "Create new version" }).click();
  await page.getByText("2", { exact: true }).first().waitFor({ timeout: 10000 });
  const ltVersions = await ec2("DescribeLaunchTemplateVersions", { LaunchTemplateId: ltId });
  check("EC2 launch template version created (UI) → visible over native wire", ltVersions.includes("<versionNumber>2</versionNumber>"), ltVersions.slice(0, 200));
  await shot("16b-ec2-launch-template-versions");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  await ec2("DeleteLaunchTemplate", { LaunchTemplateId: ltId });

  // EC2: terminate the smoke instance and clean up the security group over the wire.
  if (instanceId) await ec2("TerminateInstances", { "InstanceId.1": instanceId });
  await ec2("DeleteSecurityGroup", { GroupId: sgId });

  // CloudWatch: create an alarm through the UI wizard, verify over native wire (UI → CLI direction)
  const CWA = `v4-smoke-alarm-${Date.now() % 100000}`;
  await cw("PutMetricData", { Namespace: "VyomiSmoke/EC2", MetricData: [{ MetricName: "CPUUtilization", Value: 12.5 }] });
  await page.goto(UI + "#/cloudwatch/alarms/create");
  await page.getByRole("tab", { name: "Specify metric and conditions" }).click();
  await page.getByRole("button", { name: "Namespace" }).click();
  await page.getByRole("option", { name: "VyomiSmoke/EC2" }).click();
  await page.getByRole("button", { name: "Metric name" }).click();
  await page.getByRole("option", { name: "CPUUtilization" }).click();
  await page.getByLabel("Threshold value").fill("80");
  await page.getByRole("tab", { name: "Add alarm details" }).click();
  await page.getByLabel("Alarm name").fill(CWA);
  await page.getByRole("button", { name: "Create alarm", exact: true }).click();
  await page.getByRole("heading", { name: CWA }).waitFor({ timeout: 10000 });
  const alarmsOut = await cw("DescribeAlarms", { AlarmNames: [CWA] });
  check("CloudWatch create alarm (UI wizard) → visible over native wire", alarmsOut.MetricAlarms?.[0]?.AlarmName === CWA, JSON.stringify(alarmsOut.MetricAlarms?.[0]));
  await shot("18-cloudwatch-alarm-detail");

  // CloudWatch Logs: create a log group over the wire, verify it shows in the UI (CLI → UI direction)
  const CWG = `v4-smoke-logs-${Date.now() % 100000}`;
  await cwlogs("CreateLogGroup", { logGroupName: CWG });
  await page.goto(UI + "#/cloudwatch/logs");
  await page.getByText(CWG).first().waitFor({ timeout: 10000 });
  check("CloudWatch Logs log group created over wire → shown in Log management list", true, CWG);
  await shot("19-cloudwatch-log-groups");
  // VPC: create a VPC through the UI wizard (UI → CLI direction)
  const VN = `v4-smoke-vpc-${Date.now() % 100000}`;
  await page.goto(UI + "#/vpc/create-vpc");
  await page.getByPlaceholder("my-vpc-01").fill(VN);
  await page.getByRole("button", { name: "Create VPC", exact: true }).click();
  await page.getByRole("heading", { name: new RegExp(VN) }).waitFor({ timeout: 10000 });
  const vpcsXml = await ec2("DescribeVpcs", {});
  check("VPC create VPC (UI wizard) → visible over native wire", vpcsXml.includes(`<value>${VN}</value>`), vpcsXml.slice(0, 200));
  const vpcIdx = vpcsXml.indexOf(`<value>${VN}</value>`);
  const vpcBefore = vpcsXml.slice(0, vpcIdx);
  const vpcId = vpcIdx >= 0 ? xtag(vpcBefore.slice(vpcBefore.lastIndexOf("<vpcId>")), "vpcId") : null;
  await shot("18-vpc-detail");

  // VPC: create a route table over the wire, verify it shows up in the UI (CLI → UI direction)
  const RTN = `v4-smoke-rt-${Date.now() % 100000}`;
  const rtCreated = vpcId ? await ec2("CreateRouteTable", { VpcId: vpcId, "TagSpecification.1.ResourceType": "route-table", "TagSpecification.1.Tag.1.Key": "Name", "TagSpecification.1.Tag.1.Value": RTN }) : "";
  const rtId = xtag(rtCreated, "routeTableId");
  await page.goto(UI + "#/vpc/route-tables");
  await page.getByPlaceholder("Search").last().fill(rtId || RTN);
  await page.getByText(rtId || RTN).first().waitFor({ timeout: 10000 });
  check("VPC create route table over wire → visible in UI", true, rtId || RTN);
  await shot("19-vpc-route-tables");

  // VPC: flow log created over the wire for a VPC, verify it shows on the VPC detail page's
  // Flow logs tab (CLI → UI direction).
  const FLVPC = await ec2("CreateVpc", { CidrBlock: "10.95.0.0/16" });
  const FLVPCID = xtag(FLVPC, "vpcId");
  const flCreated = await ec2("CreateFlowLogs", { ResourceType: "VPC", "ResourceId.1": FLVPCID, LogGroupName: "v4-smoke-flowlogs" });
  const FLID = (flCreated.match(/<flowLogIdSet><item>(.*?)<\/item>/) || [])[1];
  await page.goto(UI + `#/vpc/vpcs/${FLVPCID}`);
  await page.getByRole("tab", { name: "Flow logs" }).click();
  await page.getByText(FLID).first().waitFor({ timeout: 10000 });
  check("VPC flow log created over wire → shown on VPC detail Flow logs tab", true, FLID);
  await shot("19b-vpc-flow-logs");
  if (FLID) await ec2("DeleteFlowLogs", { "FlowLogId.1": FLID });
  await ec2("DeleteVpc", { VpcId: FLVPCID });

  // VPC: Reachability Analyzer — create and analyze a path through the UI wizard, verify
  // both the path and its analysis over the native wire (UI → CLI direction).
  const nipIgw = await ec2("CreateInternetGateway", {});
  const NIPSRC = xtag(nipIgw, "internetGatewayId");
  await page.goto(UI + "#/vpc/reachability-analyzer");
  await page.getByRole("button", { name: "Create and analyze path" }).click();
  const nipDialog = page.getByRole("dialog");
  await nipDialog.getByPlaceholder("i-0123456789abcdef0").first().fill(NIPSRC);
  await nipDialog.getByPlaceholder("i-0123456789abcdef0").nth(1).fill("203.0.113.9");
  await nipDialog.getByPlaceholder("443").fill("443");
  await nipDialog.getByRole("button", { name: "Create and analyze path" }).click();
  await page.getByRole("heading", { name: /^nip-/ }).waitFor({ timeout: 10000 });
  const nipXml = await ec2("DescribeNetworkInsightsPaths", {});
  check("Reachability Analyzer create path (UI) → visible over native wire", nipXml.includes(NIPSRC), nipXml.slice(0, 200));
  const niaXml = await ec2("DescribeNetworkInsightsAnalyses", {});
  check("Reachability Analyzer run analysis (UI) → networkPathFound recorded over native wire", niaXml.includes("<networkPathFound>"), niaXml.slice(0, 200));
  await shot("19c-vpc-reachability-analyzer");
  const NIPID = (nipXml.match(/<networkInsightsPathId>(.*?)<\/networkInsightsPathId>/) || [])[1];
  for (const aid of [...niaXml.matchAll(/<networkInsightsAnalysisId>(.*?)<\/networkInsightsAnalysisId>/g)].map((m) => m[1]))
    await ec2("DeleteNetworkInsightsAnalysis", { NetworkInsightsAnalysisId: aid });
  if (NIPID) await ec2("DeleteNetworkInsightsPath", { NetworkInsightsPathId: NIPID });

  // VPC: subnet CIDR reservation created over the wire, verify it shows on the subnet
  // detail's CIDR reservations tab (CLI → UI direction), then delete it through the UI.
  const scrSubnetXml = vpcId ? await ec2("CreateSubnet", { VpcId: vpcId, CidrBlock: "10.0.9.0/24" }) : "";
  const SCRSUBNET = xtag(scrSubnetXml, "subnetId");
  const scrXml = SCRSUBNET ? await ec2("CreateSubnetCidrReservation", { SubnetId: SCRSUBNET, Cidr: "10.0.9.4/30", ReservationType: "explicit", Description: "v4-smoke-scr" }) : "";
  const SCRID = xtag(scrXml, "subnetCidrReservationId");
  await page.goto(UI + `#/vpc/subnets/${SCRSUBNET}`);
  await page.getByRole("tab", { name: "CIDR reservations" }).click();
  await page.getByText("10.0.9.4/30").first().waitFor({ timeout: 10000 });
  check("VPC subnet CIDR reservation created over wire → shown on subnet detail tab", true, SCRID);
  await shot("19d-vpc-cidr-reservations");
  if (SCRID) await ec2("DeleteSubnetCidrReservation", { SubnetCidrReservationId: SCRID });
  if (SCRSUBNET) await ec2("DeleteSubnet", { SubnetId: SCRSUBNET });

  // VPC: clean up over the wire.
  if (rtId) await ec2("DeleteRouteTable", { RouteTableId: rtId });
  if (vpcId) await ec2("DeleteVpc", { VpcId: vpcId });

  // CloudFormation: create a stack through the 4-step wizard (UI → CLI direction) —
  // uploads a template file (the real S3-URL path is proven separately by the core
  // conformance suite), picks up the real per-template parameter from ValidateTemplate.
  const CFN = `v4-smoke-stack-${Date.now() % 100000}`;
  const tplPath = `${OUT}/${CFN}.json`;
  await writeFile(tplPath, JSON.stringify({ Resources: { Q: { Type: "AWS::SQS::Queue", Properties: {} } } }));
  await page.goto(UI + "#/cloudformation/create");
  await page.getByRole("radio", { name: "Upload a template file" }).check();
  await page.locator('input[type="file"]').setInputFiles(tplPath);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Stack name", { exact: true }).fill(CFN);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  await page.getByRole("heading", { name: CFN }).waitFor({ timeout: 10000 });
  const stackXml = await cfn("DescribeStacks", { StackName: CFN });
  check("CloudFormation create stack (UI wizard) → visible over native wire", stackXml.includes(`<StackName>${CFN}</StackName>`) && stackXml.includes("CREATE_COMPLETE"), stackXml.slice(0, 200));
  await shot("20-cloudformation-stack");

  // CloudFormation: a stack created over the wire shows in the Stacks list (CLI → UI direction)
  const CFN2 = `v4-smoke-stack2-${Date.now() % 100000}`;
  await cfn("CreateStack", { StackName: CFN2, TemplateBody: JSON.stringify({ Resources: { B: { Type: "AWS::S3::Bucket", Properties: {} } } }) });
  await page.goto(UI + "#/cloudformation/stacks");
  await page.getByPlaceholder("Search by stack name").fill(CFN2);
  await page.getByText(CFN2).first().waitFor({ timeout: 10000 });
  check("CloudFormation stack created over wire → shown in Stacks list", true);
  await shot("21-cloudformation-stacks");

  // CloudFormation: a log group provisioned by a stack, then drifted out-of-band through
  // the Logs engine itself (CLI → CLI) — "Stack actions" → "Detect drift" / "View drift
  // results" render the real PROPERTY difference, not just existence.
  const CFN3 = `v4-smoke-stack3-${Date.now() % 100000}`;
  const LOGRP = `v4-smoke-loggroup-${Date.now() % 100000}`;
  await cfn("CreateStack", { StackName: CFN3, TemplateBody: JSON.stringify({ Resources: { LG: { Type: "AWS::Logs::LogGroup", Properties: { LogGroupName: LOGRP, RetentionInDays: 7 } } } }) });
  await cwlogs("PutRetentionPolicy", { logGroupName: LOGRP, retentionInDays: 30 });
  // already on the Stacks list (from the CFN2 check above); re-navigating to the identical
  // hash wouldn't remount the page, so refresh explicitly to pick up the new stack.
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByPlaceholder("Search by stack name").fill(CFN3);
  await page.getByRole("row", { name: new RegExp(CFN3) }).getByRole("radio").check();
  await page.getByRole("button", { name: "Stack actions" }).click();
  await page.getByRole("menuitem", { name: "Detect drift" }).click();
  await page.getByText(`Drift results — ${CFN3}`).waitFor({ timeout: 10000 });
  await page.getByText("MODIFIED", { exact: true }).waitFor({ timeout: 10000 });
  const driftModalText = await page.getByRole("dialog").innerText();
  check("CloudFormation drift: out-of-band retention change → UI shows MODIFIED + /RetentionInDays diff",
        driftModalText.includes("MODIFIED") && driftModalText.includes("RetentionInDays") && driftModalText.includes("30"), driftModalText.slice(0, 300));
  await shot("22-cloudformation-drift");
  await page.getByRole("button", { name: "Close" }).click();

  // CloudFormation IaC generator: an IAM role provisioned by a stack (CLI direction) is
  // really scanned, then a template generated from it in the UI shows the role's real
  // live properties back over the native wire (UI → CLI direction).
  const CFN4 = `v4-smoke-stack4-${Date.now() % 100000}`;
  const ROLE4 = `v4-smoke-iacrole-${Date.now() % 100000}`;
  const TPL4 = `v4-smoke-iactpl-${Date.now() % 100000}`;
  await cfn("CreateStack", { StackName: CFN4, "Capabilities.member.1": "CAPABILITY_NAMED_IAM",
    TemplateBody: JSON.stringify({ Resources: { R: { Type: "AWS::IAM::Role", Properties: { RoleName: ROLE4 } } } }) });
  await page.goto(UI + "#/cloudformation/iac-generator");
  await page.getByRole("button", { name: "Start a new scan" }).first().click();
  await page.getByText("COMPLETE", { exact: true }).first().waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Create template" }).first().click();
  const iacDialog = page.getByRole("dialog");
  await iacDialog.getByLabel("Template name", { exact: true }).fill(TPL4);
  await iacDialog.getByRole("row", { name: new RegExp(ROLE4) }).getByRole("checkbox").check();
  await iacDialog.getByRole("button", { name: "Create template", exact: true }).click();
  await page.getByText(`Template "${TPL4}" generated.`).waitFor({ timeout: 10000 });
  const genTplXml = await cfn("GetGeneratedTemplate", { GeneratedTemplateName: TPL4 });
  check("IaC generator create template (UI) → real live role properties over native wire",
        genTplXml.includes(ROLE4) && genTplXml.includes("AWS::IAM::Role"), genTplXml.slice(0, 300));
  await shot("23-cloudformation-iac-generator");

  // Dark mode
  await page.evaluate(() => localStorage.setItem("vyomi.v4.mode", "dark"));
  await page.reload();
  await page.waitForTimeout(1500);
  await shot("11-dark");
} catch (e) {
  const at = ((e.stack || "").match(/(?:smoke|dbg)-[a-z]+\.mjs:(\d+)/) || [])[1];   // the failing step's line
  check("smoke run", false, e.message.split("\n")[0] + (at ? ` (smoke line ${at})` : ""));
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
