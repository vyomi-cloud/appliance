/* Smoke: RDS Monitoring + Database Insights tabs read the CloudWatch series the recorder / collector publish.
 * A runtime push (POST /_obs/rds-stats - what the docker/pg_stat collector does) feeds real datapoints; an instance
 * with none shows "No data points".   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-aws-rdsobs.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/_wire"}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
const b = await pw.chromium.launch(); const pg = await (await b.newContext({ viewport: { width: 1440, height: 1800 } })).newPage();
await pg.goto(UI + "#/rds", { waitUntil: "networkidle" });
const rds = (action, params) => pg.evaluate(async ([u, a, p]) => (await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/rds/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2014-10-31", ...p }).toString() })).status, [WIRE, action, params]);
const id = `obsdb${Date.now() % 100000}`;
ok("create instance", (await rds("CreateDBInstance", { DBInstanceIdentifier: id, DBInstanceClass: "db.t3.micro", Engine: "postgres", MasterUsername: "u", MasterUserPassword: "Passw0rd!x1", AllocatedStorage: "20" })) < 300);
await pg.goto(UI + `#/rds/databases/${id}`); await pg.waitForTimeout(2000);
await pg.getByRole("tab", { name: "Monitoring" }).click(); await pg.getByTestId("metric-CPUUtilization").waitFor({ timeout: 15000 });
ok("monitoring draws graphs and no fake-unavailable panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
ok("idle -> No data points", /No data/i.test(await pg.getByTestId("metric-CPUUtilization").innerText()));
const push = (stats) => pg.evaluate(async ([u, i, s]) => (await fetch(`${u}/_obs/rds-stats`, { method: "POST", body: JSON.stringify({ dbInstanceIdentifier: i, stats: s }) })).json(), [WIRE, id, stats]);
const r = await push({ cpu_pct: 12.5, mem_used_bytes: 100e6, mem_limit_bytes: 1e9, connections: 7, active_backends: 2, blks_read: 10, blks_hit: 990, xact_commit: 100, xact_rollback: 2, deadlocks: 0 });
ok("push published insights metrics", (r.published || []).includes("DBLoad"), JSON.stringify(r));
await pg.reload(); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Monitoring" }).click(); await pg.waitForTimeout(2500);
ok("CPU graph has a datapoint", !/No data/i.test(await pg.getByTestId("metric-CPUUtilization").innerText()), (await pg.getByTestId("metric-CPUUtilization").innerText()).slice(0, 120));
await pg.getByRole("tab", { name: "Database Insights" }).click(); await pg.getByTestId("metric-DBLoad").waitFor({ timeout: 15000 }); await pg.waitForTimeout(2500);
ok("DB load graph has a datapoint", !/No data/i.test(await pg.getByTestId("metric-DBLoad").innerText()));
ok("cache hit ratio graph has a datapoint", !/No data/i.test(await pg.getByTestId("metric-BufferCacheHitRatio").innerText()));
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
