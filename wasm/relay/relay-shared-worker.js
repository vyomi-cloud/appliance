// Vyomi-Nano relay endpoint — as a SHARED WORKER.
//
// A SharedWorker is the only browser context that survives full-page navigation
// without a separate tab, so the relay endpoint (Pyodide + cores + the native-
// AWS-wire router + the outbound relay WebSocket) lives HERE. Every view
// (launch dashboard + each provider console) shows a frozen footer that connects
// to this single worker, so the tunnel stays connected as you move between views
// — no extra tab. Status + boot/splash logs are mirrored to all views over a
// same-origin BroadcastChannel('nano-relay'); commands (start/stop/query) arrive
// on each page's MessagePort.
//
// Same WS protocol as nano-endpoint.html (the standalone-tab variant kept for
// tests / advanced use):
//   relay → worker : {id, method, path, query, headers, body(base64)}
//   worker → relay : {id, status, headers, body(base64)}
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.mjs";
import { installPGlite } from "../pglite-loader.js";

const PYODIDE_INDEX = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
// Cores live at ../core/ relative to THIS worker (works at web root AND /nano/).
const CORE_BASE = new URL("../core/", self.location.href).href.replace(/\/$/, "");
const CORES = [
  "object_store.py", "s3_object_core.py", "nosql_store.py", "dynamodb_core.py",
  "kms_keystore.py", "kms_core.py", "kv_store.py", "secrets_core.py",
  "sql_store.py", "rds_core.py", "iam_store.py", "iam_core.py",
  "messaging_store.py", "sqs_core.py", "sns_core.py", "rds_data_core.py", "aws_wire_router.py",
];

const bc = new BroadcastChannel("nano-relay");
// Defaults; the page (footer) may override any of these via the `start` message
// (it reads localStorage — workers can't). `session` scopes the cloud tunnel.
const DEFAULT_CFG = {
  localHealth:   "http://127.0.0.1:8090/health",
  localWs:       "ws://127.0.0.1:8090/register",
  localExternal: "http://127.0.0.1:8090",
  cloudWsBase:   "wss://relay.vyomi.cloud/register",
  cloudExternal: "https://relay.vyomi.cloud",
};
const state = {
  phase: "off", served: 0, stopped: false,
  mode: null,        // "local" | "cloud" — which tunnel is active
  external: null,    // the URL an external app points at (differs per mode)
  session: null,     // cloud session id (from the page)
  note: null,        // actionable hint shown in the footer when a tunnel can't connect
  cfg: DEFAULT_CFG,
};
// The public relay (relay.vyomi.cloud) only accepts registrations from the prod
// origin, so from localhost the cloud tunnel can never connect — we detect that
// and tell the user to run a local tunnel instead of looping silently.
const IS_LOCAL_ORIGIN = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|$)/.test(self.location.origin);
const logbuf = [];                                   // ring buffer for late-joining views
function log(line, cls) {
  logbuf.push({ line, cls: cls || "" }); if (logbuf.length > 200) logbuf.shift();
  bc.postMessage({ type: "log", line, cls: cls || "" });
}
function announce() {
  bc.postMessage({ type: "status", state: state.phase, served: state.served,
                   mode: state.mode, external: state.external, note: state.note || null });
}
setInterval(announce, 3000);

let py = null, handle = null, booting = null, ws = null;
let monitorTimer = null, localFails = 0, cloudFailStreak = 0;

// ── Tunnel selection: prefer the LOCAL relay when present, else CLOUD ─────────
// A loopback fetch from an https tab is allowed (localhost is exempt from mixed
// content); the relay answers /health with CORS + PNA headers so the probe works.
async function probeLocal() {
  try {
    const c = new AbortController();
    const t = setTimeout(() => c.abort(), 1500);
    const r = await fetch(state.cfg.localHealth, { signal: c.signal, cache: "no-store" });
    clearTimeout(t);
    return r.ok;
  } catch (_) { return false; }
}
function wsUrlFor(mode) {
  return mode === "local"
    ? state.cfg.localWs
    : state.cfg.cloudWsBase + "?session=" + encodeURIComponent(state.session || "nano");
}
function externalFor(mode) {
  return mode === "local"
    ? state.cfg.localExternal
    : state.cfg.cloudExternal + "/" + encodeURIComponent(state.session || "nano");
}

async function bootPyodide() {
  if (booting) return booting;
  booting = (async () => {
    log("loading Pyodide…", "dim");
    py = await loadPyodide({ indexURL: PYODIDE_INDEX });   // explicit indexURL: required in a worker
    try { await py.loadPackage("sqlite3"); } catch (e) { log("sqlite3 load skipped: " + e, "dim"); }
    const hasPg = await installPGlite();
    py.globals.set("_USE_PGLITE", hasPg);
    py.FS.mkdir("/core"); py.FS.writeFile("/core/__init__.py", "");
    for (const f of CORES)
      py.FS.writeFile("/core/" + f, await (await fetch(CORE_BASE + "/" + f)).text());
    py.runPython(`
import sys, json, base64; sys.path.insert(0, "/")
from core.aws_wire_router import AwsWireRouter
from core import rds_core as _rds
if _USE_PGLITE:
    from core.sql_store import PGliteSqlStore
    _ROUTER = AwsWireRouter(sql_store=PGliteSqlStore())
else:
    _ROUTER = AwsWireRouter()
async def _handle(req_json):
    r = json.loads(req_json)
    body = base64.b64decode(r.get("body") or "")
    resp = await _ROUTER.ahandle(r["method"], r["path"], r.get("query") or {},
                                 r.get("headers") or {}, body)
    return json.dumps({"status": resp["status"], "headers": resp["headers"],
                       "body": base64.b64encode(resp["body"] or b"").decode()})
import builtins; builtins._handle = _handle
`);
    handle = (reqJson) => py.runPythonAsync(`await _handle(${JSON.stringify(reqJson)})`);
    log("cores loaded (S3·DynamoDB·KMS·Secrets·SQS·SNS·IAM·RDS — real handlers in Pyodide)", "ok");
    log(hasPg ? "RDS engine: PGlite (real Postgres)" : "RDS engine: sqlite3 (PGlite unavailable)", hasPg ? "ok" : "dim");
  })();
  return booting;
}

