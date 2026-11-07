"""DMS wire-gap operations merged into dms_core._OPS (v4 wire sweep): resource tags, Modify* for instances / endpoints /
tasks, MoveReplicationTask, ReloadTables, RefreshSchemas / DescribeSchemas (read from the simulator RDS instance an
endpoint resolves to), replication subnet groups, event subscriptions + events (derived from the real resource timeline),
certificates, premigration assessment runs, account/engine/endpoint-type catalogues, plus CRUD for the newer
migration-project objects (data providers, instance profiles, migration projects, serverless replication configs, data
migrations). State lives in ``store.dms`` on the RDS store beside the engine's own records.

Honest limits: subnet-group subnet ids are not cross-checked against the EC2 model (the DMS store sits on the RDS store);
assessment runs record and complete but evaluate no real assessment rules; serverless replication configs / data migrations
are lifecycle state machines (no capacity provisioning, and Start* does not copy data - use replication tasks for that)."""
from __future__ import annotations

import re
import time
import uuid


def _D():
    try:
        from core import dms_core
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import dms_core  # type: ignore
    return dms_core


def _err(code, msg, status=400):
    return _D().DmsError(code, msg, status)


def _s(store):
    d = _D()._st(store)
    for k in ("tags", "subnet_groups", "subscriptions", "certs", "assess_runs", "refresh", "data_providers", "instance_profiles",
              "migration_projects", "replication_configs", "replications", "data_migrations"):
        d.setdefault(k, {})
    return d


def _arn(kind, ident):
    return _D()._arn(kind, ident)


_ARN_FIELD = {"instances": "ReplicationInstanceArn", "endpoints": "EndpointArn", "tasks": "ReplicationTaskArn", "certs": "CertificateArn",
              "data_providers": "DataProviderArn", "instance_profiles": "InstanceProfileArn", "migration_projects": "MigrationProjectArn",
              "replication_configs": "ReplicationConfigArn", "data_migrations": "DataMigrationArn"}


def _all_arns(s):
    out = {rec[f] for k, f in _ARN_FIELD.items() for rec in s[k].values() if rec.get(f)}
    out |= {_arn("es", r["SubscriptionName"]) for r in s["subscriptions"].values()}
    out |= {_arn("subgrp", r["ReplicationSubnetGroupIdentifier"]) for r in s["subnet_groups"].values()}
    return out


# ── tags
def _tag_check(s, arn):
    if arn not in _all_arns(s):
        raise _err("ResourceNotFoundFault", f"The resource {arn} was not found.")


def add_tags(store, p):
    s = _s(store)
    arn = p.get("ResourceArn")
    if not arn:
        raise _err("InvalidParameterValueException", "Missing required parameter: ResourceArn")
    _tag_check(s, arn)
    cur = {t["Key"]: t for t in s["tags"].get(arn, [])}
    for t in p.get("Tags") or []:
        cur[t["Key"]] = {"Key": t["Key"], "Value": t.get("Value", "")}
    s["tags"][arn] = list(cur.values())
    return {}


def remove_tags(store, p):
    s = _s(store)
    arn = p.get("ResourceArn")
    _tag_check(s, arn)
    keys = set(p.get("TagKeys") or [])
    s["tags"][arn] = [t for t in s["tags"].get(arn, []) if t["Key"] not in keys]
    return {}


def list_tags(store, p):
    s = _s(store)
    arns = [p["ResourceArn"]] if p.get("ResourceArn") else list(p.get("ResourceArnList") or [])
    if not arns:
        raise _err("InvalidParameterValueException", "Missing required parameter: ResourceArn")
    for a in arns:
        _tag_check(s, a)
    return {"TagList": [dict(t, ResourceArn=a) if len(arns) > 1 else t for a in arns for t in s["tags"].get(a, [])]}


# ── modify
def modify_replication_instance(store, p):
    s = _s(store)
    ri = _D()._by_arn(s["instances"], p.get("ReplicationInstanceArn"), "ReplicationInstance")
    if p.get("ReplicationInstanceClass"):
        if not _D().CLASSES.match(p["ReplicationInstanceClass"]):
            raise _err("InvalidParameterValueException", f"Invalid replication instance class {p['ReplicationInstanceClass']}.")
        ri["ReplicationInstanceClass"] = p["ReplicationInstanceClass"]
    if p.get("AllocatedStorage") is not None:
        if not 5 <= int(p["AllocatedStorage"]) <= 6144:
            raise _err("InvalidParameterValueException", "AllocatedStorage must be between 5 and 6144 GiB.")
        ri["AllocatedStorage"] = int(p["AllocatedStorage"])
    for k in ("MultiAZ", "AutoMinorVersionUpgrade", "EngineVersion", "NetworkType", "PreferredMaintenanceWindow"):
        if p.get(k) is not None:
            ri[k] = p[k]
    return {"ReplicationInstance": ri}


