/* MySQL wire-protocol front end for an in-browser MySQL-family database (Nano).
 *
 * There is no MySQL/MariaDB WebAssembly build, so the data lives in sqlite and `core/mysql_dialect.py` translates MySQL SQL onto it
 * (see core/db_endpoints.py exec_json). This module is the server side of the TCP socket `vyomi-tunnel` bridges into the tab: an
 * unmodified `mysql` CLI / pymysql / mysql2 / JDBC / Go client connects to 127.0.0.1:3306 and runs queries.
 *
 * Implemented: handshake (mysql_native_password; credentials are NOT checked — the listener is loopback-only), COM_QUERY with text
 * result sets, COM_INIT_DB / PING / QUIT / FIELD_LIST / RESET_CONNECTION, and server-side prepared statements (COM_STMT_PREPARE /
 * EXECUTE / CLOSE / RESET, binary result rows). Not implemented: TLS, multi-result sets, COM_STMT_SEND_LONG_DATA, cursors, compression.
 *
 * `exec(sql)` -> Promise<{ok, columns, rows, rowcount, lastInsertId} | {ok:false, message:"ERROR 1146 (42S02): ..."}>.
 */

const te = new TextEncoder(), td = new TextDecoder();
const CAPS = 0x1 | 0x2 | 0x4 | 0x8 | 0x200 | 0x2000 | 0x8000 | 0x80000 | 0x200000;   // LONG_PASSWORD FOUND_ROWS LONG_FLAG WITH_DB PROTOCOL_41 TRANSACTIONS SECURE_CONN PLUGIN_AUTH LENENC_AUTH
const STATUS_AUTOCOMMIT = 0x0002;
const T = { TINY: 1, DOUBLE: 5, LONGLONG: 8, VAR_STRING: 253 };

function cat(...parts) { let n = 0; for (const p of parts) n += p.length; const o = new Uint8Array(n); let k = 0; for (const p of parts) { o.set(p, k); k += p.length; } return o; }
function lenenc(n) {
  if (n < 251) return Uint8Array.of(n);
  if (n < 65536) return Uint8Array.of(0xfc, n & 255, n >> 8);
  if (n < 16777216) return Uint8Array.of(0xfd, n & 255, (n >> 8) & 255, n >> 16);
  const b = new Uint8Array(9); b[0] = 0xfe; new DataView(b.buffer).setBigUint64(1, BigInt(n), true); return b;
}
const lstr = (s) => { const b = s instanceof Uint8Array ? s : te.encode(String(s)); return cat(lenenc(b.length), b); };
const le16 = (n) => Uint8Array.of(n & 255, (n >> 8) & 255);
const le32 = (n) => Uint8Array.of(n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >>> 24) & 255);
const cz = (s) => cat(te.encode(s), Uint8Array.of(0));
function packet(seq, payload) { return cat(Uint8Array.of(payload.length & 255, (payload.length >> 8) & 255, (payload.length >> 16) & 255, seq & 255), payload); }

const okPayload = (affected = 0, lastId = 0) => cat(Uint8Array.of(0), lenenc(Math.max(0, affected | 0)), lenenc(Math.max(0, Number(lastId) || 0)), le16(STATUS_AUTOCOMMIT), le16(0));
const eofPayload = () => cat(Uint8Array.of(0xfe), le16(0), le16(STATUS_AUTOCOMMIT));
function errPayload(message) {
  const m = /^ERROR (\d+) \(([0-9A-Z]{5})\): (.*)$/s.exec(String(message || ""));
  const errno = m ? Number(m[1]) : 1105, state = m ? m[2] : "HY000", text = m ? m[3] : String(message || "error");
  return cat(Uint8Array.of(0xff), le16(errno), te.encode("#" + state), te.encode(text));
}

