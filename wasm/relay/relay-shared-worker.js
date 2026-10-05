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
  "messaging_store.py", "sqs_core.py", "sns_core.py", "rds_data_core.py",
  // GCP + Azure cores — imported by aws_wire_router (must load before it).
  "gcp_storage_core.py", "gcp_firestore_core.py", "gcp_kms_core.py",
  "gcp_secretmanager_core.py", "gcp_pubsub_core.py", "gcp_iam_core.py", "gcp_cloudsql_core.py",
  "azure_blob_core.py", "azure_cosmos_core.py", "azure_keyvault_secrets_core.py",
  "azure_keyvault_keys_core.py", "azure_queue_core.py", "azure_servicebus_core.py",
  "eventbridge_core.py", "lambda_core.py", "apigateway_core.py", "vpc_core.py",
  "azure_sql_core.py", "azure_iam_core.py",
  "aws_wire_router.py",
  "nano_registry.py", "nano_persist.py",   // shared registry + store persistence (console↔CLI parity)
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
const IDLE_MS = 30 * 60 * 1000;   // pause the tunnel after 30 min with no relayed request
const state = {
  phase: "off", served: 0, stopped: false,
  idle: false,       // paused after IDLE_MS of no traffic — user reconnects manually
  noIdle: false,     // signed-in perk: never idle-pause (footer sets it from license)
  lastActivity: 0,   // ts of the last relayed request (or the connect moment)
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
                   mode: state.mode, external: state.external, note: state.note || null,
                   idle: state.idle });
}
setInterval(announce, 3000);

let py = null, handle = null, booting = null, ws = null;
let monitorTimer = null, localFails = 0, cloudFailStreak = 0;
let scheduleStoresSave = () => {};   // real impl installed once Pyodide is up (store-sync in bootPyodide)

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
from core import nano_registry as _reg, nano_persist as _persist
# Build the router from the SHARED registry so the console adapter (aws_core_adapter,
# which also draws from nano_registry) and this relay serve ONE store set, and so
# nano_persist snapshots/restores the SAME live stores across contexts. Previously
# this worker built a fresh AwsWireRouter() → a private, unsynced store, so a bucket
# created in the console UI was invisible to the SDK/CLI here.
_STORES = _reg.get()
if _USE_PGLITE:
    from core.sql_store import PGliteSqlStore
    _STORES["rds"] = PGliteSqlStore()                     # RDS = real Postgres (shared seam)
_ROUTER = AwsWireRouter(stores=_STORES)
def _capture(): return json.dumps(_persist.capture_registry())
def _restore(blob_json):
    try: _persist.restore_registry(json.loads(blob_json or "{}"))
    except Exception: pass
async def _handle(req_json):
    r = json.loads(req_json)
    body = base64.b64decode(r.get("body") or "")
    resp = await _ROUTER.ahandle(r["method"], r["path"], r.get("query") or {},
                                 r.get("headers") or {}, body)
    return json.dumps({"status": resp["status"], "headers": resp["headers"],
                       "body": base64.b64encode(resp["body"] or b"").decode()})