def reboot_replication_instance(store, p):
    s = _s(store)
    ri = _D()._by_arn(s["instances"], p.get("ReplicationInstanceArn"), "ReplicationInstance")
    ri["LastRebootTime"] = time.time()
    if p.get("ForceFailover") and not ri.get("MultiAZ"):
        raise _err("InvalidParameterCombinationException", "ForceFailover requires a Multi-AZ replication instance.")
    return {"ReplicationInstance": ri}


def modify_endpoint(store, p):
    s = _s(store)
    ep = _D()._by_arn(s["endpoints"], p.get("EndpointArn"), "Endpoint")
    if p.get("EngineName"):
        if p["EngineName"].lower() not in _D().ENGINES:
            raise _err("InvalidParameterValueException", f"Invalid endpoint engine name {p['EngineName']}.")
        ep["EngineName"] = ep["EngineDisplayName"] = p["EngineName"].lower()
    if p.get("EndpointType"):
        if p["EndpointType"] not in ("source", "target"):
            raise _err("InvalidParameterValueException", "EndpointType must be one of: source, target.")
        ep["EndpointType"] = p["EndpointType"]
    for k in ("ServerName", "Port", "DatabaseName", "Username", "ExtraConnectionAttributes", "SslMode", "CertificateArn", "ServiceAccessRoleArn"):
        if p.get(k) is not None:
            ep[k] = p[k]
    if p.get("EndpointIdentifier"):
        new = p["EndpointIdentifier"].lower()
        _D()._ident(new, "endpoint")
        s["endpoints"].pop(ep["EndpointIdentifier"], None)
        ep["EndpointIdentifier"] = new
        s["endpoints"][new] = ep
    # a changed endpoint invalidates earlier connection tests
    s["connections"] = {k: v for k, v in s["connections"].items() if v["EndpointArn"] != ep["EndpointArn"]}
    return {"Endpoint": ep}


def modify_replication_task(store, p):
    s = _s(store)
    t = _D()._by_arn(s["tasks"], p.get("ReplicationTaskArn"), "ReplicationTask")
    if t["Status"] not in ("ready", "stopped", "failed", "modifying"):
        raise _err("InvalidResourceStateFault", f"The replication task must be stopped to be modified (status: {t['Status']}).")
    if p.get("MigrationType"):
        if p["MigrationType"] not in _D().MIG_TYPES:
            raise _err("InvalidParameterValueException", "MigrationType must be one of: full-load, cdc, full-load-and-cdc.")
        t["MigrationType"] = p["MigrationType"]
    if p.get("TableMappings"):
        _D()._rules(p["TableMappings"])
        t["TableMappings"] = p["TableMappings"]
    if p.get("ReplicationTaskSettings"):
        t["ReplicationTaskSettings"] = p["ReplicationTaskSettings"]
    if p.get("ReplicationTaskIdentifier"):
        new = p["ReplicationTaskIdentifier"].lower()
        _D()._ident(new, "replication task")
        s["tasks"].pop(t["ReplicationTaskIdentifier"], None)
        s["stats"][new] = s["stats"].pop(t["ReplicationTaskIdentifier"], {})
        t["ReplicationTaskIdentifier"] = new
        s["tasks"][new] = t
    return {"ReplicationTask": t}


def move_replication_task(store, p):
    s = _s(store)
    t = _D()._by_arn(s["tasks"], p.get("ReplicationTaskArn"), "ReplicationTask")
    ri = _D()._by_arn(s["instances"], p.get("TargetReplicationInstanceArn"), "ReplicationInstance")
    if t["Status"] == "running":
        raise _err("InvalidResourceStateFault", "Stop the replication task before moving it.")
    t["ReplicationInstanceArn"] = ri["ReplicationInstanceArn"]
    return {"ReplicationTask": t}


def reload_tables(store, p):
    s = _s(store)
    t = _D()._by_arn(s["tasks"], p.get("ReplicationTaskArn"), "ReplicationTask")
    if t["Status"] != "running":
        raise _err("InvalidResourceStateFault", f"ReloadTables requires a running task (status: {t['Status']}).")
    if not p.get("TablesToReload"):
        raise _err("InvalidParameterValueException", "Missing required parameter: TablesToReload")
    stats = s["stats"].setdefault(t["ReplicationTaskIdentifier"], {})
    for tb in p["TablesToReload"]:
        stats.pop(f"{tb.get('SchemaName', 'public')}.{tb.get('TableName')}", None)
        stats.pop(tb.get("TableName"), None)
    _D()._sync(store, t, cdc=False)
    return {"ReplicationTaskArn": t["ReplicationTaskArn"]}


