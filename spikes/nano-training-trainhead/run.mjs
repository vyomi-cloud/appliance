// Driver: node run.mjs [cand ...]. Needs playwright (path below) + network. Output: results.json
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os'; import { execSync } from 'node:child_process'; import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || '/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright');
const root = path.dirname(new URL(import.meta.url).pathname);
const srv = http.createServer((q, r) => { const f = path.join(root, q.url.split('?')[0] === '/' ? 'harness.html' : q.url.split('?')[0]); if (!f.startsWith(root) || !fs.existsSync(f)) { r.writeHead(404); return r.end(); }
  r.writeHead(200, { 'content-type': f.endsWith('.js') ? 'text/javascript' : f.endsWith('.html') ? 'text/html' : 'application/json' }); fs.createReadStream(f).pipe(r); });
await new Promise((r) => srv.listen(0, r)); const url = `http://127.0.0.1:${srv.address().port}/`;
const prof = fs.mkdtempSync(path.join(process.env.PROFROOT || os.tmpdir(), 'trainhead-prof-'));
const cands = process.argv.slice(2).length ? process.argv.slice(2) : ['js', 'tfjs-wasm', 'tfjs-cpu', 'sklearn'];
const rssNow = () => { try { const rows = execSync('ps -axo pid=,ppid=,rss=,command=').toString().split('\n').map((l) => l.trim().match(/^(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/)).filter(Boolean).map((m) => ({ pid: +m[1], ppid: +m[2], rss: +m[3], cmd: m[4] }));
  const root = rows.find((r) => r.cmd.includes(prof) && !r.cmd.includes('--type=')); if (!root) return 0; const ids = new Set([root.pid]); let grew = true; while (grew) { grew = false; for (const r of rows) if (!ids.has(r.pid) && ids.has(r.ppid)) { ids.add(r.pid); grew = true; } }
  return rows.filter((r) => ids.has(r.pid)).reduce((s, r) => s + r.rss, 0); } catch { return 0; } };
async function session(fn) { // one fresh browser context (same profile => same OPFS/cache) with network + RSS accounting
  const ctx = await chromium.launchPersistentContext(prof, { headless: true, args: ['--enable-precise-memory-info'] }); const net = { bytes: 0, byHost: {} };
  ctx.on('requestfinished', async (rq) => { try { const s = await rq.sizes(); const h = new URL(rq.url()).host; if (h.startsWith('127.0.0.1')) return; net.bytes += s.responseBodySize; net.byHost[h] = (net.byHost[h] || 0) + s.responseBodySize; } catch {} });
  const page = await ctx.newPage(); page.on('console', (m) => process.stdout.write(`   [page] ${m.text()}\n`)); page.on('pageerror', (e) => console.log('   [pageerror]', String(e)));
  await page.goto(url); await page.waitForFunction('window.ready'); const base = rssNow(); let peak = base; const iv = setInterval(() => { peak = Math.max(peak, rssNow()); }, 150);
  const call = (m) => page.evaluate((x) => window.call(x), m);
  let out; try { out = await fn(call, page); } finally { clearInterval(iv); peak = Math.max(peak, rssNow()); await ctx.close(); }
  return { out, net_mb: +(net.bytes / 1e6).toFixed(2), net_by_host_mb: Object.fromEntries(Object.entries(net.byHost).map(([k, v]) => [k, +(v / 1e6).toFixed(2)])), rss_base_mb: Math.round(base / 1024), rss_peak_mb: Math.round(peak / 1024), rss_delta_mb: Math.round((peak - base) / 1024) };
}
const R = { env: { node: process.version, platform: `${os.platform()} ${os.arch()}`, chromium: chromium.name(), headless: true, webgpu: 'not used (CPU/WASM only)' } };
const must = (r) => { if (!r.ok) throw new Error(r.err); return r.r; };
console.log('== embed (shared frozen MiniLM embeddings, cached to OPFS)'); R.embed = await session(async (call) => must(await call({ cmd: 'embed' }))); console.log(JSON.stringify(R.embed));
R.baseline = await session(async (call) => must(await call({ cmd: 'baseline' }))).then((x) => x.out); console.log(JSON.stringify(R.baseline));
R.cands = {};
for (const c of cands) {
  console.log(`== ${c}: cold run (network sizes)`); const cold = await session(async (call) => must(await call({ cmd: 'train', cand: c })));
  console.log(`== ${c}: warm run (timings, memory)`); const warm = await session(async (call) => must(await call({ cmd: 'train', cand: c })));
  console.log(`== ${c}: reload in brand-new browser context (checkpoint from OPFS, no training)`); const rl = await session(async (call) => must(await call({ cmd: 'reload', cand: c })));
  R.cands[c] = { cold_download_mb: cold.net_mb, cold_download_by_host_mb: cold.net_by_host_mb, warm: warm.out, warm_rss_delta_mb: warm.rss_delta_mb, warm_rss_peak_mb: warm.rss_peak_mb, warm_rss_base_mb: warm.rss_base_mb, reload: rl.out, reload_download_mb: rl.net_mb };
  console.log(JSON.stringify(R.cands[c]));
}
fs.writeFileSync(path.join(root, 'results.json'), JSON.stringify(R, null, 1)); srv.close(); fs.rmSync(prof, { recursive: true, force: true }); console.log('done');
