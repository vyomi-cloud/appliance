/* CloudFormation StackSets + Organizations trusted access (AWS-13): UI <-> native wire.
 *   BASE=http://127.0.0.1:9043 node consoles/tests/smoke-aws-cfnstacksets.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9043";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const N = Date.now() % 100000, SS = `ss-${N}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const ORG = (op, body) => page.evaluate(async ([u, a, t, b]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(b) });
  const tx = await r.text(); return tx ? JSON.parse(tx) : {};
}, [WIRE, auth("organizations"), "AWSOrganizationsV20161128." + op, body]);
const CF = (action, p) => page.evaluate(async ([u, a, body]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body });
  return await r.text();
}, [WIRE, auth("cloudformation"), new URLSearchParams({ Action: action, Version: "2010-05-15", ...p }).toString()]);
await page.goto(UI + "#/cloudformation/stacksets");
await page.getByRole("heading", { name: "Trusted access" }).waitFor({ timeout: 30000 });
await ORG("CreateOrganization", { FeatureSet: "ALL" });
const root = (await ORG("ListRoots", {})).Roots[0].Id;
const ou = (await ORG("CreateOrganizationalUnit", { ParentId: root, Name: "Workloads" })).OrganizationalUnit.Id;
const acct = (await ORG("CreateAccount", { Email: "d@example.com", AccountName: "dev" })).CreateAccountStatus.AccountId;
await ORG("MoveAccount", { AccountId: acct, SourceParentId: root, DestinationParentId: ou });
await page.goto(UI + "#/cloudformation/stacksets");
await page.getByRole("button", { name: "Enable trusted access" }).click();
await page.getByText("Trusted access with AWS Organizations is enabled").waitFor({ timeout: 10000 });
check("trusted access enabled via UI", /ENABLED/.test(await CF("DescribeOrganizationsAccess", {})));
await page.getByRole("button", { name: "Create stack set" }).first().click();
await page.getByRole("textbox", { name: "Stack set name" }).fill(SS);
await page.getByRole("button", { name: /Permission model/ }).click();
await page.getByText("Service-managed permissions", { exact: true }).last().click();
await page.getByRole("textbox", { name: "Template" }).fill(JSON.stringify({ Resources: { B: { Type: "AWS::S3::Bucket" } } }));
await page.getByRole("button", { name: "Create stack set" }).last().click();
await page.getByText(SS).first().waitFor({ timeout: 10000 });
check("service-managed stack set created", /SERVICE_MANAGED/.test(await CF("DescribeStackSet", { StackSetName: SS })));
await page.locator("tr", { hasText: SS }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Actions" }).click();
await page.getByText("Manage stack instances").click();
await page.getByText("Choose OUs").click();
await page.getByRole("option", { name: /Workloads/ }).click();
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Deploy stack instances" }).click();
await page.getByText(acct).first().waitFor({ timeout: 10000 });
check("OU-targeted stack instance listed for the member account", true);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
