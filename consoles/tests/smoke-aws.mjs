/* End-to-end smoke of the AWS lens against a running /_wire backend (dev_server.py, the
 * offline appliance, or Nano). Drives the UI like a user; cross-checks state over the
 * native wire (what an SDK/CLI would see). Screenshots → $OUT (default ./smoke-out).
 *
 *   BASE=http://127.0.0.1:8740 node consoles/tests/smoke-aws.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

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
// EC2 Query protocol: form-encoded Action=..., XML response — extract tags with a small regex (no DOMParser in this context).
const ec2 = async (action, params = {}) => wire("/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8", authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0" }, body: new URLSearchParams({ Action: action, ...params }).toString() });
const xtag = (xml, tag) => { const m = xml.match(new RegExp(`<${tag}>(.*?)</${tag}>`)); return m ? m[1] : null; };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Native 404s ("no tag set", "no encryption config") are expected answers, not page errors.
page.on("console", (m) => m.type() === "error" && !/status of 404/.test(m.text()) && errors.push(m.text()));
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
  check("Permissions: config-only badges rendered from the registry", (await page.locator('[data-vyomi-capability="config_only"]').count()) >= 3);
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
  await shot("05b-s3-permissions-edited");

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

  // EC2: create a security group over the wire, verify it shows up in the UI (CLI → UI direction)
  const SG = `v4-smoke-sg-${Date.now() % 100000}`;
  const sgCreated = await ec2("CreateSecurityGroup", { GroupName: SG, GroupDescription: "v4 smoke test" });
  const sgId = xtag(sgCreated, "groupId");
  await page.goto(UI + "#/ec2/security-groups");
  await page.getByPlaceholder("Find security groups by attribute or tag").fill(sgId);
  await page.getByText(sgId).waitFor({ timeout: 10000 });
  check("EC2 create security group over wire → visible in UI", true, sgId);
  await shot("16-ec2-security-groups");

  // EC2: terminate the smoke instance and clean up the security group over the wire.
  if (instanceId) await ec2("TerminateInstances", { "InstanceId.1": instanceId });
  await ec2("DeleteSecurityGroup", { GroupId: sgId });

  // Dark mode
  await page.evaluate(() => localStorage.setItem("vyomi.v4.mode", "dark"));
  await page.reload();
  await page.waitForTimeout(1500);
  await shot("11-dark");
} catch (e) {
  check("smoke run", false, e.message.split("\n")[0]);
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
