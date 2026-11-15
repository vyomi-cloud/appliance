/* Nano chat-model import e2e (lane nanoimport): boots the REAL Nano console headless and drives Bedrock Custom Model Import through the page's /_wire front door:
 * S3 upload (adapter.gguf + adapter_meta.json trained on the Mesh/PEFT spike) -> CreateModelImportJob -> Get/List/GetImportedModel -> Converse on the imported ARN
 * (wllama serves SmolLM2-135M base GGUF + the LoRA adapter in the tab) over the 30 held-out tickets (tuned vs the same base without the adapter) -> InvokeModel (prompt body)
 * -> validation failures (bad GGUF, wrong base) -> reload the tab (adapter + OPFS-cached base survive) and invoke again -> DeleteImportedModel.
 *   NANO_DIR=<this wasm dir> NODE_PATH=<portal-OLD>/node_modules node wasm/ui-tests/import-e2e.mjs
 * Needs internet (wllama from jsDelivr, the SmolLM2 base GGUF from Hugging Face, MiniLM like the rest of Nano). (A Playwright route that fulfils the 145 MB base from disk kills the tab, so the base is always fetched for real.) */
import { readFileSync } from "node:fs";
import { startServer, bootConsole, chromium } from "./lib.mjs";
const FIX = new URL("../../tests/conformance/fixtures/nanoimport/", import.meta.url).pathname;
const adapter = readFileSync(FIX + "adapter.gguf"), meta = readFileSync(FIX + "adapter_meta.json"), heldout = JSON.parse(readFileSync(FIX + "heldout.json", "utf8"));
const { server, base } = await startServer(process.env.NANO_DIR || new URL("..", import.meta.url).pathname);
const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
let PASS = 0, FAIL = 0;
const check = (n, ok, d = "") => { ok ? PASS++ : FAIL++; console.log(`[${ok ? "PASS" : "FAIL"}] ${n}${!ok && d ? " - " + (typeof d === "string" ? d : JSON.stringify(d)).slice(0, 400) : ""}`); };
page.on("pageerror", (e) => console.log("  pageerror:", String(e.message).slice(0, 160)));
page.on("crash", () => console.log("  PAGE CRASHED"));
if (process.env.E2E_DEBUG) page.on("console", (m) => console.log("  [console]", m.text().slice(0, 200)));
const b64 = (b) => Buffer.from(b).toString("base64");
try {
  await bootConsole(page, base, "/aws-console.html");
  const api = `async (a) => {
    const [svc, method, path, body, bin] = a;
    const h = { authorization: "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20260101/us-east-1/" + svc + "/aws4_request, SignedHeaders=host, Signature=0", "content-type": bin ? "application/octet-stream" : "application/json" };
    const payload = body == null ? undefined : bin ? Uint8Array.from(atob(body), (c) => c.charCodeAt(0)) : (typeof body === "string" ? body : JSON.stringify(body));
    const r = await fetch(BASE + "/_wire" + path, { method, headers: h, body: payload });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (_) {}
    return { status: r.status, json: j, text: t.slice(0, 500) };
  }`;
  const call = (svc, method, path, body, bin) => page.evaluate(`(async () => { const BASE = ${JSON.stringify(base)}; return await (${api})(${JSON.stringify([svc, method, path, body ?? null, !!bin])}); })()`);
  const put = (key, buf) => call("s3", "PUT", "/model-import/" + key, b64(buf), true);
  let cb; for (let i = 0; i < 90; i++) { cb = await call("s3", "PUT", "/model-import", ""); if (!/no client/.test(cb.text)) break; if (i % 10 == 9) console.log("  s3 create retry:", cb.status, cb.text.slice(0, 300)); await new Promise((r) => setTimeout(r, 2000)); }
  check("s3 create bucket", [200, 201].includes(cb.status), cb);
  check("s3 put adapter.gguf", [200, 201].includes((await put("tuned/adapter.gguf", adapter)).status));
  check("s3 put adapter_meta.json", [200, 201].includes((await put("tuned/adapter_meta.json", meta)).status));
  // ---- validation: bad artifacts fail the job with a reason (the async API's shape), nothing is registered
  await put("bad/adapter.gguf", Buffer.from("this is not a gguf file at all, just text".repeat(8))); await put("bad/adapter_meta.json", meta);
  await put("wrongbase/adapter.gguf", adapter); await put("wrongbase/adapter_meta.json", Buffer.from(JSON.stringify({ base_model: "gpt-4", rank: 8, alpha: 16 })));
  const job = async (name, prefix) => {
    const c = await call("bedrock", "POST", "/model-import-jobs", { jobName: name, importedModelName: name + "-m", roleArn: "arn:aws:iam::123456789012:role/r", modelDataSource: { s3DataSource: { s3Uri: `s3://model-import/${prefix}/` } } });
    const g = c.json && c.json.jobArn ? (await call("bedrock", "GET", "/model-import-jobs/" + c.json.jobArn.split("/").pop())).json : null;
    return { c, g };
  };
  const bad = await job("bad-gguf", "bad"), wb = await job("wrong-base", "wrongbase");
  check("bad GGUF -> job Failed with the GGUF reason", bad.g && bad.g.status === "Failed" && /GGUF magic/.test(bad.g.failureMessage), bad.g);
  check("unsupported base -> job Failed naming the supported bases", wb.g && wb.g.status === "Failed" && /smollm2-135m-instruct/.test(wb.g.failureMessage), wb.g);
  check("malformed request -> 400 ValidationException", (await call("bedrock", "POST", "/model-import-jobs", { jobName: "x" })).status === 400);
  // ---- the real import
  const ok = await job("facilities-tuned", "tuned");
  check("CreateModelImportJob accepted + Completed", ok.c.status === 201 && ok.g && ok.g.status === "Completed" && ok.g.importedModelArn, ok);
  const arn = ok.g.importedModelArn;
  const gm = (await call("bedrock", "GET", "/imported-models/" + encodeURIComponent(arn))).json;
  check("GetImportedModel: vyomiImported, base + rank recorded", gm && gm.vyomiImported && gm.vyomiTrained && gm.vyomiImport.base === "smollm2-135m-instruct" && gm.vyomiImport.rank === 8, gm);
  const lm = (await call("bedrock", "GET", "/imported-models")).json;
  check("ListImportedModels contains it (and only it)", lm && lm.modelSummaries.length === 1 && lm.modelSummaries[0].modelArn === arn, lm);
  // ---- serving through the console wire: Converse on the imported ARN
  const conv = async (prompt) => (await call("bedrock", "POST", "/model/" + encodeURIComponent(arn) + "/converse", { messages: [{ role: "user", content: [{ text: prompt }] }], inferenceConfig: { maxTokens: 24, temperature: 0 } }));
  const t0 = Date.now();
  const first = await conv(heldout[0].prompt);
  const firstMs = Date.now() - t0;
  const st1 = await page.evaluate(() => globalThis.vyomiWllamaStatus());
  check("first Converse answers (base downloaded + cached, adapter loaded)", first.status === 200 && first.json && first.json.output, first);
  console.log(`  first call ${(firstMs / 1000).toFixed(1)} s incl. base download+load | status`, JSON.stringify({ phase: st1.phase, multiThread: st1.multiThread, threads: st1.threads, crossOriginIsolated: st1.crossOriginIsolated, loadMs: st1.loadMs, total: st1.total }));
  let tuned = 0, toks = 0, ms = 0; const miss = [];
  for (const r of heldout) {
    const t = Date.now(); const o = await conv(r.prompt); ms += Date.now() - t;
    const txt = (((o.json || {}).output || {}).message || {}).content?.[0]?.text?.trim();
    toks += ((o.json || {}).usage || {}).outputTokens || 0;
    if (txt === r.completion) tuned++; else if (miss.length < 3) miss.push([r.completion, txt]);
  }
  console.log(`  tuned held-out exact match ${tuned}/${heldout.length} | ${(toks / (ms / 1000)).toFixed(1)} tok/s end to end | misses`, JSON.stringify(miss));
  check("tuned model matches the held-out set (>= 27/30)", tuned >= 27, { tuned });
  // base only (same GGUF, no adapter) through the bridge
  const baseHits = await page.evaluate(async (rows) => {
    const eng = globalThis.vyomiWllama; const s0 = eng.status();
    const q = (r) => JSON.stringify({ model: "base-only", spec: { base: "smollm2-135m-instruct", file: s0.loaded.split("|")[0], url: "", size: 0, noAdapter: true }, messages: [{ role: "user", content: r.prompt }], max_tokens: 24, temperature: 0 });
    let n = 0; for (const r of rows) { const o = JSON.parse(await eng.chat(q(r))); if (o.text.trim() === r.completion) n++; } return n;
  }, heldout);
  console.log(`  same base GGUF without the adapter: ${baseHits}/${heldout.length}`);
  check("untuned base does NOT do the task (<= 3/30)", baseHits <= 3, { baseHits });
  // InvokeModel with a Llama-style prompt body, labelled
  const inv = await call("bedrock", "POST", "/model/" + encodeURIComponent(arn) + "/invoke", { prompt: heldout[1].prompt, max_gen_len: 24, temperature: 0 });
  check("InvokeModel prompt body -> generation, vyomiImported", inv.status === 200 && inv.json && inv.json.generation === heldout[1].completion && inv.json.vyomiImported === true, inv);
  // ---- persistence: reload the tab; adapter lives in the object store + OPFS, base in OPFS (no second download)
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller && document.querySelectorAll("#rail a, #rail button, #rail li").length > 0, null, { timeout: 180000, polling: 500 });
  const t1 = Date.now();
  const again = await conv(heldout[2].prompt);
  const st2 = await page.evaluate(() => globalThis.vyomiWllamaStatus());
  const txt2 = (((again.json || {}).output || {}).message || {}).content?.[0]?.text?.trim();
  console.log(`  after reload: ${((Date.now() - t1) / 1000).toFixed(1)} s (no base download: ${st2.bytes === 0 || st2.phase === "ready"}), phase ${st2.phase}`);
  check("reload keeps the imported model and serves it (adapter + cached base)", txt2 === heldout[2].completion, { txt2, want: heldout[2].completion, st2 });
  const lm2 = (await call("bedrock", "GET", "/imported-models")).json;
  check("ListImportedModels after reload", lm2 && lm2.modelSummaries.length === 1, lm2);
  const del = await call("bedrock", "DELETE", "/imported-models/" + encodeURIComponent(arn));
  check("DeleteImportedModel", del.status === 200 && (await call("bedrock", "GET", "/imported-models/" + encodeURIComponent(arn))).status === 404);
  check("invoking a deleted model -> ValidationException (not served by the default model)", (await conv(heldout[0].prompt)).status === 400);
} catch (e) { FAIL++; console.log("[FAIL] harness:", String(e.stack || e).slice(0, 800)); }
console.log(`${PASS} passed, ${FAIL} failed`);
await browser.close(); server.close();
process.exit(FAIL ? 1 : 0);
