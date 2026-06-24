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


def dispatch(backends: Backends, provider: str, service: str, operation: str,
             account: str = "default", params: dict | None = None) -> dict:
    """Route one call to the right cloud plugin's handler."""
    p = _REGISTRY.get(provider)
    if p is None:
        return {"ok": False, "code": "UnknownProvider", "provider": provider,
                "available": providers()}
    h = p.handlers().get((service, operation))
    if h is None:
        return {"ok": False, "code": "UnsupportedOperation",
                "provider": provider, "service": service, "operation": operation}
    out = h(backends, account, params or {})
    out.setdefault("ok", True)
    return out
