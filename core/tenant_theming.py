"""Tier-feature implementation: custom_domain + branding (Enterprise tier).

Both are per-tenant configuration that the request middleware and console
pages read to switch behavior:

  custom_domain — operator maps a domain (e.g. "cloud.acme.com") → tenant.
    When the simulator receives a request whose Host header matches, the
    active tenant is set to that tenant for the duration of the request
    (no /api/tenants/{id}/switch round-trip needed).

  branding — per-tenant logo URL + primary color + product name override.
    Console pages fetch /api/runtime/branding/{tenant}.css to apply these.

State:
  STATE["custom_domains"]    → { "cloud.acme.com": "acme-tenant-id" }
  STATE["tenant_branding"][tenant_id] → { logo_url, primary_color, name_override, favicon_url }
"""
from __future__ import annotations

import re
import time
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


# ── custom_domain ───────────────────────────────────────────────────────────

# A relaxed FQDN check — at least one dot, only label chars and dots.
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


def _domain_map(state: dict) -> dict:
    return state.setdefault("custom_domains", {})


def set_custom_domain(state: dict, tenant_id: str, domain: str) -> dict:
    domain = domain.strip().lower()
    if not _DOMAIN_RE.match(domain):
        raise ValueError(f"invalid domain: {domain!r}")
    dm = _domain_map(state)
    # Remove any existing mapping owned by this tenant (one domain per tenant)
    for d, owner in list(dm.items()):
        if owner == tenant_id and d != domain:
            dm.pop(d, None)
    dm[domain] = tenant_id
    return {"domain": domain, "tenant_id": tenant_id, "set_at": _now_iso()}


def get_custom_domain(state: dict, tenant_id: str) -> str | None:
    for d, owner in (state.get("custom_domains") or {}).items():
        if owner == tenant_id:
            return d
    return None


def delete_custom_domain(state: dict, tenant_id: str) -> bool:
    dm = _domain_map(state)
    removed = False
    for d, owner in list(dm.items()):
        if owner == tenant_id:
            dm.pop(d, None)
            removed = True
    return removed


def resolve_domain_to_tenant(state: dict, host: str) -> str | None:
    """Used by the middleware: given a Host header, return the tenant_id that
    claimed this domain, or None. Strips port if present."""
    if not host:
        return None
    host = host.split(":", 1)[0].strip().lower()
    return (state.get("custom_domains") or {}).get(host)


# ── branding ────────────────────────────────────────────────────────────────

_DEFAULT_BRANDING = {
    "name_override": "",
    "logo_url": "",
    "favicon_url": "",
    "primary_color": "#2563eb",
    "accent_color": "#0a7d36",
    "header_bg": "#0f1b2d",
    "header_fg": "#ffffff",
}


def _color_ok(s: str) -> bool:
    return bool(re.match(r"^#[0-9A-Fa-f]{6}$", s or ""))


def _url_ok(s: str) -> bool:
    return s.startswith(("http://", "https://", "/")) and len(s) <= 2048


def get_branding(state: dict, tenant_id: str) -> dict:
    b = (state.get("tenant_branding") or {}).get(tenant_id) or {}
    return {**_DEFAULT_BRANDING, **b}


def set_branding(state: dict, tenant_id: str, spec: dict) -> dict:
    bmap = state.setdefault("tenant_branding", {})
    current = bmap.get(tenant_id) or {}
    updated = dict(current)
    for k in ("name_override", "logo_url", "favicon_url"):
        if k in spec:
            v = str(spec[k] or "").strip()
            if v and k.endswith("_url") and not _url_ok(v):
                raise ValueError(f"{k} must be http(s):// or /-prefixed path")
            updated[k] = v
    for k in ("primary_color", "accent_color", "header_bg", "header_fg"):
        if k in spec:
            v = str(spec[k] or "").strip()
            if v and not _color_ok(v):
                raise ValueError(f"{k} must be #RRGGBB hex")
            updated[k] = v
    updated["updated_at"] = _now_iso()
    bmap[tenant_id] = updated
    return get_branding(state, tenant_id)


def branding_css(state: dict, tenant_id: str) -> str:
    """Render the tenant's branding as a CSS snippet consoles inject into
    their <head>. CSS variables let downstream pages compose them with their
    own selectors."""
    b = get_branding(state, tenant_id)
    name = (b.get("name_override") or "CloudLearn").replace('"', "'")
    return f"""\
/* CloudLearn branding — tenant: {tenant_id} */
:root {{
  --cl-primary: {b['primary_color']};
  --cl-accent:  {b['accent_color']};
  --cl-hdr-bg:  {b['header_bg']};
  --cl-hdr-fg:  {b['header_fg']};
  --cl-name:    "{name}";
}}
.cl-branded-name::after {{ content: var(--cl-name); }}
.cl-branded-logo {{ {f'background-image: url("{b["logo_url"]}");' if b.get('logo_url') else 'display: none;'} }}
.cl-header {{ background: var(--cl-hdr-bg); color: var(--cl-hdr-fg); }}
.cl-primary-btn,
button.cta.primary {{ background: var(--cl-primary); }}
.cl-accent {{ color: var(--cl-accent); }}
"""
