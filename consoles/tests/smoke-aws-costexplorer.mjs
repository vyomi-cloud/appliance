/* Cost Explorer + Saved by Vyomi (AWS-11): launch an EC2 instance on the wire, the dashboard shows real accrued savings. UI <-> native wire.
 *   BASE=http://127.0.0.1:9043 node consoles/tests/smoke-aws-costexplorer.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9043";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const Q = (svc, p) => page.evaluate(async ([u, a, body]) => (await fetch(u + "/", { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body })).text(),
  [WIRE, auth(svc), new URLSearchParams(p).toString()]);
await page.goto(UI + "#/cost-explorer");
await page.getByRole("heading", { name: "Saved by Vyomi" }).waitFor({ timeout: 30000 });
check("empty state before any resource", await page.getByText("Nothing metered yet").isVisible());
const imgs = await Q("ec2", { Action: "DescribeImages", Version: "2016-11-15" });
const ami = /<imageId>(ami-[0-9a-f]+)<\/imageId>/.exec(imgs)?.[1];
const run = await Q("ec2", { Action: "RunInstances", Version: "2016-11-15", ImageId: ami, InstanceType: "m5.large", MinCount: "1", MaxCount: "1" });
check("instance launched on the wire", /<instanceId>i-/.test(run), run.slice(0, 120));
await page.goto(UI + "#/cost-explorer");
await page.reload();
await page.getByRole("heading", { name: "Saved by Vyomi" }).waitFor({ timeout: 30000 });
await page.getByText("Biggest savers").waitFor({ timeout: 10000 });
await page.getByText("m5.large").first().waitFor({ timeout: 10000 });
check("the instance appears under Biggest savers", true);
check("You paid Vyomi $0.00", /You paid Vyomi\s*\n?\s*\$0\.00/.test(await page.locator("body").innerText()));
await page.getByRole("button", { name: /Group by/ }).click();
await page.getByRole("option", { name: "Instance type" }).click();
await page.getByText("Cost in period").waitFor({ timeout: 10000 });
check("cost table regroups by instance type", true);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
