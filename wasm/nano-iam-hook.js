/* Vyomi Nano - request-time IAM hook (faithful IAM, docs/architecture/v4.0/branches/iam-nano-hook.md).
 *
 * ES module usable from the page (nano-boot.js) AND the relay SharedWorker (relay/relay-shared-worker.js): no DOM, no localStorage.
 * Before a native-wire request is dispatched to the in-browser core, `guard(cloud, req)` decides whether the Python gate
 * (core.iam_engine.gate.check, via core/iam_engine/nano_bridge.py) must run, and returns the cloud-shaped denial or null.
 *
 * OFF IS FREE: per-space settings (the enforcement document, key `iam-enforcement:<cloud>` in the shared nano-spaces IndexedDB, default
 * off) are cached in JS and kept fresh over a BroadcastChannel. With every level off, guard() returns null with ZERO Python calls, no
 * engine fetch, no catalog fetch (one resolved-promise await). Only when a level is audit/enforce does it (1) mount core/iam_engine into
 * the Pyodide FS once, (2) call the gate, (3) prefetch the needed service catalog when the gate says `need` (HTTP + IndexedDB copy).
 *
 * Also serves `/api/iam/<cloud>/...` (IamApi.handle, same routes and bodies as Mesh): `api(method, path, query, body)`.
 * Wire scope: requests that carry credentials (AWS SigV4 / Bearer token = SDK/CLI through the tunnel). Credential-less traffic is the
 * console's own and is never gated (Mesh's gate skips /api/* console traffic the same way), so behaviour is identical on both substrates.
 *
 * Failure policy: gate unavailable or crashed => fail OPEN, unless some level of that cloud's document is `enforce` => fail CLOSED
 * with a 503 (contract: fail-closed when mode=enforce).
 */
const DB = "nano-spaces", KEY = (cloud) => "iam-enforcement:" + cloud, CAT_KEY = (rel) => "iam-catalog:" + rel;
const CHANNEL = "nano-iam-enforcement";
const CLOUDS = ["aws", "gcp", "azure"];

function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains("spaces")) db.createObjectStore("spaces", { keyPath: "space_id" });
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta", { keyPath: "k" });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
const metaGet = (k) => idb().then((db) => new Promise((res) => {
  try { const g = db.transaction("meta", "readonly").objectStore("meta").get(k); g.onsuccess = () => res(g.result ? g.result.v : null); g.onerror = () => res(null); }
  catch (_) { res(null); }
}), () => null);
const metaPut = (k, v) => idb().then((db) => new Promise((res, rej) => {
  const tx = db.transaction("meta", "readwrite"); tx.objectStore("meta").put({ k, v }); tx.oncomplete = () => res(); tx.onerror = () => rej(tx.error);
}));

const MODES = ["off", "audit", "enforce"];
const norm = (m) => (MODES.includes(m) ? m : "off");
/** Is any level of a settings document non-off? (cheap, pure; the only per-request work while the space is off.) */
export function anyOn(doc) {
  if (!doc) return false;
  if (norm(doc.global) !== "off" || norm(doc.space) !== "off") return true;
  for (const m of Object.values(doc.services || {})) if (norm(m) !== "off") return true;
  for (const m of Object.values(doc.resources || {})) if (norm(m) !== "off") return true;
  return false;
}
export function anyEnforce(doc) {
  if (!doc) return false;
  return [doc.global, doc.space, ...Object.values(doc.services || {}), ...Object.values(doc.resources || {})].some((m) => m === "enforce");
}

