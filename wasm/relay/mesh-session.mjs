/* Mesh session token (same format as core/mesh_session.py):
 *   v1.<b64url(payload-json)>.<b64url(HMAC-SHA256(key, "v1." + b64url(payload-json)))>
 *   v2.<b64url(payload-json incl. kid)>.<b64url(Ed25519 signature over "v2." + b64url(payload-json))>
 * payload: {aud:"vyomi-mesh-session", sub, tier, primary_cloud, session_id, iat, session_end(epoch s)}
 * v2 is verified with the portal's PINNED public keys below (never from env/files); v1 only while V1_ACCEPTED.
 * Rollout and why: docs/architecture/v4.0/MESH-SESSION-ED25519.md (MCP-GUARDRAILS finding F2).
 */
import crypto from "node:crypto";

export const AUD = "vyomi-mesh-session";
// Same set as core/mesh_session.py TRUSTED_KEYS (tests/test_mesh_session_v2.py checks they match): kid -> base64url raw 32-byte key.
export const TRUSTED_KEYS = Object.freeze({
  "portal-2026-11": "gFxVrZy9w3W4r-qhGzAW-nkN0vUrUF6tnzSeAqCovrM",
});
// Same as core/mesh_session.py V1_ACCEPTED. A code constant: an env switch would let a Codespace owner reopen F2.
export const V1_ACCEPTED = true;
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

const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");   // DER header for a raw 32-byte Ed25519 public key

/** v2 minting (tests; the portal mints in production). `privateKey` is a node KeyObject or PEM for an Ed25519 key. */
export function mintV2(privateKey, kid, { sub = "acct", tier = "pro", primary_cloud = "", session_id = "s1", session_end, iat, role, model }) {
  const payload = { aud: AUD, kid, sub, tier, primary_cloud, session_id, iat: Math.floor(iat ?? Date.now() / 1000), session_end: Math.floor(session_end) };
  if (role) payload.role = role;
  if (model) payload.model = model;
  const body = b64(JSON.stringify(payload));
  return `v2.${body}.${b64(crypto.sign(null, Buffer.from(`v2.${body}`), privateKey))}`;
}

/** Verify and return claims, or throw SessionError. `nowS` is epoch seconds. `opts` exists for tests only. */
export function verify(token, key, nowS = Date.now() / 1000, { trusted = TRUSTED_KEYS, v1Accepted = V1_ACCEPTED } = {}) {
  const parts = String(token || "").trim().split(".");
  if (parts.length !== 3 || (parts[0] !== "v1" && parts[0] !== "v2")) throw new SessionError("MeshSessionMalformed", "malformed session token");
  let got; try { got = Buffer.from(parts[2], "base64url"); } catch { got = Buffer.alloc(0); }
  let c; try { c = JSON.parse(Buffer.from(parts[1], "base64url").toString()); } catch { c = null; }
  if (parts[0] === "v2") {
    if (!c || typeof c !== "object") throw new SessionError("MeshSessionMalformed", "unreadable payload");
    const pub = Object.prototype.hasOwnProperty.call(trusted, String(c.kid || "")) ? trusted[String(c.kid)] : "";
    if (!pub) throw new SessionError("MeshSessionUnknownKey", "token signed with a key this relay does not trust");
    let ok = false;
    try {
      const keyObj = crypto.createPublicKey({ key: Buffer.concat([ED25519_SPKI_PREFIX, Buffer.from(pub, "base64url")]), format: "der", type: "spki" });
      ok = crypto.verify(null, Buffer.from(`v2.${parts[1]}`), keyObj, got);
    } catch { ok = false; }
    if (!ok) throw new SessionError("MeshSessionBadSignature", "bad signature");
    return checkClaims(c, nowS);
  }
  if (!v1Accepted) throw new SessionError("MeshSessionV1Retired", "HMAC (v1) session tokens are no longer accepted; the portal must issue a v2 token");
  if (!key) throw new SessionError("MeshSessionKeyMissing", "no session key configured", 503);
  const sigOk = (k) => { const want = crypto.createHmac("sha256", k).update(`v1.${parts[1]}`).digest(); return got.length === want.length && crypto.timingSafeEqual(got, want); };
  // The portal signs each token with a PER-SESSION key = hex(HMAC(master, "session:<id>")) (app/mesh_session.py session_key), so a
  // compromised codespace only learns its own key. The relay holds the MASTER key: accept a token signed directly with `key`
  // (tests, single-session meshes), else re-derive the per-session key from the payload's session_id and verify with that.
  if (!sigOk(key)) {
    const sid = c && c.session_id ? String(c.session_id) : "";
    const derived = sid ? crypto.createHmac("sha256", key).update(`session:${sid}`).digest("hex") : "";
    if (!derived || !sigOk(derived)) throw new SessionError("MeshSessionBadSignature", "bad signature");
  }
  if (!c) throw new SessionError("MeshSessionMalformed", "unreadable payload");
  return checkClaims(c, nowS);
}

function checkClaims(c, nowS) {
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
