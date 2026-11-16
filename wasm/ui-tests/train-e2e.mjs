/* Nano head-training e2e (lane trainengine): boots the REAL Nano console headless, then drives Bedrock customization through the page's /_wire
 * front door: S3 upload -> CreateModelCustomizationJob (engine nano-head-js: page MiniLM embeddings + Web Worker typed-array Adam) -> poll per-epoch metrics
 * -> Stop on a second job -> InvokeModel on the custom model -> reload the tab and invoke again (head restored from the persisted object store).
 *   NANO_DIR=<this wasm dir> NODE_PATH=<portal-OLD>/node_modules node wasm/ui-tests/train-e2e.mjs        (needs internet for the MiniLM weights, as Nano itself does) */
import { startServer, bootConsole, chromium } from "./lib.mjs";
const { server, base } = await startServer(process.env.NANO_DIR || new URL("..", import.meta.url).pathname);
const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
let PASS = 0, FAIL = 0;
const check = (n, ok, d = "") => { ok ? PASS++ : FAIL++; console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${!ok && d ? " - " + String(d).slice(0, 300) : ""}`); };
page.on("pageerror", (e) => console.log("  pageerror:", String(e.message).slice(0, 160)));
try {
  await bootConsole(page, base, "/aws-console.html");
  const run = (fnSrc, arg) => page.evaluate(`(${fnSrc})(${JSON.stringify(arg ?? null)})`);
  const api = `async (a) => {
    const [svc, method, path, body, raw] = a;
    const h = { authorization: "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20260101/us-east-1/" + svc + "/aws4_request, SignedHeaders=host, Signature=0", "content-type": raw ? "application/octet-stream" : "application/json" };
    const r = await fetch(BASE + "/_wire" + path, { method, headers: h, body: body == null ? undefined : (typeof body === "string" ? body : JSON.stringify(body)) });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (_) {}
    return { status: r.status, json: j, text: t.slice(0, 400) };
  }`;
  const call = (svc, method, path, body, raw) => page.evaluate(`(async () => { const BASE = ${JSON.stringify(base)}; return await (${api})(${JSON.stringify([svc, method, path, body ?? null, !!raw])}); })()`);
  // data
  const CORE = { billing: ["invoice", "refund", "charge", "payment", "card", "bill"], shipping: ["package", "delivery", "courier", "tracking", "parcel", "shipped"], login: ["password", "signin", "locked", "account", "reset", "token"] };
  const POOL = ["please", "today", "urgent", "hello", "thanks", "help", "need", "my", "the", "with"];
  let seed = 5; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296; const pick = (a, n) => [...a].sort(() => rnd() - 0.5).slice(0, n);
  const rows = []; for (const [l, ws] of Object.entries(CORE)) for (let i = 0; i < 40; i++) rows.push({ text: [...pick(ws, 2), ...pick(POOL, 3)].sort(() => rnd() - 0.5).join(" "), label: l });
  rows.sort(() => rnd() - 0.5);
  const jl = rows.map((r) => JSON.stringify(r)).join("\n");
  let cb; for (let i = 0; i < 90; i++) { cb = await call("s3", "PUT", "/train-data", ""); if (!/no client/.test(cb.text)) break; await new Promise((r) => setTimeout(r, 2000)); } console.log("  dbg", JSON.stringify(cb)); check("s3 create bucket", [200, 201].includes(cb.status), JSON.stringify(cb));
  check("s3 put training jsonl", [200, 201].includes((await call("s3", "PUT", "/train-data/intents.jsonl", jl, true)).status));
  const create = await call("bedrock", "POST", "/model-customization-jobs", { jobName: "nano-intent", customModelName: "nano-intent-m", roleArn: "arn:aws:iam::123456789012:role/r", baseModelIdentifier: "all-minilm-l6-v2",
    customizationType: "FINE_TUNING", trainingDataConfig: { s3Uri: "s3://train-data/intents.jsonl" }, outputDataConfig: { s3Uri: "s3://train-data/out/" }, hyperParameters: { epochCount: "8" } });
  check("create job accepted", create.status === 201 && create.json && create.json.jobArn, create);
  const jid = create.json.jobArn.split("/").pop();
  let g, stat = new Set(), losses = [], t0 = Date.now();
  while (Date.now() - t0 < 240000) { g = (await call("bedrock", "GET", "/model-customization-jobs/" + jid)).json; const v = g.vyomiTraining || {}; stat.add(v.status); (v.metrics || []).forEach((m) => losses[m.epoch] = m.loss); if (g.status !== "InProgress") break; await new Promise((r) => setTimeout(r, 400)); }
  const v = g.vyomiTraining || {};
  check("job Completed on engine nano-head-js", g.status === "Completed" && v.engine === "nano-head-js", g);
  check("per-epoch metrics, loss falls", (v.metrics || []).length === 8 && v.metrics[7].loss < v.metrics[0].loss, v.metrics);
  check("held-out beats baseline", v.heldOut && v.heldOut.accuracy > v.heldOut.baseline + 0.3, v.heldOut);
  console.log("  observed states:", [...stat].join(","), "| heldOut", JSON.stringify(v.heldOut), "| artifact", v.artifact);
  const arn = g.outputModelArn;
  const inv = async (text) => (await call("bedrock", "POST", "/model/" + encodeURIComponent(arn) + "/invoke", { task: "classify", text })).json;
  const i1 = await inv("where is my package courier tracking");
  check("InvokeModel classify -> shipping (MiniLM embedder), vyomiTrained", i1 && i1.label === "shipping" && i1.vyomiTrained && i1.embedder === "all-minilm-l6-v2", i1);
  // cancel
  const bigRows = []; for (let k = 0; k < 6; k++) bigRows.push(...rows);
  await call("s3", "PUT", "/train-data/long.jsonl", bigRows.map((r) => JSON.stringify(r)).join("\n"), true);
  const c2 = await call("bedrock", "POST", "/model-customization-jobs", { jobName: "nano-cancel", customModelName: "nano-cancel-m", roleArn: "arn:aws:iam::123456789012:role/r", baseModelIdentifier: "all-minilm-l6-v2",
    trainingDataConfig: { s3Uri: "s3://train-data/long.jsonl" }, outputDataConfig: { s3Uri: "s3://train-data/out/" }, hyperParameters: { epochCount: "50", taskType: "router" } });
  const j2 = c2.json.jobArn.split("/").pop(); await new Promise((r) => setTimeout(r, 1500));
  const st = await call("bedrock", "POST", "/model-customization-jobs/" + j2 + "/stop", {});
  await new Promise((r) => setTimeout(r, 2500));
  const g2 = (await call("bedrock", "GET", "/model-customization-jobs/" + j2)).json;
  check("Stop -> Stopped, worker halted before epoch 50", st.status === 200 && g2.status === "Stopped" && g2.vyomiTraining.epoch < 50, g2);
  // caps
  const big = await call("bedrock", "POST", "/model-customization-jobs", { jobName: "capx", customModelName: "capx-m", roleArn: "arn:aws:iam::123456789012:role/r", baseModelIdentifier: "all-minilm-l6-v2",
    trainingDataConfig: { s3Uri: "s3://train-data/missing.jsonl" }, outputDataConfig: { s3Uri: "s3://train-data/out/" } });
  check("missing data -> 400 ValidationException", big.status === 400, big);
  // reload persistence
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller && document.querySelectorAll("#rail a, #rail button, #rail li").length > 0, null, { timeout: 180000, polling: 500 });
  const i2 = await inv("reset my password locked signin");
  check("reload keeps the custom model + invocation", i2 && i2.label === "login" && i2.vyomiTrained, i2);
} catch (e) { FAIL++; console.log("[FAIL] harness:", String(e.stack || e).slice(0, 600)); }
console.log(`${PASS} passed, ${FAIL} failed`);
await browser.close(); server.close();
process.exit(FAIL ? 1 : 0);
