/* Postgres wire-protocol front end for an in-browser PGlite database (Nano).
 *
 * `vyomi-tunnel` opens a host TCP port and relays the bytes into the tab (wasm/db-bridge.js); this module is the server side of that
 * socket: an unmodified psql / psycopg / pg / JDBC client connects to 127.0.0.1:5432 and talks to PGlite.
 *
 * PGlite answers typed protocol messages via db.execProtocolRaw() but not the startup packet, so this layer answers SSLRequest
 * (refused: 'N'), the StartupMessage (AuthenticationOk + server parameters + ReadyForQuery) and Terminate itself, and forwards every
 * other message verbatim.
 *
 * PGlite is ONE backend session. Several client connections are multiplexed onto it at transaction boundaries (like pgbouncer's
 * transaction pooling): a connection holds the session from its first message until the backend reports ReadyForQuery 'I' (idle).
 * Limits (honest): session state (SET, named prepared statements, temp tables) is shared between connections; credentials are not
 * checked (the listener is loopback-only).
 */

const te = new TextEncoder();
const u32 = (n) => { const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, n >>> 0); return b; };
function msg(type, ...parts) {
  let len = 4; for (const p of parts) len += p.length;
  const out = new Uint8Array(1 + len); out[0] = type.charCodeAt(0); out.set(u32(len), 1);
  let o = 5; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
const cstr = (s) => te.encode(s + "\0");
function concat(a, b) { if (!a.length) return b; const o = new Uint8Array(a.length + b.length); o.set(a); o.set(b, a.length); return o; }

export function startupReply(user, version) {
  const params = [["server_version", version || "17.0"], ["server_encoding", "UTF8"], ["client_encoding", "UTF8"], ["DateStyle", "ISO, MDY"],
    ["integer_datetimes", "on"], ["IntervalStyle", "postgres"], ["is_superuser", "on"], ["session_authorization", user || "postgres"],
    ["standard_conforming_strings", "on"], ["TimeZone", "UTC"], ["application_name", ""], ["in_hot_standby", "off"]];
  const parts = [msg("R", u32(0))];
  for (const [k, v] of params) parts.push(msg("S", cstr(k), cstr(v)));
  parts.push(msg("K", u32(Math.floor(Math.random() * 0x7fffffff)), u32(Math.floor(Math.random() * 0x7fffffff))));
  parts.push(msg("Z", te.encode("I")));
  let n = 0; for (const p of parts) n += p.length;
  const out = new Uint8Array(n); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

function errorResponse(text) {
  return concat(msg("E", te.encode("S"), cstr("FATAL"), te.encode("V"), cstr("FATAL"), te.encode("C"), cstr("53300"), te.encode("M"), cstr(text), new Uint8Array([0])),
    new Uint8Array(0));
}

/** One mutex per database: serialises sessions onto PGlite's single backend. */
export class PgLock {
  constructor() { this.holder = null; this.q = []; }
  async acquire(who) {
    if (this.holder === who) return;
    if (this.holder === null) { this.holder = who; return; }
    await new Promise((res) => this.q.push([who, res]));
  }
  release(who) {
    if (this.holder !== who) return;
    const next = this.q.shift();
    this.holder = next ? next[0] : null;
    if (next) next[1]();
  }
}

/** The state of one client connection. `getDb()` -> the PGlite object; `send(bytes)`; `close()`. */
export class PgSession {
  constructor({ getDb, lock, send, close }) {
    this.getDb = getDb; this.lock = lock; this.send = send; this.close = close;
    this.buf = new Uint8Array(0); this.started = false; this.closed = false; this.chain = Promise.resolve();
  }
  feed(chunk) {
    this.buf = concat(this.buf, chunk);
    this.chain = this.chain.then(() => this._pump()).catch(() => {});
  }
  async _pump() {
    while (!this.closed) {
      if (!this.started) {
        if (this.buf.length < 4) return;
        const dv = new DataView(this.buf.buffer, this.buf.byteOffset, this.buf.byteLength);
        const len = dv.getUint32(0);
        if (len < 8 || len > 65536) { this.send(errorResponse("invalid startup packet")); return this._end(); }
        if (this.buf.length < len) return;
        const code = dv.getUint32(4);
        const body = this.buf.slice(8, len);
        this.buf = this.buf.slice(len);
        if (code === 80877103 || code === 80877104) { this.send(te.encode("N")); continue; }   // SSLRequest / GSSENCRequest: refuse, client retries in clear
        if (code === 80877102) return this._end();                                              // CancelRequest
        if (code === 196608) {
          const kv = new TextDecoder().decode(body).split("\0");
          let user = "postgres"; for (let i = 0; i + 1 < kv.length; i += 2) if (kv[i] === "user") user = kv[i + 1];
          let ver = ""; try { const db = await this.getDb(); const r = await db.query("SHOW server_version"); ver = String(r.rows[0].server_version || ""); } catch (_) { /* default */ }
          this.started = true; this.send(startupReply(user, ver)); continue;
        }
        this.send(errorResponse("unsupported frontend protocol")); return this._end();
      }
      // typed messages: [type][int32 len][payload]; process every COMPLETE message in the buffer as one batch
      let off = 0, term = false;
      while (this.buf.length - off >= 5) {
        const len = new DataView(this.buf.buffer, this.buf.byteOffset + off + 1, 4).getUint32(0);
        if (this.buf.length - off < 1 + len) break;
        if (this.buf[off] === 0x58) { term = true; off += 1 + len; break; }   // Terminate
        off += 1 + len;
      }
      if (off === 0) return;
      const batch = this.buf.slice(0, term ? off - 5 : off);
      this.buf = this.buf.slice(off);
      if (batch.length) await this._forward(batch);
      if (term) return this._end();
    }
  }
  async _forward(batch) {
    await this.lock.acquire(this);
    let out;
    try {
      const db = await this.getDb();
      out = await db.execProtocolRaw(batch);
    } catch (e) {
      this.lock.release(this);
      this.send(errorResponse("PGlite: " + (e && e.message || e)));
      return;
    }
    if (out && out.length) this.send(out instanceof Uint8Array ? out : new Uint8Array(out));
    // release the shared backend when it reports ReadyForQuery with the idle status (no open transaction)
    if (out && out.length >= 6 && out[out.length - 6] === 0x5a && out[out.length - 1] === 0x49) this.lock.release(this);
  }
  async _end() {
    if (this.closed) return;
    this.closed = true;
    if (this.lock.holder === this) {                 // a dropped connection must not leave its transaction open
      try { const db = await this.getDb(); await db.execProtocolRaw(msg("Q", cstr("ROLLBACK"))); } catch (_) { /* nothing to roll back */ }
      this.lock.release(this);
    }
    try { this.close(); } catch (_) { /* already closed */ }
  }
  dispose() { if (!this.closed) this._end(); }
}
