/* Migrate a server (MGN): UI <-> native mgn wire <-> EC2 wire.  BASE=http://127.0.0.1:9101 node consoles/tests/smoke-aws-mgn.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9101";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const HOST = `web-${Date.now() % 100000}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const M = (op, body) => page.evaluate(async ([u, a, o, b]) => {
  const r = await fetch(`${u}/${o}`, { method: "POST", headers: { authorization: a, "content-type": "application/json" }, body: JSON.stringify(b || {}) });
  const t = await r.text(); return { status: r.status, json: t ? JSON.parse(t) : {} };
}, [WIRE, auth("mgn"), op, body]);
const EC2 = (p) => page.evaluate(async ([u, a, p]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Version: "2016-11-15", ...p }).toString() });
  return await r.text();
}, [WIRE, auth("ec2"), p]);
const body = async () => await page.locator("body").innerText();
await page.goto(UI + "#/ec2");
await page.getByText("EC2").first().waitFor({ timeout: 30000 });
const vpc = await EC2({ Action: "CreateVpc", CidrBlock: "10.88.0.0/16" });
const vpcId = /<vpcId>(.*?)<\/vpcId>/.exec(vpc)[1];
const sub = /<subnetId>(.*?)<\/subnetId>/.exec(await EC2({ Action: "CreateSubnet", VpcId: vpcId, CidrBlock: "10.88.1.0/24" }))[1];
const tpl = await M("CreateReplicationConfigurationTemplate", { stagingAreaSubnetId: sub });
check("template via wire", tpl.status === 201);
await page.goto(UI + "#/ec2/migrate-a-server");
await page.getByText("Source servers").first().waitFor({ timeout: 15000 });
check("page has no Not-simulated badge", !/Not simulated/i.test(await body()));
await page.getByRole("button", { name: "Add source server" }).click();
await page.getByLabel("Hostname").fill(HOST);
await page.getByRole("button", { name: "Add", exact: true }).click();
await page.getByText(HOST).first().waitFor({ timeout: 15000 });
check("source server registered via UI", true);
// wait for replication to reach CONTINUOUS (records-only, time-driven)
await page.waitForTimeout(7000);
await page.getByRole("button", { name: "Refresh" }).first().click().catch(() => {});
await page.getByRole("row").filter({ hasText: HOST }).getByRole("radio").check();
await page.getByText("READY_FOR_TEST").first().waitFor({ timeout: 15000 });
check("replication reached READY_FOR_TEST", true);
await page.getByRole("button", { name: "Launch test instance" }).click();
await page.getByText("TEST_IN_PROGRESS").first().waitFor({ timeout: 15000 });
const srv = (await M("DescribeSourceServers", {})).json.items.find((s) => s.sourceProperties.identificationHints.hostname === HOST);
const iid = srv.launchedInstance.ec2InstanceID;
const d = await EC2({ Action: "DescribeInstances", "InstanceId.1": iid });
check("test launched a real EC2 instance", d.includes(iid), iid);
await page.getByRole("button", { name: "Terminate target instance" }).click();
await page.getByText("READY_FOR_TEST").first().waitFor({ timeout: 15000 });
const d2 = await EC2({ Action: "DescribeInstances", "InstanceId.1": iid });
check("terminate removed the target instance", /<name>terminated<\/name>/.test(d2));
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