// Mirror of core/iam_engine/routing.py (a test keeps the two in step): Entra / Vyomi extensions are exempt; Azure data planes that share the
// AWS-looking path space (/openai, /azure-openai, /azure-sql, /contentsafety) and the `/_wire/arm` alias are Azure; Cloud Storage XML API calls
// (storage.googleapis.com host, GOOG auth, Google HMAC key, x-goog-* headers) are GCP, not S3. A signed AWS request is never Azure/Entra.
const ENTRA = /^\/(?:v1\.0|beta)(?:\/|$)|\/oauth2(?:\/v2\.0)?\/(?:token|authorize|devicecode|logout)$|^\/[^/]+\/(?:v2\.0\/)?\.well-known\/openid-configuration$|^\/[^/]+\/discovery\/(?:v2\.0\/)?keys$|^\/discovery\/(?:v2\.0\/)?keys$|^\/common\/userrealm\//i;
const COGNITO_POOL = /^\/[a-z0-9-]+_[A-Za-z0-9]+\//;
const AZURE_DP = /^\/(?:openai|azure-openai|azure-sql|contentsafety)(?:\/|$)/i;
const VYOMI_EXT = /^\/openai\/vyomi\//i;
export function stripWire(path) {
  let p = String(path || "/");
  for (const pre of ["/nano/_wire", "/_wire"]) if (p === pre || p.startsWith(pre + "/")) { p = p.slice(pre.length) || "/"; break; }
  return /^\/arm(?:\/(?:subscriptions|providers|tenants)(?:\/|$))/i.test(p) ? p.slice(4) : p;
}
function signedAws(h, q) {
  const a = h.authorization || "";
  return a.startsWith("AWS4-") || a.startsWith("AWS ") || !!h["x-amz-target"] || /X-Amz-Algorithm/i.test(JSON.stringify(Object.keys(q || {}))) || !!(q && (q["X-Amz-Credential"] || q.AWSAccessKeyId));
}
function gcsXml(h, q) {
  const host = String(h.host || "").toLowerCase().replace(/:\d+$/, ""), a = h.authorization || "";
  if (/(?:^|\.)storage\.googleapis\.com$/.test(host)) return true;
  if (/^GOOG(?:1|4)/i.test(a) || (a.startsWith("AWS4-") && /Credential=GOOG/i.test(a)) || (a.startsWith("AWS ") && a.slice(4).startsWith("GOOG"))) return true;
  if (q && (q["X-Goog-Algorithm"] || q.GoogleAccessId || /^GOOG/.test(String(q["X-Amz-Credential"] || "")))) return true;
  return Object.keys(h).some((k) => k.startsWith("x-goog-")) && !a.startsWith("AWS4-");
}
/** -> {cloud: "aws"|"gcp"|"azure"|null, exempt: bool}. null cloud = not SDK/CLI traffic (no credentials) => never gated. */
export function routeOf(req) {
  const h = {}; for (const k of Object.keys(req.headers || {})) h[k.toLowerCase()] = req.headers[k];
  const q = req.query || {}, auth = h.authorization || "", p = stripWire(req.path).split("?", 1)[0];
  if (p !== "/" && gcsXml(h, q)) return { cloud: "gcp", exempt: false };
  if (/^AWS4-HMAC-SHA256/i.test(auth) || q["X-Amz-Algorithm"] || q["x-amz-algorithm"] || /^AWS /.test(auth)) return { cloud: "aws", exempt: false };
  if (VYOMI_EXT.test(p) || (ENTRA.test(p) && !COGNITO_POOL.test(p) && !p.startsWith("/identities/"))) return { cloud: null, exempt: true };
  if (AZURE_DP.test(p) || /^\/(?:subscriptions|providers|tenants)(?:\/|$)/i.test(p)) return (auth || h["api-key"] || h["x-ms-version"]) ? { cloud: "azure", exempt: false } : { cloud: null, exempt: false };
  if (/^Bearer /i.test(auth) || h["x-ms-version"] || h["x-goog-api-client"]) {
    return { cloud: (h["x-ms-version"] || /\.(blob|queue|table|file|vault)\.|\/providers\/microsoft\./i.test(p)) ? "azure" : "gcp", exempt: false };
  }
  return { cloud: null, exempt: false };
}
/** Which cloud does a wire request belong to? null = not SDK/CLI traffic (no credentials) or exempt (Entra) => never gated. */
export const cloudOf = (req) => routeOf(req).cloud;

