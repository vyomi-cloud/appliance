// Keeps the running tunnel honest about its credentials. It never exits on a bad key (a service manager would crash-loop it); instead it
// reports the key's state on /health, re-checks on a timer, when the credentials file changes, and on POST /reload, and it can be
// re-paired from the Vyomi page with POST /reset {code} (a single-use pairing code made by the signed-in portal user).
//
// Security: the relay answers CORS "*", so /reset must not be usable by an arbitrary website. It accepts only Vyomi origins (or none, i.e. a
// local program), a loopback Host header (DNS-rebinding guard), and it redeems the code ONLY at the portal named in the existing credentials
// file (or https://vyomi.cloud when there is none) -- never at a URL supplied by the caller.
import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync, copyFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { loadCredentials, fetchSession, DEFAULT_PORTAL } from "./credentials.mjs";

const BAD = { InvalidAccessKey: "invalid", SignatureMismatch: "invalid", KeyRevoked: "revoked" };
const CODE_RE = /^[A-Za-z0-9_-]{20,64}$/;
export const ALLOWED_ORIGINS = [/^https:\/\/(www\.)?vyomi\.cloud$/, /^https?:\/\/localhost(:\d+)?$/, /^https?:\/\/127\.0\.0\.1(:\d+)?$/];
export const originAllowed = (origin) => !origin || ALLOWED_ORIGINS.some((re) => re.test(origin));
export const hostIsLoopback = (host) => /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(String(host || ""));

export function createCredsSync({ env = process.env, fetchFn = globalThis.fetch, version = "1.2.4", log = () => {}, intervalMs = 300000, now = () => Date.now() } = {}) {
  const home = env.VYOMI_HOME || join(homedir(), ".vyomi");
  const file = env.VYOMI_CREDENTIALS_FILE || join(home, "credentials");
  let st = { state: "unknown", key_id: "", portal: "", checked_at: 0, error: "" };
  let mtime = 0, timer = null, busy = null;

  async function check() {
    if (busy) return busy;
    busy = (async () => {
      const c = loadCredentials({ env });
      if (!c) st = { state: "none", key_id: "", portal: DEFAULT_PORTAL, checked_at: now(), error: "NoCredentials" };
      else {
        try { await fetchSession({ creds: c, fetchFn, version }); st = { state: "ok", key_id: c.accessKeyId, portal: c.portal, checked_at: now(), error: "" }; }
        catch (e) {
          const state = BAD[e.code] || (e.code === "PlanNotAllowed" || e.code === "NoMeshSession" ? "ok" : "unreachable");   // plan/mesh state is not a key problem
          st = { state, key_id: c.accessKeyId, portal: c.portal, checked_at: now(), error: e.code || "Error" };
        }
      }
      try { mtime = statSync(file).mtimeMs; } catch { mtime = 0; }
      log(`credentials: ${st.state}${st.key_id ? " (" + st.key_id + ")" : ""}${st.error ? " " + st.error : ""}`);
      return st;
    })().finally(() => { busy = null; });
    return busy;
  }

  /** Redeem a pairing code at the PINNED portal and replace the credentials file (mode 600, previous file kept as .bak). */
  async function reset(code, host = "tunnel reset", origin = "") {
    if (!CODE_RE.test(String(code || ""))) { const e = new Error("bad code"); e.status = 400; throw e; }
    // The portal is pinned to the one in the credentials file, EXCEPT that a request coming from the real https://vyomi.cloud page may re-point
    // a tunnel that was paired elsewhere (e.g. a dev portal) at vyomi.cloud: that origin is the genuine portal and cannot be spoofed by a page.
    const home = /^https:\/\/(www\.)?vyomi\.cloud$/.test(origin || "") ? DEFAULT_PORTAL : "";
    const portal = (home || loadCredentials({ env })?.portal || env.VYOMI_PORTAL_URL || DEFAULT_PORTAL).replace(/\/$/, "");
    let r;
    try { r = await fetchFn(portal + "/api/tunnel/pair/redeem", { method: "POST", headers: { "content-type": "application/json" }, signal: AbortSignal.timeout(20000),
      body: JSON.stringify({ code, host: String(host).replace(/[^A-Za-z0-9._ -]/g, "").slice(0, 40) }) }); }
    catch { const e = new Error("cannot reach the portal"); e.status = 502; throw e; }
    const j = await r.json().catch(() => null);
    if (!r.ok || !j?.credentials_file) { const e = new Error(j?.message || j?.error || `the portal refused the code (HTTP ${r.status})`); e.status = r.status === 410 ? 410 : 502; throw e; }
    mkdirSync(dirname(file), { recursive: true });
    if (existsSync(file)) { try { copyFileSync(file, `${file}.bak.${Math.floor(now() / 1000)}`); } catch { /* */ } }
    const tmp = file + ".tmp"; writeFileSync(tmp, j.credentials_file, { mode: 0o600 }); try { chmodSync(tmp, 0o600); } catch { /* */ } renameSync(tmp, file);
    log("credentials replaced by a reset from the Vyomi page");
    return check();
  }

  function start() {
    check();
    timer = setInterval(() => {                                   // file change => re-check now; otherwise on the slow timer
      let m = 0; try { m = statSync(file).mtimeMs; } catch { /* */ }
      if (m !== mtime || now() - st.checked_at >= intervalMs) check();
    }, 5000);
    timer.unref?.();
  }
  return { check, reset, start, stop: () => clearInterval(timer), state: () => ({ ...st, version }) };
}
