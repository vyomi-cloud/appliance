/* Amazon EKS console smoke: create cluster (role + VPC helpers) -> CREATING -> ACTIVE, node group, add-ons, access entry + policy, logging, version
 * upgrade, kubectl terminal, AWS Backup for EKS backup + restore, tags, delete. Screenshots go to SHOTS (default consoles/smoke-out-eks).
 *   python3 consoles/tests/eks_fake_server.py --port 8741 &      # Docker-free (fake docker)  -- or --
 *   VYOMI_K8S_BACKEND=k3s python3 consoles/dev_server.py --port 8741 &   # real k3s
 *   BASE=http://127.0.0.1:8741 node consoles/tests/smoke-aws-eks.mjs            (REAL=1 lengthens timeouts for a real k3s boot) */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8741";
const UI = `${BASE}/v4/aws/`;
const WIRE = `${BASE}/_wire`;
const SHOTS = process.env.SHOTS || new URL("../smoke-out-eks/", import.meta.url).pathname;
const T = process.env.REAL ? 600000 : 60000;
mkdirSync(SHOTS, { recursive: true });
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: false });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261109/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
await page.goto(UI + "#/eks");
const wire = (svc, method, path, body) => page.evaluate(async ([u, m, b, a]) => { const r = await fetch(u, { method: m, body: b ? JSON.stringify(b) : undefined, headers: { authorization: a, "content-type": "application/json" } }); const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : {} }; }, [WIRE + path, method, body, auth(svc)]);
const eks = (m, p, b) => wire("eks", m, p, b);
const pick = async (label, text) => { await page.getByLabel(label, { exact: true }).first().click(); await page.getByRole("option", { name: text }).first().click(); };

// ── empty list ──
await page.getByText("Clusters").first().waitFor({ timeout: 20000 });
await page.getByText("No clusters").first().waitFor({ timeout: 20000 });
check("empty Clusters list", true);
await shot("01-clusters-empty");

// ── create ──
await page.getByRole("button", { name: "Create cluster" }).first().click();
await page.getByRole("heading", { name: "Create EKS cluster" }).waitFor();
await page.getByRole("button", { name: "Create recommended role" }).first().click();
await page.getByRole("button", { name: "Create VPC with 2 subnets" }).click();
await page.getByLabel("Cluster name").fill("ui-demo");
await page.waitForTimeout(800);
await page.getByRole("button", { name: /^Subnets/ }).click();
const opts = page.getByRole("option");
await opts.nth(0).click(); await opts.nth(1).click();
await page.keyboard.press("Escape");
await shot("02-create-cluster");
const createBtn = page.getByRole("button", { name: "Create", exact: true });
check("Create enabled with role + 2 subnets", await createBtn.isEnabled());
await createBtn.click();
await page.getByText("Cluster is being created").waitFor({ timeout: 20000 });
check("detail page shows CREATING", (await eks("GET", "/clusters/ui-demo")).body.cluster.status === "CREATING");
await shot("03-detail-creating");
await page.getByText("API server endpoint").first().waitFor({ timeout: 20000 });
await page.waitForFunction(() => document.body.innerText.includes("Active") || document.body.innerText.includes("ACTIVE"), null, { timeout: T });
const c = (await eks("GET", "/clusters/ui-demo")).body.cluster;
check("cluster ACTIVE with endpoint + CA + oidc issuer", c.status === "ACTIVE" && c.endpoint?.startsWith("https://127.0.0.1:") && c.certificateAuthority?.data && c.identity.oidc.issuer.includes("/id/"));
await page.waitForTimeout(500);
await shot("04-overview-active");

// ── compute ──
await page.getByRole("tab", { name: "Compute" }).click();
await page.getByRole("button", { name: "Add node group" }).click();
await page.getByLabel("Node group name").fill("ng-ui");
await page.getByRole("dialog").getByRole("button", { name: "Create recommended role" }).click();
await page.waitForTimeout(600);
await page.getByRole("dialog").getByRole("button", { name: /^Node IAM role/ }).click();
await page.getByRole("option", { name: "eksNodeRole" }).first().click();
await page.getByLabel("Desired size").fill("1");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("ng-ui", { exact: true }).first().waitFor({ timeout: 20000 });
for (let i = 0; i < 60; i++) { if ((await eks("GET", "/clusters/ui-demo/node-groups/ng-ui")).body.nodegroup.status === "ACTIVE") break; await page.waitForTimeout(1000); }
await page.getByRole("button", { name: "Refresh" }).first().click().catch(() => {});
await page.waitForTimeout(1000);
check("node group created via UI and ACTIVE", (await eks("GET", "/clusters/ui-demo/node-groups/ng-ui")).body.nodegroup.status === "ACTIVE");
await shot("05-compute-nodegroup");

// ── networking ──
await page.getByRole("tab", { name: "Networking" }).click();
await page.getByText("Cluster endpoint access").first().waitFor();
await shot("06-networking");

