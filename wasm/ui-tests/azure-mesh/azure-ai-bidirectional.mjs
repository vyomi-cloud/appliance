/* Azure AI (Microsoft.CognitiveServices / Azure OpenAI) console <-> ARM / az CLI / data plane bi-directional E2E on a LIVE Mesh appliance.
 *   SIM_URL=http://127.0.0.1:19000 MESH_TOKEN=... NANO_DIR=$PWD/wasm node wasm/ui-tests/azure-mesh/azure-ai-bidirectional.mjs
 * The proxy injects X-Vyomi-Session-Token (env MESH_TOKEN, never printed/written). Mesh AI pack = CPU llama.cpp: model calls get 180s. */
import { chromium, sleep, NANO_DIR } from "../lib.mjs";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const run = promisify(execFile);

const SIM = (process.env.SIM_URL || "http://127.0.0.1:19000").replace(/\/$/, "");
const TOKEN = process.env.MESH_TOKEN || "";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const R = Date.now() % 1000000;
const RG = `bd-ai-${R}`;
const NS = "Microsoft.CognitiveServices";
const V = "2024-10-01";
const MODEL_TMO = 180000;
const rows = []; let fails = 0;
const rec = (check, status, detail = "") => {
  rows.push({ check, status, detail }); if (status === "FAIL") fails++;
  console.log(`[${status}] ${check}${detail ? " :: " + String(detail).replace(TOKEN || "\u0000", "***").slice(0, 300) : ""}`);
};
const H = { "X-Vyomi-Session-Token": TOKEN };
const call = async (method, path, body, headers = {}, tmo = 30000) => {
  const r = await fetch(SIM + path, { method, headers: { "content-type": "application/json", ...H, ...headers }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(tmo) });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* */ }
  return { status: r.status, json: j, text: t };
};
const q = `?api-version=${V}`;
const acctPath = (rg, n) => `/subscriptions/${SUB}/resourceGroups/${rg}/providers/${NS}/accounts/${n}`;
const hasAz = await run("az", ["--version"]).then(() => true, () => false);
const azPut = (url, body) => run("az", ["rest", "--skip-authorization-header", "--only-show-errors", "--method", "put", "--url", SIM + url, "--headers", `X-Vyomi-Session-Token=${TOKEN}`, "Content-Type=application/json", "--body", JSON.stringify(body)], { env: { ...process.env, AZURE_CORE_COLLECT_TELEMETRY: "false" }, timeout: 60000 });
const bad = (s) => /\[object Object\]|undefined|Traceback|at \w+\.\w+ \(|<\/?pre>|\bTypeError\b/.test(s);

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, "http://x");
    if (/^\/(_wire|api|subscriptions|azure-data|openai)\b/.test(u.pathname)) {
      const chunks = []; for await (const c of req) chunks.push(c);
      const r = await fetch(SIM + req.url, { method: req.method, headers: { ...Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k))), ...H }, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks), signal: AbortSignal.timeout(200000) });
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
const ctx = await browser.newContext({ serviceWorkers: "block" });
const page = await ctx.newPage();
const pageErrors = []; page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));
const dispatch = (l) => l.dispatchEvent("click");
const go = async (hash) => { await page.goto(`${base}/v4/azure/index.html#/${hash}`, { waitUntil: "domcontentloaded" }); await page.reload({ waitUntil: "domcontentloaded" }); await sleep(2500); };
const text = async () => (await page.locator("body").innerText()).replace(/\s+/g, " ");
const listHas = async (name) => { for (let i = 0; i < 3; i++) { await go("cognitiveservices"); await page.waitForFunction(() => /Name/.test(document.body.innerText), null, { timeout: 30000 }).catch(() => {}); const t = await text(); if (t.includes(name)) return t; await sleep(2000); } return null; };
const rowOf = (t, name) => { const i = t.indexOf(name); return i < 0 ? "" : t.slice(i, i + 160); };