def delete_connection(store, p):
    s = _s(store)
    key = f"{p.get('ReplicationInstanceArn')}|{p.get('EndpointArn')}"
    c = s["connections"].pop(key, None)
    if c is None:
        raise _err("ResourceNotFoundFault", "The connection was not found.")
    return {"Connection": dict(c, Status="deleting")}


# ── schemas (read from the real RDS instance)
def refresh_schemas(store, p):
    s = _s(store)
    ep = _D()._by_arn(s["endpoints"], p.get("EndpointArn"), "Endpoint")
    ri = _D()._by_arn(s["instances"], p.get("ReplicationInstanceArn"), "ReplicationInstance")
    hit = _D()._resolve_db(store, ep) if ep["EngineName"] in _D().SQL_ENGINES else None
    st = {"EndpointArn": ep["EndpointArn"], "ReplicationInstanceArn": ri["ReplicationInstanceArn"],
          "Status": "successful" if hit else "failed", "LastRefreshDate": time.time()}
    if not hit:
        st["LastFailureMessage"] = f"Cannot resolve host '{ep.get('ServerName')}' to a simulator RDS instance."
    s["refresh"][ep["EndpointArn"]] = st
    return {"RefreshSchemasStatus": st}


def describe_refresh_status(store, p):
    s = _s(store)
    ep = _D()._by_arn(s["endpoints"], p.get("EndpointArn"), "Endpoint")
    st = s["refresh"].get(ep["EndpointArn"])
    return {"RefreshSchemasStatus": st} if st else {}


def describe_schemas(store, p):
    s = _s(store)
    ep = _D()._by_arn(s["endpoints"], p.get("EndpointArn"), "Endpoint")
    if ep["EndpointArn"] not in s["refresh"] or s["refresh"][ep["EndpointArn"]]["Status"] != "successful":
        raise _err("InvalidResourceStateFault", "Run RefreshSchemas for this endpoint first.")
    return {"Schemas": [ep.get("DatabaseName") or "public"]}


# ── subnet groups
def _sg_view(g):
    return {k: v for k, v in g.items() if not k.startswith("_")}


def create_subnet_group(store, p):
    s = _s(store)
    ident = p.get("ReplicationSubnetGroupIdentifier")
    if not ident or not p.get("ReplicationSubnetGroupDescription") or not p.get("SubnetIds"):
        raise _err("InvalidParameterValueException", "ReplicationSubnetGroupIdentifier, ReplicationSubnetGroupDescription and SubnetIds are required.")
    ident = ident.lower()
    if ident in s["subnet_groups"]:
        raise _err("ResourceAlreadyExistsFault", f"The replication subnet group {ident} already exists.")
    if len(p["SubnetIds"]) < 2:
        raise _err("InvalidSubnet", "A replication subnet group needs subnets in at least two Availability Zones.")
    azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
    g = {"ReplicationSubnetGroupIdentifier": ident, "ReplicationSubnetGroupDescription": p["ReplicationSubnetGroupDescription"],
         "VpcId": "vpc-" + uuid.uuid5(uuid.NAMESPACE_DNS, ident).hex[:17], "SubnetGroupStatus": "Complete",
         "Subnets": [{"SubnetIdentifier": sid, "SubnetAvailabilityZone": {"Name": azs[i % 3]}, "SubnetStatus": "Active"} for i, sid in enumerate(p["SubnetIds"])],
         "SupportedNetworkTypes": ["IPV4"]}
    s["subnet_groups"][ident] = g
    return {"ReplicationSubnetGroup": g}


def describe_subnet_groups(store, p):
    s = _s(store)
    items = list(s["subnet_groups"].values())
    for f in p.get("Filters") or []:
        if f.get("Name") == "replication-subnet-group-id":
            items = [g for g in items if g["ReplicationSubnetGroupIdentifier"] in f.get("Values", [])]
    return {"ReplicationSubnetGroups": items}


