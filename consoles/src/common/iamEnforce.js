/* IAM enforcement + effective-access client logic shared by the three v4 consoles (pure JS: no React, no UI library, so
 * it runs under node for tests). Contract: docs/architecture/v4.0/IAM-ENGINE-CONTRACT.md.
 *   settings = {"global","space","services":{svc:mode},"resources":{resourceName:mode}} ; mode = off|audit|enforce
 *   resolved most specific first: resource > service > space > global (default off).
 * API (same on Mesh and Nano): GET/PUT <base>/<cloud>/enforcement, GET <base>/<cloud>/audit?limit=, POST <base>/<cloud>/evaluate,
 * GET <base>/<cloud>/catalog/<service>. <base> = <wire base>/api/iam, the wire base being /_wire on Mesh and /nano/_wire on Nano (the existing console front door). */

export const MODES = ["off", "audit", "enforce"];
export const LEVELS = ["resource", "service", "space", "global"];
export const MODE_LABEL = { off: "Off", audit: "Audit", enforce: "Enforce" };
export const MODE_HELP = {
  off: "Policies are not evaluated for requests.",
  audit: "Policies are evaluated and \"would deny\" is logged; nothing is blocked.",
  enforce: "Policies are evaluated and a denial is returned to the caller (fail closed).",
};
export const SOURCE_LABEL = { resource: "this resource", service: "the service setting", space: "the space setting", global: "the global setting", default: "the default (off)" };

/* IAM service prefixes offered in the per-service control; any other key can still be typed. */
export const SERVICES = {
  aws: ["s3", "dynamodb", "sqs", "sns", "kms", "secretsmanager", "lambda", "ec2", "iam", "sts", "rds", "logs"],
  gcp: ["storage", "pubsub", "compute", "cloudkms", "secretmanager", "cloudfunctions", "run", "sql", "firestore", "iam"],
  azure: ["Microsoft.Storage", "Microsoft.KeyVault", "Microsoft.Compute", "Microsoft.Sql", "Microsoft.Network", "Microsoft.ContainerService", "Microsoft.Authorization"],
};

export const emptySettings = () => ({ global: "off", space: "off", services: {}, resources: {} });
const ok = (m) => (MODES.includes(m) ? m : undefined);

export function normalizeSettings(s) {
  const e = emptySettings();
  if (!s || typeof s !== "object") return e;
  return { global: ok(s.global) || "off", space: ok(s.space) || "off", services: { ...(s.services || {}) }, resources: { ...(s.resources || {}) } };
}

/** Effective mode + the level it comes from. A level only "wins" when it is set; global/space of "off" still count as set. */
export function resolveMode(settings, service, resource) {
  const s = normalizeSettings(settings);
  if (resource && ok(s.resources[resource])) return { mode: s.resources[resource], source: "resource" };
  if (service && ok(s.services[service])) return { mode: s.services[service], source: "service" };
  if (ok(settings?.space)) return { mode: settings.space, source: "space" };
  if (ok(settings?.global)) return { mode: settings.global, source: "global" };
  return { mode: "off", source: "default" };
}

/** Pure update. level global|space -> key ignored; service|resource -> overrides[key]; mode null/"inherit" clears an override. */
export function withMode(settings, level, key, mode) {
  const s = normalizeSettings(settings);
  if (level === "global" || level === "space") { if (!ok(mode)) throw new Error(`${level} needs a mode`); return { ...s, [level]: mode }; }
  const bag = level === "service" ? "services" : level === "resource" ? "resources" : null;
  if (!bag) throw new Error(`unknown level ${level}`);
  const next = { ...s[bag] };
  if (ok(mode)) next[key] = mode; else delete next[key];
  return { ...s, [bag]: next };
}

/** Audit rows -> a uniform shape. enforced=false in audit mode so a deny is a "would deny". */
export function normalizeAudit(rec) {
  const allowed = rec.allowed ?? rec.decision?.allowed ?? (rec.decision === "allow" || rec.decision === "allowed");
  const mode = rec.mode || "off";
  return {
    ts: rec.ts || rec.time || rec.timestamp || "",
    principal: typeof rec.principal === "string" ? rec.principal : rec.principal?.arn || rec.principal?.member || rec.principal?.object_id || "",
    action: rec.action || "", resource: rec.resource || "", service: rec.service || "", mode,
    allowed: !!allowed, reason: rec.reason || rec.decision?.reason || (allowed ? "allow" : "implicit_deny"),
    matched: rec.matched || rec.decision?.matched || [],
    wouldDeny: mode === "audit" && !allowed,
  };
}
export const auditLabel = (r) => (r.allowed ? "Allowed" : r.mode === "audit" ? "Would deny" : "Denied");

