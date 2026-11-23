"""Enforcement modes: resolve off | audit | enforce per request (resource > service > space > global).

Pure Python (no fastapi / socket). The settings document is per space and identical on every cloud:
  {"global": "off", "space": "off", "services": {"s3": "audit"}, "resources": {"arn:aws:s3:::b": "enforce"},
   "allowUnmapped": false}
Default everything `off`. Resource keys are the vendor resource names (Azure ids compare case-insensitively)."""
from __future__ import annotations

import copy

from core.iam_engine.types import MODES

CLOUDS = ("aws", "gcp", "azure")
SETTINGS_KEY = "iam_enforcement"          # where a host keeps the document on its space dict
_SCALARS = ("global", "space")


def default_settings() -> dict:
    return {"global": "off", "space": "off", "services": {}, "resources": {}, "allowUnmapped": False}


def _norm_mode(value):
    m = str(value).strip().lower() if value is not None else ""
    return m if m in MODES else None


def validate(doc) -> tuple[dict, list]:
    """Return (normalised settings, errors). Unknown top-level keys are rejected; a bad mode is an error (never silently coerced)."""
    errors: list = []
    out = default_settings()
    if doc is None:
        return out, errors
    if not isinstance(doc, dict):
        return out, ["settings must be an object"]
    for k in doc:
        if k not in ("global", "space", "services", "resources", "allowUnmapped"):
            errors.append(f"unknown key '{k}'")
    for k in _SCALARS:
        if k in doc:
            m = _norm_mode(doc[k])
            if m is None:
                errors.append(f"'{k}' must be one of {list(MODES)}")
            else:
                out[k] = m
    for k in ("services", "resources"):
        if k in doc:
            if not isinstance(doc[k], dict):
                errors.append(f"'{k}' must be an object")
                continue
            for name, val in doc[k].items():
                m = _norm_mode(val)
                if not isinstance(name, str) or not name.strip():
                    errors.append(f"'{k}' has an empty key")
                elif m is None:
                    errors.append(f"'{k}.{name}' must be one of {list(MODES)}")
                else:
                    out[k][name] = m
    if "allowUnmapped" in doc:
        if isinstance(doc["allowUnmapped"], bool):
            out["allowUnmapped"] = doc["allowUnmapped"]
        else:
            errors.append("'allowUnmapped' must be a boolean")
    return out, errors


def _lookup(table, key, ci):
    if not isinstance(table, dict) or key is None:
        return None
    if key in table:
        return _norm_mode(table[key])
    if ci:
        low = str(key).lower()
        for k, v in table.items():
            if str(k).lower() == low:
                return _norm_mode(v)
    return None


def resolve_mode(cloud, settings, service=None, resource_id=None) -> str:
    """Most specific wins: resource > service > space > global; default off. Malformed entries are skipped, never raise."""
    if not isinstance(settings, dict):
        return "off"
    ci = str(cloud).lower() == "azure"
    m = _lookup(settings.get("resources"), resource_id, ci)
    if m:
        return m
    m = _lookup(settings.get("services"), service, True)
    if m:
        return m
    return _norm_mode(settings.get("space")) or _norm_mode(settings.get("global")) or "off"


def any_active(settings) -> bool:
    """Cheap pre-check so a host can skip all request work when everything is off."""
    if not isinstance(settings, dict):
        return False
    vals = [settings.get("global"), settings.get("space")]
    vals += list((settings.get("services") or {}).values()) + list((settings.get("resources") or {}).values())
    return any(_norm_mode(v) in ("audit", "enforce") for v in vals)


def set_mode(settings, mode, service=None, resource=None):
    """Return a copy of `settings` with one level changed (resource > service > space)."""
    m = _norm_mode(mode)
    if m is None:
        raise ValueError(f"mode must be one of {list(MODES)}")
    out, _ = validate(settings)
    out = copy.deepcopy(out)
    if resource:
        out["resources"][resource] = m
    elif service:
        out["services"][service] = m
    else:
        out["space"] = m
    return out


def get_settings(holder) -> dict:
    """Read the document from a host dict (a space) ; invalid/missing -> defaults."""
    doc = holder.get(SETTINGS_KEY) if isinstance(holder, dict) else None
    out, errs = validate(doc)
    return out if not errs else default_settings()


def put_settings(holder, doc) -> dict:
    """Validate and store; raises ValueError listing every problem."""
    out, errs = validate(doc)
    if errs:
        raise ValueError("; ".join(errs))
    holder[SETTINGS_KEY] = out
    return out


# ----------------------------------------------------------------------------- injectable persistence
class MemorySettingsStore:
    """Smallest store: one settings document per (space) in memory. Nano backs the same two methods with IDB/OPFS;
    Mesh with the active space dict (see HolderSettingsStore)."""

    def __init__(self):
        self._doc = default_settings()

    def get(self) -> dict:
        return copy.deepcopy(self._doc)

    def put(self, doc) -> dict:
        out, errs = validate(doc)
        if errs:
            raise ValueError("; ".join(errs))
        self._doc = out
        return copy.deepcopy(out)


class HolderSettingsStore:
    """Store over any dict-returning callable (e.g. the active space dict); `persist` is called after a write."""

    def __init__(self, holder_fn, persist=None):
        self._holder_fn, self._persist = holder_fn, persist

    def get(self) -> dict:
        return get_settings(self._holder_fn())

    def put(self, doc) -> dict:
        out = put_settings(self._holder_fn(), doc)
        if self._persist:
            self._persist()
        return out
