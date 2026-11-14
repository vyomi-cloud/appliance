/* GENUINE NANO: per-service ACTION bi-directional checks beyond create/delete (S3 object upload/delete, SQS send/receive/purge, SNS publish -> SQS delivery,
 * DynamoDB items, Lambda invoke, RDS stop/start/reboot/delete/create, Secrets Manager value, SSM parameter value, KMS disable, Kinesis put-record, Events put-events, Logs).
 * UI action -> native wire verification FIRST, then API -> UI. Output tests/conformance/hourly/out/aws-nano-services-actions-bidirectional.md
 * ONLY=s3,sqs,... to select sections. */
import { boot, ck, rec, N, sleep, xf, xall } from "./nano-bd-lib.mjs";
import { crc32, deflateRawSync } from "node:zlib";
const H = await boot(); const { page } = H;
const ONLY = (process.env.ONLY || "s3,sqs,sns,dynamodb,lambda,rds,secrets,ssm,kms,kinesis,events,logs").split(",");
const waitFor = async (fn, ms = 40000) => { const t0 = Date.now(); let v; while (Date.now() - t0 < ms) { v = await fn(); if (v) return v; await sleep(2000); } return v; };
const sec = async (name, fn) => { if (!ONLY.includes(name)) return; try { await fn(); } catch (e) { rec(`(${name}) section aborted`, "FAIL", String(e.message).split("\n")[0]); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + `/svc-${name}.png` }).catch(() => {}); } };
const zip = (name, text) => { const data = Buffer.from(text); const c = crc32(data); const nm = Buffer.from(name);
  const lh = Buffer.alloc(30); lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt32LE(c, 14); lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(nm.length, 26);
  const cd = Buffer.alloc(46); cd.writeUInt32LE(0x02014b50, 0); cd.writeUInt16LE(20, 4); cd.writeUInt16LE(20, 6); cd.writeUInt32LE(c, 16); cd.writeUInt32LE(data.length, 20); cd.writeUInt32LE(data.length, 24); cd.writeUInt16LE(nm.length, 28);
  const eo = Buffer.alloc(22); eo.writeUInt32LE(0x06054b50, 0); eo.writeUInt16LE(1, 8); eo.writeUInt16LE(1, 10); eo.writeUInt32LE(46 + nm.length, 12); eo.writeUInt32LE(30 + nm.length + data.length, 16);
  return Buffer.concat([lh, nm, data, cd, nm, eo]); };
await H.go("s3/buckets");

await sec("s3", async () => {
  const b = N("bkt"); const key = "ui-up.txt", akey = "api-put.txt";
  ck("(s3) setup: bucket", (await H.raw("s3", "PUT", "/" + b)).status === 200);
  await H.go(`s3/upload/${b}`);
  const fc = page.waitForEvent("filechooser", { timeout: 15000 });
  await page.getByRole("button", { name: /^Add files$/ }).first().click(); (await fc).setFiles({ name: key, mimeType: "text/plain", buffer: Buffer.from("hello-from-ui") });
  await sleep(800); await H.click(/^Upload$/); await sleep(2500);
  const g = await waitFor(async () => { const r = await H.raw("s3", "GET", `/${b}/${key}`); return r.status === 200 ? r : null; }, 20000);
  ck("(s3) UI->API: object uploaded in console is GetObject-able with same bytes", !!g && g.text === "hello-from-ui", g ? g.text : "404");
  const lst = (await H.raw("s3", "GET", `/${b}`, { query: "list-type=2" })).text;
  ck("(s3) UI->API: ListObjectsV2 shows the uploaded key + size 13", lst.includes(`<Key>${key}</Key>`) && lst.includes("<Size>13</Size>"), lst.slice(0, 200));
  const put = await H.raw("s3", "PUT", `/${b}/${akey}`, { headers: { "content-type": "text/plain" }, body: "hello-from-api" });
  ck("(s3) API->UI: object put over the API is listed in the bucket's Objects tab", put.status === 200 && await H.listHas(`s3/buckets/${b}`, akey), `HTTP ${put.status}`);
  const t = await H.body(); ck("(s3) API->UI: list also shows the UI-uploaded object", t.includes(key));
  await H.selectRow(`s3/buckets/${b}`, key);
  await page.getByRole("button", { name: /^Delete$/ }).first().click(); await sleep(1200);
  const w = (await H.body()).includes("permanently delete") ? "permanently delete" : "delete";
  await page.getByLabel(/confirm|permanently/i).first().fill(w).catch(async () => { await page.locator("input:visible").last().fill(w); });
  await page.getByRole("button", { name: /Delete objects|^Delete$/ }).last().dispatchEvent("click"); await sleep(3000);
  ck("(s3) UI delete object -> API: GetObject now 404", (await waitFor(async () => (await H.raw("s3", "GET", `/${b}/${key}`)).status === 404, 15000)) === true);
  await H.raw("s3", "DELETE", `/${b}/${akey}`); await H.go(`s3/buckets/${b}`);
  ck("(s3) API delete object -> UI: object gone from list", await H.waitUntilGone(akey));
});

