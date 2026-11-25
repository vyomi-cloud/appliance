/* Playwright smoke for the shared AWS resource-policy tab (kit/ResourcePolicyTab.jsx) on S3 bucket, SQS queue and Secrets Manager, against the
 * BUILT bundle (wasm/v4/aws) with a stateful mock of the native S3 / SQS JSON / Secrets Manager JSON wire. Asserts the real stored state is
 * shown and the SAVE PAYLOAD sent to the native call (PutBucketPolicy body, SetQueueAttributes Policy, PutResourcePolicy ResourcePolicy).
 *   NODE_PATH=/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules SHOTS=<dir> node consoles/tests/smoke-aws-resource-policy-tabs.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, readFileSync, mkdirSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname, CAT = new URL("../../core/iam_catalog/aws/", import.meta.url).pathname;
const SHOTS = process.env.SHOTS || "/tmp/aws-rpol-shots"; mkdirSync(SHOTS, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  const p0 = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  let p = p0.endsWith("/") ? p0 + "index.html" : p0; const f = join(ROOT, p);
  if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
const results = []; const check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 300) : ""}`); };
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page = await ctx.newPage(); const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
const xml = (inner, action) => `<${action}Response><${action}Result>${inner}</${action}Result></${action}Response>`;
const store = { s3: null, sqs: { QueueArn: "arn:aws:sqs:us-east-1:000000000000:demo-queue" }, secret: null };
const sent = { s3: [], sqs: [], secret: [] };
const SEED_S3 = JSON.stringify({ Version: "2012-10-17", Statement: [{ Sid: "SeedRead", Effect: "Allow", Principal: "*", Action: "s3:GetObject", Resource: "arn:aws:s3:::demo-bucket/*" }] });
store.s3 = SEED_S3;
await page.route("**/_wire/**", async (r) => {
  const rq = r.request(), u = new URL(rq.url()), path = u.pathname.replace(/^.*\/_wire/, "");
  const cat = u.pathname.match(/\/api\/iam\/aws\/catalog\/([\w.-]+)$/);
  if (cat) { const f = CAT + cat[1] + ".json"; return existsSync(f) ? r.fulfill({ status: 200, contentType: "application/json", body: readFileSync(f, "utf8") }) : r.fulfill({ status: 404, body: "{}" }); }
  const target = rq.headers()["x-amz-target"];
  if (rq.method() === "POST" && target) {
    const b = JSON.parse(rq.postData() || "{}"); const json = (o) => r.fulfill({ status: 200, contentType: "application/x-amz-json-1.0", body: JSON.stringify(o) });
    if (target === "AmazonSQS.GetQueueUrl") return json({ QueueUrl: "http://localhost/000000000000/demo-queue" });
    if (target === "AmazonSQS.GetQueueAttributes") return json({ Attributes: { ...store.sqs } });
    if (target === "AmazonSQS.SetQueueAttributes") { sent.sqs.push(b); Object.assign(store.sqs, b.Attributes); return json({}); }
    if (target === "secretsmanager.DescribeSecret") return json({ Name: "demo-secret", ARN: "arn:aws:secretsmanager:us-east-1:000000000000:secret:demo-secret-AbCdEf", CreatedDate: 1700000000, LastChangedDate: 1700000000 });
    if (target === "secretsmanager.GetResourcePolicy") return json(store.secret ? { Name: "demo-secret", ResourcePolicy: store.secret } : { Name: "demo-secret" });
    if (target === "secretsmanager.PutResourcePolicy") { sent.secret.push(b); store.secret = b.ResourcePolicy; return json({ Name: "demo-secret" }); }
    if (target === "secretsmanager.DeleteResourcePolicy") { store.secret = null; return json({}); }
    return json({});
  }
  if (rq.method() === "POST") {
    const a = new URLSearchParams(rq.postData() || "").get("Action");
    const body = { ListUsers: xml(`<Users><member><UserName>alice</UserName><Arn>arn:aws:iam::000000000000:user/alice</Arn></member></Users>`, a),
      ListRoles: xml(`<Roles><member><RoleName>app-role</RoleName><Arn>arn:aws:iam::000000000000:role/app-role</Arn></member></Roles>`, a) }[a] || xml("", a);
    return r.fulfill({ status: 200, contentType: "text/xml", body });
  }
  const nosuch = (c) => r.fulfill({ status: 404, contentType: "application/xml", body: `<Error><Code>${c}</Code><Message>${c}</Message></Error>` });
  if (path === "/demo-bucket" && u.searchParams.has("policy")) {
    if (rq.method() === "GET") return store.s3 ? r.fulfill({ status: 200, contentType: "application/json", body: store.s3 }) : nosuch("NoSuchBucketPolicy");
    if (rq.method() === "PUT") { sent.s3.push(rq.postData()); store.s3 = rq.postData(); return r.fulfill({ status: 204, body: "" }); }
    if (rq.method() === "DELETE") { store.s3 = null; return r.fulfill({ status: 204, body: "" }); }
  }
  if (rq.method() === "GET" && path === "/demo-bucket" && !u.search) return r.fulfill({ status: 200, contentType: "application/xml", body: `<ListBucketResult><Name>demo-bucket</Name></ListBucketResult>` });
  return nosuch("NoSuchKey");
});

async function openEdit(title) {
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await page.getByText("Policy editor mode").first().waitFor().catch(() => {});
}
async function addVisualStatement({ sid, principal, action, resource }) {
  const card = page.getByTestId("policy-statement").last();
  await card.getByLabel("Statement ID").fill(sid);
  await card.getByLabel("Principal", { exact: true }).fill(principal);
  await card.getByRole("button", { name: "Add Principal" }).click();
  await card.getByRole("button", { name: /Choose actions/ }).click();
  await page.keyboard.type(action);
  await page.getByRole("option").filter({ hasText: new RegExp(`^${action}[a-z0-9-]+:${action}$`) }).first().click();
  await page.keyboard.press("Escape");
  if (resource) { await card.getByLabel("Resource", { exact: true }).fill(resource); await card.getByRole("button", { name: "Add Resource" }).click(); }
}

// ---------- S3 bucket policy ----------
await page.goto(`${BASE}/v4/aws/#/s3/buckets/demo-bucket?tab=permissions`);
await page.getByText("Bucket policy", { exact: true }).first().waitFor({ timeout: 30000 });
check("S3: shows the REAL stored bucket policy (seed statement)", (await page.getByTestId("policy-json").first().innerText()).includes("SeedRead"));
check("S3: statements table lists the stored Sid", (await page.getByRole("cell", { name: "SeedRead" }).count()) >= 1);
await page.screenshot({ path: `${SHOTS}/s3-policy-view.png`, fullPage: true });
await page.getByTestId("rpol-s3-bucket").getByRole("button", { name: "Edit", exact: true }).click();
await page.getByTestId("policy-statement").first().waitFor();
check("S3: visual editor opens with the stored statement", (await page.getByTestId("policy-statement").count()) === 1 && (await page.getByLabel("Statement ID").first().inputValue()) === "SeedRead");
await page.getByRole("button", { name: "Add statement" }).click();
await addVisualStatement({ sid: "AllowAlice", principal: "arn:aws:iam::000000000000:user/alice", action: "PutObject" });
await page.screenshot({ path: `${SHOTS}/s3-policy-visual.png`, fullPage: true });
await page.getByRole("button", { name: "Save changes" }).click();
await page.waitForFunction(() => true);
await page.getByText("Bucket policy saved.").first().waitFor({ timeout: 10000 }).catch(() => {});
const put = sent.s3.at(-1) ? JSON.parse(sent.s3.at(-1)) : null;
const st = put && put.Statement.find((s) => s.Sid === "AllowAlice");
check("S3: PutBucketPolicy payload has the new statement (principal, action, default resources)", !!st && st.Effect === "Allow" && JSON.stringify(st.Principal) === JSON.stringify({ AWS: "arn:aws:iam::000000000000:user/alice" }) && [].concat(st.Action).includes("s3:PutObject") && [].concat(st.Resource).includes("arn:aws:s3:::demo-bucket/*"), JSON.stringify(put));
check("S3: seed statement preserved in the same document", !!put && put.Statement.some((s) => s.Sid === "SeedRead"));

// ---------- SQS access policy ----------
await page.goto(`${BASE}/v4/aws/#/sqs/queues/demo-queue`);
await page.getByRole("tab", { name: "Access policy" }).click({ timeout: 30000 });
await page.getByText("No policy attached. Only the queue owner can send and receive messages.").waitFor();
check("SQS: empty state reflects the real (empty) stored policy", true);
await page.getByTestId("rpol-sqs-queue").getByRole("button", { name: "Edit", exact: true }).click();
await page.getByRole("button", { name: "Add statement" }).click();
await addVisualStatement({ sid: "SnsSend", principal: "sns.amazonaws.com", action: "SendMessage", resource: "arn:aws:sqs:us-east-1:000000000000:demo-queue" });
await page.screenshot({ path: `${SHOTS}/sqs-policy-visual.png`, fullPage: true });
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByRole("cell", { name: "SnsSend" }).waitFor({ timeout: 10000 });
const sp = sent.sqs.at(-1); const sdoc = sp && JSON.parse(sp.Attributes.Policy);
check("SQS: SetQueueAttributes carries Attributes.Policy with the service principal + sqs:SendMessage", !!sdoc && sdoc.Statement.some((s) => s.Sid === "SnsSend" && s.Principal?.Service === "sns.amazonaws.com" && [].concat(s.Action).includes("sqs:SendMessage")), JSON.stringify(sp));
check("SQS: QueueUrl targeted", sp?.QueueUrl?.endsWith("/demo-queue"));
// JSON mode round trip
await page.getByTestId("rpol-sqs-queue").getByRole("button", { name: "Edit", exact: true }).click();
await page.getByRole("radio", { name: "JSON" }).click().catch(async () => { await page.getByText("JSON", { exact: true }).first().click(); });
const ta = page.getByLabel("Policy document");
const cur = JSON.parse(await ta.inputValue());
cur.Statement[0].Sid = "RenamedViaJson";
await ta.fill(JSON.stringify(cur, null, 2));
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByRole("cell", { name: "RenamedViaJson" }).waitFor({ timeout: 10000 });
check("SQS: JSON editor save sends the edited document", JSON.parse(sent.sqs.at(-1).Attributes.Policy).Statement[0].Sid === "RenamedViaJson");

// ---------- Secrets Manager resource permissions ----------
await page.goto(`${BASE}/v4/aws/#/secretsmanager/secret/demo-secret`);
await page.getByText("Resource permissions", { exact: false }).first().waitFor({ timeout: 30000 });
check("Secrets: no resource policy attached (real empty state)", (await page.getByText("No resource policy attached.").count()) === 1);
await page.getByTestId("rpol-secret").getByRole("button", { name: "Edit", exact: true }).click();
await page.getByRole("button", { name: "Add statement" }).click();
await addVisualStatement({ sid: "ReadByApp", principal: "arn:aws:iam::000000000000:role/app-role", action: "GetSecretValue", resource: "*" });
await page.getByRole("button", { name: "Save changes" }).click();
await page.getByRole("cell", { name: "ReadByApp" }).waitFor({ timeout: 10000 });
const sec = sent.secret.at(-1); const secDoc = sec && JSON.parse(sec.ResourcePolicy);
check("Secrets: PutResourcePolicy {SecretId, ResourcePolicy} with GetSecretValue for the role", sec?.SecretId === "demo-secret" && !!secDoc?.Statement.some((s) => s.Sid === "ReadByApp" && [].concat(s.Action).includes("secretsmanager:GetSecretValue")), JSON.stringify(sec).slice(150,500));
await page.screenshot({ path: `${SHOTS}/secrets-policy-view.png`, fullPage: true });
await page.getByTestId("rpol-secret").getByRole("button", { name: "Delete", exact: true }).click();
await page.getByText("No resource policy attached.").waitFor({ timeout: 10000 });
check("Secrets: Delete removes the stored policy (DeleteResourcePolicy)", store.secret === null);

check("no page errors", errs.length === 0, errs[0]);
await browser.close(); server.close();
const bad = results.filter((r) => !r).length;
console.log(`\n${results.length - bad}/${results.length} checks passed`);
process.exit(bad ? 1 : 0);
