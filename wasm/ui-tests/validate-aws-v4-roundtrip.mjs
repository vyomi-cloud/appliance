/* v4.0.0 AWS console (consoles/src/aws -> /v4/aws/) UI <-> SDK bi-directional round-trip.
 * UI = the v4 console in Playwright; SDK = boto3 (endpoint only changed) on the SAME wire (/_wire).
 *   A UI create -> SDK sees it   B SDK create -> UI lists it   C SDK delete -> UI drops it   D UI delete -> SDK gone
 * Env: BASE (default http://127.0.0.1:8741, = `python3 consoles/dev_server.py --port 8741` or the appliance),
 *      UI_PATH (/v4/aws/), WIRE_PATH (/_wire), PY (python with boto3), ONLY=s3,sqs,... */
import { chromium, sleep } from "./lib.mjs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const SDKPY = join(dirname(fileURLToPath(import.meta.url)), "_aws_roundtrip_sdk.py");
const BASE = process.env.BASE || "http://127.0.0.1:8741";
const UI = BASE + (process.env.UI_PATH || "/v4/aws/");
const WIRE = BASE + (process.env.WIRE_PATH || "/_wire");
const sdk = (svc, op, name) => { try { return JSON.parse(execFileSync(process.env.PY || "python3", [SDKPY, svc, op, name], { env: { ...process.env, VYOMI_BASE_URL: WIRE }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim().split("\n").pop()); } catch (e) { throw new Error("SDK " + svc + " " + op + ": " + String(e.stderr || e).trim().split("\n").slice(-1)[0].slice(0, 220)); } };
const ALL = "s3,sqs,sns,dynamodb,kms,secretsmanager,iam,vpc,ec2,ssm,kinesis,ecr,eventbridge,cloudwatch,apigateway,backup,networkmanager,states,eks,lambda,rds,cloudformation,imagebuilder".split(",");
const ONLY = (process.env.ONLY || ALL.join(",")).split(",");

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
page.on("dialog", (d) => d.accept("delete").catch(() => {}));
if (process.env.TRACE) page.on("request", (r) => { const t = r.postData() || ""; if (r.method() !== "GET" && /Delete|Terminate|Remove|CreateStack/i.test(t + r.url())) console.log("  wire>", (t || r.url()).slice(0, 160)); });
if (process.env.TRACE) page.on("response", async (r) => { const t = r.request().postData() || ""; if (r.request().method() !== "GET" && /Delete|Terminate|Remove|CreateStack/i.test(t)) console.log("  resp>", r.status(), (await r.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 400)); });
const results = [];
// Honest SKIPs (printed, never counted as PASS): checks this suite cannot drive yet, with the reason.
const SKIP = {
};
const skipped = [];
// EKS runs wherever the k3s backend exists (the GitHub runner / Codespace); skip only when this stack has none.
if (ONLY.includes("eks")) { try { const n = "rtprobe" + Date.now().toString(36); sdk("eks", "create", n); sdk("eks", "delete", n); } catch (e) { if (/ServiceUnavailable|Kubernetes backend/i.test(String(e))) SKIP["eks:*"] = "no Kubernetes (k3s) backend on this stack (CreateCluster -> ServiceUnavailable); runs on the runner where k3s is up"; } }
const check = (name, ok, extra = "") => {
  const m = /^\[(\w+)\] ([ABCD]) /.exec(name); const why = m && (SKIP[`${m[1]}:*`] || SKIP[`${m[1]}:${m[2]}`]);
  if (why && !ok) { skipped.push(name); console.log(`[SKIP] ${name} :: ${why}`); return; } results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
// never match the feedback widget (hidden "Submit" .vyfb-send sorts last and swallowed the form's Create click)
const vis = (sel, re) => page.locator(`:is(${sel}):not(.vyfb-send, .vyfb-send *)`, { hasText: re }).filter({ visible: true });
const ROUTES = { s3: ["s3", "s3/create"], sqs: ["sqs/queues", "sqs/create-queue"], sns: ["sns/topics", "sns/create-topic"], dynamodb: ["dynamodb/tables", "dynamodb/create-table"],
  kms: ["kms/customer-managed-keys", "kms/create-key"], secretsmanager: ["secretsmanager/listsecrets", "secretsmanager/newsecret"], iam: ["iam/users", "iam/create-user"], vpc: ["vpc/vpcs", "vpc/create-vpc"],
  ec2: ["ec2/key-pairs", "ec2/create-key-pair"], ssm: ["ssm/parameters", "ssm/create-parameter"], kinesis: ["kinesis/streams", "kinesis/streams/create"], ecr: ["ecr/repositories", null],
  eventbridge: ["eventbridge/event-buses", "eventbridge/create-event-bus"], cloudwatch: ["cloudwatch/logs", "cloudwatch/logs/create"], apigateway: ["apigateway/apis", "apigateway/create-rest-api"],
  backup: ["backup/vaults", null], networkmanager: ["networkmanager/global-networks", null], states: ["states/state-machines", "states/create"], eks: ["eks/clusters", "eks/create"],
  lambda: ["lambda/functions", "lambda/create/function"], rds: ["rds/databases", "rds/create-database"], cloudformation: ["cloudformation/stacks", "cloudformation/create"], imagebuilder: ["imagebuilder/pipelines", null] };
const go = async (svc, which = 0) => { await page.goto(`${UI}#/${ROUTES[svc][which] ?? ROUTES[svc][0]}`); await page.reload(); await sleep(2500); };
const body = () => page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
const listed = async (svc, name) => { await go(svc); await sleep(500); return (await body()).includes(name); };
const dump = () => page.evaluate(() => [...document.querySelectorAll("button")].filter((e) => e.offsetParent).map((e) => e.innerText.trim().replace(/\n/g, " ") + (e.disabled ? "(disabled)" : "")).filter(Boolean).slice(0, 14).join(" | "));
const INP = "input:visible:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=number]):not([placeholder*=earch]), textarea:visible";
let step = "";

async function uiCreate(svc, name) {
  step = "open create form"; if (ROUTES[svc][1]) await go(svc, 1); else { await go(svc); await vis("button, a", /^\s*(create|add|launch|new|store)\b/i).first().click({ timeout: 8000 }); await sleep(1500); }
  step = "fill";
  if (svc === "cloudformation") {   // wizard: template source -> stack name -> options -> review -> Create stack
    await page.locator("input[type=radio][value=s3url]").check({ force: true }).catch(() => {});
    await page.locator("input[placeholder*='s3.amazonaws.com']").fill("https://s3.amazonaws.com/rt-cfn-templates/t.json");
    for (let i = 0; i < 4 && (await vis("button", /^\s*submit\s*$/i).count()) === 0; i++) {
      await vis("button", /^\s*next\s*$/i).last().click({ timeout: 8000 }); await sleep(1500);
      const sn = page.locator("input[aria-label='Stack name'], input[placeholder='Stack name']").first();
      if (await sn.count()) { await sn.fill(name).catch(() => {}); }
      // only the Stack name field gets the name; optional fields (RoleARN, tags...) stay empty
    }
  }
  if (svc === "imagebuilder") {
    await page.locator("input[aria-label='Pipeline name']").fill(name);
    for (const ph of [/choose a recipe/i, /choose an infrastructure/i]) { await vis("button", ph).first().click({ timeout: 8000 }); await sleep(400); await page.locator("[role=option]:visible").first().click({ timeout: 8000 }); await sleep(300); }
  }
  const els = svc === "imagebuilder" || svc === "cloudformation" ? page.locator("input[aria-label='__none__']") : page.locator(INP);
  for (let i = 0; i < await els.count(); i++) { const e = els.nth(i); if (/optional/i.test((await e.getAttribute("aria-label")) || "")) continue; const v = await e.inputValue().catch(() => "x"); if (!v && /s3\.amazonaws\.com/.test((await e.getAttribute("placeholder")) || "")) { await e.fill("https://s3.amazonaws.com/rt-cfn-templates/t.json").catch(() => {}); continue; } if (!v || /^(my|My|Music|new-|database-|\/vyomi|\/aws|default)/.test(v)) await e.fill(name).catch(() => {}); }
  step = "submit";
  for (let i = 0; i < (svc === "cloudformation" ? 0 : 8); i++) { const nx = vis("button", /^\s*next\b/i); if (await nx.count() === 0) break; await nx.last().click(); await sleep(500); const e2 = page.locator(INP); for (let j = 0; j < await e2.count(); j++) { const e = e2.nth(j); if (/optional/i.test((await e.getAttribute("aria-label")) || "")) continue; if (!(await e.inputValue().catch(() => "x"))) await e.fill(name).catch(() => {}); } }
  // the form's own submit: not the feedback widget and not a (hidden) modal such as DynamoDB's "Create global index"
  await page.locator("button:not(.vyfb-send):not([role=dialog] *)", { hasText: /^\s*(create|add|launch|store|save|finish|submit)\b/i }).filter({ visible: true }).last().click({ timeout: 8000 }); await sleep(3000);
}
async function uiDelete(svc, name) {
  step = "open list"; await go(svc);
  step = "select row";
  const row = page.locator("tr", { hasText: name }).first();
  const sel = row.locator("input[type=checkbox], input[type=radio]");
  if (await sel.count()) await sel.first().click({ timeout: 8000 });
  else { const lnk = row.locator("a").first(); await lnk.click({ timeout: 8000 }); await sleep(2500); step = "select row (opened detail page)"; }
  step = "delete action";
  const DEL = /^\s*(permanently )?(delete|terminate|remove|schedule (key )?deletion)/i;
  // page-level delete only: the (hidden) confirmation modal and its disabled Delete button are always in the DOM
  const direct = page.locator("button:not([disabled]):not([role=dialog] *), a:not([role=dialog] *)", { hasText: DEL }).filter({ visible: true });
  if (await direct.count()) await direct.first().click({ timeout: 8000 });
  else { await vis("button", /^\s*(key )?actions\b/i).first().click({ timeout: 8000 }); await sleep(400); await vis("[role=menuitem], li, a, span", DEL).first().click({ timeout: 8000 }); }
  await sleep(1000);
  step = "confirm";
  const txt = await body();
  const word = /permanently delete/i.test(txt) ? "permanently delete" : /type (the )?(bucket |secret |table |stack )?name|enter the name/i.test(txt) ? name : "delete";
  const ins = page.locator("input:visible:not([type=radio]):not([type=checkbox]):not([type=number]):not([placeholder*=earch])");
  for (let i = 0; i < await ins.count(); i++) { const e = ins.nth(i); const ph = await e.getAttribute("placeholder"); if (/search|find|filter/i.test(ph || "") || (await e.getAttribute("type")) === "search") continue; await e.fill(ph || word).catch(() => {}); }
  const ok = vis("button, a[role=button]", /^\s*(permanently )?(delete|terminate|remove|schedule (key )?deletion)/i);
  if (await ok.count()) await ok.last().click({ timeout: 8000 });
  await sleep(3000);
}

for (const svc of ONLY) {
  const tag = `[${svc}]`, a = "rta" + Date.now().toString(36), b = "rtb" + Date.now().toString(36); let aOk = false;
  try { if (svc === "cloudformation" || svc === "imagebuilder") sdk(svc, "prep", a); await uiCreate(svc, a); const d = sdk(svc, "describe", a); aOk = !!d.exists; check(`${tag} A UI create -> SDK sees it`, aOk, JSON.stringify(d) + (aOk ? "" : ` | UI lists it: ${await listed(svc, a)} | btns: ${await dump()}`)); } catch (e) { check(`${tag} A UI create -> SDK sees it`, false, `step=${step}: ` + String(e).split("\n")[0].slice(0, 160) + ` | btns: ${await dump()} | err: ${(await body()).match(/(error|invalid|required|must)[^.]{0,120}/i)?.[0] || ""}`); }
  try { sdk(svc, "create", b); check(`${tag} B SDK create -> UI lists it`, await listed(svc, b), "SDK created, UI list lacks it"); } catch (e) { check(`${tag} B SDK create -> UI lists it`, false, String(e).split("\n")[0]); }
  try { sdk(svc, "delete", b); check(`${tag} C SDK delete -> UI drops it`, !(await listed(svc, b)), "UI still lists it"); } catch (e) { check(`${tag} C SDK delete -> UI drops it`, false, String(e).split("\n")[0]); }
  if (!aOk) { check(`${tag} D UI delete -> SDK no longer sees it`, false, "not run: A failed"); continue; }
  try { sdk(svc, "prep", a); await uiDelete(svc, a); const d = sdk(svc, "describe", a); check(`${tag} D UI delete -> SDK no longer sees it`, !d.exists, JSON.stringify(d)); } catch (e) { check(`${tag} D UI delete -> SDK no longer sees it`, false, `step=${step}: ` + String(e).split("\n")[0].slice(0, 200) + ` | at ${await page.evaluate(() => location.hash)} | btns: ${await dump()} | dlg: ${(await page.evaluate(() => [...document.querySelectorAll("[role=dialog]")].map((d) => d.innerText.replace(/\s+/g, " ").slice(0, 160)).join(" || ")))}`); }
}
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} passed, ${skipped.length} skipped (not driven)`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
