/* Native-wire client — the v4 consoles talk to Vyomi exactly the way the real consoles
 * talk to the cloud: each service's NATIVE API (S3 REST+XML, X-Amz-Target JSON, Query+XML).
 * Requests go to a same-origin `/_wire` prefix that both substrates serve with the same
 * router the user's SDK/CLI hits, so the console and the CLI always see the same state:
 *   offline appliance: <origin>/_wire/...        (page at /v4/<cloud>/)
 *   Nano:              <origin>/nano/_wire/...   (page at /nano/v4/<cloud>/, service worker)
 *
 * SigV4 is not verified by Vyomi; the Authorization header only carries the credential
 * scope, which is the routing signal real SDKs send (service + region).
 */

export const WIRE_BASE = (() => {
  const meta = document.querySelector('meta[name="vyomi-wire-base"]');
  if (meta) return meta.content.replace(/\/$/, "");
  return location.pathname.split("/v4/")[0] + "/_wire";
})();

export class WireError extends Error {
  constructor(status, code, message, raw) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code || `HTTP${status}`;
    this.raw = raw;
  }
}

let region = "us-east-1";
export const setRegion = (r) => { region = r; };
export const getRegion = () => region;

const amzDate = () => new Date().toISOString().replace(/[-:]|\.\d{3}/g, "");

export function authHeader(service) {
  const d = amzDate();
  return {
    "authorization": `AWS4-HMAC-SHA256 Credential=VYOMICONSOLE/${d.slice(0, 8)}/${region}/${service}/aws4_request, SignedHeaders=host;x-amz-date, Signature=0`,
    "x-amz-date": d,
  };
}

async function send(method, path, { headers = {}, body, query } = {}) {
  const qs = query ? "?" + new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null)).toString() : "";
  const res = await fetch(WIRE_BASE + path + (qs === "?" ? "" : qs), { method, headers, body });
  const text = res.status === 204 ? "" : await res.text();
  return { status: res.status, headers: res.headers, text, ok: res.ok };
}

// ── XML helpers (S3 REST + Query protocol responses) ────────────────────────────────────
export function xmlToObj(node) {
  const kids = [...node.children];
  if (!kids.length) return node.textContent;
  const o = {};
  for (const k of kids) {
    const v = xmlToObj(k);
    if (k.localName in o) o[k.localName] = [].concat(o[k.localName], v);
    else o[k.localName] = v;
  }
  return o;
}
export const asList = (v) => (v === undefined || v === null || v === "" ? [] : Array.isArray(v) ? v : [v]);

function parseXml(text) {
  if (!text || !text.trim().startsWith("<")) return {};
  const doc = new DOMParser().parseFromString(text, "application/xml");
  return { [doc.documentElement.localName]: xmlToObj(doc.documentElement) };
}

function xmlError(status, text) {
  const o = parseXml(text);
  const e = o.Error || o.ErrorResponse?.Error || {};
  return new WireError(status, e.Code, e.Message, text);
}

// ── Protocols ───────────────────────────────────────────────────────────────────────────
/** AWS JSON protocol (DynamoDB, KMS, SQS-json, Secrets Manager, …). */
export async function awsJson(service, target, payload = {}, { version = "1.0" } = {}) {
  const r = await send("POST", "/", {
    headers: { ...authHeader(service), "content-type": `application/x-amz-json-${version}`, "x-amz-target": target },
    body: JSON.stringify(payload),
  });
  const data = r.text ? JSON.parse(r.text) : {};
  if (!r.ok) {
    const code = (data.__type || "").split("#").pop();
    throw new WireError(r.status, code, data.message || data.Message, r.text);
  }
  return data;
}

/** AWS Query protocol (IAM, RDS, SNS, EC2-like). Params are flattened by the caller. */
export async function awsQuery(service, action, params = {}, { version } = {}) {
  const body = new URLSearchParams({ Action: action, ...(version ? { Version: version } : {}), ...params });
  const r = await send("POST", "/", {
    headers: { ...authHeader(service), "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
    body: body.toString(),
  });
  if (!r.ok) throw xmlError(r.status, r.text);
  return parseXml(r.text);
}

/** S3 REST (path-style). Returns parsed XML (or raw text/blob when asked). */
export async function s3(method, path, { query, headers = {}, body, raw = false } = {}) {
  const r = await send(method, path, { query, body, headers: { ...authHeader("s3"), ...headers } });
  if (!r.ok) throw xmlError(r.status, r.text);
  return raw ? r : parseXml(r.text);
}

/** Generic REST JSON (GCP, Azure ARM) — used by the GCP/Azure lenses. */
export async function restJson(method, path, { query, body, headers = {} } = {}) {
  const r = await send(method, path, {
    query, headers: { "content-type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = r.text ? (() => { try { return JSON.parse(r.text); } catch { return { raw: r.text }; } })() : {};
  if (!r.ok) throw new WireError(r.status, data.error?.status || data.error?.code, data.error?.message, r.text);
  return data;
}

/** SigV4-signed REST JSON (API Gateway v1/v2, and any other AWS REST-JSON service):
 * same shape as restJson, but with the AWS Authorization header so the router can
 * credential-scope routes that don't carry a distinguishing path segment (e.g.
 * API Gateway's account-level /apikeys, /usageplans, /clientcertificates, /account). */
export async function awsRest(service, method, path, { query, body, headers = {} } = {}) {
  const r = await send(method, path, {
    query, headers: { ...authHeader(service), "content-type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = r.text ? (() => { try { return JSON.parse(r.text); } catch { return { raw: r.text }; } })() : {};
  if (!r.ok) throw new WireError(r.status, data.__type || data.message, data.message, r.text);
  return data;
}
