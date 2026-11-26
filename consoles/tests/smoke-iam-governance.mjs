/* IAM governance UI <-> native wires: AWS Organizations (SCP attach/detach, effective, S3 public access), GCP org policy (hierarchy,
 * enforce, dry-run, inheritance), Azure management groups (create, move subscription, MG role + policy assignment).
 * Asserts the SAVE PAYLOADS that leave the browser and the state read back from the wire.
 *   python3 consoles/dev_server.py --port 9111 &  BASE=http://127.0.0.1:9111 NODE_PATH=... node consoles/tests/smoke-iam-governance.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9111";
const SHOTS = process.env.SHOTS || "/tmp/gov-shots";
import { mkdirSync } from "node:fs"; mkdirSync(SHOTS, { recursive: true });
const N = Date.now() % 100000;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch();
const mk = async () => { const p = await browser.newPage({ viewport: { width: 1500, height: 1000 } }); p.errs = []; p.on("pageerror", (e) => p.errs.push(e.message)); p.posts = []; p.on("request", (r) => { if (r.method() !== "GET") p.posts.push({ m: r.method(), u: r.url(), b: r.postData() }); }); return p; };
const aws = auth => ({ authorization: `AWS4-HMAC-SHA256 Credential=X/20261101/us-east-1/${auth}/aws4_request, SignedHeaders=host, Signature=0` });
const orgCall = async (op, payload) => { const r = await fetch(`${BASE}/_wire/`, { method: "POST", headers: { ...aws("organizations"), "content-type": "application/x-amz-json-1.1", "x-amz-target": "AWSOrganizationsV20161128." + op }, body: JSON.stringify(payload || {}) }); return r.json(); };
const govGet = async (c, w) => (await fetch(`${BASE}/_wire/api/iam/${c}/governance/${w}`)).json();

// ───────── AWS ─────────
await orgCall("CreateOrganization", { FeatureSet: "ALL" });
const roots = (await orgCall("ListRoots")).Roots; const root = roots[0].Id;
await orgCall("EnablePolicyType", { RootId: root, PolicyType: "SERVICE_CONTROL_POLICY" });
const ou = (await orgCall("CreateOrganizationalUnit", { ParentId: root, Name: `Workloads${N}` })).OrganizationalUnit;
const acct = (await orgCall("CreateAccount", { Email: `a${N}@x.io`, AccountName: `team${N}` })).CreateAccountStatus;
let p = await mk();
await p.goto(`${BASE}/v4/aws/#/iam/organization-governance`);
await p.getByText("Roots, OUs and accounts").first().waitFor({ timeout: 30000 });
await p.screenshot({ path: `${SHOTS}/aws-org-tree.png` });
check("org tree lists the OU", (await p.locator("body").innerText()).includes(`Workloads${N}`));
// create an SCP in the UI
await p.getByRole("tab", { name: "Create policy" }).click();
await p.getByLabel("New policy name").fill(`DenyDeleteBucket${N}`);
await p.getByRole("button", { name: "Deny an action" }).click();
await p.getByRole("button", { name: "Create policy" }).last().click();
await p.getByText(`created`).first().waitFor({ timeout: 10000 });
const cp = p.posts.find((x) => /CreatePolicy/.test(JSON.stringify(x.b || "")) || (x.b || "").includes("DenyDeleteBucket"));
check("CreatePolicy payload has SCP type + doc", cp && cp.b.includes("SERVICE_CONTROL_POLICY") && cp.b.includes("s3:DeleteBucket"), cp?.b);
await p.screenshot({ path: `${SHOTS}/aws-create-policy.png` });
// attach to OU
await p.getByRole("tab", { name: "Organization structure" }).click();
await p.getByRole("row").filter({ hasText: `Workloads${N}` }).getByRole("radio").check();
await p.getByRole("button", { name: /Policy to attach/ }).click();
await p.getByRole("option", { name: new RegExp(`DenyDeleteBucket${N}`) }).click();
await p.getByRole("button", { name: "Attach policy" }).click();
await p.getByText("Policy attached.").first().waitFor({ timeout: 10000 });
const ap = p.posts.find((x) => (x.b || "").includes('"TargetId"') && (x.b || "").includes(ou.Id));
check("AttachPolicy payload targets the OU", !!ap, ap?.b);
await orgCall("MoveAccount", { AccountId: acct.AccountId, SourceParentId: root, DestinationParentId: ou.Id });
await p.reload(); await p.getByText("Roots, OUs and accounts").first().waitFor();
const ouRow = p.getByRole("row").filter({ hasText: `Workloads${N}` });
check("OU row shows attached SCP", (await ouRow.innerText()).includes(`DenyDeleteBucket${N}`));
// effective policies for the account
await p.getByRole("tab", { name: "Effective policies" }).click();
await p.getByRole("button", { name: /Account Account Choose/ }).click();
await p.getByRole("option", { name: new RegExp(acct.AccountId) }).click();
await p.getByText("Deny statements in force").first().waitFor({ timeout: 10000 });
check("effective view shows the inherited deny", (await p.locator("body").innerText()).includes(`DenyDeleteBucket${N}`));
await p.getByRole("button", { name: "Test", exact: true }).click();
await p.getByText(/Denied/).first().waitFor({ timeout: 10000 });
check("check panel reports Denied by SCP", true);
await p.screenshot({ path: `${SHOTS}/aws-effective.png` });
// detach
await p.getByRole("tab", { name: "Organization structure" }).click();
await p.getByRole("button", { name: new RegExp(`Detach DenyDeleteBucket${N} from`) }).click();
await p.getByText("Policy detached.").first().waitFor({ timeout: 10000 });
const t = await govGet("aws", "organization");
check("detach reflected on the wire", !JSON.stringify(t.nodes.find((n) => n.id === ou.Id).policies).includes(`DenyDeleteBucket${N}`));
// S3 public access overview
await fetch(`${BASE}/_wire/pub-${N}`, { method: "PUT", headers: aws("s3") });
await fetch(`${BASE}/_wire/pub-${N}?policy`, { method: "PUT", headers: aws("s3"), body: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: "*", Action: "s3:GetObject", Resource: `arn:aws:s3:::pub-${N}/*` }] }) });
await p.goto(`${BASE}/v4/aws/#/s3/public-access-overview`);
await p.getByText(`pub-${N}`).first().waitFor({ timeout: 20000 });
check("overview flags the public bucket", /Public/.test(await p.getByRole("row").filter({ hasText: `pub-${N}` }).innerText()));
await p.screenshot({ path: `${SHOTS}/aws-s3-overview.png` });
check("aws: no page errors", p.errs.length === 0, p.errs.join("|")); await p.close();

// ───────── GCP ─────────
p = await mk();
await p.goto(`${BASE}/v4/gcp/#/iam-admin/governance`);
await p.getByText("Organization policy constraints").first().waitFor({ timeout: 30000 });
await p.screenshot({ path: `${SHOTS}/gcp-hierarchy.png` });
const node = (await p.getByTestId("selected-node").innerText());
check("a node is selected", /projects\//.test(node), node);
await p.getByPlaceholder("Filter constraints").fill("disableServiceAccountKeyCreation");
await p.getByRole("button", { name: "Manage policy iam.disableServiceAccountKeyCreation" }).click();
await p.getByLabel("Enforcement").click(); await p.getByRole("option", { name: "Enforce", exact: true }).click();
await p.getByRole("button", { name: "Set policy" }).click();
await p.waitForTimeout(800);
const sp = p.posts.find((x) => /\/policies/.test(x.u) && ["POST","PATCH"].includes(x.m));
check("Org Policy POST payload enforce:true", sp && sp.b.includes('"enforce":true') && sp.b.includes("disableServiceAccountKeyCreation"), sp?.b);
// dry-run on a second constraint
await p.getByPlaceholder("Filter constraints").fill("disableServiceAccountCreation");
await p.getByRole("button", { name: "Manage policy iam.disableServiceAccountCreation" }).click();
await p.getByLabel(/Dry run/).check();
await p.getByLabel("Enforcement").click(); await p.getByRole("option", { name: "Enforce", exact: true }).click();
await p.getByRole("button", { name: "Set policy" }).click();
await p.waitForTimeout(800);
const dp = p.posts.filter((x) => /\/policies/.test(x.u) && ["POST","PATCH"].includes(x.m)).pop();
check("dry-run saved as dryRunSpec (no spec)", dp.b.includes("dryRunSpec") && !dp.b.includes('"spec"'), dp.b);
await p.screenshot({ path: `${SHOTS}/gcp-constraints.png` });
const v = await govGet("gcp", `orgpolicy?node=${encodeURIComponent(node.replace("Selected: ", "").trim())}`);
const keyc = v.constraints.find((c) => /disableServiceAccountKeyCreation/.test(c.constraint));
check("engine view: key creation enforced", keyc && keyc.effective.enforce === true);
// check panel: dry run would block
await p.getByRole("combobox", { name: /^Constraint/ }).click(); await p.getByRole("option", { name: "iam.disableServiceAccountCreation" }).click();
await p.getByRole("button", { name: "Check", exact: true }).click();
await p.getByTestId("check-result").waitFor({ timeout: 10000 });
check("dry-run check warns, does not block", /Allowed now/.test(await p.getByTestId("check-result").innerText()) && /Dry run would block/.test(await p.getByTestId("check-result").innerText()), await p.getByTestId("check-result").innerText());
await p.getByRole("tab", { name: "Inheritance" }).click();
await p.screenshot({ path: `${SHOTS}/gcp-inheritance.png` });
check("inheritance tab lists the enforced constraint", (await p.locator("body").innerText()).includes("disableServiceAccountKeyCreation") || /Disable service account key creation/i.test(await p.locator("body").innerText()));
check("gcp: no page errors", p.errs.length === 0, p.errs.join("|")); await p.close();

// ───────── Azure ─────────
p = await mk();
await p.goto(`${BASE}/v4/azure/#/managementgroups`);
await p.getByRole("tree").waitFor({ timeout: 30000 });
await p.screenshot({ path: `${SHOTS}/azure-mg-initial.png` });
await p.getByLabel("Management group ID").fill(`mg-prod-${N}`);
await p.getByLabel("Display name").fill("Production");
await p.getByRole("button", { name: "Create", exact: true }).click();
await p.getByText(`Management group mg-prod-${N} created.`).waitFor({ timeout: 10000 });
const cr = p.posts.find((x) => x.m === "PUT" && x.u.includes(`/managementGroups/mg-prod-${N}`));
check("MG PUT payload has displayName + parent", cr && cr.b.includes('"displayName":"Production"') && cr.b.includes("details"), cr?.b);
await p.locator(`[data-mg="mg-prod-${N}"]`).click();
await p.getByRole("tab", { name: "Details" }).click();
const subName = (await govGet("azure", "hierarchy")).root.children.find((c) => c.kind === "subscription").name;
await p.locator(`[data-sub="${subName}"] select`).selectOption(`mg-prod-${N}`);
await p.getByText(/Subscription moved/).waitFor({ timeout: 10000 });
check("subscription PUT under the MG", p.posts.some((x) => x.m === "PUT" && x.u.includes(`/managementGroups/mg-prod-${N}/subscriptions/${subName}`)));
await p.screenshot({ path: `${SHOTS}/azure-mg-tree.png` });
await p.locator(`[data-mg="mg-prod-${N}"]`).click();
await p.getByRole("tab", { name: "Access control (IAM)" }).click();
const PRI = "11111111-2222-3333-4444-555555555555";
await p.getByLabel("Principal object ID").fill(PRI);
await p.getByRole("button", { name: "Add", exact: true }).click();
await p.getByText("Role assignment added.").waitFor({ timeout: 10000 });
const ra = p.posts.find((x) => x.m === "PUT" && x.u.includes(`managementGroups/mg-prod-${N}/providers/Microsoft.Authorization/roleAssignments/`));
check("role assignment PUT at MG scope", ra && ra.b.includes(PRI) && ra.b.includes("acdd72a7"), ra?.b);
await p.locator(`[data-ra="${PRI}"]`).waitFor({ timeout: 10000 });
await p.screenshot({ path: `${SHOTS}/azure-mg-access.png` });
await p.getByRole("tab", { name: "Policy" }).click();
await p.getByLabel("Allowed location").fill("northeurope");
await p.getByRole("button", { name: "Assign policy" }).click();
await p.getByText("Policy assigned.").waitFor({ timeout: 10000 });
const pa = p.posts.find((x) => x.m === "PUT" && x.u.includes("policyAssignments/allowed-locations"));
check("policy assignment PUT at MG scope", pa && pa.b.includes("northeurope"), pa?.b);
await p.locator('[data-pa="allowed-locations"]').first().waitFor({ timeout: 10000 });
await p.screenshot({ path: `${SHOTS}/azure-mg-policy.png` });
const eff = await govGet("azure", `effective?scope=${encodeURIComponent(`/subscriptions/${subName}`)}`);
check("engine: sub inherits MG role assignment", eff.roleAssignments.some((r) => r.principalId === PRI));
check("azure: no page errors", p.errs.length === 0, p.errs.join("|")); await p.close();
await browser.close();
console.log(bad ? `${bad} FAILED` : "ALL PASS");
process.exit(bad ? 1 : 0);