export function filterAudit(records, { mode = "all", decision = "all" } = {}) {
  return records.filter((r) => (mode === "all" || r.mode === mode)
    && (decision === "all" || (decision === "allow" ? r.allowed : decision === "would_deny" ? r.wouldDeny : !r.allowed)));
}

export const REASON_TEXT = {
  allow: "Allowed by a matching statement.",
  explicit_deny: "Denied by an explicit deny.",
  implicit_deny: "Denied: no statement allows this action (implicit deny).",
  not_applicable: "The engine has no opinion for this request.",
};
export const reasonText = (d) => REASON_TEXT[d?.reason] || d?.reason || "";

/* --- API client --- */
export function iamBase(wireBase) {
  const meta = typeof document !== "undefined" ? document.querySelector('meta[name="vyomi-iam-base"]')?.content : null;
  if (meta) return meta.replace(/\/$/, "");
  // Same front door as every console page: <wire base>/api/iam. On Mesh that is <origin>/_wire/api/iam (and mesh-link.js reroutes
  // /_wire/* of a mesh-homed space to the mesh); on Nano it is <origin>/nano/_wire/api/iam, answered by the in-browser service worker.
  return String(wireBase || "").replace(/\/$/, "") + "/api/iam";
}

export function iamApi(cloud, { base, fetcher } = {}) {
  const f = fetcher || ((...a) => fetch(...a));
  const call = async (method, path, body) => {
    const res = await f(`${base}/${cloud}${path}`, { method, headers: body === undefined ? {} : { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await res.text();
    let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
    if (!res.ok) throw Object.assign(new Error(data.error?.message || data.message || `IAM API HTTP ${res.status}`), { status: res.status });
    return data;
  };
  return {
    getEnforcement: async () => normalizeSettings(await call("GET", "/enforcement")),
    putEnforcement: async (s) => normalizeSettings(await call("PUT", "/enforcement", s)),
    audit: async (limit = 100) => { const d = await call("GET", `/audit?limit=${limit}`); return (Array.isArray(d) ? d : d.records || d.items || []).map(normalizeAudit); },
    evaluate: (req) => call("POST", "/evaluate", { cloud, ...req }),
    catalog: (service) => call("GET", `/catalog/${encodeURIComponent(service)}`),
  };
}

/* In-memory fake of the same API, for tests and the visual harness. Mirrors the contract shapes; NOT a policy engine. */
export function mockIam(cloud, { allow = () => true } = {}) {
  let settings = emptySettings();
  const audit = [];
  const json = (status, body) => ({ ok: status < 400, status, text: async () => JSON.stringify(body) });
  const fetcher = async (url, init = {}) => {
    const path = url.split(`/${cloud}`)[1] || "";
    const m = init.method || "GET";
    if (path.startsWith("/enforcement")) { if (m === "PUT") settings = JSON.parse(init.body); return json(200, settings); }
    if (path.startsWith("/audit")) return json(200, { records: [...audit].reverse().slice(0, Number(new URL(url, "http://x").searchParams.get("limit") || 100)) });
    if (path.startsWith("/evaluate")) {
      const req = JSON.parse(init.body); const svc = String(req.action).split(/[:.]/)[0];
      const allowed = !!allow(req); const { mode } = resolveMode(settings, svc, req.resource);
      const d = { allowed, reason: allowed ? "allow" : "implicit_deny", matched: allowed ? [{ source: "identity", id: "policy/Mock", effect: "Allow", statement: { Action: req.action, Resource: req.resource } }] : [], mode };
      audit.push({ ts: new Date(0).toISOString(), principal: req.principal, action: req.action, resource: req.resource, service: svc, mode, allowed, reason: d.reason, matched: d.matched });
      return json(200, d);
    }
    return json(404, { message: "not found" });
  };
  return { fetcher, seedAudit: (r) => audit.push(r), get settings() { return settings; } };
}
