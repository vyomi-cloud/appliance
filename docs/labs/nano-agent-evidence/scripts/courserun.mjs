// Block-level runner for the course "Build Your First Agent (Nano)": runs every runnable block of every chapter, in order, the way the Deploy button does
// (each chapter gets the files of chapters 1..N, a later save of the same name wins), in headless Chrome with WebGPU and one in-browser model. No Mesh.
// env: PORT (Nano preview), MODEL (catalogue id, e.g. qwen2.5-1.5b), PROF (Chrome profile dir; keeps the downloaded model), OUT (jsonl), CH (e.g. "1,2"), CLEAR=1 (empty Nano store first),
//      HF_VIA_NODE=1 (fetch model shards from Node: some HF shards fail inside headless Chrome), SAMEPROC=1 (do not exit-kill)
import { chromium } from "/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/playwright/index.mjs";
import fs from "node:fs";
const PORT = process.env.PORT || 8201, MODEL = process.env.MODEL || "", PROF = process.env.PROF, OUT = process.env.OUT || "course-run.jsonl";
const only = (process.env.CH || "").split(",").filter(Boolean).map(Number);
const ctx = await chromium.launchPersistentContext(PROF, { executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: false, viewport: { width: 1400, height: 900 }, args: ["--headless=new", "--enable-unsafe-webgpu", "--use-angle=metal"], ignoreDefaultArgs: ["--headless"] });
if (process.env.HF_VIA_NODE) await ctx.route(/huggingface\.co\/mlc-ai\/.*\/resolve\//, async (route) => { try { const r = await route.fetch({ maxRedirects: 10, timeout: 600000 }); await route.fulfill({ response: r, headers: { ...r.headers(), "access-control-allow-origin": "*" } }); } catch (e) { await route.abort(); } });
const A = await ctx.newPage();
if (process.env.CLEAR) {
  await A.goto(`http://127.0.0.1:${PORT}/nano/labs/`);
  await A.evaluate(async () => { for (const d of await indexedDB.databases()) await new Promise((res) => { const q = indexedDB.deleteDatabase(d.name); q.onsuccess = q.onerror = q.onblocked = () => res(); }); try { const r = await navigator.storage.getDirectory(); for await (const [n] of r.entries()) await r.removeEntry(n, { recursive: true }); } catch (e) {} try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} for (const x of await navigator.serviceWorker.getRegistrations()) await x.unregister(); });
}
await A.goto(`http://127.0.0.1:${PORT}/nano/v4/aws/`);
await A.waitForFunction(() => typeof globalThis.vyomiLlmStatus === "function", null, { timeout: 180000 }); await A.waitForTimeout(3000);
if (MODEL) { const r = await A.evaluate(async (m) => { const t0 = performance.now(); try { const id = await globalThis.vyomiEnableWebLLM(m, () => {}); return { ok: true, id, ms: Math.round(performance.now() - t0) }; } catch (e) { return { ok: false, err: String(e).slice(0, 300) }; } }, MODEL); console.log("model:", JSON.stringify(r)); if (!r.ok) { process.exit(2); } }
const P = await ctx.newPage(); await P.goto(`http://127.0.0.1:${PORT}/nano/labs/`); await P.waitForTimeout(3000);
await P.evaluate(() => { window.__seq = 0; window.__pend = {}; window.__w = new Worker("pyrun-worker.js", { type: "module" });
  window.__w.onmessage = (e) => { const q = window.__pend[e.data.id]; if (!q) return; if (e.data.type === "log") q.text += e.data.text + "\n"; else { q.ok = e.data.ok; delete window.__pend[e.data.id]; q.res(q); } };
  window.__run = (files, run, env, ms) => new Promise((res) => { const id = ++window.__seq; const q = { text: "", res: (x) => { clearTimeout(t); res({ ok: x.ok, text: x.text }); } }; window.__pend[id] = q; const t = setTimeout(() => { const tx = window.__pend[id] ? window.__pend[id].text : ""; delete window.__pend[id]; res({ ok: false, text: tx + "\n[TIMEOUT]" }); }, ms); window.__w.postMessage({ id, files, run, env, route: null }); }); });
const course = await P.evaluate(() => fetch("data/aws-agent-nano.json").then((r) => r.json()));
const env = { AWS_ENDPOINT_URL: `http://127.0.0.1:${PORT}/nano/_wire`, AWS_DEFAULT_REGION: "us-east-1", AWS_ACCESS_KEY_ID: "test", AWS_SECRET_ACCESS_KEY: "test" };
fs.writeFileSync(OUT, "");
const acc = {}; let pass = 0, fail = 0;
for (const l of course.layers) {
  for (const b of l.lab || []) acc[b.file] = b.code;       // the files the Deploy button writes: chapters 1..N, a later save of a name wins
  if (only.length && !only.includes(l.order)) continue;
  for (const [i, b] of (l.lab || []).entries()) {
    const rec = { chapter: l.order, i: i + 1, file: b.file, run: b.run || "", expect: b.expect || "" };
    const t0 = Date.now();
    if (!b.run) { await P.evaluate(([f, e]) => window.__run(f, "", e, 60000), [acc, env]); rec.status = "SAVED"; }
    else {
      const r = await P.evaluate(([f, run, e]) => window.__run(f, run, e, 1500000), [acc, b.run, env]);
      rec.text = r.text.slice(-2500); rec.ok = r.ok; rec.matched = !b.expect || r.text.includes(b.expect); rec.status = r.ok && rec.matched ? "PASS" : "FAIL";
      rec.status === "PASS" ? pass++ : fail++;
    }
    rec.ms = Date.now() - t0; fs.appendFileSync(OUT, JSON.stringify(rec) + "\n");
    console.log(rec.chapter, rec.file, rec.status, rec.ms + "ms", (rec.text || "").trim().split("\n").slice(-1)[0].slice(0, 120));
  }
}
console.log("SUMMARY", JSON.stringify({ model: MODEL || "none", pass, fail }));
fs.appendFileSync(OUT, JSON.stringify({ summary: true, model: MODEL || "none", pass, fail }) + "\n");
setTimeout(() => process.exit(0), 4000); await ctx.close().catch(() => {}); process.exit(0);
