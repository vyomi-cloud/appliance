/* Booster-side connector: dials OUT over WSS to the relay with the signed session token (no inbound port on the Codespace)
 * and serves the relay's forwarded requests from the local simulator.
 *
 *   env: VYOMI_RELAY_URL              wss://relay.example/booster   (required; /booster appended if missing)
 *        VYOMI_BOOSTER_SESSION_TOKEN  the portal-signed session token (required)
 *        VYOMI_BOOSTER_LOCAL_URL      the local simulator (default http://127.0.0.1:9000)
 *        WS_PKG                       path to the `ws` package (default "ws")
 * The process exits 0 at the token's session_end (the relay closes its side at the same moment). It reconnects with
 * backoff until then, and never after.
 */
import http from "node:http";
import https from "node:https";
import net from "node:net";
import dns from "node:dns/promises";
import { execFile } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { peekSessionEnd } from "./booster-session.mjs";

const HOP = new Set(["host", "connection", "content-length", "transfer-encoding", "upgrade", "keep-alive"]);

function localRequest(base, token, m) {
  return new Promise((resolve) => {
    const u = new URL(m.path + (m.query && Object.keys(m.query).length ? "?" + new URLSearchParams(m.query) : ""), base);
    const headers = {};
    for (const [k, v] of Object.entries(m.headers || {})) if (!HOP.has(k.toLowerCase())) headers[k] = v;
    headers["x-vyomi-session-token"] = token;           // the simulator re-verifies the SAME token (core/booster_session.py)
    const body = Buffer.from(m.body || "", "base64");
    const lib = u.protocol === "https:" ? https : http;
    const rq = lib.request(u, { method: m.method, headers: { ...headers, "content-length": body.length, host: u.host } }, (r) => {
      const chunks = []; r.on("data", (c) => chunks.push(c));
      r.on("end", () => resolve({ id: m.id, status: r.statusCode, headers: r.headers, body: Buffer.concat(chunks).toString("base64") }));
    });
    rq.on("error", (e) => resolve({ id: m.id, status: 502, headers: { "content-type": "text/plain" }, body: Buffer.from("local simulator unreachable: " + e.message).toString("base64") }));
    rq.end(body);
  });
}

/** Where does VM <name> listen?  The Docker VM backend names containers  vyomi-i-<instance id>  (core/compute/backend.py) and puts
 *  them on the shared `vyomi-net`, where the agent's `link` container can reach them by Docker DNS name - so we try DNS first
 *  (no docker CLI / socket needed there), then `docker inspect` for agents that run on the host.  Returns {host, port} or null.
 *  Override with the `resolveVm` option (tests, other backends). Only these name patterns are ever tried: never arbitrary hosts. */
/** Reserved target names (docs 9b/12). They are answered by the agent itself and are never looked up as containers, so a VM
 *  can not shadow them; backends/portal must also refuse to create a VM with one of these names (isReservedName). */
export const RESERVED = new Set(["host", "codespace", "k3s"]);
export const isReservedName = (n) => RESERVED.has(String(n || "").toLowerCase());
export const ROLE_RE = /^[a-z0-9][a-z0-9-]{0,40}$/;
const parseAddr = (s, defPort) => { const m = /^(.*?)(?::(\d{1,5}))?$/.exec(String(s)); return { host: m[1], port: Number(m[2] || defPort) }; };
/** Reserved target -> {host, port, reserved} | null (not reserved) | false (reserved but not valid on this role).
 *  `host` (alias `codespace`, codespace role only) = the machine's own sshd, VYOMI_HOST_SSH_ADDR (default host.docker.internal:22);
 *  `k3s` = VYOMI_K3S_ADDR (default vyomi-k3s:6443). The client's requested port is ignored for these: they reach ONE fixed address. */
export function resolveReserved(name, role = "codespace", env = process.env) {
  const n = String(name || "").toLowerCase();
  if (n === "host" || (n === "codespace" && role === "codespace")) return { ...parseAddr(env.VYOMI_HOST_SSH_ADDR || "host.docker.internal:22", 22), reserved: "host" };
  if (n === "k3s") return { ...parseAddr(env.VYOMI_K3S_ADDR || "vyomi-k3s:6443", 6443), reserved: "k3s" };
  return n === "codespace" ? false : null;
}
export const vmCandidates = (name) => /^[A-Za-z0-9._-]{1,80}$/.test(name) && !isReservedName(name) ? [`vyomi-i-${name}`, `vyomi-${name}`, name] : [];
export async function dockerResolve(name, port = 22) {
  const cands = vmCandidates(name);
  for (const c of cands) {
    try { const r = await dns.lookup(c); if (r && r.address) return { host: c, port }; } catch { /* not a DNS name here */ }
  }
  for (const c of cands) {
    const ip = await new Promise((resolve) => execFile("docker", ["inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", c],
      { timeout: 5000 }, (err, out) => resolve(!err && String(out).trim().split(/\s+/).find(Boolean) || "")));
    if (ip) return { host: ip, port };
  }
  return null;
}

