/* Booster session token (same format as core/booster_session.py):
 *   v1.<b64url(payload-json)>.<b64url(HMAC-SHA256(key, "v1." + b64url(payload-json)))>
 * payload: {aud:"vyomi-booster-session", sub, tier, primary_cloud, session_id, iat, session_end(epoch s)}
 */
import crypto from "node:crypto";

export const AUD = "vyomi-booster-session";
const SKEW_S = 30;

export class SessionError extends Error {
  constructor(code, message, status = 401) { super(`${code}: ${message}`); this.code = code; this.status = status; }
}
const b64 = (buf) => Buffer.from(buf).toString("base64url");

export function mint(key, { sub = "acct", tier = "pro", primary_cloud = "", session_id = "s1", session_end, iat, role }) {
  const payload = { aud: AUD, sub, tier, primary_cloud, session_id, iat: Math.floor(iat ?? Date.now() / 1000), session_end: Math.floor(session_end) };
  if (role) payload.role = role;
  const body = b64(JSON.stringify(payload));
  return `v1.${body}.${b64(crypto.createHmac("sha256", key).update(`v1.${body}`).digest())}`;
}

/** Verify and return claims, or throw SessionError. `nowS` is epoch seconds. */
export function verify(token, key, nowS = Date.now() / 1000) {
  if (!key) throw new SessionError("BoosterSessionKeyMissing", "no session key configured", 503);
  const parts = String(token || "").trim().split(".");
  if (parts.length !== 3 || parts[0] !== "v1") throw new SessionError("BoosterSessionMalformed", "malformed session token");
  const want = crypto.createHmac("sha256", key).update(`v1.${parts[1]}`).digest();
  let got; try { got = Buffer.from(parts[2], "base64url"); } catch { got = Buffer.alloc(0); }
  if (got.length !== want.length || !crypto.timingSafeEqual(got, want)) throw new SessionError("BoosterSessionBadSignature", "bad signature");
  let c; try { c = JSON.parse(Buffer.from(parts[1], "base64url").toString()); } catch { throw new SessionError("BoosterSessionMalformed", "unreadable payload"); }
  if (c.aud !== AUD) throw new SessionError("BoosterSessionBadAudience", "not a booster session token");
  const end = Number(c.session_end);
  if (!Number.isFinite(end)) throw new SessionError("BoosterSessionMalformed", "missing session_end");
  if (Number(c.iat || 0) > nowS + SKEW_S) throw new SessionError("BoosterSessionNotYetValid", "issued in the future");
  if (nowS >= end) throw new SessionError("BoosterSessionExpired", "the booster session has ended", 410);
  if (!["pro", "max", "enterprise"].includes(String(c.tier || "").toLowerCase())) throw new SessionError("BoosterTierNotEligible", "booster needs Pro or Max", 403);
  if (!c.session_id) throw new SessionError("BoosterSessionMalformed", "missing session_id");
  return c;
}

/** Unverified peek at session_end (the booster side only schedules its own shutdown with it; the relay is the verifier). */
export function peekSessionEnd(token) {
  try { return Number(JSON.parse(Buffer.from(String(token).split(".")[1], "base64url").toString()).session_end); } catch { return NaN; }
}