def modify_subnet_group(store, p):
    s = _s(store)
    g = s["subnet_groups"].get(str(p.get("ReplicationSubnetGroupIdentifier", "")).lower())
    if g is None:
        raise _err("ResourceNotFoundFault", "The replication subnet group was not found.")
    if p.get("ReplicationSubnetGroupDescription"):
        g["ReplicationSubnetGroupDescription"] = p["ReplicationSubnetGroupDescription"]
    if p.get("SubnetIds"):
        azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
        g["Subnets"] = [{"SubnetIdentifier": sid, "SubnetAvailabilityZone": {"Name": azs[i % 3]}, "SubnetStatus": "Active"} for i, sid in enumerate(p["SubnetIds"])]
    return {"ReplicationSubnetGroup": g}


def delete_subnet_group(store, p):
    s = _s(store)
    ident = str(p.get("ReplicationSubnetGroupIdentifier", "")).lower()
    if ident not in s["subnet_groups"]:
        raise _err("ResourceNotFoundFault", "The replication subnet group was not found.")
    if any(i.get("ReplicationSubnetGroupIdentifier") == ident for i in s["instances"].values()):
        raise _err("InvalidResourceStateFault", "The replication subnet group is in use by a replication instance.")
    del s["subnet_groups"][ident]
    return {}


# ── event subscriptions / events
_CATEGORIES = [{"SourceType": "replication-instance", "EventCategories": ["configuration change", "creation", "deletion", "maintenance", "low storage", "failover", "failure"]},
               {"SourceType": "replication-task", "EventCategories": ["state change", "creation", "deletion", "failure", "configuration change"]}]


def describe_event_categories(store, p):
    st = p.get("SourceType")
    return {"EventCategoryGroupList": [c for c in _CATEGORIES if not st or c["SourceType"] == st]}


def _sub_view(x):
    return {k: v for k, v in x.items()}


def create_subscription(store, p):
    s = _s(store)
    for n in ("SubscriptionName", "SnsTopicArn"):
        if not p.get(n):
            raise _err("InvalidParameterValueException", f"Missing required parameter: {n}")
    n = p["SubscriptionName"]
    if n in s["subscriptions"]:
        raise _err("ResourceAlreadyExistsFault", f"The event subscription {n} already exists.")
    if not str(p["SnsTopicArn"]).startswith("arn:aws:sns:"):
        raise _err("SNSInvalidTopicFault", "The SNS topic ARN is invalid.")
    rec = {"CustomerAwsId": "123456789012", "CustSubscriptionId": n, "SnsTopicArn": p["SnsTopicArn"], "Status": "active",
           "SubscriptionCreationTime": time.strftime("%Y-%m-%d %H:%M:%S"), "SourceType": p.get("SourceType", "replication-instance"),
           "SourceIdsList": p.get("SourceIds") or [], "EventCategoriesList": p.get("EventCategories") or [], "Enabled": p.get("Enabled", True),
           "SubscriptionName": n}
    s["subscriptions"][n] = rec
    return {"EventSubscription": {k: v for k, v in rec.items() if k != "SubscriptionName"}}


def describe_subscriptions(store, p):
    s = _s(store)
    items = [r for r in s["subscriptions"].values() if not p.get("SubscriptionName") or r["SubscriptionName"] == p["SubscriptionName"]]
    if p.get("SubscriptionName") and not items:
        raise _err("ResourceNotFoundFault", f"The event subscription {p['SubscriptionName']} was not found.")
    return {"EventSubscriptionsList": [{k: v for k, v in r.items() if k != "SubscriptionName"} for r in items]}


def modify_subscription(store, p):
    s = _s(store)
    r = s["subscriptions"].get(p.get("SubscriptionName"))
    if r is None:
        raise _err("ResourceNotFoundFault", f"The event subscription {p.get('SubscriptionName')} was not found.")
    for k, f in (("SnsTopicArn", "SnsTopicArn"), ("SourceType", "SourceType"), ("EventCategories", "EventCategoriesList"), ("Enabled", "Enabled")):
        if p.get(k) is not None:
            r[f] = p[k]
    return {"EventSubscription": {k: v for k, v in r.items() if k != "SubscriptionName"}}


def delete_subscription(store, p):
    s = _s(store)
    r = s["subscriptions"].pop(p.get("SubscriptionName"), None)
    if r is None:
        raise _err("ResourceNotFoundFault", f"The event subscription {p.get('SubscriptionName')} was not found.")
    return {"EventSubscription": {k: v for k, v in r.items() if k != "SubscriptionName"}}


