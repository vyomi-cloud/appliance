/* Data-plane evaluation panels: VPC Lattice "Test invoke", Network Firewall "Simulate traffic", DNS Firewall "Resolve query".
 *   BASE=http://127.0.0.1:9075 node consoles/tests/smoke-aws-netsimpanels.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9075";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const N = Date.now() % 100000;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 150) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/vpc");
const raw = (svc, path, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return await r.text(); }, [WIRE + path, { ...init, headers: { authorization: auth(svc), ...init.headers } }]);
const ec2 = (p) => raw("ec2", "/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Version: "2016-11-15", ...p }).toString() });
const js = async (svc, target, ver, body) => JSON.parse(await raw(svc, "/", { method: "POST", headers: { "x-amz-target": target, "content-type": `application/x-amz-json-${ver}` }, body: JSON.stringify(body) }));
const rest = async (m, path, body) => JSON.parse((await raw("vpc-lattice", path, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined })) || "{}");
const x = (t, s) => s.match(new RegExp(`<${t}>([\\w-]+)</${t}>`))[1];

const vpc = x("vpcId", await ec2({ Action: "CreateVpc", CidrBlock: "10.50.0.0/16" }));
const sub = x("subnetId", await ec2({ Action: "CreateSubnet", VpcId: vpc, CidrBlock: "10.50.0.0/24", AvailabilityZone: "us-east-1a" }));

// Network Firewall: stateless drop of tcp/22
const rg = await js("network-firewall", "NetworkFirewall_20201112.CreateRuleGroup", "1.0", { RuleGroupName: `nossh${N}`, Type: "STATELESS", Capacity: 10, RuleGroup: { RulesSource: { StatelessRulesAndCustomActions: { StatelessRules: [{ Priority: 1, RuleDefinition: { MatchAttributes: { Protocols: [6], DestinationPorts: [{ FromPort: 22, ToPort: 22 }] }, Actions: ["aws:drop"] } }] } } } });
const pol = await js("network-firewall", "NetworkFirewall_20201112.CreateFirewallPolicy", "1.0", { FirewallPolicyName: `pol${N}`, FirewallPolicy: { StatelessDefaultActions: ["aws:pass"], StatelessFragmentDefaultActions: ["aws:pass"], StatelessRuleGroupReferences: [{ ResourceArn: rg.RuleGroupResponse.RuleGroupArn, Priority: 10 }] } });
await js("network-firewall", "NetworkFirewall_20201112.CreateFirewall", "1.0", { FirewallName: `fw${N}`, FirewallPolicyArn: pol.FirewallPolicyResponse.FirewallPolicyArn, VpcId: vpc, SubnetMappings: [{ SubnetId: sub }] });
await page.goto(UI + "#/vpc/firewalls");
await page.getByText(`fw${N}`).first().waitFor({ timeout: 15000 });
await page.getByRole("row", { name: new RegExp(`fw${N}`) }).getByRole("checkbox").or(page.getByRole("row", { name: new RegExp(`fw${N}`) }).getByRole("radio")).first().check();
await page.getByRole("tab", { name: "Simulate traffic" }).click();
await page.getByRole("textbox", { name: "Destination port" }).fill("22");
await page.getByRole("button", { name: "Simulate traffic" }).last().click();
await page.getByTestId("nfw-result").waitFor({ timeout: 15000 });
check("Network Firewall drops tcp/22", /DROP/.test(await page.getByTestId("nfw-result").innerText()), await page.getByTestId("nfw-result").innerText());
await page.getByRole("textbox", { name: "Destination port" }).fill("443");
await page.getByRole("button", { name: "Simulate traffic" }).last().click();
await page.waitForFunction(() => /PASS/.test(document.querySelector('[data-testid="nfw-result"]')?.innerText || ""), null, { timeout: 15000 });
check("Network Firewall passes tcp/443", true);

// DNS Firewall: block bad.example.com
const dl = await js("route53resolver", "Route53Resolver.CreateFirewallDomainList", "1.1", { Name: `bad${N}` });
await js("route53resolver", "Route53Resolver.UpdateFirewallDomains", "1.1", { FirewallDomainListId: dl.FirewallDomainList.Id, Operation: "ADD", Domains: ["bad.example.com"] });
const g = await js("route53resolver", "Route53Resolver.CreateFirewallRuleGroup", "1.1", { Name: `dg${N}` });
await js("route53resolver", "Route53Resolver.CreateFirewallRule", "1.1", { FirewallRuleGroupId: g.FirewallRuleGroup.Id, FirewallDomainListId: dl.FirewallDomainList.Id, Priority: 1, Action: "BLOCK", BlockResponse: "NXDOMAIN", Name: "blk" });
await js("route53resolver", "Route53Resolver.AssociateFirewallRuleGroup", "1.1", { FirewallRuleGroupId: g.FirewallRuleGroup.Id, VpcId: vpc, Priority: 101, Name: "assoc" });
await page.goto(UI + "#/vpc/dns-firewall-rule-groups");
await page.getByText(`dg${N}`).first().waitFor({ timeout: 15000 });
await page.getByRole("row", { name: new RegExp(`dg${N}`) }).getByRole("checkbox").or(page.getByRole("row", { name: new RegExp(`dg${N}`) }).getByRole("radio")).first().check();
await page.getByRole("tab", { name: "Resolve query" }).click();
await page.getByRole("textbox", { name: "Domain name" }).fill("bad.example.com");
await page.getByRole("button", { name: "Resolve query" }).last().click();
await page.getByTestId("dnsfw-result").waitFor({ timeout: 15000 });
check("DNS Firewall blocks bad.example.com", /BLOCK/.test(await page.getByTestId("dnsfw-result").innerText()) && /NXDOMAIN/.test(await page.getByTestId("dnsfw-result").innerText()), await page.getByTestId("dnsfw-result").innerText());
await page.getByRole("textbox", { name: "Domain name" }).fill("good.example.com");
await page.getByRole("button", { name: "Resolve query" }).last().click();
await page.waitForFunction(() => /No rule matched/.test(document.querySelector('[data-testid="dnsfw-result"]')?.innerText || ""), null, { timeout: 15000 });
check("DNS Firewall lets good.example.com through", true);

// Lattice: unresolvable host -> NXDOMAIN verdict with steps; then associated service -> responds
const net = await rest("POST", "/servicenetworks", { name: `net${N}`, authType: "NONE" });
const svc = await rest("POST", "/services", { name: `svc${N}`, authType: "NONE" });
await rest("POST", "/servicenetworkvpcassociations", { serviceNetworkIdentifier: net.id, vpcIdentifier: vpc });
await rest("POST", "/servicenetworkserviceassociations", { serviceNetworkIdentifier: net.id, serviceIdentifier: svc.id });
await rest("POST", `/services/${svc.id}/listeners`, { name: "http", protocol: "HTTP", port: 80, defaultAction: { fixedResponse: { statusCode: 200 } } });
await page.goto(UI + `#/vpc/lattice-services/${svc.id}`);
await page.getByRole("tab", { name: "Test invoke" }).click();
await page.getByRole("button", { name: /^Source VPC/ }).or(page.locator('[aria-label="Source VPC"]')).first().click();
await page.getByRole("option", { name: new RegExp(vpc) }).click();
await page.getByRole("button", { name: "Test invoke" }).last().click();
await page.getByTestId("invoke-result").waitFor({ timeout: 15000 });
const t = await page.getByTestId("invoke-result").innerText();
check("Lattice test invoke evaluates through the service network", /HTTP 200/.test(t), t);
check("evaluation steps are shown", await page.getByText("Evaluation steps").isVisible());
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
