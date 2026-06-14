"""AWS rail extras — stub-driven CRUD for services without dedicated backends.

Extracted from server.py — contains the /api/aws/extras/* and
/api/aws/extras-config/* route handlers plus the helper functions
_aws_extras_state(), _aws_extras_seed_if_needed(), and _aws_extras_derive().
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from core import app_context as ctx

# Aliases
PLATFORM = ctx.PLATFORM
_now = ctx.now
_persist_state = ctx.persist_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aws_extras_state(stub_key: str) -> dict:
    """Per-space slot for a given <service>/<stub-key>. Always returns a dict
    with {items:{}, seeded:False} created lazily.

    IMPORTANT: `PLATFORM.get_active_space()` returns a deepcopy. Mutating that
    copy doesn't persist. Reach into the kernel's live state dict directly."""
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return {"items": {}, "seeded": False}   # no-op; won't persist
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    services = space.setdefault("service_states", {})
    extras = services.setdefault("aws_extras", {})
    slot = extras.setdefault(stub_key, {"items": {}, "seeded": False})
    if not isinstance(slot, dict):
        slot = {"items": {}, "seeded": False}
        extras[stub_key] = slot
    slot.setdefault("items", {})
    return slot


def _aws_extras_seed_if_needed(stub_key: str) -> None:
    from core.aws_rail_extras import EXTRAS
    schema = EXTRAS.get(stub_key)
    if not schema:
        return
    slot = _aws_extras_state(stub_key)
    if slot.get("seeded"):
        return
    for s in schema.get("seed") or []:
        # Use the schema-provided name field if any, else generate.
        name = s.get("name") or s.get("id") or s.get("snapshot_id") or s.get("volume_id") \
            or s.get("allocation_id") or s.get("key_pair_id") or s.get("request_id") \
            or s.get("interface_id") or s.get("event_id") or s.get("user") or s.get("dashboard")
        if not name:
            import secrets as _sec
            name = "item-" + _sec.token_hex(3)
        slot["items"][name] = dict(s)
    slot["seeded"] = True


def _aws_extras_derive(stub_key: str) -> list[dict]:
    """For 'derived_from' stubs, compute items on the fly from related state
    in the active space."""
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    space = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
    services = space.get("service_states", {}) if isinstance(space, dict) else {}
    if stub_key == "ec2/instance-types":
        try:
            from core import instance_catalog as cat
            out = []
            for name, meta in cat.AWS.items():
                ram_gb = (meta.get("ram_mb", 0) or 0) / 1024
                out.append({"name": name, "vcpu": meta.get("vcpu"),
                            "ram_gb": f"{ram_gb:.1f} GiB" if ram_gb < 10 else f"{int(ram_gb)} GiB",
                            "family": meta.get("family"),
                            "network": "Up to 5 Gbps" if "small" in name or "micro" in name else "Up to 25 Gbps"})
            return out
        except Exception:
            return []
    if stub_key == "ec2/ami-catalog":
        try:
            import server
            res = server.api_ec2_amis()
            amis = res.get("amis") if isinstance(res, dict) else res
            return list(amis or [])
        except Exception:
            return []
    if stub_key == "ec2/network-ifs":
        ec2_instances = services.get("ec2", {}).get("instances", {}) or {}
        out = []
        for iid, inst in ec2_instances.items():
            if not isinstance(inst, dict):
                continue
            out.append({
                "interface_id": f"eni-{iid[-8:]}",
                "description": f"Primary ENI for {iid}",
                "instance_id": iid,
                "private_ip": inst.get("private_ip", "10.0.0.x"),
                "public_ip": inst.get("public_ip", "\u2014"),
                "subnet_id": inst.get("subnet_id", "subnet-default"),
                "status": "in-use" if inst.get("state") == "running" else "available",
            })
        return out
    if stub_key == "iam/dashboard":
        iam = services.get("iam", {}) or {}
        return [
            {"metric": "Users",          "value": str(len(iam.get("users") or {})),    "recommendation": "Rotate access keys every 90 days"},
            {"metric": "Groups",         "value": str(len(iam.get("groups") or {})),    "recommendation": "Use groups to assign permissions, not direct user policies"},
            {"metric": "Roles",          "value": str(len(iam.get("roles") or {})),     "recommendation": "Prefer roles over long-lived access keys"},
            {"metric": "Customer policies","value": str(len(iam.get("policies") or {})),"recommendation": "Use AWS managed policies where possible"},
            {"metric": "MFA users",      "value": "0", "recommendation": "Require MFA for all users"},
        ]
    if stub_key == "rds/dashboard":
        rds = services.get("rds", {}) or {}
        dbs = rds.get("db_instances") or rds.get("databases") or {}
        return [
            {"metric": "DB instances",   "value": str(len(dbs))},
            {"metric": "Total storage",  "value": f"{sum((d.get('allocated_storage') or 20) for d in dbs.values() if isinstance(d,dict))} GiB"},
            {"metric": "Snapshots",      "value": "\u2014"},
            {"metric": "Events (24h)",   "value": "\u2014"},
        ]
    if stub_key == "dynamodb/dashboard":
        dyn = services.get("dynamodb", {}) or {}
        tables = dyn.get("tables") or {}
        return [
            {"metric": "Total tables",   "value": str(len(tables))},
            {"metric": "Item count",     "value": str(sum(int(t.get("item_count", 0) or 0) for t in tables.values() if isinstance(t, dict)))},
            {"metric": "Provisioned RCU","value": "\u2014"},
            {"metric": "Provisioned WCU","value": "\u2014"},
        ]
    if stub_key == "lambda/dashboard":
        lam = services.get("lambda", {}) or {}
        fns = lam.get("functions") or {}
        return [
            {"metric": "Functions",       "value": str(len(fns))},
            {"metric": "Layers",          "value": "0"},
            {"metric": "Invocations 24h", "value": str(sum(len((f.get("invocations") or [])) for f in fns.values() if isinstance(f, dict)))},
            {"metric": "Errors 24h",      "value": "0"},
        ]
    if stub_key == "vpc/dashboard":
        vpc = services.get("vpc", {}) or {}
        return [
            {"metric": "VPCs",             "value": str(len(vpc.get("vpcs") or {}))},
            {"metric": "Subnets",          "value": str(len(vpc.get("subnets") or {}))},
            {"metric": "Security groups",  "value": str(len(vpc.get("security_groups") or {}))},
            {"metric": "Route tables",     "value": str(len(vpc.get("route_tables") or {}))},
            {"metric": "Internet gateways","value": str(len(vpc.get("internet_gateways") or {}))},
        ]
    if stub_key == "sqs/dlqs":
        sqs = services.get("sqs", {}) or {}
        out = []
        queues = sqs.get("queues") or {}
        for qname, q in queues.items():
            if not isinstance(q, dict):
                continue
            sources = [n for n, other in queues.items()
                       if isinstance(other, dict)
                       and (other.get("dlq_arn") or "").endswith("/"+qname)]
            if sources:
                out.append({
                    "name": qname, "arn": q.get("arn", f"arn:aws:sqs:us-east-1:123456789012:{qname}"),
                    "source_queues": ", ".join(sources), "approximate_messages": str(q.get("message_count") or 0),
                })
        return out
    return []


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Mount all /api/aws/extras/* and /api/aws/extras-config/* routes."""

    @app.get("/api/aws/extras/{stub_path:path}", include_in_schema=False)
    def api_aws_extras_get(stub_path: str):
        from core.aws_rail_extras import EXTRAS
        schema = EXTRAS.get(stub_path)
        # If stub_path doesn't match a known stub, try peeling off a trailing
        # /{name} segment — the catalog's resource_path is `.../<stub>/{name}`
        # and a console GET to that URL should return the single item.
        if not schema and "/" in stub_path:
            parent, _, name = stub_path.rpartition("/")
            schema_parent = EXTRAS.get(parent)
            if schema_parent and not schema_parent.get("derived_from") and schema_parent.get("category") != "config":
                _aws_extras_seed_if_needed(parent)
                slot = _aws_extras_state(parent)
                item = slot["items"].get(name)
                if item is not None:
                    return item
                raise HTTPException(status_code=404, detail=f"Not found: {parent}/{name}")
        if not schema:
            raise HTTPException(status_code=404, detail=f"Unknown stub: {stub_path}")
        if schema.get("derived_from"):
            return {"items": _aws_extras_derive(stub_path), "derived": True,
                    "schema": {"category": schema.get("category"), "columns": schema.get("columns")}}
        _aws_extras_seed_if_needed(stub_path)
        slot = _aws_extras_state(stub_path)
        return {"items": list(slot["items"].values()), "derived": False,
                "schema": {"category": schema.get("category"), "columns": schema.get("columns")}}

    @app.post("/api/aws/extras/{stub_path:path}", include_in_schema=False)
    def api_aws_extras_create(stub_path: str, payload: dict[str, Any] | None = None):
        from core.aws_rail_extras import EXTRAS
        import secrets as _sec
        schema = EXTRAS.get(stub_path)
        if not schema:
            raise HTTPException(status_code=404, detail=f"Unknown stub: {stub_path}")
        if schema.get("derived_from"):
            raise HTTPException(status_code=400, detail="Derived collection \u2014 create via the source service.")
        if schema.get("category") == "config":
            raise HTTPException(status_code=400, detail="Use PUT to update config.")
        payload = dict(payload or {})
        name = payload.get("name") or payload.get("id")
        if not name:
            prefix = stub_path.split("/")[-1].split("-")[0][:3]
            name = f"{prefix}-{_sec.token_hex(4)}"
        payload["name"] = name
        payload.setdefault("created", _now())
        for col_path, _ in (schema.get("columns") or []):
            if "." not in col_path and col_path not in payload:
                payload[col_path] = payload.get(col_path, "\u2014")
        slot = _aws_extras_state(stub_path)
        slot["items"][name] = payload
        slot["seeded"] = True
        _persist_state()
        return payload

    @app.delete("/api/aws/extras/{stub_path:path}", include_in_schema=False)
    def api_aws_extras_delete_one(stub_path: str):
        """Delete by name. URL pattern is /api/aws/extras/<svc>/<stub>/<name>."""
        from core.aws_rail_extras import EXTRAS
        parts = stub_path.rsplit("/", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Expected /api/aws/extras/<service>/<stub>/<name>")
        key, name = parts
        schema = EXTRAS.get(key)
        if not schema:
            raise HTTPException(status_code=404, detail=f"Unknown stub: {key}")
        if schema.get("derived_from"):
            raise HTTPException(status_code=400, detail="Derived collection \u2014 delete via the source service.")
        slot = _aws_extras_state(key)
        slot["items"].pop(name, None)
        _persist_state()
        return {"deleted": True, "name": name}

    @app.get("/api/aws/extras-config/{stub_path:path}", include_in_schema=False)
    def api_aws_extras_config_get(stub_path: str):
        """Config-category stubs are a single editable record."""
        from core.aws_rail_extras import EXTRAS
        schema = EXTRAS.get(stub_path)
        if not schema or schema.get("category") != "config":
            raise HTTPException(status_code=404, detail=f"Not a config stub: {stub_path}")
        slot = _aws_extras_state(stub_path)
        if not slot.get("seeded"):
            slot["items"] = dict(schema.get("defaults") or {})
            slot["seeded"] = True
        return {"values": slot["items"], "schema": {"fields": schema.get("fields"), "defaults": schema.get("defaults")}}

    @app.put("/api/aws/extras-config/{stub_path:path}", include_in_schema=False)
    def api_aws_extras_config_put(stub_path: str, payload: dict[str, Any] | None = None):
        from core.aws_rail_extras import EXTRAS
        schema = EXTRAS.get(stub_path)
        if not schema or schema.get("category") != "config":
            raise HTTPException(status_code=404, detail=f"Not a config stub: {stub_path}")
        slot = _aws_extras_state(stub_path)
        slot["items"] = dict(payload or {})
        slot["seeded"] = True
        _persist_state()
        return {"values": slot["items"]}
