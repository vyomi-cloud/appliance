// Mesh plane for the user's own `vyomi-tunnel` (no args): the link runs on the LAPTOP (docs/architecture/v4.0/VYOMI-TUNNEL-ARCHITECTURE.md §1c),
// so the Nano console reaches the Mesh through this local relay with no hosted relay and no MESH_RELAY_URL.
//
// The ssh session to the Codespace is opened lazily, on the FIRST Mesh request (an X-Vyomi-Session-Token call, /shell or /connect): Nano-only
// and Free users never open one. It needs the user's Vyomi access key (Mesh = Pro/Max) and a running Mesh Codespace; both are checked by
// openMesh(). When the Mesh session ends the hub is dropped, and the next request opens a fresh one.
import { createSshHub } from "./mesh-ssh.mjs";

export function createLazySshHub({ WebSocketServer, WebSocket, openMesh, currentCodespace = null, recheckMs = 30000, log = () => {}, retryMs = 15000, now = Date.now } = {}) {
  let hub = null, pending = null, failed = null;          // failed: {at, err}
  let hubCs = null, checkedAt = 0;                         // the Codespace this link was opened for; when we last re-checked it
  const drop = () => { const h = hub; hub = null; hubCs = null; try { h && h.close(); } catch { /* */ } };
  // A Mesh restart creates a NEW Codespace. A relay that keeps running must not keep talking to the dead one: while there is Mesh traffic,
  // re-read the account's current Codespace (at most every recheckMs, from a fresh signed session) and drop the link when it changed or the
  // Mesh session is over. The next request then opens a fresh link.
  async function fresh() {
    if (!hub || !currentCodespace || now() - checkedAt < recheckMs) return;
    checkedAt = now();
    let r; try { r = await currentCodespace({ log }); } catch { return; }
    if (r && (r.error === "SessionEnded" || (r.codespace && hubCs && r.codespace !== hubCs))) {
      log(r.error ? "your Mesh session has ended." : `Mesh moved to a new Codespace (${r.codespace}); reconnecting.`); drop(); failed = null;
    }
  }
  const stale = () => { checkedAt = 0; setTimeout(drop, 0); };   // the simulator stream failed: don't keep a possibly dead link
  function ensure() {
    return fresh().then(() => hub ? hub : open());
  }
  function open() {
    if (failed && now() - failed.at < retryMs) return Promise.reject(failed.err);       // don't hammer the portal / gh on every poll
    if (!pending) {
      pending = (async () => {
        const o = await openMesh({ log });
        if (o.error) { const e = new Error(o.error); e.code = o.code || "MeshUnavailable"; throw e; }
        o.transport.onStop(() => { log("your Mesh session has ended."); drop(); });
        hub = createSshHub({ WebSocketServer, WebSocket, transport: o.transport, log });
        hubCs = (o.sess && o.sess.codespace) || o.transport.codespace || null; checkedAt = now();
        failed = null;
        return hub;
      })().catch((e) => { failed = { at: now(), err: e }; throw e; }).finally(() => { pending = null; });
    }
    return pending;
  }
  const refuse = (socket, status, code) => { try { socket.write(`HTTP/1.1 ${status} ${code}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); } catch { /* */ } socket.destroy(); };
  return {
    enabled: () => !!hub,
    linked: () => (hub ? hub.linked() : []),
    streams: () => (hub ? hub.streams() : 0),
    close: drop,
    /** Mesh plane = HTTP carrying X-Vyomi-Session-Token (the Nano console's compute/AI calls). Anything else is the relay's own business. */
    http(req, res, body) {
      if (req.headers["x-vyomi-session-token"] === undefined) return false;
      const wh = res.writeHead.bind(res); res.writeHead = (st, ...a) => { if (st === 502) stale(); return wh(st, ...a); };
      ensure().then((h) => h.http(req, res, body)).catch((e) => {
        if (res.headersSent) return;
        res.writeHead(e.code === "PlanNotAllowed" ? 403 : 503, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: { ok: false, code: e.code || "MeshUnavailable", reason: String(e.message).slice(0, 200) } }));
      });
      return true;
    },
    upgrade: (_q, socket) => { refuse(socket, 410, "MeshLinkNotUsed"); return true; },
    shellUpgrade(req, socket, head) { ensure().then((h) => h.shellUpgrade(req, socket, head)).catch(() => refuse(socket, 503, "MeshUnavailable")); return true; },
    connectUpgrade(req, socket, head) { ensure().then((h) => h.connectUpgrade(req, socket, head)).catch(() => refuse(socket, 503, "MeshUnavailable")); return true; },
  };
}
