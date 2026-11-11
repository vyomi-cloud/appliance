/* Nano: resources created through the console API survive a page reload.
 * Regression: RDS (Postgres + MySQL) vanished on reload. nano-boot swapped the registry's RDS store to PGlite AFTER the console
 * adapter had imported it, so aws_core_adapter.RDB was a dead InMemorySqlStore that was never snapshotted. SQS / DynamoDB / S3 are
 * checked alongside so a fix for one never breaks the others. No relay needed. NANO_DIR = the wasm/ dir (absolute). */
import { chromium, sleep, startServer, bootConsole } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
const call = (m, p, b) => page.evaluate(async ([m, p, b]) => {
  const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  return { status: r.status, text: await r.text() };
}, [m, p, b]);
const N = Date.now().toString(36);
const NAMES = { pg: `pg${N}`, my: `my${N}`, q: `q${N}`, t: `t${N}`, b: `b${N}` };

try {
  await bootConsole(page, base, "/aws-console.html");
  await sleep(4000);
  const mk = [
    ["RDS postgres", "/api/rds/databases", { engine: "postgres", engine_version: "16.4", name: NAMES.pg, master_username: "u", instance_class: "db.t3.micro", tags: {} }],
    ["RDS mysql", "/api/rds/databases", { engine: "mysql", engine_version: "8.0", name: NAMES.my, master_username: "u", instance_class: "db.t3.micro", tags: {} }],
    ["SQS queue", "/api/sqs/queues", { name: NAMES.q }],
    ["DynamoDB table", "/api/dynamodb/tables", { name: NAMES.t, partition_key: "id" }],
    ["S3 bucket", "/api/s3/buckets", { name: NAMES.b }],
  ];
  for (const [label, path, body] of mk) { const r = await call("POST", path, body); check(`create ${label}`, r.status === 200, `${r.status} ${r.text.slice(0, 120)}`); }
  await sleep(3500);
  await page.reload();
  await sleep(10000);
  const after = [
    ["RDS postgres", "/api/rds/databases", NAMES.pg], ["RDS mysql", "/api/rds/databases", NAMES.my],
    ["SQS queue", "/api/sqs/queues", NAMES.q], ["DynamoDB table", "/api/dynamodb/tables", NAMES.t], ["S3 bucket", "/api/s3/buckets", NAMES.b],
  ];
  for (const [label, path, name] of after) { const r = await call("GET", path, null); check(`${label} still listed after reload`, r.text.includes(name), `${r.status} ${r.text.slice(0, 160)}`); }
  // the RDS console path and the store the registry snapshots must be the SAME object (the root cause)
  const r = await call("GET", "/api/rds/databases", null);
  check("RDS list answers 200", r.status === 200, String(r.status));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server.close();
process.exit(results.length && results.every(Boolean) ? 0 : 1);
