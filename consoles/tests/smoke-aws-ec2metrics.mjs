/* AWS-05 EC2 instance + EBS volume metrics: the Monitoring tabs draw REAL CloudWatch series. The dev server stands in for the offline
 * appliance's docker-exec sampler through POST /_dev/ec2-counters (same parse + publish path); an instance with no samples shows
 * "No data points" (never an invented line).
 *   BASE=http://127.0.0.1:9042 node consoles/tests/smoke-aws-ec2metrics.mjs */
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
const page = await browser.newPage({ viewport: { width: 1440, height: 2000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/ec2");
const ec2 = (action, params) => page.evaluate(async ([u, a, p]) => { const r = await fetch(u + "/", { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2016-11-15", ...p }).toString() }); return r.text(); }, [WIRE, action, params]);
const blob = (rx, tx, cpu, rb, wb, ri, wi) => `Inter-|\n face |\n  eth0: ${rx} ${rx / 100} 0 0 0 0 0 0 ${tx} ${tx / 100} 0 0 0 0 0 0\n---CPU\nusage_usec ${cpu}\n---IO\n254:0 rbytes=${rb} wbytes=${wb} rios=${ri} wios=${wi}\n`;

const ami = (await ec2("DescribeImages", {})).match(/<imageId>(ami-\w+)<\/imageId>/)[1];
const run = await ec2("RunInstances", { ImageId: ami, MinCount: "1", MaxCount: "1", InstanceType: "t3.micro" });
const iid = run.match(/<instanceId>(i-\w+)<\/instanceId>/)[1];
const vols = await ec2("DescribeVolumes", {});
const vid = [...vols.matchAll(/<volumeId>(vol-\w+)<\/volumeId>/g)].map((m) => m[1]).pop();
// no samples yet: honest empty state
await page.goto(UI + `#/ec2/instances/${iid}`);
await page.getByRole("tab", { name: "Monitoring" }).click();
await page.getByTestId("metric-CPUUtilization").waitFor({ timeout: 10000 });
check("monitoring tab draws graphs (not Not-simulated)", !/Not simulated in Vyomi/i.test(await page.locator("body").innerText()));
check("no samples -> No data points", /No data/i.test(await page.getByTestId("metric-CPUUtilization").innerText()));

// feed three real-shaped readings through the sampler path, 60 s apart, ending now
const now = Math.floor(Date.now() / 1000);
const push = (t, args) => page.evaluate(async ([u, i, v, tt, b]) => (await fetch(`${u}?instance=${i}&volume=${v}&vcpus=2&t=${tt}`, { method: "POST", body: b })).json(), [`${BASE}/_dev/ec2-counters`, iid, vid, t, blob(...args)]);
await push(now - 120, [1000, 500, 1_000_000, 0, 0, 0, 0]);
const r1 = await push(now - 60, [51000, 20500, 7_000_000, 1048576, 0, 100, 0]);
const r2 = await push(now, [101000, 40500, 19_000_000, 2097152, 524288, 200, 40]);
check("sampler publishes 14 series per reading", r1.published.length === 14 && r2.published.length === 14);
await page.goto(UI + "#/ec2"); await page.goto(UI + `#/ec2/instances/${iid}`); await page.getByRole("tab", { name: "Monitoring" }).click();
await page.waitForFunction(() => /datapoint/.test(document.querySelector('[data-testid="metric-CPUUtilization"]')?.innerText || ""), null, { timeout: 15000 });
const cpuTxt = await page.getByTestId("metric-CPUUtilization").innerText();
check("CPU graph has datapoints", /2 datapoints/.test(cpuTxt), cpuTxt.replace(/\n/g, " "));
check("CPU latest = 10% (12 s CPU over 60 s x 2 vCPUs)", /latest (10|10\.0)/.test(cpuTxt), cpuTxt.replace(/\n/g, " "));
const netTxt = await page.getByTestId("metric-NetworkIn").innerText();
check("NetworkIn total = 100000 bytes", /total 100000/.test(netTxt), netTxt.replace(/\n/g, " "));
await page.screenshot({ path: `${OUT}/ec2-instance-metrics.png`, fullPage: true });

await page.goto(UI + `#/ec2/volumes/${vid}`);
await page.getByRole("tab", { name: "Monitoring" }).click();
await page.getByTestId("metric-VolumeWriteBytes").waitFor({ timeout: 10000 });
await page.waitForFunction(() => /datapoint/.test(document.querySelector('[data-testid="metric-VolumeWriteBytes"]')?.innerText || ""), null, { timeout: 15000 });
const wTxt = await page.getByTestId("metric-VolumeWriteBytes").innerText();
check("volume write bytes graph", /total 524288/.test(wTxt), wTxt.replace(/\n/g, " "));
await page.screenshot({ path: `${OUT}/ec2-volume-metrics.png`, fullPage: true });
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