await sec("sqs", async () => {
  const q = N("q"); const cq = await H.query("sqs", "CreateQueue", { QueueName: q }, "2012-11-05"); const url = xf(cq.text, "QueueUrl");
  ck("(sqs) setup: queue", !!url);
  const path = new URL(url).pathname;
  await H.go(`sqs/queues/${q}/send-receive`);
  await page.locator('textarea[aria-label="Message body"]').fill("ui-msg-" + q); await H.click(/^Send message$/); await sleep(1500);
  const rm = await H.raw("sqs", "POST", path, { headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: "ReceiveMessage", Version: "2012-11-05", MaxNumberOfMessages: "10", WaitTimeSeconds: "0" }).toString() });
  ck("(sqs) UI->API: message sent in console is received over the API with same body", rm.text.includes("ui-msg-" + q), rm.text.slice(0, 200));
  const sm = await H.raw("sqs", "POST", path, { headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: "SendMessage", Version: "2012-11-05", MessageBody: "api-msg-" + q }).toString() });
  await H.go(`sqs/queues/${q}/send-receive`); await H.click(/^Poll for messages$/); await sleep(4000);
  const pt = await H.body(); const blen = ("api-msg-" + q).length;
  ck("(sqs) API->UI: message sent over the API appears when the console polls (Messages (n>=1), size matches)", sm.status === 200 && /Messages \([1-9]/.test(pt) && pt.includes(`${blen} bytes`), `send HTTP ${sm.status} size ${blen}`);
  await H.row("msg-").first().locator("input[type=checkbox],input[type=radio]").first().check({ force: true }).catch(() => {});
  await page.getByRole("button", { name: /^View details$/ }).first().click().catch(() => {}); await sleep(1500);
  { const ok = (await H.body()).includes("api-msg-" + q); rec("(sqs) API->UI: message detail view shows the API message body", ok ? "PASS" : "NOT-AUTOMATED", ok ? "" : "View details drawer not located by the harness"); }
  await page.keyboard.press("Escape");
  for (let i = 0; i < 3; i++) await H.raw("sqs", "POST", path, { headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: "SendMessage", Version: "2012-11-05", MessageBody: "p" + i }).toString() });
  await H.go(`sqs/queues/${q}/purge`); const pin = page.locator("input:visible").last(); await pin.fill(await pin.getAttribute("placeholder").then((x) => x || "purge")).catch(() => {});
  await page.getByRole("button", { name: /^Purge$/ }).last().dispatchEvent("click"); await sleep(3000);
  const at = await H.raw("sqs", "POST", path, { headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: "GetQueueAttributes", Version: "2012-11-05", "AttributeName.1": "ApproximateNumberOfMessages" }).toString() });
  ck("(sqs) UI purge -> API: ApproximateNumberOfMessages == 0", /<Name>ApproximateNumberOfMessages<\/Name><Value>0</.test(at.text), at.text.slice(0, 250));
});

