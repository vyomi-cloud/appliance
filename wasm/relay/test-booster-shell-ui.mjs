/* UI check for the booster shell: the REAL wasm/booster-link.js + wasm/vm/nano-vm-host.js + xterm in headless Chromium, talking to the
 * REAL relay + dial agent + core/booster_shell.py (fake docker CLI -> local sh on the PTY). Only the portal's /api/booster/status is stubbed.
 *   PY=<venv python> NODE_PATH=/tmp/np/node_modules RELAY_PORT=8812 node wasm/relay/test-booster-shell-ui.mjs
 * Proves: with a running booster session "Open shell" attaches the terminal to the Codespace VM (not the in-browser VM), typing works,
 * booster down shows a clear message (no silent fallback), no booster session leaves the in-browser path untouched. */
import { spawn } from "node:child_process";
import http from "node:http";
import fs from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, extname } from "node:path";
import { mint } from "./booster-session.mjs";
import { dial } from "./booster-dial.mjs";

const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const { chromium } = require("playwright");
const here = dirname(fileURLToPath(import.meta.url)), root = resolve(here, "../..");
const PY = process.env.PY || "python3";
const RELAY = Number(process.env.RELAY_PORT || 8812), SIM = RELAY + 1, WEB = RELAY + 2;
const KEY = "shell-ui-key-abcdef";
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 220) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const procs = [];
const spawnP = (cmd, args, env) => { const p = spawn(cmd, args, { env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] }); p.stdout.on("data", () => {}); p.stderr.on("data", () => {}); procs.push(p); return p; };
const cleanup = () => { for (const p of procs) try { p.kill(); } catch {} try { web.close(); } catch {} };
process.on("exit", cleanup);

const MIME = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".mjs": "text/javascript" };
const web = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/harness.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(`<!doctype html><html><head><meta charset=utf-8><script src="/booster-link.js"></script><script src="/vm/nano-vm-host.js"></script></head><body><div id="host"></div></body></html>`); }
  const f = join(root, "wasm", decodeURIComponent(u.pathname));
  if (!f.startsWith(join(root, "wasm")) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); fs.createReadStream(f).pipe(res);
}).listen(WEB, "127.0.0.1");

spawnP(process.execPath, [join(here, "local-relay.mjs")], { RELAY_PORT: String(RELAY), RELAY_HOST: "127.0.0.1", VYOMI_BOOSTER_SESSION_KEY: KEY, VYOMI_RELAY_ALLOW_LOOPBACK: "1" });
spawnP(PY, [join(here, "test-fixtures/fake_booster_sim.py"), String(SIM)], { APPLIANCE_ROOT: root, PYTHONPATH: root, VYOMI_ROLE: "booster", VYOMI_BOOSTER_SESSION_KEY: KEY,
  VYOMI_DOCKER_BIN: join(here, "test-fixtures/fake-docker.sh"), VYOMI_SHELL_NETWORK: "vyomi-net" });
for (let i = 0; i < 80; i++) { try { if ((await fetch(`http://127.0.0.1:${RELAY}/health`)).ok) break; } catch {} await sleep(100); }
for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${SIM}/x`); break; } catch {} await sleep(100); }

const token = mint(KEY, { sub: "acct-1", tier: "pro", primary_cloud: "aws", session_id: "ui-sess", session_end: Math.floor(Date.now() / 1000) + 600 });
let link = dial({ relayUrl: `ws://127.0.0.1:${RELAY}`, token, localUrl: `http://127.0.0.1:${SIM}`, WS, log: () => {} });
for (let i = 0; i < 50 && !link.state.linked; i++) await sleep(100);

