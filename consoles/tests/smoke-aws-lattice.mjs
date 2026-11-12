/* VPC Lattice (AWS-12): service networks, services + listeners, target groups, VPC association, resource gateway, domain verification.
 * UI <-> native vpc-lattice wire.
 *   BASE=http://127.0.0.1:9041 node consoles/tests/smoke-aws-lattice.mjs
 *   BASE=http://127.0.0.1:8810 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-lattice.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9041";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const N = Date.now() % 100000;
const NET = `smnet-${N}`, SVC = `smsvc-${N}`, TG = `smtg-${N}`, GW = `smgw-${N}`, DOM = `d${N}.example.com`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const L = (method, path, body) => page.evaluate(async ([u, a, m, p, b]) => {
  const r = await fetch(u + p, { method: m, headers: { authorization: a, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  const tx = await r.text(); return { status: r.status, json: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth("vpc-lattice"), method, path, body]);
const ec2 = (params) => page.evaluate(async ([u, a, p]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(p).toString() });
  return await r.text();
}, [WIRE, auth("ec2"), params]);
const body = async () => await page.locator("body").innerText();
const pick = async (label, optionText) => {
  const dlg = page.getByRole("dialog");
  await dlg.getByRole("button", { name: new RegExp(label) }).first().click();
  await page.getByRole("option", { name: new RegExp(optionText) }).first().click();
};

await page.goto(UI + "#/vpc");
await page.getByText("VPC").first().waitFor({ timeout: 30000 });
const vpcId = (await ec2({ Action: "CreateVpc", CidrBlock: "10.55.0.0/16" })).match(/<vpcId>(vpc-\w+)<\/vpcId>/)[1];
const subId = (await ec2({ Action: "CreateSubnet", VpcId: vpcId, CidrBlock: "10.55.1.0/24", AvailabilityZone: "us-east-1a" })).match(/<subnetId>(subnet-\w+)<\/subnetId>/)[1];

// service network via UI
await page.goto(UI + "#/vpc/service-networks");
await page.getByRole("button", { name: "Create service network" }).click();
await page.getByRole("dialog").getByLabel("Service network name").fill(NET);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(NET).first().waitFor({ timeout: 15000 });
const sns = await L("GET", "/servicenetworks");
const sn = (sns.json.items || []).find((x) => x.name === NET);
check("service network created via UI (wire)", !!sn);

// target group via UI
await page.goto(UI + "#/vpc/lattice-target-groups");
await page.getByRole("button", { name: "Create target group" }).click();
await page.getByRole("dialog").getByLabel("Target group name").fill(TG);
await pick("VPC", vpcId);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(TG).first().waitFor({ timeout: 15000 });
const tgs = await L("GET", "/targetgroups");
const tg = (tgs.json.items || []).find((x) => x.name === TG);
check("target group created via UI (wire)", !!tg && tg.vpcIdentifier === vpcId);
await page.getByRole("link", { name: TG }).first().click().catch(async () => { await page.getByText(TG).first().click(); });
await page.getByRole("button", { name: "Register targets" }).waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "Register targets" }).click();
await page.getByRole("dialog").getByLabel("IP address").fill("10.55.1.10");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("10.55.1.10").first().waitFor({ timeout: 15000 });
const lt = await L("POST", `/targetgroups/${tg.id}/listtargets`, {});
check("target registered via UI (wire)", (lt.json.items || []).some((t) => t.id === "10.55.1.10" && t.status === "UNUSED"));

// service + listener via UI
await page.goto(UI + "#/vpc/lattice-services");
await page.getByRole("button", { name: "Create service" }).click();
await page.getByRole("dialog").getByLabel("Service name").fill(SVC);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(SVC).first().waitFor({ timeout: 15000 });
const svcs = await L("GET", "/services");
const svc = (svcs.json.items || []).find((x) => x.name === SVC);
check("service created via UI (wire)", !!svc && /vpc-lattice-svcs/.test(svc.dnsEntry.domainName));
await page.goto(UI + `#/vpc/lattice-services/${svc.id}`);
await page.getByRole("button", { name: "Add listener" }).waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "Add listener" }).click();
await page.getByRole("dialog").getByLabel("Listener name").fill("http-80");
await pick("Target group", TG);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("http-80").first().waitFor({ timeout: 15000 });
const ls = await L("GET", `/services/${svc.id}/listeners`);
check("listener created via UI (wire)", (ls.json.items || []).some((l) => l.name === "http-80" && l.port === 80));
const tgd = await L("GET", `/targetgroups/${tg.id}`);
check("target group now in use by the service", (tgd.json.serviceArns || []).length === 1);
const del = await L("DELETE", `/targetgroups/${tg.id}`);
check("in-use target group delete is refused (409)", del.status === 409);

// VPC association via UI
await page.goto(UI + `#/vpc/service-networks/${sn.id}`);
await page.getByRole("button", { name: "Create VPC association" }).waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "Create VPC association" }).click();
await pick("VPC", vpcId);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(vpcId).first().waitFor({ timeout: 15000 });
let va; for (let i = 0; i < 20; i++) { va = await L("GET", `/servicenetworkvpcassociations?serviceNetworkIdentifier=${sn.id}`); if ((va.json.items || []).some((a) => a.vpcId === vpcId)) break; await page.waitForTimeout(500); }
check("VPC association created via UI (wire)", (va.json.items || []).some((a) => a.vpcId === vpcId));

// resource gateway via UI
await page.goto(UI + "#/vpc/resource-gateways");
await page.getByRole("button", { name: "Create resource gateway" }).click();
await page.getByRole("dialog").getByLabel("Resource gateway name").fill(GW);
await pick("VPC", vpcId);
await pick("Subnet", subId);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(GW).first().waitFor({ timeout: 15000 });
const gws = await L("GET", "/resourcegateways");
check("resource gateway created via UI (wire)", (gws.json.items || []).some((g) => g.name === GW && g.subnetIds.includes(subId)));

// domain verification via UI
await page.goto(UI + "#/vpc/domain-verifications");
await page.getByRole("button", { name: "Start domain verification" }).click();
await page.getByRole("dialog").getByLabel("Domain name").fill(DOM);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(DOM).first().waitFor({ timeout: 15000 });
check("domain verification shows the TXT challenge", /vpc-lattice-verification=/.test(await body()));
await page.screenshot({ path: `${OUT}/lattice.png` });

// the honest-gap panel is gone
await page.goto(UI + "#/vpc/service-networks");
await page.getByText(NET).first().waitFor({ timeout: 15000 });
check("no 'Not simulated' panel on service networks", !/Not simulated/i.test(await body()));
check("no page errors", errors.length === 0, errors[0]);
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
