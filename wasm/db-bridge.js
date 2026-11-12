/* Host access to in-browser databases (Nano) — the browser half of `vyomi-tunnel`'s /db bridge.
 *
 * A browser tab cannot listen on a TCP port, so for every available database instance (RDS, Cloud SQL) this opens one WebSocket to the
 * local tunnel (`GET /db?db=<id>&engine=postgres|mysql`). The tunnel listens on the host (the engine's standard port when free:
 * 5432 / 3306) and relays each accepted TCP connection as a stream. Each stream is served here by a wire-protocol front end:
 *   postgres -> wasm/db-wire-pg.js    (PGlite, real Postgres)
 *   mysql    -> wasm/db-wire-mysql.js (sqlite behind core/mysql_dialect; there is no MySQL WebAssembly build)
 * so `psql`, `mysql`, psycopg, pg, pymysql, mysql2, JDBC and ORMs connect to 127.0.0.1 unchanged.
 *
 * Loaded by every context that owns the Pyodide stores (nano-boot.js, relay-shared-worker.js, nano-endpoint.html); a Web Lock makes
 * sure only ONE context runs the bridge at a time (another takes over if it dies).
 *
 * Tunnel framing (same as the VM SSH bridge): JSON control frames {tcp-open, tcp-opened, tcp-close, ping/pong, vm-listening};
 * binary frames are [u32 stream id][payload].
 */
import { PgSession, PgLock } from "./db-wire-pg.js";
import { MySqlSession } from "./db-wire-mysql.js";

const DEFAULT_PORT = { postgres: 5432, mysql: 3306 };
const POLL_MS = 5000;

function tunnelBase() {
  try { return (globalThis.localStorage && localStorage.getItem("nano_local_ext") || "http://127.0.0.1:8090").replace(/\/$/, ""); } catch (_) { return "http://127.0.0.1:8090"; }
}
const safeId = (key) => String(key).replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 80);

