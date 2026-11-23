"""Nano host adapter for the faithful-IAM engine (pure Python, Pyodide-safe). JS side: wasm/nano-iam-hook.js.

Mesh wraps `api.IamApi` in FastAPI and calls `gate.check` from core/middleware.py. Nano does the same two things from here, with the same
engine, so behaviour is identical:

  api(cloud_method, path, query_json, body_json)   the /api/iam/<cloud>/... routes  (IamApi.handle)
  check(req_json, settings_json)                   the request-time decision        (gate.check)

Results are JSON strings; both can answer {"need": [[cloud, service], ...]} = "prefetch these catalogs, preload() them, call again" (Python
cannot await fetch(); catalogs are loaded lazily per service, never at boot). Everything environment-specific is injected by the JS host:

  host.get_settings(cloud) -> json str | None     per-space enforcement document (JS cache over IndexedDB; sync)
  host.put_settings(cloud, json_str)              persist + broadcast
  host.audit_push(json_str)                       append one record to the shared ring (IndexedDB + BroadcastChannel)
  host.audit_list(cloud) -> json str              all records of the shared ring, newest first
  host.audit_clear()

State + principal come from core/iam_state_adapters.py (the SAME adapters Mesh uses) bound to Nano's registry stores (core.nano_registry)."""
from __future__ import annotations

import base64
import json

from core.iam_engine import catalog_loader

_host = None
_known = {}          # cloud -> set(service) available as catalogs in this bundle (from the manifest)
_have = set()        # (cloud, service) already preloaded
_apis = {}
_inventory = None
_inventory_loaded = False
_state_override = None


def configure(host, manifest_catalogs_json="{}"):
    global _host, _known
    _host = host
    _known = {c: set(v) for c, v in json.loads(manifest_catalogs_json or "{}").items()}
    _apis.clear()


def set_state_override(fn):
    """fn(cloud, headers, query) -> (state, principal). Tests / alternative hosts."""
    global _state_override
    _state_override = fn


def preload(cloud, service, text):
    catalog_loader.preload(cloud, service, text)
    _have.add((cloud, service))


def preload_inventory(text):
    """wasm/service-inventory.json text, or "null" when the bundle has none (vyomi.simulated is then reported as unknown)."""
    global _inventory, _inventory_loaded
    _inventory, _inventory_loaded = json.loads(text or "null"), True


def _registry():
    from core import nano_registry
    return nano_registry.get()


def state_and_principal(cloud, headers, query=""):
    if _state_override:
        return _state_override(cloud, headers, query)
    from core import iam_state_adapters as A       # vendored when present (Mesh WP); same functions as the appliance
    reg = _registry()
    if cloud == "aws":
        s = reg["iam"]
        return A.aws_state(s), A.aws_principal(headers, query, s)
    if cloud == "gcp":
        st = reg.get("gcp_iam")
        raw = {"policies": getattr(st, "policies", None) or {}, "service_accounts": getattr(st, "service_accounts", None) or {},
               "bindings": getattr(st, "bindings", None) or []}
        return A.gcp_state(raw), A.gcp_principal(headers, None)
    arm = reg.get("az_arm")
    return A.azure_state(getattr(arm, "state", None) or {}), A.azure_principal(headers, None)


# ----------------------------------------------------------------------------- host-backed settings + audit
def _modes():
    from core.iam_engine import modes
    return modes


class NanoSettingsStore:
    """get()/put(doc) over the JS host's per-cloud cache (sync); IamApi's settings_store contract."""

    def __init__(self, cloud):
        self.cloud = cloud

    def get(self):
        m = _modes()
        raw = _host.get_settings(self.cloud) if _host is not None else None
        raw = raw if isinstance(raw, str) else None          # JS null arrives as a sentinel, not None
        out, errs = m.validate(json.loads(raw) if raw else None)
        return out if not errs else m.default_settings()

    def put(self, doc):
        m = _modes()
        out, errs = m.validate(doc)
        if errs:
            raise ValueError("; ".join(errs))
        if _host is not None:
            _host.put_settings(self.cloud, json.dumps(out))
        return out


def _audit_cls():
    from core.iam_engine import audit

    class NanoAuditLog(audit.AuditLog):
        """Records locally (same shape as Mesh) and mirrors every record to the shared IndexedDB ring; list() reads the shared ring so the
        page and the relay worker (two Pyodide contexts) show one log."""

        def record(self, *a, **k):
            rec = super().record(*a, **k)
            if _host is not None:
                try:
                    _host.audit_push(json.dumps(rec))
                except Exception:
                    pass
            return rec

        def list(self, limit=100, cloud=None, decision=None, principal=None):
            if _host is None:
                return super().list(limit, cloud, decision, principal)
            try:
                limit = max(0, int(limit))
            except (TypeError, ValueError):
                limit = 100
            out = []
            for r in json.loads(_host.audit_list(cloud or "") or "[]"):
                if (cloud and r.get("cloud") != cloud) or (decision and r.get("decision") != decision) or (principal and r.get("principal") != principal):
                    continue
                out.append(r)
                if len(out) >= limit:
                    break
            return out

        def clear(self):
            super().clear()
            if _host is not None:
                _host.audit_clear()

    return NanoAuditLog