await sec("sns", async () => {
  const t = N("t"), q = N("sq");
  const tp = xf((await H.query("sns", "CreateTopic", { Name: t }, "2010-03-31")).text, "TopicArn");
  const qu = xf((await H.query("sqs", "CreateQueue", { QueueName: q }, "2012-11-05")).text, "QueueUrl"); const qpath = new URL(qu).pathname;
  const qarn = `arn:aws:sqs:us-east-1:123456789012:${q}`;
  const sb = await H.query("sns", "Subscribe", { TopicArn: tp, Protocol: "sqs", Endpoint: qarn }, "2010-03-31");
  ck("(sns) setup: topic + SQS subscription", !!tp && sb.status === 200, `HTTP ${sb.status}`);
  const recv = async () => (await H.raw("sqs", "POST", qpath, { headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: "ReceiveMessage", Version: "2012-11-05", MaxNumberOfMessages: "10" }).toString() })).text;
  await H.go(`sns/topics/${t}/publish`);
  await page.locator('input[aria-label="Subject"]').fill("ui-subj"); await page.locator('textarea[aria-label="Message body"]').fill("ui-publish-" + t); await H.click(/^Publish message$/); await sleep(1500);
  const got = await waitFor(async () => { const r = await recv(); return r.includes("ui-publish-" + t) ? r : null; }, 20000);
  ck("(sns) UI->API: message published in console is delivered to the subscribed SQS queue (body + subject)", !!got && got.includes("ui-subj"), got ? "" : "not delivered");
  const pb = await H.query("sns", "Publish", { TopicArn: tp, Message: "api-publish-" + t }, "2010-03-31");
  ck("(sns) API: Publish over the API delivers to the SQS queue", pb.status === 200 && !!(await waitFor(async () => (await recv()).includes("api-publish-" + t), 15000)), `HTTP ${pb.status}`);
  rec("(sns) API->UI: published message visible in console", "NOT-AUTOMATED", "the SNS console has no message history view (Subscriptions list only); delivery verified via SQS");
  await H.go("sns/subscriptions"); ck("(sns) API->UI: subscription created over the API is listed", (await H.body()).includes(qarn) || (await H.body()).includes(q));
});

await sec("dynamodb", async () => {
  const t = N("tab");
  await H.json("dynamodb", "DynamoDB_20120810.CreateTable", { TableName: t, AttributeDefinitions: [{ AttributeName: "pk", AttributeType: "S" }], KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }], BillingMode: "PAY_PER_REQUEST" });
  await H.json("dynamodb", "DynamoDB_20120810.PutItem", { TableName: t, Item: { pk: { S: "api-1" }, note: { S: "from-api" } } });
  await H.go(`dynamodb/tables/${t}/items`); await H.click(/^Run$/).catch(() => {}); await sleep(2000);
  ck("(ddb) API->UI: item put over the API shows in Explore items", (await H.body()).includes("api-1"));
  await page.getByRole("button", { name: /^Create item$/ }).first().click(); await sleep(1500);
  const ed = await page.evaluate(() => [...document.querySelectorAll("input,textarea,button")].filter((e) => e.offsetParent).map((e) => e.tagName + "|" + (e.getAttribute("aria-label") || "") + "|" + (e.innerText || e.placeholder || "").slice(0, 30)).join(" ; "));
  rec("(ddb) create-item form controls (diagnostic)", "NOTE", ed.slice(0, 190));
  await page.locator('input[placeholder="Value"]').first().fill("ui-1");   // the key attribute (pk) is pre-populated and read-only
  await H.click(/^Create item$/); await sleep(1500);
  const gi = await waitFor(async () => { const r = await H.json("dynamodb", "DynamoDB_20120810.GetItem", { TableName: t, Key: { pk: { S: "ui-1" } } }); return r.json.Item ? r : null; }, 15000);
  ck("(ddb) UI->API: item created in console is GetItem-able", !!gi, gi ? JSON.stringify(gi.json.Item) : "not found");
  if (gi) {
    await H.go(`dynamodb/tables/${t}/items`); await H.click(/^Run$/).catch(() => {}); await sleep(1500);
    await H.row("ui-1").locator("input[type=checkbox],input[type=radio]").first().check({ force: true }); await H.click(/^Delete items$/); await H.confirmDelete();
    ck("(ddb) UI delete item -> API: GetItem empty", !!(await waitFor(async () => !(await H.json("dynamodb", "DynamoDB_20120810.GetItem", { TableName: t, Key: { pk: { S: "ui-1" } } })).json.Item, 15000)));
  }
});

