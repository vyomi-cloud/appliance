// Stub of the portal's POST /api/tunnel/session: verifies the signature exactly as the contract says. Tests only.
import http from "node:http";
import { sign, sha256hex } from "../credentials.mjs";
export const KEYS = { VYKAPRO: { secret: "pro-secret", tier: "pro", allowed: true }, VYKAFREE: { secret: "free-secret", tier: "free", allowed: false },
                      VYKAREVOKED: { secret: "r", revoked: true } };
export function startStubPortal({ codespace = "vyomi-mesh-stub", sessionEnd = null, ttl = 900, github = "gho_stub", port = 0 } = {}) {
  const calls = [];
  const srv = http.createServer((req, res) => {
    const b = []; req.on("data", (d) => b.push(d)); req.on("end", () => {
      const body = Buffer.concat(b).toString(); const send = (st, o) => { res.writeHead(st, { "content-type": "application/json" }); res.end(JSON.stringify(o)); };
      const err = (st, code) => send(st, { error: { code, message: code } });
      if (req.method !== "POST" || req.url !== "/api/tunnel/session") return err(404, "NotFound");
      const id = req.headers["x-vyomi-key"], date = req.headers["x-vyomi-date"], sig = req.headers["x-vyomi-signature"]; calls.push({ id, date });
      const k = KEYS[id]; if (!k) return err(401, "InvalidAccessKey");
      if (Math.abs(Date.now() - Date.parse(date)) > 300000) return err(401, "RequestTimeSkew");
      if (sig !== sign({ secret: k.secret, method: "POST", path: "/api/tunnel/session", date, body })) return err(401, "SignatureMismatch");
      if (k.revoked) return err(403, "KeyRevoked");
      const now = Math.floor(Date.now() / 1000);
      send(200, { session: { expires_at: now + ttl, tier: k.tier, allowed: k.allowed, session_end: k.allowed ? sessionEnd : null,
        mesh: k.allowed && codespace ? { codespace, state: "Available" } : null, github: k.allowed && github ? { token: github, expires_at: now + 3600 } : null } });
    });
  });
  return new Promise((r) => srv.listen(port, "127.0.0.1", () => r({ url: `http://127.0.0.1:${srv.address().port}`, calls, close: () => srv.close() })));
}