import builtins; builtins._handle = _handle
builtins._capture = _capture; builtins._restore = _restore
`);
    handle = (reqJson) => py.runPythonAsync(`await _handle(${JSON.stringify(reqJson)})`);
    log("cores loaded (S3·DynamoDB·KMS·Secrets·SQS·SNS·IAM·RDS — real handlers in Pyodide)", "ok");
    log(hasPg ? "RDS engine: PGlite (real Postgres)" : "RDS engine: sqlite3 (PGlite unavailable)", hasPg ? "ok" : "dim");

    // ── Store persistence + cross-context sync (console ↔ SDK/CLI parity) ──
    // Snapshot the shared registry → nano-spaces IndexedDB after each served
    // request, rehydrate on boot, and reload when the console broadcasts a change —
    // so a bucket created in the console UI is visible via the SDK/CLI through this
    // relay, and vice-versa. Same DB/store/key/channel the console (nano-boot.js)
    // uses. All guarded — persistence NEVER blocks serving. Workers have indexedDB
    // + BroadcastChannel, so this runs in the SharedWorker just as in the tab.
    const _SK = "nano:stores";
    const _idb = (mode, fn) => new Promise((res) => {
      const r = indexedDB.open("nano-spaces", 1);
      r.onupgradeneeded = () => { const d = r.result;
        if (!d.objectStoreNames.contains("spaces")) d.createObjectStore("spaces", { keyPath: "space_id" });
        if (!d.objectStoreNames.contains("meta"))   d.createObjectStore("meta",   { keyPath: "k" }); };
      r.onsuccess = () => { try { fn(r.result.transaction("meta", mode).objectStore("meta"), res); } catch (_) { res(null); } };
      r.onerror = () => res(null);
    });
    const idbGet = (k) => _idb("readonly",  (s, res) => { const g = s.get(k); g.onsuccess = () => res(g.result ? g.result.v : null); g.onerror = () => res(null); });
    const idbPut = (k, v) => _idb("readwrite", (s, res) => { s.put({ k, v }); res(null); });
    let _storesBC = null; try { _storesBC = new BroadcastChannel("nano-stores"); } catch (_) {}
    let _restoring = false, _storeTimer = null;
    const capStores = () => { try { return py.runPython("_capture()"); } catch (_) { return null; } };
    const resStores = (j) => { if (!j) return; try { py.globals.set("_vy_blob", j); py.runPython("_restore(_vy_blob)"); } catch (_) {} };
    async function saveStores(notify) { try { const j = capStores(); if (!j) return; await idbPut(_SK, j); if (notify && _storesBC) { try { _storesBC.postMessage({ k: _SK, t: Date.now() }); } catch (_) {} } } catch (_) {} }
    scheduleStoresSave = () => { if (_storeTimer) return; _storeTimer = setTimeout(() => { _storeTimer = null; saveStores(true); }, 400); };
    if (_storesBC) _storesBC.onmessage = async (e) => { if (!e.data || e.data.k !== _SK || _restoring) return; _restoring = true; try { resStores(await idbGet(_SK)); } finally { _restoring = false; } };
    try { resStores(await idbGet(_SK)); } catch (_) {}   // boot: rehydrate before serving
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
    opened = true; cloudFailStreak = 0; state.note = null; state.idle = false;
    state.phase = "connected"; state.external = externalFor(state.mode);
    state.lastActivity = Date.now();
    log("registered [" + state.mode + "] · apps → " + state.external, "ok");
    announce();
  };
  ws.onclose = (ev) => {
    if (state.stopped) { state.phase = "off"; announce(); return; }
    if (state.idle) { state.phase = "idle"; announce(); return; }   // paused — wait for the user, no auto-reconnect
    // A registration that never opens: on LOCALHOST the local relay isn't running
    // (localhost never uses the cloud relay — it can't register there); on PROD the
    // cloud relay is down/blocked. After a couple of misses, surface an ACTIONABLE
    // note instead of a silent spinner; the 15s monitor keeps probing so it clears
    // the moment the tunnel appears.
    if (!opened && ++cloudFailStreak >= 2 && !state.note) {
      state.note = IS_LOCAL_ORIGIN
        ? "no local tunnel — run `vyomi-tunnel`"
        : "relay unreachable — retrying";
      log(IS_LOCAL_ORIGIN
        ? "Localhost uses the LOCAL tunnel. Start it: `vyomi-tunnel` (or `node local-relay.mjs`) — it connects automatically once up. (The public relay only serves vyomi.cloud.)"
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
      state.served++; state.lastActivity = Date.now(); announce();
      scheduleStoresSave();   // persist the shared registry + notify the console (parity)
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
    // Idle auto-pause: no relayed request for IDLE_MS → disconnect to conserve
    // resources. Honest timeout — the user reconnects with one click, no strings.
    if (state.phase === "connected" && !state.noIdle && Date.now() - state.lastActivity > IDLE_MS) { idlePause(); return; }
    const up = await probeLocal();
    if (state.mode === "cloud" && up) {
      log("local tunnel detected → switching to LOCAL", "ok");
      switchTo("local");
    } else if (state.mode === "local") {
      if (up) { localFails = 0; }
      else if (!IS_LOCAL_ORIGIN && ++localFails >= 2) {   // prod: fall back to cloud
        log("local tunnel gone → falling back to CLOUD", "dim");
        switchTo("cloud");
      }
      // localhost NEVER falls back to cloud (it can't register there) — stays local
      // and keeps retrying; the note tells the user to run `vyomi-tunnel`.
    }
  }, 15000);
}
function switchTo(mode) {
  if (mode === state.mode) return;
  state.mode = mode; localFails = 0; cloudFailStreak = 0; state.note = null;
  // Closing triggers onclose → reconnect, which now targets the new mode's URL.
  try { if (ws) ws.close(1000, "tunnel-switch"); } catch (_) {}
}
// Pause (not stop): keep Pyodide + the cores warm so Reconnect is instant. The
// onclose handler sees state.idle and does NOT auto-reconnect.
function idlePause() {
  state.idle = true; state.phase = "idle";
  log("Tunnel paused after 30 min idle — external apps can't reach the sim until you Reconnect (one click).", "dim");
  try { if (ws) ws.close(1000, "idle"); } catch (_) {}
  announce();
}

async function start(msg) {
  msg = msg || {};
  if (msg.session) state.session = msg.session;
  if (msg.config) state.cfg = { ...DEFAULT_CFG, ...msg.config };
  if (state.phase === "connected" || (state.phase === "connecting" && !state.stopped && ws)) { announce(); return; }
  if (msg.noIdle !== undefined) state.noIdle = !!msg.noIdle;
  state.stopped = false; state.note = null; cloudFailStreak = 0; state.idle = false;
  state.lastActivity = Date.now();
  state.phase = "connecting"; announce();
  try { await bootPyodide(); } catch (e) { log("boot failed: " + (e && e.stack || e), "err"); state.phase = "off"; announce(); return; }
  // Localhost ALWAYS uses the LOCAL tunnel — the public relay only serves
  // vyomi.cloud, so a cloud attempt from localhost just 403s. Prod origins use
  // local if present, else the cloud relay.
  const localUp = await probeLocal();
  state.mode = IS_LOCAL_ORIGIN ? "local" : (localUp ? "local" : "cloud");
  localFails = 0;
  if (state.mode === "local" && !localUp) {
    log("tunnel: LOCAL — no local tunnel running yet. Localhost uses the local relay; run `vyomi-tunnel` (the public relay only serves vyomi.cloud). It connects automatically once up.", "dim");
  } else {
    log(state.mode === "local"
      ? "tunnel: LOCAL (detected — fast, private, offline)"
      : "tunnel: CLOUD (Cloudflare — no local tunnel detected)", state.mode === "local" ? "ok" : "dim");
  }
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
    else if (m.type === "noidle") { state.noIdle = !!m.on; if (state.idle && state.noIdle) start(m); }   // sign-in mid-session → cancel idle
    else if (m.type === "query") { announce(); bc.postMessage({ type: "logs", lines: logbuf.slice() }); }
  };
  // Greet the new view with current state + log history immediately.
  announce(); port.postMessage({ type: "logs", lines: logbuf.slice() });
};
