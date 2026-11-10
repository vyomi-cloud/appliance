/* Mesh session token (same format as core/mesh_session.py):
 *   v1.<b64url(payload-json)>.<b64url(HMAC-SHA256(key, "v1." + b64url(payload-json)))>
 * payload: {aud:"vyomi-mesh-session", sub, tier, primary_cloud, session_id, iat, session_end(epoch s)}
 */
import crypto from "node:crypto";

export const AUD = "vyomi-mesh-session";
const SKEW_S = 30;

export class SessionError extends Error {
  constructor(code, message, status = 401) { super(`${code}: ${message}`); this.code = code; this.status = status; }
}
const b64 = (buf) => Buffer.from(buf).toString("base64url");

export function mint(key, { sub = "acct", tier = "pro", primary_cloud = "", session_id = "s1", session_end, iat, role, model }) {
  const payload = { aud: AUD, sub, tier, primary_cloud, session_id, iat: Math.floor(iat ?? Date.now() / 1000), session_end: Math.floor(session_end) };
  if (role) payload.role = role;
  if (model) payload.model = model;
  const body = b64(JSON.stringify(payload));
  return `v1.${body}.${b64(crypto.createHmac("sha256", key).update(`v1.${body}`).digest())}`;
}

/** Verify and return claims, or throw SessionError. `nowS` is epoch seconds. */
export function verify(token, key, nowS = Date.now() / 1000) {
  if (!key) throw new SessionError("MeshSessionKeyMissing", "no session key configured", 503);
  const parts = String(token || "").trim().split(".");
  if (parts.length !== 3 || parts[0] !== "v1") throw new SessionError("MeshSessionMalformed", "malformed session token");
  let got; try { got = Buffer.from(parts[2], "base64url"); } catch { got = Buffer.alloc(0); }
  const sigOk = (k) => { const want = crypto.createHmac("sha256", k).update(`v1.${parts[1]}`).digest(); return got.length === want.length && crypto.timingSafeEqual(got, want); };
  let c; try { c = JSON.parse(Buffer.from(parts[1], "base64url").toString()); } catch { c = null; }
  // The portal signs each token with a PER-SESSION key = hex(HMAC(master, "session:<id>")) (app/mesh_session.py session_key), so a
  // compromised codespace only learns its own key. The relay holds the MASTER key: accept a token signed directly with `key`
  // (tests, single-session meshes), else re-derive the per-session key from the payload's session_id and verify with that.
  if (!sigOk(key)) {
    const sid = c && c.session_id ? String(c.session_id) : "";
    const derived = sid ? crypto.createHmac("sha256", key).update(`session:${sid}`).digest("hex") : "";
    if (!derived || !sigOk(derived)) throw new SessionError("MeshSessionBadSignature", "bad signature");
  }
  if (!c) throw new SessionError("MeshSessionMalformed", "unreadable payload");
  if (c.aud !== AUD) throw new SessionError("MeshSessionBadAudience", "not a mesh session token");
  const end = Number(c.session_end);
  if (!Number.isFinite(end)) throw new SessionError("MeshSessionMalformed", "missing session_end");
  if (Number(c.iat || 0) > nowS + SKEW_S) throw new SessionError("MeshSessionNotYetValid", "issued in the future");
  if (nowS >= end) throw new SessionError("MeshSessionExpired", "the mesh session has ended", 410);
  if (!["pro", "max", "enterprise"].includes(String(c.tier || "").toLowerCase())) throw new SessionError("MeshTierNotEligible", "mesh needs Pro or Max", 403);
  if (!c.session_id) throw new SessionError("MeshSessionMalformed", "missing session_id");
  return c;
}

/** Unverified peek at session_end (the mesh side only schedules its own shutdown with it; the relay is the verifier). */
export function peekSessionEnd(token) {
  try { return Number(JSON.parse(Buffer.from(String(token).split(".")[1], "base64url").toString()).session_end); } catch { return NaN; }
}