function colType(rows, i) {
  let t = null;
  for (const r of rows) {
    const v = r[i]; if (v === null || v === undefined) continue;
    if (typeof v === "number") { const cand = Number.isInteger(v) ? T.LONGLONG : T.DOUBLE; t = t === null ? cand : (t === cand ? t : (t === T.VAR_STRING ? t : T.DOUBLE)); }
    else if (typeof v === "boolean") { t = t === null ? T.LONGLONG : t; }
    else return T.VAR_STRING;
  }
  return t === null ? T.VAR_STRING : t;
}
function colDef(name, type) {
  const str = type === T.VAR_STRING;
  return cat(lstr("def"), lstr(""), lstr(""), lstr(""), lstr(name), lstr(name), Uint8Array.of(0x0c), le16(str ? 45 : 63), le32(str ? 1020 : (type === T.DOUBLE ? 22 : 20)),
    Uint8Array.of(type), le16(str ? 0 : 0x80), Uint8Array.of(type === T.DOUBLE ? 31 : 0), Uint8Array.of(0, 0));
}
const asText = (v) => (typeof v === "boolean" ? (v ? "1" : "0") : String(v));
function textRow(row, n) { const ps = []; for (let i = 0; i < n; i++) { const v = row[i]; ps.push(v === null || v === undefined ? Uint8Array.of(0xfb) : lstr(asText(v))); } return cat(...ps); }
function binaryRow(row, types) {
  const n = types.length, bm = new Uint8Array((n + 9) >> 3), ps = [];
  for (let i = 0; i < n; i++) {
    const v = row[i];
    if (v === null || v === undefined) { const bit = i + 2; bm[bit >> 3] |= 1 << (bit & 7); continue; }
    if (types[i] === T.LONGLONG) { const b = new Uint8Array(8); new DataView(b.buffer).setBigInt64(0, BigInt(typeof v === "boolean" ? (v ? 1 : 0) : Math.trunc(Number(v))), true); ps.push(b); }
    else if (types[i] === T.DOUBLE) { const b = new Uint8Array(8); new DataView(b.buffer).setFloat64(0, Number(v), true); ps.push(b); }
    else ps.push(lstr(asText(v)));
  }
  return cat(Uint8Array.of(0), bm, ...ps);
}

function placeholderCount(sql) {
  let n = 0, i = 0;
  while (i < sql.length) {
    const c = sql[i];
    if (c === "'" || c === '"' || c === "`") { const q = c; i++; while (i < sql.length && sql[i] !== q) { if (sql[i] === "\\" && q !== "`") i++; i++; } i++; continue; }
    if (c === "-" && sql[i + 1] === "-") { while (i < sql.length && sql[i] !== "\n") i++; continue; }
    if (c === "#") { while (i < sql.length && sql[i] !== "\n") i++; continue; }
    if (c === "/" && sql[i + 1] === "*") { const e = sql.indexOf("*/", i + 2); i = e < 0 ? sql.length : e + 2; continue; }
    if (c === "?") n++;
    i++;
  }
  return n;
}
function literal(v) {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "number" || typeof v === "bigint") return String(v);
  if (v instanceof Uint8Array) return "X'" + Array.from(v, (b) => b.toString(16).padStart(2, "0")).join("") + "'";
  return "'" + String(v).replace(/\\/g, "\\\\").replace(/'/g, "''") + "'";
}
function fillPlaceholders(sql, params) {
  let out = "", k = 0, i = 0;
  while (i < sql.length) {
    const c = sql[i];
    if (c === "'" || c === '"' || c === "`") { const q = c; let j = i + 1; while (j < sql.length && sql[j] !== q) { if (sql[j] === "\\" && q !== "`") j++; j++; } out += sql.slice(i, j + 1); i = j + 1; continue; }
    if (c === "?") { out += literal(params[k++]); i++; continue; }
    out += c; i++;
  }
  return out;
}

class Reader {
  constructor(b) { this.b = b; this.o = 0; this.dv = new DataView(b.buffer, b.byteOffset, b.byteLength); }
  u8() { return this.b[this.o++]; }
  u16() { const v = this.dv.getUint16(this.o, true); this.o += 2; return v; }
  u32() { const v = this.dv.getUint32(this.o, true); this.o += 4; return v; }
  lenenc() { const f = this.u8(); if (f < 251) return f; if (f === 0xfc) return this.u16(); if (f === 0xfd) { const v = this.b[this.o] | (this.b[this.o + 1] << 8) | (this.b[this.o + 2] << 16); this.o += 3; return v; } const v = Number(this.dv.getBigUint64(this.o, true)); this.o += 8; return v; }
  bytes(n) { const v = this.b.slice(this.o, this.o + n); this.o += n; return v; }
  lstr() { return td.decode(this.bytes(this.lenenc())); }
  cstr() { let e = this.o; while (e < this.b.length && this.b[e] !== 0) e++; const v = td.decode(this.b.slice(this.o, e)); this.o = e + 1; return v; }
  left() { return this.b.length - this.o; }
}

