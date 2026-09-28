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
// Lens-aware: each cloud lens (aws|gcp|…) has its own manifest. `capabilities()`
// returns whichever lens was loaded most recently — the CURRENT lens. Switching
// lenses re-fetches (cached per lens); the UI re-renders purely from the returned
// data — no if(cloud) branching anywhere (§15.2).
let _caps = null;
const _byLens = {};
export async function loadCapabilities(lens) {
  const l = (lens || 'aws').toLowerCase();
  if (_byLens[l]) { _caps = _byLens[l]; return _caps; }
  const caps = await apiGet('/api/console/capabilities?lens=' + encodeURIComponent(l));
  _byLens[l] = caps;
  _caps = caps;
  return caps;
}
export function capabilities() { return _caps; }

// widgetMode(id) -> "full" | "generic" | "degraded" | "partial" | undefined
export function widgetMode(widgetId) {
  return _caps && _caps.widgets ? _caps.widgets[widgetId] : undefined;
}
// degradeNote(id) -> substrate-driven CTA copy for a degraded/partial widget, or ''.
// Read from the manifest's degrade_notes map (§14.9) — capability-driven, the caller
// never checks the substrate name (§15.2).
export function degradeNote(widgetId) {
  return (_caps && _caps.degrade_notes && _caps.degrade_notes[widgetId]) || '';
}
export function feature(name) {
  return !!(_caps && _caps.features && _caps.features[name]);
}
