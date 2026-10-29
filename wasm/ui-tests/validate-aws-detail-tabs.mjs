/* AWS detail tabs show the resource's own data (not a copy of another tab):
 *   VPC  -> "VPC details" lists the VPC's CIDR/DHCP/route table/SG
 *   EC2  -> "Status and alarms" lists status checks and differs from "Monitoring"
 * Nano by default (NANO_DIR); offline when VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const offlineUrl = process.env.VYOMI_CONSOLE_URL;
let server = null, base = null;
if (!offlineUrl) ({ server, base } = await startServer());
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const openService = async (name) => {
  await page.locator("#rail >> text=/^\\s*(\\w+\\s*)?" + name + "\\s*$/").first().click();
  await sleep(2500);
};
const tab = async (label) => {
  await page.locator("#main .top-tabs button", { hasText: new RegExp("^\\s*" + label + "\\s*$") }).first().click();
  await sleep(1200);
  return page.locator("#main").innerText();
};
try {
  if (offlineUrl) {
    await page.goto(offlineUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else await bootConsole(page, base, "/aws-console.html");
  const tag = "dt" + Date.now().toString(36);
  const made = await page.evaluate(async (tag) => {
    const post = async (u, b) => { const r = await fetch(u, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) }); return r.status; };
    return [await post("/api/vpc/vpcs", { name: tag + "-vpc", cidr_block: "10.42.0.0/16", cidr: "10.42.0.0/16" }),
            await post("/api/ec2/instances", { name: tag + "-ec2", instance_type: "t3.micro", image_id: "ami-amzn2023-x86_64" })];
  }, tag);
  check("seed VPC + instance created", made.every((s) => s < 300), JSON.stringify(made));
  await sleep(1500);

  await openService("VPC");
  await page.locator("#main tr", { hasText: tag + "-vpc" }).locator("a.id, a").first().click();
  await sleep(2000);
  const overview = await page.locator("#main").innerText();
  const details = await tab("VPC details");
  check("VPC details tab differs from the overview", details !== overview);
  check("VPC details shows CIDR, DHCP option set and main route table", /10\.42\.0\.0\/16/.test(details) && /DHCP option set/i.test(details) && /rtb-/.test(details), details.slice(-300));

  if (offlineUrl) await page.goto(offlineUrl, { waitUntil: "domcontentloaded" }); else await page.goto(base + "/aws-console.html");
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 120000 });
  await sleep(2000);
  await openService("EC2");
  await page.locator("#main tr", { hasText: tag + "-ec2" }).locator("a.id, a").first().click();
  await sleep(2000);
  const status = await tab("Status and alarms");
  const mon = await tab("Monitoring");
  check("Status and alarms lists the status checks", /System reachability/.test(status) && /Instance reachability/.test(status), status.slice(-200));
  check("Monitoring differs from Status and alarms", mon !== status);
  check("no page error", errors.length === 0, errors.join(";"));
} catch (e) { check("flow", false, String(e).split("\n")[0] + " :: " + (await page.locator("#main").innerText().catch(() => "")).slice(0, 300).replace(/\n/g, "|")); }
await browser.close(); if (server) server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
