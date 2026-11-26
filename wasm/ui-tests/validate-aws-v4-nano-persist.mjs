/* GENUINE Nano (service worker + Pyodide cores, served by consoles/nano_preview.mjs) v4 AWS console: resources created over /_wire survive a
 * full page reload. Retarget of the legacy validate-nano-rds-persist.mjs (+ the reload half of validate-nano-aws-compute-reload.mjs).
 * Regression guarded: RDS (Postgres + MySQL) vanished on reload because nano-boot swapped the store to PGlite after the adapter had
 * imported it; SQS / DynamoDB / S3 / EC2 VPC / Lambda are checked alongside so a fix for one never breaks the others.
 * Env: BASE (default http://127.0.0.1:8743 = `node consoles/nano_preview.mjs --port 8743`), UI_PATH (/nano/v4/aws/), WIRE_PATH (/nano/_wire), PW_CHANNEL. */
import { chromium, sleep } from "./lib.mjs";
const BASE = process.env.BASE || "http://127.0.0.1:8743";
const UI = BASE + (process.env.UI_PATH || "/nano/v4/aws/"), WIRE = BASE + (process.env.WIRE_PATH || "/nano/_wire");
const s = Date.now().toString(36).slice(-6), SQS = "pq" + s, DDB = "pt" + s, S3 = "pb" + s, FN = "pf" + s, API = "pa" + s, PG = "ppg" + s, MY = "pmy" + s, VPC = "pv" + s;
const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + String(extra).replace(/\s+/g, " ").slice(0, 220)}`); };
const ready = () => page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 300000, polling: 500 });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const call = (svc, version, action, params) => page.evaluate(async ([u, svc, a, v, p, au]) => { const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: v, ...p }).toString() }); return { status: r.status, text: await r.text() }; }, [WIRE, svc, action, version, params, auth(svc)]);
const ddb = (target, body) => page.evaluate(async ([u, t, b, au]) => { const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-amz-json-1.0", "x-amz-target": "DynamoDB_20120810." + t }, body: JSON.stringify(b) }); return { status: r.status, text: await r.text() }; }, [WIRE, target, body, auth("dynamodb")]);
const rest = (method, path, body) => page.evaluate(async ([u, m, p, b, au]) => { const r = await fetch(u + p, { method: m, headers: { authorization: au, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return { status: r.status, text: await r.text() }; }, [WIRE, method, path, body || null, auth("lambda")]);
const ZIP = "UEsDBBQAAAAAAAdcel2mA0oqIQAAACEAAAAIAAAAaW5kZXgucHlkZWYgaGFuZGxlcihlLCBjKToKICAgIHJldHVybiB7fQpQSwECFAMUAAAAAAAHXHpdpgNKKiEAAAAhAAAACAAAAAAAAAAAAAAAgAEAAAAAaW5kZXgucHlQSwUGAAAAAAEAAQA2AAAARwAAAAAA";
const s3 = (method, path) => page.evaluate(async ([u, m, p, au]) => { const r = await fetch(u + p, { method: m, headers: { authorization: au } }); return { status: r.status, text: await r.text() }; }, [WIRE, method, path, auth("s3")]);
try {
  await page.goto(UI + "#/rds", { waitUntil: "domcontentloaded" }); await ready();
  const pw = "Passw0rd!x1";
  const mk = [
    ["SQS queue", await call("sqs", "2012-11-05", "CreateQueue", { QueueName: SQS })],
    ["DynamoDB table", await ddb("CreateTable", { TableName: DDB, KeySchema: [{ AttributeName: "id", KeyType: "HASH" }], AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], BillingMode: "PAY_PER_REQUEST" })],
    ["S3 bucket", await s3("PUT", "/" + S3)],
    ["RDS Postgres", await call("rds", "2014-10-31", "CreateDBInstance", { DBInstanceIdentifier: PG, DBInstanceClass: "db.t3.micro", Engine: "postgres", MasterUsername: "u", MasterUserPassword: pw, AllocatedStorage: "20" })],
    ["RDS MySQL", await call("rds", "2014-10-31", "CreateDBInstance", { DBInstanceIdentifier: MY, DBInstanceClass: "db.t3.micro", Engine: "mysql", MasterUsername: "u", MasterUserPassword: pw, AllocatedStorage: "20" })],
    ["EC2 VPC", await call("ec2", "2016-11-15", "CreateVpc", { CidrBlock: "10.93.0.0/16" })],
    ["Lambda function", await rest("POST", "/2015-03-31/functions", { FunctionName: FN, Runtime: "python3.12", Role: "arn:aws:iam::123456789012:role/r", Handler: "index.handler", Code: { ZipFile: ZIP } })],
    ["API Gateway REST API", await rest("POST", "/restapis", { name: API })],
  ];
  for (const [n, r] of mk) check(`create ${n} on the Nano wire`, r.status < 300, `${r.status} ${r.text.slice(0, 120)}`);
  const vpcId = (mk[5][1].text.match(/<vpcId>([^<]+)</) || [])[1];
  await sleep(4000);                       // let the persisted-registry snapshot flush
  await page.reload({ waitUntil: "domcontentloaded" }); await ready(); await sleep(2000);
  const q = await call("sqs", "2012-11-05", "ListQueues", {}); check("SQS queue survives a reload", q.text.includes(SQS), q.text.slice(0, 160));
  const t = await ddb("ListTables", {}); check("DynamoDB table survives a reload", t.text.includes(DDB), t.text.slice(0, 160));
  const b = await s3("GET", "/"); check("S3 bucket survives a reload", b.text.includes(S3), b.text.slice(0, 160));
  const d = await call("rds", "2014-10-31", "DescribeDBInstances", {});
  check("RDS Postgres instance survives a reload", d.text.includes(`<DBInstanceIdentifier>${PG}<`), d.text.slice(0, 160));
  check("RDS MySQL instance survives a reload", d.text.includes(`<DBInstanceIdentifier>${MY}<`), d.text.slice(0, 160));
  const fl = await rest("GET", "/2015-03-31/functions"); check("Lambda function survives a reload", fl.text.includes(FN), fl.text.slice(0, 160));
  const al = await rest("GET", "/restapis"); check("API Gateway REST API survives a reload", al.text.includes(API), al.text.slice(0, 160));
  const v = await call("ec2", "2016-11-15", "DescribeVpcs", {}); check("EC2 VPC survives a reload", !!vpcId && v.text.includes(vpcId), v.text.slice(0, 160));
  await page.goto(UI + "#/rds/databases"); await page.reload(); await ready(); await sleep(3000);
  const body = await page.evaluate(() => document.body.innerText);
  check("console RDS list shows both reloaded instances", body.includes(PG) && body.includes(MY), body.slice(0, 200));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
