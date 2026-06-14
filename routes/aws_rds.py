"""AWS RDS database CRUD, snapshots, parameter groups, subnet groups, Docker/LXD runtime.

Extracted from server.py — contains both the REST API route handlers and
the underlying helper / business-logic functions.
"""
from __future__ import annotations

import copy
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from core import app_context as ctx
from core.models import (
    RDSDatabaseRequest,
    RDSModifyRequest,
    RDSParameterGroupRequest,
    RDSRestoreSnapshotRequest,
    RDSSnapshotRequest,
    RDSSubnetGroupRequest,
)

# ---------------------------------------------------------------------------
# Lazy back-reference to server.py
# ---------------------------------------------------------------------------


def _srv():
    import server as _s
    return _s


# ---------------------------------------------------------------------------
# State access
# ---------------------------------------------------------------------------

rds_state = ctx.rds_state
vpc_state = ctx.vpc_state

# ---------------------------------------------------------------------------
# Helper proxies — delegate to server.py
# ---------------------------------------------------------------------------


def _rds_find_db_instance(db_id: str):
    return _srv()._rds_find_db_instance(db_id)


def _rds_db_view(db: dict) -> dict:
    return _srv()._rds_db_view(db)


def _rds_list_databases_view() -> dict:
    return _srv()._rds_list_databases_view()


def _rds_prepare_db_instance(payload, source_snapshot=None) -> dict:
    return _srv()._rds_prepare_db_instance(payload, source_snapshot)


def _rds_update_db_instance(db: dict, payload) -> dict:
    return _srv()._rds_update_db_instance(db, payload)


def _rds_delete_db_instance(db_id: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = ""):
    return _srv()._rds_delete_db_instance(db_id, skip_final_snapshot, final_snapshot_identifier)


def _rds_create_snapshot_from_db(db: dict, snapshot_id: str, tags=None) -> dict:
    return _srv()._rds_create_snapshot_from_db(db, snapshot_id, tags)


def _rds_restore_snapshot(snapshot: dict, payload) -> dict:
    return _srv()._rds_restore_snapshot(snapshot, payload)


def _rds_find_db_snapshot(snapshot_id: str):
    return _srv()._rds_find_db_snapshot(snapshot_id)


def _rds_db_snapshot_view(snapshot: dict) -> dict:
    return _srv()._rds_db_snapshot_view(snapshot)


def _rds_find_db_subnet_group(name: str):
    return _srv()._rds_find_db_subnet_group(name)


def _rds_find_db_parameter_group(name: str):
    return _srv()._rds_find_db_parameter_group(name)


def _rds_make_db_subnet_group(name, description, vpc_id, subnet_ids, tags=None) -> dict:
    return _srv()._rds_make_db_subnet_group(name, description, vpc_id, subnet_ids, tags)


def _rds_make_db_parameter_group(name, family, description, tags=None) -> dict:
    return _srv()._rds_make_db_parameter_group(name, family, description, tags)


def _rds_resource_tags(resource: dict) -> list[dict[str, str]]:
    return _srv()._rds_resource_tags(resource)


def _rds_set_tags(resource: dict, tags):
    return _srv()._rds_set_tags(resource, tags)


def _rds_runtime_start(db: dict) -> dict:
    return _srv()._rds_runtime_start(db)


def _rds_runtime_stop(db: dict) -> dict:
    return _srv()._rds_runtime_stop(db)


def _rds_runtime_reboot(db: dict) -> dict:
    return _srv()._rds_runtime_reboot(db)


# ---------------------------------------------------------------------------
# Query-protocol handler (XML)
# ---------------------------------------------------------------------------

async def api_rds_query(request: Request):
    return await _srv().api_rds_query(request)


# ---------------------------------------------------------------------------
# Console REST API route handlers
# ---------------------------------------------------------------------------

def api_rds_list_databases():
    return _rds_list_databases_view()


def api_rds_create_database(req: RDSDatabaseRequest):
    ctx.enforce_quantity_cap("database")
    ctx.enforce_size_cap("database", "aws", req.db_instance_class)
    db = _rds_prepare_db_instance(req)
    bundle = _srv()._cloudsim_runtime_bundle("rds")
    db["runtime_bundle_id"] = bundle.get("id", "")
    db["runtime_bundle_name"] = bundle.get("name", "")
    db["runtime_bundle_kind"] = bundle.get("kind", "")
    ctx.record_usage("rds.create_db_instance", {"db_instance_identifier": db.get("db_instance_identifier", "")})
    return _rds_db_view(db)


def api_rds_get_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    return _rds_db_view(db)


