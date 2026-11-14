/* GENUINE NANO v4 AWS console UI <-> SDK bi-directional round-trip (A UI create->SDK, B SDK create->UI, C SDK delete->UI, D UI delete->SDK).
 * UI = /v4/aws/ in the real Nano bundle (service worker + Pyodide cores) in Playwright. SDK = the REAL boto3 (endpoint only changed) talking to a tiny local HTTP
 * bridge that forwards every request, byte for byte, into the SAME Nano page's /_wire/ (so boto3 and the console see one in-browser store).
 * Env: NANO_DIR (=<repo>/wasm), PY (python with boto3), ONLY=s3,sqs,... */
import { chromium, sleep, startServer } from "./lib.mjs";
import { execFile } from "node:child_process";
import http from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const SDKPY = join(dirname(fileURLToPath(import.meta.url)), "_aws_roundtrip_sdk.py");
const { server: staticSrv, base: BASE } = await startServer();
const UI = BASE + "/v4/aws/index.html";
const sdk = (svc, op, name) => new Promise((res, rej) => execFile(process.env.PY || "python3", [SDKPY, svc, op, name], { env: { ...process.env, VYOMI_BASE_URL: BRIDGE }, encoding: "utf8", timeout: 180000 }, (err, out, serr) => {
  if (err) return rej(new Error("SDK " + svc + " " + op + ": " + String(serr || err).trim().split("\n").slice(-1)[0].slice(0, 220)));
  try { res(JSON.parse(String(out).trim().split("\n").pop())); } catch (e) { rej(new Error("SDK " + svc + " " + op + ": bad output " + String(out).slice(0, 120))); } }));
const ALL = "s3,sqs,sns,dynamodb,kms,secretsmanager,iam,vpc,ec2,ssm,kinesis,ecr,eventbridge,cloudwatch,apigateway,backup,networkmanager,states,lambda,rds,cloudformation,imagebuilder".split(",");
const ONLY = (process.env.ONLY || ALL.join(",")).split(",");

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
// boto3 -> bridge -> Nano page /_wire/ (retries while the page is navigating/cold-loading)
const bridge = http.createServer(async (req, res) => {
  const chunks = []; for await (const c of req) chunks.push(c);
  const body = Buffer.concat(chunks).toString("base64");
  const hdr = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length", "accept-encoding", "expect"].includes(k)));
  for (let i = 0; i < 40; i++) {
    try {
      const r = await page.evaluate(async ([m, p, h, b]) => {
        const bin = b ? Uint8Array.from(atob(b), (c) => c.charCodeAt(0)) : undefined;
        const r = await fetch("/_wire" + p, { method: m, headers: h, body: m === "GET" || m === "HEAD" ? undefined : bin });
        const buf = new Uint8Array(await r.arrayBuffer()); let s = ""; for (let i = 0; i < buf.length; i += 8192) s += String.fromCharCode.apply(null, buf.subarray(i, i + 8192));
        return { status: r.status, headers: [...r.headers.entries()], b64: btoa(s) };
      }, [req.method, req.url, hdr, body]);
      res.writeHead(r.status, Object.fromEntries(r.headers.filter(([k]) => !["content-encoding", "transfer-encoding", "content-length", "connection"].includes(k))));
      return res.end(Buffer.from(r.b64, "base64"));
    } catch (e) { await sleep(1500); }
  }
  res.writeHead(502); res.end("bridge: Nano page unavailable");
});
await new Promise((r) => bridge.listen(0, "127.0.0.1", r));
const BRIDGE = `http://127.0.0.1:${bridge.address().port}`;
page.on("dialog", (d) => d.accept("delete").catch(() => {}));
if (process.env.TRACE) page.on("request", (r) => { const t = r.postData() || ""; if (r.method() !== "GET" && /Delete|Terminate|Remove|CreateStack/i.test(t + r.url())) console.log("  wire>", (t || r.url()).slice(0, 160)); });
if (process.env.TRACE) page.on("response", async (r) => { const t = r.request().postData() || ""; if (r.request().method() !== "GET" && /Delete|Terminate|Remove|CreateStack/i.test(t)) console.log("  resp>", r.status(), (await r.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 400)); });
const results = [];
// Honest SKIPs (printed, never counted as PASS): checks this suite cannot drive yet, with the reason.
const SKIP = {
};
const skipped = [];
// EKS runs wherever the k3s backend exists (the GitHub runner / Codespace); skip only when this stack has none.
if (false && ONLY.includes("eks")) {   // Nano: EKS needs a k3s backend (reachable only via the tunnel) -> not driven here
  try { const n = "rtprobe" + Date.now().toString(36); await sdk("eks", "create", n); await sdk("eks", "delete", n); } catch (e) { if (/ServiceUnavailable|Kubernetes backend/i.test(String(e))) SKIP["eks:*"] = "no Kubernetes (k3s) backend on this stack (CreateCluster -> ServiceUnavailable); runs on the runner where k3s is up"; } }
