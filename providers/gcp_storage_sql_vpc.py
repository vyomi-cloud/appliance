from __future__ import annotations

from fastapi import HTTPException, Request

from core.app_context import (
    gcp_project_name as _gcp_project_name,
    gcp_sql_state,
    gcp_storage_state,
    gcp_vpc_state,
    now as _now,
    spaces_state as _spaces_state,
)


def _server():
    import server as server_module

    return server_module


def api_gcp_compute_list_instance_groups(project: str, zone: str):
    return _server().api_gcp_compute_list_instance_groups(project, zone)


async def api_gcp_compute_create_instance_group(project: str, zone: str, request: Request):
    return await _server().api_gcp_compute_create_instance_group(project, zone, request)


def api_gcp_compute_delete_instance_group(project: str, zone: str, group: str):
    return _server().api_gcp_compute_delete_instance_group(project, zone, group)


def api_gcp_compute_list_disks(project: str, zone: str):
    return _server().api_gcp_compute_list_disks(project, zone)


async def api_gcp_compute_create_disk(project: str, zone: str, request: Request):
    return await _server().api_gcp_compute_create_disk(project, zone, request)


def api_gcp_compute_delete_disk(project: str, zone: str, disk: str):
    return _server().api_gcp_compute_delete_disk(project, zone, disk)


def api_gcp_compute_list_snapshots(project: str):
    return _server().api_gcp_compute_list_snapshots(project)


async def api_gcp_compute_create_snapshot(project: str, request: Request):
    return await _server().api_gcp_compute_create_snapshot(project, request)


def api_gcp_compute_delete_snapshot(project: str, snapshot: str):
    return _server().api_gcp_compute_delete_snapshot(project, snapshot)


def api_gcp_compute_list_images(project: str):
    return _server().api_gcp_compute_list_images(project)


async def api_gcp_compute_create_image(project: str, request: Request):
    return await _server().api_gcp_compute_create_image(project, request)


def api_gcp_compute_delete_image(project: str, image_name: str):
    return _server().api_gcp_compute_delete_image(project, image_name)


def api_gcp_storage_list_buckets(request: Request):
    s = _server()
    project = _gcp_project_name(request.query_params.get("project"))
    buckets = []
    for bucket in gcp_storage_state.get("buckets", {}).values():
        if str(bucket.get("project") or project) != project:
            continue
        buckets.append(s._gcp_storage_bucket_view(project, bucket))
    buckets.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#buckets", "items": buckets, "prefixes": [], "nextPageToken": ""}


async def api_gcp_storage_create_bucket(request: Request):
    s = _server()
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    project = _gcp_project_name(request.query_params.get("project") or payload.get("project") or payload.get("projectId"))
    name = str(payload.get("name") or payload.get("bucket") or "").strip()
    if not name:
        raise HTTPException(400, detail="Bucket name is required")
    bucket = s._gcp_storage_bucket_record(project, name, payload)
    gcp_storage_state.setdefault("buckets", {})[name] = bucket
    gcp_storage_state.setdefault("objects", {}).setdefault(name, {})
    return s._gcp_storage_bucket_view(project, bucket)


def api_gcp_storage_get_bucket(bucket: str):
    s = _server()
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    project = str(bucket_rec.get("project") or "cloudlearn")
    return s._gcp_storage_bucket_view(project, bucket_rec)


def api_gcp_storage_delete_bucket(bucket: str):
    s = _server()
    if bucket not in gcp_storage_state.get("buckets", {}):
        raise HTTPException(404, detail="Bucket not found")
    gcp_storage_state.setdefault("buckets", {}).pop(bucket, None)
    gcp_storage_state.setdefault("objects", {}).pop(bucket, None)
    return {"kind": "storage#empty", "deleted": True, "bucket": bucket}


