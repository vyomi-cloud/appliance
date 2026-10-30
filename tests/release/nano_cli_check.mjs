/* Release check, Nano: the real aws / gcloud / az CLIs against Nano through the
 * relay tunnel, plus CLI ↔ console both ways — the same tests/release/cli_crosscheck.py
 * the offline appliance runs.
 *
 *   CLIs ──HTTP──▶ local relay (wasm/relay/local-relay.mjs, :8090)
 *                    │ WebSocket
 *                    ▼
 *                  Nano tab (wasm/, Pyodide + the cores) ◀── console API calls
 *                                                           (bridge :8091 → fetch
 *                                                            inside the SW-controlled page)
 *
 * The tab is a real Nano spaces page; the tunnel is started with its own
 * "Start tunnel" button, as a user does. The bridge runs each console request
 * as a fetch inside that page, so it is served by the Nano service worker —
 * exactly the calls the console makes.
 *
 *   NODE_PATH=<dir with playwright + ws> OUT=nano-cli-check node tests/release/nano_cli_check.mjs
 */
import { spawn } from "node:child_process";
import http from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
process.env.NANO_DIR = process.env.NANO_DIR || resolve(ROOT, "wasm");
const { startServer, chromium, sleep } = await import(resolve(ROOT, "wasm/ui-tests/lib.mjs"));

const RELAY_PORT = +(process.env.RELAY_PORT || 8090);   // the bundle auto-detects a local relay on :8090
const BRIDGE_PORT = +(process.env.BRIDGE_PORT || 8091);
const RELAY = `http://127.0.0.1:${RELAY_PORT}`;
const OUT = process.env.OUT || "nano-cli-check";
const children = [];
const stop = (code) => { for (const c of children) try { c.kill(); } catch {} process.exit(code); };

async function health() {
  try { return await (await fetch(RELAY + "/health")).json(); } catch { return {}; }
}

// 1. the local relay (what `vyomi-tunnel` runs)
const relay = spawn(process.execPath, [resolve(ROOT, "wasm/relay/local-relay.mjs")],
  { env: { ...process.env, RELAY_PORT: String(RELAY_PORT) }, stdio: ["ignore", "inherit", "inherit"] });
children.push(relay);
for (let i = 0; i < 50 && !(await health()).ok; i++) await sleep(200);
if (!(await health()).ok) { console.log("FAIL: local relay did not start"); stop(1); }

// 2. the Nano bundle + a real spaces page, tunnel started from its own button
const { server, base } = await startServer(process.env.NANO_DIR);
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("pageerror", (e) => console.log("[nano pageerror]", e.message));
await page.goto(base + "/clouds.html", { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => navigator.serviceWorker && navigator.serviceWorker.controller
  && document.querySelector("#nano-foot-toggle"), null, { timeout: 180000, polling: 500 });
for (let i = 0; i < 120 && !(await health()).tab; i++) {
  if (i % 20 === 0) {
    await page.evaluate(() => {
      const b = document.querySelector("#nano-foot-toggle");
      if (b && /start|reconnect/i.test(b.textContent || "")) b.click();
    }).catch(() => {});
  }
  await sleep(1500);
}
if (!(await health()).tab) { console.log("FAIL: the Nano tab never registered with the relay"); await browser.close(); server.close(); stop(1); }
console.log("Nano tab registered with the relay:", JSON.stringify(await health()));

// 3. the console bridge: each request becomes a fetch inside the Nano page
const bridge = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", async () => {
    try {
      const body = chunks.length ? Buffer.concat(chunks).toString("utf8") : null;
      const r = await page.evaluate(async ({ method, url, body, ct }) => {
        const resp = await fetch(url, { method, body: body ?? undefined, headers: ct ? { "content-type": ct } : {} });
        return { status: resp.status, ct: resp.headers.get("content-type") || "", text: await resp.text() };
      }, { method: req.method, url: req.url, body, ct: req.headers["content-type"] || "" });
      res.writeHead(r.status, { "content-type": r.ct || "application/json" });
      res.end(r.text);
    } catch (e) {
      res.writeHead(502, { "content-type": "text/plain" });
      res.end("bridge: " + String(e).slice(0, 300));
    }
  });
});
await new Promise((r) => bridge.listen(BRIDGE_PORT, "127.0.0.1", r));

// 4. the same release check the offline appliance runs
const check = spawn("python3", [resolve(ROOT, "tests/release/cli_crosscheck.py")], {
  cwd: ROOT, stdio: "inherit",
  env: { ...process.env, ENDPOINT: RELAY, CONSOLE: `http://127.0.0.1:${BRIDGE_PORT}`, TARGET: "nano", OUT },
});
const code = await new Promise((r) => check.on("exit", r));
bridge.close(); server.close(); await browser.close();
stop(code ?? 1);