function readParam(r, type, unsigned) {
  switch (type) {
    case 0x06: return null;
    case 0x01: return unsigned ? r.u8() : (r.u8() << 24) >> 24;
    case 0x02: case 0x0d: { const v = r.u16(); return unsigned ? v : (v << 16) >> 16; }
    case 0x03: case 0x09: { const v = r.u32(); return unsigned ? v : v | 0; }
    case 0x08: { const v = r.dv.getBigInt64(r.o, true), u = r.dv.getBigUint64(r.o, true); r.o += 8; const x = unsigned ? u : v; return x >= -9007199254740991n && x <= 9007199254740991n ? Number(x) : x; }
    case 0x04: { const v = r.dv.getFloat32(r.o, true); r.o += 4; return v; }
    case 0x05: { const v = r.dv.getFloat64(r.o, true); r.o += 8; return v; }
    case 0x07: case 0x0a: case 0x0c: {
      const len = r.u8(); if (len === 0) return "0000-00-00 00:00:00";
      const y = r.u16(), mo = r.u8(), d = r.u8(); let h = 0, mi = 0, s = 0, us = 0;
      if (len >= 7) { h = r.u8(); mi = r.u8(); s = r.u8(); } if (len >= 11) us = r.u32();
      const p = (n, w = 2) => String(n).padStart(w, "0");
      return `${p(y, 4)}-${p(mo)}-${p(d)}` + (type === 0x0a ? "" : ` ${p(h)}:${p(mi)}:${p(s)}` + (us ? "." + p(us, 6) : ""));
    }
    case 0x0b: { const len = r.u8(); if (len === 0) return "00:00:00"; const neg = r.u8(), days = r.u32(), h = r.u8(), mi = r.u8(), s = r.u8(); if (len > 8) r.u32(); const p = (n) => String(n).padStart(2, "0"); return (neg ? "-" : "") + p(days * 24 + h) + ":" + p(mi) + ":" + p(s); }
    case 0xfc: case 0xfb: case 0xfa: case 0xf9: return r.bytes(r.lenenc());                 // BLOBs -> bytes
    default: return r.lstr();                                                              // VARCHAR / STRING / DECIMAL / JSON ...
  }
}