const uiAcct = `bdai-ui-${R}`, apiAcct = `bdai-api-${R}`, cliAcct = `bdai-cli-${R}`;
const dep = (rg, a, d) => `${acctPath(rg, a)}/deployments/${d}`;
let key1 = "", endpoint = "";
try {
  const h = await call("GET", "/healthz"); rec("(setup) Mesh appliance reachable through the tunnel", h.json?.status === "ok" ? "PASS" : "FAIL", JSON.stringify(h.json || h.text).slice(0, 80));
  if (h.json?.status !== "ok") throw new Error("not reachable");
  await call("POST", "/api/spaces/space-azure-default/switch");
  const g = await call("PUT", `/subscriptions/${SUB}/resourcegroups/${RG}?api-version=2021-04-01`, { location: "eastus" });
  rec("(setup) create test resource group", g.status < 300 ? "PASS" : "FAIL", g.status);
  const mods = await call("GET", `/subscriptions/${SUB}/providers/${NS}/locations/eastus/models?api-version=${V}`);
  const mnames = (mods.json?.value || []).map((m) => m.model?.name);
  rec("(setup) Mesh-only model catalogue offered (qwen2.5-3b + nomic-embed-text)", mnames.includes("qwen2.5-3b") && mnames.includes("nomic-embed-text") ? "PASS" : "FAIL", `${mnames.length} models; ${mods.status}`);

  // ---- (1) UI -> API: wizard
  await go("cognitiveservices/create");
  let created = false, why = "";
  try {
    await page.getByLabel("Resource group", { exact: true }).first().waitFor({ timeout: 30000 });
    await page.waitForFunction((rg) => [...document.querySelectorAll("select option")].some((o) => o.value === rg), RG, { timeout: 20000 });
    await page.locator("#cs-rg").selectOption(RG);
    await page.getByLabel("Name", { exact: true }).fill(uiAcct);
    await page.locator("#cs-region").selectOption("eastus");
    await page.getByRole("tab", { name: "Network" }).dispatchEvent("click");
    await page.getByLabel("Custom subdomain name").fill(uiAcct);
    await dispatch(page.getByRole("button", { name: /Review \+ create/ }).first());
    await dispatch(page.getByRole("button", { name: /^Create$/ }).first());
    await sleep(4000); created = true;
  } catch (e) { why = String(e.message).split("\n")[0]; }
  const g1 = await call("GET", acctPath(RG, uiAcct) + q);
  const a1 = g1.json || {};
  rec("(1) UI->API: account created in the wizard is returned by ARM GET", created && g1.status === 200 ? "PASS" : "FAIL", created ? `GET ${g1.status}` : why);
  if (g1.status === 200) {
    const ok = a1.name === uiAcct && a1.location === "eastus" && a1.kind === "OpenAI" && a1.sku?.name === "S0";
    rec("(1) UI->API: same name/location/kind/sku", ok ? "PASS" : "FAIL", JSON.stringify({ n: a1.name, l: a1.location, k: a1.kind, s: a1.sku?.name }));
    rec("(1) UI->API: provisioningState Succeeded and endpoint present", a1.properties?.provisioningState === "Succeeded" && /^https?:\/\//.test(a1.properties?.endpoint || "") ? "PASS" : "FAIL", `${a1.properties?.provisioningState} ${a1.properties?.endpoint}`);
    endpoint = a1.properties?.endpoint || "";
  }

  // ---- (2) API -> UI, CLI -> UI
  const p = await call("PUT", acctPath(RG, apiAcct) + q, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: apiAcct } });
  const t = p.status < 300 && await listHas(apiAcct);
  rec("(2) API->UI: ARM-created account is listed in the console", t ? "PASS" : "FAIL", p.status >= 300 ? `PUT ${p.status} ${p.text.slice(0, 100)}` : (t ? "listed" : "not listed"));
  if (t) { const r = rowOf(t, apiAcct); rec("(2) API->UI: list row shows name, kind (Azure OpenAI) and region (East US)", /Azure OpenAI/.test(r) && /East US/.test(r) ? "PASS" : "FAIL", r); }
  if (hasAz) {
    const o = await azPut(acctPath(RG, cliAcct) + q, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: cliAcct } }).catch((e) => ({ stderr: String(e.message) }));
    const tc = await listHas(cliAcct);
    rec("(2) CLI->UI: `az rest` account is listed in the console", tc ? "PASS" : "FAIL", tc ? "" : String(o.stderr || "").slice(0, 150));
  } else rec("(2) CLI->UI", "NOT-AUTOMATED", "az not installed");
  const lt = await listHas(uiAcct);
  rec("(2) UI list shows the wizard-created account with region", lt && /East US/.test(rowOf(lt, uiAcct)) ? "PASS" : "FAIL", lt ? rowOf(lt, uiAcct) : "not listed");

  // keys
  const kr = await call("POST", acctPath(RG, uiAcct) + "/listKeys" + q);
  key1 = kr.json?.key1 || "";
  rec("(4) listKeys returns key1/key2", kr.status === 200 && key1 && kr.json?.key2 ? "PASS" : "FAIL", `HTTP ${kr.status}`);

  // ---- (3) deployments UI -> ARM
  const depUi = async (name, model, cap) => {
    await go(`cognitiveservices/${RG}/${uiAcct}/deployments`);
    await page.getByRole("button", { name: /Create new deployment/ }).or(page.getByText("Create new deployment")).first().dispatchEvent("click");
    const d = page.getByRole("dialog", { name: /Deploy model/ }); await d.waitFor({ timeout: 15000 });
    await d.getByLabel("Select a model").selectOption(model);
    await d.getByLabel("Deployment name").fill(name);
    await d.getByLabel(/Tokens per minute/).fill(String(cap));
    await dispatch(d.getByRole("button", { name: /^Deploy$/ }));
    await sleep(3500);
    return d;
  };
  const cD = `bdchat${R}`, eD = `bdemb${R}`;
  try { await depUi(cD, "qwen2.5-3b", 7); } catch (e) { rec("(3) UI deploy chat dialog", "FAIL", String(e.message).split("\n")[0]); }
  let g2 = await call("GET", dep(RG, uiAcct, cD) + q);
  rec("(3) UI->ARM: chat deployment created in UI is returned by ARM", g2.status === 200 ? "PASS" : "FAIL", `GET ${g2.status}`);
  if (g2.status === 200) { const d = g2.json; rec("(3) UI->ARM: chat deployment same name/model/sku/capacity", d.name === cD && d.properties?.model?.name === "qwen2.5-3b" && d.sku?.name === "Standard" && d.sku?.capacity === 7 && d.properties?.provisioningState === "Succeeded" ? "PASS" : "FAIL", JSON.stringify({ n: d.name, m: d.properties?.model?.name, s: d.sku, ps: d.properties?.provisioningState })); }
  try { await depUi(eD, "nomic-embed-text", 3); } catch (e) { rec("(3) UI deploy embedding dialog", "FAIL", String(e.message).split("\n")[0]); }
  g2 = await call("GET", dep(RG, uiAcct, eD) + q);
  rec("(3) UI->ARM: embedding deployment created in UI is returned by ARM", g2.status === 200 && g2.json?.properties?.model?.name === "nomic-embed-text" && g2.json?.sku?.capacity === 3 ? "PASS" : "FAIL", `GET ${g2.status} ${JSON.stringify({ m: g2.json?.properties?.model?.name, s: g2.json?.sku })}`);
  const dl = await call("GET", `${acctPath(RG, uiAcct)}/deployments${q}`);
  rec("(3) UI->ARM: ARM deployments list has both", [cD, eD].every((n) => (dl.json?.value || []).some((x) => x.name === n)) ? "PASS" : "FAIL", (dl.json?.value || []).map((x) => x.name).join(","));

  // ---- ARM -> UI deployments (gpt-4o-mini alias of the local model + an embedding alias)
  const aC = `bdapichat${R}`, aE = `bdapiemb${R}`;
  const pc = await call("PUT", dep(RG, uiAcct, aC) + q, { sku: { name: "Standard", capacity: 5 }, properties: { model: { format: "OpenAI", name: "gpt-4o-mini", version: "1" } } });
  const pe = await call("PUT", dep(RG, uiAcct, aE) + q, { sku: { name: "Standard", capacity: 2 }, properties: { model: { format: "OpenAI", name: "text-embedding-3-small", version: "1" } } });
  rec("(3) ARM create deployments (gpt-4o-mini, text-embedding-3-small aliases of the Mesh models)", pc.status < 300 && pe.status < 300 ? "PASS" : "FAIL", `${pc.status} ${pe.status} ${pc.status >= 300 ? pc.text.slice(0, 150) : ""} ${pe.status >= 300 ? pe.text.slice(0, 150) : ""}`);
  await go(`cognitiveservices/${RG}/${uiAcct}/deployments`);
  const dt = await text();
  rec("(3) ARM->UI: UI deployments grid shows ARM-created deployments with model/type/capacity", dt.includes(aC) && dt.includes(aE) && new RegExp(aC + "\\s+gpt-4o-mini\\s+1\\s+Standard\\s+5").test(dt) ? "PASS" : "FAIL", rowOf(dt, aC));
  rec("(3) UI grid also shows UI-created rows with same values", new RegExp(cD + "\\s+qwen2.5-3b\\s+1\\s+Standard\\s+7").test(dt) ? "PASS" : "FAIL", rowOf(dt, cD));

  // ---- (4) inference
  const dp = (d, op) => `/azure-data/openai/${uiAcct}/openai/deployments/${d}/${op}?api-version=2024-10-21`;
  endpoint && rec("(4) account endpoint targets the appliance data plane /azure-data/openai/<acct>/", endpoint.includes(`/azure-data/openai/${uiAcct}`) ? "PASS" : "FAIL", endpoint);
  let t0 = Date.now();
  let c = await call("POST", dp(cD, "chat/completions"), { messages: [{ role: "user", content: "Reply with the single word: pong" }], max_tokens: 24 }, { "api-key": key1 }, MODEL_TMO).catch((e) => ({ status: 0, text: String(e.message) }));
  const cm = c.json?.choices?.[0]?.message?.content;
  rec("(4) data plane chat/completions (UI-created deployment): OpenAI-shaped, choices[0].message.content non-empty", c.status === 200 && typeof cm === "string" && cm.trim() && c.json.object === "chat.completion" && c.json.usage ? "PASS" : "FAIL", c.status === 0 ? `TIMEOUT/ERR after ${(Date.now() - t0) / 1000}s: ${c.text}` : `${c.status} ${Math.round((Date.now() - t0) / 1000)}s ${JSON.stringify(cm)?.slice(0, 80)} ${c.status !== 200 ? c.text.slice(0, 160) : ""}`);
  t0 = Date.now();
  c = await call("POST", dp(aC, "chat/completions"), { messages: [{ role: "user", content: "Say hello in one short sentence." }], max_tokens: 24 }, { "api-key": key1 }, MODEL_TMO).catch((e) => ({ status: 0, text: String(e.message) }));
  rec("(4) data plane chat on the ARM-created gpt-4o-mini deployment: non-empty", c.status === 200 && c.json?.choices?.[0]?.message?.content?.trim() ? "PASS" : "FAIL", c.status === 0 ? "TIMEOUT/ERR " + c.text : `${c.status} ${Math.round((Date.now() - t0) / 1000)}s`);
  t0 = Date.now();
  const em = await call("POST", dp(eD, "embeddings"), { input: ["vyomi mesh embedding check", "second"] }, { "api-key": key1 }, MODEL_TMO).catch((e) => ({ status: 0, text: String(e.message) }));
  const v0 = em.json?.data?.[0]?.embedding;
  rec("(4) data plane embeddings: 2 vectors of length 768 (nomic-embed-text native)", em.status === 200 && em.json.data.length === 2 && Array.isArray(v0) && v0.length === 768 && v0.every((x) => typeof x === "number") ? "PASS" : "FAIL", em.status === 0 ? "TIMEOUT/ERR " + em.text : `${em.status} ${Math.round((Date.now() - t0) / 1000)}s len=${v0?.length} ${em.status !== 200 ? em.text.slice(0, 150) : ""}`);
  const wk = await call("POST", dp(cD, "chat/completions"), { messages: [{ role: "user", content: "hi" }] }, { "api-key": "definitely-wrong-key" }, 30000);
  rec("(4) wrong api-key is refused 401 with a proper message", wk.status === 401 && /invalid subscription key|Access denied/i.test(wk.json?.error?.message || "") && !bad(wk.text) ? "PASS" : "FAIL", `${wk.status} ${wk.text.slice(0, 140)}`);
  const nk = await call("POST", dp(cD, "chat/completions"), { messages: [{ role: "user", content: "hi" }] }, {}, 30000);
  rec("(4) missing api-key is refused 401", nk.status === 401 && /subscription key|Access denied/i.test(nk.json?.error?.message || "") ? "PASS" : "FAIL", `${nk.status} ${nk.text.slice(0, 140)}`);
  const key2 = (await call("POST", acctPath(RG, uiAcct) + "/listKeys" + q)).json?.key2 || "";
  const k2 = await call("POST", dp(cD, "chat/completions"), { messages: [{ role: "user", content: "Reply: ok" }], max_tokens: 8 }, { "api-key": key2 }, MODEL_TMO).catch((e) => ({ status: 0, text: String(e.message) }));
  rec("(4) key2 also authenticates the data plane", k2.status === 200 ? "PASS" : "FAIL", k2.status === 0 ? "TIMEOUT/ERR " + k2.text : k2.status);
  const nd = await call("POST", dp("no-such-deployment", "chat/completions"), { messages: [{ role: "user", content: "hi" }] }, { "api-key": key1 }, 30000);
  rec("(4) unknown deployment -> 404 DeploymentNotFound with message", nd.status === 404 && /DeploymentNotFound/.test(nd.text) && !bad(nd.text) ? "PASS" : "FAIL", `${nd.status} ${nd.text.slice(0, 140)}`);

  // UI playground
  await go(`cognitiveservices/${RG}/${uiAcct}/playground`);
  try {
    await page.getByLabel("Deployment", { exact: true }).selectOption(cD);
    await page.getByLabel("User query").fill("Reply with the single word: pong");
    await dispatch(page.getByRole("button", { name: /^Send$/ }));
    t0 = Date.now();
    const chat = page.getByTestId("aoai-chat");
    await page.waitForFunction(() => /Assistant:\s*\S/.test(document.querySelector('[data-testid="aoai-chat"]')?.innerText || ""), null, { timeout: MODEL_TMO }).catch(() => {});
    const ct = (await chat.innerText()).replace(/\s+/g, " ");
    const m = ct.match(/Assistant:\s*(.*)/);
    const errTxt = await page.locator('[role="alert"], .fui-MessageBar').allInnerTexts().catch(() => []);
    rec("(4) UI chat playground: prompt -> non-empty assistant reply", m && m[1].trim() ? "PASS" : "FAIL", m ? `${Math.round((Date.now() - t0) / 1000)}s ${m[1].slice(0, 100)}` : `no reply in ${MODEL_TMO / 1000}s (timeout); ${errTxt.join(" | ").slice(0, 200)}`);
  } catch (e) { rec("(4) UI chat playground", "FAIL", String(e.message).split("\n")[0]); }
  rec("(4) UI embeddings playground", "NOT-AUTOMATED", "the console only offers a Chat playground (no embeddings/completions/Foundry UI); embeddings verified over the data plane above");

  // ---- (5) validation
  await go("cognitiveservices/create");
  const vtry = async (nm, sub) => {
    await go("cognitiveservices/create");
    await page.getByLabel("Name", { exact: true }).fill(nm);
    if (sub) { await page.getByRole("tab", { name: "Network" }).dispatchEvent("click"); await page.getByLabel("Custom subdomain name").fill(sub); }
    await dispatch(page.getByRole("button", { name: /Review \+ create/ }).first());
    await sleep(800); return text();
  };
  let vt = await vtry("bad name!"); 
  rec("(5) UI wizard: invalid account name 'bad name!' -> 'Validation failed' with a meaningful message, Create disabled", /Validation failed/.test(vt) && /Name must be 2-64 characters/.test(vt) && !bad(vt) && await page.getByRole("button", { name: /^Create$/ }).first().isDisabled() ? "PASS" : "FAIL", vt.slice(vt.indexOf("Validation"), vt.indexOf("Validation") + 160));
  vt = await vtry("x");
  rec("(5) UI wizard: 1-char account name refused", /Validation failed/.test(vt) && /2-64/.test(vt) ? "PASS" : "FAIL", "");
  vt = await vtry(`bdv-${R}`, "-bad-");
  rec("(5) UI wizard: invalid custom subdomain refused with message", /Validation failed/.test(vt) && /Custom subdomain name must be/.test(vt) && !bad(vt) ? "PASS" : "FAIL", "");
  vt = await vtry(uiAcct, null);
  rec("(5) UI wizard: duplicate account name refused", /already exists/.test(vt) ? "PASS" : "FAIL", vt.slice(vt.indexOf("Validation"), vt.indexOf("Validation") + 140));
  let b = await call("PUT", acctPath(RG, "bad name!") + q, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: {} });
  rec("(5) ARM: invalid account name -> 400 InvalidResourceName + message", b.status === 400 && /InvalidResourceName/.test(b.text) && !bad(b.text) ? "PASS" : "FAIL", `${b.status} ${b.text.slice(0, 160)}`);
  b = await call("PUT", acctPath(RG, `bdbadsku${R}`) + q, { location: "eastus", kind: "OpenAI", sku: { name: "F9" }, properties: { customSubDomainName: `bdbadsku${R}` } });
  rec("(5) ARM: invalid sku for kind -> 4xx with message", b.status >= 400 && b.status < 500 && b.json?.error?.message && !bad(b.text) ? "PASS" : "FAIL", `${b.status} ${b.text.slice(0, 160)}`);
  b = await call("PUT", dep(RG, uiAcct, "bad name!") + q, { sku: { name: "Standard", capacity: 1 }, properties: { model: { format: "OpenAI", name: "qwen2.5-3b", version: "1" } } });
  rec("(5) ARM: invalid deployment name -> 400 InvalidResourceName", b.status === 400 && /InvalidResourceName/.test(b.text) ? "PASS" : "FAIL", `${b.status} ${b.text.slice(0, 140)}`);
  b = await call("PUT", dep(RG, uiAcct, `bdover${R}`) + q, { sku: { name: "Standard", capacity: 5000 }, properties: { model: { format: "OpenAI", name: "qwen2.5-3b", version: "1" } } });
  rec("(5) ARM: quota overflow (capacity 5000) -> 400 InsufficientQuota with numbers", b.status === 400 && /InsufficientQuota/.test(b.text) && /quota limit is 1000/.test(b.text) ? "PASS" : "FAIL", `${b.status} ${b.text.slice(0, 200)}`);
  b = await call("PUT", dep(RG, uiAcct, `bdnomodel${R}`) + q, { sku: { name: "Standard", capacity: 1 }, properties: { model: { format: "OpenAI", name: "no-such-model", version: "1" } } });
  rec("(5) ARM: unknown model -> 400 DeploymentModelNotSupported", b.status === 400 && /DeploymentModelNotSupported/.test(b.text) ? "PASS" : "FAIL", `${b.status} ${b.text.slice(0, 140)}`);
  // UI dialog: quota overflow + invalid name
  const dlgTry = async (name, cap) => {
    await go(`cognitiveservices/${RG}/${uiAcct}/deployments`);
    await page.getByRole("button", { name: /Create new deployment/ }).or(page.getByText("Create new deployment")).first().dispatchEvent("click");
    const d = page.getByRole("dialog", { name: /Deploy model/ }); await d.waitFor({ timeout: 15000 });
    await d.getByLabel("Deployment name").fill(name); await d.getByLabel(/Tokens per minute/).fill(String(cap));
    await dispatch(d.getByRole("button", { name: /^Deploy$/ })); await sleep(3000);
    return text();
  };
  let ut = await dlgTry(`bdover${R}`, 5000);
  rec("(5) UI deploy dialog: quota overflow shows a meaningful error (no [object Object]/undefined)", /(InsufficientQuota|quota)/i.test(ut) && /limit is 1000/.test(ut) && !bad(ut.replace(/undefined\s*$/, "")) ? "PASS" : "FAIL", (ut.match(/.{0,60}quota.{0,120}/i) || ["no error text"])[0]);
  const none = await call("GET", dep(RG, uiAcct, `bdover${R}`) + q);
  rec("(5) quota-overflow deployment was NOT created", none.status === 404 ? "PASS" : "FAIL", none.status);
  ut = await dlgTry("bad name!", 1);
  rec("(5) UI deploy dialog: invalid deployment name shows a meaningful error", /invalid/i.test(ut) && /deployment name/i.test(ut) && !bad(ut) ? "PASS" : "FAIL", (ut.match(/.{0,60}deployment name.{0,100}/i) || ["no error text"])[0]);

  // ---- (3) deletes both ways
  await go(`cognitiveservices/${RG}/${uiAcct}/deployments`);
  try {
    await page.locator("tr", { hasText: eD }).first().getByRole("checkbox").check();
    await dispatch(page.getByRole("button", { name: /^Delete$/ }).first()); await sleep(1500);
    const cf = page.getByRole("dialog"); await cf.getByLabel("Confirm deletion").fill(eD);
    await dispatch(cf.getByRole("button", { name: /^Delete$/ }));
    await sleep(3000);
  } catch (e) { rec("(3) UI delete deployment", "FAIL", String(e.message).split("\n")[0]); }
  let gd = await call("GET", dep(RG, uiAcct, eD) + q);
  rec("(3) UI delete -> ARM: deployment deleted in the console is gone from ARM", gd.status === 404 ? "PASS" : "FAIL", `GET ${gd.status}`);
  const dd = await call("DELETE", dep(RG, uiAcct, aE) + q); await go(`cognitiveservices/${RG}/${uiAcct}/deployments`);
  const t3 = await text();
  rec("(3) ARM delete -> UI: deployment deleted over ARM disappears from the grid", dd.status < 300 && !t3.includes(aE) ? "PASS" : "FAIL", `DELETE ${dd.status}`);

  // ---- account delete both ways
  const da = await call("DELETE", acctPath(RG, apiAcct) + q);
  const ta = await listHas(uiAcct);
  rec("(2) ARM delete -> UI: account deleted over ARM disappears from the list", da.status < 300 && ta && !ta.includes(apiAcct) ? "PASS" : "FAIL", `DELETE ${da.status}`);
  await go(`cognitiveservices/${RG}/${uiAcct}`);
  try {
    await dispatch(page.getByRole("button", { name: /^Delete$/ }).first()); await sleep(1500);
    const cf = page.getByRole("dialog"); await cf.getByLabel("Confirm deletion").fill(uiAcct);
    await dispatch(cf.getByRole("button", { name: /^Delete$/ })); await sleep(3500);
  } catch (e) { rec("(2) UI delete account", "FAIL", String(e.message).split("\n")[0]); }
  const gu = await call("GET", acctPath(RG, uiAcct) + q);
  rec("(2) UI delete -> ARM: account deleted in the console is gone from ARM", gu.status === 404 ? "PASS" : "FAIL", `GET ${gu.status}`);
} catch (e) {
  rec("(run) harness ran to completion", "FAIL", String(e.message).split("\n")[0]);
}
// cleanup (only what this run created)
for (const n of [uiAcct, apiAcct, cliAcct]) { await call("DELETE", acctPath(RG, n) + q).catch(() => {}); }
const dg = await call("DELETE", `/subscriptions/${SUB}/resourcegroups/${RG}?api-version=2021-04-01`).catch(() => ({ status: 0 }));
// soft-deleted accounts: purge ours so nothing lingers
for (const n of [uiAcct, apiAcct, cliAcct]) await call("DELETE", `/subscriptions/${SUB}/providers/${NS}/locations/eastus/resourceGroups/${RG}/deletedAccounts/${n}${q}`).catch(() => {});
rec("(cleanup) test resource group + accounts deleted", dg.status < 300 ? "PASS" : "FAIL", dg.status);
rec("(run) no uncaught page errors", pageErrors.length ? "FAIL" : "PASS", pageErrors.slice(0, 3).join(" | "));

const outDir = new URL("../../../tests/conformance/hourly/out/", import.meta.url).pathname;
mkdirSync(outDir, { recursive: true });
let md = `# Azure AI (Cognitive Services / Azure OpenAI) UI <-> ARM bi-directional on the Mesh appliance\n\n| Check | Result | Detail |\n|---|---|---|\n`;
for (const r of rows) md += `| ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 160)} |\n`;
const n = (s) => rows.filter((r) => r.status === s).length;
md += `\n**${n("PASS")} pass, ${n("FAIL")} fail, ${n("NOT-AUTOMATED")} not automated.**\n`;
writeFileSync(outDir + "azure-ai-mesh-bidirectional.md", md);
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
