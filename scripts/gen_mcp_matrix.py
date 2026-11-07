#!/usr/bin/env python3
"""Generate cmd/vyomi/mcp_matrix.json, the knowledge base `vyomi mcp` embeds.

Never hand-edit the JSON. It is derived from the code so it cannot drift:

  services/registry.json           WHICH services are released (status, version):
                                   the same registry release.yml publishes as
                                   services.json for vyomi.cloud
  providers/capabilities.py        per-service summaries (enrichment)
  core/pack_catalog.py             service packs: API actions + data plane (enrichment)
  providers/{aws,gcp,azure}.py     tool_response(): per-SDK / CLI endpoint config
  docker-compose.appliance.yml     host ports of the simulator + emulator containers
  .env.example                     documented VYOMI_* settings
  scripts/mcp_wiring.json          hand-curated client wiring (env vars, TLS, gotchas)
  VERSION                          appliance version stamped into the matrix

Import hygiene: providers/__init__.py pulls in FastAPI and core.app_context boots
the platform (and writes .cloudlearn_state.sqlite3). Both are stubbed so this
script is side-effect free and needs no third-party packages.

Usage:
  python3 scripts/gen_mcp_matrix.py           # write the matrix
  python3 scripts/gen_mcp_matrix.py --check   # exit 1 if the committed matrix is stale (CI)
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cmd" / "vyomi" / "mcp_matrix.json"
WIRING = ROOT / "scripts" / "mcp_wiring.json"
CLOUDS = ("aws", "gcp", "azure")

# tool_response() keys per provider module, normalised to the MCP's `lang` names.
TOOL_KEYS = {
    "aws": {"cli": "cli", "sdk/python": "python", "sdk/nodejs": "nodejs", "sdk/java": "java", "sdk/go": "go"},
    "gcp": {"gcloud": "cli", "sdk/python": "python", "sdk/nodejs": "nodejs", "sdk/java": "java", "sdk/go": "go"},
    "azure": {"cli": "cli", "sdk/python": "python", "sdk/nodejs": "nodejs", "sdk/java": "java", "sdk/go": "go"},
}


def _sandbox_imports() -> None:
    sys.path.insert(0, str(ROOT))
    providers = types.ModuleType("providers")
    providers.__path__ = [str(ROOT / "providers")]  # skip providers/__init__ (FastAPI)
    sys.modules["providers"] = providers
    import core  # noqa: F401  (plain package, no side effects)

    app_context = types.ModuleType("core.app_context")
    app_context.gcp_project_name = lambda project=None: project or "cloudlearn"
    sys.modules["core.app_context"] = app_context
    sys.modules["core"].app_context = app_context


def _pack_service_id(pack_id: str, cloud: str) -> str:
    parts = pack_id.split(".")
    if parts and parts[0] == "cloudlearn":
        parts = parts[1:]
    if parts and parts[0] == cloud:
        parts = parts[1:]
    if parts and parts[-1] == "basic":
        parts = parts[:-1]
    return ".".join(parts)


def _services(cloud: str, wiring: dict) -> list[dict]:
    """Released services from services/registry.json, enriched with capability
    summaries and pack actions. capabilities.py / pack ids that differ from the
    registry key are mapped through wiring["id_aliases"]."""
    from providers.capabilities import SERVICE_CAPABILITIES
    from core.pack_catalog import packs_for_provider

    aliases = wiring.get("id_aliases", {}).get(cloud, {})
    registry = json.loads((ROOT / "services" / "registry.json").read_text())["services"]
    out: dict[str, dict] = {}
    for svc in registry:
        if svc.get("cloud") != cloud or svc.get("status") != "released":
            continue  # pending-release services appear once the release bot flips them
        out[svc["key"]] = {
            "id": svc["key"],
            "name": svc.get("name", svc["key"]),
            "status": svc.get("status", "released"),
            "released_in": svc.get("released_in", ""),
        }
    unmatched = []
    for cap in SERVICE_CAPABILITIES.get(cloud, []):
        sid = aliases.get(cap["id"], cap["id"])
        if sid in out:
            out[sid]["summary"] = cap.get("summary", "")
        else:
            unmatched.append(f"capabilities:{cap['id']}")
    for pack in packs_for_provider(cloud):
        if pack.get("type") != "service":
            continue
        pid = _pack_service_id(pack.get("id", ""), cloud)
        sid = aliases.get(pid, pid)
        if sid not in out:
            unmatched.append(f"pack:{pack.get('id')}")
            continue
        api = pack.get("api") or {}
        out[sid]["pack_id"] = pack.get("id")
        if api.get("actions"):
            out[sid]["actions"] = list(api["actions"])
        if api.get("dataPlane"):
            out[sid]["data_plane"] = api["dataPlane"]
        if api.get("protocol"):
            out[sid]["protocol"] = api["protocol"]
    if unmatched:  # an engine that is not in the registry: surface it, don't invent a status
        print(f"note: {cloud}: not in services/registry.json, left out of the matrix: "
              + ", ".join(sorted(unmatched)), file=sys.stderr)
    return [out[k] for k in sorted(out)]


def _tools(cloud: str) -> dict:
    import importlib

    mod = importlib.import_module(f"providers.{cloud}")
    tools = {}
    for key, lang in TOOL_KEYS[cloud].items():
        try:
            resp = copy.deepcopy(mod.tool_response(key))
        except Exception as exc:  # a broken tool_response must fail the build loudly
            raise SystemExit(f"providers/{cloud}.py tool_response({key!r}) failed: {exc}")
        if not isinstance(resp, dict) or resp.get("error"):
            continue
        resp.pop("provider_surface", None)
        resp.pop("provider", None)
        tools[lang] = resp
    return tools


def _host_ports() -> dict:
    """service -> ["host:container", ...] from the appliance compose file (no PyYAML)."""
    text = (ROOT / "docker-compose.appliance.yml").read_text()
    ports: dict[str, list[str]] = {}
    in_services, current, in_ports = False, None, False
    for line in text.splitlines():
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services and re.match(r"^\S", line):
            break  # next top-level key (volumes:, networks:)
        if not in_services:
            continue
        m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if m:
            current, in_ports = m.group(1), False
            continue
        if re.match(r"^    ports:\s*$", line):
            in_ports = True
            continue
        if in_ports:
            pm = re.match(r"""^\s+-\s+["']?(\d+:\d+)["']?\s*$""", line)
            if pm:
                ports.setdefault(current, []).append(pm.group(1))
            elif re.match(r"^    \S", line):
                in_ports = False
    return dict(sorted(ports.items()))


def _settings() -> list[dict]:
    """VYOMI_* knobs documented in .env.example (commented-out ones included)."""
    out, doc = [], []
    for raw in (ROOT / ".env.example").read_text().splitlines():
        line = raw.strip()
        m = re.match(r"^#?\s*(VYOMI_[A-Z0-9_]+)=(.*)$", line)
        if m:
            out.append({"name": m.group(1), "default": m.group(2).strip(),
                        "doc": " ".join(doc).strip(), "commented_out": line.startswith("#")})
            continue
        if line.startswith("#") and not line.startswith("# ──") and not line.startswith("# ─"):
            doc.append(line.lstrip("# ").strip())
        else:
            doc = []
    return out


def build() -> dict:
    _sandbox_imports()
    from core.provider_registry import get_provider

    wiring = json.loads(WIRING.read_text())
    clouds = {}
    for cloud in CLOUDS:
        info = get_provider(cloud)
        clouds[cloud] = {
            "display_name": info.get("name", cloud),
            "native_services": info.get("native_services", []),
            "services": _services(cloud, wiring),
            "tools": _tools(cloud),
            "wiring": wiring["clouds"][cloud],
        }
    return {
        "schema": 1,
        "generated_by": "scripts/gen_mcp_matrix.py",
        "appliance_version": (ROOT / "VERSION").read_text().strip(),
        "defaults": {"sim_port": 9000, "tls_port": 9443, "host": "127.0.0.1", "azure_account": "devstoreaccount1"},
        "host_ports": _host_ports(),
        "settings": _settings(),
        "clouds": clouds,
        "scan": wiring["scan"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed matrix is stale")
    args = ap.parse_args()
    rendered = json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != rendered:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 scripts/gen_mcp_matrix.py", file=sys.stderr)
            return 1
        print("mcp matrix up to date")
        return 0
    OUT.write_text(rendered)
    m = json.loads(rendered)
    counts = ", ".join(f"{c}={len(m['clouds'][c]['services'])}" for c in CLOUDS)
    print(f"wrote {OUT.relative_to(ROOT)} (v{m['appliance_version']}; services {counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
