/* Booster SHELL stream test (tab -> relay /shell -> hub -> booster WSS -> booster-dial.mjs -> simulator /booster/shell -> PTY).
 *   NODE_PATH=/tmp/np/node_modules PY=<venv>/bin/python RELAY_PORT=8802 node wasm/relay/test-booster-shell.mjs
 * Real components: local-relay.mjs, booster-dial.mjs, core/booster_shell.py + core/booster_session.py (uvicorn). Only `docker` is
 * a test double (fixtures/fake-docker.sh runs a local `sh` on the PTY core/booster_shell.py allocates, so open/echo/resize are real).
 * Exit 1 on any FAIL. */
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import fs from "node:fs";
import os from "node:os";
import { mint } from "./booster-session.mjs";
import { dial } from "./booster-dial.mjs";

const require = createRequire(import.meta.url);
const WS = require(process.env.WS_PKG || "ws");
const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const PY = process.env.PY || "python3";
const RELAY = Number(process.env.RELAY_PORT || 8802), SIM = RELAY + 1;
const KEY = "shell-test-key-abcdef";
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowS = () => Math.floor(Date.now() / 1000);
const tok = (o = {}) => mint(o.key ?? KEY, { sub: "acct-1", tier: "pro", primary_cloud: "aws", session_id: "sess-1", session_end: nowS() + 3600, ...o });
const dockerLog = join(os.tmpdir(), `fake-docker-${process.pid}.log`);
try { fs.unlinkSync(dockerLog); } catch {}

const procs = [];
const spawnP = (cmd, args, env) => { const p = spawn(cmd, args, { env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] }); let log = ""; p.stdout.on("data", (d) => (log += d)); p.stderr.on("data", (d) => (log += d)); p.log = () => log; procs.push(p); return p; };
const cleanup = () => { for (const p of procs) try { p.kill(); } catch {} };
process.on("exit", cleanup);

const relayProc = spawnP(process.execPath, [join(here, "local-relay.mjs")], { RELAY_PORT: String(RELAY), RELAY_HOST: "127.0.0.1", VYOMI_BOOSTER_SESSION_KEY: KEY, VYOMI_SHELL_IDLE_MS: "4000", VYOMI_SHELL_MAX_PER_SESSION: "3" });
const startSim = (port = SIM) => spawnP(PY, [join(here, "test-fixtures/fake_booster_sim.py"), String(port)], {
  APPLIANCE_ROOT: root, VYOMI_ROLE: "booster", VYOMI_BOOSTER_SESSION_KEY: KEY, VYOMI_DOCKER_BIN: join(here, "test-fixtures/fake-docker.sh"),
  VYOMI_SHELL_NETWORK: "vyomi-net", VYOMI_FAKE_DOCKER: dockerLog, VYOMI_SHELL_IDLE_S: "3600", PYTHONPATH: root });
const simProc = startSim();
const sim2 = startSim(SIM + 1);          // a second booster (its own simulator process: the session end latches process-wide by design)
for (let i = 0; i < 80; i++) { try { if ((await fetch(`http://127.0.0.1:${RELAY}/health`)).ok) break; } catch {} await sleep(100); }
for (const port of [SIM, SIM + 1]) for (let i = 0; i < 100; i++) { try { await fetch(`http://127.0.0.1:${port}/x`); break; } catch {} await sleep(100); }
const health = await (await fetch(`http://127.0.0.1:${RELAY}/health`)).json();
check("relay advertises booster-shell", health.features.includes("booster-shell"), JSON.stringify(health.features));

const relayWs = `ws://127.0.0.1:${RELAY}`;
const token = tok();
const link = dial({ relayUrl: relayWs, token, localUrl: `http://127.0.0.1:${SIM}`, WS, log: () => {} });
for (let i = 0; i < 50 && !link.state.linked; i++) await sleep(100);
check("booster links", link.state.linked === true);

