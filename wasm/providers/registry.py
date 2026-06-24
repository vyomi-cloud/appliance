"""Cloud-provider plugin registry for the WASM (Nano) substrate.

ADDING A NEW CLOUD (Oracle, IBM, Alibaba, DigitalOcean, ...) is additive:
write a module that subclasses CloudProvider, map its API operations to the
shared generic backends (object-store / nosql / queue / ...), and call
`register(MyCloud())`. No core change, no new storage logic, no fork — exactly
the ADR-001 model carried into the browser.

The service worker (sw.js) hands each intercepted SDK request to `dispatch()`,
which routes (provider, service, operation, params) to the right plugin.
"""
from __future__ import annotations

from typing import Any, Callable

from ..backends.store import Backends

# An operation handler: (backends, account, params) -> response dict
Handler = Callable[[Backends, str, dict], dict]


class CloudProvider:
    """Base class. A cloud declares its id + a map of (service, op) -> handler."""
    id: str = ""           # "aws" | "gcp" | "azure" | "oracle" | ...
    label: str = ""
    # how the SW recognises this cloud's requests (host suffix / path prefix /
    # x-amz-target style). Kept declarative so the SW stays provider-agnostic.
    match_hosts: tuple[str, ...] = ()
    match_paths: tuple[str, ...] = ()

    def handlers(self) -> dict[tuple[str, str], Handler]:
        """Return {(service, operation): handler}. Override in each cloud."""
        return {}


_REGISTRY: dict[str, CloudProvider] = {}


def register(provider: CloudProvider) -> None:
    if not provider.id:
        raise ValueError("provider.id is required")
    _REGISTRY[provider.id] = provider


def providers() -> list[str]:
    return sorted(_REGISTRY)


def _resource_dispatch(backends: Backends, provider: str, operation: str,
                       account: str, params: dict) -> dict:
    """Generic catalog-driven CRUD, cloud-agnostic. The console drives every
    service the same way (list/create on collection_path, get/update/delete on
    resource_path), so one handler backs them all. `params.service` is the
    catalog service key (ec2, s3, iam, …); `params.name` the resource id."""
    r = backends.resources
    svc = params.get("service", "")
    name = params.get("name", "")
    body = params.get("body") or {}
    if operation == "List":
        return {"ok": True, "items": r.list(provider, account, svc)}
    if operation == "Create":
        return {"ok": True, **r.create(provider, account, svc, body)}
    if operation == "Get":
        rec = r.get(provider, account, svc, name)
        return {"ok": True, **rec} if rec else {"ok": False, "code": "NotFound", "name": name}
    if operation == "Update":
        rec = r.update(provider, account, svc, name, body)
        return {"ok": True, **rec} if rec else {"ok": False, "code": "NotFound", "name": name}
    if operation == "Delete":
        ok = r.delete(provider, account, svc, name)
        return {"ok": ok, "code": None if ok else "NotFound", "name": name}
    return {"ok": False, "code": "UnsupportedOperation", "operation": operation}


def dispatch(backends: Backends, provider: str, service: str, operation: str,
             account: str = "default", params: dict | None = None) -> dict:
    """Route one call to the right cloud plugin's handler."""
    p = _REGISTRY.get(provider)
    if p is None:
        return {"ok": False, "code": "UnknownProvider", "provider": provider,
                "available": providers()}
    # Generic catalog-driven CRUD — handled centrally, not per-cloud, so a new
    # cloud's services get list/create/get/update/delete for free.
    if service == "_resource":
        return _resource_dispatch(backends, provider, operation, account, params or {})
    h = p.handlers().get((service, operation))
    if h is None:
        return {"ok": False, "code": "UnsupportedOperation",
                "provider": provider, "service": service, "operation": operation}
    out = h(backends, account, params or {})
    out.setdefault("ok", True)
    return out
