/* End-to-end proof of the Nano relay loop, fully local:
 *   external HTTP client → local relay → browser tab
 *      (Pyodide + AwsWireRouter + all 7 cores) → response
 *
 * This is the CORE GOAL demonstrated: an external client (standing in for
 * aws-cli/boto3) validates against the in-browser sim across MULTIPLE services —
 * no install on the "sim" side beyond a browser tab. Same WS protocol the
 * Cloudflare relay uses. Also exercises the in-tab PGlite SQL bridge.
 *
 * Prereqs: a repo-root static server on :8000 (so /wasm/core/*.py,
 * /wasm/relay/*.html and /wasm/pglite-loader.js are reachable), the local relay
 * on :8090, and Playwright available. (See ../../scratchpad e2e-browser.mjs for a
 * fully self-contained runner that starts the server + relay itself.)
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || "playwright");

const RELAY = process.env.RELAY_HTTP || "http://localhost:8090";
const TAB_URL = process.env.TAB_URL ||
  "http://localhost:8000/wasm/relay/nano-endpoint.html?relay=ws://localhost:8090/register&core=/wasm/core";

const fail = (m) => { console.log("FAIL:", m); process.exit(1); };

// the "external app" — raw HTTP, exactly as a real SDK sends it
async function call(method, path, headers = {}, body) {
  const r = await fetch(RELAY + path, { method, headers, body: body ?? undefined });
  return { status: r.status, headers: Object.fromEntries(r.headers), text: await r.text() };
}
const json = (target, payload, ct = "application/x-amz-json-1.0") =>
  call("POST", "/", { "x-amz-target": target, "content-type": ct }, JSON.stringify(payload));
const query = (params) => call("POST", "/", { "content-type": "application/x-www-form-urlencoded" },
  Object.entries(params).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&"));

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("[tab pageerror]", e.message));
try {
  await page.goto(TAB_URL, { waitUntil: "load" });
  await page.waitForFunction(() => window.__nano && window.__nano.registered, { timeout: 120000 })
    .catch(() => fail("tab never registered with the relay (Pyodide/core/WS boot)"));
  console.log("0. PASS — Nano tab booted cores + registered with the relay");

  // S3 — native method+path wire
  if ((await call("PUT", "/demo")).status !== 200) fail("s3 mb");
  const put = await call("PUT", "/demo/hello.txt", { "content-type": "text/plain" }, "hello from an EXTERNAL client");
  if (put.status !== 200 || !put.headers.etag) fail("s3 put " + JSON.stringify(put));
  const get = await call("GET", "/demo/hello.txt");
  if (get.text !== "hello from an EXTERNAL client") fail("s3 get " + JSON.stringify(get));
  if (!(await call("GET", "/demo")).text.includes("<Key>hello.txt</Key>")) fail("s3 list");
  console.log("1. PASS — S3 PUT/GET/LIST round-trip via in-browser core");

  // DynamoDB — JSON wire (X-Amz-Target)
  await json("DynamoDB_20120810.CreateTable", { TableName: "u",
    KeySchema: [{ AttributeName: "id", KeyType: "HASH" }],
    AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], BillingMode: "PAY_PER_REQUEST" });
  await json("DynamoDB_20120810.PutItem", { TableName: "u", Item: { id: { S: "a" }, n: { N: "7" } } });
  const gi = await json("DynamoDB_20120810.GetItem", { TableName: "u", Key: { id: { S: "a" } } });
  if (JSON.parse(gi.text).Item.n.N !== "7") fail("ddb " + gi.text);
  console.log("2. PASS — DynamoDB CreateTable/PutItem/GetItem (typed) via in-browser core");

  // KMS — encrypt → decrypt round-trip
  const key = JSON.parse((await json("TrentService.CreateKey", {}, "application/x-amz-json-1.1")).text).KeyMetadata.KeyId;
  const enc = JSON.parse((await json("TrentService.Encrypt", { KeyId: key, Plaintext: "c2VjcmV0" }, "application/x-amz-json-1.1")).text);
  const dec = JSON.parse((await json("TrentService.Decrypt", { CiphertextBlob: enc.CiphertextBlob }, "application/x-amz-json-1.1")).text);
  if (dec.Plaintext !== "c2VjcmV0") fail("kms " + JSON.stringify(dec));
  console.log("3. PASS — KMS Encrypt→Decrypt round-trip via in-browser core");

  // SQS — send/receive
  const qurl = JSON.parse((await json("AmazonSQS.CreateQueue", { QueueName: "jobs" })).text).QueueUrl;
  await json("AmazonSQS.SendMessage", { QueueUrl: qurl, MessageBody: "ping" });
  if (JSON.parse((await json("AmazonSQS.ReceiveMessage", { QueueUrl: qurl })).text).Messages[0].Body !== "ping") fail("sqs");
  console.log("4. PASS — SQS Send/Receive via in-browser core");

  // IAM — Query+XML
  await query({ Action: "CreateUser", UserName: "alice", Version: "2010-05-08" });
  if (!(await query({ Action: "ListUsers", Version: "2010-05-08" })).text.includes("alice")) fail("iam");
  console.log("5. PASS — IAM CreateUser/ListUsers (Query+XML) via in-browser core");

  // RDS — control plane (Query+XML)
  const cdb = await query({ Action: "CreateDBInstance", DBInstanceIdentifier: "appdb",
    Engine: "postgres", DBInstanceClass: "db.t3.micro", AllocatedStorage: "20", Version: "2014-10-31" });
  if (!cdb.text.includes("<DBInstanceIdentifier>appdb</DBInstanceIdentifier>")) fail("rds " + cdb.text.slice(0, 200));
  console.log("6. PASS — RDS CreateDBInstance (Query+XML) via in-browser core");

  // In-tab SQL bridge — real engine (PGlite Postgres, or sqlite3 fallback)
  const pg = await page.evaluate(() => typeof globalThis.__nano_pglite_new === "function");
  const sql = (db, q, p = []) => page.evaluate(([db, q, p]) => window.__nano.sql(db, q, p), [db, q, p]);
  if (!(await sql("appdb", "CREATE TABLE t (id INTEGER, name TEXT)")).ok) fail("sql create");
  await sql("appdb", `INSERT INTO t (id, name) VALUES (${pg ? "$1" : "?"}, ${pg ? "$2" : "?"})`, [1, "alice"]);
  const sel = await sql("appdb", `SELECT id, name FROM t WHERE id = ${pg ? "$1" : "?"}`, [1]);
  if (!sel.ok || JSON.stringify(sel.rows) !== JSON.stringify([[1, "alice"]])) fail("sql select " + JSON.stringify(sel));
  console.log(`7. PASS — in-tab SQL bridge round-trip on ${pg ? "PGlite (real Postgres)" : "sqlite3"}`);
  if (pg && !String((await sql("appdb", "SELECT version()")).rows[0][0]).includes("PostgreSQL")) fail("not postgres");

  // RDS Data API over the relay — EXTERNAL boto3-rds-data-style HTTP, reads the row
  // the in-tab bridge inserted (same engine instance). The relational path that
  // survives the HTTP relay (no Postgres-wire TCP).
  const dataApi = (action, body) => call("POST", "/" + action,
    { "content-type": "application/json" }, JSON.stringify(body));
  const ds = await dataApi("Execute", {
    resourceArn: "arn:aws:rds:us-east-1:123456789012:cluster:appdb", database: "appdb",
    sql: "SELECT id, name FROM t WHERE id = :id", includeResultMetadata: true,
    parameters: [{ name: "id", value: { longValue: 1 } }] });
  const dj = JSON.parse(ds.text);
  if (ds.status !== 200 || JSON.stringify(dj.records) !== JSON.stringify([[{ longValue: 1 }, { stringValue: "alice" }]]))
    fail("rds-data execute " + ds.status + " " + ds.text.slice(0, 200));
  console.log(`8. PASS — RDS Data API ExecuteStatement over the relay → typed records from ${pg ? "PGlite" : "sqlite3"}`);

  const served = await page.evaluate(() => window.__nano.served);
  console.log(`\nRESULT: PASS — external client validated against the IN-BROWSER sim via the relay across 7 services + the SQL bridge (${served} requests served by the tab).`);
} catch (e) {
  fail(String(e));
} finally {
  await browser.close();
}