/** Start the link. Returns {stop(), done: Promise<"session_end"|"stopped">, state}. */
export function dial({ relayUrl, token, localUrl = "http://127.0.0.1:9000", WS, log = () => {}, minBackoffMs = 500, maxBackoffMs = 15000, resolveVm = dockerResolve, role = "codespace", env = process.env, audit = null }) {
  if (!ROLE_RE.test(role)) throw new Error("bad role label");
  const end = peekSessionEnd(token);
  const streams = new Map();     // sid -> net.Socket (TCP forwards to VM sshd)
  let ws = null, stopped = false, resolveDone, timer = null, endTimer = null, backoff = minBackoffMs;
  const state = { linked: false, connects: 0 };
  const done = new Promise((r) => { resolveDone = r; });
  const base = /\/booster\/?$/.test(relayUrl) ? relayUrl : relayUrl.replace(/\/$/, "") + "/booster";
  const url = base + (base.includes("?") ? "&" : "?") + "role=" + encodeURIComponent(role);
  const auditLog = audit || ((m) => log("AUDIT " + m));
  const finish = (why) => {
    if (stopped) return; stopped = true; clearTimeout(timer); clearTimeout(endTimer);
    try { ws && ws.close(1000, why); } catch { /* */ }
    state.linked = false; for (const sk of streams.values()) { try { sk.destroy(); } catch { /* */ } } streams.clear(); resolveDone(why);
  };
  if (Number.isFinite(end)) endTimer = setTimeout(() => finish("session_end"), Math.max(0, end * 1000 - Date.now()));
  const connect = () => {
    if (stopped) return;
    if (Number.isFinite(end) && Date.now() >= end * 1000) return finish("session_end");
    state.connects++;
    ws = new WS(url, { headers: { authorization: `Bearer ${token}` } });
    ws.on("open", () => { backoff = minBackoffMs; });
    ws.on("message", async (data, isBinary) => {
      if (isBinary) {                                         // [u32 sid][payload] laptop -> VM
        const sock = streams.get(data.readUInt32BE(0)); if (sock) sock.write(data.subarray(4));
        return;
      }
      let m; try { m = JSON.parse(data.toString()); } catch { return; }
      if (m.type === "tcp-open") {
        const rsv = resolveReserved(m.vm, role, env);       // checked BEFORE any container lookup; a custom resolver cannot shadow it
        if (rsv) auditLog(`open ${rsv.reserved} role=${role} target=${m.vm} -> ${rsv.host}:${rsv.port} sid=${m.sid}`);
        const target = rsv === false ? null : rsv || await resolveVm(m.vm, m.port);
        if (!target) { ws.send(JSON.stringify({ type: "tcp-error", sid: m.sid, reason: "no such VM" })); return; }
        const sock = net.connect({ host: target.host, port: target.port });
        sock.setNoDelay(true);
        streams.set(m.sid, sock);
        sock.once("connect", () => ws.send(JSON.stringify({ type: "tcp-opened", sid: m.sid })));
        sock.on("data", (d) => { const f = Buffer.allocUnsafe(4 + d.length); f.writeUInt32BE(m.sid, 0); d.copy(f, 4); if (ws.readyState === 1) ws.send(f); });
        const end = (kind) => { if (!streams.delete(m.sid)) return; try { if (ws.readyState === 1) ws.send(JSON.stringify({ type: kind, sid: m.sid })); } catch { /* */ } };
        sock.on("close", () => end("tcp-close")); sock.on("error", () => { end("tcp-error"); try { sock.destroy(); } catch { /* */ } });
        return;
      }
      if (m.type === "tcp-close") { const sock = streams.get(m.sid); if (sock) { streams.delete(m.sid); sock.end(); } return; }
      if (m.type === "linked") { state.linked = true; log("linked to relay"); return; }
      if (m.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
      if (m.id && m.method) ws.send(JSON.stringify(await localRequest(localUrl, token, m)));
    });
    const retry = () => {
      state.linked = false; for (const sk of streams.values()) { try { sk.destroy(); } catch { /* */ } } streams.clear();
      if (stopped) return;
      timer = setTimeout(connect, backoff); backoff = Math.min(maxBackoffMs, backoff * 2);
    };
    ws.on("close", retry);
    ws.on("error", () => { /* 'close' follows */ });
    ws.on("unexpected-response", (_req, res) => {            // relay refused the token / origin: do not hammer it forever
      log(`relay refused the dial: HTTP ${res.statusCode}`);
      if ([401, 403, 410].includes(res.statusCode)) finish(`refused-${res.statusCode}`);
    });
  };
  connect();
  return { stop: () => finish("stopped"), done, state };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const relayUrl = process.env.VYOMI_RELAY_URL, token = process.env.VYOMI_BOOSTER_SESSION_TOKEN;
  if (!relayUrl || !token) { console.error("booster-dial: VYOMI_RELAY_URL and VYOMI_BOOSTER_SESSION_TOKEN are required"); process.exit(2); }
  const WS = createRequire(import.meta.url)(process.env.WS_PKG || "ws");
  const link = dial({ relayUrl, token, role: process.env.VYOMI_AGENT_ROLE || "codespace", localUrl: process.env.VYOMI_BOOSTER_LOCAL_URL || "http://127.0.0.1:9000", WS,
                      log: (m) => console.log("[booster-dial] " + m) });
  link.done.then((why) => { console.log("[booster-dial] ended: " + why); process.exit(why === "session_end" || why === "stopped" ? 0 : 1); });
}
