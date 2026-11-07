"""RDS wire gaps (v4 wire sweep), served behind core/rds_core.dispatch.

Aurora / Multi-AZ-cluster control plane on the SAME store the instance ops use: DB clusters (create / describe / modify / delete /
start / stop / reboot / failover / promote / HTTP endpoint / capacity / roles) whose members are REAL DB instances created with
``DBClusterIdentifier`` (first member is the writer; the instance record carries ``db_cluster_identifier`` and is rendered
into DescribeDBInstances), cluster snapshots (+ attributes, copy, restore), cluster parameter groups, custom cluster endpoints,
global clusters, DB security groups, DB snapshot attributes / copy / modify, point-in-time restore, subnet-group / option-group /
event-subscription modification, parameter-group reset / copy, proxy modify + target groups + endpoints, pending maintenance
(derived from live instance state: an instance on an old CA has a real pending ca-certificate-rotation), orderable-option /
valid-modification / engine-default catalogs.

Honest limits: cluster storage is not a separate volume (the SQL data lives in the writer instance's engine; a cluster snapshot
captures the writer's tables for export, and restore recreates the cluster METADATA - data is not replayed into new members);
Backtrack, Blue/Green deployments, shard groups, tenant databases, activity streams and cross-region automated-backup
replication are not modelled; the orderable-option / major-version / reserved-offering catalogs are static tables, not the full
AWS matrix."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _esc


def _R():
    try:
        from core import rds_core as r
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import rds_core as r  # type: ignore
    return r


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _g(store):
    g = store.__dict__.setdefault("gap", {})
    for k in ("clusters", "csnaps", "cpgs", "ceps", "globals", "secgroups", "snapattrs", "pending", "pxeps", "pxtg", "automated_repl"):
        g.setdefault(k, {})
    return g


# ───────────────────────── XML ─────────────────────────
_MEM = {"DBClusterMembers": "DBClusterMember", "VpcSecurityGroups": "VpcSecurityGroupMembership", "AvailabilityZones": "AvailabilityZone",
        "AssociatedRoles": "DBClusterRole", "ReadReplicaIdentifiers": "ReadReplicaIdentifier", "DBClusters": "DBCluster",
        "DBClusterSnapshots": "DBClusterSnapshot", "DBClusterParameterGroups": "DBClusterParameterGroup", "Parameters": "Parameter",
        "DBClusterEndpoints": "DBClusterEndpoint", "GlobalClusters": "GlobalClusterMember", "GlobalClusterMembers": "GlobalClusterMember",
        "DBSecurityGroups": "DBSecurityGroup", "EC2SecurityGroups": "EC2SecurityGroup", "IPRanges": "IPRange", "StaticMembers": "member",
        "ExcludedMembers": "member", "Readers": "member", "DBClusterSnapshotAttributes": "DBClusterSnapshotAttribute", "DBSnapshotAttributes": "DBSnapshotAttribute",
        "AttributeValues": "AttributeValue", "DBProxyEndpoints": "DBProxyEndpoint", "TargetGroups": "member", "VpcSubnetIds": "member",
        "VpcSecurityGroupIds": "member", "OrderableDBInstanceOptions": "OrderableDBInstanceOption", "ValidStorageOptions": "ValidStorageOptions",
        "StorageSize": "Range", "ValidDBInstanceClassesForModification": "x", "PendingMaintenanceActions": "ResourcePendingMaintenanceActions",
        "PendingMaintenanceActionDetails": "PendingMaintenanceAction", "EventCategoriesMapList": "EventCategoriesMap", "EventCategories": "EventCategory",
        "SourceRegions": "SourceRegion", "ReservedDBInstancesOfferings": "ReservedDBInstancesOffering", "RecurringCharges": "RecurringCharge",
        "DBMajorEngineVersions": "DBMajorEngineVersion", "ValidUpgradeTarget": "UpgradeTarget", "SupportedEngineModes": "member",
        "ServerlessV2PlatformVersions": "ServerlessV2PlatformVersionInfo", "AvailabilityZoneList": "AvailabilityZone", "AvailabilityZoneGroup": "x",
        "SupportedEngineModesList": "member", "DomainMemberships": "DomainMembership", "EnabledCloudwatchLogsExports": "member", "DBClusterOptionGroupMemberships": "DBClusterOptionGroup",
        "DBClusterBacktracks": "DBClusterBacktrack", "DBClusterAutomatedBackups": "DBClusterAutomatedBackup", "TagList": "Tag", "DBProxyTargetGroupsList": "x",
        "CustomEndpointList": "x", "FailoverState": "x"}


def _x(tag, val):
    if val is None:
        return ""
    if isinstance(val, bool):
        return f"<{tag}>{'true' if val else 'false'}</{tag}>"
    if isinstance(val, dict):
        return f"<{tag}>" + "".join(_x(k, v) for k, v in val.items()) + f"</{tag}>"
    if isinstance(val, (list, tuple)):
        m = _MEM.get(tag, "member")
        return f"<{tag}>" + "".join(_x(m, v) for v in val) + f"</{tag}>"
    return f"<{tag}>{_esc(str(val))}</{tag}>"


def _ok(action, inner=""):
    return _R()._success(action, inner)


def _err(code, msg, status=400):
    raise _R().RdsError(code, msg, status)


def _p(params, k, default=""):
    v = params.get(k)
    return default if v is None else str(v)


def _b(params, k, default=False):
    v = params.get(k)
    return default if v is None else str(v).lower() == "true"


def _i(params, k, default):
    v = params.get(k)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _list(params, prefix):
    return _R()._members(params, prefix)


def _tags(params):
    return _R()._tags_from_params(params)


def _filters(params):
    out, i = {}, 1
    while f"Filters.Filter.{i}.Name" in params or f"Filters.member.{i}.Name" in params:
        base = f"Filters.Filter.{i}" if f"Filters.Filter.{i}.Name" in params else f"Filters.member.{i}"
        vals, j = [], 1
        while True:
            v = params.get(f"{base}.Values.Value.{j}", params.get(f"{base}.Values.member.{j}"))
            if v is None:
                break
            vals.append(v)
            j += 1
        out[params[f"{base}.Name"]] = vals
        i += 1
    return out


# ───────────────────────── clusters ─────────────────────────
_ENGINE_PORT = {"aurora-mysql": 3306, "aurora": 3306, "mysql": 3306, "aurora-postgresql": 5432, "postgres": 5432}
_ENGINE_VER = {"aurora-mysql": "8.0.mysql_aurora.3.05.2", "aurora": "5.6.mysql_aurora.1.23.4", "aurora-postgresql": "16.4", "mysql": "8.0.39", "postgres": "16.4"}
_ENGINE_FAMILY = {"aurora-mysql": "aurora-mysql8.0", "aurora": "aurora5.6", "aurora-postgresql": "aurora-postgresql16", "mysql": "mysql8.0", "postgres": "postgres16"}


def _carn(store, cid):
    return f"arn:aws:rds:us-east-1:{store.account_id}:cluster:{cid}"


def _need_cluster(store, cid):
    c = _g(store)["clusters"].get((cid or "").lower())
    if c is None:
        _err("DBClusterNotFoundFault", f"DBCluster {cid} not found.", 404)
    return c


def _members_of(store, cid):
    return [store.get_instance(i) for i in store.instance_ids() if (store.get_instance(i) or {}).get("db_cluster_identifier") == cid]


def _cluster_view(store, c):
    mem = _members_of(store, c["DBClusterIdentifier"])
    writer = next((m for m in mem if m.get("is_cluster_writer")), None)
    v = {k: val for k, val in c.items() if not k.startswith("_")}
    v["DBClusterMembers"] = [{"DBInstanceIdentifier": m["db_instance_identifier"], "IsClusterWriter": bool(m.get("is_cluster_writer")),
                              "DBClusterParameterGroupStatus": "in-sync", "PromotionTier": int(m.get("promotion_tier", 1))} for m in mem]
    v["MultiAZ"] = len({m.get("availability_zone") for m in mem}) > 1
    if c["Status"] == "available" and mem and all(m.get("db_instance_status") == "stopped" for m in mem):
        v["Status"] = "stopped"
    v["_writer"] = writer["db_instance_identifier"] if writer else None
    v.pop("_writer")
    return v


def _cluster_xml(store, c):
    return _x("DBCluster", _cluster_view(store, c))


def create_cluster(store, params, msg_store=None):
    R = _R()
    cid = _p(params, "DBClusterIdentifier").lower()
    if not cid:
        _err("InvalidParameterValue", "DBClusterIdentifier is required.")
    if cid in _g(store)["clusters"]:
        _err("DBClusterAlreadyExistsFault", f"DB cluster {cid} already exists.")
    engine = _p(params, "Engine").lower()
    if engine not in _ENGINE_PORT:
        _err("InvalidParameterValue", f"Invalid DB engine: {params.get('Engine') or ''}")
    if not _p(params, "MasterUsername") and not params.get("SnapshotIdentifier") and not params.get("_restore"):
        _err("InvalidParameterCombination", "The parameter MasterUsername must be provided and must not be blank.")
    pgn = _p(params, "DBClusterParameterGroupName", f"default.{_ENGINE_FAMILY[engine]}")
    if pgn in _g(store)["cpgs"] or pgn.startswith("default."):
        pass
    else:
        _err("DBParameterGroupNotFound", f"DB cluster parameter group {pgn} not found.", 404)
    sg = _p(params, "DBSubnetGroupName", "default")
    if sg != "default" and not store.get_subnet_group(sg):
        _err("DBSubnetGroupNotFoundFault", f"DB subnet group {sg} not found.", 404)
    arn = _carn(store, cid)
    c = {"DBClusterIdentifier": cid, "DBClusterArn": arn, "DbClusterResourceId": "cluster-" + uuid.uuid4().hex[:26].upper(), "Status": "available",
         "Engine": engine, "EngineVersion": _p(params, "EngineVersion", _ENGINE_VER[engine]), "EngineMode": _p(params, "EngineMode", "provisioned"),
         "Port": _i(params, "Port", _ENGINE_PORT[engine]), "MasterUsername": _p(params, "MasterUsername", "admin"), "DatabaseName": params.get("DatabaseName"),
         "Endpoint": f"{cid}.cluster-nano.us-east-1.rds.amazonaws.com", "ReaderEndpoint": f"{cid}.cluster-ro-nano.us-east-1.rds.amazonaws.com",
         "AvailabilityZones": _list(params, "AvailabilityZones") or ["us-east-1a", "us-east-1b", "us-east-1c"], "BackupRetentionPeriod": _i(params, "BackupRetentionPeriod", 1),
         "DBClusterParameterGroup": pgn, "DBSubnetGroup": sg, "PreferredBackupWindow": _p(params, "PreferredBackupWindow", "07:00-09:00"),
         "PreferredMaintenanceWindow": _p(params, "PreferredMaintenanceWindow", "sun:05:00-sun:06:00"), "ClusterCreateTime": _now(),
         "StorageEncrypted": _b(params, "StorageEncrypted"), "KmsKeyId": params.get("KmsKeyId"), "DeletionProtection": _b(params, "DeletionProtection"),
         "HttpEndpointEnabled": _b(params, "EnableHttpEndpoint"), "IAMDatabaseAuthenticationEnabled": _b(params, "EnableIAMDatabaseAuthentication"),
         "AssociatedRoles": [], "VpcSecurityGroups": [{"VpcSecurityGroupId": s, "Status": "active"} for s in (_list(params, "VpcSecurityGroupIds") or ["sg-default"])],
         "CopyTagsToSnapshot": _b(params, "CopyTagsToSnapshot"), "StorageType": _p(params, "StorageType", "aurora"), "NetworkType": "IPV4",
         "EnabledCloudwatchLogsExports": _list(params, "EnableCloudwatchLogsExports"), "ReplicationSourceIdentifier": params.get("ReplicationSourceIdentifier"),
         "ReadReplicaIdentifiers": [], "GlobalClusterIdentifier": params.get("GlobalClusterIdentifier"), "CrossAccountClone": False,
         "AutoMinorVersionUpgrade": True, "AllocatedStorage": _i(params, "AllocatedStorage", 1), "DBClusterInstanceClass": params.get("DBClusterInstanceClass")}
    if params.get("ServerlessV2ScalingConfiguration.MinCapacity") is not None:
        c["ServerlessV2ScalingConfiguration"] = {"MinCapacity": float(params["ServerlessV2ScalingConfiguration.MinCapacity"]),
                                                 "MaxCapacity": float(params.get("ServerlessV2ScalingConfiguration.MaxCapacity", 1))}
    if params.get("ScalingConfiguration.MinCapacity") is not None:
        c["ScalingConfigurationInfo"] = {"MinCapacity": int(params["ScalingConfiguration.MinCapacity"]), "MaxCapacity": int(params.get("ScalingConfiguration.MaxCapacity", 16)),
                                         "AutoPause": _b({"x": params.get("ScalingConfiguration.AutoPause")}, "x")}
    gid = c["GlobalClusterIdentifier"]
    if gid:
        gc = _g(store)["globals"].get(gid)
        if gc is None:
            _err("GlobalClusterNotFoundFault", f"Global cluster {gid} not found.", 404)
        gc["GlobalClusterMembers"].append({"DBClusterArn": arn, "IsWriter": not gc["GlobalClusterMembers"], "Readers": []})
    c["_pw"] = _p(params, "MasterUserPassword")
    _g(store)["clusters"][cid] = c
    t = _tags(params)
    if t:
        store.set_tags(arn, t)
    store.persist()
    R._log_event(store, cid, "db-cluster", f"DB cluster {cid} created.", ["creation"], msg_store)
    return c


def op_CreateDBCluster(store, params, msg_store=None):
    c = create_cluster(store, params, msg_store)
    return _ok("CreateDBCluster", _cluster_xml(store, c))


def op_DescribeDBClusters(store, params, msg_store=None):
    cid = _p(params, "DBClusterIdentifier").lower()
    items = list(_g(store)["clusters"].values())
    if cid:
        items = [_need_cluster(store, cid)]
    f = _filters(params)
    if f.get("db-cluster-id"):
        want = {w.lower().rsplit(":", 1)[-1] for w in f["db-cluster-id"]}
        items = [c for c in items if c["DBClusterIdentifier"] in want]
    if f.get("engine"):
        items = [c for c in items if c["Engine"] in f["engine"]]
    return _ok("DescribeDBClusters", "<DBClusters>" + "".join(_cluster_xml(store, c) for c in items) + "</DBClusters>")


def op_ModifyDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    for pk, fk, cast in (("EngineVersion", "EngineVersion", str), ("Port", "Port", int), ("BackupRetentionPeriod", "BackupRetentionPeriod", int),
                         ("PreferredBackupWindow", "PreferredBackupWindow", str), ("PreferredMaintenanceWindow", "PreferredMaintenanceWindow", str),
                         ("DBClusterParameterGroupName", "DBClusterParameterGroup", str), ("StorageType", "StorageType", str),
                         ("MasterUserPassword", "_pw", str), ("AllocatedStorage", "AllocatedStorage", int)):
        if params.get(pk) is not None:
            if pk == "DBClusterParameterGroupName" and params[pk] not in _g(store)["cpgs"] and not params[pk].startswith("default."):
                _err("DBParameterGroupNotFound", f"DB cluster parameter group {params[pk]} not found.", 404)
            c[fk] = cast(params[pk])
    for pk, fk in (("DeletionProtection", "DeletionProtection"), ("CopyTagsToSnapshot", "CopyTagsToSnapshot"),
                   ("EnableIAMDatabaseAuthentication", "IAMDatabaseAuthenticationEnabled"), ("EnableHttpEndpoint", "HttpEndpointEnabled")):
        if params.get(pk) is not None:
            c[fk] = _b(params, pk)
    if _list(params, "VpcSecurityGroupIds"):
        c["VpcSecurityGroups"] = [{"VpcSecurityGroupId": s, "Status": "active"} for s in _list(params, "VpcSecurityGroupIds")]
    if params.get("ServerlessV2ScalingConfiguration.MinCapacity") is not None:
        c["ServerlessV2ScalingConfiguration"] = {"MinCapacity": float(params["ServerlessV2ScalingConfiguration.MinCapacity"]),
                                                 "MaxCapacity": float(params.get("ServerlessV2ScalingConfiguration.MaxCapacity", 1))}
    new = _p(params, "NewDBClusterIdentifier").lower()
    if new and new != c["DBClusterIdentifier"]:
        if new in _g(store)["clusters"]:
            _err("DBClusterAlreadyExistsFault", f"DB cluster {new} already exists.")
        old = c["DBClusterIdentifier"]
        del _g(store)["clusters"][old]
        c["DBClusterIdentifier"], c["DBClusterArn"] = new, _carn(store, new)
        c["Endpoint"] = f"{new}.cluster-nano.us-east-1.rds.amazonaws.com"
        c["ReaderEndpoint"] = f"{new}.cluster-ro-nano.us-east-1.rds.amazonaws.com"
        _g(store)["clusters"][new] = c
        for m in _members_of(store, old):
            m["db_cluster_identifier"] = new
    store.persist()
    _R()._log_event(store, c["DBClusterIdentifier"], "db-cluster", "DB cluster modified.", ["configuration change"], msg_store)
    return _ok("ModifyDBCluster", _cluster_xml(store, c))


def op_DeleteDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    cid = c["DBClusterIdentifier"]
    if c.get("DeletionProtection"):
        _err("InvalidParameterCombination", "Cannot delete protected DB Cluster, please disable deletion protection and try again.")
    if _members_of(store, cid):
        _err("InvalidDBClusterStateFault", f"Cluster cannot be deleted, it still contains DB instances in non-deleting state.")
    if not _b(params, "SkipFinalSnapshot", False) and not _p(params, "FinalDBSnapshotIdentifier"):
        _err("InvalidParameterCombination", "FinalDBSnapshotIdentifier is required unless SkipFinalSnapshot is specified.")
    if _p(params, "FinalDBSnapshotIdentifier") and not _b(params, "SkipFinalSnapshot"):
        _snapshot_cluster(store, c, _p(params, "FinalDBSnapshotIdentifier"), "automated")
    view = _cluster_xml(store, c)
    for gc in _g(store)["globals"].values():
        gc["GlobalClusterMembers"] = [m for m in gc["GlobalClusterMembers"] if m["DBClusterArn"] != c["DBClusterArn"]]
    for k in [k for k, e in _g(store)["ceps"].items() if e["_cluster"] == cid]:
        del _g(store)["ceps"][k]
    del _g(store)["clusters"][cid]
    store.persist()
    _R()._log_event(store, cid, "db-cluster", f"DB cluster {cid} deleted.", ["deletion"], msg_store)
    return _ok("DeleteDBCluster", view.replace("<Status>available</Status>", "<Status>deleting</Status>", 1))


def _set_members(store, cid, status):
    for m in _members_of(store, cid):
        m["db_instance_status"] = status
        m["updated"] = _now()


def op_StopDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if c["Status"] == "stopped" or (_members_of(store, c["DBClusterIdentifier"]) and all(m.get("db_instance_status") == "stopped" for m in _members_of(store, c["DBClusterIdentifier"]))):
        _err("InvalidDBClusterStateFault", f"DB cluster {c['DBClusterIdentifier']} is not in available state.")
    if c["EngineMode"] != "provisioned":
        _err("InvalidDBClusterStateFault", "Only provisioned clusters can be stopped.")
    _set_members(store, c["DBClusterIdentifier"], "stopped")
    c["Status"] = "stopped"
    store.persist()
    return _ok("StopDBCluster", _cluster_xml(store, c))


def op_StartDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if c["Status"] != "stopped":
        _err("InvalidDBClusterStateFault", f"DB cluster {c['DBClusterIdentifier']} is not in stopped state.")
    _set_members(store, c["DBClusterIdentifier"], "available")
    c["Status"] = "available"
    store.persist()
    return _ok("StartDBCluster", _cluster_xml(store, c))


def op_RebootDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if c["Status"] == "stopped":
        _err("InvalidDBClusterStateFault", f"DB cluster {c['DBClusterIdentifier']} is stopped.")
    _set_members(store, c["DBClusterIdentifier"], "available")
    _R()._log_event(store, c["DBClusterIdentifier"], "db-cluster", "DB cluster rebooted.", ["availability"], msg_store)
    return _ok("RebootDBCluster", _cluster_xml(store, c))


def op_FailoverDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    mem = _members_of(store, c["DBClusterIdentifier"])
    writer = next((m for m in mem if m.get("is_cluster_writer")), None)
    readers = [m for m in mem if m is not writer]
    if not readers:
        _err("InvalidDBClusterStateFault", "Cluster has no reader instance to fail over to.")
    target = _p(params, "TargetDBInstanceIdentifier")
    new = next((m for m in readers if m["db_instance_identifier"] == target), None) if target else sorted(readers, key=lambda m: int(m.get("promotion_tier", 1)))[0]
    if new is None:
        _err("InvalidDBInstanceState", f"Instance {target} is not a reader in cluster {c['DBClusterIdentifier']}.")
    if writer:
        writer["is_cluster_writer"] = False
    new["is_cluster_writer"] = True
    store.persist()
    _R()._log_event(store, c["DBClusterIdentifier"], "db-cluster", f"Completed failover to DB instance: {new['db_instance_identifier']}", ["failover"], msg_store)
    return _ok("FailoverDBCluster", _cluster_xml(store, c))


def op_PromoteReadReplicaDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if not c.get("ReplicationSourceIdentifier"):
        _err("InvalidDBClusterStateFault", f"DB cluster {c['DBClusterIdentifier']} is not a read replica.")
    c["ReplicationSourceIdentifier"] = None
    store.persist()
    return _ok("PromoteReadReplicaDBCluster", _cluster_xml(store, c))


def _by_arn(store, params):
    arn = _p(params, "ResourceArn")
    c = next((c for c in _g(store)["clusters"].values() if c["DBClusterArn"] == arn), None)
    if c is None:
        _err("DBClusterNotFoundFault", f"DBCluster {arn} not found.", 404)
    return c


def op_EnableHttpEndpoint(store, params, msg_store=None):
    c = _by_arn(store, params)
    if c["EngineMode"] != "serverless" and not c["Engine"].startswith("aurora"):
        _err("InvalidParameterValue", "Data API is only available on Aurora clusters.")
    c["HttpEndpointEnabled"] = True
    return _ok("EnableHttpEndpoint", _x("ResourceArn", c["DBClusterArn"]) + _x("HttpEndpointEnabled", True))


def op_DisableHttpEndpoint(store, params, msg_store=None):
    c = _by_arn(store, params)
    c["HttpEndpointEnabled"] = False
    return _ok("DisableHttpEndpoint", _x("ResourceArn", c["DBClusterArn"]) + _x("HttpEndpointEnabled", False))


def op_ModifyCurrentDBClusterCapacity(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if c["EngineMode"] != "serverless":
        _err("InvalidDBClusterStateFault", "Only serverless (v1) clusters support ModifyCurrentDBClusterCapacity.")
    cap = _i(params, "Capacity", 1)
    if cap not in (1, 2, 4, 8, 16, 32, 64, 128, 256, 384, 512):
        _err("InvalidParameterValue", f"Invalid capacity {cap}.")
    c["_capacity"] = cap
    return _ok("ModifyCurrentDBClusterCapacity", _x("DBClusterIdentifier", c["DBClusterIdentifier"]) + _x("PendingCapacity", cap) + _x("CurrentCapacity", cap)
               + _x("SecondsBeforeTimeout", _i(params, "SecondsBeforeTimeout", 300)) + _x("TimeoutAction", _p(params, "TimeoutAction", "ForceApplyCapacityChange")))


def op_AddRoleToDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    arn = _p(params, "RoleArn")
    if not re.match(r"^arn:aws[a-z-]*:iam::\d{12}:role/.+$", arn):
        _err("InvalidParameterValue", "RoleArn must be an IAM role ARN.")
    if any(r["RoleArn"] == arn and r.get("FeatureName") == params.get("FeatureName") for r in c["AssociatedRoles"]):
        _err("DBClusterRoleAlreadyExists", "Role already associated with the cluster.")
    c["AssociatedRoles"].append({"RoleArn": arn, "Status": "ACTIVE", "FeatureName": params.get("FeatureName")})
    return _ok("AddRoleToDBCluster")


def op_RemoveRoleFromDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    arn = _p(params, "RoleArn")
    if not any(r["RoleArn"] == arn for r in c["AssociatedRoles"]):
        _err("DBClusterRoleNotFound", "Role is not associated with the cluster.", 404)
    c["AssociatedRoles"] = [r for r in c["AssociatedRoles"] if r["RoleArn"] != arn]
    return _ok("RemoveRoleFromDBCluster")


def op_DescribeDBClusterBacktracks(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if c["Engine"] != "aurora":
        _err("InvalidParameterValue", "Backtrack is only supported by Aurora MySQL 1.x (engine aurora).")
    return _ok("DescribeDBClusterBacktracks", "<DBClusterBacktracks></DBClusterBacktracks>")


def op_BacktrackDBCluster(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    if c["Engine"] != "aurora":
        _err("InvalidParameterValue", "Backtrack is only supported by Aurora MySQL 1.x (engine aurora).")
    _err("InvalidDBClusterStateFault", "Backtrack is not enabled for this cluster.")


# membership hooks called from rds_core --------------------------------------------------
def pre_create_instance(store, params):
    """-> cluster record or None; validates DBClusterIdentifier for CreateDBInstance."""
    cid = _p(params, "DBClusterIdentifier").lower()
    if not cid:
        return None
    c = _need_cluster(store, cid)
    if c["Status"] == "stopped":
        _err("InvalidDBClusterStateFault", f"DB cluster {cid} is stopped.")
    eng = _p(params, "Engine").lower()
    if eng and eng != c["Engine"]:
        _err("InvalidParameterCombination", f"Engine {eng} does not match the cluster engine {c['Engine']}.")
    return c


def post_create_instance(store, params, c):
    db = store.get_instance(_p(params, "DBInstanceIdentifier"))
    if db is None or c is None:
        return
    mem = [m for m in _members_of(store, c["DBClusterIdentifier"]) if m is not db]
    db["db_cluster_identifier"] = c["DBClusterIdentifier"]
    db["is_cluster_writer"] = not any(m.get("is_cluster_writer") for m in mem)
    db["promotion_tier"] = _i(params, "PromotionTier", 1)
    db["engine"], db["engine_version"] = c["Engine"], c["EngineVersion"]
    db["endpoint_port"] = c["Port"]
    db["master_username"] = c["MasterUsername"]
    db["backup_retention_period"] = c["BackupRetentionPeriod"]
    store.persist()


def post_delete_instance(store, db):
    cid = (db or {}).get("db_cluster_identifier")
    if not cid:
        return
    rest = [m for m in _members_of(store, cid) if m["db_instance_identifier"] != db["db_instance_identifier"]]
    if db.get("is_cluster_writer") and rest:
        sorted(rest, key=lambda m: int(m.get("promotion_tier", 1)))[0]["is_cluster_writer"] = True


def check_delete_instance(store, db):
    if db.get("db_cluster_identifier") and db.get("is_cluster_writer"):
        c = _g(store)["clusters"].get(db["db_cluster_identifier"])
        if c and c.get("DeletionProtection") and len(_members_of(store, c["DBClusterIdentifier"])) == 1:
            _err("InvalidParameterCombination", "Cannot delete the last instance of a deletion-protected cluster.")


# ───────────────────────── cluster snapshots ─────────────────────────
def _csnap_xml(s):
    return _x("DBClusterSnapshot", {k: v for k, v in s.items() if not k.startswith("_")})


def _snapshot_cluster(store, c, sid, stype="manual", tags=None):
    if sid in _g(store)["csnaps"]:
        _err("DBClusterSnapshotAlreadyExistsFault", f"Cluster snapshot {sid} already exists.")
    writer = next((m for m in _members_of(store, c["DBClusterIdentifier"]) if m.get("is_cluster_writer")), None)
    data = None
    if writer is not None:
        try:
            data = _R()._capture_snapshot_data(store, writer)
        except Exception:
            data = None
    s = {"DBClusterSnapshotIdentifier": sid, "DBClusterIdentifier": c["DBClusterIdentifier"], "DBClusterSnapshotArn": f"arn:aws:rds:us-east-1:{store.account_id}:cluster-snapshot:{sid}",
         "SnapshotCreateTime": _now(), "ClusterCreateTime": c["ClusterCreateTime"], "Status": "available", "Engine": c["Engine"], "EngineVersion": c["EngineVersion"],
         "Port": c["Port"], "MasterUsername": c["MasterUsername"], "AllocatedStorage": c.get("AllocatedStorage", 1), "SnapshotType": stype, "PercentProgress": 100,
         "StorageEncrypted": c.get("StorageEncrypted", False), "KmsKeyId": c.get("KmsKeyId"), "VpcId": "vpc-default", "LicenseModel": "aurora" if c["Engine"].startswith("aurora") else "general-public-license",
         "StorageType": c.get("StorageType", "aurora"), "DbClusterResourceId": c["DbClusterResourceId"], "IAMDatabaseAuthenticationEnabled": c.get("IAMDatabaseAuthenticationEnabled", False),
         "AvailabilityZones": c["AvailabilityZones"], "_data": data, "_attrs": {}}
    _g(store)["csnaps"][sid] = s
    if tags:
        store.set_tags(s["DBClusterSnapshotArn"], tags)
    store.persist()
    return s


def op_CreateDBClusterSnapshot(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    sid = _p(params, "DBClusterSnapshotIdentifier")
    if not sid:
        _err("InvalidParameterValue", "DBClusterSnapshotIdentifier is required.")
    if c["Status"] != "available":
        _err("InvalidDBClusterStateFault", f"DB cluster {c['DBClusterIdentifier']} is not in available state.")
    s = _snapshot_cluster(store, c, sid, "manual", _tags(params))
    _R()._log_event(store, sid, "db-cluster-snapshot", f"Cluster snapshot {sid} created.", ["creation"], msg_store)
    return _ok("CreateDBClusterSnapshot", _csnap_xml(s))


def _need_csnap(store, sid):
    s = _g(store)["csnaps"].get(sid)
    if s is None:
        _err("DBClusterSnapshotNotFoundFault", f"DBClusterSnapshot {sid} not found.", 404)
    return s


def op_DescribeDBClusterSnapshots(store, params, msg_store=None):
    items = list(_g(store)["csnaps"].values())
    if _p(params, "DBClusterSnapshotIdentifier"):
        items = [_need_csnap(store, _p(params, "DBClusterSnapshotIdentifier"))]
    if _p(params, "DBClusterIdentifier"):
        items = [s for s in items if s["DBClusterIdentifier"] == _p(params, "DBClusterIdentifier").lower()]
    if _p(params, "SnapshotType"):
        items = [s for s in items if s["SnapshotType"] == _p(params, "SnapshotType")]
    return _ok("DescribeDBClusterSnapshots", "<DBClusterSnapshots>" + "".join(_csnap_xml(s) for s in items) + "</DBClusterSnapshots>")


def op_DeleteDBClusterSnapshot(store, params, msg_store=None):
    s = _need_csnap(store, _p(params, "DBClusterSnapshotIdentifier"))
    if s["SnapshotType"] == "automated":
        _err("InvalidDBClusterSnapshotStateFault", "Automated snapshots cannot be deleted directly.")
    del _g(store)["csnaps"][s["DBClusterSnapshotIdentifier"]]
    return _ok("DeleteDBClusterSnapshot", _csnap_xml(s))


def op_CopyDBClusterSnapshot(store, params, msg_store=None):
    src = _p(params, "SourceDBClusterSnapshotIdentifier").rsplit(":", 1)[-1]
    s = _need_csnap(store, src)
    tid = _p(params, "TargetDBClusterSnapshotIdentifier")
    if tid in _g(store)["csnaps"]:
        _err("DBClusterSnapshotAlreadyExistsFault", f"Cluster snapshot {tid} already exists.")
    n = dict(s)
    n.update({"DBClusterSnapshotIdentifier": tid, "DBClusterSnapshotArn": f"arn:aws:rds:us-east-1:{store.account_id}:cluster-snapshot:{tid}", "SnapshotType": "manual",
              "SnapshotCreateTime": _now(), "_attrs": {}})
    if _p(params, "KmsKeyId"):
        n["KmsKeyId"], n["StorageEncrypted"] = params["KmsKeyId"], True
    _g(store)["csnaps"][tid] = n
    t = _tags(params)
    if t or _b(params, "CopyTags"):
        store.set_tags(n["DBClusterSnapshotArn"], {**(store.get_tags(s["DBClusterSnapshotArn"]) if _b(params, "CopyTags") else {}), **t})
    return _ok("CopyDBClusterSnapshot", _csnap_xml(n))


def _attr_list(attrs):
    return [{"AttributeName": k, "AttributeValues": v} for k, v in attrs.items()]


def op_ModifyDBClusterSnapshotAttribute(store, params, msg_store=None):
    s = _need_csnap(store, _p(params, "DBClusterSnapshotIdentifier"))
    name = _p(params, "AttributeName")
    if name != "restore":
        _err("InvalidParameterValue", "AttributeName must be 'restore'.")
    vals = s["_attrs"].setdefault(name, [])
    for v in _list(params, "ValuesToAdd"):
        if v != "all" and not re.fullmatch(r"\d{12}", v):
            _err("InvalidParameterValue", f"Invalid account id {v}.")
        if v not in vals:
            vals.append(v)
    rem = set(_list(params, "ValuesToRemove"))
    s["_attrs"][name] = [v for v in vals if v not in rem]
    return _ok("ModifyDBClusterSnapshotAttribute", _x("DBClusterSnapshotAttributesResult", {"DBClusterSnapshotIdentifier": s["DBClusterSnapshotIdentifier"], "DBClusterSnapshotAttributes": _attr_list(s["_attrs"])}))


def op_DescribeDBClusterSnapshotAttributes(store, params, msg_store=None):
    s = _need_csnap(store, _p(params, "DBClusterSnapshotIdentifier"))
    return _ok("DescribeDBClusterSnapshotAttributes", _x("DBClusterSnapshotAttributesResult", {"DBClusterSnapshotIdentifier": s["DBClusterSnapshotIdentifier"], "DBClusterSnapshotAttributes": _attr_list(s["_attrs"])}))


def op_RestoreDBClusterFromSnapshot(store, params, msg_store=None):
    s = _need_csnap(store, _p(params, "SnapshotIdentifier").rsplit(":", 1)[-1])
    p = dict(params)
    p.update({"_restore": "1", "Engine": params.get("Engine") or s["Engine"], "EngineVersion": params.get("EngineVersion") or s["EngineVersion"],
              "Port": params.get("Port") or s["Port"], "MasterUsername": s["MasterUsername"]})
    c = create_cluster(store, p, msg_store)
    c["RestoredFrom"] = s["DBClusterSnapshotIdentifier"]
    c["MasterUsername"] = s["MasterUsername"]
    return _ok("RestoreDBClusterFromSnapshot", _cluster_xml(store, c))


def op_RestoreDBClusterToPointInTime(store, params, msg_store=None):
    src = _need_cluster(store, _p(params, "SourceDBClusterIdentifier").lower())
    if not _b(params, "UseLatestRestorableTime") and not params.get("RestoreToTime"):
        _err("InvalidParameterCombination", "Specify RestoreToTime or UseLatestRestorableTime=true.")
    if src["BackupRetentionPeriod"] < 1:
        _err("InvalidDBClusterStateFault", "Point-in-time restore needs BackupRetentionPeriod >= 1 on the source cluster.")
    p = dict(params)
    p.update({"_restore": "1", "Engine": src["Engine"], "EngineVersion": src["EngineVersion"], "Port": params.get("Port") or src["Port"], "MasterUsername": src["MasterUsername"]})
    c = create_cluster(store, p, msg_store)
    c["RestoredFrom"] = src["DBClusterIdentifier"]
    return _ok("RestoreDBClusterToPointInTime", _cluster_xml(store, c))


def op_RestoreDBClusterFromS3(store, params, msg_store=None):
    if not _p(params, "S3BucketName") or not _p(params, "SourceEngine"):
        _err("InvalidParameterValue", "S3BucketName and SourceEngine are required.")
    p = dict(params)
    p["_restore"] = "1"
    c = create_cluster(store, p, msg_store)
    return _ok("RestoreDBClusterFromS3", _cluster_xml(store, c))


# ───────────────────────── cluster parameter groups ─────────────────────────
def _cpg_xml(g):
    return _x("DBClusterParameterGroup", {k: v for k, v in g.items() if k != "_params"})


def _need_cpg(store, name):
    g = _g(store)["cpgs"].get(name)
    if g is None:
        _err("DBParameterGroupNotFound", f"DB cluster parameter group {name} not found.", 404)
    return g


def op_CreateDBClusterParameterGroup(store, params, msg_store=None):
    name = _p(params, "DBClusterParameterGroupName")
    if not name:
        _err("InvalidParameterValue", "DBClusterParameterGroupName is required.")
    if name in _g(store)["cpgs"]:
        _err("DBParameterGroupAlreadyExists", f"DB cluster parameter group {name} already exists.")
    fam = _p(params, "DBParameterGroupFamily", "aurora-mysql8.0")
    g = {"DBClusterParameterGroupName": name, "DBParameterGroupFamily": fam, "Description": _p(params, "Description"),
         "DBClusterParameterGroupArn": f"arn:aws:rds:us-east-1:{store.account_id}:cluster-pg:{name}", "_params": _R()._default_parameters(fam)}
    _g(store)["cpgs"][name] = g
    t = _tags(params)
    if t:
        store.set_tags(g["DBClusterParameterGroupArn"], t)
    return _ok("CreateDBClusterParameterGroup", _cpg_xml(g))


def op_DescribeDBClusterParameterGroups(store, params, msg_store=None):
    n = _p(params, "DBClusterParameterGroupName")
    items = [_need_cpg(store, n)] if n else list(_g(store)["cpgs"].values())
    return _ok("DescribeDBClusterParameterGroups", "<DBClusterParameterGroups>" + "".join(_cpg_xml(g) for g in items) + "</DBClusterParameterGroups>")


def op_DeleteDBClusterParameterGroup(store, params, msg_store=None):
    g = _need_cpg(store, _p(params, "DBClusterParameterGroupName"))
    if any(c["DBClusterParameterGroup"] == g["DBClusterParameterGroupName"] for c in _g(store)["clusters"].values()):
        _err("InvalidDBParameterGroupState", "One or more clusters are associated with this parameter group.")
    del _g(store)["cpgs"][g["DBClusterParameterGroupName"]]
    return _ok("DeleteDBClusterParameterGroup")


def _params_xml(g_params, params):
    R = _R()
    src = _p(params, "Source")
    items = sorted(g_params.items())
    if src:
        items = [(n, p) for n, p in items if p.get("source", "engine-default") == src]
    return "<Parameters>" + "".join(R._parameter_xml(n, p) for n, p in items) + "</Parameters>"


def op_DescribeDBClusterParameters(store, params, msg_store=None):
    g = _need_cpg(store, _p(params, "DBClusterParameterGroupName"))
    return _ok("DescribeDBClusterParameters", _params_xml(g["_params"], params))


def op_ModifyDBClusterParameterGroup(store, params, msg_store=None):
    g = _need_cpg(store, _p(params, "DBClusterParameterGroupName"))
    for it in _list(params, "Parameters"):
        n = it.get("ParameterName")
        if n:
            p = g["_params"].setdefault(n, {"data_type": "string", "allowed_values": "", "is_modifiable": True, "apply_type": "dynamic", "description": ""})
            p["parameter_value"], p["source"] = it.get("ParameterValue", ""), "user"
    return _ok("ModifyDBClusterParameterGroup", _x("DBClusterParameterGroupName", g["DBClusterParameterGroupName"]))


def op_ResetDBClusterParameterGroup(store, params, msg_store=None):
    g = _need_cpg(store, _p(params, "DBClusterParameterGroupName"))
    _reset(g["_params"], params, g["DBParameterGroupFamily"])
    return _ok("ResetDBClusterParameterGroup", _x("DBClusterParameterGroupName", g["DBClusterParameterGroupName"]))


def _reset(pmap, params, family):
    dflt = _R()._default_parameters(family)
    if _b(params, "ResetAllParameters"):
        pmap.clear()
        pmap.update(dflt)
        return
    for it in _list(params, "Parameters"):
        n = it.get("ParameterName")
        if n in dflt:
            pmap[n] = dflt[n]
        else:
            pmap.pop(n, None)


def op_CopyDBClusterParameterGroup(store, params, msg_store=None):
    src = _need_cpg(store, _p(params, "SourceDBClusterParameterGroupIdentifier").rsplit(":", 1)[-1])
    tid = _p(params, "TargetDBClusterParameterGroupIdentifier")
    if tid in _g(store)["cpgs"]:
        _err("DBParameterGroupAlreadyExists", f"DB cluster parameter group {tid} already exists.")
    g = dict(src)
    g.update({"DBClusterParameterGroupName": tid, "Description": _p(params, "TargetDBClusterParameterGroupDescription"),
              "DBClusterParameterGroupArn": f"arn:aws:rds:us-east-1:{store.account_id}:cluster-pg:{tid}", "_params": {k: dict(v) for k, v in src["_params"].items()}})
    _g(store)["cpgs"][tid] = g
    return _ok("CopyDBClusterParameterGroup", _cpg_xml(g))


def op_DescribeEngineDefaultClusterParameters(store, params, msg_store=None):
    fam = _p(params, "DBParameterGroupFamily")
    if not fam:
        _err("InvalidParameterValue", "DBParameterGroupFamily is required.")
    return _ok("DescribeEngineDefaultClusterParameters", _x("EngineDefaults", {"DBParameterGroupFamily": fam}).replace("</EngineDefaults>", _params_xml(_R()._default_parameters(fam), {}) + "</EngineDefaults>"))


def op_DescribeEngineDefaultParameters(store, params, msg_store=None):
    fam = _p(params, "DBParameterGroupFamily")
    if not fam:
        _err("InvalidParameterValue", "DBParameterGroupFamily is required.")
    return _ok("DescribeEngineDefaultParameters", _x("EngineDefaults", {"DBParameterGroupFamily": fam}).replace("</EngineDefaults>", _params_xml(_R()._default_parameters(fam), {}) + "</EngineDefaults>"))


def op_ResetDBParameterGroup(store, params, msg_store=None):
    name = _p(params, "DBParameterGroupName")
    pg = store.get_parameter_group(name)
    if not pg:
        _err("DBParameterGroupNotFound", f"DB parameter group {name} not found.", 404)
    _reset(pg["parameters"], params, pg.get("db_parameter_group_family", "postgres16"))
    store.persist()
    return _ok("ResetDBParameterGroup", _x("DBParameterGroupName", name))


def op_CopyDBParameterGroup(store, params, msg_store=None):
    R = _R()
    src = store.get_parameter_group(_p(params, "SourceDBParameterGroupIdentifier").rsplit(":", 1)[-1])
    if not src:
        _err("DBParameterGroupNotFound", "Source DB parameter group not found.", 404)
    tid = _p(params, "TargetDBParameterGroupIdentifier")
    if store.get_parameter_group(tid):
        _err("DBParameterGroupAlreadyExists", f"DB parameter group {tid} already exists.")
    rec = dict(src)
    rec.update({"db_parameter_group_name": tid, "description": _p(params, "TargetDBParameterGroupDescription"), "db_parameter_group_arn": R._parameter_group_arn(store, tid),
                "parameters": {k: dict(v) for k, v in src["parameters"].items()}})
    store.put_parameter_group(tid, rec)
    store.persist()
    return _ok("CopyDBParameterGroup", R._parameter_group_xml(rec))


# ───────────────────────── cluster endpoints ─────────────────────────
def _cep_xml(e):
    return _x("DBClusterEndpoint", {k: v for k, v in e.items() if not k.startswith("_")})


def op_CreateDBClusterEndpoint(store, params, msg_store=None):
    c = _need_cluster(store, _p(params, "DBClusterIdentifier").lower())
    eid = _p(params, "DBClusterEndpointIdentifier").lower()
    if not eid:
        _err("InvalidParameterValue", "DBClusterEndpointIdentifier is required.")
    if eid in _g(store)["ceps"]:
        _err("DBClusterEndpointAlreadyExistsFault", f"Endpoint {eid} already exists.")
    et = _p(params, "EndpointType").upper()
    if et not in ("READER", "ANY", "WRITER"):
        _err("InvalidParameterValue", "EndpointType must be READER, WRITER or ANY.")
    e = {"DBClusterEndpointIdentifier": eid, "DBClusterIdentifier": c["DBClusterIdentifier"], "DBClusterEndpointResourceIdentifier": "cluster-endpoint-" + uuid.uuid4().hex[:20].upper(),
         "Endpoint": f"{eid}.cluster-custom-nano.us-east-1.rds.amazonaws.com", "Status": "available", "EndpointType": "CUSTOM", "CustomEndpointType": et,
         "StaticMembers": _list(params, "StaticMembers"), "ExcludedMembers": _list(params, "ExcludedMembers"),
         "DBClusterEndpointArn": f"arn:aws:rds:us-east-1:{store.account_id}:cluster-endpoint:{eid}", "_cluster": c["DBClusterIdentifier"]}
    _g(store)["ceps"][eid] = e
    return _ok("CreateDBClusterEndpoint", _cep_xml(e).replace("<DBClusterEndpoint>", "", 1).replace("</DBClusterEndpoint>", "", 1))


def _need_cep(store, eid):
    e = _g(store)["ceps"].get(eid.lower())
    if e is None:
        _err("DBClusterEndpointNotFoundFault", f"DB cluster endpoint {eid} not found.", 404)
    return e


def op_DescribeDBClusterEndpoints(store, params, msg_store=None):
    items = list(_g(store)["ceps"].values())
    if _p(params, "DBClusterEndpointIdentifier"):
        items = [_need_cep(store, _p(params, "DBClusterEndpointIdentifier"))]
    if _p(params, "DBClusterIdentifier"):
        items = [e for e in items if e["_cluster"] == _p(params, "DBClusterIdentifier").lower()]
    return _ok("DescribeDBClusterEndpoints", "<DBClusterEndpoints>" + "".join(_cep_xml(e) for e in items) + "</DBClusterEndpoints>")


def op_ModifyDBClusterEndpoint(store, params, msg_store=None):
    e = _need_cep(store, _p(params, "DBClusterEndpointIdentifier"))
    if _p(params, "EndpointType"):
        e["CustomEndpointType"] = _p(params, "EndpointType").upper()
    if _list(params, "StaticMembers"):
        e["StaticMembers"] = _list(params, "StaticMembers")
    if _list(params, "ExcludedMembers"):
        e["ExcludedMembers"] = _list(params, "ExcludedMembers")
    return _ok("ModifyDBClusterEndpoint", _cep_xml(e).replace("<DBClusterEndpoint>", "", 1).replace("</DBClusterEndpoint>", "", 1))


def op_DeleteDBClusterEndpoint(store, params, msg_store=None):
    e = _need_cep(store, _p(params, "DBClusterEndpointIdentifier"))
    del _g(store)["ceps"][e["DBClusterEndpointIdentifier"]]
    return _ok("DeleteDBClusterEndpoint", _cep_xml(e).replace("<DBClusterEndpoint>", "", 1).replace("</DBClusterEndpoint>", "", 1))


# ───────────────────────── global clusters ─────────────────────────
def _gc_xml(gc):
    return _x("GlobalCluster", {k: v for k, v in gc.items() if not k.startswith("_")})


def _need_gc(store, gid):
    gc = _g(store)["globals"].get(gid)
    if gc is None:
        _err("GlobalClusterNotFoundFault", f"Global cluster {gid} not found.", 404)
    return gc


def op_CreateGlobalCluster(store, params, msg_store=None):
    gid = _p(params, "GlobalClusterIdentifier")
    if not gid:
        _err("InvalidParameterValue", "GlobalClusterIdentifier is required.")
    if gid in _g(store)["globals"]:
        _err("GlobalClusterAlreadyExistsFault", f"Global cluster {gid} already exists.")
    members, eng, ver = [], _p(params, "Engine"), _p(params, "EngineVersion")
    src = _p(params, "SourceDBClusterIdentifier")
    if src:
        c = _need_cluster(store, src.rsplit(":", 1)[-1].lower())
        members = [{"DBClusterArn": c["DBClusterArn"], "IsWriter": True, "Readers": []}]
        eng, ver = c["Engine"], c["EngineVersion"]
        c["GlobalClusterIdentifier"] = gid
    if eng not in ("aurora-mysql", "aurora-postgresql", "aurora"):
        _err("InvalidParameterValue", "Global clusters require an Aurora engine (aurora-mysql or aurora-postgresql).")
    gc = {"GlobalClusterIdentifier": gid, "GlobalClusterResourceId": "cluster-" + uuid.uuid4().hex[:26].upper(), "GlobalClusterArn": f"arn:aws:rds::{store.account_id}:global-cluster:{gid}",
          "Status": "available", "Engine": eng, "EngineVersion": ver or _ENGINE_VER[eng], "DatabaseName": params.get("DatabaseName"), "StorageEncrypted": _b(params, "StorageEncrypted"),
          "DeletionProtection": _b(params, "DeletionProtection"), "GlobalClusterMembers": members}
    _g(store)["globals"][gid] = gc
    return _ok("CreateGlobalCluster", _gc_xml(gc))


def op_DescribeGlobalClusters(store, params, msg_store=None):
    gid = _p(params, "GlobalClusterIdentifier")
    items = [_need_gc(store, gid)] if gid else list(_g(store)["globals"].values())
    return _ok("DescribeGlobalClusters", "<GlobalClusters>" + "".join(_gc_xml(g) for g in items) + "</GlobalClusters>")


def op_ModifyGlobalCluster(store, params, msg_store=None):
    gc = _need_gc(store, _p(params, "GlobalClusterIdentifier"))
    if params.get("DeletionProtection") is not None:
        gc["DeletionProtection"] = _b(params, "DeletionProtection")
    if _p(params, "EngineVersion"):
        gc["EngineVersion"] = params["EngineVersion"]
    new = _p(params, "NewGlobalClusterIdentifier")
    if new and new != gc["GlobalClusterIdentifier"]:
        old = gc["GlobalClusterIdentifier"]
        del _g(store)["globals"][old]
        gc["GlobalClusterIdentifier"] = new
        _g(store)["globals"][new] = gc
        for c in _g(store)["clusters"].values():
            if c.get("GlobalClusterIdentifier") == old:
                c["GlobalClusterIdentifier"] = new
    return _ok("ModifyGlobalCluster", _gc_xml(gc))


def op_DeleteGlobalCluster(store, params, msg_store=None):
    gc = _need_gc(store, _p(params, "GlobalClusterIdentifier"))
    if gc["GlobalClusterMembers"]:
        _err("InvalidGlobalClusterStateFault", "Global cluster still has member clusters; remove them first.")
    if gc.get("DeletionProtection"):
        _err("InvalidParameterCombination", "Cannot delete a deletion-protected global cluster.")
    del _g(store)["globals"][gc["GlobalClusterIdentifier"]]
    return _ok("DeleteGlobalCluster", _gc_xml(gc))


def op_RemoveFromGlobalCluster(store, params, msg_store=None):
    gc = _need_gc(store, _p(params, "GlobalClusterIdentifier"))
    arn = _p(params, "DbClusterIdentifier")
    m = next((m for m in gc["GlobalClusterMembers"] if m["DBClusterArn"] == arn), None)
    if m is None:
        _err("DBClusterNotFoundFault", f"Cluster {arn} is not a member of {gc['GlobalClusterIdentifier']}.", 404)
    gc["GlobalClusterMembers"].remove(m)
    c = next((c for c in _g(store)["clusters"].values() if c["DBClusterArn"] == arn), None)
    if c:
        c["GlobalClusterIdentifier"] = None
    return _ok("RemoveFromGlobalCluster", _gc_xml(gc))


def _gc_move(store, params, action):
    gc = _need_gc(store, _p(params, "GlobalClusterIdentifier"))
    target = _p(params, "TargetDbClusterIdentifier")
    new = next((m for m in gc["GlobalClusterMembers"] if m["DBClusterArn"] == target), None)
    if new is None:
        _err("DBClusterNotFoundFault", f"Cluster {target} is not a member of {gc['GlobalClusterIdentifier']}.", 404)
    for m in gc["GlobalClusterMembers"]:
        m["IsWriter"] = m is new
    return _ok(action, _gc_xml(gc))


def op_FailoverGlobalCluster(store, params, msg_store=None):
    return _gc_move(store, params, "FailoverGlobalCluster")


def op_SwitchoverGlobalCluster(store, params, msg_store=None):
    return _gc_move(store, params, "SwitchoverGlobalCluster")


# ───────────────────────── DB security groups (EC2-Classic) ─────────────────────────
def _sg_xml(s):
    return _x("DBSecurityGroup", {k: v for k, v in s.items() if not k.startswith("_")})


def _need_sg(store, n):
    s = _g(store)["secgroups"].get(n)
    if s is None:
        _err("DBSecurityGroupNotFound", f"DBSecurityGroup {n} not found.", 404)
    return s


def op_CreateDBSecurityGroup(store, params, msg_store=None):
    n = _p(params, "DBSecurityGroupName")
    if not n:
        _err("InvalidParameterValue", "DBSecurityGroupName is required.")
    if n in _g(store)["secgroups"]:
        _err("DBSecurityGroupAlreadyExists", f"DB security group {n} already exists.")
    s = {"OwnerId": store.account_id, "DBSecurityGroupName": n, "DBSecurityGroupDescription": _p(params, "DBSecurityGroupDescription"), "EC2SecurityGroups": [], "IPRanges": [],
         "DBSecurityGroupArn": f"arn:aws:rds:us-east-1:{store.account_id}:secgrp:{n}"}
    _g(store)["secgroups"][n] = s
    return _ok("CreateDBSecurityGroup", _sg_xml(s))


def op_DescribeDBSecurityGroups(store, params, msg_store=None):
    n = _p(params, "DBSecurityGroupName")
    items = [_need_sg(store, n)] if n else list(_g(store)["secgroups"].values())
    return _ok("DescribeDBSecurityGroups", "<DBSecurityGroups>" + "".join(_sg_xml(s) for s in items) + "</DBSecurityGroups>")


def op_DeleteDBSecurityGroup(store, params, msg_store=None):
    s = _need_sg(store, _p(params, "DBSecurityGroupName"))
    del _g(store)["secgroups"][s["DBSecurityGroupName"]]
    return _ok("DeleteDBSecurityGroup")


def op_AuthorizeDBSecurityGroupIngress(store, params, msg_store=None):
    s = _need_sg(store, _p(params, "DBSecurityGroupName"))
    cidr, sgid = _p(params, "CIDRIP"), _p(params, "EC2SecurityGroupId") or _p(params, "EC2SecurityGroupName")
    if not cidr and not sgid:
        _err("InvalidParameterValue", "Specify CIDRIP or an EC2 security group.")
    if cidr:
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}", cidr):
            _err("InvalidParameterValue", f"Invalid CIDR {cidr}.")
        if any(r["CIDRIP"] == cidr for r in s["IPRanges"]):
            _err("AuthorizationAlreadyExists", f"{cidr} is already authorized.")
        s["IPRanges"].append({"Status": "authorized", "CIDRIP": cidr})
    else:
        s["EC2SecurityGroups"].append({"Status": "authorized", "EC2SecurityGroupName": _p(params, "EC2SecurityGroupName"), "EC2SecurityGroupId": _p(params, "EC2SecurityGroupId"),
                                       "EC2SecurityGroupOwnerId": _p(params, "EC2SecurityGroupOwnerId", store.account_id)})
    return _ok("AuthorizeDBSecurityGroupIngress", _sg_xml(s))


def op_RevokeDBSecurityGroupIngress(store, params, msg_store=None):
    s = _need_sg(store, _p(params, "DBSecurityGroupName"))
    cidr = _p(params, "CIDRIP")
    if cidr:
        if not any(r["CIDRIP"] == cidr for r in s["IPRanges"]):
            _err("AuthorizationNotFound", f"{cidr} is not authorized.", 404)
        s["IPRanges"] = [r for r in s["IPRanges"] if r["CIDRIP"] != cidr]
    else:
        gid = _p(params, "EC2SecurityGroupId")
        s["EC2SecurityGroups"] = [r for r in s["EC2SecurityGroups"] if r["EC2SecurityGroupId"] != gid]
    return _ok("RevokeDBSecurityGroupIngress", _sg_xml(s))


# ───────────────────────── DB snapshots: attributes / copy / modify / PITR ─────────────────────────
def _need_snap(store, sid):
    s = store.get_snapshot(sid)
    if not s:
        _err("DBSnapshotNotFound", f"DBSnapshot {sid} not found.", 404)
    return s


def _snap_attrs(store, sid):
    return _g(store)["snapattrs"].setdefault(sid, {})


def op_ModifyDBSnapshotAttribute(store, params, msg_store=None):
    sid = _p(params, "DBSnapshotIdentifier")
    _need_snap(store, sid)
    if _p(params, "AttributeName") != "restore":
        _err("InvalidParameterValue", "AttributeName must be 'restore'.")
    a = _snap_attrs(store, sid).setdefault("restore", [])
    for v in _list(params, "ValuesToAdd"):
        if v != "all" and not re.fullmatch(r"\d{12}", v):
            _err("InvalidParameterValue", f"Invalid account id {v}.")
        if v not in a:
            a.append(v)
    rem = set(_list(params, "ValuesToRemove"))
    _g(store)["snapattrs"][sid]["restore"] = [v for v in a if v not in rem]
    return _ok("ModifyDBSnapshotAttribute", _x("DBSnapshotAttributesResult", {"DBSnapshotIdentifier": sid, "DBSnapshotAttributes": _attr_list(_snap_attrs(store, sid))}))


def op_DescribeDBSnapshotAttributes(store, params, msg_store=None):
    sid = _p(params, "DBSnapshotIdentifier")
    _need_snap(store, sid)
    return _ok("DescribeDBSnapshotAttributes", _x("DBSnapshotAttributesResult", {"DBSnapshotIdentifier": sid, "DBSnapshotAttributes": _attr_list(_snap_attrs(store, sid))}))


def op_CopyDBSnapshot(store, params, msg_store=None):
    R = _R()
    src = _need_snap(store, _p(params, "SourceDBSnapshotIdentifier").rsplit(":", 1)[-1])
    tid = _p(params, "TargetDBSnapshotIdentifier")
    if not tid:
        _err("InvalidParameterValue", "TargetDBSnapshotIdentifier is required.")
    if store.get_snapshot(tid):
        _err("DBSnapshotAlreadyExists", f"Snapshot {tid} already exists.")
    n = dict(src)
    n.update({"db_snapshot_identifier": tid, "db_snapshot_arn": R._snapshot_arn(store, tid), "snapshot_type": "manual", "created": _now()})
    store.put_snapshot(tid, n)
    t = _tags(params)
    if _b(params, "CopyTags"):
        t = {**store.get_tags(src.get("db_snapshot_arn") or R._snapshot_arn(store, src["db_snapshot_identifier"])), **t}
    if t:
        store.set_tags(n["db_snapshot_arn"], t)
    store.persist()
    return _ok("CopyDBSnapshot", R._db_snapshot_xml(n))


def op_ModifyDBSnapshot(store, params, msg_store=None):
    R = _R()
    s = _need_snap(store, _p(params, "DBSnapshotIdentifier"))
    if _p(params, "EngineVersion"):
        s["engine_version"] = params["EngineVersion"]
    store.persist()
    return _ok("ModifyDBSnapshot", R._db_snapshot_xml(s))


def op_RestoreDBInstanceToPointInTime(store, params, msg_store=None):
    R = _R()
    src_id = _p(params, "SourceDBInstanceIdentifier")
    src = store.get_instance(src_id)
    if src is None:
        _err("DBInstanceNotFound", f"DBInstance {src_id} not found.", 404)
    tgt = _p(params, "TargetDBInstanceIdentifier")
    if not tgt:
        _err("InvalidParameterValue", "TargetDBInstanceIdentifier is required.")
    if store.instance_exists(tgt):
        _err("DBInstanceAlreadyExists", f"DBInstance {tgt} already exists.")
    if not _b(params, "UseLatestRestorableTime") and not params.get("RestoreTime"):
        _err("InvalidParameterCombination", "Specify RestoreTime or UseLatestRestorableTime=true.")
    if int(src.get("backup_retention_period", 0)) < 1:
        _err("PointInTimeRestoreNotEnabled", "Point-in-time restore needs automated backups (BackupRetentionPeriod >= 1) on the source instance.")
    rec = {k: v for k, v in src.items() if k not in ("read_replica_db_instance_identifiers", "read_replica_source_db_instance_identifier", "db_cluster_identifier", "is_cluster_writer")}
    rec.update({"db_instance_identifier": tgt, "db_instance_class": _p(params, "DBInstanceClass", src.get("db_instance_class", "db.t3.micro")), "endpoint_address": f"{tgt}.nano-rds.local",
                "db_instance_arn": R._instance_arn(store, tgt), "read_replica_db_instance_identifiers": [], "read_replica_source_db_instance_identifier": None,
                "created": _now(), "updated": _now(), "restored_from": src_id, "db_instance_status": "available", "deletion_protection": False})
    if _p(params, "Port"):
        rec["endpoint_port"] = int(params["Port"])
    store.put_instance(tgt, rec)
    store.mirror_create_instance(tgt, rec)
    store.persist()
    R._log_event(store, tgt, "db-instance", f"Restored DB instance {tgt} from {src_id} (point in time).", ["creation"], msg_store)
    return _ok("RestoreDBInstanceToPointInTime", R._db_instance_xml(rec))


def op_SwitchoverReadReplica(store, params, msg_store=None):
    R = _R()
    rep = store.get_instance(_p(params, "DBInstanceIdentifier"))
    if rep is None:
        _err("DBInstanceNotFound", f"DBInstance {_p(params, 'DBInstanceIdentifier')} not found.", 404)
    sid = rep.get("read_replica_source_db_instance_identifier")
    if not sid:
        _err("InvalidDBInstanceState", "DB instance is not a read replica.")
    src = store.get_instance(sid)
    others = [r for r in src.get("read_replica_db_instance_identifiers", []) if r != rep["db_instance_identifier"]] + [sid]
    src["read_replica_db_instance_identifiers"] = []
    src["read_replica_source_db_instance_identifier"] = rep["db_instance_identifier"]
    rep["read_replica_source_db_instance_identifier"] = None
    rep["read_replica_db_instance_identifiers"] = others
    for o in others[:-1]:
        oi = store.get_instance(o)
        if oi:
            oi["read_replica_source_db_instance_identifier"] = rep["db_instance_identifier"]
    store.persist()
    return _ok("SwitchoverReadReplica", R._db_instance_xml(rep))


def op_DeleteDBInstanceAutomatedBackup(store, params, msg_store=None):
    R = _R()
    rid = _p(params, "DbiResourceId")
    db = next((store.get_instance(i) for i in store.instance_ids() if rid and store.get_instance(i).get("dbi_resource_id", store.get_instance(i)["db_instance_identifier"]) == rid), None)
    if db is None:
        _err("DBInstanceAutomatedBackupNotFound", f"No automated backup for {rid}.", 404)
    if db.get("db_instance_status") != "deleting" and store.instance_exists(db["db_instance_identifier"]):
        _err("InvalidDBInstanceAutomatedBackupState", "Automated backups of a live instance cannot be deleted; delete the instance or set retention to 0.")
    return _ok("DeleteDBInstanceAutomatedBackup", R._automated_backup_xml(db))


def op_StartDBInstanceAutomatedBackupsReplication(store, params, msg_store=None):
    R = _R()
    arn = _p(params, "SourceDBInstanceArn")
    db = next((store.get_instance(i) for i in store.instance_ids() if store.get_instance(i).get("db_instance_arn") == arn), None)
    if db is None:
        _err("DBInstanceNotFound", f"DBInstance {arn} not found.", 404)
    if int(db.get("backup_retention_period", 0)) < 1:
        _err("InvalidDBInstanceState", "Automated backups are disabled on the source instance.")
    _g(store)["automated_repl"][arn] = {"retention": _i(params, "BackupRetentionPeriod", db["backup_retention_period"]), "region": "us-east-2"}
    return _ok("StartDBInstanceAutomatedBackupsReplication", R._automated_backup_xml(db))


def op_StopDBInstanceAutomatedBackupsReplication(store, params, msg_store=None):
    R = _R()
    arn = _p(params, "SourceDBInstanceArn")
    if arn not in _g(store)["automated_repl"]:
        _err("DBInstanceAutomatedBackupNotFound", f"No replicated automated backups for {arn}.", 404)
    del _g(store)["automated_repl"][arn]
    db = next(store.get_instance(i) for i in store.instance_ids() if store.get_instance(i).get("db_instance_arn") == arn)
    return _ok("StopDBInstanceAutomatedBackupsReplication", R._automated_backup_xml(db))


# ───────────────────────── subnet / option groups / event subscriptions ─────────────────────────
def op_ModifyDBSubnetGroup(store, params, msg_store=None):
    R = _R()
    n = _p(params, "DBSubnetGroupName")
    sg = store.get_subnet_group(n)
    if not sg:
        _err("DBSubnetGroupNotFoundFault", f"DB subnet group {n} not found.", 404)
    ids = _list(params, "SubnetIds")
    if not ids:
        _err("InvalidParameterValue", "SubnetIds is required.")
    azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
    sg["subnets"] = [{"subnet_identifier": s, "availability_zone": azs[i % 3]} for i, s in enumerate(ids)]
    if params.get("DBSubnetGroupDescription") is not None:
        sg["db_subnet_group_description"] = params["DBSubnetGroupDescription"]
    store.persist()
    return _ok("ModifyDBSubnetGroup", R._subnet_group_xml(sg))


def op_ModifyOptionGroup(store, params, msg_store=None):
    R = _R()
    n = _p(params, "OptionGroupName")
    og = store.get_option_group(n)
    if not og:
        _err("OptionGroupNotFoundFault", f"Option group {n} not found.", 404)
    opts = og.setdefault("options", {})
    for it in _list(params, "OptionsToInclude"):
        nm = it.get("OptionName")
        if nm:
            opts[nm] = {"OptionName": nm, "Port": it.get("Port"), "OptionSettings": []}
    for nm in _list(params, "OptionsToRemove"):
        opts.pop(nm, None)
    store.persist()
    xml = R._option_group_xml(og).replace("<Options></Options>", _x("Options", [{"OptionName": o["OptionName"], "Port": o.get("Port"), "Persistent": False, "Permanent": False} for o in opts.values()]).replace("<member>", "<Option>").replace("</member>", "</Option>"))
    return _ok("ModifyOptionGroup", xml)


def op_CopyOptionGroup(store, params, msg_store=None):
    R = _R()
    src = store.get_option_group(_p(params, "SourceOptionGroupIdentifier").rsplit(":", 1)[-1])
    if not src:
        _err("OptionGroupNotFoundFault", "Source option group not found.", 404)
    tid = _p(params, "TargetOptionGroupIdentifier")
    if store.get_option_group(tid):
        _err("OptionGroupAlreadyExistsFault", f"Option group {tid} already exists.")
    rec = dict(src)
    rec.update({"option_group_name": tid, "option_group_description": _p(params, "TargetOptionGroupDescription"), "option_group_arn": R._option_group_arn(store, tid),
                "options": {k: dict(v) for k, v in (src.get("options") or {}).items()}})
    store.put_option_group(tid, rec)
    store.persist()
    return _ok("CopyOptionGroup", R._option_group_xml(rec))


def _sub(store, params):
    n = _p(params, "SubscriptionName")
    es = store.get_event_subscription(n)
    if not es:
        _err("SubscriptionNotFoundFault", f"Event subscription {n} not found.", 404)
    return es


def op_ModifyEventSubscription(store, params, msg_store=None):
    es = _sub(store, params)
    if _p(params, "SnsTopicArn"):
        es["sns_topic_arn"] = params["SnsTopicArn"]
    if _p(params, "SourceType"):
        es["source_type"] = params["SourceType"]
    if _list(params, "EventCategories"):
        es["event_categories"] = _list(params, "EventCategories")
    if params.get("Enabled") is not None:
        es["enabled"] = _b(params, "Enabled")
    store.persist()
    return _ok("ModifyEventSubscription", _R()._event_subscription_xml(es))


def op_AddSourceIdentifierToSubscription(store, params, msg_store=None):
    es = _sub(store, params)
    sid = _p(params, "SourceIdentifier")
    if not sid:
        _err("InvalidParameterValue", "SourceIdentifier is required.")
    ids = es.setdefault("source_ids", [])
    if sid not in ids:
        ids.append(sid)
    return _ok("AddSourceIdentifierToSubscription", _R()._event_subscription_xml(es))


def op_RemoveSourceIdentifierFromSubscription(store, params, msg_store=None):
    es = _sub(store, params)
    sid = _p(params, "SourceIdentifier")
    if sid not in es.get("source_ids", []):
        _err("SourceNotFound", f"{sid} is not a source of this subscription.", 404)
    es["source_ids"].remove(sid)
    return _ok("RemoveSourceIdentifierFromSubscription", _R()._event_subscription_xml(es))


_EVENT_CATS = {"db-instance": ["availability", "backup", "configuration change", "creation", "deletion", "failover", "failure", "low storage", "maintenance", "notification", "recovery", "restoration"],
               "db-parameter-group": ["configuration change"], "db-security-group": ["configuration change", "failure"], "db-snapshot": ["creation", "deletion", "notification", "restoration"],
               "db-cluster": ["configuration change", "creation", "deletion", "failover", "failure", "maintenance", "notification"], "db-cluster-snapshot": ["backup", "creation", "deletion", "notification", "restoration"],
               "db-proxy": ["configuration change", "creation", "deletion", "failure"]}


def op_DescribeEventCategories(store, params, msg_store=None):
    st = _p(params, "SourceType")
    if st and st not in _EVENT_CATS:
        _err("InvalidParameterValue", f"Invalid source type {st}.")
    rows = [{"SourceType": k, "EventCategories": v} for k, v in _EVENT_CATS.items() if not st or k == st]
    return _ok("DescribeEventCategories", _x("EventCategoriesMapList", rows))


# ───────────────────────── proxies ─────────────────────────
def _px(store, n):
    p = store.get_proxy(n)
    if not p:
        _err("DBProxyNotFoundFault", f"DB proxy {n} not found.", 404)
    return p


def op_ModifyDBProxy(store, params, msg_store=None):
    R = _R()
    p = _px(store, _p(params, "DBProxyName"))
    if params.get("RequireTLS") is not None:
        p["require_tls"] = _b(params, "RequireTLS")
    if params.get("IdleClientTimeout") is not None:
        p["idle_client_timeout"] = _i(params, "IdleClientTimeout", 1800)
    if _p(params, "RoleArn"):
        p["role_arn"] = params["RoleArn"]
    if _list(params, "SecurityGroups"):
        p["vpc_security_group_ids"] = _list(params, "SecurityGroups")
    if _list(params, "Auth"):
        p["auth"] = [{"AuthScheme": a.get("AuthScheme", "SECRETS"), "SecretArn": a.get("SecretArn", ""), "IAMAuth": a.get("IAMAuth", "DISABLED")} for a in _list(params, "Auth")]
    new = _p(params, "NewDBProxyName")
    if new and new != p["db_proxy_name"]:
        if store.get_proxy(new):
            _err("DBProxyAlreadyExistsFault", f"DB proxy {new} already exists.")
        store.drop_proxy(p["db_proxy_name"])
        p["db_proxy_name"], p["db_proxy_arn"], p["endpoint"] = new, R._proxy_arn(store, new), f"{new}.proxy-nano.us-east-1.rds.amazonaws.com"
        store.put_proxy(new, p)
    store.persist()
    return _ok("ModifyDBProxy", R._proxy_xml(p))


def _tg(p):
    c = p.setdefault("_tg", {"ConnectionPoolConfig": {"MaxConnectionsPercent": 100, "MaxIdleConnectionsPercent": 50, "ConnectionBorrowTimeout": 120, "SessionPinningFilters": []}})
    return {"DBProxyName": p["db_proxy_name"], "TargetGroupName": "default", "TargetGroupArn": f"{p['db_proxy_arn']}/default", "IsDefault": True, "Status": "available",
            "ConnectionPoolConfig": c["ConnectionPoolConfig"], "CreatedDate": p.get("created", ""), "UpdatedDate": p.get("created", "")}


def op_DescribeDBProxyTargetGroups(store, params, msg_store=None):
    p = _px(store, _p(params, "DBProxyName"))
    tg = _tg(p)
    if _p(params, "TargetGroupName") and _p(params, "TargetGroupName") != "default":
        _err("DBProxyTargetGroupNotFoundFault", "Target group not found.", 404)
    return _ok("DescribeDBProxyTargetGroups", "<TargetGroups>" + _x("member", tg) + "</TargetGroups>")


def op_ModifyDBProxyTargetGroup(store, params, msg_store=None):
    p = _px(store, _p(params, "DBProxyName"))
    _tg(p)
    cfg = p["_tg"]["ConnectionPoolConfig"]
    for k, fk in (("MaxConnectionsPercent", "ConnectionPoolConfig.MaxConnectionsPercent"), ("MaxIdleConnectionsPercent", "ConnectionPoolConfig.MaxIdleConnectionsPercent"),
                  ("ConnectionBorrowTimeout", "ConnectionPoolConfig.ConnectionBorrowTimeout")):
        if params.get(fk) is not None:
            v = int(params[fk])
            if k.endswith("Percent") and not 0 <= v <= 100:
                _err("InvalidParameterValue", f"{k} must be between 0 and 100.")
            cfg[k] = v
    if cfg["MaxIdleConnectionsPercent"] > cfg["MaxConnectionsPercent"]:
        _err("InvalidParameterValue", "MaxIdleConnectionsPercent cannot exceed MaxConnectionsPercent.")
    store.persist()
    return _ok("ModifyDBProxyTargetGroup", _x("DBProxyTargetGroup", _tg(p)))


def _pxep_xml(e):
    return _x("DBProxyEndpoint", {k: v for k, v in e.items() if not k.startswith("_")})


def op_CreateDBProxyEndpoint(store, params, msg_store=None):
    p = _px(store, _p(params, "DBProxyName"))
    n = _p(params, "DBProxyEndpointName")
    if not n:
        _err("InvalidParameterValue", "DBProxyEndpointName is required.")
    key = f"{p['db_proxy_name']}/{n}"
    if key in _g(store)["pxeps"]:
        _err("DBProxyEndpointAlreadyExistsFault", f"Proxy endpoint {n} already exists.")
    tr = _p(params, "TargetRole", "READ_WRITE")
    if tr not in ("READ_WRITE", "READ_ONLY"):
        _err("InvalidParameterValue", "TargetRole must be READ_WRITE or READ_ONLY.")
    e = {"DBProxyEndpointName": n, "DBProxyEndpointArn": f"arn:aws:rds:us-east-1:{store.account_id}:db-proxy-endpoint:prx-endpoint-{n}", "DBProxyName": p["db_proxy_name"], "Status": "available",
         "VpcId": "vpc-default", "VpcSecurityGroupIds": _list(params, "VpcSecurityGroupIds"), "VpcSubnetIds": _list(params, "VpcSubnetIds") or p.get("vpc_subnet_ids", []),
         "Endpoint": f"{n}.endpoint.proxy-nano.us-east-1.rds.amazonaws.com", "CreatedDate": _now(), "TargetRole": tr, "IsDefault": False}
    _g(store)["pxeps"][key] = e
    return _ok("CreateDBProxyEndpoint", _pxep_xml(e).replace("<DBProxyEndpoint>", "<DBProxyEndpoint>", 1))


def _need_pxep(store, n):
    e = next((e for e in _g(store)["pxeps"].values() if e["DBProxyEndpointName"] == n), None)
    if e is None:
        _err("DBProxyEndpointNotFoundFault", f"Proxy endpoint {n} not found.", 404)
    return e


def op_DescribeDBProxyEndpoints(store, params, msg_store=None):
    items = list(_g(store)["pxeps"].values())
    if _p(params, "DBProxyEndpointName"):
        items = [_need_pxep(store, _p(params, "DBProxyEndpointName"))]
    if _p(params, "DBProxyName"):
        items = [e for e in items if e["DBProxyName"] == _p(params, "DBProxyName")]
    return _ok("DescribeDBProxyEndpoints", "<DBProxyEndpoints>" + "".join(_pxep_xml(e) for e in items) + "</DBProxyEndpoints>")


def op_ModifyDBProxyEndpoint(store, params, msg_store=None):
    e = _need_pxep(store, _p(params, "DBProxyEndpointName"))
    if _list(params, "VpcSecurityGroupIds"):
        e["VpcSecurityGroupIds"] = _list(params, "VpcSecurityGroupIds")
    new = _p(params, "NewDBProxyEndpointName")
    if new:
        _g(store)["pxeps"].pop(f"{e['DBProxyName']}/{e['DBProxyEndpointName']}")
        e["DBProxyEndpointName"] = new
        _g(store)["pxeps"][f"{e['DBProxyName']}/{new}"] = e
    return _ok("ModifyDBProxyEndpoint", _pxep_xml(e))


def op_DeleteDBProxyEndpoint(store, params, msg_store=None):
    e = _need_pxep(store, _p(params, "DBProxyEndpointName"))
    del _g(store)["pxeps"][f"{e['DBProxyName']}/{e['DBProxyEndpointName']}"]
    return _ok("DeleteDBProxyEndpoint", _pxep_xml(e))


# ───────────────────────── maintenance / catalogs ─────────────────────────
def _pending_for(store):
    R = _R()
    out = []
    for i in store.instance_ids():
        d = store.get_instance(i)
        if d.get("ca_certificate_identifier", R.DEFAULT_CA) != R.DEFAULT_CA:
            out.append((d["db_instance_arn"], {"Action": "ca-certificate-rotation", "Description": f"Rotate the CA certificate from {d['ca_certificate_identifier']} to {R.DEFAULT_CA}", "_iid": i}))
        if d.get("pending_engine_version"):
            out.append((d["db_instance_arn"], {"Action": "system-update", "Description": f"Engine version upgrade to {d['pending_engine_version']}", "_iid": i}))
    return out


def op_DescribePendingMaintenanceActions(store, params, msg_store=None):
    rid = _p(params, "ResourceIdentifier")
    byres = {}
    for arn, a in _pending_for(store):
        if rid and rid not in (arn, a["_iid"]):
            continue
        byres.setdefault(arn, []).append({"Action": a["Action"], "Description": a["Description"], "AutoAppliedAfterDate": _now(), "CurrentApplyDate": _now(), "OptInStatus": "pending"})
    rows = [{"ResourceIdentifier": arn, "PendingMaintenanceActionDetails": acts} for arn, acts in byres.items()]
    return _ok("DescribePendingMaintenanceActions", _x("PendingMaintenanceActions", rows))


def op_ApplyPendingMaintenanceAction(store, params, msg_store=None):
    R = _R()
    rid, act = _p(params, "ResourceIdentifier"), _p(params, "ApplyAction")
    if _p(params, "OptInType") not in ("immediate", "next-maintenance", "undo-opt-in"):
        _err("InvalidParameterValue", "OptInType must be immediate, next-maintenance or undo-opt-in.")
    hit = next(((arn, a) for arn, a in _pending_for(store) if rid in (arn, a["_iid"]) and a["Action"] == act), None)
    if hit is None:
        _err("ResourceNotFoundFault", f"No pending {act} action for {rid}.", 404)
    d = store.get_instance(hit[1]["_iid"])
    if _p(params, "OptInType") == "immediate":
        if act == "ca-certificate-rotation":
            d["ca_certificate_identifier"] = R.DEFAULT_CA
        elif act == "system-update":
            d["engine_version"] = d.pop("pending_engine_version")
        store.persist()
    remaining = [a for arn, a in _pending_for(store) if arn == hit[0]]
    rows = {"ResourceIdentifier": hit[0], "PendingMaintenanceActionDetails": [{"Action": a["Action"], "Description": a["Description"], "OptInStatus": "pending"} for a in remaining]}
    return _ok("ApplyPendingMaintenanceAction", _x("ResourcePendingMaintenanceActions", rows))


_CLASSES = {"mysql": ["db.t3.micro", "db.t3.small", "db.t3.medium", "db.m5.large", "db.m5.xlarge", "db.r5.large", "db.r5.xlarge"],
            "postgres": ["db.t3.micro", "db.t3.small", "db.t3.medium", "db.m5.large", "db.m5.xlarge", "db.r5.large", "db.r5.xlarge"],
            "mariadb": ["db.t3.micro", "db.t3.small", "db.m5.large", "db.r5.large"],
            "aurora-mysql": ["db.t3.medium", "db.t4g.medium", "db.r5.large", "db.r5.xlarge", "db.r6g.large", "db.serverless"],
            "aurora-postgresql": ["db.t3.medium", "db.t4g.medium", "db.r5.large", "db.r5.xlarge", "db.r6g.large", "db.serverless"],
            "oracle-ee": ["db.m5.large", "db.r5.large"], "sqlserver-ex": ["db.t3.small", "db.t3.medium"]}


def op_DescribeOrderableDBInstanceOptions(store, params, msg_store=None):
    eng = _p(params, "Engine").lower()
    if not eng:
        _err("InvalidParameterValue", "Engine is required.")
    if eng not in _CLASSES:
        return _ok("DescribeOrderableDBInstanceOptions", "<OrderableDBInstanceOptions></OrderableDBInstanceOptions>")
    ver = _p(params, "EngineVersion", _ENGINE_VER.get(eng, "1.0"))
    want = _p(params, "DBInstanceClass")
    rows = []
    for cls in _CLASSES[eng]:
        if want and cls != want:
            continue
        rows.append({"Engine": eng, "EngineVersion": ver, "DBInstanceClass": cls, "LicenseModel": "aurora" if eng.startswith("aurora") else "general-public-license",
                     "AvailabilityZones": [{"Name": z} for z in ("us-east-1a", "us-east-1b", "us-east-1c")], "MultiAZCapable": not eng.startswith("aurora"), "ReadReplicaCapable": True,
                     "Vpc": True, "SupportsStorageEncryption": True, "StorageType": "aurora" if eng.startswith("aurora") else "gp3", "SupportsIops": not eng.startswith("aurora"),
                     "SupportsEnhancedMonitoring": True, "SupportsIAMDatabaseAuthentication": True, "SupportsPerformanceInsights": not cls.startswith("db.t"), "MinStorageSize": 20, "MaxStorageSize": 65536})
    return _ok("DescribeOrderableDBInstanceOptions", "<OrderableDBInstanceOptions>" + "".join(_x("OrderableDBInstanceOption", r).replace("<AvailabilityZones><member>", "<AvailabilityZones><AvailabilityZone>").replace("</member></AvailabilityZones>", "</AvailabilityZone></AvailabilityZones>") for r in rows) + "</OrderableDBInstanceOptions>")


def op_DescribeValidDBInstanceModifications(store, params, msg_store=None):
    n = _p(params, "DBInstanceIdentifier")
    d = store.get_instance(n)
    if d is None:
        _err("DBInstanceNotFound", f"DBInstance {n} not found.", 404)
    cur = d.get("allocated_storage", 20)
    classes = [c for c in _CLASSES.get(d["engine"], [d["db_instance_class"]])]
    inner = ("<Storage>" + _x("member", {"StorageType": d.get("storage_type", "gp3"), "StorageSize": [{"From": cur, "To": 65536, "Step": 1}], "IopsToStorageRatio": [{"From": 0.5, "To": 50.0}], "SupportsStorageAutoscaling": True}) + "</Storage>"
             + "<ValidProcessorFeatures></ValidProcessorFeatures>")
    inner = inner.replace("<StorageSize><member>", "<StorageSize><Range>").replace("</member></StorageSize>", "</Range></StorageSize>").replace("<IopsToStorageRatio><member>", "<IopsToStorageRatio><DoubleRange>").replace("</member></IopsToStorageRatio>", "</DoubleRange></IopsToStorageRatio>")
    inner = inner.replace("<member><StorageType>", "<ValidStorageOptions><StorageType>").replace("</SupportsStorageAutoscaling></member>", "</SupportsStorageAutoscaling></ValidStorageOptions>")
    return _ok("DescribeValidDBInstanceModifications", f"<ValidDBInstanceModificationsMessage>{inner}</ValidDBInstanceModificationsMessage>")


def op_DescribeOptionGroupOptions(store, params, msg_store=None):
    eng = _p(params, "EngineName")
    if not eng:
        _err("InvalidParameterValue", "EngineName is required.")
    cat = {"mysql": [("MEMCACHED", "Innodb Memcached for MySQL", 11211)], "oracle-ee": [("OEM", "Oracle Enterprise Manager", 5500), ("S3_INTEGRATION", "Oracle S3 integration", None), ("SSL", "Oracle SSL", 2484)],
           "sqlserver-ee": [("SQLSERVER_BACKUP_RESTORE", "SQL Server native backup/restore", None)]}.get(eng, [])
    rows = "".join(_x("OptionGroupOption", {"Name": n, "Description": d, "EngineName": eng, "MajorEngineVersion": _p(params, "MajorEngineVersion", "8.0"), "DefaultPort": p, "PortRequired": p is not None, "Persistent": False, "Permanent": False}) for n, d, p in cat)
    return _ok("DescribeOptionGroupOptions", f"<OptionGroupOptions>{rows}</OptionGroupOptions>")


def op_DescribeSourceRegions(store, params, msg_store=None):
    regs = ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-south-1", "ap-southeast-1"]
    if _p(params, "RegionName"):
        regs = [r for r in regs if r == params["RegionName"]]
    return _ok("DescribeSourceRegions", _x("SourceRegions", [{"RegionName": r, "Endpoint": f"https://rds.{r}.amazonaws.com", "Status": "available", "SupportsDBInstanceAutomatedBackupsReplication": True} for r in regs]))


def op_DescribeReservedDBInstancesOfferings(store, params, msg_store=None):
    rows = []
    for cls, hourly in (("db.t3.micro", 0.012), ("db.t3.medium", 0.05), ("db.m5.large", 0.14), ("db.r5.large", 0.18)):
        for term, label in ((31536000, "No Upfront"), (31536000, "All Upfront"), (94608000, "All Upfront")):
            for multi in (False, True):
                oid = f"offering-{cls}-{term}-{label.replace(' ', '')}-{'maz' if multi else 'saz'}"
                rows.append({"ReservedDBInstancesOfferingId": oid, "DBInstanceClass": cls, "Duration": term, "FixedPrice": 0.0 if label == "No Upfront" else round(hourly * 8760 * (term / 31536000) * 0.6, 2),
                             "UsagePrice": 0.0, "CurrencyCode": "USD", "ProductDescription": _p(params, "ProductDescription", "postgresql"), "OfferingType": label, "MultiAZ": multi,
                             "RecurringCharges": [{"RecurringChargeAmount": round(hourly * (2 if multi else 1) * 0.7, 4), "RecurringChargeFrequency": "Hourly"}] if label == "No Upfront" else []})
    for k, pk in (("DBInstanceClass", "DBInstanceClass"), ("OfferingType", "OfferingType"), ("ReservedDBInstancesOfferingId", "ReservedDBInstancesOfferingId")):
        if _p(params, pk):
            rows = [r for r in rows if r[k] == params[pk]]
    if params.get("MultiAZ") is not None:
        rows = [r for r in rows if r["MultiAZ"] == _b(params, "MultiAZ")]
    if _p(params, "Duration"):
        rows = [r for r in rows if str(r["Duration"]) == params["Duration"] or (params["Duration"] in ("1", "3") and r["Duration"] == int(params["Duration"]) * 31536000)]
    return _ok("DescribeReservedDBInstancesOfferings", "<ReservedDBInstancesOfferings>" + "".join(_x("ReservedDBInstancesOffering", r) for r in rows) + "</ReservedDBInstancesOfferings>")


def op_DescribeDBMajorEngineVersions(store, params, msg_store=None):
    rows = [("mysql", "8.0"), ("mysql", "5.7"), ("postgres", "16"), ("postgres", "15"), ("postgres", "14"), ("mariadb", "10.11"), ("aurora-mysql", "8.0"), ("aurora-postgresql", "16")]
    if _p(params, "Engine"):
        rows = [r for r in rows if r[0] == params["Engine"]]
    return _ok("DescribeDBMajorEngineVersions", _x("DBMajorEngineVersions", [{"Engine": e, "MajorEngineVersion": v, "SupportedEngineLifecycles": []} for e, v in rows]))


def op_DescribeServerlessV2PlatformVersions(store, params, msg_store=None):
    rows = [{"ServerlessV2PlatformVersion": "3", "Engine": "aurora-mysql", "Status": "enabled", "IsDefault": True}, {"ServerlessV2PlatformVersion": "3", "Engine": "aurora-postgresql", "Status": "enabled", "IsDefault": True}]
    if _p(params, "Engine"):
        rows = [r for r in rows if r["Engine"] == params["Engine"]]
    return _ok("DescribeServerlessV2PlatformVersions", _x("ServerlessV2PlatformVersions", rows))


def op_ModifyCertificates(store, params, msg_store=None):
    R = _R()
    cert = _p(params, "CertificateIdentifier")
    if params.get("RemoveCustomerOverride") is not None:
        pass
    if cert:
        R._validate_ca_certificate(cert)
    g = _g(store)
    g["default_cert"] = None if _b(params, "RemoveCustomerOverride") else (cert or g.get("default_cert"))
    eff = g["default_cert"] or R.DEFAULT_CA
    return _ok("ModifyCertificates", _x("Certificate", {"CertificateIdentifier": eff, "CertificateType": "CA", "CustomerOverride": bool(g["default_cert"]), "CertificateArn": R._certificate_arn(store, eff)}))


def op_ModifyCustomDBEngineVersion(store, params, msg_store=None):
    R = _R()
    key = f"{_p(params, 'Engine')}:{_p(params, 'EngineVersion')}"
    cev = None
    for i in store.custom_engine_version_ids():
        c = store.get_custom_engine_version(i)
        if i == key or (c.get("engine") == params.get("Engine") and c.get("engine_version") == params.get("EngineVersion")):
            cev = c
    if cev is None:
        _err("CustomDBEngineVersionNotFoundFault", f"Custom engine version {key} not found.", 404)
    if _p(params, "Description"):
        cev["description"] = params["Description"]
    if _p(params, "Status"):
        if params["Status"] not in ("available", "inactive", "inactive-except-restore"):
            _err("InvalidParameterValue", "Status must be available, inactive or inactive-except-restore.")
        cev["status"] = params["Status"]
    store.persist()
    return _ok("ModifyCustomDBEngineVersion", R._custom_engine_version_xml(cev).replace("<DBEngineVersion>", "", 1).replace("</DBEngineVersion>", "", 1))


# ───────────────────────── registry ─────────────────────────
OPS = {k[3:]: v for k, v in globals().items() if k.startswith("op_")}
