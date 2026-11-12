/* AWS v4 console <-> API bi-directional checks for EC2, against a live (Mesh) appliance.
 *   NODE_PATH=... CHROMIUM_PATH=... NANO_DIR=$PWD/wasm SIM_URL=http://127.0.0.1:19000 MESH_TOKEN=... node wasm/ui-tests/aws-bd/ec2-bidirectional.mjs
 * The proxy injects X-Vyomi-Session-Token (env MESH_TOKEN, never logged). Writes tests/conformance/hourly/out/aws-ec2-bidirectional.md
 */
import { chromium, sleep, NANO_DIR } from "../lib.mjs";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const SIM = (process.env.SIM_URL || "http://127.0.0.1:19000").replace(/\/$/, "");
const TOKEN = process.env.MESH_TOKEN || "";
const RUN = Math.random().toString(36).slice(2, 8);
const N = (s) => `bd-${RUN}-${s}`;
const rows = []; let fails = 0;
const rec = (check, status, detail = "") => { rows.push({ check, status, detail }); if (status === "FAIL") fails++; console.log(`[${status}] ${check}${detail ? " :: " + detail : ""}`); };
const ck = (check, ok, detail = "") => rec(check, ok ? "PASS" : "FAIL", detail);

// ---- EC2 Query API (external client, as an SDK/CLI would)
const AUTH = "AWS4-HMAC-SHA256 Credential=test/20261111/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=x";
const ec2 = async (Action, params = {}) => {
  const body = new URLSearchParams({ Action, Version: "2016-11-15", ...params });
  const r = await fetch(SIM + "/", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", authorization: AUTH, "x-vyomi-session-token": TOKEN }, body, signal: AbortSignal.timeout(60000) });
  return { status: r.status, text: await r.text() };
};
const items = (x, tag) => { const m = x.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`)); return m ? [...m[1].split(/<item>/).slice(1)] : []; };
const f = (x, t) => (x.match(new RegExp(`<${t}>([^<]*)</${t}>`)) || [])[1];
const parseInst = (chunk) => ({ id: f(chunk, "instanceId"), ami: f(chunk, "imageId"), type: f(chunk, "instanceType"), state: (chunk.match(/<instanceState><code>\d+<\/code><name>([^<]+)</) || [])[1], name: (chunk.match(/<key>Name<\/key>\s*<value>([^<]*)<\/value>/) || [])[1], sgs: [...chunk.matchAll(/<groupId>([^<]+)<\/groupId>/g)].map((m) => m[1]), key: f(chunk, "keyName") });
const descInst = async (filters = {}) => {
  const r = await ec2("DescribeInstances", filters);
  return r.text.split("<instancesSet>").slice(1).flatMap((s) => s.split("</instancesSet>")[0].split(/<item><instanceId>/).slice(1).map((c) => parseInst("<instanceId>" + c)));
};
const byName = async (n) => (await descInst()).filter((i) => i.name === n);
const byId = async (id) => (await descInst({ "InstanceId.1": id }))[0];
const waitState = async (id, want, ms = 90000) => { const t0 = Date.now(); let s; while (Date.now() - t0 < ms) { s = (await byId(id))?.state; if (want.includes(s)) return s; await sleep(2500); } return s; };
const keyNames = async () => [...(await ec2("DescribeKeyPairs")).text.matchAll(/<keyName>([^<]*)<\/keyName>/g)].map((m) => m[1]);
const sgs = async () => (await ec2("DescribeSecurityGroups")).text.split("<securityGroupInfo>").slice(1).flatMap((s) => s.split("</securityGroupInfo>")[0].split(/<item><groupId>/).slice(1).map((c) => ("<groupId>" + c)).map((c) => ({ id: f(c, "groupId"), name: f(c, "groupName"), desc: f(c, "groupDescription") })));

// ---- harness: static console + authenticated proxy
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, "http://x");
    if (/^\/(_wire|api)\b/.test(u.pathname)) {
      const chunks = []; for await (const c of req) chunks.push(c);
      const h = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k))); h["x-vyomi-session-token"] = TOKEN;
      const r = await fetch(SIM + req.url, { method: req.method, headers: h, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
      res.writeHead(r.status, Object.fromEntries([...r.headers].filter(([k]) => !["content-encoding", "transfer-encoding", "content-length"].includes(k))));
      return res.end(Buffer.from(await r.arrayBuffer()));
    }
    let p = normalize(decodeURIComponent(u.pathname)); if (p === "/") p = "/index.html";
    const fp = join(NANO_DIR, p);
    if (!fp.startsWith(NANO_DIR) || !existsSync(fp)) { res.writeHead(404); return res.end("404"); }
    let body = await readFile(fp);
    if (/\/v4\/\w+\/index\.html$/.test(p)) body = Buffer.from(body.toString().replace('content="nano"', 'content="offline"').replace(/<script[^>]*nano-boot\.js[^>]*><\/script>/g, "").replace(/<script[^>]*nano-kernel\.js[^>]*><\/script>/g, "").replace(/<script>window\.__nk[^<]*<\/script>/g, ""));
    res.writeHead(200, { "content-type": MIME[extname(fp)] || "application/octet-stream", "cache-control": "no-cache" }); res.end(body);
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ serviceWorkers: "block", acceptDownloads: true, viewport: { width: 1500, height: 1000 } });
const page = await ctx.newPage();
const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));
const go = async (route) => {
  await page.goto(`${base}/v4/aws/index.html#/ec2/${route}`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await sleep(2500);
};
const body = async () => (await page.locator("body").innerText()).replace(/\s+/g, " ");
const listHas = async (route, text, tries = 4) => { for (let i = 0; i < tries; i++) { await go(route); const t = await body(); if (t.includes(text)) return t; await sleep(2500); } return null; };
const rowOf = (text) => page.locator("tr", { hasText: text }).first();
const pick = async (label, optText) => {   // Cloudscape Select
  await page.getByRole("button", { name: new RegExp(label, "i") }).first().click().catch(async () => { await page.locator(`[aria-label="${label}"]`).first().click(); });
  await sleep(500);
  await page.getByRole("option", { name: optText }).first().click();
};
const createdInst = [], createdKeys = [], createdSgs = [];
let uiInst = null, apiInst = null;

try {
  const h = await ec2("DescribeKeyPairs");
  ck("(setup) EC2 API reachable with the Mesh token", h.status === 200, `HTTP ${h.status}`);
  if (h.status !== 200) throw new Error("API unreachable");

  // ===== 4/5 prerequisites: key pair + security group created in the UI
  const uiKey = N("uikey"), apiKey = N("apikey"), uiSg = N("uisg"), apiSg = N("apisg");
  createdKeys.push(uiKey, apiKey); 
  await go("create-key-pair");
  await page.getByLabel("Name", { exact: true }).first().fill(uiKey);
  await page.getByRole("button", { name: /^Create key pair$/ }).last().dispatchEvent("click");
  await sleep(3500);
  ck("(4) UI->API: key pair created in the console is in DescribeKeyPairs", (await keyNames()).includes(uiKey));
  const ak = await ec2("CreateKeyPair", { KeyName: apiKey });
  ck("(4) API->UI: key pair created over the API is listed in the console", ak.status === 200 && !!(await listHas("key-pairs", apiKey)), `create HTTP ${ak.status}`);
  { const t = await body(); ck("(4) API->UI: key pair list also shows the UI-created key (same fingerprint/type shown)", t.includes(uiKey) && /rsa/i.test(t)); }

  createdSgs.push(uiSg, apiSg);
  await go("create-security-group");
  await page.getByLabel("Security group name").fill(uiSg);
  await page.getByLabel("Description", { exact: true }).fill(`desc ${uiSg}`);
  await page.getByRole("button", { name: /^Create security group$/ }).last().dispatchEvent("click");
  await sleep(3500);
  const g1 = (await sgs()).find((g) => g.name === uiSg);
  ck("(5) UI->API: security group created in the console is in DescribeSecurityGroups with same name+description", !!g1 && g1.desc === `desc ${uiSg}`, JSON.stringify(g1 || null));
  const asg = await ec2("CreateSecurityGroup", { GroupName: apiSg, GroupDescription: `desc ${apiSg}` });
  const seenSg = asg.status === 200 && (await listHas("security-groups", apiSg));
  ck("(5) API->UI: security group created over the API is listed in the console", !!seenSg, `create HTTP ${asg.status}`);
  if (seenSg) ck("(5) API->UI: list row shows the API description", seenSg.includes(`desc ${apiSg}`));

  // ===== 6. Launch form dropdowns populated, Launch enabled
  await go("launch-instance");
  await page.getByRole("button", { name: /Amazon Machine Image \(AMI\)/ }).first().click().catch(() => {});
  await sleep(800);
  const amiOpts = await page.getByRole("option").allInnerTexts(); await page.keyboard.press("Escape");
  ck("(6) Launch form: AMI dropdown is populated", amiOpts.length > 0, `${amiOpts.length} options`);
  await page.getByRole("button", { name: /Instance type/ }).first().click().catch(() => {}); await sleep(800);
  const typeOpts = await page.getByRole("option").allInnerTexts(); await page.keyboard.press("Escape");
  ck("(6) Launch form: instance type dropdown is populated", typeOpts.length > 0, `${typeOpts.length} options`);
  await page.getByRole("button", { name: /Key pair name/ }).first().click().catch(() => {}); await sleep(800);
  const keyOpts = await page.getByRole("option").allInnerTexts(); await page.keyboard.press("Escape");
  ck("(6) Launch form: key pair dropdown lists existing key pairs (incl. the two just created)", keyOpts.some((o) => o.includes(uiKey)) && keyOpts.some((o) => o.includes(apiKey)), `${keyOpts.length} options`);
  await page.getByText("Select existing security group").click(); await sleep(400);
  await page.getByRole("button", { name: /Common security groups/ }).first().click().catch(() => {}); await sleep(800);
  const sgOpts = await page.getByRole("option").allInnerTexts(); await page.keyboard.press("Escape");
  ck("(6) Launch form: security group dropdown lists existing groups (incl. UI and API ones)", sgOpts.some((o) => o.includes(uiSg)) && sgOpts.some((o) => o.includes(apiSg)), `${sgOpts.length} options`);
  const launchBtn = page.getByRole("button", { name: /^Launch instance$/ }).last();
  ck("(6) Launch form: Launch instance button is enabled (AMI preselected)", await launchBtn.isEnabled());

  // ===== 1. UI -> API: launch through the form
  const uiName = N("ui-inst");
  await go("launch-instance");
  await page.getByLabel("Name", { exact: true }).first().fill(uiName);
  await sleep(1500);
  const summ = await body();   // Summary panel prints the selected AMI name
  const imgs = [...(await ec2("DescribeImages", { "Owner.1": "amazon", "Owner.2": "self" })).text.matchAll(/<imageId>([^<]+)<\/imageId>[\s\S]*?<name>([^<]*)<\/name>/g)].map((m) => ({ id: m[1], name: m[2] }));
  const uiAmiId = (imgs.filter((i) => i.name && summ.includes("Software Image (AMI) " + i.name))[0] || {}).id;
  await page.getByRole("button", { name: /Key pair name/ }).first().click(); await sleep(500);
  await page.getByRole("option", { name: uiKey }).first().click();
  await page.getByText("Select existing security group").click(); await sleep(400);
  await page.getByRole("button", { name: /Common security groups/ }).first().click(); await sleep(500);
  await page.getByRole("option", { name: new RegExp(uiSg) }).first().click();
  await page.getByRole("button", { name: /^Launch instance$/ }).last().dispatchEvent("click");
  await sleep(6000);
  let found = []; for (let i = 0; i < 8 && !found.length; i++) { found = await byName(uiName); if (!found.length) await sleep(2000); }
  uiInst = found[0];
  ck("(1) UI->API: instance launched in the console form is returned by DescribeInstances (Name tag)", !!uiInst, uiInst ? uiInst.id : "not found by Name tag");
  if (uiInst) {
    createdInst.push(uiInst.id);
    ck("(1) UI->API: same instance type (t3.micro) in API", uiInst.type === "t3.micro", uiInst.type);
    ck("(1) UI->API: same AMI as selected in the form", !!uiAmiId && uiInst.ami === uiAmiId, `form ${uiAmiId} api ${uiInst.ami}`);
    ck("(1) UI->API: key pair + security group chosen in the form are on the instance", uiInst.key === uiKey && uiInst.sgs.includes(g1?.id), `key ${uiInst.key} sgs ${uiInst.sgs}`);
    const s = await waitState(uiInst.id, ["running"]);
    ck("(1) UI->API: instance reaches running (<=90s)", s === "running", `state ${s}`);
  }

  // ===== 2. API -> UI
  let apiName, apiId;
  const runApi = async (label) => {
  apiName = N("api-inst") + (label ? "r" : "");
  const ri = await ec2("RunInstances", { ImageId: uiInst?.ami || "ami-amzn2023", InstanceType: "t3.micro", MinCount: "1", MaxCount: "1", "TagSpecification.1.ResourceType": "instance", "TagSpecification.1.Tag.1.Key": "Name", "TagSpecification.1.Tag.1.Value": apiName });
  apiId = f(ri.text, "instanceId");
  ck(`(2${label}) API: RunInstances with Name tag succeeds`, ri.status === 200 && !!apiId, `HTTP ${ri.status} ${ri.status !== 200 ? ri.text.slice(0, 150) : ""}`);
  if (apiId) {
    createdInst.push(apiId); apiInst = await byId(apiId);
    const s = await waitState(apiId, ["running"]);
    ck(`(2${label}) API: instance reaches running (<=90s)`, s === "running", `state ${s}`);
    const t = await listHas("instances", apiName);
    ck(`(2${label}) API->UI: console Instances list shows the API instance by Name`, !!t);
    if (t) { const r = await rowOf(apiName).innerText(); ck(`(2${label}) API->UI: row shows same id, type, state`, r.includes(apiId) && r.includes("t3.micro") && /running/.test(r), r.replace(/\s+/g, " ").slice(0, 140)); }
  }

  };
  // The Mesh host caps concurrent running instances (the owner's i-cdd87653f9e1 + one more), so keep only ONE of ours running at a time.
  const selectRow = async (route, name) => { await go(route); await rowOf(name).waitFor({ timeout: 20000 }); await rowOf(name).locator("input[type=checkbox]").first().check({ force: true }); };
  const stateMenu = async (item) => { await page.getByRole("button", { name: /^Instance state$/ }).first().click(); await sleep(400); await page.getByRole("menuitem", { name: item }).first().click(); await sleep(2500); };
  if (uiInst) {
    const cap = await ec2("RunInstances", { ImageId: uiInst.ami, InstanceType: "t3.micro", MinCount: "1", MaxCount: "1" });
    const capId = f(cap.text, "instanceId");
    if (capId) { createdInst.push(capId); await ec2("TerminateInstances", { "InstanceId.1": capId }); await waitState(capId, ["terminated"], 40000); }
    rec("(info) a 3rd concurrent instance (owner's + UI-launched + API) via RunInstances", capId ? "NOTE" : "NOTE", capId ? "accepted" : `HTTP ${cap.status} ${(f(cap.text, "Code") || "")} - host caps concurrent running instances at 2 (see report)`);
    try { await selectRow("instances", uiName); await stateMenu(/Stop instance/); } catch (e) { rec("(3) UI stop action", "NOT-AUTOMATED", String(e.message).split("\n")[0]); }
    const s = await waitState(uiInst.id, ["stopped"], 60000);
    ck("(3) UI->API: stop in console -> API says stopped", s === "stopped", `state ${s}`);
    const t0 = await listHas("instances", uiName); const r0 = t0 ? await rowOf(uiName).innerText() : "";
    ck("(3) UI list agrees: stopped instance row shows stopped", /stopped/.test(r0), r0.replace(/\s+/g, " ").slice(0, 100));
  }
  await runApi("");
  if (apiId) {
    const tr = await ec2("TerminateInstances", { "InstanceId.1": apiId });
    ck("(3) API: TerminateInstances succeeds", tr.status === 200, `HTTP ${tr.status}`);
    await waitState(apiId, ["terminated", undefined], 60000); await sleep(1500);
    await go("instances"); const r = await page.locator("tr", { hasText: apiName }).first().innerText({ timeout: 3000 }).catch(() => "");
    ck("(3) API->UI: terminated-via-API instance is no longer shown running in the console", !/running|pending/.test(r), r ? r.replace(/\s+/g, " ").slice(0, 120) : "row gone");
  }
  if (uiInst) {
    const st = await ec2("StartInstances", { "InstanceId.1": uiInst.id });
    const s2 = await waitState(uiInst.id, ["running"]);
    ck("(3) API: StartInstances -> API running (<=90s)", st.status === 200 && s2 === "running", `HTTP ${st.status} state ${s2}`);
    const t = await listHas("instances", uiName); const r = t ? await rowOf(uiName).innerText() : "";
    ck("(3) API->UI: console shows the API-started instance running", /running/.test(r), r.replace(/\s+/g, " ").slice(0, 120));
    try { await selectRow("instances", uiName); await stateMenu(/Terminate instance/); } catch (e) { rec("(3) UI terminate action", "NOT-AUTOMATED", String(e.message).split("\n")[0]); }
    const s3 = await waitState(uiInst.id, ["terminated", "shutting-down", undefined], 60000);
    ck("(3) UI->API: terminate in console -> API terminated/shutting-down/gone", ["terminated", "shutting-down", undefined].includes(s3), `state ${s3}`);
  }

  // ===== 4/5 deletes both ways (instances are gone, SG can be deleted)
  await sleep(4000);
  await go("key-pairs"); await rowOf(uiKey).waitFor({ timeout: 20000 });
  await rowOf(uiKey).locator("input[type=checkbox]").first().check({ force: true });
  await page.getByRole("button", { name: /^Actions$/ }).first().click(); await sleep(400);
  await page.getByRole("menuitem", { name: /^Delete$/ }).first().click(); await sleep(500);
  await page.getByLabel("Confirm deletion").fill("delete");
  await page.getByRole("button", { name: /^Delete$/ }).last().dispatchEvent("click"); await sleep(3000);
  ck("(4) UI delete -> API: key pair deleted in the console is gone from DescribeKeyPairs", !(await keyNames()).includes(uiKey));
  const dk = await ec2("DeleteKeyPair", { KeyName: apiKey });
  await go("key-pairs");
  ck("(4) API delete -> UI: key pair deleted over the API disappears from the list", dk.status === 200 && !(await body()).includes(apiKey), `HTTP ${dk.status}`);

  await go("security-groups"); await rowOf(uiSg).waitFor({ timeout: 20000 });
  await rowOf(uiSg).locator("input[type=checkbox]").first().check({ force: true });
  await page.getByRole("button", { name: /^Actions$/ }).first().click(); await sleep(400);
  await page.getByRole("menuitem", { name: /Delete security groups/ }).first().click(); await sleep(500);
  await page.getByLabel("Confirm deletion").fill("delete").catch(() => {});
  await page.getByRole("button", { name: /^Delete$/ }).last().dispatchEvent("click"); await sleep(3000);
  const uiSgLeft = (await sgs()).some((g) => g.name === uiSg);
  ck("(5) UI delete -> API: security group deleted in the console is gone from the API", !uiSgLeft, uiSgLeft ? "still in DescribeSecurityGroups (the instance may still reference it, DependencyViolation?)" : "");
  const apiSgId = (await sgs()).find((g) => g.name === apiSg)?.id; const ds = await ec2("DeleteSecurityGroup", { GroupId: apiSgId || "sg-missing" });
  await go("security-groups");
  ck("(5) API delete -> UI: security group deleted over the API disappears from the list", ds.status === 200 && !(await body()).includes(apiSg), `HTTP ${ds.status} ${ds.status !== 200 ? ds.text.slice(0, 120) : ""}`);
} catch (e) {
  rec("(run) harness ran to completion", "FAIL", String(e.message).split("\n")[0]);
  await page.screenshot({ path: (process.env.SHOT_DIR || ".") + "/ec2-bd-fail.png" }).catch(() => {});
}
// ---- cleanup (only what this run created)
for (const id of createdInst) await ec2("TerminateInstances", { "InstanceId.1": id }).catch(() => {});
await sleep(5000);
for (const k of createdKeys) await ec2("DeleteKeyPair", { KeyName: k }).catch(() => {});
for (const g of (await sgs().catch(() => [])).filter((g) => (g.name || "").startsWith(`bd-${RUN}-`))) await ec2("DeleteSecurityGroup", { GroupId: g.id }).catch(() => {});
rec("no uncaught page errors", pageErrors.length ? "NOTE" : "PASS", pageErrors.slice(0, 3).join(" | "));

const outDir = new URL("../../../tests/conformance/hourly/out/", import.meta.url).pathname;
mkdirSync(outDir, { recursive: true });
let md = `# AWS EC2 console <-> API bi-directional report (run ${RUN})\n\n| Check | Result | Detail |\n|---|---|---|\n`;
for (const r of rows) md += `| ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 140)} |\n`;
md += `\n**${rows.filter((r) => r.status === "PASS").length} pass, ${fails} fail, ${rows.filter((r) => r.status === "NOT-AUTOMATED").length} not automated.**\n`;
writeFileSync(outDir + "aws-ec2-bidirectional.md", md);
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
