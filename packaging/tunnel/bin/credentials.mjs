// vyomi-tunnel credentials: the AWS-CLI model. ~/.vyomi/credentials (INI) holds an access key; the tunnel signs a request to the portal
// and gets a short-lived session (plan, Mesh session end, Codespace, GitHub token). Contract: docs/architecture/v4.0/TUNNEL-CREDENTIALS-CONTRACT.md
import { createHmac, createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export class TunnelAuthError extends Error { constructor(code, message) { super(message); this.code = code; } }
export const DEFAULT_PORTAL = "https://vyomi.cloud";
export const keysUrl = (portal) => (portal || DEFAULT_PORTAL).replace(/\/$/, "") + "/account/tunnel-credentials";
export const KEYS_URL = keysUrl();
export const noCredentials = (portal) => `No Vyomi credentials. Download your access key and secret from ${keysUrl(portal)} (console: avatar menu > Tunnel credentials) and save the file as ~/.vyomi/credentials`;
export const NO_CREDENTIALS = noCredentials();

export function parseIni(text) {
  const out = {}; let cur = null;
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.replace(/\s[;#].*$/, "").trim();               // inline comments need a space before ; or #
    if (!line || line.startsWith(";") || line.startsWith("#")) continue;
    const sec = /^\[([^\]]+)\]$/.exec(line); if (sec) { cur = out[sec[1].trim()] = out[sec[1].trim()] || {}; continue; }
    const kv = /^([A-Za-z0-9_.-]+)\s*=\s*(.*)$/.exec(line); if (kv && cur) cur[kv[1].toLowerCase()] = kv[2].trim();
  }
  return out;
}

/** @returns {accessKeyId, secretAccessKey, githubToken, portal, profile, source} or null */
export function loadCredentials({ env = process.env, read = (f) => readFileSync(f, "utf8"), home = env.VYOMI_HOME || join(homedir(), ".vyomi") } = {}) {
  const profile = env.VYOMI_PROFILE || "default";
  const file = env.VYOMI_CREDENTIALS_FILE || join(home, "credentials");
  let sec = {}; let source = "env";
  try { sec = parseIni(read(file))[profile] || {}; source = file; } catch { /* no file: env only */ }
  const accessKeyId = env.VYOMI_ACCESS_KEY_ID || sec.vyomi_access_key_id || "";
  const secretAccessKey = env.VYOMI_SECRET_ACCESS_KEY || sec.vyomi_secret_access_key || "";
  if (!accessKeyId || !secretAccessKey) return null;
  return { accessKeyId, secretAccessKey, githubToken: sec.github_token || "", portal: (env.VYOMI_PORTAL_URL || sec.portal || DEFAULT_PORTAL).replace(/\/$/, ""), profile, source };
}

export const sha256hex = (s) => createHash("sha256").update(s).digest("hex");
export const sign = ({ secret, method, path, date, body }) => createHmac("sha256", secret).update(`${method}\n${path}\n${date}\n${sha256hex(body)}`).digest("hex");

const friendly = (portal) => ({
  InvalidAccessKey: `your Vyomi access key is not valid. Create a new one at ${keysUrl(portal)}.`,
  SignatureMismatch: `your Vyomi secret key does not match. Create a new access key at ${keysUrl(portal)}.`,
  RequestTimeSkew: "your computer's clock is off by more than 5 minutes. Fix the clock and retry.",
  KeyRevoked: `this access key was revoked. Create a new one at ${keysUrl(portal)}.`,
  PlanNotAllowed: "Mesh needs a Pro or Max plan.",
  NoMeshSession: "Mesh is not running. Start it in the Vyomi console, then retry.",
  Throttled: "too many requests; wait a moment and retry.",
});

export async function fetchSession({ creds, fetchFn = globalThis.fetch, now = () => new Date(), version = "1.2.0" }) {
  const path = "/api/tunnel/session", body = JSON.stringify({ client: "vyomi-tunnel/" + version });
  const date = now().toISOString().replace(/\.\d+Z$/, "Z");
  let r;
  try {
    r = await fetchFn(creds.portal + path, { method: "POST", body, signal: AbortSignal.timeout(15000), headers: { "content-type": "application/json",
      "x-vyomi-key": creds.accessKeyId, "x-vyomi-date": date, "x-vyomi-signature": sign({ secret: creds.secretAccessKey, method: "POST", path, date, body }) } });
  } catch (e) { throw new TunnelAuthError("Unreachable", `cannot reach ${creds.portal} (${String(e.message).slice(0, 80)})`); }
  let j = null; try { j = await r.json(); } catch { /* not json */ }
  if (!r.ok) { const code = j?.error?.code || "Error"; throw new TunnelAuthError(code, friendly(creds.portal)[code] || j?.error?.message || `the portal refused the request (HTTP ${r.status})`); }
  const s = j?.session; if (!s || typeof s.expires_at !== "number") throw new TunnelAuthError("BadResponse", "unexpected response from the portal");
  return { tier: s.tier || "", meshAllowed: s.allowed !== false, expiresAt: s.expires_at, sessionEnd: s.session_end ?? null, codespace: s.mesh?.codespace || "", meshState: s.mesh?.state || "",
           githubToken: s.github?.token || "" };
}

/** A cached, auto-refreshing session. get() throws TunnelAuthError (NoCredentials, ...). */
export function createSessionManager({ env = process.env, loader = () => loadCredentials({ env }), fetchFn, now = () => new Date(), log = () => {}, refreshMarginS = 120 } = {}) {
  let cur = null, creds = null;
  async function get() {
    creds = creds || loader(); if (!creds) throw new TunnelAuthError("NoCredentials", noCredentials(env.VYOMI_PORTAL_URL));
    const t = now().getTime() / 1000;
    if (cur && cur.expiresAt - t > refreshMarginS) return withGithub(cur);
    cur = await fetchSession({ creds, fetchFn, now });
    if (cur.sessionEnd && cur.sessionEnd <= t) { cur = null; throw new TunnelAuthError("SessionEnded", "your Mesh session has ended. Start Mesh again in the console."); }
    log(`session ok (${cur.tier || "?"}${cur.sessionEnd ? ", ends " + new Date(cur.sessionEnd * 1000).toISOString() : ""})`);
    return withGithub(cur);
  }
  const withGithub = (s) => ({ ...s, githubToken: s.githubToken || creds?.githubToken || "" });
  return { get, creds: () => creds };
}

/** Every command needs a valid key (Nano included: a Free key is fine). Returns the session, or {error, code}. */
export async function requireSession({ log = () => {}, ...opts } = {}) {
  try { return { sess: await createSessionManager({ log, ...opts }).get() }; } catch (e) { return { error: e.message, code: e.code || "Error" }; }
}
