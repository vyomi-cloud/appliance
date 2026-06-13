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
        if coll:
            specs.append(ActionSpec(
                provider="aws", service=key, action="list",
                method="GET", path=coll,
            ))
            specs.append(ActionSpec(
                provider="aws", service=key, action="create",
                method=str(svc.get("create_method") or "POST").upper(),
                path=coll, payload=payload_for("aws", key),
            ))
        if res:
            specs.append(ActionSpec(
                provider="aws", service=key, action="get",
                method="GET", path=res, requires_resource=True,
            ))
        for action_name, api_path in (svc.get("api_paths") or {}).items():
            if not isinstance(api_path, dict):
                continue
            specs.append(ActionSpec(
                provider="aws", service=key, action=action_name,
                method=str(api_path.get("method", "POST")).upper(),
                path=str(api_path.get("path", "")),
                requires_resource="{name}" in str(api_path.get("path", "")),
            ))
        if res:
            specs.append(ActionSpec(
                provider="aws", service=key, action="delete",
                method="DELETE", path=res, requires_resource=True,
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
        if coll:
            specs.append(ActionSpec(
                provider="gcp", service=key, action="list",
                method="GET", path=coll,
            ))
            specs.append(ActionSpec(
                provider="gcp", service=key, action="create",
                method=str(svc.get("create_method") or "POST").upper(),
                path=coll, payload=payload_for("gcp", key),
            ))
        if res:
            specs.append(ActionSpec(
                provider="gcp", service=key, action="get",
                method="GET", path=res, requires_resource=True,
            ))
        for action_name, api_path in (svc.get("api_paths") or {}).items():
            if not isinstance(api_path, dict):
                continue
            specs.append(ActionSpec(
                provider="gcp", service=key, action=action_name,
                method=str(api_path.get("method", "POST")).upper(),
                path=str(api_path.get("path", "")),
                requires_resource="{name}" in str(api_path.get("path", "")),
            ))
        if res:
            specs.append(ActionSpec(
                provider="gcp", service=key, action="delete",
                method="DELETE", path=res, requires_resource=True,
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