def describe_events(store, p):
    """Events derived from the actual resource timeline (creation of instances / task starts / failures)."""
    s = _s(store)
    ev = []
    for r in s["instances"].values():
        ev.append({"SourceIdentifier": r["ReplicationInstanceIdentifier"], "SourceType": "replication-instance",
                   "Message": "Replication instance created", "EventCategories": ["creation"], "Date": r["InstanceCreateTime"]})
    for t in s["tasks"].values():
        ev.append({"SourceIdentifier": t["ReplicationTaskIdentifier"], "SourceType": "replication-task",
                   "Message": "Replication task created", "EventCategories": ["creation"], "Date": t["ReplicationTaskCreationDate"]})
        if t.get("ReplicationTaskStartDate"):
            ev.append({"SourceIdentifier": t["ReplicationTaskIdentifier"], "SourceType": "replication-task",
                       "Message": f"Replication task status: {t['Status']}", "EventCategories": ["state change"], "Date": t["ReplicationTaskStartDate"]})
        if t.get("LastFailureMessage"):
            ev.append({"SourceIdentifier": t["ReplicationTaskIdentifier"], "SourceType": "replication-task",
                       "Message": t["LastFailureMessage"], "EventCategories": ["failure"], "Date": t.get("ReplicationTaskStartDate", time.time())})
    if p.get("SourceIdentifier"):
        ev = [e for e in ev if e["SourceIdentifier"] == p["SourceIdentifier"].lower()]
    if p.get("SourceType"):
        ev = [e for e in ev if e["SourceType"] == p["SourceType"]]
    return {"Events": sorted(ev, key=lambda e: e["Date"])}


# ── certificates
def import_certificate(store, p):
    s = _s(store)
    ident = p.get("CertificateIdentifier")
    pem = p.get("CertificatePem")
    if not ident or not pem:
        raise _err("InvalidParameterValueException", "CertificateIdentifier and CertificatePem are required.")
    if "BEGIN CERTIFICATE" not in pem:
        raise _err("InvalidCertificateFault", "The certificate is not a valid PEM-encoded certificate.")
    if ident in s["certs"]:
        raise _err("ResourceAlreadyExistsFault", f"The certificate {ident} already exists.")
    rec = {"CertificateIdentifier": ident, "CertificateCreationDate": time.time(), "CertificatePem": pem,
           "CertificateArn": _arn("cert", ident.upper()), "CertificateOwner": "123456789012", "SigningAlgorithm": "SHA256withRSA", "KeyLength": 2048}
    s["certs"][ident] = rec
    return {"Certificate": {k: v for k, v in rec.items() if k != "CertificatePem"}}


def describe_certificates(store, p):
    return {"Certificates": [{k: v for k, v in c.items() if k != "CertificatePem"} for c in _s(store)["certs"].values()]}


def delete_certificate(store, p):
    s = _s(store)
    c = next((c for c in s["certs"].values() if c["CertificateArn"] == p.get("CertificateArn")), None)
    if c is None:
        raise _err("ResourceNotFoundFault", "The certificate was not found.")
    if any(e.get("CertificateArn") == c["CertificateArn"] for e in s["endpoints"].values()):
        raise _err("ResourceQuotaExceededFault", "The certificate is in use by an endpoint.")
    del s["certs"][c["CertificateIdentifier"]]
    return {"Certificate": {k: v for k, v in c.items() if k != "CertificatePem"}}


# ── assessments
_INDIVIDUAL = ["unsupported-data-types-in-source", "table-with-lob-but-without-primary-or-unique-key", "source-table-without-primary-key"]


def describe_applicable_individual(store, p):
    return {"IndividualAssessmentNames": list(_INDIVIDUAL)}


def start_assessment_run(store, p):
    s = _s(store)
    t = _D()._by_arn(s["tasks"], p.get("ReplicationTaskArn"), "ReplicationTask")
    for n in ("ServiceAccessRoleArn", "ResultLocationBucket", "AssessmentRunName"):
        if not p.get(n):
            raise _err("InvalidParameterValueException", f"Missing required parameter: {n}")
    arn = _arn("assessment-run", uuid.uuid4().hex[:26].upper())
    r = {"ReplicationTaskAssessmentRunArn": arn, "ReplicationTaskArn": t["ReplicationTaskArn"], "Status": "passed",
         "ReplicationTaskAssessmentRunCreationDate": time.time(), "AssessmentProgress": {"IndividualAssessmentCount": len(_INDIVIDUAL), "IndividualAssessmentCompletedCount": len(_INDIVIDUAL)},
         "ServiceAccessRoleArn": p["ServiceAccessRoleArn"], "ResultLocationBucket": p["ResultLocationBucket"],
         "ResultLocationFolder": p.get("ResultLocationFolder"), "AssessmentRunName": p["AssessmentRunName"]}
    s["assess_runs"][arn] = {k: v for k, v in r.items() if v is not None}
    return {"ReplicationTaskAssessmentRun": s["assess_runs"][arn]}


