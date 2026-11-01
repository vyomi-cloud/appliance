"""Amazon DynamoDB Accelerator (DAX) core — substrate-independent, same shape as
core/dynamodb_core.py: plain functions over a store seam, native wire responses, no
fastapi / boto3 / socket imports (loads under Pyodide).

Two halves:
  1. Control plane (the AmazonDAXV3 JSON protocol real DAX SDKs/CLI speak): clusters,
     subnet groups, parameter groups, events, tags. CreateCluster/DescribeClusters/
     UpdateCluster/DeleteCluster/IncreaseReplicationFactor/DecreaseReplicationFactor/
     RebootNode; CreateSubnetGroup/DescribeSubnetGroups/UpdateSubnetGroup/
     DeleteSubnetGroup; CreateParameterGroup/DescribeParameterGroups/DescribeParameters/
     DescribeDefaultParameters/UpdateParameterGroup/DeleteParameterGroup; DescribeEvents;
     ListTags/TagResource/UntagResource. This is what the console pages
     (consoles/src/aws/services/dynamodb/dax/) drive.
  2. A real cache engine in front of the DynamoDB store (core/nosql_store.NoSqlStore):
     item cache + query cache, read-through / write-through, TTLs from the cluster's
     parameter group (record-ttl-millis / query-ttl-millis), strongly-consistent reads
     bypass the cache, LRU eviction sized by the cluster's node type. DAX's real client
     talks a binary protocol over a persistent TCP connection to the cluster's discovery
     endpoint — that wire comes later (wave 6 tunnel TCP relay); until then this engine
     is exercised directly (conformance tests, `get_item`/`put_item`/… below) rather
     than through a socket, which is why aws.dynamodb.dax.cache is "limited" in
     core/capabilities/aws/dynamodb.json.

Native errors use DAX's `{"__type", "message"}` shape, same convention as DynamoDB.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    from core import cloudwatch_core as _cw_core
except ImportError:  # pragma: no cover - Pyodide flat layout
    import cloudwatch_core as _cw_core  # type: ignore

DEFAULT_ACCOUNT_ID = "123456789012"


# ── transport types (same shape as DdbResponse/DdbError) ───────────────────
@dataclass
class DaxResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class DaxError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _validation(message: str) -> DaxError:
    return DaxError("InvalidParameterValueException", message, 400)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _epoch() -> float:
    return time.time()


def _short(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8]


# ── node type → approximate item-cache capacity (entries), for LRU sizing ──
_NODE_TYPE_CAPACITY = {
    "dax.t3.small": 200, "dax.t3.medium": 400,
    "dax.r4.large": 2000, "dax.r4.xlarge": 4000, "dax.r4.2xlarge": 8000,
    "dax.r4.4xlarge": 16000, "dax.r4.8xlarge": 32000, "dax.r4.16xlarge": 64000,
    "dax.r5.large": 2000, "dax.r5.xlarge": 4000, "dax.r5.2xlarge": 8000,
}
_DEFAULT_CAPACITY = 1000
DEFAULT_PARAMETER_GROUP = "default.dax1.0"


class DaxStore:
    """In-memory DAX control plane + cache engine. `ddb_store` and `cw_store` are
    wired by the router (same pattern as dynamodb_core's `_cw`/`_kinesis` seams)."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, region: str = "us-east-1") -> None:
        self.account_id = account_id
        self.region = region
        self.clusters: dict[str, dict] = {}
        self.subnet_groups: dict[str, dict] = {}
        self.parameter_groups: dict[str, dict] = {
            DEFAULT_PARAMETER_GROUP: {
                "parameter_group_name": DEFAULT_PARAMETER_GROUP,
                "description": "Default parameter group for dax1.0",
                "parameters": {"query-ttl-millis": "300000", "record-ttl-millis": "0"},
                "is_default": True,
            }
        }
        self.events: list[dict] = []
        self.tags: dict[str, dict[str, str]] = {}
        # Cache engine state (ephemeral — not control-plane state, so `_`-prefixed:
        # nano_persist's generic vars()-capture skips it, matching a real cache's
        # "lost on cold start" semantics). Keyed per-cluster.
        self._item_cache: dict[str, "OrderedDict[tuple, dict]"] = {}
        self._query_cache: dict[str, "OrderedDict[tuple, dict]"] = {}
        self.ddb_store: Any = None   # the NoSqlStore this cluster fronts (wired by the router)
        self.cw_store: Any = None    # CloudWatch (wired by the router)

    def persist(self) -> None:
        pass


def _record_event(store: DaxStore, source_name: str, source_type: str, message: str) -> None:
    store.events.insert(0, {"source_name": source_name, "source_type": source_type,
                            "message": message, "date": _now()})
    del store.events[500:]


def _emit_cache_metric(store: DaxStore, cluster_name: str, metric: str) -> None:
    cw = store.cw_store
    if cw is None:
        return
    dims = [{"Name": "ClusterId", "Value": cluster_name}]
    _cw_core.ingest_internal_metric(cw, "AWS/DAX", metric, dims, 1.0, unit="Count", ts=_epoch())


# ── ARNs / endpoints ─────────────────────────────────────────────────────────
def _cluster_arn(store: DaxStore, name: str) -> str:
    return f"arn:aws:dax:{store.region}:{store.account_id}:cache/{name}"


def _cluster_address(store: DaxStore, name: str) -> str:
    return f"{name}.{_short(store.account_id, name)}.dax-clusters.{store.region}.amazonaws.com"


def _node_address(store: DaxStore, cluster_name: str, node_id: str) -> str:
    return f"{node_id}.{_short(store.account_id, cluster_name, node_id)}.nodes.dax-clusters.{store.region}.amazonaws.com"


# ── clusters ─────────────────────────────────────────────────────────────────
def _require_cluster(store: DaxStore, name: str) -> dict:
    cl = store.clusters.get(str(name))
    if not cl:
        raise DaxError("ClusterNotFoundFault", f"Cluster not found: {name}", 400)
    return cl


def _make_node(cluster_name: str, idx: int, az: str) -> dict:
    node_id = f"{cluster_name}-{idx:03d}"
    return {"node_id": node_id, "node_status": "available", "availability_zone": az,
           "parameter_group_status": "in-sync", "node_create_time": _now()}


def _node_view(store: DaxStore, cluster_name: str, node: dict) -> dict:
    return {
        "NodeId": node["node_id"],
        "NodeStatus": node["node_status"],
        "AvailabilityZone": node["availability_zone"],
        "NodeCreateTime": node["node_create_time"],
        "Endpoint": {"Address": _node_address(store, cluster_name, node["node_id"]), "Port": 8111},
        "ParameterGroupStatus": node["parameter_group_status"],
    }


def _cluster_view(store: DaxStore, cl: dict) -> dict:
    name = cl["cluster_name"]
    nodes = cl["nodes"]
    pg = cl["parameter_group_name"]
    view = {
        "ClusterName": name,
        "Description": cl.get("description", ""),
        "ClusterArn": _cluster_arn(store, name),
        "TotalNodes": len(nodes),
        "ActiveNodes": sum(1 for n in nodes if n["node_status"] == "available"),
        "NodeType": cl["node_type"],
        "Status": cl["status"],
        "ClusterDiscoveryEndpoint": {"Address": _cluster_address(store, name), "Port": 8111,
                                     "URL": f"dax://{_cluster_address(store, name)}:8111"},
        "NodeIdsToRemove": [],
        "Nodes": [_node_view(store, name, n) for n in nodes],
        "PreferredMaintenanceWindow": cl.get("preferred_maintenance_window", "sun:05:00-sun:06:00"),
        "SubnetGroup": cl.get("subnet_group", ""),
        "SecurityGroups": [{"SecurityGroupIdentifier": sg, "Status": "active"}
                          for sg in cl.get("security_group_ids", [])],
        "IamRoleArn": cl.get("iam_role_arn", ""),
        "ParameterGroup": {"ParameterGroupName": pg, "ParameterApplyStatus": "in-sync", "NodeIdsToReboot": []},
        "SSEDescription": {"Status": "ENABLED" if cl.get("sse_enabled") else "DISABLED"},
        "ClusterEndpointEncryptionType": "TLS" if cl.get("cluster_endpoint_encryption_type") == "TLS" else "NONE",
    }
    if cl.get("notification_topic_arn"):
        view["NotificationConfiguration"] = {"TopicArn": cl["notification_topic_arn"], "TopicStatus": "active"}
    return view


def _create_cluster(store: DaxStore, payload: dict) -> dict:
    name = str(payload.get("ClusterName") or "")
    if not name or not (1 <= len(name) <= 20):
        raise _validation("ClusterName must be between 1 and 20 characters")
    if name in store.clusters:
        raise DaxError("ClusterAlreadyExistsFault", f"Cluster already exists: {name}", 400)
    node_type = str(payload.get("NodeType") or "")
    if not node_type:
        raise _validation("NodeType is required")
    rf = int(payload.get("ReplicationFactor") or 1)
    if rf < 1:
        raise _validation("ReplicationFactor must be at least 1")
    pg = str(payload.get("ParameterGroupName") or DEFAULT_PARAMETER_GROUP)
    if pg not in store.parameter_groups:
        raise DaxError("ParameterGroupNotFoundFault", f"Parameter group not found: {pg}", 400)
    subnet_group = str(payload.get("SubnetGroupName") or "")
    if subnet_group and subnet_group not in store.subnet_groups:
        raise DaxError("SubnetGroupNotFoundFault", f"Subnet group not found: {subnet_group}", 400)
    azs = payload.get("AvailabilityZones") or ["us-east-1a", "us-east-1b", "us-east-1c"]
    nodes = [_make_node(name, i + 1, azs[i % len(azs)]) for i in range(rf)]
    cl = {
        "cluster_name": name, "description": str(payload.get("Description") or ""),
        "node_type": node_type, "replication_factor": rf, "nodes": nodes,
        "parameter_group_name": pg, "subnet_group": subnet_group,
        "security_group_ids": list(payload.get("SecurityGroupIds") or []),
        "iam_role_arn": str(payload.get("IamRoleArn") or ""),
        "preferred_maintenance_window": str(payload.get("PreferredMaintenanceWindow") or "sun:05:00-sun:06:00"),
        "notification_topic_arn": str(payload.get("NotificationTopicArn") or ""),
        "sse_enabled": bool((payload.get("SSESpecification") or {}).get("Enabled")),
        "cluster_endpoint_encryption_type": str(payload.get("ClusterEndpointEncryptionType") or "NONE"),
        "status": "available", "created": _now(),
    }
    store.clusters[name] = cl
    tags = payload.get("Tags") or []
    if tags:
        store.tags[_cluster_arn(store, name)] = {t.get("Key"): t.get("Value") for t in tags if isinstance(t, dict)}
    store._item_cache[name] = OrderedDict()
    store._query_cache[name] = OrderedDict()
    _record_event(store, name, "CLUSTER", "Cluster created")
    store.persist()
    return cl


def _update_cluster(store: DaxStore, payload: dict) -> dict:
    cl = _require_cluster(store, str(payload.get("ClusterName") or ""))
    if "Description" in payload:
        cl["description"] = str(payload.get("Description") or "")
    if "PreferredMaintenanceWindow" in payload:
        cl["preferred_maintenance_window"] = str(payload["PreferredMaintenanceWindow"])
    if "NotificationTopicArn" in payload:
        cl["notification_topic_arn"] = str(payload.get("NotificationTopicArn") or "")
    if "ParameterGroupName" in payload:
        pg = str(payload["ParameterGroupName"])
        if pg not in store.parameter_groups:
            raise DaxError("ParameterGroupNotFoundFault", f"Parameter group not found: {pg}", 400)
        cl["parameter_group_name"] = pg
        for n in cl["nodes"]:
            n["parameter_group_status"] = "in-sync"
    if "SecurityGroupIds" in payload:
        cl["security_group_ids"] = list(payload.get("SecurityGroupIds") or [])
    _record_event(store, cl["cluster_name"], "CLUSTER", "Cluster settings updated")
    store.persist()
    return cl


def _delete_cluster(store: DaxStore, name: str) -> dict:
    cl = _require_cluster(store, name)
    cl["status"] = "deleting"
    view = _cluster_view(store, cl)
    del store.clusters[name]
    store._item_cache.pop(name, None)
    store._query_cache.pop(name, None)
    _record_event(store, name, "CLUSTER", "Cluster deleted")
    store.persist()
    return view


def _increase_replication_factor(store: DaxStore, payload: dict) -> dict:
    cl = _require_cluster(store, str(payload.get("ClusterName") or ""))
    new_rf = int(payload.get("NewReplicationFactor") or 0)
    if new_rf <= len(cl["nodes"]):
        raise _validation("NewReplicationFactor must be greater than the current replication factor")
    azs = payload.get("AvailabilityZones") or [n["availability_zone"] for n in cl["nodes"]] or ["us-east-1a"]
    next_idx = len(cl["nodes"]) + 1
    for i in range(new_rf - len(cl["nodes"])):
        cl["nodes"].append(_make_node(cl["cluster_name"], next_idx + i, azs[(next_idx + i - 1) % len(azs)]))
    cl["replication_factor"] = new_rf
    _record_event(store, cl["cluster_name"], "CLUSTER", f"Replication factor increased to {new_rf}")
    store.persist()
    return cl


def _decrease_replication_factor(store: DaxStore, payload: dict) -> dict:
    cl = _require_cluster(store, str(payload.get("ClusterName") or ""))
    new_rf = int(payload.get("NewReplicationFactor") or 0)
    if new_rf <= 0 or new_rf >= len(cl["nodes"]):
        raise _validation("NewReplicationFactor must be positive and less than the current replication factor")
    remove_ids = set(payload.get("NodeIdsToRemove") or [])
    if remove_ids:
        cl["nodes"] = [n for n in cl["nodes"] if n["node_id"] not in remove_ids]
    else:
        cl["nodes"] = cl["nodes"][:new_rf]
    cl["replication_factor"] = len(cl["nodes"])
    _record_event(store, cl["cluster_name"], "CLUSTER", f"Replication factor decreased to {cl['replication_factor']}")
    store.persist()
    return cl


def _reboot_node(store: DaxStore, payload: dict) -> dict:
    cl = _require_cluster(store, str(payload.get("ClusterName") or ""))
    node_id = str(payload.get("NodeId") or "")
    node = next((n for n in cl["nodes"] if n["node_id"] == node_id), None)
    if not node:
        raise DaxError("NodeNotFoundFault", f"Node not found: {node_id}", 400)
    # A reboot really drops that node's share of the cache (same effect a real reboot has).
    cache = store._item_cache.get(cl["cluster_name"])
    if cache is not None:
        cache.clear()
    _record_event(store, cl["cluster_name"], "CLUSTER", f"Node {node_id} rebooted")
    store.persist()
    return cl


# ── subnet groups ────────────────────────────────────────────────────────────
def _require_subnet_group(store: DaxStore, name: str) -> dict:
    sg = store.subnet_groups.get(str(name))
    if not sg:
        raise DaxError("SubnetGroupNotFoundFault", f"Subnet group not found: {name}", 400)
    return sg


def _subnet_group_view(sg: dict) -> dict:
    return {
        "SubnetGroupName": sg["subnet_group_name"], "Description": sg.get("description", ""),
        "VpcId": sg.get("vpc_id", ""),
        "Subnets": [{"SubnetIdentifier": s, "SubnetAvailabilityZone": az}
                    for s, az in zip(sg.get("subnet_ids", []), sg.get("availability_zones", []) or
                                     ["us-east-1a"] * len(sg.get("subnet_ids", [])))],
    }


def _create_subnet_group(store: DaxStore, payload: dict) -> dict:
    name = str(payload.get("SubnetGroupName") or "")
    if not name:
        raise _validation("SubnetGroupName is required")
    if name in store.subnet_groups:
        raise DaxError("SubnetGroupAlreadyExistsFault", f"Subnet group already exists: {name}", 400)
    subnet_ids = list(payload.get("SubnetIds") or [])
    if not subnet_ids:
        raise _validation("SubnetIds must not be empty")
    sg = {"subnet_group_name": name, "description": str(payload.get("Description") or ""),
         "vpc_id": str(payload.get("VpcId") or "") or "vpc-" + _short(store.account_id, "vpc", name),
         "subnet_ids": subnet_ids}
    store.subnet_groups[name] = sg
    store.persist()
    return sg


def _update_subnet_group(store: DaxStore, payload: dict) -> dict:
    sg = _require_subnet_group(store, str(payload.get("SubnetGroupName") or ""))
    if "Description" in payload:
        sg["description"] = str(payload.get("Description") or "")
    if payload.get("SubnetIds"):
        sg["subnet_ids"] = list(payload["SubnetIds"])
    store.persist()
    return sg


# ── parameter groups ─────────────────────────────────────────────────────────
_VALID_PARAMS = {"query-ttl-millis", "record-ttl-millis"}


def _require_parameter_group(store: DaxStore, name: str) -> dict:
    pg = store.parameter_groups.get(str(name))
    if not pg:
        raise DaxError("ParameterGroupNotFoundFault", f"Parameter group not found: {name}", 400)
    return pg


def _parameter_group_view(pg: dict) -> dict:
    return {"ParameterGroupName": pg["parameter_group_name"], "Description": pg.get("description", "")}


def _parameters_view(pg: dict) -> list:
    return [{"ParameterName": k, "ParameterValue": v, "ParameterType": "USER" if not pg.get("is_default") else "DEFAULT",
            "IsModifiable": True, "Description": _PARAM_DOC.get(k, "")} for k, v in pg.get("parameters", {}).items()]


_PARAM_DOC = {
    "query-ttl-millis": "TTL in milliseconds for the DAX query cache.",
    "record-ttl-millis": "TTL in milliseconds for the DAX item cache (0 = no expiry).",
}


def _create_parameter_group(store: DaxStore, payload: dict) -> dict:
    name = str(payload.get("ParameterGroupName") or "")
    if not name:
        raise _validation("ParameterGroupName is required")
    if name in store.parameter_groups:
        raise DaxError("ParameterGroupAlreadyExistsFault", f"Parameter group already exists: {name}", 400)
    pg = {"parameter_group_name": name, "description": str(payload.get("Description") or ""),
         "parameters": {"query-ttl-millis": "300000", "record-ttl-millis": "0"}}
    store.parameter_groups[name] = pg
    store.persist()
    return pg


def _update_parameter_group(store: DaxStore, payload: dict) -> dict:
    pg = _require_parameter_group(store, str(payload.get("ParameterGroupName") or ""))
    if pg.get("is_default"):
        raise _validation("The default parameter group cannot be modified")
    for p in payload.get("ParameterNameValues") or []:
        pname, pval = str(p.get("ParameterName") or ""), p.get("ParameterValue")
        if pname not in _VALID_PARAMS:
            raise _validation(f"Invalid parameter name: {pname}")
        try:
            if int(pval) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise _validation(f"{pname} must be a non-negative integer")
        pg["parameters"][pname] = str(pval)
    store.persist()
    return pg


# ── tags ─────────────────────────────────────────────────────────────────────
def _tags_view(store: DaxStore, arn: str) -> list:
    return [{"Key": k, "Value": v} for k, v in store.tags.get(arn, {}).items()]


# ── events ───────────────────────────────────────────────────────────────────
def _events_view(store: DaxStore, source_name: str, source_type: str) -> list:
    rows = store.events
    if source_name:
        rows = [e for e in rows if e["source_name"] == source_name]
    if source_type:
        rows = [e for e in rows if e["source_type"] == source_type.upper()]
    return [{"SourceName": e["source_name"], "SourceType": e["source_type"], "Message": e["message"],
            "Date": e["date"]} for e in rows]


# ── cache engine (read-through / write-through; conformance/console hooks) ──
def _ttl_seconds(store: DaxStore, cl: dict, key: str) -> float:
    pg = store.parameter_groups.get(cl["parameter_group_name"]) or {}
    ms = int((pg.get("parameters") or {}).get(key, 0) or 0)
    return ms / 1000.0


def _cache_capacity(cl: dict) -> int:
    return _NODE_TYPE_CAPACITY.get(cl.get("node_type", ""), _DEFAULT_CAPACITY)


def _lru_touch(cache: "OrderedDict", k: tuple, v: dict, capacity: int) -> None:
    cache[k] = v
    cache.move_to_end(k)
    while len(cache) > capacity:
        cache.popitem(last=False)


def _key_tuple(key: dict) -> tuple:
    return tuple(sorted((k, json.dumps(v, sort_keys=True)) for k, v in (key or {}).items()))


def _ddb() -> Any:
    try:
        from core import dynamodb_core as m
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import dynamodb_core as m  # type: ignore
    return m


def get_item(store: DaxStore, cluster_name: str, table_name: str, key: dict, *,
             consistent_read: bool = False) -> dict | None:
    """Read-through GetItem: a cache hit skips the DynamoDB store entirely; a miss
    (or a strongly-consistent read, which always bypasses the cache) falls through to
    the real DynamoDB core (so expiry/projection/validation all behave exactly like
    DynamoDB itself) and populates the item cache with record-ttl-millis."""
    cl = _require_cluster(store, cluster_name)
    cache = store._item_cache.setdefault(cluster_name, OrderedDict())
    ck = (table_name, _key_tuple(key))
    if not consistent_read:
        entry = cache.get(ck)
        if entry is not None:
            if entry["expires"] is None or entry["expires"] > _epoch():
                cache.move_to_end(ck)
                _emit_cache_metric(store, cluster_name, "ItemCacheHits")
                return entry["item"]
            del cache[ck]
        _emit_cache_metric(store, cluster_name, "ItemCacheMisses")
    if store.ddb_store is None:
        return None
    r = _ddb().dispatch(store.ddb_store, "DynamoDB_20120810.GetItem",
                        {"TableName": table_name, "Key": key, "ConsistentRead": consistent_read})
    av = r.body.get("Item") if r.status == 200 else None
    if not consistent_read and av is not None:
        ttl = _ttl_seconds(store, cl, "record-ttl-millis")
        _lru_touch(cache, ck, {"item": av, "expires": (_epoch() + ttl) if ttl > 0 else None}, _cache_capacity(cl))
    return av


def put_item(store: DaxStore, cluster_name: str, table_name: str, item: dict) -> None:
    """Write-through PutItem: the write lands in the real DynamoDB core first, then
    the item cache entry is refreshed from the table's own key schema (never left stale)."""
    _require_cluster(store, cluster_name)
    if store.ddb_store is None:
        return
    r = _ddb().dispatch(store.ddb_store, "DynamoDB_20120810.PutItem", {"TableName": table_name, "Item": item})
    if r.status != 200:
        raise DaxError("InvalidParameterValueException", str(r.body.get("message") or "PutItem failed"), 400)
    table = store.ddb_store.get_table(table_name) or {}
    key_names = [n for n in (table.get("partition_key_name"), table.get("sort_key_name")) if n]
    key = {n: item[n] for n in key_names if n in item}
    cl = store.clusters[cluster_name]
    cache = store._item_cache.setdefault(cluster_name, OrderedDict())
    ck = (table_name, _key_tuple(key))
    ttl = _ttl_seconds(store, cl, "record-ttl-millis")
    _lru_touch(cache, ck, {"item": item, "expires": (_epoch() + ttl) if ttl > 0 else None}, _cache_capacity(cl))
    store._query_cache.get(cluster_name, OrderedDict()).clear()   # a write can change any cached query's result set


def delete_item(store: DaxStore, cluster_name: str, table_name: str, key: dict) -> None:
    _require_cluster(store, cluster_name)
    if store.ddb_store is not None:
        _ddb().dispatch(store.ddb_store, "DynamoDB_20120810.DeleteItem", {"TableName": table_name, "Key": key})
    cache = store._item_cache.setdefault(cluster_name, OrderedDict())
    cache.pop((table_name, _key_tuple(key)), None)
    store._query_cache.get(cluster_name, OrderedDict()).clear()


def query(store: DaxStore, cluster_name: str, table_name: str, query_signature: dict) -> list | None:
    """Read-through query cache keyed by the query's shape; TTL from query-ttl-millis."""
    cl = _require_cluster(store, cluster_name)
    cache = store._query_cache.setdefault(cluster_name, OrderedDict())
    qk = (table_name, json.dumps(query_signature, sort_keys=True))
    entry = cache.get(qk)
    if entry is not None and (entry["expires"] is None or entry["expires"] > _epoch()):
        cache.move_to_end(qk)
        _emit_cache_metric(store, cluster_name, "QueryCacheHits")
        return entry["items"]
    _emit_cache_metric(store, cluster_name, "QueryCacheMisses")
    return None


def put_query_result(store: DaxStore, cluster_name: str, table_name: str, query_signature: dict, items: list) -> None:
    cl = _require_cluster(store, cluster_name)
    cache = store._query_cache.setdefault(cluster_name, OrderedDict())
    qk = (table_name, json.dumps(query_signature, sort_keys=True))
    ttl = _ttl_seconds(store, cl, "query-ttl-millis")
    _lru_touch(cache, qk, {"items": items, "expires": (_epoch() + ttl) if ttl > 0 else None}, _cache_capacity(cl))




# ── dispatch (AmazonDAXV3 JSON protocol) ────────────────────────────────────
def dispatch(store: DaxStore, target: str, payload: dict | None = None) -> DaxResponse:
    payload = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return DaxResponse(400, {"__type": "MissingAction", "message": "The request must include X-Amz-Target."})
    try:
        if action == "CreateCluster":
            cl = _create_cluster(store, payload)
            return DaxResponse(200, {"Cluster": _cluster_view(store, cl)})

        if action == "DescribeClusters":
            names = payload.get("ClusterNames")
            rows = [store.clusters[n] for n in names if n in store.clusters] if names else list(store.clusters.values())
            rows.sort(key=lambda c: c["cluster_name"])
            return DaxResponse(200, {"Clusters": [_cluster_view(store, c) for c in rows]})

        if action == "UpdateCluster":
            cl = _update_cluster(store, payload)
            return DaxResponse(200, {"Cluster": _cluster_view(store, cl)})

        if action == "DeleteCluster":
            view = _delete_cluster(store, str(payload.get("ClusterName") or ""))
            view["Status"] = "deleting"
            return DaxResponse(200, {"Cluster": view})

        if action == "IncreaseReplicationFactor":
            cl = _increase_replication_factor(store, payload)
            return DaxResponse(200, {"Cluster": _cluster_view(store, cl)})

        if action == "DecreaseReplicationFactor":
            cl = _decrease_replication_factor(store, payload)
            return DaxResponse(200, {"Cluster": _cluster_view(store, cl)})

        if action == "RebootNode":
            cl = _reboot_node(store, payload)
            return DaxResponse(200, {"Cluster": _cluster_view(store, cl)})

        if action == "CreateSubnetGroup":
            sg = _create_subnet_group(store, payload)
            return DaxResponse(200, {"SubnetGroup": _subnet_group_view(sg)})

        if action == "DescribeSubnetGroups":
            names = payload.get("SubnetGroupNames")
            rows = [store.subnet_groups[n] for n in names if n in store.subnet_groups] if names \
                else list(store.subnet_groups.values())
            rows.sort(key=lambda s: s["subnet_group_name"])
            return DaxResponse(200, {"SubnetGroups": [_subnet_group_view(s) for s in rows]})

        if action == "UpdateSubnetGroup":
            sg = _update_subnet_group(store, payload)
            return DaxResponse(200, {"SubnetGroup": _subnet_group_view(sg)})

        if action == "DeleteSubnetGroup":
            name = str(payload.get("SubnetGroupName") or "")
            _require_subnet_group(store, name)
            del store.subnet_groups[name]
            store.persist()
            return DaxResponse(200, {})

        if action == "CreateParameterGroup":
            pg = _create_parameter_group(store, payload)
            return DaxResponse(200, {"ParameterGroup": _parameter_group_view(pg)})

        if action == "DescribeParameterGroups":
            names = payload.get("ParameterGroupNames")
            rows = [store.parameter_groups[n] for n in names if n in store.parameter_groups] if names \
                else list(store.parameter_groups.values())
            rows.sort(key=lambda p: p["parameter_group_name"])
            return DaxResponse(200, {"ParameterGroups": [_parameter_group_view(p) for p in rows]})

        if action == "DescribeParameters":
            pg = _require_parameter_group(store, str(payload.get("ParameterGroupName") or ""))
            return DaxResponse(200, {"Parameters": _parameters_view(pg)})

        if action == "DescribeDefaultParameters":
            pg = store.parameter_groups[DEFAULT_PARAMETER_GROUP]
            return DaxResponse(200, {"Parameters": _parameters_view(pg)})

        if action == "UpdateParameterGroup":
            pg = _update_parameter_group(store, payload)
            return DaxResponse(200, {"ParameterGroup": _parameter_group_view(pg)})

        if action == "DeleteParameterGroup":
            name = str(payload.get("ParameterGroupName") or "")
            pg = _require_parameter_group(store, name)
            if pg.get("is_default"):
                raise _validation("The default parameter group cannot be deleted")
            del store.parameter_groups[name]
            store.persist()
            return DaxResponse(200, {})

        if action == "DescribeEvents":
            rows = _events_view(store, str(payload.get("SourceName") or ""), str(payload.get("SourceType") or ""))
            return DaxResponse(200, {"Events": rows})

        if action == "ListTags":
            return DaxResponse(200, {"Tags": _tags_view(store, str(payload.get("ResourceName") or ""))})

        if action == "TagResource":
            arn = str(payload.get("ResourceName") or "")
            tags = store.tags.setdefault(arn, {})
            for t in payload.get("Tags") or []:
                if isinstance(t, dict):
                    tags[str(t.get("Key"))] = str(t.get("Value"))
            store.persist()
            return DaxResponse(200, {"Tags": _tags_view(store, arn)})

        if action == "UntagResource":
            arn = str(payload.get("ResourceName") or "")
            tags = store.tags.get(arn, {})
            for k in payload.get("TagKeys") or []:
                tags.pop(str(k), None)
            store.persist()
            return DaxResponse(200, {"Tags": _tags_view(store, arn)})

        return DaxResponse(400, {"__type": "UnknownOperationException",
                                 "message": f"The action {action} is not implemented."})
    except DaxError as e:
        return DaxResponse(e.status, {"__type": e.code, "message": e.message})
