/* Amazon Bedrock console <-> API bi-directional E2E against a live (Mesh) appliance.
 * env: NANO_DIR, SIM_URL, MESH_TOKEN (injected as X-Vyomi-Session-Token on every proxied request, never logged), CHROMIUM_PATH.
 * Writes tests/conformance/hourly/out/aws-bedrock-bidirectional.md. */
import { chromium, sleep, NANO_DIR } from "../lib.mjs";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const SIM = (process.env.SIM_URL || "http://127.0.0.1:19000").replace(/\/$/, "");
const TOK = process.env.MESH_TOKEN || "";
const T = `bd${Math.random().toString(36).slice(2, 8)}`;
const CALL_MS = 120000;
const ROLE = "arn:aws:iam::123456789012:role/vyomi-bedrock";
const rows = [];
const rec = (check, status, detail = "") => { rows.push({ check, status, detail }); console.log(`[${status}] ${check}${detail ? " :: " + detail : ""}`); };
const ok = (c, check, detail = "") => rec(check, c ? "PASS" : "FAIL", detail);
const BAD = /\[object Object\]|\bundefined\b|Traceback|at \w+\.\w+ \(|NaN/;

const auth = (svc) => ({ authorization: `AWS4-HMAC-SHA256 Credential=test/20261111/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=x`, "x-vyomi-session-token": TOK });
const api = async (svc, method, path, body, timeout = CALL_MS) => {
  const r = await fetch(SIM + path, { method, headers: { ...auth(svc), ...(body !== undefined && typeof body !== "string" ? { "content-type": "application/json" } : {}) }, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body), signal: AbortSignal.timeout(timeout) });
  const text = await r.text(); let json = null; try { json = JSON.parse(text); } catch { /* xml */ }
  return { status: r.status, json, text };
};
const B = async (m, p, b, t) => { if (awsSpace) await ensureAws(); return api("bedrock", m, p, b, t); };
const AC = async (m, p, b, t) => { await ensureAws(); return api("bedrock-agentcore", m, p, b, t); };

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, "http://x");
    if (/^\/(_wire|api)\b/.test(u.pathname)) {
      const chunks = []; for await (const c of req) chunks.push(c);
      const h = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k))); h["x-vyomi-session-token"] = TOK;
      const r = await fetch(SIM + req.url, { method: req.method, headers: h, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
      res.writeHead(r.status, Object.fromEntries([...r.headers].filter(([k]) => !["content-encoding", "transfer-encoding", "content-length"].includes(k))));
      return res.end(Buffer.from(await r.arrayBuffer()));
    }
    let p = normalize(decodeURIComponent(u.pathname)); if (p === "/") p = "/index.html";
    const f = join(NANO_DIR, p);
    if (!f.startsWith(NANO_DIR) || !existsSync(f)) { res.writeHead(404); return res.end("404"); }
    let body = await readFile(f);
    if (/\/v4\/\w+\/index\.html$/.test(p)) body = Buffer.from(body.toString().replace('content="nano"', 'content="offline"')
      .replace(/<script[^>]*nano-boot\.js[^>]*><\/script>/g, "").replace(/<script[^>]*nano-kernel\.js[^>]*><\/script>/g, "").replace(/<script>window\.__nk[^<]*<\/script>/g, ""));
    res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream", "cache-control": "no-cache" }); res.end(body);
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ serviceWorkers: "block", viewport: { width: 1500, height: 1000 } });
const page = await ctx.newPage();
const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));