def describe_assessment_runs(store, p):
    return {"ReplicationTaskAssessmentRuns": list(_s(store)["assess_runs"].values())}


def _run(s, p):
    r = s["assess_runs"].get(p.get("ReplicationTaskAssessmentRunArn"))
    if r is None:
        raise _err("ResourceNotFoundFault", "The assessment run was not found.")
    return r


def cancel_assessment_run(store, p):
    s = _s(store)
    r = _run(s, p)
    r["Status"] = "cancelling"
    return {"ReplicationTaskAssessmentRun": r}


def delete_assessment_run(store, p):
    s = _s(store)
    r = _run(s, p)
    del s["assess_runs"][r["ReplicationTaskAssessmentRunArn"]]
    return {"ReplicationTaskAssessmentRun": r}


def start_task_assessment(store, p):
    s = _s(store)
    t = _D()._by_arn(s["tasks"], p.get("ReplicationTaskArn"), "ReplicationTask")
    t["AssessmentStatus"] = "completed"
    return {"ReplicationTask": t}


def empty(key):
    return lambda store, p: {key: []}


# ── catalogues
def describe_account_attributes(store, p):
    s = _s(store)
    q = [("ReplicationInstances", 20, len(s["instances"])), ("AllocatedStorage", 10000, sum(i["AllocatedStorage"] for i in s["instances"].values())),
         ("Endpoints", 1000, len(s["endpoints"])), ("ReplicationTasks", 200, len(s["tasks"])), ("EndpointsPerInstance", 20, 0),
         ("TasksPerInstance", 200, 0), ("SubnetGroups", 20, len(s["subnet_groups"])), ("EventSubscriptions", 20, len(s["subscriptions"])),
         ("Certificates", 100, len(s["certs"]))]
    return {"AccountQuotas": [{"AccountQuotaName": n, "Used": u, "Max": m} for n, m, u in q], "UniqueAccountIdentifier": "e5f7a3c2-0d1b-4f9e-8a77-4c2d5b6e7f80"}


def describe_endpoint_types(store, p):
    out = []
    for e in sorted(_D().ENGINES):
        for t in ("source", "target"):
            out.append({"EngineName": e, "SupportsCDC": e in _D().SQL_ENGINES, "EndpointType": t, "EngineDisplayName": e})
    return {"SupportedEndpointTypes": out}


def describe_engine_versions(store, p):
    return {"EngineVersions": [{"Version": v, "Lifecycle": lc, "ReleaseStatus": "beta" if lc == "preview" else "", "LaunchDate": 1700000000.0, "AutoUpgradeDate": 1900000000.0,
                                "DeprecationDate": 1950000000.0, "ForceUpgradeDate": 2000000000.0, "AvailableUpgrades": []}
                               for v, lc in (("3.5.4", "active"), ("3.5.3", "active"), ("3.4.7", "deprecated"))]}


def describe_orderable(store, p):
    cls = ["dms.t3.micro", "dms.t3.small", "dms.t3.medium", "dms.t3.large", "dms.c5.large", "dms.c5.xlarge", "dms.r5.large", "dms.r5.xlarge"]
    return {"OrderableReplicationInstances": [{"EngineVersion": "3.5.4", "ReplicationInstanceClass": c, "StorageType": "gp2", "MinAllocatedStorage": 5,
                                               "MaxAllocatedStorage": 6144, "DefaultAllocatedStorage": 50, "IncludedAllocatedStorage": 50, "AvailabilityZones": ["us-east-1a", "us-east-1b", "us-east-1c"],
                                               "ReleaseStatus": ""} for c in cls]}


def describe_endpoint_settings(store, p):
    eng = str(p.get("EngineName") or "").lower()
    if eng not in _D().ENGINES:
        raise _err("InvalidParameterValueException", f"Invalid endpoint engine name {p.get('EngineName')}.")
    return {"EndpointSettings": [{"Name": "ServerName", "Type": "string", "Required": True, "Sensitive": False}, {"Name": "Port", "Type": "integer", "Required": True, "Sensitive": False},
                                 {"Name": "DatabaseName", "Type": "string", "Required": eng in _D().SQL_ENGINES, "Sensitive": False}, {"Name": "SslMode", "Type": "enum", "Enums": ["none", "require", "verify-ca", "verify-full"], "Required": False, "Sensitive": False}]}


