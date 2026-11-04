/* AWS-06 EC2 dashboard: Service health (live probes) and EC2 cost (current inventory priced at AWS list prices vs Vyomi's $0.00).
 *   BASE=http://127.0.0.1:9042 node consoles/tests/smoke-aws-ec2dash.mjs */
import { createRequire } from "node:module";
import { mkdir, readFile } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9042";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH ?? "/_wire"}`;
const OUT = process.env.OUT || "smoke-out";
const prices = JSON.parse(await readFile(new URL("../src/aws/services/ec2/price-table.json", import.meta.url), "utf8"));
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " - " + String(detail).slice(0, 160) : "")); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1800 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/ec2");
const AUTH = "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0";
const ec2 = (action, params) => page.evaluate(async ([u, a, p, auth]) => (await fetch(u + "/", { method: "POST", headers: { authorization: auth, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2016-11-15", ...p }).toString() })).text(), [WIRE, action, params, AUTH]);
const money = async (id) => Number((await page.getByTestId(id).innerText()).replace("$", ""));

await page.goto(UI + "#/ec2/dashboard");
await page.getByText("Service is operating normally").waitFor({ timeout: 15000 });
check("service health widget is live, not Not-simulated", !/AWS Health Dashboard/.test(await page.locator("body").innerText()));
await page.getByTestId("cost-charged").waitFor({ timeout: 15000 });
const baseMonthly = await money("cost-monthly");
check("Vyomi charges $0.00", (await page.getByTestId("cost-charged").innerText()).trim() === "$0.00");

const ami = (await ec2("DescribeImages", {})).match(/<imageId>(ami-\w+)<\/imageId>/)[1];
const iid = (await ec2("RunInstances", { ImageId: ami, MinCount: "1", MaxCount: "1", InstanceType: "m5.large" })).match(/<instanceId>(i-\w+)<\/instanceId>/)[1];
await page.reload();
await page.getByTestId("cost-monthly").waitFor({ timeout: 15000 });
await page.waitForFunction((b) => Number(document.querySelector('[data-testid="cost-monthly"]').innerText.replace("$", "")) > b, baseMonthly, { timeout: 15000 });
const after = await money("cost-monthly");
const rate = prices.vmHourly["m5.large"] * prices.hoursPerMonth;
check("monthly grew by at least the m5.large list price", after - baseMonthly >= Math.round(rate * 100) / 100 - 0.02, baseMonthly + " -> " + after + " (m5.large " + rate.toFixed(2) + ")");
check("by-type table lists running instances", /Instances \(running\)/.test(await page.locator("body").innerText()));
await page.screenshot({ path: OUT + "/ec2-dashboard.png", fullPage: true });
await ec2("TerminateInstances", { "InstanceId.1": iid });
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log("\n" + (results.length - bad.length) + "/" + results.length + " passed");
process.exit(bad.length ? 1 : 0);
