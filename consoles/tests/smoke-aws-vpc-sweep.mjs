/* AWS VPC sweep: VPN (customer/virtual private gateways, VPN connections, Client VPN, concentrators),
 * route propagation + edge associations, VPC CIDRs, Traffic Mirroring, TGW policy tables/multicast/metering.
 * Drives the real UI and cross-checks each step over the native EC2 Query wire.
 *
 *   BASE=http://127.0.0.1:9111 node consoles/tests/smoke-aws-vpc-sweep.mjs                                  (offline)
 *   BASE=http://127.0.0.1:9113 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-vpc-sweep.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9111";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "/tmp/smoke-out-vpcsweep";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const sign = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0`;
const ec2 = (Action, params = {}) => page.evaluate(async ([u, au, Action, params]) => {
  const body = new URLSearchParams({ Action, Version: "2016-11-15", ...params }).toString();
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-www-form-urlencoded" }, body });
  return { status: r.status, text: await r.text() };
}, [WIRE, sign, Action, params]);
const id = (t, tag) => (t.match(new RegExp(`<${tag}>(.*?)</${tag}>`)) || [])[1];
const body = () => page.locator("body").innerText();
const badges = () => page.locator("[data-vyomi-not-simulated]").count();
const go = async (hash, heading) => { await page.goto(UI + hash); await page.reload(); await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 40000 }); await page.waitForTimeout(800); };
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const pick = async (label, optionText) => { await page.getByRole("button", { name: new RegExp(label) }).last().click(); await page.getByRole("option", { name: new RegExp(optionText) }).first().click(); };

await page.goto(UI + "#/vpc/dashboard");
await page.getByRole("heading", { name: /VPC dashboard|Resources by Region/ }).first().waitFor({ timeout: 60000 }).catch(() => {});

// ── seed a VPC / subnet / TGW over the wire ──
const vpc = id((await ec2("CreateVpc", { CidrBlock: "10.91.0.0/16" })).text, "vpcId");
const sub = id((await ec2("CreateSubnet", { VpcId: vpc, CidrBlock: "10.91.1.0/24" })).text, "subnetId");
const tgw = id((await ec2("CreateTransitGateway", { "Options.MulticastSupport": "enable" })).text, "transitGatewayId");

// ── every previously-honest page is a real page now ──
for (const [hash, heading] of [["customer-gateways", "Customer gateways"], ["virtual-private-gateways", "Virtual private gateways"], ["vpn-connections", "Site-to-Site VPN connections"],
  ["vpn-concentrators", "Site-to-Site VPN Concentrators"], ["client-vpn-endpoints", "Client VPN endpoints"], ["mirror-targets", "Mirror targets"], ["mirror-filters", "Mirror filters"],
  ["mirror-sessions", "Mirror sessions"], ["transit-gateway-policy-tables", "Transit gateway policy tables"], ["transit-gateway-multicast", "Transit gateway multicast"], ["metering-policies", "Metering policies"]]) {
  await go(`#/vpc/${hash}`, heading);
  check(`${heading}: real page, no Not-simulated badge`, (await badges()) === 0 && (await page.getByRole("button", { name: /^Create|Associate|Attach/ }).count()) > 0);
}

// ── Customer gateway: create through the UI ──
await go("#/vpc/customer-gateways", "Customer gateways");
await page.getByRole("button", { name: "Create customer gateway" }).click();
await page.getByRole("textbox", { name: "IP address" }).fill("203.0.113.55");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
const cgwList = await ec2("DescribeCustomerGateways");
check("UI-created customer gateway exists on the wire", cgwList.text.includes("203.0.113.55"));
check("Customer gateways list shows it", (await body()).includes("203.0.113.55"));
await page.getByRole("button", { name: "Create customer gateway" }).click();
await page.getByRole("textbox", { name: "IP address" }).fill("not-an-ip");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1200);
check("invalid IP is rejected with an error in the modal", (await body()).toLowerCase().includes("invalid"));
await page.getByRole("button", { name: "Cancel" }).click();
const cgw = id(cgwList.text, "customerGatewayId");

// ── VGW + VPN connection + propagation, driven over the wire then verified in the UI ──
const vgw = id((await ec2("CreateVpnGateway", { Type: "ipsec.1" })).text, "vpnGatewayId");
await go("#/vpc/virtual-private-gateways", "Virtual private gateways");
await page.locator("tr", { hasText: vgw }).locator("input[type=checkbox]").check({ force: true });
await page.getByRole("button", { name: "Attach to VPC" }).click();
await pick("VPC", vpc);
await page.getByRole("button", { name: "Confirm" }).click();
await page.waitForTimeout(1500);
check("UI attach -> VGW attached to the VPC on the wire", (await ec2("DescribeVpnGateways", { "VpnGatewayId.1": vgw })).text.includes(`<vpcId>${vpc}</vpcId>`));
const vpn = id((await ec2("CreateVpnConnection", { CustomerGatewayId: cgw, VpnGatewayId: vgw, Type: "ipsec.1", "Options.StaticRoutesOnly": "true" })).text, "vpnConnectionId");
await go("#/vpc/vpn-connections", "Site-to-Site VPN connections");
await page.locator("tr", { hasText: vpn }).locator("input[type=checkbox]").check({ force: true });
await page.getByRole("button", { name: "Add static route" }).click();
await page.getByRole("textbox", { name: "IP prefix" }).fill("192.168.91.0/24");
await page.getByRole("button", { name: "Confirm" }).click();
await page.waitForTimeout(1500);
check("UI static route lands on the VPN connection", (await ec2("DescribeVpnConnections", { "VpnConnectionId.1": vpn })).text.includes("192.168.91.0/24"));
await page.locator("tr", { hasText: vpn }).locator("input[type=checkbox]").check({ force: true });
await page.getByRole("tab", { name: "Tunnel details" }).click();
const txt = await body();
check("tunnel details honest: two tunnels DOWN with the no-IPsec-peer message", (txt.match(/DOWN/g) || []).length >= 2 && txt.includes("no IPsec peer"));
await shot("vpn-connection");

// route propagation through the route-table UI
const rtb = id((await ec2("CreateRouteTable", { VpcId: vpc })).text, "routeTableId");
await go(`#/vpc/route-tables/${rtb}`, new RegExp(rtb));
await page.getByRole("tab", { name: "Route propagation" }).click();
await page.getByRole("button", { name: "Edit route propagation" }).click();
await pick("Virtual private gateway", vgw);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
const rtx = (await ec2("DescribeRouteTables", { "RouteTableId.1": rtb })).text;
check("UI enable propagation -> propagated route on the wire", rtx.includes("EnableVgwRoutePropagation") && rtx.includes("192.168.91.0/24"));
await page.getByRole("tab", { name: "Routes" }).click();
check("Routes tab shows the propagated route as Propagated: Yes", (await body()).includes("192.168.91.0/24") && (await page.locator("tr", { hasText: "192.168.91.0/24" }).innerText()).includes("Yes"));
await shot("route-propagation");
// netsim honours it
const eni = id((await ec2("CreateNetworkInterface", { SubnetId: sub })).text, "networkInterfaceId");
await ec2("AssociateRouteTable", { RouteTableId: rtb, SubnetId: sub });
const nip = id((await ec2("CreateNetworkInsightsPath", { Source: eni, DestinationIp: "192.168.91.7", Protocol: "tcp", DestinationPort: "443" })).text, "networkInsightsPathId");
const an = (await ec2("StartNetworkInsightsAnalysis", { NetworkInsightsPathId: nip })).text;
check("Reachability Analyzer: the propagated prefix is reachable via the VPN", an.includes("<networkPathFound>true</networkPathFound>"));

// edge association tab
const igw = id((await ec2("CreateInternetGateway")).text, "internetGatewayId");
await ec2("AttachInternetGateway", { InternetGatewayId: igw, VpcId: vpc });
const rtb2 = id((await ec2("CreateRouteTable", { VpcId: vpc })).text, "routeTableId");
await go(`#/vpc/route-tables/${rtb2}`, new RegExp(rtb2));
await page.getByRole("tab", { name: "Edge associations" }).click();
await page.getByRole("button", { name: "Edit edge associations" }).click();
await pick("Associated gateway", igw);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
check("UI edge association -> gatewayId association on the wire", (await ec2("DescribeRouteTables", { "RouteTableId.1": rtb2 })).text.includes(`<gatewayId>${igw}</gatewayId><main>false</main>`));

// ── VPC CIDRs tab ──
await go(`#/vpc/vpcs/${vpc}`, new RegExp(vpc));
await page.getByRole("tab", { name: "CIDRs" }).click();
await page.getByRole("button", { name: "Add new CIDR" }).click();
await page.getByRole("textbox", { name: /IPv4 CIDR/ }).fill("10.92.0.0/16");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
check("UI secondary CIDR associated on the wire", (await ec2("DescribeVpcs", { "VpcId.1": vpc })).text.includes("<cidrBlock>10.92.0.0/16</cidrBlock>"));
await page.getByRole("button", { name: "Add new CIDR" }).click();
await page.getByRole("textbox", { name: /IPv4 CIDR/ }).fill("10.91.5.0/24");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1200);
check("overlapping CIDR rejected with EC2's error", (await body()).includes("conflicts"));
await page.getByRole("button", { name: "Cancel" }).click();
await shot("vpc-cidrs");

// ── Client VPN ──
const cv = id((await ec2("CreateClientVpnEndpoint", { ClientCidrBlock: "10.201.0.0/16", ServerCertificateArn: "arn:aws:acm:us-east-1:123456789012:certificate/x", "Authentication.1.Type": "certificate-authentication", "Authentication.1.MutualAuthentication.ClientRootCertificateChainArn": "arn:aws:acm:us-east-1:123456789012:certificate/y", VpcId: vpc })).text, "clientVpnEndpointId");
await go("#/vpc/client-vpn-endpoints", "Client VPN endpoints");
await page.locator("tr", { hasText: cv }).locator("input[type=checkbox]").check({ force: true });
await page.getByRole("button", { name: "Associate target network" }).click();
await pick("Subnet", sub);
await page.getByRole("button", { name: "Confirm" }).click();
await page.waitForTimeout(1500);
check("UI target-network association -> endpoint available", (await ec2("DescribeClientVpnEndpoints", { "ClientVpnEndpointId.1": cv })).text.includes("<code>available</code>"));
await page.getByRole("tab", { name: "Route table" }).click();
await page.waitForTimeout(1500);
check("Client VPN route table lists the auto-created VPC route", (await body()).includes("10.91.0.0/16"));
await page.getByRole("tab", { name: "Connections" }).click();
await page.waitForTimeout(1500);
check("Connections tab honest: no OpenVPN server", (await body()).includes("no OpenVPN server"));
await shot("client-vpn");

// ── Traffic Mirroring ──
const eni2 = id((await ec2("CreateNetworkInterface", { SubnetId: sub })).text, "networkInterfaceId");
const tt = id((await ec2("CreateTrafficMirrorTarget", { NetworkInterfaceId: eni2 })).text, "trafficMirrorTargetId");
await go("#/vpc/mirror-filters", "Mirror filters");
await page.getByRole("button", { name: "Create traffic mirror filter" }).click();
await page.getByRole("textbox", { name: "Description" }).fill(`flt-${N}`);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
const flt = id((await ec2("DescribeTrafficMirrorFilters")).text, "trafficMirrorFilterId");
check("UI-created mirror filter exists on the wire", (await ec2("DescribeTrafficMirrorFilters")).text.includes(`flt-${N}`));
await go("#/vpc/mirror-sessions", "Mirror sessions");
await page.getByRole("button", { name: "Create traffic mirror session" }).click();
await pick("Mirror source", eni);
await pick("Mirror target", tt);
await pick("Mirror filter", flt);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
check("UI-created mirror session exists on the wire", (await ec2("DescribeTrafficMirrorSessions")).text.includes(eni));
await shot("mirror-sessions");

// ── TGW extras ──
await go("#/vpc/transit-gateway-policy-tables", "Transit gateway policy tables");
await page.getByRole("button", { name: "Create policy table" }).click();
await pick("Transit gateway", tgw);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
check("UI-created policy table exists on the wire", (await ec2("DescribeTransitGatewayPolicyTables")).text.includes(tgw));
await go("#/vpc/metering-policies", "Metering policies");
await page.getByRole("button", { name: "Create metering policy" }).click();
await pick("Transit gateway", tgw);
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
check("UI-created metering policy exists on the wire", (await ec2("DescribeTransitGatewayMeteringPolicies")).text.includes(tgw));

// ── honest pages stay honest ──
for (const [hash, heading] of [["firewalls", "Firewalls"], ["service-networks", "Service networks"]]) {
  await go(`#/vpc/${hash}`, heading);
  check(`${heading}: still an honest page (badge present)`, (await badges()) > 0 || (await body()).toLowerCase().includes("not simulated"));
}
check("no uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