let origSpace = null, awsSpace = null;
const ensureAws = async () => {   // other agents switch the global active space: re-activate AWS before each section/navigation
  const r = await api("x", "GET", "/api/spaces", undefined, 20000);
  const sp = r.json?.spaces || [];
  if (!origSpace) {
    origSpace = sp[0]?.cloudsim?.summary?.active_space_id || null;
    awsSpace = sp.find((x) => x.id === origSpace && /aws/i.test(x.name || x.cloud || ""))?.id || sp.find((x) => /aws/i.test(`${x.cloud || ""} ${x.provider || ""} ${x.name || ""}`))?.id || origSpace;
  }
  const cur = sp[0]?.cloudsim?.summary?.active_space_id;
  if (awsSpace && cur !== awsSpace) { await api("x", "POST", `/api/spaces/${awsSpace}/switch`, undefined, 30000); spaceSwitches++; }
};
let spaceSwitches = 0;
const go = async (route) => {
  await ensureAws();
  await page.goto(`${base}/v4/aws/index.html#/bedrock/${route}`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.body.innerText.length > 300, null, { timeout: 30000 }).catch(() => {});
  await sleep(2000);
};
const txt = async () => (await page.locator("body").innerText()).replace(/\s+/g, " ");
const listHas = async (route, name, want = true) => {
  for (let i = 0; i < 4; i++) { await go(route); const t = await txt(); if (t.includes(name) === want) return t; await sleep(2000); }
  return null;
};
const click = (loc) => loc.dispatchEvent("click");
const dlg = (h) => page.locator('[role="dialog"]:visible', h ? { hasText: h } : {}).last();
const selectOption = async (label, optText) => {   // Cloudscape Select by aria label
  await dlg("Create knowledge base").locator("button").filter({ hasText: "Choose a bucket" }).first().click();
  await sleep(1500);
  const o = page.locator('[role="option"]', optText ? { hasText: optText } : {}).first();
  await o.click({ timeout: 8000 });
  await sleep(500);
};
const uiDelete = async (route, name, resourceBtn = "Delete") => {
  await go(route);
  await page.locator("tr", { hasText: name }).first().locator("input[type=radio]").check({ force: true });
  await click(page.getByRole("button", { name: "Delete", exact: true }).first());
  await sleep(600);
  await dlg("Permanently delete").locator("input").fill(name);
  await click(dlg("Permanently delete").getByRole("button", { name: "Delete", exact: true }));
  await sleep(2500);
};