// IAM analysis routes (mirror of core/iam_engine/analyze_wire.match; a test keeps the two in step): Access Analyzer REST, Policy Troubleshooter,
// Cloud Asset analyzeIamPolicy, Azure checkAccess / permissions / filtered role assignments / PIM schedules, and the IAM Query simulate actions.
const AA_PATH = /^\/(?:analyzer|finding|findingv2|policy\/(?:validation|check-no-new-access|check-access-not-granted|check-no-public-access)|resource\/scan)(?:\/|$)/;
const GCP_TS = /^\/v[13]\/iam:troubleshoot$/, GCP_AN = /^\/v1\/(?:projects|folders|organizations)\/[^/:]+:analyzeIamPolicy$/;
const AZ_AUTHZ = /\/providers\/microsoft\.authorization\/(checkaccess|permissions|roleassignments|roleeligibilityschedules|roleeligibilityscheduleinstances|roleassignmentschedules|roleassignmentscheduleinstances)\/?$/i;
const SIM_ACTIONS = /(?:^|&)Action=(?:SimulatePrincipalPolicy|SimulateCustomPolicy|GetContextKeysForPrincipalPolicy|GetContextKeysForCustomPolicy)(?:&|$)/;
/** -> "analyze" (answer from the engine) | "engine" (IAM Query simulate: mount the engine, then dispatch normally) | null. Cheap and synchronous. */
export function analysisRoute(req) {
  const h = {}; for (const k of Object.keys(req.headers || {})) h[k.toLowerCase()] = req.headers[k];
  const p = stripWire(req.path).split("?", 1)[0], m = String(req.method || "GET").toUpperCase(), q = req.query || {};
  if ((/access-analyzer\/aws4_request/.test(h.authorization || "") || /^access-analyzer\./i.test(h.host || "")) && AA_PATH.test(p)) return "analyze";
  if (m === "POST" && GCP_TS.test(p)) return "analyze";
  if (m === "GET" && GCP_AN.test(p)) return "analyze";
  const a = AZ_AUTHZ.exec(p);
  if (a) {
    const res = a[1].toLowerCase();
    if (res === "checkaccess") { if (m !== "POST") return null; let t = ""; try { t = atob(req.body_b64 || ""); } catch (_) {} return /"subject"/i.test(t) && /"actions"/i.test(t) ? "analyze" : null; }
    if (res === "roleassignments") return m === "GET" && (q["$filter"] || /[?&]\$filter=/.test(String(req.path))) ? "analyze" : null;
    return m === "GET" ? "analyze" : null;
  }
  if (m === "POST" && /^AWS4-/.test(h.authorization || "") && /\/iam\/aws4_request/.test(h.authorization || "")) {
    let t = ""; try { t = atob(req.body_b64 || ""); } catch (_) {}
    if (SIM_ACTIONS.test(t)) return "engine";
  }
  return null;
}

const DENY_503 = (cloud) => ({
  status: 503, headers: { "content-type": "application/json" },
  body_b64: btoa(JSON.stringify({ __type: "ServiceUnavailable", message: "IAM enforcement is on for this space but the engine could not run; failing closed (" + cloud + ")." })),
});
const AUDIT_CAP = 1000, AUDIT_KEY = "iam-audit", AUDIT_CH = "nano-iam-audit";

/**
 * @param {object} o  { py: Pyodide, base: bundle base URL path (like nano-boot BASE), log?: fn }
 * @returns {{guard, api, ready, stats, settings, setSettings}}
 */