export function installDbBridge(py, opts = {}) {
  if (globalThis.__nano_db_bridge) return globalThis.__nano_db_bridge;
  let dbe;
  try { dbe = py.runPython("import sys\nif '/' not in sys.path: sys.path.insert(0, '/')\nfrom core import db_endpoints as _dbe\n_dbe"); } catch (e) { console.warn("[nano] db bridge: db_endpoints unavailable:", e); return null; }

  const base = opts.base || tunnelBase();
  const eps = new Map();            // key -> {ws, engine, label, hostPort, streams, lock, dbPromise, prefer}
  const hostPorts = (globalThis.__nano_db_hostports = globalThis.__nano_db_hostports || {});
  let stopped = false, connId = 1;

  const listEndpoints = () => { try { return JSON.parse(dbe.list_json()); } catch (_) { return []; } };
  const execJson = async (key, sql) => { try { return JSON.parse(await dbe.exec_json(key, sql)); } catch (e) { return { ok: false, message: "ERROR 1105 (HY000): " + (e && e.message || e) }; } };

  function openEndpoint(ep) {
    const prior = eps.get(ep.key);
    const e = { ws: null, engine: ep.engine, label: ep.label, hostPort: prior ? prior.hostPort : 0, streams: new Map(), lock: new PgLock(), dbPromise: null, ep };
    eps.set(ep.key, e);
    const url = base.replace(/^http/, "ws") + `/db?db=${encodeURIComponent(safeId(ep.key))}&engine=${ep.engine}&port=${DEFAULT_PORT[ep.engine]}&prefer=${e.hostPort || DEFAULT_PORT[ep.engine]}`;
    let ws;
    try { ws = new WebSocket(url); } catch (_) { eps.delete(ep.key); return; }
    ws.binaryType = "arraybuffer";
    e.ws = ws;
    const frame = (sid, bytes) => { const out = new Uint8Array(4 + bytes.length); new DataView(out.buffer).setUint32(0, sid); out.set(bytes, 4); try { ws.send(out); } catch (_) { /* socket gone */ } };
    const closeStream = (sid, notify) => { const s = e.streams.get(sid); if (!s) return; e.streams.delete(sid); try { s.dispose(); } catch (_) { /* done */ } if (notify) { try { ws.send(JSON.stringify({ type: "tcp-close", sid })); } catch (_) { /* gone */ } } };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        const dv = new DataView(ev.data), sid = dv.getUint32(0), s = e.streams.get(sid);
        if (s) s.feed(new Uint8Array(ev.data, 4).slice());
        return;
      }
      let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
      if (m.type === "ping") { try { ws.send(JSON.stringify({ type: "pong" })); } catch (_) { /* gone */ } return; }
      if (m.type === "vm-listening") { e.hostPort = m.host_port; hostPorts[ep.key] = { engine: ep.engine, host: "127.0.0.1", port: m.host_port, label: ep.label, user: ep.user, database: ep.database }; try { globalThis.dispatchEvent && globalThis.dispatchEvent(new Event("nano-db-hostports")); } catch (_) { /* no events here */ } return; }
      if (m.type === "tcp-close") { closeStream(m.sid, false); return; }
      if (m.type !== "tcp-open") return;
      const sid = m.sid, send = (b) => frame(sid, b), close = () => closeStream(sid, true);
      let session;
      if (ep.engine === "postgres") {
        const getDb = () => (e.dbPromise = e.dbPromise || dbe.pg_handle(ep.key).then((d) => { if (!d) throw new Error("this instance's engine is not PGlite"); return d; }, (er) => { e.dbPromise = null; throw er; }));
        session = new PgSession({ getDb, lock: e.lock, send, close });
      } else {
        session = new MySqlSession({ exec: (sql) => execJson(ep.key, sql), send, close, version: (ep.version && /^\d/.test(ep.version) ? ep.version : "8.0.36"), database: ep.database || "", connectionId: connId++ });
      }
      e.streams.set(sid, session);
      try { ws.send(JSON.stringify({ type: "tcp-opened", sid })); } catch (_) { /* gone */ }
      if (session.start) session.start();
    };
    ws.onclose = () => { for (const sid of [...e.streams.keys()]) closeStream(sid, false); if (eps.get(ep.key) === e) { eps.delete(ep.key); delete hostPorts[ep.key]; } };
    ws.onerror = () => { try { ws.close(); } catch (_) { /* closed */ } };
  }

  async function tick() {
    if (stopped) return;
    let feats = null;
    try { const r = await fetch(base + "/health", { signal: AbortSignal.timeout(1500) }); if (r.ok) feats = (await r.json()).features || []; } catch (_) { /* no tunnel */ }
    if (!feats || !feats.includes("db-tcp")) { for (const [k, e] of eps) { try { e.ws.close(); } catch (_) { /* closed */ } eps.delete(k); delete hostPorts[k]; } return; }
    const want = listEndpoints(), keys = new Set(want.map((w) => w.key));
    for (const [k, e] of eps) if (!keys.has(k)) { try { e.ws.close(); } catch (_) { /* closed */ } eps.delete(k); delete hostPorts[k]; }
    for (const ep of want) if (!eps.has(ep.key)) openEndpoint(ep);
  }

  const start = () => { tick(); const t = setInterval(tick, POLL_MS); return () => { stopped = true; clearInterval(t); for (const e of eps.values()) { try { e.ws.close(); } catch (_) { /* closed */ } } }; };
  let stop = null;
  if (globalThis.navigator && navigator.locks) {
    navigator.locks.request("vyomi-db-bridge", { mode: "exclusive" }, () => new Promise((resolve) => { stopped = false; stop = start(); globalThis.addEventListener && globalThis.addEventListener("pagehide", () => { if (stop) stop(); resolve(); }); }));
  } else stop = start();
  const api = { eps, hostPorts, tick, stop: () => stop && stop() };
  globalThis.__nano_db_bridge = api;
  return api;
}