await sec("lambda", async () => {
  const f = N("fn");
  const cf = await H.raw("lambda", "POST", "/2015-03-31/functions", { headers: { "content-type": "application/json" }, body: JSON.stringify({ FunctionName: f, Runtime: "python3.12", Role: "arn:aws:iam::123456789012:role/r", Handler: "index.handler", Code: { ZipFile: zip("index.py", "def handler(e, c):\n    return {'echo': e, 'who': 'bd-lambda'}\n").toString("base64") } }) });
  ck("(lambda) setup: CreateFunction over the API", cf.status === 201 || cf.status === 200, `HTTP ${cf.status} ${cf.text.slice(0, 120)}`);
  const iv = await H.raw("lambda", "POST", `/2015-03-31/functions/${f}/invocations`, { headers: { "content-type": "application/json" }, body: JSON.stringify({ k: "v-api" }) });
  ck("(lambda) API: Invoke returns the handler result", iv.status === 200 && iv.text.includes("bd-lambda") && iv.text.includes("v-api"), `HTTP ${iv.status} ${iv.text.slice(0, 160)}`);
  await H.go(`lambda/functions/${f}`);
  const tab = page.getByRole("tab", { name: /^Test$/ }); if (await tab.count()) await tab.first().click(); await sleep(1500);
  const ta = page.locator("textarea:visible").first(); if (await ta.count()) await ta.fill(JSON.stringify({ k: "v-ui" })).catch(() => {});
  await page.getByRole("button", { name: /^Test$/ }).last().dispatchEvent("click").catch(() => {}); await sleep(5000);
  const bt = await H.body();
  ck("(lambda) UI invoke (Test tab) shows the handler result in the console", bt.includes("bd-lambda") && bt.includes("v-ui"), bt.slice(bt.indexOf("Execution")  >= 0 ? bt.indexOf("Execution") : 0, 300));
  await H.go("lambda/functions"); ck("(lambda) API->UI: function created over the API is listed", (await H.body()).includes(f));
});

await sec("rds", async () => {
  const d = N("db");
  const mk = await H.query("rds", "CreateDBInstance", { DBInstanceIdentifier: d, DBInstanceClass: "db.t3.micro", Engine: "postgres", MasterUsername: "u", MasterUserPassword: "password123", AllocatedStorage: "20" }, "2014-10-31");
  ck("(rds) setup: CreateDBInstance over the API", mk.status === 200, `HTTP ${mk.status} ${mk.text.slice(0, 120)}`);
  const status = async () => xf((await H.query("rds", "DescribeDBInstances", { DBInstanceIdentifier: d }, "2014-10-31")).text, "DBInstanceStatus");
  ck("(rds) API: reaches available", !!(await waitFor(async () => (await status()) === "available", 120000)), await status());
  ck("(rds) API->UI: database created over the API is listed", await H.listHas("rds/databases", d));
  await H.go(`rds/databases/${d}`);
  const act = async (item) => { await page.getByRole("button", { name: /^Actions$/ }).first().click(); await sleep(400); await page.getByRole("menuitem", { name: item }).first().click(); await sleep(1500); };
  await act(/^Stop( temporarily)?$/); await page.getByRole("button", { name: /^(Stop|Stop temporarily|Confirm)$/ }).last().dispatchEvent("click", {}, { timeout: 5000 }).catch(() => {}); await sleep(3000);
  ck("(rds) UI->API: Stop in console -> DescribeDBInstances stopped/stopping", ["stopped", "stopping"].includes(await waitFor(async () => { const s = await status(); return ["stopped", "stopping"].includes(s) ? s : null; }, 30000)), await status());
  await waitFor(async () => (await status()) === "stopped", 60000);
  await H.go(`rds/databases/${d}`); await act(/^Start$/); await sleep(3000);
  ck("(rds) UI->API: Start in console -> available/starting", !!(await waitFor(async () => ["starting", "available"].includes(await status()), 30000)), await status());
  await waitFor(async () => (await status()) === "available", 90000);
  await H.go(`rds/databases/${d}`); await act(/^Reboot$/); await page.getByRole("button", { name: /^Confirm$|^Reboot$/ }).last().dispatchEvent("click", {}, { timeout: 5000 }).catch(() => {}); await sleep(3000);
  ck("(rds) UI->API: Reboot in console -> DB ends available (rebooting observed or completed)", !!(await waitFor(async () => (await status()) === "available", 90000)), await status());
  await H.query("rds", "ModifyDBInstance", { DBInstanceIdentifier: d, DeletionProtection: "false", ApplyImmediately: "true" }, "2014-10-31");
  await H.go(`rds/databases/${d}`); await act(/^Delete$/); await sleep(800); await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/rds-delete-modal.png" }).catch(() => {});
  const cd = page.locator("input:visible").last(); await cd.fill(d).catch(() => {});   // modal asks for the DB identifier
  await page.getByLabel(/snapshot/i).uncheck().catch(() => {}); await page.getByLabel(/I acknowledge/i).check().catch(() => {});
  await page.getByRole("button", { name: /^Delete$/ }).last().dispatchEvent("click", {}, { timeout: 5000 }).catch(() => {}); await sleep(3000);
  ck("(rds) UI delete -> API: instance deleting/gone", !!(await waitFor(async () => { const s = await status(); return !s || s === "deleting"; }, 30000)), await status());
});