const check = (name, ok, extra = "") => {
  const m = /^\[(\w+)\] ([ABCD]) /.exec(name); const why = m && (SKIP[`${m[1]}:*`] || SKIP[`${m[1]}:${m[2]}`]);
  if (why && !ok) { skipped.push(name); console.log(`[SKIP] ${name} :: ${why}`); return; } results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
const vis = (sel, re) => page.locator(sel, { hasText: re }).filter({ visible: true });
const ROUTES = { s3: ["s3", "s3/create"], sqs: ["sqs/queues", "sqs/create-queue"], sns: ["sns/topics", "sns/create-topic"], dynamodb: ["dynamodb/tables", "dynamodb/create-table"],
  kms: ["kms/customer-managed-keys", "kms/create-key"], secretsmanager: ["secretsmanager/listsecrets", "secretsmanager/newsecret"], iam: ["iam/users", "iam/create-user"], vpc: ["vpc/vpcs", "vpc/create-vpc"],
  ec2: ["ec2/key-pairs", "ec2/create-key-pair"], ssm: ["ssm/parameters", "ssm/create-parameter"], kinesis: ["kinesis/streams", "kinesis/streams/create"], ecr: ["ecr/repositories", null],
  eventbridge: ["eventbridge/event-buses", "eventbridge/create-event-bus"], cloudwatch: ["cloudwatch/logs", "cloudwatch/logs/create"], apigateway: ["apigateway/apis", "apigateway/create-rest-api"],
  backup: ["backup/vaults", null], networkmanager: ["networkmanager/global-networks", null], states: ["states/state-machines", "states/create"], eks: ["eks/clusters", "eks/create"],
  lambda: ["lambda/functions", "lambda/create/function"], rds: ["rds/databases", "rds/create-database"], cloudformation: ["cloudformation/stacks", "cloudformation/create"], imagebuilder: ["imagebuilder/pipelines", null] };
const go = async (svc, which = 0) => {
  const first = page.waitForResponse((r) => r.url().includes("/_wire/") && r.status() < 500, { timeout: 90000 }).catch(() => null);
  await page.goto("about:blank"); await page.goto(`${UI}#/${ROUTES[svc][which] ?? ROUTES[svc][0]}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller, null, { timeout: 90000, polling: 300 });
  await first; await sleep(2500);
};
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
  for (let i = 0; i < await els.count(); i++) { const e = els.nth(i); const v = await e.inputValue().catch(() => "x"); if (!v && /s3\.amazonaws\.com/.test((await e.getAttribute("placeholder")) || "")) { await e.fill("https://s3.amazonaws.com/rt-cfn-templates/t.json").catch(() => {}); continue; } if (!v || /^(my|My|Music|new-|database-|\/vyomi|\/aws|default)/.test(v)) await e.fill(name).catch(() => {}); }
  step = "submit";
  for (let i = 0; i < (svc === "cloudformation" ? 0 : 8); i++) { const nx = vis("button", /^\s*next\b/i); if (await nx.count() === 0) break; await nx.last().click(); await sleep(500); const e2 = page.locator(INP); for (let j = 0; j < await e2.count(); j++) { const e = e2.nth(j); if (!(await e.inputValue().catch(() => "x"))) await e.fill(name).catch(() => {}); } }
  await vis("button", /^\s*(create|add|launch|store|save|finish|submit)\b/i).last().click({ timeout: 8000 }); await sleep(3000);
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
  const direct = vis("button, a", DEL);
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

await go("s3");   // boot the Nano page first: the boto3 bridge forwards into it
for (const svc of ONLY) {
  const tag = `[${svc}]`, a = "rta" + Date.now().toString(36), b = "rtb" + Date.now().toString(36); let aOk = false;
  try { if (svc === "cloudformation" || svc === "imagebuilder") await sdk(svc, "prep", a); await uiCreate(svc, a); const d = await sdk(svc, "describe", a); aOk = !!d.exists; check(`${tag} A UI create -> SDK sees it`, aOk, JSON.stringify(d) + (aOk ? "" : ` | UI lists it: ${await listed(svc, a)} | btns: ${await dump()}`)); } catch (e) { check(`${tag} A UI create -> SDK sees it`, false, `step=${step}: ` + String(e).split("\n")[0].slice(0, 160) + ` | btns: ${await dump()} | err: ${(await body()).match(/(error|invalid|required|must)[^.]{0,120}/i)?.[0] || ""}`); }
  try { await sdk(svc, "create", b); check(`${tag} B SDK create -> UI lists it`, await listed(svc, b), "SDK created, UI list lacks it"); } catch (e) { check(`${tag} B SDK create -> UI lists it`, false, String(e).split("\n")[0]); }
  try { await sdk(svc, "delete", b); check(`${tag} C SDK delete -> UI drops it`, !(await listed(svc, b)), "UI still lists it"); } catch (e) { check(`${tag} C SDK delete -> UI drops it`, false, String(e).split("\n")[0]); }
  if (!aOk) { check(`${tag} D UI delete -> SDK no longer sees it`, false, "not run: A failed"); continue; }
  try { await sdk(svc, "prep", a); await uiDelete(svc, a); const d = await sdk(svc, "describe", a); check(`${tag} D UI delete -> SDK no longer sees it`, !d.exists, JSON.stringify(d)); } catch (e) { check(`${tag} D UI delete -> SDK no longer sees it`, false, `step=${step}: ` + String(e).split("\n")[0].slice(0, 200) + ` | at ${await page.evaluate(() => location.hash)} | btns: ${await dump()} | dlg: ${(await page.evaluate(() => [...document.querySelectorAll("[role=dialog]")].map((d) => d.innerText.replace(/\s+/g, " ").slice(0, 160)).join(" || ")))}`); }
}
await browser.close(); staticSrv.close(); bridge.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} passed, ${skipped.length} skipped (not driven)`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
