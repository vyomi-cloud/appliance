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


def _arm_dispatch(backends: Backends, method: str, params: dict) -> dict:
    """Native Azure Resource Manager control plane. Unlike the generic
    catalog CRUD (which rides /api/{cloud}/{service} paths), the Azure console
    speaks real ARM — /subscriptions/{sub}/resourceGroups/{rg}/providers/
    Microsoft.X/{type}/{name}?api-version= — served verbatim by the substrate-
    free AzureArm core (the in-WASM analogue of azure_services.handle_arm).
    `operation` carries the HTTP method; params carries {path, query, body}.
    Returns the raw HTTP envelope under __http so the SW can honour the real
    ARM status code, headers (Azure-AsyncOperation/Location) and body."""
    arm = getattr(backends, "_azure_arm", None)
    if arm is None:
        from core.azure_arm_core import AzureArm
        arm = AzureArm()
        backends._azure_arm = arm
    resp = arm.handle(method, params.get("path", ""),
                      params.get("query") or {}, params.get("body"))
    return {"ok": resp["status"] < 400, "__http": resp}


# Per-resource weights — kept identical to the appliance's host-distribution
# (server.py) so the Nano dashboard reports the SAME footprint the full appliance
# would: a VM ~ 2 vCPU / 2 GiB / 8 GB, a light resource (bucket, table, key, …) ~ 1/4 VM.
_PER_VM = {"vcpu": 2.0, "ram_mb": 2048, "disk_mb": 8192}
_PER_LIGHT = {"vcpu": 0.5, "ram_mb": 512, "disk_mb": 2048}
# Which catalog/ARM service keys count as a VM (heavier weight) per cloud.
_VM_SERVICES = {
    "aws": {"ec2", "rds"},
    "gcp": {"compute", "gce", "instances", "computeengine"},
    "azure": {"microsoft.compute/virtualmachines"},
}


def _weigh(resources: int, vms: int) -> dict:
    light = max(0, resources - vms)
    return {
        "vcpus":   round(vms * _PER_VM["vcpu"]   + light * _PER_LIGHT["vcpu"],   2),
        "ram_mb":  int(vms * _PER_VM["ram_mb"]   + light * _PER_LIGHT["ram_mb"]),
        "disk_mb": int(vms * _PER_VM["disk_mb"]  + light * _PER_LIGHT["disk_mb"]),
    }


def _census_dispatch(backends: Backends, provider: str) -> dict:
    """Count the LIVE in-memory resources this page's backend holds for `provider`,
    across every core store, and weight them the same way the appliance does. The
    console page runs this and persists the result so the (Pyodide-less) dashboard
    can show a REAL per-cloud footprint instead of a nominal per-space estimate."""
    provider = (provider or "").lower()
    by_service: dict[str, int] = {}
    vms = 0
    try:
        # AWS data-plane services are served by the proven cores (module-level
        # singletons in aws_core_adapter), not the generic ResourceStore — count
        # them via the same list handlers the console uses.
        if provider == "aws":
            from . import aws_core_adapter as A
            aws_counts = {
                "s3":             len(A.s3_list_buckets().get("buckets", [])),
                "dynamodb":       len(A.ddb_list_tables().get("tables", [])),
                "kms":            len(A.kms_list_keys().get("value", [])),
                "secretsmanager": len(A.secrets_list().get("value", [])),
                "sqs":            len(A.sqs_list_queues().get("queues", [])),
                "iam": (len(A.iam_list_users().get("users", [])) +
                        len(A.iam_list_roles().get("roles", [])) +
                        len(A.iam_list_policies().get("policies", [])) +
                        len(A.iam_list_groups().get("groups", []))),
                "rds":            len(A.rds_list().get("databases", [])),
            }
            for svc, n in aws_counts.items():
                if n:
                    by_service[svc] = by_service.get(svc, 0) + n
            vms += aws_counts["rds"]  # DB instances are VM-like

        # Generic catalog CRUD collections (EC2, Lambda, and every GCP service)
        # live in the shared ResourceStore, namespaced "provider/account/service".
        vm_svcs = _VM_SERVICES.get(provider, set())
        prefix = provider + "/"
        for key, coll in getattr(backends.resources, "_c", {}).items():
            if not key.startswith(prefix):
                continue
            svc = key.rsplit("/", 1)[-1]
            n = len(coll)
            if not n:
                continue
            by_service[svc] = by_service.get(svc, 0) + n
            if svc.lower() in vm_svcs:
                vms += n

        # Azure resources live in the ARM core's flat state, keyed by resource id.
        if provider == "azure":
            arm = getattr(backends, "_azure_arm", None)
            for rid in getattr(arm, "_state", {}) or {}:
                i = rid.find("/providers/")
                if i < 0:
                    continue  # resource groups etc. have no /providers/ segment
                tail = rid[i + len("/providers/"):].split("/")
                if len(tail) < 2:
                    continue
                rtype = (tail[0] + "/" + tail[1]).lower()
                by_service[rtype] = by_service.get(rtype, 0) + 1
                if rtype in _VM_SERVICES["azure"]:
                    vms += 1
    except Exception as e:  # census is best-effort — never break a console
        return {"ok": True, "provider": provider, "resources": 0, "vms": 0,
                "by_service": {}, "error": str(e), **_weigh(0, 0)}

    resources = sum(by_service.values())
    return {"ok": True, "provider": provider, "resources": resources, "vms": vms,
            "by_service": by_service, **_weigh(resources, vms)}


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
    # Native Azure ARM control plane (real /subscriptions/* wire).
    if service == "_arm":
        return _arm_dispatch(backends, operation, params or {})
    # Live resource census for the dashboard's per-cloud footprint pies.
    if service == "_census":
        return _census_dispatch(backends, provider)
    h = p.handlers().get((service, operation))
    if h is None:
        return {"ok": False, "code": "UnsupportedOperation",
                "provider": provider, "service": service, "operation": operation}
    out = h(backends, account, params or {})
    out.setdefault("ok", True)
    return out