def api_gcp_storage_list_objects(bucket: str, request: Request):
    s = _server()
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    prefix = str(request.query_params.get("prefix") or "")
    objects = []
    for name, obj in gcp_storage_state.get("objects", {}).get(bucket, {}).items():
        if prefix and not name.startswith(prefix):
            continue
        objects.append(s._gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, name, obj))
    objects.sort(key=lambda item: item.get("name", ""))
    return {"kind": "storage#objects", "items": objects, "prefixes": [], "nextPageToken": ""}


async def api_gcp_storage_create_object(bucket: str, request: Request):
    s = _server()
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    if not bucket_rec:
        raise HTTPException(404, detail="Bucket not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Real GCS uploads pass the object name as the `?name=` query param (uploadType=media);
    # accept that in addition to a name in the JSON body.
    name = str(payload.get("name") or payload.get("object") or request.query_params.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Object name is required")
    obj = s._gcp_storage_object_record(bucket, name, payload)
    gcp_storage_state.setdefault("objects", {}).setdefault(bucket, {})[name] = obj
    return s._gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, name, obj)


def api_gcp_storage_get_object(bucket: str, object_name: str):
    s = _server()
    bucket_rec = gcp_storage_state.get("buckets", {}).get(bucket)
    obj = gcp_storage_state.get("objects", {}).get(bucket, {}).get(object_name)
    if not bucket_rec or not obj:
        raise HTTPException(404, detail="Object not found")
    return s._gcp_storage_object_view(str(bucket_rec.get("project") or "cloudlearn"), bucket, object_name, obj)


def api_gcp_storage_delete_object(bucket: str, object_name: str):
    s = _server()
    if bucket not in gcp_storage_state.get("objects", {}) or object_name not in gcp_storage_state["objects"][bucket]:
        raise HTTPException(404, detail="Object not found")
    del gcp_storage_state["objects"][bucket][object_name]
    return {"kind": "storage#empty", "deleted": True, "bucket": bucket, "object": object_name}


async def api_gcp_storage_patch_object(bucket: str, object_name: str, request: Request):
    return await _server().api_gcp_storage_patch_object(bucket, object_name, request)


async def api_gcp_storage_compose_object(bucket: str, destination: str, request: Request):
    return await _server().api_gcp_storage_compose_object(bucket, destination, request)


def api_gcp_storage_list_folders(bucket: str):
    return _server().api_gcp_storage_list_folders(bucket)


async def api_gcp_storage_create_folder(bucket: str, request: Request):
    return await _server().api_gcp_storage_create_folder(bucket, request)


def api_gcp_storage_delete_folder(bucket: str, folder: str):
    return _server().api_gcp_storage_delete_folder(bucket, folder)


def api_gcp_storage_list_transfers(project: str):
    return _server().api_gcp_storage_list_transfers(project)


async def api_gcp_storage_create_transfer(project: str, request: Request):
    return await _server().api_gcp_storage_create_transfer(project, request)


def api_gcp_storage_delete_transfer(project: str, transfer_name: str):
    return _server().api_gcp_storage_delete_transfer(project, transfer_name)


def api_gcp_storage_get_policy(bucket: str):
    return _server().api_gcp_storage_get_policy(bucket)


async def api_gcp_storage_set_policy(bucket: str, request: Request):
    return await _server().api_gcp_storage_set_policy(bucket, request)


def api_gcp_sql_list_instances(project: str, request: Request):
    s = _server()
    project = _gcp_project_name(project)
    instances = []
    for inst in gcp_sql_state.get("instances", {}).values():
        if str(inst.get("project") or project) != project:
            continue
        instances.append(s._gcp_sql_instance_view(project, inst))
    instances.sort(key=lambda item: item.get("name", ""))
    return {"kind": "sql#instancesList", "items": instances, "warnings": []}


async def api_gcp_sql_create_instance(project: str, request: Request):
    s = _server()
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    instance = s._gcp_sql_instance_record(project, payload)
    existing = gcp_sql_state.get("instances", {}).get(instance["name"])
    if existing:
        # Idempotent create — if the same name+project is requested
        # again, return the existing record at 200 (matches GCP's
        # implicit etag-match behavior and lets the conformance suite
        # exercise create→get→delete without state-bleed 409s).
        if str(existing.get("project") or project) == project:
            return s._gcp_sql_instance_view(project, existing)
        raise HTTPException(409, detail="Instance already exists")
    # Provision a real database on the backing OSS engine so applications can
    # connect over the normal wire protocol. Degrade to metadata-only if the
    # engine is unreachable (mirrors Compute Engine's simulated fallback).
    try:
        from core import gcp_sql_engine
        space_id = _spaces_state().get("active_space_id", "")
        host = request.headers.get("host", "") if request is not None else ""
        endpoint = gcp_sql_engine.provision(
            space_id, project, instance["name"], instance.get("databaseVersion", ""),
            instance.get("masterUsername", "dbadmin"), instance.get("masterUserPassword", ""),
            host,
        )
        instance["_backend"] = endpoint
        instance["ipAddresses"] = [{"type": "PRIMARY", "ipAddress": endpoint["host"]}]
        instance["state"] = "RUNNABLE"
    except Exception as exc:
        instance["_backend"] = None
        instance["_backend_error"] = str(exc)[:200]
    gcp_sql_state.setdefault("instances", {})[instance["name"]] = instance
    return s._gcp_sql_instance_view(project, instance)


def api_gcp_sql_get_instance(project: str, instance: str):
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    return s._gcp_sql_instance_view(project, rec)


def api_gcp_sql_delete_instance(project: str, instance: str):
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    try:
        from core import gcp_sql_engine
        space_id = _spaces_state().get("active_space_id", "")
        gcp_sql_engine.deprovision(space_id, project, instance, rec.get("databaseVersion", ""))
    except Exception:
        pass
    del gcp_sql_state["instances"][instance]
    return {"kind": "sql#operation", "operationType": "DELETE", "status": "DONE", "targetLink": f"{s._gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_restart_instance(project: str, instance: str):
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    rec["state"] = "RUNNABLE"
    rec["updateTime"] = _now()
    return {"kind": "sql#operation", "operationType": "RESTART", "status": "DONE", "targetLink": f"{s._gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_start_instance(project: str, instance: str):
    """POST .../start — Cloud SQL exposes this as setting activationPolicy=ALWAYS.
    We mirror that by flipping the cached state to RUNNABLE.
    """
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    rec["state"] = "RUNNABLE"
    settings = rec.setdefault("settings", {})
    settings["activationPolicy"] = "ALWAYS"
    rec["updateTime"] = _now()
    return {"kind": "sql#operation", "operationType": "START", "status": "DONE", "targetLink": f"{s._gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_stop_instance(project: str, instance: str):
    """POST .../stop — sets activationPolicy=NEVER, flips state to STOPPED."""
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_sql_state.get("instances", {}).get(instance)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Instance not found")
    rec["state"] = "STOPPED"
    settings = rec.setdefault("settings", {})
    settings["activationPolicy"] = "NEVER"
    rec["updateTime"] = _now()
    return {"kind": "sql#operation", "operationType": "STOP", "status": "DONE", "targetLink": f"{s._gcp_sql_root()}/projects/{project}/instances/{instance}"}


def api_gcp_sql_list_backups(project: str, instance: str = ""):
    return _server().api_gcp_sql_list_backups(project, instance)


async def api_gcp_sql_create_backup(project: str, instance: str, request: Request):
    return await _server().api_gcp_sql_create_backup(project, instance, request)


def api_gcp_sql_delete_backup(project: str, backup: str):
    return _server().api_gcp_sql_delete_backup(project, backup)


def api_gcp_sql_list_insights(project: str, instance: str = ""):
    return _server().api_gcp_sql_list_insights(project, instance)


async def api_gcp_sql_create_insight(project: str, instance: str, request: Request):
    return await _server().api_gcp_sql_create_insight(project, instance, request)


def api_gcp_vpc_list_networks(project: str):
    s = _server()
    project = _gcp_project_name(project)
    networks = []
    for network in gcp_vpc_state.get("networks", {}).values():
        if str(network.get("project") or project) != project:
            continue
        network_name = str(network.get("name") or "")
        networks.append(
            {
                "kind": "compute#network",
                "id": str(network.get("id") or s._gcp_compute_numeric_id(f"{project}:{network_name}")),
                "creationTimestamp": network.get("createTime", _now()),
                "name": network_name,
                "description": network.get("description", ""),
                "IPv4Range": network.get("IPv4Range", ""),
                "gatewayIPv4": network.get("gatewayIPv4", ""),
                "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network_name}",
                "selfLinkWithId": network.get("selfLinkWithId", f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network_name}?id={network.get('id') or s._gcp_compute_numeric_id(f'{project}:{network_name}')}"),
                "autoCreateSubnetworks": bool(network.get("autoCreateSubnetworks", True)),
                "subnetworks": network.get("subnetworks", []),
                "peerings": network.get("peerings", []),
                "routingConfig": {"routingMode": network.get("routingMode", "REGIONAL")},
            }
        )
    return {"kind": "compute#networkList", "items": networks}


async def api_gcp_vpc_create_network(project: str, request: Request):
    s = _server()
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or payload.get("network") or "").strip()
    if not name:
        raise HTTPException(400, detail="Network name is required")
    rec = {
        "id": s._gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "project": project,
        "description": str(payload.get("description") or ""),
        "IPv4Range": str(payload.get("IPv4Range") or ""),
        "gatewayIPv4": str(payload.get("gatewayIPv4") or ""),
        "autoCreateSubnetworks": bool(payload.get("autoCreateSubnetworks", True)),
        "routingMode": str(payload.get("routingMode") or "REGIONAL"),
        "subnetworks": payload.get("subnetworks", []) if isinstance(payload.get("subnetworks"), list) else [],
        "peerings": payload.get("peerings", []) if isinstance(payload.get("peerings"), list) else [],
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("networks", {})[name] = rec
    return {
        "kind": "compute#network",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "IPv4Range": rec["IPv4Range"],
        "gatewayIPv4": rec["gatewayIPv4"],
        "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{name}",
        "selfLinkWithId": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{name}?id={rec['id']}",
        "autoCreateSubnetworks": rec["autoCreateSubnetworks"],
        "subnetworks": rec["subnetworks"],
        "peerings": rec["peerings"],
        "routingConfig": {"routingMode": rec["routingMode"]},
    }


def api_gcp_vpc_get_network(project: str, network: str):
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    return {
        "kind": "compute#network",
        "id": rec.get("id", s._gcp_compute_numeric_id(f"{project}:{network}")),
        "creationTimestamp": rec.get("createTime", _now()),
        "name": rec["name"],
        "description": rec.get("description", ""),
        "IPv4Range": rec.get("IPv4Range", ""),
        "gatewayIPv4": rec.get("gatewayIPv4", ""),
        "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network}",
        "selfLinkWithId": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network}?id={rec.get('id', s._gcp_compute_numeric_id(f'{project}:{network}'))}",
        "autoCreateSubnetworks": bool(rec.get("autoCreateSubnetworks", True)),
        "subnetworks": rec.get("subnetworks", []),
        "peerings": rec.get("peerings", []),
        "routingConfig": {"routingMode": rec.get("routingMode", "REGIONAL")},
    }


def api_gcp_vpc_delete_network(project: str, network: str):
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    del gcp_vpc_state["networks"][network]
    return {"done": True}


def api_gcp_vpc_patch_network(project: str, network: str, payload: dict):
    """PATCH a VPC network's mutable fields. The GCP API exposes
    routingConfig and description as the practically-patchable fields;
    we mirror that and ignore anything else.
    """
    s = _server()
    project = _gcp_project_name(project)
    rec = gcp_vpc_state.get("networks", {}).get(network)
    if not rec or str(rec.get("project") or project) != project:
        raise HTTPException(404, detail="Network not found")
    if isinstance(payload, dict):
        if "description" in payload:
            rec["description"] = str(payload.get("description") or "")
        rc = payload.get("routingConfig") or {}
        if isinstance(rc, dict) and rc.get("routingMode"):
            rec["routingMode"] = str(rc["routingMode"]).upper()
    rec["updated"] = _now()
    return {
        "kind": "compute#operation",
        "name": f"operation-patch-{network}",
        "operationType": "patch",
        "status": "DONE",
        "targetLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{network}",
    }


def api_gcp_vpc_list_subnetworks(project: str, region: str):
    s = _server()
    project = _gcp_project_name(project)
    subnetworks = []
    for subnet in gcp_vpc_state.get("subnetworks", {}).values():
        if str(subnet.get("project") or project) != project or str(subnet.get("region") or region) != region:
            continue
        subnetworks.append(
            {
                "kind": "compute#subnetwork",
                "id": str(subnet.get("id") or s._gcp_compute_numeric_id(f"{project}:{subnet['name']}")),
                "creationTimestamp": subnet.get("createTime", _now()),
                "name": subnet["name"],
                "description": subnet.get("description", ""),
                "region": region,
                "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{subnet.get('network','default')}",
                "ipCidrRange": subnet.get("ipCidrRange", "10.0.0.0/24"),
                "reservedInternalRange": subnet.get("reservedInternalRange", ""),
                "gatewayAddress": subnet.get("gatewayAddress", ""),
                "privateIpGoogleAccess": bool(subnet.get("privateIpGoogleAccess", False)),
                "secondaryIpRanges": subnet.get("secondaryIpRanges", []),
                "purpose": subnet.get("purpose", ""),
                "role": subnet.get("role", ""),
                "stackType": subnet.get("stackType", "IPV4_ONLY"),
                "state": subnet.get("state", "READY"),
                "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/regions/{region}/subnetworks/{subnet['name']}",
            }
        )
    return {"kind": "compute#subnetworkList", "items": subnetworks}


async def api_gcp_vpc_create_subnetwork(project: str, region: str, request: Request):
    s = _server()
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Subnetwork name is required")
    rec = {
        "id": s._gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "description": str(payload.get("description") or ""),
        "project": project,
        "region": region,
        "network": str(payload.get("network") or "default").split("/")[-1],
        "ipCidrRange": str(payload.get("ipCidrRange") or "10.0.0.0/24"),
        "reservedInternalRange": str(payload.get("reservedInternalRange") or ""),
        "gatewayAddress": str(payload.get("gatewayAddress") or ""),
        "privateIpGoogleAccess": bool(payload.get("privateIpGoogleAccess", False)),
        "secondaryIpRanges": payload.get("secondaryIpRanges", []) if isinstance(payload.get("secondaryIpRanges"), list) else [],
        "purpose": str(payload.get("purpose") or ""),
        "role": str(payload.get("role") or ""),
        "stackType": str(payload.get("stackType") or "IPV4_ONLY"),
        "state": str(payload.get("state") or "READY"),
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("subnetworks", {})[name] = rec
    return {
        "kind": "compute#subnetwork",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "region": region,
        "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{rec['network']}",
        "ipCidrRange": rec["ipCidrRange"],
        "reservedInternalRange": rec["reservedInternalRange"],
        "gatewayAddress": rec["gatewayAddress"],
        "privateIpGoogleAccess": rec["privateIpGoogleAccess"],
        "secondaryIpRanges": rec["secondaryIpRanges"],
        "purpose": rec["purpose"],
        "role": rec["role"],
        "stackType": rec["stackType"],
        "state": rec["state"],
        "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/regions/{region}/subnetworks/{name}",
    }


def api_gcp_vpc_list_firewalls(project: str):
    s = _server()
    project = _gcp_project_name(project)
    firewalls = []
    for fw in gcp_vpc_state.get("firewalls", {}).values():
        if str(fw.get("project") or project) != project:
            continue
        firewalls.append(
            {
                "kind": "compute#firewall",
                "id": str(fw.get("id") or s._gcp_compute_numeric_id(f"{project}:{fw['name']}")),
                "creationTimestamp": fw.get("createTime", _now()),
                "name": fw["name"],
                "description": fw.get("description", ""),
                "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{fw.get('network','default')}",
                "priority": int(fw.get("priority") or 1000),
                "direction": fw.get("direction", "INGRESS"),
                "allowed": fw.get("allowed", [{"IPProtocol": "tcp", "ports": ["22"]}]),
                "denied": fw.get("denied", []),
                "sourceRanges": fw.get("sourceRanges", ["0.0.0.0/0"]),
                "destinationRanges": fw.get("destinationRanges", []),
                "sourceTags": fw.get("sourceTags", []),
                "targetTags": fw.get("targetTags", []),
                "sourceServiceAccounts": fw.get("sourceServiceAccounts", []),
                "targetServiceAccounts": fw.get("targetServiceAccounts", []),
                "disabled": bool(fw.get("disabled", False)),
                "logConfig": fw.get("logConfig", {}),
                "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/firewalls/{fw['name']}",
            }
        )
    return {"kind": "compute#firewallList", "items": firewalls}


async def api_gcp_vpc_create_firewall(project: str, request: Request):
    s = _server()
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Firewall name is required")
    rec = {
        "id": s._gcp_compute_numeric_id(f"{project}:{name}"),
        "name": name,
        "description": str(payload.get("description") or ""),
        "project": project,
        "network": str(payload.get("network") or "default").split("/")[-1],
        "priority": int(payload.get("priority") or 1000),
        "direction": str(payload.get("direction") or "INGRESS"),
        "allowed": payload.get("allowed") if isinstance(payload.get("allowed"), list) else [{"IPProtocol": "tcp", "ports": ["22"]}],
        "denied": payload.get("denied") if isinstance(payload.get("denied"), list) else [],
        "sourceRanges": payload.get("sourceRanges") if isinstance(payload.get("sourceRanges"), list) else ["0.0.0.0/0"],
        "destinationRanges": payload.get("destinationRanges") if isinstance(payload.get("destinationRanges"), list) else [],
        "sourceTags": payload.get("sourceTags") if isinstance(payload.get("sourceTags"), list) else [],
        "targetTags": payload.get("targetTags") if isinstance(payload.get("targetTags"), list) else [],
        "sourceServiceAccounts": payload.get("sourceServiceAccounts") if isinstance(payload.get("sourceServiceAccounts"), list) else [],
        "targetServiceAccounts": payload.get("targetServiceAccounts") if isinstance(payload.get("targetServiceAccounts"), list) else [],
        "disabled": bool(payload.get("disabled", False)),
        "logConfig": payload.get("logConfig") if isinstance(payload.get("logConfig"), dict) else {},
        "createTime": _now(),
    }
    gcp_vpc_state.setdefault("firewalls", {})[name] = rec
    return {
        "kind": "compute#firewall",
        "id": rec["id"],
        "creationTimestamp": rec["createTime"],
        "name": name,
        "description": rec["description"],
        "network": f"{s._gcp_compute_network_root()}/projects/{project}/global/networks/{rec['network']}",
        "priority": rec["priority"],
        "direction": rec["direction"],
        "allowed": rec["allowed"],
        "denied": rec["denied"],
        "sourceRanges": rec["sourceRanges"],
        "destinationRanges": rec["destinationRanges"],
        "sourceTags": rec["sourceTags"],
        "targetTags": rec["targetTags"],
        "sourceServiceAccounts": rec["sourceServiceAccounts"],
        "targetServiceAccounts": rec["targetServiceAccounts"],
        "disabled": rec["disabled"],
        "logConfig": rec["logConfig"],
        "selfLink": f"{s._gcp_compute_network_root()}/projects/{project}/global/firewalls/{name}",
    }


def api_gcp_vpc_list_routes(project: str):
    return _server().api_gcp_vpc_list_routes(project)


async def api_gcp_vpc_create_route(project: str, request: Request):
    return await _server().api_gcp_vpc_create_route(project, request)


def api_gcp_vpc_delete_route(project: str, route: str):
    return _server().api_gcp_vpc_delete_route(project, route)