const browser = await chromium.launch();
async function page(sessionStatus) {
  const ctx = await browser.newContext();
  const pg = await ctx.newPage();
  const errors = []; pg.on("pageerror", (e) => errors.push(String(e)));
  await pg.route("**/api/booster/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(sessionStatus) }));
  await pg.route("**/api/account/booster", (r) => r.fulfill({ status: 404, body: "{}" }));
  await pg.route("**/api/spaces/active", (r) => r.fulfill({ status: 404, body: "{}" }));
  await pg.route("**/connect-info", (r) => r.fulfill({ status: 404, contentType: "application/json", body: '{"ok":false}' }));
  await pg.goto(`http://127.0.0.1:${WEB}/harness.html`);
  return { pg, errors };
}
const running = { entitled: true, relay_url: `http://127.0.0.1:${RELAY}`, session: { state: "running", countdown_seconds: 500, session_token: token } };

// 1. booster running: shell goes to the Codespace VM
{
  const { pg, errors } = await page(running);
  await pg.waitForFunction(() => window.VyomiBooster && window.VyomiBooster.sessionLive() && window.VyomiBooster.state("vyomi-session") === "connected", null, { timeout: 15000 });
  check("session booster is registered and its link state is connected", true);
  await pg.evaluate(() => window.NanoVM.renderConnect(document.getElementById("host"), "aws", "i-good"));
  await pg.waitForSelector("[data-nano-booster-shell]", { timeout: 15000 });
  await pg.waitForFunction(() => /Connected to your Codespace VM vyomi-i-good/.test(document.querySelector("[data-nano-booster-status]").textContent), null, { timeout: 15000 });
  check("UI says 'Connected to your Codespace VM vyomi-i-good'", true);
  check("the in-browser VM panel is NOT shown for a booster instance", (await pg.getByText(/^In-browser VM$/).count()) === 0);
  await pg.click(".vy-term"); await pg.keyboard.type("echo ui-$((6*7))"); await pg.keyboard.press("Enter");
  const term = () => pg.evaluate(() => Array.from(document.querySelectorAll(".xterm-rows > div")).map((d) => d.textContent).join("\n"));
  let txt = ""; for (let i = 0; i < 50 && !/ui-42/.test(txt.replace(/echo ui-\$\(\(6\*7\)\)/g, "")); i++) { await sleep(100); txt = await term(); }
  check("typing in the terminal reaches the Codespace VM shell and its output renders", /FAKE-VM:vyomi-i-good/.test(txt) && /ui-42/.test(txt.replace(/echo ui-\$\(\(6\*7\)\)/g, "")), txt.slice(-200));
  check("power view: a booster instance is not rewritten to stopped/pending", await pg.evaluate(() => window.NanoVM.shownPower("aws", "i-good")) === "running");
  // booster dies mid-session: clear message + reconnect button, no fallback to the in-browser VM
  link.stop();
  await pg.waitForFunction(() => /not reachable|dropped|closed/i.test(document.querySelector("[data-nano-booster-status]").textContent), null, { timeout: 15000 });
  const msg = await pg.locator("[data-nano-booster-status]").textContent();
  check("booster link lost: the UI says so clearly and offers Reconnect", /Codespace booster is not reachable|booster link dropped/.test(msg) && await pg.locator("[data-nano-booster-reconnect]").isVisible(), msg);
  check("no uncaught page errors", errors.length === 0, errors.join(";"));
  await pg.context().close();
}
// 2. booster session running but the link is down at open time: explicit message, not the in-browser VM
{
  const { pg } = await page(running);
  await pg.waitForFunction(() => window.VyomiBooster && window.VyomiBooster.sessionLive(), null, { timeout: 15000 });
  await pg.waitForFunction(() => window.VyomiBooster.state("vyomi-session") === "unreachable", null, { timeout: 20000 });   // booster (link) is stopped now
  await pg.evaluate(() => window.NanoVM.renderConnect(document.getElementById("host"), "aws", "i-good"));
  await pg.waitForSelector("[data-nano-booster-msg=down]", { timeout: 10000 });
  check("booster down at open: 'Codespace booster unreachable' (no silent in-browser fallback)", (await pg.getByText(/^In-browser VM$/).count()) === 0 && /unreachable/i.test(await pg.locator("[data-nano-booster-msg]").textContent()));
  await pg.context().close();
}
// 3. no booster session: the in-browser path is untouched
{
  const { pg } = await page({ entitled: false });
  await pg.evaluate(() => window.NanoVM.renderConnect(document.getElementById("host"), "aws", "i-1"));
  await pg.getByText("VM not ready").waitFor({ timeout: 10000 });   // the unchanged in-browser path (connect-info 404 is stubbed)
  check("Free / no booster: the unchanged in-browser connect flow runs (no booster shell, no booster messages)", (await pg.locator("[data-nano-booster-shell]").count()) === 0 && (await pg.getByText(/^In-browser VM$/).count()) === 1 && (await pg.locator("[data-nano-booster-msg]").count()) === 0);
  await pg.context().close();
}
await browser.close(); link.stop(); cleanup();
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
