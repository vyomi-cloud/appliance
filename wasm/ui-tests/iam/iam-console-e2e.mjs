/* Nano faithful-IAM driven through the REAL v4 consoles (/v4/<cloud>/) in the real Nano build: service worker + in-browser engine + Pyodide.
 *   NODE_PATH=/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules NANO_DIR=<worktree>/wasm [PHASE=aws,gcp,azure] node wasm/ui-tests/iam/iam-console-e2e.mjs
 * Nothing is mocked: UI clicks -> /_wire -> page hook -> in-browser cores; denials come from the vendored gate. Credential-less console traffic is
 * never gated by design (same as Mesh), so "denied call" checks sign requests exactly as an SDK/CLI through the tunnel does, from the same page.
 * Needs network for Pyodide (CDN) unless wasm/vendor/pyodide exists. */
import { startServer, chromium, sleep } from "../lib.mjs";
const PHASES = (process.env.PHASE || "aws,gcp,azure").split(",");
const { server, base } = await startServer();
const browser = await chromium.launch({ channel: process.env.CHROME_CHANNEL || "chrome" }).catch(() => chromium.launch());
const SFX = Date.now().toString(36).slice(-5);
const results = [];
const check = (name, ok, detail = "") => { results.push(!!ok); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  - " + String(detail).slice(0, 300) : ""}`); };

async function open(cloud, route) {
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
  const page = await ctx.newPage(); page.errs = []; globalThis.__lastPage = page;
  page.on("pageerror", (e) => page.errs.push(String(e)));
  page.on("dialog", (d) => d.accept().catch(() => {}));
  await page.goto(`${base}/v4/${cloud}/index.html#/${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 90000 });
  await page.waitForFunction(() => !!globalThis.NanoIamHook, null, { timeout: 120000 });
  await page.evaluate(() => {
    const W = "/_wire", sig = (k, svc) => `AWS4-HMAC-SHA256 Credential=${k}/20261125/us-east-1/${svc}/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);
    const b64u = (o) => btoa(JSON.stringify(o)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
    const out = async (x) => ({ s: x.status, t: await x.text() });
    const f = (u, i = {}) => fetch(u, { ...i, signal: AbortSignal.timeout(40000) });
    globalThis.T = {
      jwt: (c) => "eyJhbGciOiJub25lIn0." + b64u(c) + ".sig",
      form: async (svc, params, key = "AKIAVYOMIDUMMY") => out(await f(W + "/", { method: "POST", headers: { authorization: sig(key, svc), "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Version: svc === "iam" ? "2010-05-08" : "2012-11-05", ...params }).toString() })),
      rest: async (key, m, p, body, svc = "s3") => out(await f(W + p, { method: m, headers: { authorization: sig(key, svc) }, body })),
      g: async (m, p, body, tok) => { const h = { "content-type": "application/json" }; if (tok) h.authorization = "Bearer " + tok; return out(await f(W + p, { method: m, headers: h, body: body === undefined ? undefined : (typeof body === "string" ? body : JSON.stringify(body)) })); },
      api: async (cloud, m, p, body) => { const x = await f("/api/iam/" + cloud + p, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); return { s: x.status, b: await x.json().catch(() => null) }; },
    };
  });
  return page;
}
const body = (p) => p.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
const shot = (p, n) => p.screenshot({ path: `${process.env.SHOTS || "/tmp"}/iam-console-${n}.png` }).catch(() => {});
const go = async (p, route) => { await p.evaluate((r) => { location.hash = "#/" + r; }, route); await sleep(1200); };
const sigAws = (k, svc) => `AWS4-HMAC-SHA256 Credential=${k}/20261125/us-east-1/${svc}/aws4_request, SignedHeaders=host;x-amz-date, Signature=` + "0".repeat(64);

try {
  if (PHASES.includes("aws")) await aws();
  if (PHASES.includes("gcp")) await gcp();
  if (PHASES.includes("azure")) await azure();
} catch (e) { check("harness completed without exception", false, e.stack || e); await shot(globalThis.__lastPage, "FAILURE"); }
await browser.close(); server.close();
const bad = results.filter((r) => !r).length;
console.log(`\n${results.length - bad}/${results.length} checks passed`);
process.exit(bad ? 1 : 0);

// ================================================================================================================ AWS
async function aws() {
  const page = await open("aws", "iam/create-policy");
  const U = "vnuser" + SFX, POL = "vn-s3-read-" + SFX, BKT = "vn-bkt-" + SFX, Q = "vn-q-" + SFX;
  // seed a user + access key + bucket + queue in the in-browser stores (through the wire, as the console would)
  const seed = await page.evaluate(async ([U, BKT, Q]) => {
    await T.form("iam", { Action: "CreateUser", UserName: U });
    const k = await T.form("iam", { Action: "CreateAccessKey", UserName: U });
    const b = await T.rest("AKIAVYOMIDUMMY", "PUT", "/" + BKT);
    const q = await T.form("sqs", { Action: "CreateQueue", QueueName: Q });
    return { key: /<AccessKeyId>([^<]+)</.exec(k.t)?.[1], b: b.s, q: q.s, qt: q.t.slice(0, 200) };
  }, [U, BKT, Q]);
  check("AWS seed: user+access key+bucket+queue created in the in-browser stores", !!seed.key && seed.b === 200 && seed.q === 200, JSON.stringify(seed));
  const KEY = seed.key;

  // 1. Visual policy editor: create
  await page.getByRole("button", { name: /Choose a service/ }).first().click();
  await page.getByPlaceholder("Search services").fill("S3");
  await page.getByRole("option", { name: "S3", exact: true }).click();
  await page.getByPlaceholder("Filter Actions").fill("GetObject");
  await page.getByLabel("GetObject", { exact: true }).check();
  await page.getByText("Resources", { exact: true }).first().click();
  await page.getByRole("radio", { name: "Specific" }).check({ force: true });
  await page.getByTestId("res-row-object").getByText("Add ARNs").click();
  await page.getByLabel("object ARN").fill(`arn:aws:s3:::${BKT}/*`);
  await page.getByRole("button", { name: "Add ARN", exact: true }).click();
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  const gen = JSON.parse(await page.getByLabel("Policy document").inputValue());
  await page.getByRole("button", { name: "Visual", exact: true }).click();
  check("AWS visual editor generates Allow s3:GetObject on the bucket ARN", gen.Statement[0].Effect === "Allow" && [].concat(gen.Statement[0].Action).includes("s3:GetObject") && JSON.stringify(gen.Statement[0].Resource).includes(BKT), JSON.stringify(gen.Statement[0]));
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Policy name").fill(POL);
  await page.getByRole("button", { name: "Create policy", exact: true }).click();
  await page.waitForFunction((n) => location.hash.includes("/iam/policies/" + n), POL, { timeout: 30000 }).catch(() => {});
  const lp = await page.evaluate(() => T.form("iam", { Action: "ListPolicies", Scope: "Local" }));
  check("AWS Create policy (visual) persisted: ListPolicies has it", lp.t.includes(POL) && lp.t.includes("<Arn>"), lp.t.slice(0, 150));
  const polArn = new RegExp(`<Arn>([^<]*${POL})</Arn>`).exec(lp.t)?.[1];
  const gp = await page.evaluate(([a]) => T.form("iam", { Action: "GetPolicyVersion", PolicyArn: a, VersionId: "v1" }), [polArn]);
  check("AWS stored policy document is the visual editor output (s3:GetObject)", decodeURIComponent(gp.t).includes("s3:GetObject"), gp.t.slice(0, 200));

  // 2. attach in the UI
  await go(page, "iam/users/" + U);
  await page.getByRole("button", { name: "Add permissions" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Filter policies").fill(POL);
  await sleep(500);
  await dlg.getByLabel(`Select ${POL}`).check();
  await dlg.getByRole("button", { name: "Attach policy" }).click();
  await sleep(2500);
  const al = await page.evaluate((U) => T.form("iam", { Action: "ListAttachedUserPolicies", UserName: U }), U);
  check("AWS attach policy from the console: ListAttachedUserPolicies shows it", al.t.includes(POL), al.t.slice(0, 200));
  await shot(page, "aws-attached");

  // 3. before enforcement: signed calls pass the gate (mode off)
  const sdk = (k, m, p, svc, b) => page.evaluate(([k, m, p, svc, b]) => T.rest(k, m, p, b, svc), [k, m, p, svc, b]);
  const pre = await sdk(KEY, "PUT", `/${BKT}/obj.txt`, "s3", "hello");
  check("AWS mode off: PutObject by the policy-less user is not gated (200)", pre.s === 200, pre.s + " " + pre.t.slice(0, 120));

  // 4. flip enforcement to enforce from the console UI (service level s3 + sqs)
  await go(page, "iam/enforcement");
  await page.getByRole("radio", { name: "Enforce" }).first().waitFor({ timeout: 30000 }).catch(() => {});
  await shot(page, "aws-enforcement-before");
  for (const svc of ["s3", "sqs"]) {
    const row = page.getByRole("row").filter({ has: page.getByText(svc, { exact: true }) }).first();
    await row.getByText("Enforce", { exact: true }).click();
    await sleep(800);
  }
  const en = await page.evaluate(() => T.api("aws", "GET", "/enforcement"));
  check("AWS enforcement flipped to Enforce for s3 + sqs from the console", en.b?.services?.s3 === "enforce" && en.b?.services?.sqs === "enforce", JSON.stringify(en.b));
  await shot(page, "aws-enforcement-after");
  const get = await sdk(KEY, "GET", `/${BKT}/obj.txt`, "s3");
  const put = await sdk(KEY, "PUT", `/${BKT}/obj2.txt`, "s3", "x");
  check("AWS enforce: s3:GetObject allowed by the attached visual policy", get.s === 200 && get.t === "hello", get.s + " " + get.t.slice(0, 120));
  check("AWS enforce: s3:PutObject denied (403 AccessDenied) - not in the policy", put.s === 403 && /AccessDenied/.test(put.t), put.s + " " + put.t.slice(0, 160));
  const send = await page.evaluate(([k, Q]) => T.form("sqs", { Action: "SendMessage", QueueUrl: `http://x/000000000000/${Q}`, MessageBody: "hi" }, k), [KEY, Q]);
  check("AWS enforce: sqs:SendMessage denied for the user (403/AccessDenied)", send.s === 403 && /AccessDenied|not authorized/i.test(send.t), send.s + " " + send.t.slice(0, 160));

  // 5. audit tab + effective access
  await go(page, "iam/enforcement");
  const aud = await page.evaluate(() => T.api("aws", "GET", "/audit?limit=50"));
  const rows = aud.b?.records || [];
  check("AWS audit log recorded the denied decisions", JSON.stringify(rows).includes("deny"), JSON.stringify(rows).slice(0, 200));

  const ACCT = /arn:aws:iam::(\d+):/.exec(polArn)[1];
  // 6. resource policy tab save (S3 bucket policy)
  await go(page, `s3/buckets/${BKT}?tab=permissions`);
  await page.getByText("Bucket policy", { exact: true }).first().waitFor({ timeout: 30000 });
  await page.getByTestId("rpol-s3-bucket").getByRole("button", { name: /Edit/ }).first().click();
  await page.getByTestId("policy-statement").first().waitFor().catch(() => {});
  const before = await page.getByTestId("policy-statement").count();
  if (before === 0 || await page.getByRole("button", { name: "Add statement" }).count()) await page.getByRole("button", { name: "Add statement" }).click();
  const card = page.getByTestId("policy-statement").last();
  await card.getByLabel("Statement ID").fill("VnAllowAlice");
  await card.getByLabel("Principal", { exact: true }).fill("arn:aws:iam::" + ACCT + ":user/" + U);
  await card.getByRole("button", { name: "Add Principal" }).click();
  await card.getByRole("button", { name: /Choose actions/ }).click();
  await page.keyboard.type("PutObject");
  await page.getByRole("option").filter({ hasText: /^PutObject/ }).first().click();
  await page.keyboard.press("Escape");
  await card.getByLabel("Resource", { exact: true }).fill(`arn:aws:s3:::${BKT}/*`);
  await card.getByRole("button", { name: "Add Resource" }).click();
  await shot(page, "aws-bucket-policy-edit");
  await page.getByRole("button", { name: "Save changes" }).click();
  await sleep(2500);
  const gbp = await sdk("AKIAVYOMIDUMMY", "GET", `/${BKT}?policy`, "s3");
  check("AWS resource-policy tab save: GetBucketPolicy returns the saved statement", gbp.s === 200 && gbp.t.includes("VnAllowAlice") && gbp.t.includes("s3:PutObject"), gbp.s + " " + gbp.t.slice(0, 200));
  const put2 = await sdk(KEY, "PUT", `/${BKT}/obj3.txt`, "s3", "y");
  check("AWS enforce: bucket policy now allows s3:PutObject for the user (resource-based allow honoured)", put2.s === 200, put2.s + " " + put2.t.slice(0, 160));

  // 7. SimulatePrincipalPolicy (console page + API)
  await go(page, "iam/policy-simulator");
  await page.getByRole("button", { name: /Choose a user or role|Principal/ }).first().click().catch(() => {});
  await page.getByRole("option", { name: new RegExp("^" + U) }).first().click().catch(() => {});
  await shot(page, "aws-simulator");
  const sim = await page.evaluate(async (U) => {
    const acct = /arn:aws:iam::(\d+):user/.exec((await T.form("iam", { Action: "GetUser", UserName: U })).t)[1];
    return T.form("iam", { Action: "SimulatePrincipalPolicy", PolicySourceArn: `arn:aws:iam::${acct}:user/${U}`, "ActionNames.member.1": "s3:GetObject", "ActionNames.member.2": "s3:DeleteObject", "ResourceArns.member.1": "arn:aws:s3:::x/y" });
  }, U);
  check("AWS SimulatePrincipalPolicy: allowed for GetObject?? (policy scoped to bucket) / implicitDeny for DeleteObject", /implicitDeny/.test(sim.t) && /EvalActionName>s3:DeleteObject/.test(sim.t), sim.t.slice(0, 400));
  check("AWS no page errors", page.errs.length === 0, page.errs[0]);
  await page.context().close();
}
async function gcp() {
  const page = await open("gcp", "iam-admin/iam");
  const P = "nano-project", SA = `vn-sa-${SFX}@${P}.iam.gserviceaccount.com`, DEV = "dev-vn" + SFX, OTHER = "prod-vn" + SFX;
  const seed = await page.evaluate(async ([P, DEV, OTHER, SFX]) => {
    const r = {};
    r.sa = (await T.g("POST", `/v1/projects/${P}/serviceAccounts`, { accountId: "vn-sa-" + SFX, serviceAccount: { displayName: "VN SA" } })).s;
    for (const b of [DEV, OTHER]) { r["b_" + b] = (await T.g("POST", "/storage/v1/b?project=" + P, { name: b })).s; r["o_" + b] = (await T.g("POST", `/upload/storage/v1/b/${b}/o?uploadType=media&name=o.txt`, "data-" + b)).s; }
    return r;
  }, [P, DEV, OTHER, SFX]);
  check("GCP seed: service account + 2 buckets/objects created in the in-browser stores", Object.values(seed).every((v) => v === 200), JSON.stringify(seed));

  // Grant access with a condition (UI)
  await page.getByRole("button", { name: "Grant access" }).first().click();
  const panel = page.getByRole("dialog", { name: "Grant access" });
  await panel.waitFor({ timeout: 30000 });
  await panel.getByLabel("New principals").fill(SA); await panel.getByLabel("New principals").press("Enter");
  await panel.getByRole("button", { name: "Select a role" }).click();
  const popup = page.getByTestId("role-popup"); await popup.waitFor();
  await popup.getByLabel("Search roles").fill("storage object viewer");
  await popup.locator('[data-role-id="roles/storage.objectViewer"]').click();
  await panel.getByRole("button", { name: "Add IAM condition" }).click();
  const cond = page.getByRole("dialog", { name: "Add condition" }); await cond.waitFor();
  await cond.getByLabel("Condition title").fill("Dev buckets only");
  await cond.getByRole("combobox", { name: "Condition type 1" }).click();
  await page.getByRole("option", { name: "Name" }).click();
  await cond.getByRole("combobox", { name: "Operator" }).click(); await page.getByRole("option", { name: "starts with" }).click();
  await cond.getByLabel("Resource name value").fill("projects/_/buckets/dev-");
  const cel = await cond.getByTestId("cel-preview").innerText();
  check("GCP condition builder generates CEL and the in-browser engine validates it", /startsWith\("projects\/_\/buckets\/dev-"\)/.test(cel) && await cond.getByTestId("cel-ok").isVisible(), cel);
  await cond.getByRole("button", { name: "Save" }).click();
  await panel.getByText("Condition: Dev buckets only").waitFor();
  await shot(page, "gcp-grant-condition");
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await sleep(2500);
  const pol = await page.evaluate((P) => T.g("POST", `/v1/projects/${P}:getIamPolicy`, {}), P);
  const pj = JSON.parse(pol.t); const bnd = (pj.bindings || []).find((b) => b.role === "roles/storage.objectViewer" && (b.members || []).includes("serviceAccount:" + SA));
  check("GCP Grant access (UI): project policy now binds the SA with the CEL condition", !!bnd && bnd.condition?.title === "Dev buckets only" && /dev-/.test(bnd.condition.expression), JSON.stringify(bnd));

  // enforcement flip from the console
  await go(page, "iam-admin/enforcement");
  await page.getByLabel("Space enforcement mode").getByText("Enforce", { exact: true }).click();
  await sleep(1000);
  const en = await page.evaluate(() => T.api("gcp", "GET", "/enforcement"));
  check("GCP enforcement flipped to Enforce from the console (space level)", en.b?.space === "enforce", JSON.stringify(en.b));
  await shot(page, "gcp-enforcement");
  const tok = await page.evaluate((SA) => T.jwt({ email: SA }), SA);
  const rd = (b) => page.evaluate(([b, tok]) => T.g("GET", `/storage/v1/b/${b}/o/o.txt?alt=media`, undefined, tok), [b, tok]);
  const okR = await rd(DEV), noR = await rd(OTHER);
  check("GCP enforce: conditional binding -> read in dev-* bucket allowed (200)", okR.s === 200 && okR.t === "data-" + DEV, okR.s + " " + okR.t.slice(0, 160));
  check("GCP enforce: same SA, bucket outside the condition -> 403 PERMISSION_DENIED", noR.s === 403 && /PERMISSION_DENIED/.test(noR.t), noR.s + " " + noR.t.slice(0, 200));

  // Policy Troubleshooter (UI)
  await go(page, "iam-admin/troubleshooter");
  await page.getByLabel("Principal").fill(SA);
  await page.getByLabel("Permission 1").fill("storage.objects.get");
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByText(/Granted:|Denied:/).first().waitFor({ timeout: 30000 }).catch(() => {});
  const tb = await page.locator(".MuiAlert-message").allInnerTexts();
  await shot(page, "gcp-troubleshooter");
  check("GCP Policy Troubleshooter (UI) shows a Granted/Denied verdict for storage.objects.get on the project", tb.some((t) => /^(Granted|Denied): storage\.objects\.get on projects\/nano-project/.test(t)), tb.join(" | "));
  // against the bucket resource the conditional grant must resolve per bucket
  const verdict = async (b) => { await page.getByLabel("Resource 1").fill(`//storage.googleapis.com/projects/_/buckets/${b}/objects/o.txt`); await page.getByRole("button", { name: "Check access" }).click(); await sleep(2500); return (await page.locator(".MuiAlert-message").allInnerTexts()).join(" | "); };
  const vDev = await verdict(DEV), vOther = await verdict(OTHER);
  check("GCP Troubleshooter on the object: Granted for dev-*, Denied for the other bucket (condition honoured)", /^Granted/.test(vDev) && /^Denied/.test(vOther), vDev + " || " + vOther);
  const ev1 = await page.evaluate(([SA, DEV, OTHER]) => Promise.all([DEV, OTHER].map((b) => T.api("gcp", "POST", "/evaluate", { principal: { member: "serviceAccount:" + SA }, action: "storage.objects.get", resource: `//storage.googleapis.com/projects/_/buckets/${b}/objects/o.txt` }))), [SA, DEV, OTHER]);
  check("GCP /evaluate (engine behind Effective access): allow in dev-*, deny elsewhere", ev1[0].b?.allowed === true && ev1[1].b?.allowed === false, JSON.stringify(ev1.map((x) => x.b)).slice(0, 400));
  check("GCP no page errors", page.errs.length === 0, page.errs[0]);
  await page.evaluate(() => T.api("gcp", "PUT", "/enforcement", {}));
  await page.context().close();
}
async function azure() {
  const SC = "/subscriptions/00000000-0000-0000-0000-cloudlearn01", RG = "vnrg" + SFX, SA = "vnsa" + SFX, SAID = `${SC}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`;
  const page = await open("azure", "storage");
  const seed = await page.evaluate(async ([SC, RG, SA, SFX]) => {
    const r = {}, A = (m, p, b) => T.g(m, p, b);
    r.rg = (await A("PUT", `${SC}/resourcegroups/${RG}?api-version=2021-04-01`, { location: "eastus" })).s;
    r.sa = (await A("PUT", `${SC}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}?api-version=2023-01-01`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } })).s;
    const u1 = await A("POST", "/v1.0/users", { displayName: "VN Blob " + SFX, userPrincipalName: `vnblob${SFX}@vyomi.cloud`, mailNickname: "vnblob" + SFX, accountEnabled: true });
    const u2 = await A("POST", "/v1.0/users", { displayName: "VN Reader " + SFX, userPrincipalName: `vnreader${SFX}@vyomi.cloud`, mailNickname: "vnreader" + SFX, accountEnabled: true });
    r.u1 = u1.s; r.u2 = u2.s; r.id1 = JSON.parse(u1.t).id; r.id2 = JSON.parse(u2.t).id;
    return r;
  }, [SC, RG, SA, SFX]);
  check("Azure seed: resource group, storage account and two directory users created in the in-browser stores", seed.rg === 201 && seed.sa < 300 && seed.u1 < 300 && seed.u2 < 300 && !!seed.id1 && !!seed.id2, JSON.stringify(seed));
  const [ID1, ID2] = [seed.id1, seed.id2];

  // role assignment with an ABAC condition (UI)
  await go(page, `storage/${RG}/${SA}/iam`);
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByRole("button", { name: "Add role assignment" }).click();
  await page.getByTestId("role-picker").waitFor();
  await page.getByLabel("Search by role name, description, or ID").fill("Storage Blob Data Reader");
  await page.getByTestId("role-row-Storage Blob Data Reader").waitFor();
  await page.getByLabel("View Storage Blob Data Reader").click();
  await page.getByText("DataActions (", { exact: false }).first().waitFor();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("tab", { name: "Members" }).click();
  await page.getByTestId("select-members").click();
  await page.getByTestId("member-picker").waitFor();
  await page.getByTestId("member-picker").locator("input").first().fill("VN Blob " + SFX);
  await page.getByLabel("Select VN Blob " + SFX).check();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("tab", { name: "Conditions" }).click();
  await page.getByRole("button", { name: "Add condition" }).click();
  await page.getByLabel("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read").check();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByLabel("Attribute source").first().selectOption("Resource");
  await page.getByLabel("Attribute", { exact: true }).first().selectOption({ label: "Container name" });
  await page.getByLabel("Value", { exact: true }).first().fill("logs");
  await page.getByRole("tab", { name: "Code" }).click();
  const code = await page.getByTestId("abac-code").innerText();
  await shot(page, "azure-abac");
  await page.getByRole("button", { name: "Review + assign" }).click();
  await page.getByTestId("ra-review").waitFor();
  await page.getByRole("button", { name: "Review + assign" }).click();
  await sleep(2500);
  const ras = await page.evaluate((SAID) => T.g("GET", `${SAID}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01`), SAID);
  const mine = (JSON.parse(ras.t).value || []).find((x) => x.properties?.principalId === ID1);
  check("Azure role assignment with ABAC condition (UI): ARM stores it with the condition + conditionVersion 2.0", !!mine && mine.properties.condition === code && mine.properties.conditionVersion === "2.0", JSON.stringify(mine?.properties).slice(0, 300));

  // Reader for user 2 (via ARM, as az would), then enforcement flip from the console
  const READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7";
  const rd = await page.evaluate(([SAID, SC, ID2, READER]) => T.g("PUT", `${SAID}/providers/Microsoft.Authorization/roleAssignments/aaaaaaaa-0000-0000-0000-0000000000${String(Date.now()).slice(-2)}?api-version=2022-04-01`, { properties: { roleDefinitionId: `${SC}/providers/Microsoft.Authorization/roleDefinitions/${READER}`, principalId: ID2, principalType: "User" } }), [SAID, SC, ID2, READER]);
  check("Azure Reader assignment for user 2 created through ARM", rd.s === 201, rd.s + " " + rd.t.slice(0, 160));
  await page.getByRole("tab", { name: "Enforcement" }).click();
  await page.locator('[aria-label="Space enforcement mode"]').getByText("Enforce", { exact: true }).click();
  await sleep(1000);
  const en = await page.evaluate(() => T.api("azure", "GET", "/enforcement"));
  check("Azure enforcement flipped to Enforce from the console (space level)", en.b?.space === "enforce", JSON.stringify(en.b));
  await shot(page, "azure-enforcement");
  const call = (oid, m, p, b) => page.evaluate(async ([oid, m, p, b]) => T.g(m, p, b, T.jwt({ oid, tid: "t" })), [oid, m, p, b]);
  const getSA = (oid) => call(oid, "GET", `${SAID}?api-version=2023-01-01`);
  const r2 = await getSA(ID2), r1 = await getSA(ID1);
  check("Azure enforce: Reader (user 2) reads the storage account -> 200", r2.s === 200, r2.s + " " + r2.t.slice(0, 120));
  check("Azure enforce: data-plane-only Blob Data Reader (user 1) has no management read -> 403 AuthorizationFailed", r1.s === 403 && /AuthorizationFailed/.test(r1.t), r1.s + " " + r1.t.slice(0, 200));

  // ABAC through the engine behind Effective access: condition true for container logs, false otherwise
  const ev = (cn) => page.evaluate(([ID1, SAID, cn]) => T.api("azure", "POST", "/evaluate", { principal: { object_id: ID1, type: "User" }, action: "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read", resource: SAID, data: true,
    context: { resource: { "Microsoft.Storage/storageAccounts/blobServices/containers:name": cn } } }), [ID1, SAID, cn]);
  const eLogs = await ev("logs"), eOther = await ev("secrets");
  check("Azure ABAC (engine evaluate): container 'logs' allowed, 'secrets' denied", eLogs.b?.allowed === true && eOther.b?.allowed === false, JSON.stringify([eLogs.b?.reason, eOther.b?.reason]));

  // Check access (UI) -> ARM checkAccess
  await page.getByRole("tab", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Select principal" }).click();
  await page.getByTestId("member-picker").locator("input").first().fill("VN Reader " + SFX);
  await page.getByLabel("Select VN Reader " + SFX).check();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  check("Azure Check access (UI): principal chosen through the picker", /VN Reader/.test(await page.getByTestId("principal-value").innerText()));
  const ca = async (action) => page.evaluate(([SAID, ID2, a]) => T.g("POST", `${SAID}/providers/Microsoft.Authorization/checkAccess?api-version=2022-04-01`, { principalId: ID2, actions: [{ id: a }], resource: { id: SAID } }), [SAID, ID2, action]);
  const caRead = await ca("Microsoft.Storage/storageAccounts/read");
  check("Azure checkAccess (ARM) for Reader: storageAccounts/read -> Allowed", /Allowed/i.test(caRead.t) && !/NotAllowed/i.test(caRead.t), caRead.s + " " + caRead.t.slice(0, 200));

  // Deny assignment (UI)
  await page.getByRole("tab", { name: "Deny assignments" }).click();
  await page.getByRole("button", { name: /Add deny assignment/ }).first().click();
  const bl = page.getByTestId("add-deny"); await bl.waitFor();
  await bl.getByLabel("Deny assignment name").fill("vn-deny-read-" + SFX);
  await bl.getByRole("button", { name: "Select principal" }).click();
  await page.getByTestId("member-picker").locator("input").first().fill("VN Reader " + SFX);
  await page.getByLabel("Select VN Reader " + SFX).check();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await bl.getByRole("button", { name: /Add denied actions/ }).click();
  await page.getByLabel("Search for a resource provider").fill("Microsoft.Stor");
  await page.getByTestId("provider-Microsoft.Storage").click();
  await page.getByLabel("Search for an action").fill("storageAccounts/read");
  await page.getByLabel("Microsoft.Storage/storageAccounts/read", { exact: true }).check();
  await page.getByRole("dialog", { name: "Add permissions" }).getByRole("button", { name: "Add", exact: true }).click();
  await shot(page, "azure-deny-dialog");
  await page.getByRole("dialog", { name: "Add deny assignment" }).getByRole("button", { name: "Add", exact: true }).click();
  await sleep(2500);
  const r2d = await getSA(ID2);
  check("Azure deny assignment (UI) wins over the Reader role: user 2 read -> 403 AuthorizationFailed", r2d.s === 403 && /AuthorizationFailed/.test(r2d.t), r2d.s + " " + r2d.t.slice(0, 240));
  const caDeny = await ca("Microsoft.Storage/storageAccounts/read");
  check("Azure checkAccess after the deny assignment -> not allowed", !(/Allowed/i.test(caDeny.t) && !/NotAllowed/i.test(caDeny.t)), caDeny.s + " " + caDeny.t.slice(0, 240));
  const aud = await page.evaluate(() => T.api("azure", "GET", "/audit?limit=50"));
  check("Azure audit log recorded the deny decisions", JSON.stringify(aud.b?.records || []).includes("deny"), JSON.stringify(aud.b?.records || []).slice(0, 200));
  check("Azure no page errors", page.errs.length === 0, page.errs[0]);
  await page.evaluate(() => T.api("azure", "PUT", "/enforcement", {}));
  await page.context().close();
}
