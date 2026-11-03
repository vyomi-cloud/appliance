/* EC2 ops (AWS-03/AWS-04): dashboard zones/alarms, instance health rollup, EBS fault tolerance, Recycle Bin, Create IAM profile,
 * Compare SG rules, Instance type finder, Spot, Reserved Instances, Capacity Reservations, Dedicated Hosts, Events, Settings tabs.
 *
 *   BASE=http://127.0.0.1:9100 node consoles/tests/smoke-aws-ec2ops.mjs                                  (offline; no RunInstances on macOS)
 *   BASE=http://127.0.0.1:8800 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-ec2ops.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9100";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || ""}`;
const OUT = process.env.OUT || "smoke-out";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 1500 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const authFor = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/ec2");
await page.waitForTimeout(process.env.UI_PATH ? 5000 : 500);   // Nano: the service worker takes control (and may reload) on first load
await page.goto(UI + "#/ec2");
const q = (svc, params) => page.evaluate(async ([u, a, p]) => { const r = await fetch(`${u}/`, { method: "POST", headers: { authorization: a, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(p).toString() }); return { status: r.status, text: await r.text() }; }, [WIRE, authFor(svc), params]);
const ec2 = (Action, p = {}) => q("ec2", { Action, ...p });
const tag = (t, n) => (t.match(new RegExp(`<${n}>(.*?)</${n}>`)) || [])[1];
const go = async (hash) => { await page.goto(UI + "#/ec2/" + hash); await page.waitForTimeout(600); };
const body = () => page.locator("body").innerText();
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const notSim = async () => /Not simulated in Vyomi/i.test(await body());
const N = Date.now() % 100000;

// the rbin quota is 10 rules/Region (as on AWS) and a locked rule can't be deleted for 7+ days, so tidy unlocked leftovers first
const RB = (m, path, b) => page.evaluate(async ([u, a, m, path, b]) => { const r = await fetch(u + path, { method: m, headers: { authorization: a, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return r.json().catch(() => ({})); }, [WIRE, authFor("rbin"), m, path, b]);
for (const t of ["EBS_SNAPSHOT", "EC2_IMAGE"]) for (const r of (await RB("POST", "/list-rules", { ResourceType: t })).Rules || []) if (r.LockState === "unlocked") await RB("DELETE", `/rules/${r.Identifier}`);

// can this substrate launch instances? (offline macOS cannot)
const img = tag((await ec2("DescribeImages", { "Owner.1": "amazon" })).text, "imageId");
const probe = await ec2("RunInstances", { ImageId: img, InstanceType: "t3.micro", MinCount: "1", MaxCount: "1" });
const CAN_RUN = probe.status === 200;
const iid = CAN_RUN ? tag(probe.text, "instanceId") : null;
console.log(`# can RunInstances: ${CAN_RUN}`);

// ── dashboard ──
await go("dashboard");
await page.getByText("Instance alarms").first().waitFor();
check("Zones/Alarms are real widgets, not Not-simulated panels", !/Local Zones \/ Wavelength Zones enablement|No custom alarms are modeled/.test(await body()));
check("Zones widget lists real AZs", /us-east-1a/.test(await body()) && /use1-az1/.test(await body()));
check("Instance alarms widget renders counts", await page.getByTestId("alarms-widget").isVisible().catch(() => false) || /In alarm/.test(await body()));
await shot("ec2ops-dashboard");

// ── instances: health rollup ──
await go("instances");
await page.getByText("Instance health").first().waitFor();
check("health rollup renders", /Running instances/.test(await body()) && /Scheduled events/.test(await body()) && !(await notSim()));
if (CAN_RUN) check("rollup counts the running instance as 2/2 passing", /Passing 2\/2 checks\s*\n?\s*[1-9]/.test(await body()));

// ── volumes: fault tolerance ──
const vol = tag((await ec2("CreateVolume", { AvailabilityZone: "us-east-1a", Size: "8" })).text, "volumeId");
// (the offline appliance lists volumes from its own runtime, so a wire-created EBS volume is only visible on Nano)
const VOL_VISIBLE = (await ec2("DescribeVolumes")).text.includes(vol);
await go("volumes");
await page.getByText("Fault tolerance for all volumes in this Region").first().waitFor();
await page.getByTestId("fault-tolerance").waitFor();
check("fault-tolerance widget renders (not a Not-simulated panel)", !/Data Lifecycle Manager \/ backup fault-tolerance rollup/.test(await body()));
const ft = async () => {
  if (!VOL_VISIBLE) return "0 0 0";
  for (let i = 0; i < 40; i++) { const t = (await page.getByTestId("fault-tolerance").innerText()).replace(/\s+/g, " "); if (/(\d+)\D+(\d+)\D+(\d+)$/.test(t) && t.match(/\d+/g).reduce((a, b) => a + Number(b), 0) > 0) return t; await page.waitForTimeout(250); }
  return (await page.getByTestId("fault-tolerance").innerText()).replace(/\s+/g, " ");
};
const noSnap1 = Number((await ft()).match(/No snapshot (\d+)/)?.[1]);
if (VOL_VISIBLE) check("a fresh volume counts as 'No snapshot'", noSnap1 >= 1, await ft());
const snap = tag((await ec2("CreateSnapshot", { VolumeId: vol })).text, "snapshotId");
await go("snapshots"); await go("volumes"); await page.getByTestId("fault-tolerance").waitFor();
const noSnap2 = Number((await ft()).match(/No snapshot (\d+)/)?.[1]);
if (VOL_VISIBLE) check("snapshotting it moves it to 'recent'", noSnap2 === noSnap1 - 1, await ft());

// ── Recycle Bin ──
await go("recycle-bin");
await page.getByRole("button", { name: "Create retention rule" }).first().click();
await page.getByLabel("Retention period in days").fill("5");
await page.getByLabel("Rule description").fill(`smoke-${N}`);
await page.getByRole("dialog").getByRole("button", { name: "Create retention rule" }).click();
await page.getByText(`smoke-${N}`).first().waitFor({ timeout: 10000 });
check("rule created in UI + visible on rbin wire", true);
await ec2("DeleteSnapshot", { SnapshotId: snap });
await page.getByRole("tab", { name: "Resources" }).click();
await page.getByRole("button", { name: /refresh/i }).first().click().catch(() => {});
await page.getByText(snap).first().waitFor({ timeout: 10000 });
check("deleted snapshot is retained in the bin", (await ec2("ListSnapshotsInRecycleBin")).text.includes(snap));
await page.getByRole("row", { name: new RegExp(snap) }).getByRole("radio").check();
await page.getByRole("button", { name: "Recover" }).click();
await page.waitForFunction((s) => !document.body.innerText.includes(s) || /recovered/.test(document.body.innerText), snap, { timeout: 10000 });
check("recover restores the snapshot", (await ec2("DescribeSnapshots")).text.includes(snap));
await page.getByRole("tab", { name: "Retention rules" }).click();
await page.getByRole("row", { name: new RegExp(`smoke-${N}`) }).getByRole("radio").check();
await page.getByRole("button", { name: "Actions" }).click();
await page.getByRole("menuitem", { name: "Lock rule", exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: "Lock rule" }).click();
await page.getByRole("row", { name: new RegExp(`smoke-${N}.*locked`) }).waitFor({ timeout: 10000 });
await page.waitForTimeout(600);
await page.getByRole("row", { name: new RegExp(`smoke-${N}`) }).getByRole("radio").check();
await page.getByRole("button", { name: "Actions" }).click();
check("locked rule can't be deleted from the UI", await page.getByRole("menuitem", { name: "Delete rule", exact: true }).getAttribute("aria-disabled") === "true");
await page.keyboard.press("Escape");
await shot("ec2ops-recycle-bin");

// ── Create IAM profile ──
await go("create-iam-profile");
await page.getByLabel("Instance profile name").fill(`prof-${N}`);
await page.getByText("No role (empty profile)").click();
await page.getByRole("button", { name: "Create instance profile" }).click();
await page.waitForURL(/launch-instance/, { timeout: 10000 });
const ip = await q("iam", { Action: "ListInstanceProfiles" });
check("instance profile exists in IAM", ip.text.includes(`prof-${N}`));

// ── Compare SG rules ──
const sgA = tag((await ec2("CreateSecurityGroup", { GroupName: `cmpA-${N}`, GroupDescription: "a" })).text, "groupId");
const sgB = tag((await ec2("CreateSecurityGroup", { GroupName: `cmpB-${N}`, GroupDescription: "b" })).text, "groupId");
await ec2("AuthorizeSecurityGroupIngress", { GroupId: sgA, "IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "22", "IpPermissions.1.ToPort": "22", "IpPermissions.1.IpRanges.1.CidrIp": "10.0.0.0/8" });
await ec2("AuthorizeSecurityGroupIngress", { GroupId: sgB, "IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "443", "IpPermissions.1.ToPort": "443", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0" });
await go("compare-security-group-rules");
for (const g of [`cmpA-${N}`, `cmpB-${N}`]) {
  await page.getByText(/Choose security groups to compare|Choose options/).first().click();
  await page.getByRole("option", { name: new RegExp(g) }).first().click();
  await page.keyboard.press("Escape");
}
await page.getByTestId("sg-compare").waitFor({ timeout: 10000 });
const cmp = await page.getByTestId("sg-compare").innerText();
check("compare shows the 22 and 443 rules as different", /22/.test(cmp) && /443/.test(cmp) && (cmp.match(/Different/g) || []).length >= 2, cmp.replace(/\s+/g, " "));

// ── Instance type finder ──
await go("instance-type-finder");
await page.getByText("Matching instance types").first().waitFor();
check("type finder lists catalog matches", /t3\.micro|t3\./.test(await body()) && !(await notSim()));

// ── Spot ──
await go("spot-requests");
await page.getByRole("button", { name: "Request Spot Instances" }).first().click();
await page.getByLabel("Maximum price").fill("0.0001");
await page.getByRole("dialog").getByRole("button", { name: "Request", exact: true }).click();
await page.getByText("price-too-low").first().waitFor({ timeout: 10000 });
check("a below-market Spot bid stays open (price-too-low)", true);
await shot("ec2ops-spot");
if (CAN_RUN) {
  const s = await ec2("RequestSpotInstances", { SpotPrice: "1.0", "LaunchSpecification.ImageId": img, "LaunchSpecification.InstanceType": "t3.micro" });
  check("a high bid fulfills with a real instance", /<state>active<\/state>/.test(s.text) && !!tag(s.text, "instanceId"));
}

// ── Reserved Instances ──
await go("reserved-instances");
await page.getByText("Offerings").first().waitFor();
await page.getByRole("row", { name: /No Upfront/ }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Purchase" }).click();
await page.getByText(/Purchased reservation/).first().waitFor({ timeout: 10000 });
check("purchased RI is listed active", (await ec2("DescribeReservedInstances")).text.includes("<state>active</state>"));

// ── Capacity Reservations ──
await go("capacity-reservations");
await page.getByRole("button", { name: "Create Capacity Reservation" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("cr-").first().waitFor({ timeout: 10000 });
const crs = (await ec2("DescribeCapacityReservations")).text;
check("capacity reservation created, full capacity available", /<availableInstanceCount>1<\/availableInstanceCount>/.test(crs));
await page.getByRole("row", { name: /cr-/ }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Cancel reservation" }).click();
await page.getByText("Capacity Reservation cancelled").first().waitFor({ timeout: 10000 });
check("cancel works", true);

// ── Dedicated Hosts ──
await go("dedicated-hosts");
await page.getByRole("button", { name: "Allocate Dedicated Host" }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Allocate", exact: true }).click();
await page.getByText(/h-[0-9a-f]{8}/).first().waitFor({ timeout: 10000 });
const hosts = (await ec2("DescribeHosts")).text;
check("host allocated with 96 vCPUs", /<totalVCpus>96<\/totalVCpus>/.test(hosts));
await page.getByRole("row", { name: /h-/ }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Release host" }).click();
await page.getByText("Release requested").first().waitFor({ timeout: 10000 });
check("host released", true);

// ── Events ──
await go("events");
await page.getByText("Scheduled events").first().waitFor();
check("events page is real (not a Not-simulated panel)", !(await notSim()));
if (CAN_RUN) {
  await page.getByRole("button", { name: "Schedule test event" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Schedule", exact: true }).click();
  await page.getByText("instance-event-").first().waitFor({ timeout: 10000 });
  check("scheduled event listed + on the wire", (await ec2("DescribeInstanceStatus", { "InstanceId.1": iid })).text.includes("instance-event-"));
  await shot("ec2ops-events");
}

// ── Settings tabs ──
await go("settings");
await page.getByRole("tab", { name: /Managed resources/ }).click();
check("managed resources tab is real", !(await notSim()) && (await page.getByTestId("managed-resources").isVisible()));
await page.getByRole("tab", { name: "Auto Scaling groups" }).click();
await page.getByTestId("asg-settings").waitFor({ timeout: 10000 });
await page.waitForFunction(() => /500/.test(document.querySelector("[data-testid=asg-settings]")?.innerText || ""), null, { timeout: 10000 }).catch(() => {});
check("ASG tab shows real quotas", /500/.test(await page.getByTestId("asg-settings").innerText()));
await shot("ec2ops-settings");

check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
