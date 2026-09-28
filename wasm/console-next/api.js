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

// ── reveal-CLI (§12.8 / §13.1) ──
// One shared helper so any primary action can surface its equivalent CLI/SDK line,
// uniformly across widgets. It reuses the descriptor's `service.connect.cli` (the
// SAME data the Connect block already shows) plus the widget's own action context,
// and does light {placeholder} substitution. It is cloud/substrate-agnostic — the
// command text comes entirely from data (the manifest + the caller's ctx), never
// from an if(cloud)/if(substrate) branch (§15.2). Falls back to an explicit
// per-action command if the caller supplies one and the descriptor has no cli.
//
//   cliForAction(service, { command, ctx })
//     service  — the selected service descriptor (may carry service.connect.cli)
//     command  — optional widget-supplied CLI line for THIS action (preferred)
//     ctx      — { bucket, key, db, table, queue, ... } for {placeholder} fill-in
export function cliForAction(service, opts) {
  const o = opts || {};
  const connect = (service && service.connect) || {};
  // Prefer the action-specific command the widget passes in; else reuse the
  // descriptor's connect.cli (the same line the Connect block reveals).
  let cmd = o.command || connect.cli || '';
  const ctx = o.ctx || {};
  return String(cmd).replace(/\{(\w+)\}/g, (m, k) =>
    (ctx[k] != null ? String(ctx[k]) : m));
}

// ── Familiar mode (§7 — "recognizable, not cloned") ──
// OPTIONAL native-lens THEME. This is theming only: it sets a `data-vy-familiar`
// attribute on <html>, which tokens.css uses to override design tokens (accent /
// spacing) — every Shadow-DOM component re-themes via inherited custom properties,
// no component is forked and NO behaviour changes (§7, §15.2). The choice persists
// in localStorage. The attribute value tracks the current cloud lens so the accent
// matches AWS/GCP/Azure; turning it off removes the attribute with zero residue.
const _FAMILIAR_KEY = 'vy.console.familiar';

export function isFamiliar() {
  try { return localStorage.getItem(_FAMILIAR_KEY) === '1'; }
  catch (_) { return false; }
}

// setFamiliar(on, lens) — apply/remove the theme, persist the choice, and return the
// resolved boolean. `lens` selects which provider accent to theme toward (default
// aws). Safe to call repeatedly (idempotent) and on any (re)mount / lens switch.
export function setFamiliar(on, lens) {
  const el = (typeof document !== 'undefined') && document.documentElement;
  const l = (lens || 'aws').toLowerCase();
  if (on) {
    if (el) el.setAttribute('data-vy-familiar', l);
    try { localStorage.setItem(_FAMILIAR_KEY, '1'); } catch (_) { /* private mode */ }
    return true;
  }
  if (el) el.removeAttribute('data-vy-familiar');
  try { localStorage.setItem(_FAMILIAR_KEY, '0'); } catch (_) { /* private mode */ }
  return false;
}