export function createIamHook(o) {
  const { py } = o, base = (o.base || "").replace(/\/$/, ""), log = o.log || (() => {});
  const docs = {}, stats = { calls: 0, skipped: 0, denied: 0, errors: 0, engine_mounts: 0, catalog_fetches: 0, api_calls: 0 };
  let engine = null, manifest = null, bridge = null, ring = [], pending = null;
  const ready = Promise.all([...CLOUDS.map(async (c) => { docs[c] = await metaGet(KEY(c)); }),
    metaGet(AUDIT_KEY).then((r) => { if (Array.isArray(r)) ring = r; })]).then(() => { ready.settled = true; return true; });
  let bc = null, abc = null;
  try {
    bc = new BroadcastChannel(CHANNEL);
    bc.onmessage = (e) => { if (e.data && CLOUDS.includes(e.data.cloud)) docs[e.data.cloud] = e.data.doc || null; };
    abc = new BroadcastChannel(AUDIT_CH);
    abc.onmessage = (e) => {            // another context (page <-> relay worker) recorded: merge into our view
      if (e.data && e.data.rec && !ring.some((r) => r.ctx === e.data.rec.ctx && r.id === e.data.rec.id)) { ring.unshift(e.data.rec); ring.length = Math.min(ring.length, AUDIT_CAP); }
      if (e.data && e.data.clear) ring = [];
    };
  } catch (_) { /* no BroadcastChannel: the next page load reads the stored document / ring */ }
  const ctx = Math.random().toString(36).slice(2, 8);      // ids are per Pyodide context: (ctx, id) is unique across the shared ring
  const flush = () => { pending = null; metaPut(AUDIT_KEY, ring).catch(() => {}); };

  // The object the Python bridge calls back into (sync: JS-side caches over IndexedDB).
  const host = {
    get_settings: (c) => (docs[c] ? JSON.stringify(docs[c]) : null),
    put_settings: (c, j) => { setSettings(c, JSON.parse(j)); },
    audit_push: (j) => { const rec = { ...JSON.parse(j), ctx }; ring.unshift(rec); ring.length = Math.min(ring.length, AUDIT_CAP);
      try { abc && abc.postMessage({ rec }); } catch (_) {} if (!pending) pending = setTimeout(flush, 300); },
    audit_list: (c) => JSON.stringify(ring.filter((r) => !c || r.cloud === c)),
    audit_clear: () => { ring = []; try { abc && abc.postMessage({ clear: true }); } catch (_) {} flush(); },
  };

  const fetchText = async (rel) => {
    const r = await fetch(base + "/" + rel, { cache: "force-cache" });
    if (!r.ok) throw new Error(rel + " -> HTTP " + r.status);
    return r.text();
  };
  async function manifestOnce() { return manifest || (manifest = JSON.parse(await fetchText("core/iam_engine/manifest.json"))); }

  /** Mount core/iam_engine (+ host adapters) into the Pyodide FS and configure the bridge (once). Not at boot: only when something needs it. */
  async function mountEngine() {
    if (!engine) engine = (async () => {
      const m = await manifestOnce();
      try { py.FS.mkdir("/core/iam_engine"); } catch (_) { /* exists */ }
      for (const f of m.engine) py.FS.writeFile("/core/iam_engine/" + f, await fetchText("core/iam_engine/" + f));
      for (const f of m.core || []) py.FS.writeFile("/core/" + f, await fetchText("core/" + f));
      py.runPython("import sys; sys.path.insert(0, '/') if '/' not in sys.path else None");
      bridge = py.pyimport("core.iam_engine.nano_bridge");
      bridge.configure(host, JSON.stringify(m.catalogs));
      stats.engine_mounts++; log("iam engine mounted (" + m.engine.length + " modules)");
    })();
    try { await engine; } catch (e) { engine = null; throw e; }
    return bridge;
  }

  /** One catalog (or the service inventory) -> Python. IndexedDB copy keyed by the manifest digest; the network is the fallback. */
  async function load(cloud, svc) {
    const m = await manifestOnce(), inv = cloud === "_inventory";
    const rel = inv ? "service-inventory.json" : "core/iam_catalog/" + cloud + "/" + svc + ".json";
    if (!inv && !(m.catalogs[cloud] || []).includes(svc)) return false;          // not in this bundle
    let text = null;
    if (inv) {                                    // optional file: absent => simulated flag unknown (never an error)
      try { text = await fetchText(rel); } catch (_) { text = "null"; }
      bridge.preload_inventory(text); return true;
    }
    const hit = await metaGet(CAT_KEY(rel));
    if (hit && hit.digest === m.digest) text = hit.text;
    if (text == null) {
      text = await fetchText(rel); stats.catalog_fetches++;
      try { await metaPut(CAT_KEY(rel), { digest: m.digest, text }); } catch (_) { /* cache is best effort */ }
    }
    bridge.preload(cloud, svc, text);
    return true;
  }
  const feed = async (needs) => { let n = 0; for (const [c, s] of needs) if (await load(c, s)) n++; return n; };

  const callGate = (cloud, req, doc) => JSON.parse(bridge.check(JSON.stringify({ cloud, method: req.method, path: req.path, query: req.query || {},
    headers: req.headers || {}, body_b64: req.body_b64 || "" }), JSON.stringify(doc)));

  /** null = dispatch normally; object = {status, headers, body_b64} to answer with instead. */
  async function guard(cloud, req) {
    if (!ready.settled) await ready;
    const doc = docs[cloud];
    if (!anyOn(doc)) { stats.skipped++; return null; }            // the off path: nothing below runs
    try {
      await mountEngine();
      for (let i = 0; i < 6; i++) {
        stats.calls++;
        const out = callGate(cloud, req, doc);
        if (out.need) { await feed(out.need); if (out.need.every(([c, s]) => !((manifest.catalogs[c] || []).includes(s)))) throw new Error("catalog missing from bundle: " + JSON.stringify(out.need)); continue; }
        if (out.deny) { stats.denied++; return out.deny; }
        if (out.error) throw new Error(out.error);
        return null;
      }
      throw new Error("catalog prefetch did not converge");
    } catch (e) {
      stats.errors++; log("iam gate error: " + (e && e.message || e));
      return anyEnforce(doc) ? DENY_503(cloud) : null;
    }
  }

  /** An IAM analysis route (see analysisRoute). null = dispatch normally; object = {status, headers, body_b64} to answer with. The engine is mounted on
   *  demand (these are explicit API calls, independent of the enforcement mode); catalogs the analysis reads are prefetched like the gate's. */
  async function analyze(req) {
    const kind = analysisRoute(req);
    if (!kind) return null;
    if (!ready.settled) await ready;
    stats.analyze_calls = (stats.analyze_calls || 0) + 1;
    try {
      await mountEngine();
      if (kind === "engine") return null;                         // simulate: iam_core now finds core.iam_engine; the router serves the request
      for (let i = 0; i < 6; i++) {
        const out = JSON.parse(bridge.analyze(JSON.stringify({ method: req.method, path: req.path, query: req.query || {}, headers: req.headers || {}, body_b64: req.body_b64 || "" })));
        if (out.need) { await feed(out.need); if (out.need.every(([c, s]) => !((manifest.catalogs[c] || []).includes(s)))) throw new Error("catalog missing from bundle: " + JSON.stringify(out.need)); continue; }
        if (out.error) throw new Error(out.error);
        return out.resp || null;
      }
      throw new Error("catalog prefetch did not converge");
    } catch (e) {
      stats.errors++; log("iam analyze error: " + (e && e.message || e));
      return { status: 500, headers: { "content-type": "application/json" }, body_b64: btoa(JSON.stringify({ message: "IAM analysis failed: " + (e && e.message || e), error: { code: 500, message: String(e && e.message || e) } })) };
    }
  }

  /** /api/iam/<cloud>/... (IamApi.handle). Always mounts the engine (an explicit API call, not request traffic). -> {status, body} */
  async function api(method, path, query, body) {
    if (!ready.settled) await ready;
    stats.api_calls++;
    try {
      await mountEngine();
      for (let i = 0; i < 6; i++) {
        const out = JSON.parse(bridge.api(method, path, JSON.stringify(query || {}), JSON.stringify(body === undefined ? null : body)));
        if (out.need) { await feed(out.need); continue; }
        if (out.error) return { status: 501, body: { error: out.error } };
        return out;
      }
      return { status: 500, body: { error: "catalog prefetch did not converge" } };
    } catch (e) { return { status: 501, body: { error: "IAM engine unavailable: " + (e && e.message || e) } }; }
  }

  async function setSettings(cloud, doc) {
    docs[cloud] = doc; await metaPut(KEY(cloud), doc);
    try { bc && bc.postMessage({ cloud, doc }); } catch (_) {}
  }
  return { guard, api, analyze, ready, stats, settings: (c) => docs[c] || null, setSettings };
}

/** Request shape helpers for the two callers. */
export const fromWireParams = (p) => ({ method: p.method, path: p.path, query: p.query, headers: p.headers, body_b64: p.body_b64 });
export async function guardWire(hook, params) {
  if (!hook) return null;
  if (analysisRoute(params)) { const a = await hook.analyze(fromWireParams(params)); if (a) return a; }       // IAM analysis APIs: answered by the engine, any mode
  const cloud = cloudOf(params);
  return cloud ? hook.guard(cloud, fromWireParams(params)) : null;
}