export class MySqlSession {
  constructor({ exec, send, close, version = "8.0.36", database = "", connectionId = 1 }) {
    this.exec = exec; this.sendRaw = send; this.close = close; this.version = version; this.db = database; this.cid = connectionId;
    this.buf = new Uint8Array(0); this.phase = "new"; this.stmts = new Map(); this.nextStmt = 1; this.chain = Promise.resolve(); this.closed = false;
  }
  start() {
    const salt = new Uint8Array(20); crypto.getRandomValues(salt);
    const payload = cat(Uint8Array.of(10), cz(this.version + "-Vyomi"), le32(this.cid), salt.slice(0, 8), Uint8Array.of(0), le16(CAPS & 0xffff), Uint8Array.of(45),
      le16(STATUS_AUTOCOMMIT), le16(CAPS >>> 16), Uint8Array.of(21), new Uint8Array(10), salt.slice(8), Uint8Array.of(0), cz("mysql_native_password"));
    this.send(1 - 1, payload);
    this.phase = "auth";
  }
  send(seq, payload) { this.sendRaw(packet(seq, payload)); }
  feed(chunk) {
    this.buf = cat(this.buf, chunk);
    for (;;) {
      if (this.buf.length < 4) return;
      const len = this.buf[0] | (this.buf[1] << 8) | (this.buf[2] << 16);
      if (this.buf.length < 4 + len) return;
      const seq = this.buf[3], payload = this.buf.slice(4, 4 + len);
      this.buf = this.buf.slice(4 + len);
      this.chain = this.chain.then(() => this._packet(seq, payload)).catch((e) => { try { this.send(1, errPayload("ERROR 1105 (HY000): " + (e && e.message || e))); } catch (_) { /* closed */ } });
    }
  }
  async _packet(seq, p) {
    if (this.closed) return;
    if (this.phase === "auth") {
      try {
        const r = new Reader(p); const caps = r.u32(); r.u32(); r.u8(); r.bytes(23); r.cstr();
        if (caps & 0x200000) r.bytes(r.lenenc()); else if (caps & 0x8000) r.bytes(r.u8()); else r.cstr();
        if (caps & 0x8) { const d = r.cstr(); if (d) this.db = d; }
      } catch (_) { /* tolerate odd clients: credentials are not checked */ }
      this.phase = "cmd"; this.send(seq + 1, okPayload()); return;
    }
    if (this.phase !== "cmd") return;
    const cmd = p[0];
    switch (cmd) {
      case 0x01: this.closed = true; try { this.close(); } catch (_) { /* gone */ } return;
      case 0x02: this.db = td.decode(p.slice(1)); this.send(1, okPayload()); return;
      case 0x0e: case 0x1a: case 0x1f: this.send(1, okPayload()); return;
      case 0x04: this.send(1, eofPayload()); return;
      case 0x1b: this.send(1, eofPayload()); return;
      case 0x03: return this._query(td.decode(p.slice(1)), false, null);
      case 0x16: return this._prepare(td.decode(p.slice(1)));
      case 0x17: return this._execute(p);
      case 0x19: { const id = new DataView(p.buffer, p.byteOffset, p.byteLength).getUint32(1, true); this.stmts.delete(id); return; }
      default: this.send(1, errPayload("ERROR 1047 (08S01): Unknown command"));
    }
  }
  async _query(sql, binary) {
    const res = await this.exec(sql);
    if (!res || !res.ok) { this.send(1, errPayload(res && res.message)); return; }
    if (!res.columns || res.columns.length === 0) { this.send(1, okPayload(res.rowcount, res.lastInsertId)); return; }
    const n = res.columns.length, types = res.columns.map((_, i) => colType(res.rows, i));
    let seq = 1; const out = [];
    out.push(packet(seq++, lenenc(n)));
    for (let i = 0; i < n; i++) out.push(packet(seq++, colDef(String(res.columns[i]), types[i])));
    out.push(packet(seq++, eofPayload()));
    for (const row of res.rows) out.push(packet(seq++, binary ? binaryRow(row, types) : textRow(row, n)));
    out.push(packet(seq++, eofPayload()));
    this.sendRaw(cat(...out));
  }
  _prepare(sql) {
    const id = this.nextStmt++, n = placeholderCount(sql);
    this.stmts.set(id, { sql, n, types: null });
    const head = cat(Uint8Array.of(0), le32(id), le16(0), le16(n), Uint8Array.of(0), le16(0));
    let seq = 1; const out = [packet(seq++, head)];
    if (n > 0) { for (let i = 0; i < n; i++) out.push(packet(seq++, colDef("?", T.VAR_STRING))); out.push(packet(seq++, eofPayload())); }
    this.sendRaw(cat(...out));
  }
  async _execute(p) {
    const r = new Reader(p); r.u8(); const id = r.u32(); r.u8(); r.u32();
    const st = this.stmts.get(id);
    if (!st) { this.send(1, errPayload("ERROR 1243 (HY000): Unknown prepared statement handler (" + id + ") given to mysqld_stmt_execute")); return; }
    const params = [];
    if (st.n > 0) {
      const nb = r.bytes((st.n + 7) >> 3), bound = r.u8();
      if (bound === 1) { st.types = []; for (let i = 0; i < st.n; i++) { const t = r.u8(), f = r.u8(); st.types.push([t, (f & 0x80) !== 0]); } }
      for (let i = 0; i < st.n; i++) {
        if (nb[i >> 3] & (1 << (i & 7))) { params.push(null); continue; }
        const [t, u] = (st.types && st.types[i]) || [0xfd, false];
        params.push(readParam(r, t, u));
      }
    }
    return this._query(fillPlaceholders(st.sql, params), true);
  }
  dispose() { this.closed = true; }
}