def api_rds_start_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    # Idempotent: return current view if already available rather than 409.
    # Mirrors the console-button UX (no-op when already on) and lets harness
    # tests run lifecycle in any order without sequencing pre-conditions.
    if db.get("db_instance_status") == "available":
        return _rds_db_view(db)
    _rds_runtime_start(db)
    ctx.record_usage("rds.start_db_instance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_stop_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    _rds_runtime_stop(db)
    ctx.record_usage("rds.stop_db_instance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_reboot_database(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    _rds_runtime_reboot(db)
    ctx.record_usage("rds.reboot_db_instance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_modify_database(db_instance_identifier: str, req: RDSModifyRequest):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    _rds_update_db_instance(db, req)
    ctx.record_usage("rds.modify_db_instance", {"db_instance_identifier": db_instance_identifier})
    return _rds_db_view(db)


def api_rds_delete_database(db_instance_identifier: str, skip_final_snapshot: bool = True, final_snapshot_identifier: str = ""):
    _rds_delete_db_instance(db_instance_identifier, skip_final_snapshot, final_snapshot_identifier)
    ctx.record_usage("rds.delete_db_instance", {"db_instance_identifier": db_instance_identifier})
    return {"deleted": True, "db_instance_identifier": db_instance_identifier}


def api_rds_list_subnet_groups():
    groups = list(rds_state["db_subnet_groups"].values())
    return {"db_subnet_groups": groups, "count": len(groups)}


def api_rds_create_subnet_group(req: RDSSubnetGroupRequest):
    name = (req.db_subnet_group_name or "").strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: db_subnet_group_name")
    if name in rds_state["db_subnet_groups"]:
        raise HTTPException(409, detail="DBSubnetGroupAlreadyExists")
    vpc_id = req.vpc_id or ""
    if not vpc_id:
        vpcs = list(vpc_state.get("vpcs", {}).keys())
        if vpcs:
            vpc_id = vpcs[0]
    subnet_ids = req.subnet_ids or []
    if not subnet_ids and vpc_id:
        subnet_ids = [s["subnet_id"] for s in vpc_state.get("subnets", {}).values() if s.get("vpc_id") == vpc_id][:2]
    group = _rds_make_db_subnet_group(name, req.description or "", vpc_id, subnet_ids, req.tags)
    ctx.record_usage("rds.create_db_subnet_group", {"db_subnet_group_name": name})
    return group


def api_rds_delete_subnet_group(db_subnet_group_name: str):
    name = (db_subnet_group_name or "").strip().lower()
    for db in rds_state["db_instances"].values():
        if db.get("db_subnet_group_name") == name:
            raise HTTPException(400, detail="InvalidDBSubnetGroupState: Subnet group is in use by one or more DB instances.")
    group = _rds_find_db_subnet_group(name)
    if not group:
        raise HTTPException(404, detail="DBSubnetGroupNotFound")
    del rds_state["db_subnet_groups"][name]
    ctx.record_usage("rds.delete_db_subnet_group", {"db_subnet_group_name": name})
    return {"deleted": True, "db_subnet_group_name": name}


def api_rds_list_parameter_groups():
    groups = list(rds_state["db_parameter_groups"].values())
    return {"db_parameter_groups": groups, "count": len(groups)}


def api_rds_create_parameter_group(req: RDSParameterGroupRequest):
    name = (req.db_parameter_group_name or "").strip().lower()
    if not name:
        raise HTTPException(400, detail="MissingParameter: db_parameter_group_name")
    if name in rds_state["db_parameter_groups"]:
        raise HTTPException(409, detail="DBParameterGroupAlreadyExists")
    group = _rds_make_db_parameter_group(name, req.db_parameter_group_family or "mysql8.0", req.description or "", req.tags)
    ctx.record_usage("rds.create_db_parameter_group", {"db_parameter_group_name": name})
    return group


def api_rds_delete_parameter_group(db_parameter_group_name: str):
    name = (db_parameter_group_name or "").strip().lower()
    for db in rds_state["db_instances"].values():
        if db.get("db_parameter_group_name") == name:
            raise HTTPException(400, detail="InvalidDBParameterGroupState: Parameter group is in use.")
    group = _rds_find_db_parameter_group(name)
    if not group:
        raise HTTPException(404, detail="DBParameterGroupNotFound")
    del rds_state["db_parameter_groups"][name]
    ctx.record_usage("rds.delete_db_parameter_group", {"db_parameter_group_name": name})
    return {"deleted": True, "db_parameter_group_name": name}


def api_rds_list_snapshots():
    snapshots = [_rds_db_snapshot_view(s) for s in rds_state["db_snapshots"].values()]
    return {"db_snapshots": snapshots, "count": len(snapshots)}


def api_rds_create_snapshot(db_instance_identifier: str, req: RDSSnapshotRequest):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    snapshot = _rds_create_snapshot_from_db(db, req.db_snapshot_identifier, req.tags)
    ctx.record_usage("rds.create_snapshot", {"db_instance_identifier": db_instance_identifier, "db_snapshot_identifier": req.db_snapshot_identifier})
    return _rds_db_snapshot_view(snapshot)


def api_rds_restore_snapshot(db_snapshot_identifier: str, req: RDSRestoreSnapshotRequest):
    snapshot = _rds_find_db_snapshot(db_snapshot_identifier)
    if not snapshot:
        raise HTTPException(404, detail="DBSnapshotNotFound")
    db = _rds_restore_snapshot(snapshot, req)
    ctx.record_usage("rds.restore_snapshot", {"db_snapshot_identifier": db_snapshot_identifier, "db_instance_identifier": db.get("db_instance_identifier", "")})
    return _rds_db_view(db)


def api_rds_add_tags(db_instance_identifier: str, payload: dict[str, Any]):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    tags = payload.get("tags") or payload.get("Tags") or []
    if isinstance(tags, dict):
        tags = [{"Key": str(k), "Value": str(v)} for k, v in tags.items()]
    _rds_set_tags(db, tags)
    ctx.record_usage("rds.add_tags", {"db_instance_identifier": db_instance_identifier})
    return {"tagged": True, "db_instance_identifier": db_instance_identifier, "tags": _rds_resource_tags(db)}


def api_rds_list_tags(db_instance_identifier: str):
    db = _rds_find_db_instance(db_instance_identifier)
    if not db:
        raise HTTPException(404, detail="DBInstanceNotFound")
    return {"db_instance_identifier": db_instance_identifier, "tags": _rds_resource_tags(db)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Register RDS routes on the FastAPI app.

    NOTE: RDS routes are currently registered via providers/aws_routes.py
    using the dynamic _proxy/_add_route mechanism.  This register() function
    is provided for future use when the migration is complete.
    """
    pass  # Routes registered via providers/aws_routes.py spec table