# ── newer migration-project objects: generic CRUD
def _crud(kind, label, id_field, arn_field, arn_kind, required=(), extra=None):
    plural = {"data_providers": "DataProviders", "instance_profiles": "InstanceProfiles", "migration_projects": "MigrationProjects",
              "replication_configs": "ReplicationConfigs", "data_migrations": "DataMigrations"}[kind]

    def create(store, p):
        s = _s(store)
        for n in required:
            if p.get(n) in (None, ""):
                raise _err("InvalidParameterValueException", f"Missing required parameter: {n}")
        name = p.get(id_field) or p.get(label + "Name")
        if any(r.get(id_field) == name for r in s[kind].values()):
            raise _err("ResourceAlreadyExistsFault", f"The {label} {name} already exists.")
        rid = uuid.uuid4().hex[:26].upper()
        rec = {k: v for k, v in p.items() if v is not None and k not in ("Tags",)}
        rec[id_field] = name
        rec[arn_field] = _arn(arn_kind, rid)
        rec[label + "CreationTime"] = time.time()
        if extra:
            extra(rec)
        s[kind][rid] = rec
        if p.get("Tags"):
            s["tags"][rec[arn_field]] = [{"Key": t["Key"], "Value": t.get("Value", "")} for t in p["Tags"]]
        return {label: rec}

    def _find(s, p):
        ident = p.get(arn_field) or p.get(label + "Identifier")
        for rec in s[kind].values():
            if ident in (rec[arn_field], rec.get(id_field)):
                return rec
        raise _err("ResourceNotFoundFault", f"The {label} {ident} was not found.")

    def describe(store, p):
        s = _s(store)
        items = list(s[kind].values())
        for f in p.get("Filters") or []:
            items = [r for r in items if any(str(r.get(id_field)) == v or r.get(arn_field) == v for v in f.get("Values", []))]
        return {plural: items}

    def modify(store, p):
        s = _s(store)
        rec = _find(s, p)
        for k, v in p.items():
            if v is not None and not k.endswith("Identifier") and k != arn_field:
                rec[k] = v
        return {label: rec}

    def delete(store, p):
        s = _s(store)
        rec = _find(s, p)
        for k2 in ("migration_projects",) if kind in ("data_providers", "instance_profiles") else ():
            for mp in s[k2].values():
                if rec[arn_field] in str(mp):
                    raise _err("InvalidResourceStateFault", f"The {label} is referenced by migration project {mp.get('MigrationProjectName')}.")
        del s[kind][next(k for k, v in s[kind].items() if v is rec)]
        s["tags"].pop(rec[arn_field], None)
        return {label: rec}
    return create, describe, modify, delete, _find


_dp = _crud("data_providers", "DataProvider", "DataProviderName", "DataProviderArn", "data-provider", ("Engine", "Settings"))
_ip = _crud("instance_profiles", "InstanceProfile", "InstanceProfileName", "InstanceProfileArn", "instance-profile", ())
_mp = _crud("migration_projects", "MigrationProject", "MigrationProjectName", "MigrationProjectArn", "migration-project",
            ("SourceDataProviderDescriptors", "TargetDataProviderDescriptors", "InstanceProfileIdentifier"))
_rc = _crud("replication_configs", "ReplicationConfig", "ReplicationConfigIdentifier", "ReplicationConfigArn", "replication-config",
            ("ReplicationConfigIdentifier", "SourceEndpointArn", "TargetEndpointArn", "ComputeConfig", "ReplicationType", "TableMappings"))
_dm = _crud("data_migrations", "DataMigration", "DataMigrationName", "DataMigrationArn", "data-migration", ("MigrationProjectIdentifier", "DataMigrationType", "ServiceAccessRoleArn"),
            extra=lambda r: r.update(DataMigrationStatus="ready"))


def start_replication(store, p):
    s = _s(store)
    cfg = _rc[4](s, {"ReplicationConfigArn": p.get("ReplicationConfigArn")})
    if p.get("StartReplicationType") not in ("start-replication", "resume-processing", "reload-target"):
        raise _err("InvalidParameterValueException", "StartReplicationType must be start-replication, resume-processing or reload-target.")
    r = s["replications"][cfg["ReplicationConfigArn"]] = {"ReplicationConfigArn": cfg["ReplicationConfigArn"], "ReplicationConfigIdentifier": cfg["ReplicationConfigIdentifier"],
                                                          "Status": "running", "ReplicationType": cfg["ReplicationType"], "SourceEndpointArn": cfg["SourceEndpointArn"],
                                                          "TargetEndpointArn": cfg["TargetEndpointArn"], "ProvisionData": {"ProvisionState": "provisioned", "ProvisionedCapacityUnits": 1},
                                                          "ReplicationCreateTime": time.time(), "ReplicationLastStopTime": None}
    return {"Replication": {k: v for k, v in r.items() if v is not None}}


