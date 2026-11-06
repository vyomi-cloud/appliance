/* Vyomi-Nano — PGlite engine loader (browser side of the RDS data-plane swap).
 *
 * The RDS data plane runs behind the SqlStore seam (core/sql_store.py). The Nano
 * default engine is stdlib sqlite3 (real SQL, runs in Pyodide). PGliteSqlStore
 * swaps in REAL Postgres (Postgres compiled to WASM) for genuine dialect/wire
 * fidelity — `$1` placeholders, SERIAL, RETURNING, ILIKE, real types — so an
 * unmodified Postgres-SQL app validates against the in-browser sim faithfully.
 *
 * PGlite is async; the Python engine (PGliteSqlStore.aexecute_sql) awaits a
 * factory the page must install on `globalThis`:
 *
 *     globalThis.__nano_pglite_new : async () => <a fresh PGlite database>
 *
 * This is the EXACT contract proven by tests/conformance/test_rds_pglite_core.py
 * (run_pglite) on real Pyodide. Call installPGlite() once during boot BEFORE the
 * RDS data plane runs; it's idempotent and lazy (the heavy WASM only loads when a
 * database is actually created).
 *
 * Returns true if the factory is installed, false if PGlite couldn't be loaded
 * (the caller should then keep the sqlite3 engine — never a hard failure).
 */
const PGLITE_URL = "https://cdn.jsdelivr.net/npm/@electric-sql/pglite/dist/index.js";

export async function installPGlite(url = PGLITE_URL) {
  if (typeof globalThis.__nano_pglite_new === "function") return true;  // idempotent
  try {
    const { PGlite } = await import(url);
    // One PGlite database per RDS instance id (the engine calls this per-instance).
    globalThis.__nano_pglite_new = async (dbId) => {
      const db = await PGlite.create();
      if (dbId) startBridge(String(dbId), db);
      return db;
    };
    globalThis.__nano_pg_endpoint = (dbId) => bridgePort(String(dbId));
    globalThis.__nano_pg_close = (dbId) => stopBridge(String(dbId));
    globalThis.__nano_pg_sync = (ns, keys) => { const keep = new Set(Array.from(keys || []).map(String));
      for (const k of Array.from(_bridges.keys())) if (k.startsWith(ns + "/") && !keep.has(k)) stopBridge(k); };
    return true;
  } catch (e) {
    console.warn("[nano] PGlite unavailable, RDS keeps the sqlite3 engine:", String(e));
    return false;
  }
}


/* ── Host access to in-browser Postgres ───────────────────────────────────────────────────────────
 * Each PGlite database is published on a host TCP port through the local `vyomi-tunnel` relay's
 * generic /vm bridge (the same one that carries ssh to Nano VMs): psql / any Postgres driver connects to
 * 127.0.0.1:<port>, the relay forwards the raw wire bytes over a WebSocket, and we hand them to PGlite
 * (execProtocolRawStream). Connections are served one query at a time (PGlite is single-session).
 * Without a reachable tunnel nothing is published and the bridge retries quietly. */
const SSL_REQUEST = 80877103;
const _bridges = new Map();   // dbId -> {ws, port, waiters, closed, timer}
function _relayWsBase() {
  let ext = ""; try { ext = (globalThis.localStorage && localStorage.getItem("nano_local_ext")) || ""; } catch (_) {}   // same setting db-bridge.js uses
  return (globalThis.__nano_local_ws_base || (ext ? ext.replace(/^http/, "ws") : "ws://127.0.0.1:8090")).replace(/\/$/, "");
}
function startBridge(dbId, db) {
  if (typeof WebSocket === "undefined" || _bridges.has(dbId)) return;
  const b = { ws: null, port: 0, waiters: [], closed: false, timer: null, chains: new Map() };
  _bridges.set(dbId, b);
  const vm = "db-" + dbId.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 70);
  const connect = () => {
    if (b.closed) return;
    let ws;
    try { ws = new WebSocket(_relayWsBase() + "/vm?vm=" + encodeURIComponent(vm) + "&port=5432&prefer=" + (b.port || 0)); }
    catch (_) { b.timer = setTimeout(connect, 8000); return; }
    ws.binaryType = "arraybuffer";
    b.ws = ws;
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
        if (m.type === "vm-listening") { b.port = m.host_port; b.waiters.splice(0).forEach((f) => f(b.port));
          if (typeof globalThis.__nano_pg_on_port === "function") { try { globalThis.__nano_pg_on_port(dbId, b.port); } catch (_) {} }
          setTimeout(() => { try { globalThis.__nano_stores_dirty && globalThis.__nano_stores_dirty(); } catch (_) {} }, 300); }
        else if (m.type === "tcp-open") ws.send(JSON.stringify({ type: "tcp-opened", sid: m.sid }));
        else if (m.type === "tcp-close") b.chains.delete(m.sid);
        else if (m.type === "ping") ws.send(JSON.stringify({ type: "pong" }));
        return;
      }
      const dv = new DataView(ev.data), sid = dv.getUint32(0), msg = new Uint8Array(ev.data, 4);
      const send = (chunk) => { const f = new Uint8Array(4 + chunk.length); new DataView(f.buffer).setUint32(0, sid); f.set(chunk, 4); try { ws.send(f); } catch (_) {} };
      const prev = b.chains.get(sid) || Promise.resolve();
      b.chains.set(sid, prev.then(async () => {
        if (msg.length === 8 && new DataView(msg.buffer, msg.byteOffset).getUint32(4) === SSL_REQUEST) return send(Uint8Array.of(0x4e)); // 'N': no TLS
        await db.runExclusive(async () => { await db.execProtocolRawStream(msg.slice(), { onRawData: send }); });
      }).catch(() => {}));
    };
    ws.onclose = () => { b.ws = null; b.chains.clear(); if (!b.closed) b.timer = setTimeout(connect, 8000); };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  };
  connect();
}
function bridgePort(dbId) {
  const b = _bridges.get(dbId);
  if (!b) return Promise.resolve(0);
  if (b.port) return Promise.resolve(b.port);
  return new Promise((res) => { b.waiters.push(res); setTimeout(() => res(b.port || 0), 4000); });
}
function stopBridge(dbId) {
  const b = _bridges.get(dbId); if (!b) return;
  b.closed = true; clearTimeout(b.timer); try { b.ws && b.ws.close(); } catch (_) {}
  _bridges.delete(dbId);
}