/** Open a tab-side shell. Returns {ws, out(), text[], closed:Promise<{code}>, send(), opened:Promise} */
function tab({ t = token, cloud = "aws", ref = "i-good", origin, extra = {}, raw } = {}) {
  const ws = new WS(`${relayWs}/shell`, origin ? { headers: { origin } } : {});
  const o = { ws, out: "", ctrl: [], rejected: null };
  o.opened = new Promise((res) => { o._opened = res; });
  o.closed = new Promise((res) => ws.on("close", (code) => res({ code })));
  ws.on("unexpected-response", (_q, r) => { o.rejected = r.statusCode; o._opened(false); });
  ws.on("error", () => {});
  ws.on("message", (d, isBin) => {
    if (isBin) { o.out += d.toString(); return; }
    const c = JSON.parse(d.toString()); o.ctrl.push(c);
    if (c.t === "opened") o._opened(true); if (c.t === "error") o._opened(false);
  });
  ws.on("open", () => ws.send(raw ?? JSON.stringify({ type: "auth", token: t, cloud, ref, cols: 90, rows: 25, ...extra })));
  o.send = (s) => ws.send(Buffer.from(s));
  o.waitFor = async (re, ms = 6000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (re.test(o.out)) return true; await sleep(50); } return false; };
  return o;
}
const code = (o) => o.ctrl.find((c) => c.t === "error")?.code;

// ── happy path
let a = tab();
check("open: stream opens and reports the container", await a.opened && a.ctrl[0].container === "vyomi-i-good", JSON.stringify(a.ctrl));
check("open: the VM banner (container identity) reaches the tab", await a.waitFor(/FAKE-VM:vyomi-i-good/));
a.send("echo hello-$((20+22))\n");
check("echo: typed input round-trips through the PTY", await a.waitFor(/hello-42/));
a.send("stty size\n");
check("initial size from the open frame is applied (25 rows x 90 cols)", await a.waitFor(/25 90/));
a.ws.send(JSON.stringify({ t: "resize", cols: 120, rows: 40 }));
await sleep(300); a.send("stty size\n");
check("resize: the PTY window size changes (40 rows x 120 cols)", await a.waitFor(/40 120/));
const argv = fs.readFileSync(dockerLog, "utf8").split("\n").filter((l) => l.startsWith("exec"));
check("docker exec argv is fixed (-it, TERM, shell-id tag, container, sh -c ...) with no client-controlled parts",
      argv.length === 1 && /^exec -it -e TERM=xterm-256color -e VYOMI_SHELL_ID=[0-9a-f]{32} vyomi-i-good sh -c /.test(argv[0]), JSON.stringify(argv));
a.send("exit\n");
const cl = await Promise.race([a.closed, sleep(5000).then(() => null)]);
check("close: shell exit closes the stream cleanly", cl && cl.code === 1000, JSON.stringify(cl));

// ── client closes
a = tab(); await a.opened; await a.waitFor(/FAKE-VM/);
a.ws.send(JSON.stringify({ t: "close" }));
check("close: client close frame ends the stream", !!(await Promise.race([a.closed, sleep(3000).then(() => null)])));
await sleep(300);
check("relay holds no streams after close", (await (await fetch(`http://127.0.0.1:${RELAY}/health`)).json()).booster_streams === 0);

// ── other clouds
for (const [cloud, ref, cn] of [["gcp", "vm-gcp1", "vyomi-i-gcp1"], ["azure", "vm-az1", "vyomi-i-az1"]]) {
  const t = tab({ cloud, ref }); const ok = await t.opened;
  check(`${cloud}: shell opens into ${cn}`, ok && t.ctrl[0].container === cn && await t.waitFor(new RegExp("FAKE-VM:" + cn)), JSON.stringify(t.ctrl));
  t.ws.close();
}