function connect() {
  if (state.stopped) return;
  state.phase = "connecting"; announce();
  const url = wsUrlFor(state.mode);
  ws = new WebSocket(url);
  let opened = false;
  ws.onopen = () => {
    opened = true; cloudFailStreak = 0; state.note = null;
    state.phase = "connected"; state.external = externalFor(state.mode);
    log("registered [" + state.mode + "] · apps → " + state.external, "ok");
    announce();
  };
  ws.onclose = (ev) => {
    if (state.stopped) { state.phase = "off"; announce(); return; }
    // A cloud registration that never opened is almost always the relay's origin
    // guardrail (relay.vyomi.cloud only accepts the prod origin) or the relay
    // being down — so retrying silently forever just reads as a stuck spinner.
    // After a couple of misses, surface an ACTIONABLE note; the 15s local monitor
    // keeps probing, so the moment a local tunnel appears we switch + this clears.
    if (!opened && state.mode === "cloud" && ++cloudFailStreak >= 2 && !state.note) {
      state.note = IS_LOCAL_ORIGIN
        ? "no local tunnel — run `vyomi-tunnel`"
        : "relay unreachable — retrying";
      log(IS_LOCAL_ORIGIN
        ? "The public relay only serves vyomi.cloud, so localhost can't register. Start a local tunnel: `vyomi-tunnel` (or `node local-relay.mjs`). This connects automatically once it's up."
        : "Relay unreachable — retrying. If it persists, start a local tunnel (`vyomi-tunnel`).", "err");
    }
    state.phase = "connecting"; log("disconnected (code " + ev.code + "); retrying…", "dim"); announce();
    setTimeout(connect, state.note ? 5000 : 1000);   // back off once the hint is shown
  };
  ws.onerror = () => log("ws error [" + state.mode + "]", "err");
  ws.onmessage = async (ev) => {
    let req; try { req = JSON.parse(ev.data); } catch { return; }
    if (req.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
    try {
      const resp = JSON.parse(await handle(JSON.stringify(req)));
      ws.send(JSON.stringify({ id: req.id, ...resp }));
      state.served++; announce();
    } catch (e) {
      ws.send(JSON.stringify({ id: req.id, status: 500,
        headers: { "content-type": "text/plain" }, body: btoa("nano endpoint error: " + e) }));
    }
  };
}

// Re-probe local on a timer so the choice is DYNAMIC: install the local tunnel
// later and we switch up to it; kill it and we fall back to cloud — no reload.
function startMonitor() {
  if (monitorTimer) return;
  monitorTimer = setInterval(async () => {
    if (state.stopped) return;
    const up = await probeLocal();
    if (state.mode === "cloud" && up) {
      log("local tunnel detected → switching to LOCAL", "ok");
      switchTo("local");
    } else if (state.mode === "local") {
      if (up) { localFails = 0; }
      else if (++localFails >= 2) {          // two misses ⇒ really gone
        log("local tunnel gone → falling back to CLOUD", "dim");
        switchTo("cloud");
      }
    }
  }, 15000);
}
function switchTo(mode) {
  if (mode === state.mode) return;
  state.mode = mode; localFails = 0; cloudFailStreak = 0; state.note = null;
  // Closing triggers onclose → reconnect, which now targets the new mode's URL.
  try { if (ws) ws.close(1000, "tunnel-switch"); } catch (_) {}
}

async function start(msg) {
  msg = msg || {};
  if (msg.session) state.session = msg.session;
  if (msg.config) state.cfg = { ...DEFAULT_CFG, ...msg.config };
  if (state.phase === "connected" || (state.phase === "connecting" && !state.stopped && ws)) { announce(); return; }
  state.stopped = false; state.note = null; cloudFailStreak = 0;
  state.phase = "connecting"; announce();
  try { await bootPyodide(); } catch (e) { log("boot failed: " + (e && e.stack || e), "err"); state.phase = "off"; announce(); return; }
  state.mode = (await probeLocal()) ? "local" : "cloud";
  localFails = 0;
  log(state.mode === "local"
    ? "tunnel: LOCAL (detected — fast, private, offline)"
    : "tunnel: CLOUD (Cloudflare — no local tunnel detected)", state.mode === "local" ? "ok" : "dim");
  connect();
  startMonitor();
}

function stop() {
  state.stopped = true;
  if (monitorTimer) { clearInterval(monitorTimer); monitorTimer = null; }
  try { if (ws) ws.close(); } catch (_) {}
  state.phase = "off"; state.note = null; announce();
}

self.onconnect = (e) => {
  const port = e.ports[0]; port.start();
  port.onmessage = (ev) => {
    const m = ev.data || {};
    if (m.type === "start") start(m);
    else if (m.type === "stop") stop();
    else if (m.type === "query") { announce(); bc.postMessage({ type: "logs", lines: logbuf.slice() }); }
  };
  // Greet the new view with current state + log history immediately.
  announce(); port.postMessage({ type: "logs", lines: logbuf.slice() });
};
