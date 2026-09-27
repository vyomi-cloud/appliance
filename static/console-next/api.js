// Vyomi console-next — API client + capability store.
//
// GUARANTEE (§15.1 #2): the SPA talks ONLY to `/api/*`. Who serves it — FastAPI
// or the Nano SW→Pyodide router — is transparent here. There is NO `if (nano)` /
// `if (local)` branching anywhere in the UI; substrate differences arrive as data
// via the capability manifest below (§15.2).

const API_BASE = (window.__VY && window.__VY.API_BASE) || '/';

function u(path) {
  // path is always "/api/..."; join against the (sub)path base without doubling.
  const base = API_BASE.endsWith('/') ? API_BASE.slice(0, -1) : API_BASE;
  return base + path;
}

export async function apiGet(path) {
  const r = await fetch(u(path), { headers: { accept: 'application/json' } });
  if (!r.ok) throw await asError(r);
  return r.json();
}

export async function apiSend(method, path, body, isForm) {
  const opts = { method, headers: {} };
  if (isForm) {
    opts.body = body; // FormData — let the browser set the boundary
  } else if (body !== undefined) {
    opts.headers['content-type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(u(path), opts);
  if (!r.ok) throw await asError(r);
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.text();
}

async function asError(r) {
  let detail = r.statusText;
  try {
    const j = await r.json();
    detail = j.detail || j.message || detail;
  } catch (_) { /* non-json body */ }
  const e = new Error(detail);
  e.status = r.status;
  return e;
}

export function apiUrl(path) { return u(path); }

// ── Capability manifest (the single source of substrate/cloud truth) ──
let _caps = null;
export async function loadCapabilities() {
  if (_caps) return _caps;
  _caps = await apiGet('/api/console/capabilities');
  return _caps;
}
export function capabilities() { return _caps; }

// widgetMode(id) -> "full" | "generic" | "degraded" | "partial" | undefined
export function widgetMode(widgetId) {
  return _caps && _caps.widgets ? _caps.widgets[widgetId] : undefined;
}
export function feature(name) {
  return !!(_caps && _caps.features && _caps.features[name]);
}
