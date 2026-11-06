/* Nano link vs the REAL booster (core/booster.py via tests/booster/run_real_booster.py): code from /booster/pair/start (CLI path),
 * pair in the tab, status fields, authenticated /_wire, bad token refused, kill -> "Datacenter unreachable", restart -> recovery,
 * expired trial -> lock. Self-contained (starts the Nano preview + the booster).
 *   PW=<playwright path> PY=<python> node consoles/tests/booster-link-real-smoke.mjs      Exit 1 on any FAIL. */
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "..", "..");
const PY = process.env.PY || "/Users/sudhirganti/Applications/simulator/appliance/.venv/bin/python";
const NP = Number(process.env.PORT || 8791), BP = Number(process.env.BOOSTER_PORT || 9101);
const NANO = `http://127.0.0.1:${NP}/nano`, BOOSTER = `http://127.0.0.1:${BP}`;
let bad = 0; const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let booster = null;
const startBooster = async (days = 14, stateDir) => {
  booster = spawn(PY, [join(root, "tests/booster/run_real_booster.py"), String(BP), String(days)], { cwd: root, env: { ...process.env, PYTHONPATH: root, VYOMI_BOOSTER_RELAY_URL: BOOSTER + "/", ...(stateDir ? { CLOUDLEARN_STATE_DIR: stateDir } : {}) }, stdio: "ignore" });
  for (let i = 0; i < 120; i++) { try { if ((await fetch(BOOSTER + "/booster/status")).ok) return; } catch {} await sleep(500); }
  throw new Error("booster did not start");
};
const stopBooster = async () => { if (booster) { booster.kill("SIGKILL"); booster = null; await sleep(800); } };
const preview = spawn("node", [join(root, "consoles/nano_preview.mjs"), "--port", String(NP)], { stdio: "ignore" });
for (let i = 0; i < 40; i++) { try { if ((await fetch(`${NANO}/`, { redirect: "manual" })).status < 500) break; } catch {} await sleep(250); }
const stateDir = (await import("node:fs")).mkdtempSync((await import("node:os")).tmpdir() + "/booster-real-");
let browser;
try {
  await startBooster(14, stateDir);
  const st0 = await (await fetch(BOOSTER + "/booster/status")).json();
  check("real booster is headless Pro with trial days", st0.headless && st0.tier === "pro" && st0.trial_days_left >= 13, JSON.stringify([st0.tier, st0.trial_days_left]));
  check("booster serves no UI (404 BoosterHeadless)", (await fetch(BOOSTER + "/ui/", { headers: { accept: "text/html" } })).status === 404);
  browser = await pw.chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(() => { try { localStorage.setItem("vyomi.booster_poll_ms", "300"); } catch {} });
  const page = await ctx.newPage(); const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  const wait = (fn, arg, t = 20000) => page.waitForFunction(fn, arg, { timeout: t }).then(() => true, () => false);
  await page.goto(`${NANO}/clouds.html`);
  await wait(() => !!window.VyomiBooster && !!navigator.serviceWorker.controller, null, 40000); await page.waitForTimeout(1500);
  await wait(() => !!window.VyomiBooster && !!navigator.serviceWorker.controller, null, 40000);
  // pairing: the code comes from the CLI path (loopback POST), never the browser
  const code = (await (await fetch(BOOSTER + "/booster/pair/start", { method: "POST" })).json()).code;
  check("pair/start issues a code from loopback", /^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code || ""), code);
  const wrong = await page.evaluate((b) => VyomiBooster.pair(b, "ZZZZ-0000").then(() => "paired", (e) => String(e.message)), BOOSTER);
  check("wrong code refused", /refused|check the code/i.test(wrong), wrong);
  const code2 = (await (await fetch(BOOSTER + "/booster/pair/start", { method: "POST" })).json()).code;
  const paired = await page.evaluate(([b, c]) => VyomiBooster.pair(b, c).then((x) => x || "ok", (e) => "ERR " + e.message), [BOOSTER, code2]);
  check("pairing with the real code succeeds", !String(paired).startsWith("ERR"), JSON.stringify(paired));
  check("tab reports connected", await wait(() => VyomiBooster.list().some((b) => VyomiBooster.state(b.id) === "connected")));
  const reg = await page.evaluate(() => JSON.stringify(VyomiBooster.list()));
  check("registry has the booster, token not exposed", new RegExp("127-0-0-1-" + BP).test(reg) && !/"token"/.test(reg), reg);
  const regE = await page.evaluate(() => JSON.parse(localStorage.getItem("vyomi.boosters"))[0]);
  check("pair response endpoints land in the registry (relay_url from the booster, local_url null)", regE.relay_url === BOOSTER && !regE.local_url, JSON.stringify([regE.relay_url, regE.local_url]));
  // authenticated /_wire straight at the real booster
  const tok = await page.evaluate(() => { const r = JSON.parse(localStorage.getItem("vyomi.boosters") || "[]"); return r[0] && r[0].token; });
  const okWire = await fetch(BOOSTER + "/_wire/", { headers: { "x-vyomi-booster-token": tok, origin: `http://127.0.0.1:${NP}` } });
  const badWire = await fetch(BOOSTER + "/_wire/", { headers: { "x-vyomi-booster-token": "nope", origin: `http://127.0.0.1:${NP}` } });
  check("valid token accepted on /_wire", okWire.status !== 401, okWire.status);
  check("bad token refused on /_wire (401)", badWire.status === 401, badWire.status);
  const pre = await fetch(BOOSTER + "/booster/status", { method: "OPTIONS", headers: { origin: `http://127.0.0.1:${NP}`, "access-control-request-method": "GET", "access-control-request-private-network": "true", "access-control-request-headers": "authorization,x-vyomi-booster-token" } });
  check("CORS preflight allows private network + token header", pre.status < 300 && pre.headers.get("access-control-allow-private-network") === "true" && /x-vyomi-booster-token/i.test(pre.headers.get("access-control-allow-headers") || ""), `${pre.status} ${pre.headers.get("access-control-allow-headers")}`);
  // outage -> unreachable -> recovery (same state dir keeps the secret, so the token stays valid)
  await stopBooster();
  check("tab shows unreachable when the booster dies", await wait(() => VyomiBooster.list().some((b) => VyomiBooster.state(b.id) === "unreachable"), null, 30000));
  await startBooster(14, stateDir);
  check("tab recovers when the booster returns", await wait(() => VyomiBooster.list().some((b) => VyomiBooster.state(b.id) === "connected"), null, 40000));
  // expired trial -> locked
  await stopBooster(); await startBooster(-1, stateDir);
  const stL = await (await fetch(BOOSTER + "/booster/status")).json();
  check("expired trial reports locked, still headless", stL.locked === true && stL.headless === true, JSON.stringify([stL.locked, stL.trial_state]));
  check("no page errors", errors.length === 0, errors.join(" | "));
} catch (e) { bad++; console.log("FAIL harness - " + (e && e.stack || e)); }
finally { try { await browser?.close(); } catch {} await stopBooster(); preview.kill(); }
console.log(bad ? `${bad} FAILED` : "ALL PASS"); process.exit(bad ? 1 : 0);