// ── auth / origin failures
let b = tab({ t: tok({ key: "wrong-key" }) }); await b.opened;
check("auth failure: token signed by another key -> error + close", code(b) === "BoosterSessionBadSignature", JSON.stringify(b.ctrl));
b = tab({ raw: "not json" }); await b.opened; check("auth failure: garbage first message", code(b) === "BadRequest", JSON.stringify(b.ctrl));
b = tab({ t: "" }); await b.opened; check("auth failure: empty token", /BoosterSession/.test(code(b) || ""), JSON.stringify(b.ctrl));
b = tab({ origin: "https://evil.example" }); await b.opened;
check("origin check: wrong Origin refused at upgrade (403)", b.rejected === 403, b.rejected);
b = tab({ origin: "https://vyomi.cloud" }); check("origin check: https://vyomi.cloud allowed", await b.opened === true); b.ws.close();
b = tab({ t: tok({ tier: "free" }) }); await b.opened; check("Free-tier token cannot open a shell", code(b) === "BoosterTierNotEligible", JSON.stringify(b.ctrl));
b = tab({ t: tok({ session_end: nowS() - 5, iat: nowS() - 100 }) }); await b.opened; check("expired token refused", code(b) === "BoosterSessionExpired", JSON.stringify(b.ctrl));
b = tab({ t: tok({ role: "llm-runner" }) }); await b.opened; check("runner-role token cannot open a shell", code(b) === "BoosterSessionWrongRole", JSON.stringify(b.ctrl));

// ── no cross-session / cross-account access
b = tab({ t: tok({ session_id: "other-session" }) }); await b.opened;
check("cross-session: valid token for a session with no booster -> BoosterNotLinked", code(b) === "BoosterNotLinked", JSON.stringify(b.ctrl));
b = tab({ t: tok({ sub: "someone-else" }) }); await b.opened;
check("cross-account: same session id, other account -> BoosterSessionMismatch", code(b) === "BoosterSessionMismatch", JSON.stringify(b.ctrl));

// ── wrong-container refusals (the simulator decides; the client cannot name a container)
const refusals = [["aws", "i-ghost", "InstanceNotFound"], ["aws", "i-nope", "InstanceNotFound"], ["aws", "i-evil", "ContainerNotAllowed"], ["aws", "i-evil2", "ContainerNotAllowed"],
                  ["aws", "i-othernet", "ContainerNotAllowed"], ["aws", "i-nolabel", "ContainerNotAllowed"], ["aws", "i-stopped", "InstanceNotRunning"], ["aws", "vyomi-i-good", "InstanceNotFound"]];
for (const [cloud, ref, want] of refusals) {
  b = tab({ cloud, ref }); await b.opened; check(`refused: ${cloud}/${ref} -> ${want}`, code(b) === want, JSON.stringify(b.ctrl));
}
b = tab({ cloud: "aws", ref: "i-good", extra: { container: "vyomi-i-good2", name: "nginx" } }); await b.opened;
check("a client-supplied container name is ignored (still the resolved instance)", b.ctrl[0]?.container === "vyomi-i-good", JSON.stringify(b.ctrl)); b.ws.close();
b = tab({ cloud: "../..", ref: "i-good" }); await b.opened; check("bad cloud refused", code(b) === "BadRequest", JSON.stringify(b.ctrl));
const inspected = fs.readFileSync(dockerLog, "utf8");
check("no docker exec was ever run for a refused target", !/exec .*(nginx|ghost|othernet|nolabel|stopped|evil)/.test(inspected));

// ── limits
const many = []; for (let i = 0; i < 3; i++) { const t = tab(); await t.opened; many.push(t); }
b = tab(); await b.opened; check("per-session stream cap (3 in this test)", code(b) === "TooManyShells", JSON.stringify(b.ctrl));
many.forEach((t) => t.ws.close()); await sleep(500);
const big = tab(); await big.opened; big.ws.send(Buffer.alloc(80 * 1024, 97));
check("oversized input frame closes the stream", (await Promise.race([big.closed, sleep(3000).then(() => null)]))?.code === 1009);

// ── idle timeout (relay: 4 s in this test)
const idle = tab(); await idle.opened;
const ic = await Promise.race([idle.closed, sleep(9000).then(() => null)]);
check("idle timeout closes the stream (4408)", ic?.code === 4408 && code(idle) === "IdleTimeout", JSON.stringify({ ic, c: idle.ctrl }));