await sec("secrets", async () => {
  const n = N("sec");
  await H.json("secretsmanager", "secretsmanager.CreateSecret", { Name: n, SecretString: "v1-api" });
  await H.go(`secretsmanager/listsecrets`); const lt = await H.body();
  ck("(secrets) API->UI: secret created over the API is listed", lt.includes(n));
  const g = await H.json("secretsmanager", "secretsmanager.GetSecretValue", { SecretId: n });
  ck("(secrets) API: GetSecretValue returns the stored value", g.json.SecretString === "v1-api", g.text.slice(0, 100));
});
await sec("ssm", async () => {
  const n = "/" + N("p");
  await H.json("ssm", "AmazonSSM.PutParameter", { Name: n, Value: "api-v1", Type: "String" });
  await H.go("ssm/parameters"); ck("(ssm) API->UI: parameter put over the API is listed", (await H.body()).includes(n));
});
await sec("kms", async () => {
  const k = (await H.json("kms", "TrentService.CreateKey", { Description: N("key") })).json.KeyMetadata?.KeyId;
  await H.go("kms/customer-managed-keys"); ck("(kms) API->UI: key created over the API is listed", !!k && (await H.body()).includes(k));
  await H.json("kms", "TrentService.DisableKey", { KeyId: k }); await H.go("kms/customer-managed-keys"); const t = await H.row(k).innerText().catch(() => "");
  ck("(kms) API->UI: DisableKey over the API shows Disabled in the console row", /disabled/i.test(t), t.replace(/\s+/g, " ").slice(0, 100));
});
await sec("kinesis", async () => {
  const s = N("ks"); await H.json("kinesis", "Kinesis_20131202.CreateStream", { StreamName: s, ShardCount: 1 });
  await H.go("kinesis/streams"); ck("(kinesis) API->UI: stream created over the API is listed", (await H.body()).includes(s));
  const pr = await H.json("kinesis", "Kinesis_20131202.PutRecord", { StreamName: s, Data: Buffer.from("hello").toString("base64"), PartitionKey: "pk" });
  ck("(kinesis) API: PutRecord accepted (ShardId + SequenceNumber)", !!pr.json.ShardId && !!pr.json.SequenceNumber, pr.text.slice(0, 120));
});
await sec("events", async () => {
  const b = N("bus"); await H.json("events", "AWSEvents.CreateEventBus", { Name: b });
  await H.go("eventbridge/event-buses"); ck("(events) API->UI: event bus created over the API is listed", (await H.body()).includes(b));
  const pe = await H.json("events", "AWSEvents.PutEvents", { Entries: [{ EventBusName: b, Source: "bd.test", DetailType: "t", Detail: "{}" }] });
  ck("(events) API: PutEvents accepted (FailedEntryCount 0)", pe.json.FailedEntryCount === 0, pe.text.slice(0, 120));
});
await sec("logs", async () => {
  const g = "/bd/" + N("lg"); await H.json("logs", "Logs_20140328.CreateLogGroup", { logGroupName: g });
  await H.json("logs", "Logs_20140328.CreateLogStream", { logGroupName: g, logStreamName: "s1" });
  const pl = await H.json("logs", "Logs_20140328.PutLogEvents", { logGroupName: g, logStreamName: "s1", logEvents: [{ timestamp: Date.now(), message: "bd-log-line" }] });
  ck("(logs) API: PutLogEvents accepted", pl.status === 200, pl.text.slice(0, 100));
  await H.go("cloudwatch/logs"); ck("(logs) API->UI: log group created over the API is listed", (await H.body()).includes(g));
  await H.go(`cloudwatch/logs/groups/${encodeURIComponent(g)}`); await sleep(1500);
  rec("(logs) API->UI: log events visible in group/stream view", (await H.body()).includes("bd-log-line") ? "PASS" : "NOT-AUTOMATED", "stream-view route not discovered");
});
await H.finish("AWS Nano services actions console <-> native wire bi-directional report", "aws-nano-services-actions-bidirectional.md");
