/* VPC encryption control: create a control on a VPC with a non-encrypting instance, enforce is refused with the blocking resource,
 * monitor shows the audit (UI -> wire).   BASE=http://127.0.0.1:9050 PW=... node consoles/tests/smoke-aws-vpcencryption.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9050";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1800 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0";
await page.goto(UI + "#/vpc");
const ec2 = async (p) => (await page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return await r.text(); },
  [WIRE + "/", { method: "POST", body: new URLSearchParams({ Version: "2016-11-15", ...p }).toString(), headers: { authorization: auth, "content-type": "application/x-www-form-urlencoded" } }]));
const vpc = /<vpcId>([^<]+)</.exec(await ec2({ Action: "CreateVpc", CidrBlock: "10.77.0.0/16" }))[1];
const sub = /<subnetId>([^<]+)</.exec(await ec2({ Action: "CreateSubnet", VpcId: vpc, CidrBlock: "10.77.1.0/24" }))[1];
const img = /<imageId>([^<]+)</.exec(await ec2({ Action: "DescribeImages", "Owner.1": "amazon" }))[1];
await ec2({ Action: "RunInstances", ImageId: img, InstanceType: "m5.large", SubnetId: sub, MinCount: "1", MaxCount: "1" });
await page.goto(UI + "#/vpc");
await page.getByText("Account-level encryption control").first().click();
await page.getByText("Encryption controls").first().waitFor();
check("real page, not a gap modal", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
await page.getByRole("button", { name: /Choose a VPC/ }).click();
await page.getByText(vpc).first().click();
await page.getByRole("button", { name: "Create encryption control" }).click();
await page.getByRole("row", { name: new RegExp(vpc) }).waitFor({ timeout: 8000 });
await page.getByRole("row", { name: new RegExp(vpc) }).getByRole("radio").check({ force: true });
await page.getByText(`Resource audit - ${vpc}`).waitFor({ timeout: 8000 });
await page.getByText("Unencrypted", { exact: true }).first().waitFor({ timeout: 10000 }).catch(() => {});
check("audit flags the m5 instance as unencrypted", /Unencrypted/.test(await page.locator("body").innerText()) && /m5\.large/.test(await page.locator("body").innerText()));
await page.getByRole("button", { name: "Switch to enforce" }).click();
await page.waitForTimeout(800);
check("enforce refused while the m5 instance exists", /cannot enter enforce mode/.test(await page.locator("body").innerText()));
check("no page errors", errors.length === 0, errors.join("; "));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
