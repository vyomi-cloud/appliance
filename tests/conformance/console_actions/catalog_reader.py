"""Unified catalog reader — fetches via HTTP from a running simulator.

Originally tried importing providers/aws_catalog.py directly, but that
pulls in fastapi / pydantic / the whole simulator codebase, which makes
the harness un-installable on a clean machine. The simulator already
exposes its catalogs at /api/{aws,gcp,azure}/catalog for the consoles
to consume — we use the same source.

Net win: zero Python-import dependencies on the simulator. The harness
works in any venv that has `requests` + `pytest`.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any, Optional


_BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://127.0.0.1:9000").rstrip("/")


@dataclass
class ActionSpec:
    provider:           str
    service:            str
    action:             str
    method:             str
    path:               str
    payload:            Optional[dict] = None
    requires_resource:  bool = False
    expected_status:    tuple[int, ...] = field(default_factory=lambda: (200, 201, 202, 204))
    notes:              str = ""
    # Backend's canonical id field on the create response. Pulled from the
    # catalog's `name_field`. The harness uses this when capturing the
    # created resource's identifier so subsequent get/delete tests target
    # the correct resource (avoids picking "name" when the resource_path
    # actually wants "vpc_id" — that was the classic 404-after-create bug).
    name_field:         str = ""

    @property
    def test_id(self) -> str:
        return f"{self.provider}.{self.service}.{self.action}"


def _fetch_catalog(path: str) -> Any:
    """Best-effort fetch — returns None if the endpoint isn't there."""
    import requests
    try:
        r = requests.get(f"{_BASE_URL}{path}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── AWS ──────────────────────────────────────────────────────────────────────

def _read_aws() -> list[ActionSpec]:
    cat = _fetch_catalog("/api/aws/catalog")
    if not cat:
        return []
    services = cat.get("services") if isinstance(cat, dict) else cat
    if not isinstance(services, list):
        return []
    specs: list[ActionSpec] = []
    from .sample_payloads import payload_for
    for svc in services:
        key = str(svc.get("key", "")).strip()
        if not key:
            continue
        coll = str(svc.get("collection_path", "")).strip()
        res = str(svc.get("resource_path", "")).strip()
        name_field = str(svc.get("name_field") or "").strip()
        if coll:
            specs.append(ActionSpec(
                provider="aws", service=key, action="list",
                method="GET", path=coll, name_field=name_field,
            ))
            # Honor create_path override (S3 — POST /api/s3/buckets/{name})
            create_template = str(svc.get("create_path") or coll)
            specs.append(ActionSpec(
                provider="aws", service=key, action="create",
                method=str(svc.get("create_method") or "POST").upper(),
                path=create_template, payload=payload_for("aws", key),
                requires_resource="{name}" in create_template,
                name_field=name_field,
            ))
        if res:
            specs.append(ActionSpec(
                provider="aws", service=key, action="get",
                method="GET", path=res, requires_resource=True,
                name_field=name_field,
            ))
        api_paths = svc.get("api_paths") or {}
        for action_name, api_path in api_paths.items():
            if not isinstance(api_path, dict):
                continue
            specs.append(ActionSpec(
                provider="aws", service=key, action=action_name,
                method=str(api_path.get("method", "POST")).upper(),
                path=str(api_path.get("path", "")),
                requires_resource="{name}" in str(api_path.get("path", "")),
                name_field=name_field,
            ))
        # Auto-append a delete spec from resource_path ONLY if api_paths
        # didn't already declare its own delete. Otherwise the harness runs
        # the same delete twice and the second one 404s on a tombstone — a
        # false negative that masks real failures.
        if res and "delete" not in api_paths:
            specs.append(ActionSpec(
                provider="aws", service=key, action="delete",
                method="DELETE", path=res, requires_resource=True,
                name_field=name_field,
            ))
    return specs


# ── GCP ──────────────────────────────────────────────────────────────────────

def _read_gcp() -> list[ActionSpec]:
    cat = _fetch_catalog("/api/gcp/catalog")
    if not cat:
        return []
    services = cat.get("services") if isinstance(cat, dict) else cat
    if not isinstance(services, list):
        return []
    specs: list[ActionSpec] = []
    from .sample_payloads import payload_for
    for svc in services:
        key = str(svc.get("key", "")).strip()
        if not key:
            continue
        coll = str(svc.get("collection_path", "")).strip()
        res = str(svc.get("resource_path", "")).strip()
        name_field = str(svc.get("name_field") or "").strip()
        if coll:
            specs.append(ActionSpec(
                provider="gcp", service=key, action="list",
                method="GET", path=coll, name_field=name_field,
            ))
            specs.append(ActionSpec(
                provider="gcp", service=key, action="create",
                method=str(svc.get("create_method") or "POST").upper(),
                path=coll, payload=payload_for("gcp", key),
                name_field=name_field,
            ))
        if res:
            specs.append(ActionSpec(
                provider="gcp", service=key, action="get",
                method="GET", path=res, requires_resource=True,
                name_field=name_field,
            ))
        api_paths = svc.get("api_paths") or {}
        for action_name, api_path in api_paths.items():
            if not isinstance(api_path, dict):
                continue
            specs.append(ActionSpec(
                provider="gcp", service=key, action=action_name,
                method=str(api_path.get("method", "POST")).upper(),
                path=str(api_path.get("path", "")),
                requires_resource="{name}" in str(api_path.get("path", "")),
                name_field=name_field,
            ))
        # Auto-append a delete spec from resource_path ONLY if api_paths
        # didn't already declare its own delete. Otherwise the harness runs
        # the same delete twice and the second one 404s on a tombstone — a
        # false negative that masks real failures.
        if res and "delete" not in api_paths:
            specs.append(ActionSpec(
                provider="gcp", service=key, action="delete",
                method="DELETE", path=res, requires_resource=True,
                name_field=name_field,
            ))
    return specs


# ── Azure ────────────────────────────────────────────────────────────────────

def _read_azure() -> list[ActionSpec]:
    cat = _fetch_catalog("/api/azure/catalog")
    if not cat:
        return []
    services = cat.get("services") if isinstance(cat, dict) else cat
    if not isinstance(services, list):
        return []
    specs: list[ActionSpec] = []
    from .sample_payloads import payload_for
    for svc in services:
        key = str(svc.get("key", "")).strip()
        if not key:
            continue
        namespace = svc.get("namespace") or "Microsoft.Compute"
        rtype = svc.get("type") or "virtualMachines"
        coll = (
            f"/subscriptions/sim-sub/resourceGroups/cloudlearn-rg/"
            f"providers/{namespace}/{rtype}"
        )
        res = coll + "/{name}"
        specs.append(ActionSpec(
            provider="azure", service=key, action="list",
            method="GET", path=coll,
        ))
        specs.append(ActionSpec(
            provider="azure", service=key, action="create",
            method="PUT", path=res.replace("{name}", f"vyomi-conf-{key}"),
            payload=payload_for("azure", key), requires_resource=True,
        ))
        specs.append(ActionSpec(
            provider="azure", service=key, action="get",
            method="GET", path=res, requires_resource=True,
        ))
        specs.append(ActionSpec(
            provider="azure", service=key, action="delete",
            method="DELETE", path=res, requires_resource=True,
        ))
    return specs


def enumerate_actions(providers: Optional[list[str]] = None) -> list[ActionSpec]:
    providers = providers or ["aws", "gcp", "azure"]
    out: list[ActionSpec] = []
    if "aws"   in providers: out.extend(_read_aws())
    if "gcp"   in providers: out.extend(_read_gcp())
    if "azure" in providers: out.extend(_read_azure())
    # Sort so the harness runs actions in lifecycle order WITHIN each
    # service: create FIRST (so subsequent get/delete have a real id),
    # list / get next (idempotent reads), lifecycle in the middle,
    # delete LAST (cleans up). Without this, parameterized pytest runs
    # alphabetically, which kicks 'delete' before 'create' and produces
    # a flood of false-positive 404s on resources that never existed.
    _ACTION_ORDER = {
        "create": 0, "list": 1, "get": 2,
        # lifecycle / sub-actions middle
        "start": 4, "restart": 4, "reboot": 4, "stop": 5,
        "modify": 5, "update": 5, "patch": 5,
        # destructive last
        "purge": 8, "terminate": 9, "delete": 9,
    }
    # Sub-resource action prefixes that depend on a prior sub-create
    # (e.g. addIngress needs createSecurityGroup; addRoute needs
    # createRouteTable + createIgw). Schedule AFTER parent + sub-creates
    # but before delete.
    _DEP_PREFIXES = ("add", "attach", "associate", "put", "set")
    def _order_for(action: str) -> int:
        if action in _ACTION_ORDER:
            return _ACTION_ORDER[action]
        if action.startswith("create"):
            return 3  # sub-resource creates run right after parent create
        if action.startswith(_DEP_PREFIXES):
            return 6  # depend on sub-create having captured an id
        return 7
    def sort_key(s: ActionSpec):
        return (s.provider, s.service, _order_for(s.action), s.action)
    out.sort(key=sort_key)
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Enumerate console action specs")
    p.add_argument("--provider", action="append", choices=["aws", "gcp", "azure"])
    args = p.parse_args()
    specs = enumerate_actions(args.provider)
    by = {}
    for s in specs: by[s.provider] = by.get(s.provider, 0) + 1
    print(f"Total: {len(specs)} actions")
    for k, v in sorted(by.items()): print(f"  {k}: {v}")