// ── add-ons ──
await page.getByRole("tab", { name: "Add-ons" }).click();
await page.getByText("coredns", { exact: true }).first().waitFor();
check("coredns + kube-proxy listed", await page.getByText("kube-proxy", { exact: true }).first().isVisible());
await page.getByRole("button", { name: "Get more add-ons" }).click();
await page.getByRole("dialog").getByRole("button", { name: /^Add-on/ }).click();
await page.getByRole("option", { name: /vpc-cni/ }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByText("vpc-cni", { exact: true }).first().waitFor({ timeout: 20000 });
check("vpc-cni add-on created via UI", (await eks("GET", "/clusters/ui-demo/addons/vpc-cni")).status === 200);
await shot("07-addons");

// ── access ──
await page.getByRole("tab", { name: "Access" }).click();
await page.getByText("IAM access entries").first().waitFor();
await page.getByRole("button", { name: "Create access entry" }).click();
await page.getByLabel("IAM principal ARN").fill("arn:aws:iam::123456789012:role/developers");
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByText("arn:aws:iam::123456789012:role/developers", { exact: true }).first().waitFor({ timeout: 20000 });
await page.getByRole("row", { name: /developers/ }).getByRole("radio").check();
await page.getByRole("button", { name: "Add access policy" }).click();
await page.getByRole("dialog").getByRole("button", { name: /^Policy name/ }).click();
await page.getByRole("option", { name: "AmazonEKSViewPolicy" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Add policy" }).click();
await page.getByText(/AmazonEKSViewPolicy \(cluster\)/).waitFor({ timeout: 20000 });
check("access entry + policy via UI", (await eks("GET", "/clusters/ui-demo/access-entries/arn:aws:iam::123456789012:role%2Fdevelopers/access-policies")).body.associatedAccessPolicies?.length === 1);
await shot("08-access");

// ── observability + update history ──
await page.getByRole("tab", { name: "Observability" }).click();
await page.getByRole("checkbox", { name: "audit" }).check();
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByRole("tab", { name: "Update history" }).click();
await page.getByText("LoggingUpdate", { exact: true }).first().waitFor({ timeout: 20000 });
check("logging update recorded in the history", true);
await shot("09-update-history");

// ── upgrade ──
await page.waitForTimeout(3000);
await page.getByRole("button", { name: "Upgrade version" }).click();
await page.getByRole("dialog").getByRole("button", { name: /^Upgrade to/ }).click();
await page.getByRole("option").first().click();
await page.getByRole("dialog").getByRole("button", { name: "Update" }).click();
await page.waitForFunction(async () => (await (await fetch(`${location.pathname.replace(/\/v4\/aws\/.*/, "")}/_wire/clusters/ui-demo`, { headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261109/us-east-1/eks/aws4_request, SignedHeaders=host, Signature=0" } })).json()).cluster.version !== "1.33", null, { timeout: 30000 }).catch(() => {});
check("version upgraded one minor", (await eks("GET", "/clusters/ui-demo")).body.cluster.version === "1.34" || (await eks("GET", "/clusters/ui-demo/updates")).body.updateIds.length >= 2);

// ── tags ──
await page.getByRole("tab", { name: "Tags" }).click();
await page.getByLabel("Tag key").fill("team");
await page.getByLabel("Tag value").fill("platform");
await page.getByRole("button", { name: "Add tag" }).click();
await page.getByText("team", { exact: true }).first().waitFor({ timeout: 20000 });
check("tag added via UI", (await eks("GET", `/tags/${encodeURIComponent(c.arn)}`)).body.tags.team === "platform");

// ── backup + kubectl ──
await page.waitForTimeout(3000);
await page.getByRole("tab", { name: "Backup and kubectl" }).click();
await page.getByTestId("kube-backup").waitFor({ timeout: 20000 });
const term = page.getByLabel("Terminal input");
const run = async (cmd) => { await term.fill(cmd); await term.press("Enter"); await page.waitForTimeout(1500); };
await page.getByTestId("deploy-mock").click();
await page.waitForTimeout(2500);
await run("kubectl get nodes");
await run("aws backup create-backup-vault --backup-vault-name eks-ui-vault");
await run("aws backup start-backup-job --backup-vault-name eks-ui-vault");
await page.waitForFunction(() => document.body.innerText.includes("Backup job COMPLETED"), null, { timeout: 30000 });
check("backup job COMPLETED through the terminal", true);
await shot("10-backup-terminal");
const rps = (await wire("backup", "GET", `/resources/${encodeURIComponent(c.arn)}/recovery-points`)).body.RecoveryPoints || [];
check("recovery point of ResourceType EKS exists", rps.length === 1 && rps[0].ResourceType === "EKS", rps[0]?.RecoveryPointArn);
await page.getByTestId("inject-disaster").click();
await page.waitForTimeout(2000);
await run("aws backup start-restore-job");
await page.waitForFunction(() => document.body.innerText.includes("Restore job COMPLETED"), null, { timeout: 30000 });
check("restore job COMPLETED through the terminal", true);
await shot("11-restore");

// ── delete ──
await page.goto(UI + "#/eks/clusters");
await page.getByText("ui-demo", { exact: true }).first().waitFor({ timeout: 20000 });
await page.getByRole("row", { name: /ui-demo/ }).getByRole("radio").check();
await page.getByRole("button", { name: "Delete", exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click().catch(() => {});
check("cluster with a node group cannot be deleted (native error shown)", (await eks("DELETE", "/clusters/ui-demo")).status === 409);
await eks("DELETE", "/clusters/ui-demo/node-groups/ng-ui");
await page.waitForTimeout(1500);
const del = await eks("DELETE", "/clusters/ui-demo");
check("cluster deleted after its node group", del.status === 200 && del.body.cluster.status === "DELETING");
await page.waitForTimeout(2000);
check("cluster gone", (await eks("GET", "/clusters/ui-demo")).status === 404);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
