/* IAM sweep 2: AWS Organizations on the real backend - organization create, OU/account lifecycle (create OU,
 * create account, invite -> accept, move, remove, close), SCP/RCP create + attach + detach + delete, centralized
 * root access (IAM Enable/Disable...Organizations features), delegated administrator, Organization activity tree.
 * Drives the real UI and cross-checks every step over the native Organizations / IAM wire.
 *
 *   BASE=http://127.0.0.1:9091 node consoles/tests/smoke-aws-iam-sweep2.mjs                                  (offline)
 *   BASE=http://127.0.0.1:9093 UI_PATH=/nano/v4/aws/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-aws-iam-sweep2.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:9091";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "/tmp/smoke-out-iam2";
const N = Date.now() % 100000;
const OU = `ou-ui-${N}`, ACCT = `acct-ui-${N}`, EMAIL = `ui${N}@example.com`, SCP = `scp-ui-${N}`, RCP = `rcp-ui-${N}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 160) : ""}`); };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const sign = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const org = (op, p = {}) => page.evaluate(async ([u, op, p, au]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-amz-json-1.1", "x-amz-target": `AWSOrganizationsV20161128.${op}` }, body: JSON.stringify(p) });
  const t = await r.text(); return { status: r.status, json: t ? JSON.parse(t) : {} };
}, [WIRE, op, p, sign("organizations")]);
const iam = (action) => page.evaluate(async ([u, a, au]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: "2010-05-08" }).toString() });
  return { status: r.status, text: await r.text() };
}, [WIRE, action, sign("iam")]);
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });
const body = () => page.locator("body").innerText();
const badges = () => page.locator('[data-vyomi-not-simulated]').count();
const go = async (hash, heading) => { await page.goto(UI + hash); await page.reload(); await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 40000 }); await page.waitForTimeout(800); };

await page.goto(UI + "#/iam/dashboard");
await page.getByRole("heading", { name: "IAM Dashboard" }).first().waitFor({ timeout: 60000 });

// idempotent reruns: tear down any organization left behind
async function resetOrg() {
  if ((await org("DescribeOrganization")).status !== 200) return;
  await org("DisableAWSServiceAccess", { ServicePrincipal: "iam.amazonaws.com" });
  for (const d of (await org("ListDelegatedAdministrators")).json.DelegatedAdministrators || []) await org("DeregisterDelegatedAdministrator", { AccountId: d.Id, ServicePrincipal: "iam.amazonaws.com" });
  await org("DisableAWSServiceAccess", { ServicePrincipal: "iam.amazonaws.com" });
  const root = (await org("ListRoots")).json.Roots[0];
  for (const a of (await org("ListAccounts")).json.Accounts) if (a.JoinedMethod !== "INVITED" || a.Name !== "Management account") await org("RemoveAccountFromOrganization", { AccountId: a.Id });
  const ous = [];
  const walk = async (pid) => { for (const u of (await org("ListOrganizationalUnitsForParent", { ParentId: pid })).json.OrganizationalUnits || []) { await walk(u.Id); ous.push(u.Id); } };
  await walk(root.Id);
  for (const id of ous) await org("DeleteOrganizationalUnit", { OrganizationalUnitId: id });
  await org("DeleteOrganization");
}
await resetOrg();

// ── 1. No organization yet: honest empty state with a real "Create organization" action
await go("#/iam/organization-activity", "Organization activity");
await page.getByText("Your account is not a member of an organization").waitFor({ timeout: 15000 });
check("Organization activity without an organization offers Create organization (no badge)", (await badges()) === 0);
await page.getByRole("button", { name: "Create organization" }).click();
await page.getByText(/Management account/).first().waitFor({ timeout: 15000 });
check("Create organization -> native DescribeOrganization", (await org("DescribeOrganization")).json.Organization?.FeatureSet === "ALL");
check("Organization activity shows the management account in the tree", (await body()).includes("management account"));
await page.getByText("SegmentedControl", { exact: false }).count();
await page.getByText("List", { exact: true }).first().click();
await page.getByRole("columnheader", { name: /Last IAM activity/ }).waitFor({ timeout: 10000 });
check("List view has a per-account Last IAM activity column", true);
await shot("iam2-org-activity");

// ── 2. Account access manager: OU + account lifecycle
await go("#/iam/account-access-manager", "Organization accounts");
check("Account access manager has no Not-simulated badge", (await badges()) === 0);
await page.getByRole("button", { name: "Create OU" }).click();
await page.getByRole("textbox", { name: "Organizational unit name" }).fill(OU);
await page.getByRole("dialog").getByRole("button", { name: "Create organizational unit" }).click();
await page.getByText(new RegExp(`OU ${OU} created`)).waitFor({ timeout: 10000 });
const root = (await org("ListRoots")).json.Roots[0];
const ous = (await org("ListOrganizationalUnitsForParent", { ParentId: root.Id })).json.OrganizationalUnits;
check("OU created in the UI is visible natively", ous.some((u) => u.Name === OU));
await page.getByRole("button", { name: "Create account" }).click();
await page.getByRole("textbox", { name: "AWS account name" }).fill(ACCT);
await page.getByRole("textbox", { name: "Email address" }).fill(EMAIL);
await page.getByRole("dialog").getByRole("button", { name: "Create AWS account" }).click();
await page.getByText(new RegExp(`Account ${ACCT} created`)).waitFor({ timeout: 10000 });
let accts = (await org("ListAccounts")).json.Accounts;
const acct = accts.find((a) => a.Name === ACCT);
check("Create account -> native ListAccounts (ACTIVE, CREATED)", acct && acct.Status === "ACTIVE" && acct.JoinedMethod === "CREATED");
await page.getByRole("button", { name: "List" }).first().click().catch(() => {});
await page.getByText("List", { exact: true }).first().click();
await page.getByRole("row", { name: new RegExp(ACCT) }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "Move", exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: /Root/ }).click();
await page.getByRole("option", { name: new RegExp(`Root / ${OU}`) }).click();
await page.getByRole("dialog").getByRole("button", { name: "Move AWS account" }).click();
await page.getByText(new RegExp(`Account ${ACCT} moved`)).waitFor({ timeout: 10000 });
const ouId = ous.find((u) => u.Name === OU).Id;
check("Move -> native ListAccountsForParent shows it under the OU", ((await org("ListAccountsForParent", { ParentId: ouId })).json.Accounts || []).some((a) => a.Id === acct.Id));
await page.getByRole("button", { name: "Invite account" }).click();
await page.getByRole("textbox", { name: "AWS account ID" }).fill("111122223333");
await page.getByRole("dialog").getByRole("button", { name: "Send invitation" }).click();
await page.getByRole("button", { name: "Accept as invitee" }).waitFor({ timeout: 10000 });
check("Invite -> OPEN handshake in the UI and natively", ((await org("ListHandshakesForOrganization")).json.Handshakes || []).some((h) => h.State === "OPEN"));
await page.getByRole("button", { name: "Accept as invitee" }).click();
await page.getByText("Invitation accepted").waitFor({ timeout: 10000 });
check("Accepting the invitation adds the account (INVITED)", ((await org("ListAccounts")).json.Accounts || []).some((a) => a.Id === "111122223333" && a.JoinedMethod === "INVITED"));
await shot("iam2-account-access-manager");

// ── 3. SCPs: create -> attach to OU -> detach -> delete
await go("#/iam/service-control-policies", "Service control policies (SCPs)");
check("SCP page has no Not-simulated badge", (await badges()) === 0);
await page.getByRole("link", { name: "FullAWSAccess" }).waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Create policy" }).first().click();
await page.getByRole("textbox", { name: "Policy name" }).fill(SCP);
await page.getByRole("dialog").getByRole("button", { name: "Create policy" }).click();
await page.getByRole("link", { name: SCP }).waitFor({ timeout: 10000 });
check("SCP created in the UI is visible natively", ((await org("ListPolicies", { Filter: "SERVICE_CONTROL_POLICY" })).json.Policies || []).some((p) => p.Name === SCP));
await page.getByRole("link", { name: SCP }).click();
await page.getByRole("heading", { name: SCP }).first().waitFor({ timeout: 15000 });
await page.getByRole("button", { name: /Choose a target/ }).click();
await page.getByRole("option", { name: new RegExp(`OU: Root / ${OU}`) }).click();
await page.getByRole("button", { name: "Attach", exact: true }).click();
await page.getByRole("cell", { name: ouId }).waitFor({ timeout: 10000 });
const scpId = (await org("ListPolicies", { Filter: "SERVICE_CONTROL_POLICY" })).json.Policies.find((p) => p.Name === SCP).Id;
check("Attach -> native ListTargetsForPolicy", ((await org("ListTargetsForPolicy", { PolicyId: scpId })).json.Targets || []).some((t) => t.TargetId === ouId));
// the OU still has no FullAWSAccess, and this is its only SCP: AWS refuses to detach the last one
await page.getByRole("button", { name: "Detach" }).click();
await page.getByText(/at least one SCP/i).first().waitFor({ timeout: 10000 });
check("Detaching the last SCP of a target is refused (ConstraintViolation shown in the UI)", true);
check("Service access report is a registered gap (exactly 1 badge on the SCP detail)", (await badges()) === 1);
await shot("iam2-scp-detail");
await org("DetachPolicy", { PolicyId: scpId, TargetId: ouId }).catch(() => {});
await go("#/iam/service-control-policies", "Service control policies (SCPs)");
await org("AttachPolicy", { PolicyId: "p-FullAWSAccess", TargetId: ouId });
await org("DetachPolicy", { PolicyId: scpId, TargetId: ouId });
await go("#/iam/service-control-policies", "Service control policies (SCPs)");
await page.getByRole("row", { name: new RegExp(SCP) }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "Delete", exact: true }).click();
await page.getByRole("link", { name: SCP }).waitFor({ state: "detached", timeout: 10000 });
check("SCP deleted from the UI is gone natively", !((await org("ListPolicies", { Filter: "SERVICE_CONTROL_POLICY" })).json.Policies || []).some((p) => p.Name === SCP));

// ── 4. RCPs: enable the type, create, list
await go("#/iam/resource-control-policies", "Resource control policies (RCPs)").catch(async () => { await page.getByText("Resource control policies (RCPs) are not enabled").waitFor({ timeout: 15000 }); });
if (await page.getByRole("button", { name: /Enable Resource control policies/ }).count()) await page.getByRole("button", { name: /Enable Resource control policies/ }).click();
await page.getByRole("button", { name: "Create policy" }).first().waitFor({ timeout: 15000 });
await page.getByRole("button", { name: "Create policy" }).first().click();
await page.getByRole("textbox", { name: "Policy name" }).fill(RCP);
await page.getByRole("dialog").getByRole("button", { name: "Create policy" }).click();
await page.getByRole("link", { name: RCP }).waitFor({ timeout: 10000 });
check("RCP enable + create in the UI -> native ListPolicies(RESOURCE_CONTROL_POLICY)", ((await org("ListPolicies", { Filter: "RESOURCE_CONTROL_POLICY" })).json.Policies || []).some((p) => p.Name === RCP));
check("RCP page has no Not-simulated badge", (await badges()) === 0);

// ── 5. Centralized root access + delegated administrator
await go("#/iam/root-access-management", "Root access management").catch(() => {});
await page.getByText("Centralized root access for member accounts").first().waitFor({ timeout: 15000 });
await page.getByText("Root credentials management").first().click();
await page.waitForTimeout(1000);
check("Toggling root credentials management -> IAM ListOrganizationsFeatures", (await iam("ListOrganizationsFeatures")).text.includes("RootCredentialsManagement"));
await page.getByText("Root sessions").first().click();
await page.waitForTimeout(1000);
check("Toggling root sessions -> IAM ListOrganizationsFeatures", (await iam("ListOrganizationsFeatures")).text.includes("RootSessions"));
check("trusted access for iam.amazonaws.com was enabled by the UI", ((await org("ListAWSServiceAccessForOrganization")).json.EnabledServicePrincipals || []).some((s) => s.ServicePrincipal === "iam.amazonaws.com"));
check("Root access management table lists member accounts (Enabled)", (await body()).includes("Enabled") && (await body()).includes(ACCT));
check("Root access management has no Not-simulated badge", (await badges()) === 0);
await shot("iam2-root-access");
await go("#/iam/account-settings/assign-delegated-administrator", "Assign delegated administrator for centralized root access");
await page.getByRole("button", { name: /Choose an account/ }).click();
await page.getByRole("option", { name: new RegExp(acct.Id) }).click();
await page.getByRole("button", { name: "Assign", exact: true }).click();
await page.getByRole("cell", { name: acct.Id }).waitFor({ timeout: 10000 });
check("Assign delegated administrator -> native ListDelegatedAdministrators", ((await org("ListDelegatedAdministrators", { ServicePrincipal: "iam.amazonaws.com" })).json.DelegatedAdministrators || []).some((a) => a.Id === acct.Id));
await go("#/iam/account-settings", "Account settings");
await page.getByText("Centralized root access for member accounts").first().waitFor({ timeout: 15000 });
check("Account settings: centralized root access is real and shows the delegated admin; only Role manager is a gap", (await body()).includes(ACCT) && (await badges()) === 1);
await shot("iam2-account-settings");

// ── 6. cleanup from the UI side: remove + close
await go("#/iam/account-access-manager", "Organization accounts");
await page.getByText("List", { exact: true }).first().click();
await page.getByRole("row", { name: new RegExp(ACCT) }).getByRole("radio").click({ force: true });
await page.getByRole("button", { name: "Close account" }).click();
await page.getByText(/closed/).first().waitFor({ timeout: 10000 });
check("Close account -> native Status SUSPENDED", ((await org("DescribeAccount", { AccountId: acct.Id })).json.Account || {}).Status === "SUSPENDED");
await resetOrg();
console.log("page errors:", errors.length ? errors.slice(0, 3).join(" | ") : "none");
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
