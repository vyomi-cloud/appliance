"""Dump the REAL console bootstrap responses to static JSON so the Nano
in-browser harness serves a faithful console — no faked catalog.

The console (static/aws-console.html) boots by fetching:
  /api/spaces/active   -> the active space (gate: must be an aws space)
  /api/aws/catalog     -> services[] with collection_path/resource_path, region, account
  /api/tenants         -> account/username

`/api/aws/catalog` is produced by providers/aws_catalog.build_console_payload(),
which is pure data and imports standalone (the package __init__ drags in fastapi,
so we load the module by path to avoid it). The data-plane (list/create/get/
delete on those paths) is served live in-browser by the wasm/ backend; only
these read-only bootstrap shapes are snapshotted here.

Run:  python3 wasm/build_fixtures.py
"""
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)  # so `core.*` (pure-data deps of the catalog) imports


def _load_by_path(modname, relpath):
    """Import a single module by file path without running its package
    __init__ (which pulls in fastapi/uvicorn — not needed for the data)."""
    pkg = modname.rsplit(".", 1)[0]
    if pkg not in sys.modules:
        p = types.ModuleType(pkg)
        p.__path__ = [os.path.join(ROOT, *pkg.split("."))]
        sys.modules[pkg] = p
    spec = importlib.util.spec_from_file_location(modname, os.path.join(ROOT, relpath))
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


def _aws_catalog():
    m = _load_by_path("providers.aws_catalog", "providers/aws_catalog.py")
    return m.build_console_payload(active_region="us-east-1",
                                   active_account="000000000000")


def _gcp_catalog():
    m = _load_by_path("providers.gcp_catalog", "providers/gcp_catalog.py")
    return m.build_console_payload(active_project="nano-project",
                                   active_region="us-central1")


# A minimal-but-real shell context so the console's space gate passes and the
# account/region chrome renders. Mirrors server.py's _space_payload defaults.
def _space(provider):
    return {
        "space_id": f"nano-{provider}",
        "name": f"Nano {provider.upper()}",
        "provider": provider,
        "status": "running",
        "active_region": "us-east-1",
        "active_account": "000000000000",
    }


FIXTURES = {
    # Console boot (aws-console.html): a single active AWS space.
    "spaces-active.json": {"space": _space("aws")},
    # Launch dashboard (clouds.html) reads /api/spaces as an ARRAY + counts.
    "spaces.json": {"spaces": [_space("aws"), _space("gcp")], "active_space_id": "nano-aws"},
    "tenants.json": {
        "active_tenant_id": "nano",
        "tenants": [{"tenant_id": "nano", "name": "Nano User"}],
    },
    # Dashboard chrome (host/runtime). The page does r.ok?json:null).catch(null)
    # so these are best-effort display values — minimal but plausible.
    "runtime-tier.json": {"tier": "nano", "label": "Nano",
                          "price": {"sym": "₹", "num": "199", "per": "/mo"}},
    "host-cpu.json": {"percent": 7, "cores": 4},
    "host-mem.json": {"percent": 28},
    "host-sizing.json": {"memory_total_mb": 8192, "memory_used_mb": 2294, "cpu_cores": 4},
    "runtime-disk-health.json": {"percent_used": 16, "used_gb": 5, "total_gb": 32, "status": "ok"},
    "runtime-host-distribution.json": {"backends": []},
    "runtime-update-check.json": {"update_available": False, "current": "nano", "latest": "nano"},
}


def main():
    os.makedirs(OUT, exist_ok=True)
    catalog = _aws_catalog()
    with open(os.path.join(OUT, "aws-catalog.json"), "w") as f:
        json.dump(catalog, f)
    svcs = catalog.get("services", [])
    print(f"aws-catalog.json: {len(svcs)} services, "
          f"{os.path.getsize(os.path.join(OUT, 'aws-catalog.json'))} bytes")
    try:
        gcat = _gcp_catalog()
        with open(os.path.join(OUT, "gcp-catalog.json"), "w") as f:
            json.dump(gcat, f)
        print(f"gcp-catalog.json: {len(gcat.get('services', []))} services")
    except Exception as e:
        print(f"gcp-catalog.json: SKIPPED ({type(e).__name__}: {e})")
    for name, body in FIXTURES.items():
        with open(os.path.join(OUT, name), "w") as f:
            json.dump(body, f)
        print(f"{name}: ok")
    # Emit the route table the SW needs (collection/resource paths -> service key)
    routes = [
        {"key": s.get("key"), "name": s.get("name"),
         "collection": s.get("collection_path"), "resource": s.get("resource_path"),
         "create_method": s.get("create_method", "POST")}
        for s in svcs if s.get("collection_path")
    ]
    with open(os.path.join(OUT, "routes.json"), "w") as f:
        json.dump(routes, f)
    print(f"routes.json: {len(routes)} CRUD routes")


if __name__ == "__main__":
    main()