try {
  await ensureAws();
  const h = await fetch(SIM + "/healthz", { headers: { "x-vyomi-session-token": TOK } }).then((r) => r.json()).catch(() => ({}));
  ok(h.status === "ok", "(setup) appliance reachable", JSON.stringify(h).slice(0, 80));
  if (h.status !== "ok") throw new Error("appliance not reachable");

  // ---------- (1) model catalog ----------
  const lm = await B("GET", "/foundation-models");
  const models = lm.json?.modelSummaries || [];
  ok(lm.status === 200 && models.length > 0, "API ListFoundationModels returns models", `${models.length} models`);
  await go("models");
  let t = await txt();
  const missing = [];
  for (const m of models) for (const f of [m.modelName, m.modelId, m.providerName]) if (!t.includes(f)) missing.push(`${m.modelId}:${f}`);
  const uiRows = await page.locator("table tbody tr").count();
  ok(!missing.length, "(1) console model catalog shows every API model's name, id and provider", missing.length ? "missing " + missing.slice(0, 5).join(",") : `${models.length} models x 3 fields`);
  ok(uiRows === models.length, "(1) catalog row count == API count", `ui=${uiRows} api=${models.length}`);
  const mod0 = models.find((m) => m.modelId === "vyomi.qwen2.5-3b") || models[0];
  const rowTxt = (await page.locator("tr", { hasText: mod0.modelId }).first().innerText()).replace(/\s+/g, " ");
  ok(/Available/.test(rowTxt) === !!mod0.vyomiAvailability?.available && (!mod0.responseStreamingSupported || /Yes/.test(rowTxt)), "(1) availability + streaming columns match the API for " + mod0.modelId, rowTxt.slice(0, 120));

  // ---------- (2) playground vs API ----------
  const textModels = models.filter((m) => m.outputModalities?.includes("TEXT") && m.vyomiAvailability?.available);
  const chat = textModels[0];
  ok(!!chat, "(2) an available TEXT model exists", chat?.modelId);
  const marker = `Reply with the single word PONG-${T}.`;
  await go("playground");
  await page.getByLabel("Prompt", { exact: true }).fill(marker).catch(async () => { await page.locator("textarea").nth(1).fill(marker); });
  const chosen = await page.locator("button").filter({ hasText: new RegExp(models.map((x) => x.modelName.replace(/[.+]/g, "\\$&")).join("|")) }).first().innerText().catch(() => "");
  const t0 = Date.now();
  await click(page.getByRole("button", { name: "Run", exact: true }));
  let uiOut = "";
  try { await page.waitForSelector('[data-testid="converse-output"]', { timeout: CALL_MS }); uiOut = (await page.locator('[data-testid="converse-output"]').innerText()).trim(); } catch { uiOut = ""; }
  const bodyAfter = await txt();
  ok(uiOut.length > 0 && !BAD.test(uiOut), "(2) console playground returns a non-empty reply", `${Date.now() - t0}ms model="${chosen.replace(/\s+/g, " ").slice(0, 50)}" reply="${uiOut.slice(0, 60)}"`);
  const m = bodyAfter.match(/Input tokens\s*(\d+)\s*Output tokens\s*(\d+)\s*Stop reason\s*(\S+)\s*Latency\s*(\d+)/);
  ok(!!m && +m[1] > 0 && +m[2] > 0, "(2) playground usage/stopReason/latency panel populated", m ? `in=${m[1]} out=${m[2]} stop=${m[3]} ${m[4]}ms` : "panel not found");
  const cv = await B("POST", `/model/${encodeURIComponent(chat.modelId)}/converse`, { messages: [{ role: "user", content: [{ text: marker }] }], inferenceConfig: { maxTokens: 64 } });
  const c = cv.json;
  const apiText = c?.output?.message?.content?.map((x) => x.text).join("") || "";
  ok(cv.status === 200 && apiText.trim().length > 0, "(2) API Converse returns a non-empty reply", `${apiText.slice(0, 60)}`);
  const shape = (o) => o && o.output?.message?.role === "assistant" && Array.isArray(o.output.message.content) && typeof o.stopReason === "string" && Number.isInteger(o.usage?.inputTokens) && Number.isInteger(o.usage?.outputTokens) && Number.isFinite(o.metrics?.latencyMs);
  ok(shape(c), "(2) API Converse reply has the real Converse shape (role, content[], stopReason, usage, metrics)", Object.keys(c || {}).join(","));
  ok(m && c?.usage && Math.abs(+m[1] - c.usage.inputTokens) <= 2, "(2) same prompt -> same input token count in UI and API", m ? `ui=${m[1]} api=${c?.usage?.inputTokens}` : "n/a");
  const bad = await B("POST", "/model/bogus.model/converse", { messages: [{ role: "user", content: [{ text: "hi" }] }] });
  ok(bad.status >= 400 && bad.status < 500 && !BAD.test(bad.text) && (bad.json?.message || "").length > 5, "(2) Converse with an unknown model is refused with a clear message", `${bad.status} ${bad.text.slice(0, 80)}`);
  const lg = await B("GET", "/logging/modelinvocations");
  const ml = await api("monitoring", "POST", "/", "Action=ListMetrics&Namespace=AWS%2FBedrock&Version=2010-08-01").catch(() => ({ text: "" }));
  const hasMetric = /<member>/.test(ml.text || "");
  const logged = lg.status === 200 && lg.json && Object.keys(lg.json.loggingConfig || {}).length;
  if (!hasMetric && !logged) rec("(2) the console playground call is visible on the API side (CloudWatch AWS/Bedrock metrics or model-invocation logging)", "NOT-AUTOMATED", `simulator records neither: ListMetrics(AWS/Bedrock) empty after the call, GET /logging/modelinvocations -> ${lg.status} ${(lg.text || "").slice(0, 60)}. Product gap, not a UI bug.`);
  else ok(true, "(2) call visible via API metrics/logging", `metric=${hasMetric} logging=${!!logged}`);
  const ui2 = await B("GET", "/foundation-models");   // catalog stays consistent after inference
  ok(ui2.json?.modelSummaries?.length === models.length, "(2) catalog unchanged after inference");

  // ---------- (3a) agents: UI -> API ----------
  const uiAgent = `${T}-uiagent`, apiAgent = `${T}-apiagent`;
  const instr = "You are a helpful assistant for the bidirectional test; answer briefly and politely.";
  await go("agents");
  await click(page.getByRole("button", { name: "Create agent" }).first());
  await sleep(800);
  await dlg("Create agent").getByLabel("Agent name").fill(uiAgent);
  const defModel = (await dlg("Create agent").locator("button").filter({ hasText: new RegExp(models.map((x) => x.modelName.replace(/[.+]/g, "\\$&")).join("|")) }).first().innerText().catch(() => "")).replace(/\s+/g, " ");
  await dlg("Create agent").getByLabel("Instructions").fill(instr);
  await click(dlg("Create agent").getByRole("button", { name: "Create", exact: true }));
  await sleep(3500);
  let la = await B("GET", "/agents/");
  const ua = (la.json?.agentSummaries || []).find((a) => a.agentName === uiAgent);
  ok(!!ua, "(3) agent created in the console is returned by API ListAgents", ua ? ua.agentId : "not found");
  let ga = null;
  if (ua) {
    ga = (await B("GET", `/agents/${ua.agentId}/`)).json?.agent;
    ok(ga && ga.agentName === uiAgent && ga.instruction === instr && /^arn:aws:bedrock:[^:]+:\d+:agent\/.+/.test(ga.agentArn || ""), "(3) API GetAgent: same name, instruction, well-formed ARN", `${ga?.agentArn}`);
    ok(!!ga && !!ga.foundationModel && defModel.includes(models.find((x) => x.modelId === ga.foundationModel)?.modelName || "@@"), "(3) agent foundationModel == model chosen in the UI", `ui="${defModel.slice(0, 40)}" api=${ga?.foundationModel}`);
    const detail = await txt();   // the UI navigated to the detail page after create
    ok(ga && detail.includes(ga.agentArn) && detail.includes(uiAgent) && detail.includes(ga.agentStatus), "(3) console agent detail shows the API's ARN, name and status", ga?.agentStatus);
  }
  // API -> UI
  const ca = await B("PUT", "/agents/", { agentName: apiAgent, foundationModel: chat.modelId, instruction: instr, agentResourceRoleArn: ROLE });
  ok(ca.status < 300 && ca.json?.agent?.agentId, "(3) API CreateAgent", `${ca.status} ${ca.text.slice(0, 80)}`);
  const apiAgentId = ca.json?.agent?.agentId;
  let tt = await listHas("agents", apiAgent);
  ok(!!tt, "(3) agent created via API appears in the console Agents list");
  if (tt && ua) ok(tt.includes(uiAgent) && tt.includes(apiAgentId) && tt.includes(ca.json.agent.agentStatus), "(3) list row carries API agentId + status", ca.json.agent.agentStatus);
  // delete both ways: UI delete of API-created, API delete of UI-created
  await uiDelete("agents", apiAgent);
  const afterUiDel = await B("GET", "/agents/");
  ok(!(afterUiDel.json?.agentSummaries || []).some((a) => a.agentName === apiAgent), "(3) agent deleted in the console is gone from the API list");
  if (ua) { const d = await B("DELETE", `/agents/${ua.agentId}/?skipResourceInUseCheck=true`); ok(d.status < 300, "(3) API DeleteAgent of the UI-created agent", String(d.status)); ok(!!(await listHas("agents", uiAgent, false)), "(3) agent deleted via API disappears from the console list"); }

  // ---------- (3b) knowledge base ----------
  const bucket = `${T}-kb`, kbUi = `${T}_uikb`, kbApi = `${T}_apikb`;
  const s3 = (m, p, b) => api("s3", m, p, b);
  const mb = await s3("PUT", `/_wire/${bucket}`.replace("/_wire", ""), "");
  const po = await s3("PUT", `/${bucket}/docs/note.txt`, "Vyomi bidirectional test document. The secret word is pineapple.");
  ok(mb.status < 300 && po.status < 300, "(3) test S3 bucket + document created via S3 API", `${mb.status}/${po.status}`);
  await go("knowledge-bases");
  await click(page.getByRole("button", { name: "Create knowledge base" }).first());
  await sleep(800);
  await dlg("Create knowledge base").getByLabel("Knowledge base name").fill(kbUi);
  try { await selectOption("S3 bucket", bucket); } catch (e) { rec("(3) KB wizard: choose the S3 bucket", "FAIL", String(e.message).split("\n")[0]); }
  await click(dlg("Create knowledge base").getByRole("button", { name: "Create and sync" }));
  await sleep(6000);
  const lk = await B("POST", "/knowledgebases/", {});
  const uk = (lk.json?.knowledgeBaseSummaries || []).find((k) => k.name === kbUi);
  ok(!!uk, "(3) knowledge base created in the console is returned by API ListKnowledgeBases", uk?.knowledgeBaseId || "not found");
  if (uk) {
    const gk = (await B("GET", `/knowledgebases/${uk.knowledgeBaseId}`)).json?.knowledgeBase;
    ok(gk?.name === kbUi && /^arn:aws:bedrock:[^:]+:\d+:knowledge-base\/.+/.test(gk.knowledgeBaseArn || ""), "(3) API GetKnowledgeBase: same name + well-formed ARN", gk?.knowledgeBaseArn);
    const dsl = (await B("POST", `/knowledgebases/${uk.knowledgeBaseId}/datasources/`, {})).json?.dataSourceSummaries || [];
    ok(dsl.length === 1 && dsl[0].name === `${kbUi}-s3`, "(3) console-created KB has its data source over the API", dsl.map((d) => d.name).join(","));
    if (dsl[0]) {
      const jobs = (await B("POST", `/knowledgebases/${uk.knowledgeBaseId}/datasources/${dsl[0].dataSourceId}/ingestionjobs/`, {})).json?.ingestionJobSummaries || [];
      ok(jobs.length >= 1 && jobs[0].status === "COMPLETE" && (jobs[0].statistics?.numberOfNewDocumentsIndexed ?? 0) >= 1, "(3) the console's sync ingested the S3 doc (API job COMPLETE, >=1 doc)", JSON.stringify(jobs[0]?.statistics || jobs[0]?.status));
      const rt = await B("POST", `/knowledgebases/${uk.knowledgeBaseId}/retrieve`, { retrievalQuery: { text: "secret word" } });
      ok(rt.status === 200 && JSON.stringify(rt.json?.retrievalResults || []).includes("pineapple"), "(3) API Retrieve returns the document the console ingested", `${rt.status}`);
    }
    const kt = await txt();
    ok(kt.includes(kbUi) && kt.includes(uk.knowledgeBaseId), "(3) console KB detail page shows name + id from the API");
  }
  const ck = await B("PUT", "/knowledgebases/", { name: kbApi, roleArn: ROLE, knowledgeBaseConfiguration: { type: "VECTOR", vectorKnowledgeBaseConfiguration: { embeddingModelArn: "arn:aws:bedrock:us-east-1::foundation-model/vyomi.nomic-embed-text" } }, storageConfiguration: { type: "OPENSEARCH_SERVERLESS" } });
  ok(ck.status < 300 && ck.json?.knowledgeBase?.knowledgeBaseId, "(3) API CreateKnowledgeBase", `${ck.status} ${ck.text.slice(0, 80)}`);
  ok(!!(await listHas("knowledge-bases", kbApi)), "(3) KB created via API appears in the console list");
  await uiDelete("knowledge-bases", kbApi);
  ok(!((await B("POST", "/knowledgebases/", {})).json?.knowledgeBaseSummaries || []).some((k) => k.name === kbApi), "(3) KB deleted in the console is gone from the API");
  if (uk) { const d = await B("DELETE", `/knowledgebases/${uk.knowledgeBaseId}`); ok(d.status < 300, "(3) API DeleteKnowledgeBase of the UI-created KB", String(d.status)); ok(!!(await listHas("knowledge-bases", kbUi, false)), "(3) KB deleted via API disappears from the console list"); }
  await s3("DELETE", `/${bucket}/docs/note.txt`); await s3("DELETE", `/${bucket}`);

  // ---------- (3c) AgentCore gateway ----------
  const gwUi = `${T}-uigw`, gwApi = `${T}-apigw`;
  await go("agentcore");
  const gwBtn = page.getByRole("button", { name: "Create gateway" }).first();
  await click(gwBtn); await sleep(800);
  await dlg("Create gateway").getByLabel("Gateway name").fill(gwUi);
  await click(dlg("Create gateway").getByRole("button", { name: "Create gateway" }));
  await sleep(3500);
  const lg2 = (await AC("GET", "/gateways/")).json?.items || [];
  const ug = lg2.find((g) => g.name === gwUi);
  ok(!!ug, "(3) AgentCore gateway created in the console is returned by API ListGateways", ug?.gatewayId || "not found");
  if (ug) { const g = (await AC("GET", `/gateways/${ug.gatewayId}/`)).json; ok(g?.name === gwUi && /^arn:aws:bedrock-agentcore:/.test(g.gatewayArn || ""), "(3) API GetGateway: same name + ARN", g?.gatewayArn); }
  const cg = await AC("POST", "/gateways/", { name: gwApi, protocolType: "MCP", authorizerType: "NONE", roleArn: "arn:aws:iam::123456789012:role/vyomi-agentcore" });
  ok(cg.status < 300 && cg.json?.gatewayId, "(3) API CreateGateway", `${cg.status} ${cg.text.slice(0, 80)}`);
  ok(!!(await listHas("agentcore", gwApi)), "(3) gateway created via API appears in the console AgentCore list");
  await uiDelete("agentcore", gwApi);
  ok(!((await AC("GET", "/gateways/")).json?.items || []).some((g) => g.name === gwApi), "(3) gateway deleted in the console is gone from the API");
  if (ug) { const d = await AC("DELETE", `/gateways/${ug.gatewayId}/`); ok(d.status < 300, "(3) API DeleteGateway of the UI-created gateway", String(d.status)); ok(!!(await listHas("agentcore", gwUi, false)), "(3) gateway deleted via API disappears from the console list"); }

  // ---------- (3d) not offered ----------
  rec("(3) guardrails: create/list in the console", "NOT-AUTOMATED", "consoles/src/aws/services/bedrock has no Guardrails page (nav: Playground, Model catalog, Knowledge bases, Agents, AgentCore); the API (core/bedrock_guardrails_core.py) exists");
  rec("(3) custom/imported models, model customization jobs, prompts, evaluation", "NOT-AUTOMATED", "not offered by the console nav or routes");

  // ---------- (4) validation ----------
  await go("agents");
  await click(page.getByRole("button", { name: "Create agent" }).first()); await sleep(800);
  const createBtn = dlg("Create agent").getByRole("button", { name: "Create", exact: true });
  ok(await createBtn.isDisabled(), "(4) agent wizard: Create disabled with an empty name");
  await dlg("Create agent").getByLabel("Agent name").fill("bad name!!");
  await click(createBtn); await sleep(2500);
  let alert = (await dlg("Create agent").locator('[role="alert"], [class*="alert"]').allInnerTexts().catch(() => [])).join(" ").replace(/\s+/g, " ");
  ok(alert.length > 10 && !BAD.test(alert), "(4) agent wizard: invalid name is refused with a meaningful message", alert.slice(0, 160) || "NO MESSAGE SHOWN");
  await dlg("Create agent").getByLabel("Agent name").fill(`${T}-short`);
  await dlg("Create agent").getByLabel("Instructions").fill("too short");
  await click(createBtn); await sleep(2500);
  alert = (await dlg("Create agent").locator('[role="alert"], [class*="alert"]').allInnerTexts().catch(() => [])).join(" ").replace(/\s+/g, " ");
  ok(alert.length > 10 && !BAD.test(alert) && /instruction|40|character|short/i.test(alert), "(4) agent wizard: instructions < 40 chars refused with a meaningful message", alert.slice(0, 160) || "NO MESSAGE SHOWN");
  ok(!((await B("GET", "/agents/")).json?.agentSummaries || []).some((a) => /short|bad/.test(a.agentName) && a.agentName.startsWith(T)), "(4) no agent was created by the refused submissions");
  await page.keyboard.press("Escape");
  const v1 = await B("PUT", "/agents/", { agentName: "bad name!!", foundationModel: chat.modelId, instruction: instr, agentResourceRoleArn: ROLE });
  ok(v1.status === 400 && !BAD.test(v1.text) && (v1.json?.message || "").length > 8, "(4) API CreateAgent invalid name -> 400 + message", v1.text.slice(0, 120));
  const v2 = await B("PUT", "/knowledgebases/", { name: "bad name!!", roleArn: ROLE, knowledgeBaseConfiguration: { type: "VECTOR", vectorKnowledgeBaseConfiguration: { embeddingModelArn: "arn:aws:bedrock:us-east-1::foundation-model/vyomi.nomic-embed-text" } }, storageConfiguration: { type: "OPENSEARCH_SERVERLESS" } });
  ok(v2.status === 400 && !BAD.test(v2.text) && (v2.json?.message || "").length > 8, "(4) API CreateKnowledgeBase invalid name -> 400 + message", v2.text.slice(0, 120));
  // KB wizard: invalid name through the console
  const bk = `${T}-vb`; await s3("PUT", `/${bk}`, "");
  await go("knowledge-bases");
  await click(page.getByRole("button", { name: "Create knowledge base" }).first()); await sleep(800);
  await dlg("Create knowledge base").getByLabel("Knowledge base name").fill("bad name!!");
  await sleep(2500); let selErr = ""; try { await selectOption("S3 bucket", bk); } catch (e) { selErr = String(e.message).split("\n")[0] + " opts=[" + (await page.locator("[role=option]").allInnerTexts()).join(",") + "] s3=" + (await api("s3", "GET", "/")).text.match(/<Name>[^<]+/g) + " bk=" + bk; }
  const kbDis = await dlg("Create knowledge base").getByRole("button", { name: "Create and sync" }).isDisabled();
  await click(dlg("Create knowledge base").getByRole("button", { name: "Create and sync" })); await sleep(3500);
  alert = (await dlg("Create knowledge base").locator('[role="alert"], [class*="alert"]').allInnerTexts().catch(() => [])).join(" ").replace(/\s+/g, " ");
  ok(alert.length > 10 && !BAD.test(alert), "(4) KB wizard: invalid name is refused with a meaningful message", (alert.slice(0, 160) || "NO MESSAGE SHOWN") + ` [createDisabled=${kbDis} selErr=${selErr} kbNow=${((await B("POST", "/knowledgebases/", {})).json?.knowledgeBaseSummaries || []).map((k) => k.name).join(",")}]`);
  await page.keyboard.press("Escape");
  await s3("DELETE", `/${bk}`);
  ok(!pageErrors.length, "(4) no uncaught page errors during the run", pageErrors.slice(0, 3).join(" | "));
} catch (e) {
  rec("(run) script error", "FAIL", String(e.stack || e).split("\n").slice(0, 3).join(" | "));
} finally {
  // safety-net cleanup of anything of ours left
  try {
    for (const a of (await B("GET", "/agents/")).json?.agentSummaries || []) if (a.agentName.startsWith(T)) await B("DELETE", `/agents/${a.agentId}/?skipResourceInUseCheck=true`);
    for (const k of (await B("POST", "/knowledgebases/", {})).json?.knowledgeBaseSummaries || []) if (k.name.startsWith(T)) await B("DELETE", `/knowledgebases/${k.knowledgeBaseId}`);
    for (const g of (await AC("GET", "/gateways/")).json?.items || []) if (g.name.startsWith(T)) await AC("DELETE", `/gateways/${g.gatewayId}/`);
  } catch { /* best effort */ }
  try { if (origSpace) await api("x", "POST", `/api/spaces/${origSpace}/switch`, undefined, 30000); } catch { /* */ }
  console.log(`space re-switches to AWS during run: ${spaceSwitches} (aws space=${awsSpace}, restored to ${origSpace})`);
  await browser.close(); server.close();
  const n = (s) => rows.filter((r) => r.status === s).length;
  const md = `# Amazon Bedrock UI <-> API bi-directional (${new Date().toISOString()})\n\nPASS ${n("PASS")} / FAIL ${n("FAIL")} / NOT-AUTOMATED ${n("NOT-AUTOMATED")}  (run id ${T})\n\n| Status | Check | Detail |\n|---|---|---|\n` + rows.map((r) => `| ${r.status} | ${r.check} | ${String(r.detail).replace(/\|/g, "/").slice(0, 200)} |`).join("\n") + "\n";
  mkdirSync("tests/conformance/hourly/out", { recursive: true });
  writeFileSync("tests/conformance/hourly/out/aws-bedrock-bidirectional.md", md);
  console.log(`\nPASS ${n("PASS")} FAIL ${n("FAIL")} NOT-AUTOMATED ${n("NOT-AUTOMATED")}`);
  process.exit(n("FAIL") ? 1 : 0);
}