// ── backpressure: a flood of output reaches the tab intact and the link stays alive
const flood = tab(); await flood.opened; await flood.waitFor(/FAKE-VM/);
flood.send("i=0; while [ $i -lt 4000 ]; do echo flood-line-$i-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx; i=$((i+1)); done; echo FLOOD-DONE\n");
check("flood output (~300 KB) streams through the link and completes", await flood.waitFor(/flood-line-3999-x+\r\nFLOOD-DONE/, 20000) && flood.out.includes("flood-line-0-") && (flood.out.match(/flood-line-\d+-/g) || []).length >= 4000, `${flood.out.length} bytes; ctrl=${JSON.stringify(flood.ctrl)}; tail=${JSON.stringify(flood.out.slice(-120))}`);
flood.ws.close();

// ── token expiry closes streams (session_end in 4 s; relay timer fires at the exact second)
const t2 = tok({ session_id: "sess-exp", session_end: nowS() + 4 });
const link2 = dial({ relayUrl: relayWs, token: t2, localUrl: `http://127.0.0.1:${SIM + 1}`, WS, log: () => {} });
for (let i = 0; i < 50 && !link2.state.linked; i++) await sleep(100);
const e = tab({ t: t2 }); check("short session opens a shell", await e.opened === true);
const ec = await Promise.race([e.closed, sleep(9000).then(() => null)]);
check("token expiry closes the open stream (4410)", ec?.code === 4410 && code(e) === "BoosterSessionExpired", JSON.stringify({ ec, c: e.ctrl }));

// ── booster link dies (relay restart / booster disconnect): streams are cleaned up on both sides
const c1 = tab(); await c1.opened; if (!c1.ctrl.some((c) => c.t === "opened")) console.log("c1 ctrl", JSON.stringify(c1.ctrl)); await c1.waitFor(/FAKE-VM/);
const pidFile = join(os.tmpdir(), `shellpid-${process.pid}`);
c1.send("echo $$ > " + pidFile + "; sleep 600\n");
for (let i = 0; i < 50 && !(fs.existsSync(pidFile) && fs.readFileSync(pidFile, "utf8").trim()); i++) await sleep(100);
const shellPid = Number(fs.readFileSync(pidFile, "utf8").trim());
relayProc.kill("SIGKILL");
const rc = await Promise.race([c1.closed, sleep(5000).then(() => null)]);
check("relay restart: the tab's stream is closed", !!rc);
await sleep(1500);
let alive = true; try { process.kill(shellPid, 0); } catch { alive = false; }
check("relay restart: the PTY child on the booster is killed (no orphan shell)", !alive, "pid " + shellPid);
try { fs.unlinkSync(pidFile); } catch {}
check("dial agent saw the link drop (its local streams are closed in the same handler)", link.state.linked === false);

// ── simulator-level: direct (no relay) refusals
const direct = (hdrs) => new Promise((resolveP) => {
  const w = new WS(`ws://127.0.0.1:${SIM}/booster/shell?cloud=aws&ref=i-good`, { headers: hdrs });
  let opened = false; w.on("open", () => (opened = true));
  w.on("unexpected-response", (_q, r) => resolveP({ status: r.statusCode }));
  w.on("close", (c) => resolveP({ opened, code: c })); w.on("error", () => {});
});
let dres = await direct({});
check("simulator endpoint: no session token -> refused (1008)", dres.code === 1008 || dres.status === 403, JSON.stringify(dres));
dres = await direct({ "x-vyomi-session-token": tok({ key: "wrong-key" }) });
check("simulator endpoint: bad token -> refused", dres.code === 1008 || dres.status === 403, JSON.stringify(dres));

link.stop(); link2.stop(); cleanup();
try { fs.unlinkSync(dockerLog); } catch {}
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
process.exit(bad ? 1 : 0);
