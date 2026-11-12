/* AWS-06 EC2 security-group Sharing tab (RAM): share a security group with an account, see the association, Stop sharing; the wire's
 * DeleteSecurityGroup refuses while shared.
 *   BASE=http://127.0.0.1:9042 node consoles/tests/smoke-aws-ec2ram.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9042";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/ec2");
const ec2 = (action, params) => page.evaluate(async ([u, a, p]) => { const r = await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2016-11-15", ...p }).toString() }); return { status: r.status, text: await r.text() }; }, [WIRE, action, params]);
const N = Date.now() % 100000;
const vpc = (await ec2("CreateVpc", { CidrBlock: "10.44.0.0/16" })).text.match(/<vpcId>(vpc-\w+)<\/vpcId>/)[1];
const sg = (await ec2("CreateSecurityGroup", { GroupName: `shared-${N}`, GroupDescription: "d", VpcId: vpc })).text.match(/<groupId>(sg-\w+)<\/groupId>/)[1];
await page.goto(UI + `#/ec2/security-groups/${sg}`);
await page.getByRole("tab", { name: "Sharing" }).click();
await page.getByRole("button", { name: "Share resource" }).waitFor({ timeout: 10000 });
check("Sharing tab is not the Not-simulated panel", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
await page.getByRole("button", { name: "Share resource" }).click();
await page.getByPlaceholder("my-share").fill(`share-${N}`);
await page.getByRole("dialog").getByRole("textbox").last().fill("210987654321");
await page.getByRole("dialog").getByRole("button", { name: "Share", exact: true }).click();
await page.getByText(new RegExp(`resource-share/rs-`)).first().waitFor({ timeout: 10000 });
check("share association listed", true);
check("delete refused while shared (wire)", (await ec2("DeleteSecurityGroup", { GroupId: sg })).status >= 400);
await page.getByRole("button", { name: "Stop sharing" }).click();
await page.getByText("Not shared with any other account.").waitFor({ timeout: 10000 });
check("stop sharing clears the association", true);
check("delete allowed after unsharing (wire)", (await ec2("DeleteSecurityGroup", { GroupId: sg })).status === 200);
await page.screenshot({ path: `${OUT}/ec2-ram.png`, fullPage: true });
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
