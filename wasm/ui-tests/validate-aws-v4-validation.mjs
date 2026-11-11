/* v4.0.0 AWS console form validation + meaningful errors (check 4, UI half).
 * For each service's create form: submit INVALID input and require (a) the form does NOT create the resource,
 * (b) the user sees a readable error (inline field error or flashbar) that is not "undefined"/"[object ...]"/a stack trace/a bare
 * HTTP code, (c) no 5xx from the wire. The SDK half (same wire, no UI) is _aws_validation_sdk.py.
 * Env: BASE (default http://127.0.0.1:8741), UI_PATH (/v4/aws/), ONLY=s3,sqs,..., TRACE=1, SDK_PY=<python with boto3> to also run the SDK half. */
import { chromium, sleep } from "./lib.mjs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const HERE = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE || "http://127.0.0.1:8741";
const UI = BASE + (process.env.UI_PATH || "/v4/aws/");
const BAD = "Bad Name!#";   // invalid for every name field below (space + punctuation + uppercase)
const ROUTES = {
  s3: "s3/create", sqs: "sqs/create-queue", sns: "sns/create-topic", dynamodb: "dynamodb/create-table", secretsmanager: "secretsmanager/newsecret",
  iam: "iam/create-user", vpc: "vpc/create-vpc", ssm: "ssm/create-parameter", kinesis: "kinesis/streams/create", eventbridge: "eventbridge/create-event-bus",
  cloudwatch: "cloudwatch/logs/create", apigateway: "apigateway/create-rest-api", states: "states/create", lambda: "lambda/create/function",
  rds: "rds/create-database", cloudformation: "cloudformation/create", ecr: "ecr/repositories", backup: "backup/vaults",
};
// Honest SKIPs (printed, never PASS): forms this suite cannot drive yet / that have no invalid-name input.
const SKIP = {
  kms: "key creation has no required name field (alias optional); invalid-input path is covered by the SDK half",
  ec2: "key-pair names accept any ASCII, so no name is invalid there",
  networkmanager: "create is a free-form description only", imagebuilder: "multi-step wizard needs prepared recipe/infra; covered by the SDK half",
  eks: "needs the k3s backend (runs on the runner)",
};
// Free-text name fields (any string is valid) are tested with an EMPTY name; the VPC form is tested with a bad CIDR instead.
const EMPTY = new Set(["apigateway"]);
const ONLY = (process.env.ONLY || Object.keys(ROUTES).concat(Object.keys(SKIP)).join(",")).split(",");
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
const wire = [];
page.on("response", async (r) => { const q = r.request(); if (q.method() === "GET" || !/_wire|\/api\//.test(r.url())) return; wire.push({ status: r.status(), post: (q.postData() || "").slice(0, 300), body: (await r.text().catch(() => "")).slice(0, 400) }); });
const results = []; const skipped = [];
const rec = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${extra ? " :: " + extra : ""}`); };
const body = () => page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
const vis = (sel, re) => page.locator(sel, { hasText: re }).filter({ visible: true });
const INP = "input:visible:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=number]):not([placeholder*=earch]), textarea:visible";
const BADTOK = /undefined|\[object|NaN\b|Traceback|Internal Server Error|TypeError|KeyError|AttributeError|at Object\.|\bnull\b is not/i;
const GOODERR = /invalid|must|can only|can't|cannot|not valid|pattern|already|characters|required|between|should|only contain|use only|allowed|illegal|begin with|start with|unsupported|enter a|at least|no more than|exceeds/i;
const errRegion = () => page.evaluate(() => [...document.querySelectorAll("[role=alert], [class*=error], [class*=Error], [class*=flash], [class*=Flash], [data-testid*=error], [id*=error]")]
  .filter((e) => e.offsetParent && e.innerText.trim()).map((e) => e.innerText.replace(/\s+/g, " ").trim()).join(" || ").slice(0, 600));

async function openForm(svc) {
  await page.goto(`${UI}#/${ROUTES[svc]}`); await page.reload(); await sleep(2500);
  if (svc === "ecr" || svc === "backup") { await vis("button, a", /^\s*(create|add|new)\b/i).first().click({ timeout: 8000 }); await sleep(1500); }
}
async function fillAndSubmit(svc) {
  wire.length = 0;
  if (svc === "cloudformation") {   // wizard: template source -> stack name -> ... -> Submit
    await page.locator("input[type=radio][value=s3url]").check({ force: true }).catch(() => {});
    await page.locator("input[placeholder*='s3.amazonaws.com']").fill("https://s3.amazonaws.com/nope/t.json").catch(() => {});
    for (let i = 0; i < 4 && (await vis("button", /^\s*submit\s*$/i).count()) === 0; i++) {
      await vis("button", /^\s*next\s*$/i).last().click({ timeout: 8000 }).catch(() => {}); await sleep(1200);
      const sn = page.locator("input[aria-label='Stack name'], input[placeholder='Stack name']").first();
      if (await sn.count()) await sn.fill(BAD).catch(() => {});
    }
  } else {
    const els = page.locator(INP);
    for (let i = 0; i < await els.count(); i++) { const e = els.nth(i); const v = await e.inputValue().catch(() => "x");
      if (svc === "vpc" && /^\d+\.\d+\.\d+\.\d+\/\d+$/.test(v)) { await e.fill("10.0.0.0/8").catch(() => {}); continue; }   // VPC netmask must be /16../28
      if (EMPTY.has(svc)) { await e.fill("").catch(() => {}); continue; }
      if (!v || /^(my|My|Music|new-|database-|\/vyomi|\/aws|default)/.test(v)) await e.fill(BAD).catch(() => {}); }
    for (let i = 0; i < 8; i++) { const nx = vis("button", /^\s*next\b/i); if (await nx.count() === 0) break; if (await nx.last().isDisabled()) break; await nx.last().click(); await sleep(500); const e2 = page.locator(INP); for (let j = 0; j < await e2.count(); j++) { const e = e2.nth(j); if (!(await e.inputValue().catch(() => "x"))) await e.fill(BAD).catch(() => {}); } }
  }
  const btn = vis("button", /^\s*(create|add|launch|store|save|finish|submit)\b/i).last();
  if (!(await btn.count())) return "no-submit-button";
  const disabled = await btn.isDisabled();
  if (!disabled) { await btn.click({ timeout: 8000 }).catch(() => {}); await sleep(2500); }
  return disabled ? "disabled" : "clicked";
}

for (const svc of ONLY) {
  const tag = `[${svc}] invalid name is refused with a readable error`;
  if (SKIP[svc]) { skipped.push(svc); console.log(`[SKIP] ${tag} :: ${SKIP[svc]}`); continue; }
  if (!ROUTES[svc]) { skipped.push(svc); console.log(`[SKIP] ${tag} :: no route`); continue; }
  try {
    await openForm(svc);
    const how = await fillAndSubmit(svc);
    const txt = await body(), region = await errRegion();
    const created = wire.find((w) => w.status < 300 && /Create|Put|Run|New|Register|Make|Add/i.test(w.post) && !/Describe|List|Get/i.test(w.post.slice(0, 60)));
    const serverErr = wire.find((w) => w.status >= 500);
    const msg = region || (txt.match(new RegExp(`[^.]{0,80}(${GOODERR.source})[^.]{0,100}`, "i")) || [""])[0];
    let why = "";
    if (how === "no-submit-button") why = "driver: no submit button found";
    else if (serverErr) why = `5xx from the wire: ${serverErr.status} ${serverErr.body.slice(0, 160)}`;
    else if (created) why = `SILENT SUCCESS: the wire accepted the invalid name (${created.post.slice(0, 100)})`;
    else if (BADTOK.test(region) || (wire.length && BADTOK.test(wire.map((w) => w.body).join(" ").slice(0, 400)) && !GOODERR.test(region + txt))) why = `unreadable error text: ${(region || "").slice(0, 160)}`;
    else if (!GOODERR.test(msg)) why = how === "disabled" ? "Create is disabled with no explanation" : `no readable error shown (clicked=${how}, wire calls=${wire.length}, page: ${txt.slice(0, 120)})`;
    if (why.startsWith("driver:")) { skipped.push(svc); console.log(`[SKIP] ${tag} :: ${why}`); continue; }
    rec(tag, !why, why || `"${msg.slice(0, 110)}"`);
  } catch (e) { rec(tag, false, "driver exception: " + String(e).split("\n")[0].slice(0, 160)); }
}
await browser.close();
let sdkOk = true;
if (process.env.SDK_PY) {   // the SDK half, same wire
  try { const o = execFileSync(process.env.SDK_PY, [join(HERE, "_aws_validation_sdk.py")], { env: { ...process.env, VYOMI_BASE_URL: BASE + (process.env.WIRE_PATH || "/_wire") }, encoding: "utf8" }); console.log(o.trim().split("\n").slice(-1)[0]); }
  catch (e) { sdkOk = false; console.log(String(e.stdout || e).split("\n").filter((l) => /FAIL|passed/.test(l)).join("\n")); }
}
console.log(`\nUI half: ${results.filter(Boolean).length}/${results.length} passed, ${skipped.length} skipped (not driven)`);
process.exit(results.length && results.every(Boolean) && sdkOk ? 0 : 1);