def stop_replication(store, p):
    s = _s(store)
    r = s["replications"].get(p.get("ReplicationConfigArn"))
    if r is None or r["Status"] != "running":
        raise _err("InvalidResourceStateFault", "The replication is not running.")
    r["Status"] = "stopped"
    r["ReplicationLastStopTime"] = time.time()
    return {"Replication": r}


def describe_replications(store, p):
    return {"Replications": list(_s(store)["replications"].values())}


def _dm_state(status):
    def op(store, p):
        s = _s(store)
        rec = _dm[4](s, {"DataMigrationArn": p.get("DataMigrationIdentifier"), "DataMigrationIdentifier": p.get("DataMigrationIdentifier")})
        if status == "running" and rec["DataMigrationStatus"] == "running":
            raise _err("InvalidResourceStateFault", "The data migration is already running.")
        rec["DataMigrationStatus"] = status
        if status == "running":
            rec["DataMigrationStartTime"] = time.time()
        else:
            rec["DataMigrationEndTime"] = time.time()
        return {"DataMigration": rec}
    return op


OPS = {
    "AddTagsToResource": add_tags, "RemoveTagsFromResource": remove_tags, "ListTagsForResource": list_tags,
    "ModifyReplicationInstance": modify_replication_instance, "RebootReplicationInstance": reboot_replication_instance,
    "ModifyEndpoint": modify_endpoint, "ModifyReplicationTask": modify_replication_task, "MoveReplicationTask": move_replication_task,
    "ReloadTables": reload_tables, "DeleteConnection": delete_connection,
    "RefreshSchemas": refresh_schemas, "DescribeRefreshSchemasStatus": describe_refresh_status, "DescribeSchemas": describe_schemas,
    "CreateReplicationSubnetGroup": create_subnet_group, "DescribeReplicationSubnetGroups": describe_subnet_groups,
    "ModifyReplicationSubnetGroup": modify_subnet_group, "DeleteReplicationSubnetGroup": delete_subnet_group,
    "DescribeEventCategories": describe_event_categories, "CreateEventSubscription": create_subscription,
    "DescribeEventSubscriptions": describe_subscriptions, "ModifyEventSubscription": modify_subscription,
    "DeleteEventSubscription": delete_subscription, "DescribeEvents": describe_events,
    "ImportCertificate": import_certificate, "DescribeCertificates": describe_certificates, "DeleteCertificate": delete_certificate,
    "DescribeApplicableIndividualAssessments": describe_applicable_individual,
    "StartReplicationTaskAssessmentRun": start_assessment_run, "DescribeReplicationTaskAssessmentRuns": describe_assessment_runs,
    "CancelReplicationTaskAssessmentRun": cancel_assessment_run, "DeleteReplicationTaskAssessmentRun": delete_assessment_run,
    "StartReplicationTaskAssessment": start_task_assessment,
    "DescribeReplicationTaskAssessmentResults": empty("ReplicationTaskAssessmentResults"),
    "DescribeReplicationTaskIndividualAssessments": empty("ReplicationTaskIndividualAssessments"),
    "DescribePendingMaintenanceActions": empty("PendingMaintenanceActions"),
    "DescribeAccountAttributes": describe_account_attributes, "DescribeEndpointTypes": describe_endpoint_types,
    "DescribeEngineVersions": describe_engine_versions, "DescribeOrderableReplicationInstances": describe_orderable,
    "DescribeEndpointSettings": describe_endpoint_settings,
    "CreateDataProvider": _dp[0], "DescribeDataProviders": _dp[1], "ModifyDataProvider": _dp[2], "DeleteDataProvider": _dp[3],
    "CreateInstanceProfile": _ip[0], "DescribeInstanceProfiles": _ip[1], "ModifyInstanceProfile": _ip[2], "DeleteInstanceProfile": _ip[3],
    "CreateMigrationProject": _mp[0], "DescribeMigrationProjects": _mp[1], "ModifyMigrationProject": _mp[2], "DeleteMigrationProject": _mp[3],
    "CreateReplicationConfig": _rc[0], "DescribeReplicationConfigs": _rc[1], "ModifyReplicationConfig": _rc[2], "DeleteReplicationConfig": _rc[3],
    "StartReplication": start_replication, "StopReplication": stop_replication, "DescribeReplications": describe_replications,
    "CreateDataMigration": _dm[0], "DescribeDataMigrations": _dm[1], "ModifyDataMigration": _dm[2], "DeleteDataMigration": _dm[3],
    "StartDataMigration": _dm_state("running"), "StopDataMigration": _dm_state("stopped"),
}