_audit_log = None


def audit_log():
    global _audit_log
    if _audit_log is None:
        _audit_log = _audit_cls()()
    return _audit_log


def _inventory_fn():
    if not _inventory_loaded:
        raise catalog_loader.CatalogUnavailable("_inventory", "service-inventory")
    return _inventory


def _api(cloud):
    if cloud not in _apis:
        from core.iam_engine import api
        _apis[cloud] = api.IamApi(settings_store=NanoSettingsStore(cloud), state_fn=lambda c: state_and_principal(c, {}, "")[0],
                                  catalog_fn=catalog_loader.load, inventory_fn=_inventory_fn, audit_log=audit_log())
    return _apis[cloud]


def api(method, path, query_json="{}", body_json="null"):
    """-> json {"status": int, "body": ...} | {"need": [[cloud, service]]} | {"error": str}"""
    try:
        parts = [p for p in str(path).split("/") if p]
        cloud = parts[2] if len(parts) > 2 else ""
        if cloud not in ("aws", "gcp", "azure"):
            return json.dumps({"status": 404, "body": {"error": f"unknown cloud '{cloud}'"}})
        status, body = _api(cloud).handle(method, path, json.loads(query_json or "{}"), json.loads(body_json or "null"))
        return json.dumps({"status": status, "body": body})
    except catalog_loader.CatalogUnavailable as e:
        return json.dumps({"need": [e.need]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ----------------------------------------------------------------------------- request-time hook
def _need_from_oserror(e):
    import re
    m = re.search(r"iam_catalog[/\\](aws|gcp|azure)[/\\]([^/\\]+)\.json", str(getattr(e, "filename", "") or e))
    return [m.group(1), m.group(2)] if m else None


def _wire(spec):
    body = spec.get("body", b"")
    if isinstance(body, str):
        body = body.encode("utf-8")
    elif not isinstance(body, (bytes, bytearray)):
        body = json.dumps(body).encode("utf-8")
    hdrs = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
    if spec.get("content_type"):
        hdrs["content-type"] = spec["content_type"]
    return {"status": int(spec.get("status") or 403), "headers": hdrs, "body_b64": base64.b64encode(bytes(body)).decode()}


def check(req_json, settings_json):
    """-> json: {"ok":true} | {"deny":{status,headers,body_b64}} | {"need":[[cloud,svc]..]} | {"error":str}"""
    try:
        from core.iam_engine import gate
    except ImportError as e:
        return json.dumps({"error": f"gate unavailable: {e}"})
    try:
        r = json.loads(req_json)
        cloud = r["cloud"]
        headers = {str(k).lower(): v for k, v in (r.get("headers") or {}).items()}
        q = r.get("query") or {}
        qs = q if isinstance(q, str) else "&".join(f"{k}={v}" for k, v in q.items())
        hr = {"method": str(r.get("method", "GET")).upper(), "path": r.get("path", "/"), "query": q, "headers": headers,
              "host": headers.get("host", ""), "body": base64.b64decode(r.get("body_b64") or "")}
        settings = json.loads(settings_json) if settings_json else {}
        state, principal = state_and_principal(cloud, headers, qs)
        hr["principal"] = principal
        # preflight: the op map needs the service catalog; so does anything the engine reads. Python cannot await a fetch: ask the host.
        try:
            perms = gate.required_permissions(cloud, hr)
        except catalog_loader.CatalogUnavailable as e:
            return json.dumps({"need": [e.need]})
        except OSError as e:
            n = _need_from_oserror(e)
            if n is None:
                raise
            return json.dumps({"need": [n]})
        except Exception:
            perms = None          # a mapping error is the gate's to record / fail closed on
        if perms:
            need = []
            for p in perms:
                svc = p.get("service")
                if svc and svc in _known.get(cloud, ()) and (cloud, svc) not in _have and [cloud, svc] not in need:
                    need.append([cloud, svc])
            if need:
                return json.dumps({"need": need})
        spec = gate.check(cloud, hr, state, settings, audit=audit_log(), bypass=lambda _hr: False)
        return json.dumps({"ok": True} if spec is None else {"deny": _wire(spec)})
    except catalog_loader.CatalogUnavailable as e:
        return json.dumps({"need": [e.need]})
    except Exception as e:      # never raise into the dispatch path; the JS side decides open/closed from the modes
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
