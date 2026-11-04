# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Database Migration Service (target prefix AmazonDMSv20160101, JSON 1.1) between simulator RDS instances.

Replication instances, endpoints (source/target), TestConnection, replication tasks (full-load / cdc / full-load-and-cdc) with
selection-rule TableMappings, table statistics. The migration is REAL: an endpoint's ServerName resolves to a simulator RDS
instance (its endpoint address or identifier) and StartReplicationTask copies the selected tables' schema + rows between the two
instances' SQL engines. "CDC-lite": a running cdc / full-load-and-cdc task re-reads the source and applies row-level
inserts/updates/deletes (keyed on the primary key, else on the whole row) every time the task is described or reloaded, and
counts them in DescribeTableStatistics - there is no WAL/binlog reader, so changes become visible when polled, not instantly.

Honest limits: engines are whatever the simulator RDS instance runs (sqlite3 on Nano/offline-lite, Postgres where configured); the
DMS EngineName on an endpoint must be a real DMS engine but is checked against the RDS instance's engine only for the
postgres/mysql/mariadb families; no data validation, LOB settings, transformations/column rules, CDC checkpoints, premigration
assessments or serverless replication configs. State: ``store.dms`` on the RDS store (memory; rebuilt per boot).
"""
from __future__ import annotations

import json
import re
import time
import types
import uuid

REGION, ACCT = "us-east-1", "123456789012"
ENGINES = {"mysql", "oracle", "postgres", "mariadb", "aurora", "aurora-postgresql", "opensearch", "redshift", "s3", "db2", "azuredb",
           "sybase", "dynamodb", "mongodb", "kinesis", "kafka", "elasticsearch", "docdb", "sqlserver", "neptune", "redshift-serverless",
           "db2-zos", "aurora-serverless", "babelfish"}
SQL_ENGINES = {"mysql", "postgres", "mariadb", "aurora", "aurora-postgresql", "aurora-serverless"}
CLASSES = re.compile(r"^dms\.(t2|t3|c4|c5|c6i|r4|r5|r6i)\.(micro|small|medium|large|xlarge|2xlarge|4xlarge|8xlarge|12xlarge|16xlarge|24xlarge)$")
MIG_TYPES = ("full-load", "cdc", "full-load-and-cdc")


class DmsError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _st(store) -> dict:
    d = store.__dict__.setdefault("dms", {})
    for k in ("instances", "endpoints", "tasks", "connections", "stats"):
        d.setdefault(k, {})
    return d


def _arn(kind, ident):
    return f"arn:aws:dms:{REGION}:{ACCT}:{kind}:{ident}"


def _req(p, *names):
    for n in names:
        if p.get(n) in (None, ""):
            raise DmsError("InvalidParameterValueException", f"Missing required parameter: {n}")


def _ident(v, what):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,254}", str(v)) or "--" in str(v) or str(v).endswith("-"):
        raise DmsError("InvalidParameterValueException", f"The {what} identifier must start with a letter, contain only ASCII letters, digits and hyphens, "
                       "not end with a hyphen or contain two consecutive hyphens.")


def _ts():
    return time.time()


def _by_arn(d, arn, what):
    for v in d.values():
        if v.get(f"{what}Arn") == arn:
            return v
    raise DmsError("ResourceNotFoundFault", f"{what} '{arn}' not found.")


def _filters(items, p, mapping):
    for f in p.get("Filters") or []:
        key = mapping.get(f.get("Name"))
        if key is None:
            raise DmsError("InvalidParameterValueException", f"Unsupported filter name: {f.get('Name')}")
        vals = f.get("Values") or []
        items = [i for i in items if any(str(i.get(key, "")).split(":")[-1] == v or i.get(key) == v for v in vals)]
    return items


# ── replication instances
def create_replication_instance(store, p):
    s = _st(store)
    _req(p, "ReplicationInstanceIdentifier", "ReplicationInstanceClass")
    _ident(p["ReplicationInstanceIdentifier"], "replication instance")
    iid = p["ReplicationInstanceIdentifier"].lower()
    if iid in s["instances"]:
        raise DmsError("ResourceAlreadyExistsFault", f"The replication instance {iid} already exists.")
    if not CLASSES.match(p["ReplicationInstanceClass"]):
        raise DmsError("InvalidParameterValueException", f"Invalid replication instance class {p['ReplicationInstanceClass']}.")
    stor = int(p.get("AllocatedStorage") or 50)
    if not 5 <= stor <= 6144:
        raise DmsError("InvalidParameterValueException", "AllocatedStorage must be between 5 and 6144 GiB.")
    rec = {"ReplicationInstanceIdentifier": iid, "ReplicationInstanceClass": p["ReplicationInstanceClass"], "AllocatedStorage": stor,
           "ReplicationInstanceStatus": "available", "EngineVersion": p.get("EngineVersion") or "3.5.4",
           "MultiAZ": bool(p.get("MultiAZ")), "PubliclyAccessible": p.get("PubliclyAccessible", True),
           "AvailabilityZone": p.get("AvailabilityZone") or f"{REGION}a", "ReplicationInstanceArn": _arn("rep", iid.upper()),
           "InstanceCreateTime": _ts(), "AutoMinorVersionUpgrade": p.get("AutoMinorVersionUpgrade", True),
           "ReplicationInstancePrivateIpAddresses": ["10.0.0.%d" % (len(s["instances"]) + 10)],
           "ReplicationInstancePublicIpAddresses": ["203.0.113.%d" % (len(s["instances"]) + 10)], "PendingModifiedValues": {}}
    s["instances"][iid] = rec
    return {"ReplicationInstance": rec}


def describe_replication_instances(store, p):
    items = _filters(list(_st(store)["instances"].values()), p, {"replication-instance-id": "ReplicationInstanceIdentifier",
                     "replication-instance-arn": "ReplicationInstanceArn", "replication-instance-class": "ReplicationInstanceClass"})
    return {"ReplicationInstances": items}


def delete_replication_instance(store, p):
    s = _st(store)
    _req(p, "ReplicationInstanceArn")
    rec = _by_arn(s["instances"], p["ReplicationInstanceArn"], "ReplicationInstance")
    if any(t["ReplicationInstanceArn"] == rec["ReplicationInstanceArn"] for t in s["tasks"].values()):
        raise DmsError("InvalidResourceStateFault", "The replication instance is associated with one or more replication tasks.")
    del s["instances"][rec["ReplicationInstanceIdentifier"]]
    s["connections"] = {k: v for k, v in s["connections"].items() if v["ReplicationInstanceArn"] != rec["ReplicationInstanceArn"]}
    rec["ReplicationInstanceStatus"] = "deleting"
    return {"ReplicationInstance": rec}


# ── endpoints
def create_endpoint(store, p):
    s = _st(store)
    _req(p, "EndpointIdentifier", "EndpointType", "EngineName")
    _ident(p["EndpointIdentifier"], "endpoint")
    eid = p["EndpointIdentifier"].lower()
    if eid in s["endpoints"]:
        raise DmsError("ResourceAlreadyExistsFault", f"The endpoint {eid} already exists.")
    if p["EndpointType"] not in ("source", "target"):
        raise DmsError("InvalidParameterValueException", "EndpointType must be one of: source, target.")
    eng = p["EngineName"].lower()
    if eng not in ENGINES:
        raise DmsError("InvalidParameterValueException", f"Invalid endpoint engine name {p['EngineName']}.")
    if eng in SQL_ENGINES:
        for n in ("ServerName", "Port", "DatabaseName", "Username"):
            if p.get(n) in (None, ""):
                raise DmsError("InvalidParameterValueException", f"{n} is required for the {eng} engine.")
    rec = {"EndpointIdentifier": eid, "EndpointType": p["EndpointType"].lower(), "EngineName": eng, "EngineDisplayName": eng,
           "Username": p.get("Username"), "ServerName": p.get("ServerName"), "Port": p.get("Port"), "DatabaseName": p.get("DatabaseName"),
           "ExtraConnectionAttributes": p.get("ExtraConnectionAttributes"), "Status": "active", "KmsKeyId": p.get("KmsKeyId"),
           "EndpointArn": _arn("endpoint", eid.upper()), "SslMode": p.get("SslMode") or "none"}
    s["endpoints"][eid] = {k: v for k, v in rec.items() if v is not None}
    return {"Endpoint": s["endpoints"][eid]}


def describe_endpoints(store, p):
    items = _filters(list(_st(store)["endpoints"].values()), p, {"endpoint-id": "EndpointIdentifier", "endpoint-arn": "EndpointArn",
                     "endpoint-type": "EndpointType", "engine-name": "EngineName"})
    return {"Endpoints": items}


def delete_endpoint(store, p):
    s = _st(store)
    _req(p, "EndpointArn")
    rec = _by_arn(s["endpoints"], p["EndpointArn"], "Endpoint")
    if any(rec["EndpointArn"] in (t["SourceEndpointArn"], t["TargetEndpointArn"]) for t in s["tasks"].values()):
        raise DmsError("InvalidResourceStateFault", "The endpoint is used by one or more replication tasks.")
    del s["endpoints"][rec["EndpointIdentifier"]]
    s["connections"] = {k: v for k, v in s["connections"].items() if v["EndpointArn"] != rec["EndpointArn"]}
    return {"Endpoint": dict(rec, Status="deleting")}


def _resolve_db(store, ep):
    """The simulator RDS instance this endpoint points at, or None."""
    srv = (ep.get("ServerName") or "").lower()
    for dbid in store.instance_ids():
        db = store.get_instance(dbid) or {}
        if srv in (dbid.lower(), str(db.get("endpoint_address", "")).lower()):
            return dbid, db
    return None


def test_connection(store, p):
    s = _st(store)
    _req(p, "ReplicationInstanceArn", "EndpointArn")
    ri = _by_arn(s["instances"], p["ReplicationInstanceArn"], "ReplicationInstance")
    ep = _by_arn(s["endpoints"], p["EndpointArn"], "Endpoint")
    msg, status = "", "successful"
    if ep["EngineName"] in SQL_ENGINES:
        hit = _resolve_db(store, ep)
        if not hit:
            status, msg = "failed", f"Failed to connect to database. Cannot resolve host '{ep.get('ServerName')}'."
        elif (hit[1].get("status") or "available") != "available":
            status, msg = "failed", f"Failed to connect to database. The instance {hit[0]} is {hit[1].get('status')}."
        elif hit[1].get("master_username") and ep.get("Username") and hit[1]["master_username"] != ep["Username"]:
            status, msg = "failed", "Failed to connect to database. Authentication failed for the supplied user."
    else:
        status, msg = "failed", f"The simulator can only connect DMS endpoints of SQL engines ({', '.join(sorted(SQL_ENGINES))}); {ep['EngineName']} is not reachable."
    conn = {"ReplicationInstanceArn": ri["ReplicationInstanceArn"], "EndpointArn": ep["EndpointArn"], "Status": status,
            "LastFailureMessage": msg, "EndpointIdentifier": ep["EndpointIdentifier"],
            "ReplicationInstanceIdentifier": ri["ReplicationInstanceIdentifier"]}
    if not msg:
        conn.pop("LastFailureMessage")
    s["connections"][ri["ReplicationInstanceArn"] + "|" + ep["EndpointArn"]] = conn
    return {"Connection": conn}


def describe_connections(store, p):
    return {"Connections": _filters(list(_st(store)["connections"].values()), p, {"endpoint-arn": "EndpointArn", "replication-instance-arn": "ReplicationInstanceArn"})}


# ── tasks
def _rules(mappings):
    try:
        m = json.loads(mappings) if isinstance(mappings, str) else mappings
        rules = m["rules"]
        assert isinstance(rules, list) and rules
    except Exception:
        raise DmsError("InvalidParameterValueException", "TableMappings is not valid JSON of the form {\"rules\": [...]}.")
    for r in rules:
        if r.get("rule-type") not in ("selection", "transformation") or not r.get("rule-id") or "object-locator" not in r:
            raise DmsError("InvalidParameterValueException", "Each mapping rule needs rule-type, rule-id and object-locator.")
        if r["rule-type"] == "selection" and r.get("rule-action") not in ("include", "exclude", "explicit"):
            raise DmsError("InvalidParameterValueException", "Selection rule-action must be include, exclude or explicit.")
    if not any(r["rule-type"] == "selection" and r["rule-action"] != "exclude" for r in rules):
        raise DmsError("InvalidParameterValueException", "TableMappings must include at least one selection rule that includes tables.")
    return rules


def _like(pat, name):
    return re.fullmatch(re.escape(pat).replace("%", ".*").replace("_", "."), name, re.I) if "%" in pat else pat.lower() == name.lower()


def _selected(rules, tables):
    out = []
    for t in tables:
        inc = None
        for r in rules:
            if r["rule-type"] != "selection":
                continue
            loc = r["object-locator"]
            if _like(loc.get("table-name", "%"), t):
                inc = r["rule-action"] != "exclude"
        if inc:
            out.append(t)
    return out


def create_replication_task(store, p):
    s = _st(store)
    _req(p, "ReplicationTaskIdentifier", "SourceEndpointArn", "TargetEndpointArn", "ReplicationInstanceArn", "MigrationType", "TableMappings")
    _ident(p["ReplicationTaskIdentifier"], "replication task")
    tid = p["ReplicationTaskIdentifier"].lower()
    if tid in s["tasks"]:
        raise DmsError("ResourceAlreadyExistsFault", f"The replication task {tid} already exists.")
    if p["MigrationType"] not in MIG_TYPES:
        raise DmsError("InvalidParameterValueException", "MigrationType must be one of: full-load, cdc, full-load-and-cdc.")
    src = _by_arn(s["endpoints"], p["SourceEndpointArn"], "Endpoint")
    tgt = _by_arn(s["endpoints"], p["TargetEndpointArn"], "Endpoint")
    ri = _by_arn(s["instances"], p["ReplicationInstanceArn"], "ReplicationInstance")
    if src["EndpointType"] != "source" or tgt["EndpointType"] != "target":
        raise DmsError("InvalidParameterValueException", "The source endpoint must be of type source and the target endpoint of type target.")
    _rules(p["TableMappings"])
    for ep in (src, tgt):
        c = s["connections"].get(ri["ReplicationInstanceArn"] + "|" + ep["EndpointArn"])
        if not c or c["Status"] != "successful":
            raise DmsError("InvalidResourceStateFault", f"Endpoint {ep['EndpointIdentifier']} has not been successfully tested from replication instance "
                           f"{ri['ReplicationInstanceIdentifier']} (run TestConnection first).")
    rec = {"ReplicationTaskIdentifier": tid, "SourceEndpointArn": src["EndpointArn"], "TargetEndpointArn": tgt["EndpointArn"],
           "ReplicationInstanceArn": ri["ReplicationInstanceArn"], "MigrationType": p["MigrationType"], "TableMappings": p["TableMappings"] if isinstance(p["TableMappings"], str) else json.dumps(p["TableMappings"]),
           "ReplicationTaskSettings": p.get("ReplicationTaskSettings") or "{}", "Status": "ready", "ReplicationTaskCreationDate": _ts(),
           "ReplicationTaskArn": _arn("task", tid.upper()), "ReplicationTaskStats": {"FullLoadProgressPercent": 0, "TablesLoaded": 0, "TablesLoading": 0,
           "TablesQueued": 0, "TablesErrored": 0}}
    s["tasks"][tid] = rec
    s["stats"][tid] = {}
    return {"ReplicationTask": rec}


def describe_replication_tasks(store, p):
    s = _st(store)
    for t in s["tasks"].values():
        if t["Status"] == "running" and "cdc" in t["MigrationType"]:
            _sync(store, t, cdc=True)
    return {"ReplicationTasks": _filters(list(s["tasks"].values()), p, {"replication-task-id": "ReplicationTaskIdentifier",
            "replication-task-arn": "ReplicationTaskArn", "migration-type": "MigrationType", "endpoint-arn": "SourceEndpointArn",
            "replication-instance-arn": "ReplicationInstanceArn"})}


def _tables(store, dbid):
    r = store.execute_sql(dbid, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [x[0] for x in r["rows"]]


def _schema(store, dbid, table):
    r = store.execute_sql(dbid, f'PRAGMA table_info("{table}")')
    return [{"name": c[1], "type": c[2] or "TEXT", "pk": c[5]} for c in r["rows"]]


def _sync(store, task, cdc=False):
    """Full-load (create + copy) or CDC-lite (diff + apply) every selected table. Updates the per-table statistics."""
    s = _st(store)
    src = _by_arn(s["endpoints"], task["SourceEndpointArn"], "Endpoint")
    tgt = _by_arn(s["endpoints"], task["TargetEndpointArn"], "Endpoint")
    sd, td = _resolve_db(store, src), _resolve_db(store, tgt)
    if not sd or not td:
        raise DmsError("InvalidResourceStateFault", "Source or target endpoint no longer resolves to a simulator RDS instance.")
    stats = s["stats"].setdefault(task["ReplicationTaskIdentifier"], {})
    tables = _selected(_rules(task["TableMappings"]), _tables(store, sd[0]))
    ph = store.param_placeholder
    loaded = 0
    for t in tables:
        st = stats.setdefault(t, {"SchemaName": src.get("DatabaseName") or "public", "TableName": t, "Inserts": 0, "Deletes": 0, "Updates": 0,
                                  "Ddls": 0, "FullLoadRows": 0, "TableState": "Table does not exist"})
        cols = _schema(store, sd[0], t)
        names = [c["name"] for c in cols]
        pk = [c["name"] for c in sorted((c for c in cols if c["pk"]), key=lambda c: c["pk"])] or names
        rows = [tuple(r) for r in store.execute_sql(sd[0], f'SELECT {",".join(chr(34)+n+chr(34) for n in names)} FROM "{t}"')["rows"]]
        exists = st["TableState"] != "Table does not exist"
        if not exists:
            ddl = ", ".join(f'"{c["name"]}" {c["type"]}' for c in cols)
            if any(c["pk"] for c in cols):
                ddl += ", PRIMARY KEY (" + ",".join(f'"{k}"' for k in pk) + ")"
            store.execute_sql(td[0], f'CREATE TABLE IF NOT EXISTS "{t}" ({ddl})')
            st["Ddls"] += 1
            store.execute_sql(td[0], f'DELETE FROM "{t}"')
            ins = f'INSERT INTO "{t}" VALUES ({",".join(ph(i + 1) for i in range(len(names)))})'
            for r in rows:
                store.execute_sql(td[0], ins, list(r))
            st["FullLoadRows"] = len(rows)
            st["TableState"] = "Table completed"
            loaded += 1
            continue
        if not cdc:
            continue
        ki = [names.index(k) for k in pk]
        cur = {tuple(r[i] for i in ki): tuple(r) for r in (tuple(x) for x in store.execute_sql(td[0], f'SELECT {",".join(chr(34)+n+chr(34) for n in names)} FROM "{t}"')["rows"])}
        new = {tuple(r[i] for i in ki): r for r in rows}
        where = " AND ".join(f'"{k}" = {ph(i + 1)}' for i, k in enumerate(pk))
        for k in set(cur) - set(new):
            store.execute_sql(td[0], f'DELETE FROM "{t}" WHERE {where}', list(k))
            st["Deletes"] += 1
        for k, r in new.items():
            if k not in cur:
                store.execute_sql(td[0], f'INSERT INTO "{t}" VALUES ({",".join(ph(i + 1) for i in range(len(names)))})', list(r))
                st["Inserts"] += 1
            elif cur[k] != r:
                sets = ", ".join(f'"{n}" = {ph(i + 1)}' for i, n in enumerate(names))
                w2 = " AND ".join(f'"{k2}" = {ph(len(names) + i + 1)}' for i, k2 in enumerate(pk))
                store.execute_sql(td[0], f'UPDATE "{t}" SET {sets} WHERE {w2}', list(r) + list(k))
                st["Updates"] += 1
        st["LastUpdateTime"] = _ts()
    task["ReplicationTaskStats"] = {"FullLoadProgressPercent": 100, "TablesLoaded": len(tables), "TablesLoading": 0, "TablesQueued": 0,
                                    "TablesErrored": 0, "ElapsedTimeMillis": 1}
    return tables


def start_replication_task(store, p):
    s = _st(store)
    _req(p, "ReplicationTaskArn", "StartReplicationTaskType")
    t = _by_arn(s["tasks"], p["ReplicationTaskArn"], "ReplicationTask")
    typ = p["StartReplicationTaskType"]
    if typ not in ("start-replication", "resume-processing", "reload-target"):
        raise DmsError("InvalidParameterValueException", "StartReplicationTaskType must be start-replication, resume-processing or reload-target.")
    if t["Status"] == "running":
        raise DmsError("InvalidResourceStateFault", "The replication task is already running.")
    if typ == "resume-processing" and t["Status"] != "stopped":
        raise DmsError("InvalidResourceStateFault", "resume-processing requires a stopped task.")
    if typ == "reload-target":
        s["stats"][t["ReplicationTaskIdentifier"]] = {}
    try:
        _sync(store, t, cdc=typ == "resume-processing")
    except Exception as e:  # engine / connection failure -> failed task, like DMS
        t["Status"] = "failed"
        t["LastFailureMessage"] = str(getattr(e, "message", e))
        t["StopReason"] = "Stop Reason RECOVERABLE_ERROR"
        return {"ReplicationTask": t}
    t.pop("LastFailureMessage", None)
    t["ReplicationTaskStartDate"] = _ts()
    if t["MigrationType"] == "full-load":
        t["Status"], t["StopReason"] = "stopped", "Stop Reason FULL_LOAD_ONLY_FINISHED"
    else:
        t["Status"] = "running"
        t.pop("StopReason", None)
    return {"ReplicationTask": t}


def stop_replication_task(store, p):
    s = _st(store)
    _req(p, "ReplicationTaskArn")
    t = _by_arn(s["tasks"], p["ReplicationTaskArn"], "ReplicationTask")
    if t["Status"] != "running":
        raise DmsError("InvalidResourceStateFault", f"The replication task is not running (status: {t['Status']}).")
    _sync(store, t, cdc=True)
    t["Status"], t["StopReason"] = "stopped", "Stop Reason NORMAL"
    return {"ReplicationTask": t}


def delete_replication_task(store, p):
    s = _st(store)
    _req(p, "ReplicationTaskArn")
    t = _by_arn(s["tasks"], p["ReplicationTaskArn"], "ReplicationTask")
    if t["Status"] == "running":
        raise DmsError("InvalidResourceStateFault", "The replication task is running; stop it before deleting.")
    del s["tasks"][t["ReplicationTaskIdentifier"]]
    s["stats"].pop(t["ReplicationTaskIdentifier"], None)
    return {"ReplicationTask": dict(t, Status="deleting")}


def describe_table_statistics(store, p):
    s = _st(store)
    _req(p, "ReplicationTaskArn")
    t = _by_arn(s["tasks"], p["ReplicationTaskArn"], "ReplicationTask")
    if t["Status"] == "running" and "cdc" in t["MigrationType"]:
        _sync(store, t, cdc=True)
    return {"ReplicationTaskArn": t["ReplicationTaskArn"], "TableStatistics": list(s["stats"].get(t["ReplicationTaskIdentifier"], {}).values())}


_OPS = {n: globals()[f] for n, f in (
    ("CreateReplicationInstance", "create_replication_instance"), ("DescribeReplicationInstances", "describe_replication_instances"),
    ("DeleteReplicationInstance", "delete_replication_instance"), ("CreateEndpoint", "create_endpoint"),
    ("DescribeEndpoints", "describe_endpoints"), ("DeleteEndpoint", "delete_endpoint"), ("TestConnection", "test_connection"),
    ("DescribeConnections", "describe_connections"), ("CreateReplicationTask", "create_replication_task"),
    ("DescribeReplicationTasks", "describe_replication_tasks"), ("StartReplicationTask", "start_replication_task"),
    ("StopReplicationTask", "stop_replication_task"), ("DeleteReplicationTask", "delete_replication_task"),
    ("DescribeTableStatistics", "describe_table_statistics"))}


def dispatch(store, target: str, payload: dict | None = None):
    action = (target or "").rsplit(".", 1)[-1]
    op = _OPS.get(action)
    hdr = {"x-amzn-requestid": str(uuid.uuid4())}
    if op is None:
        return types.SimpleNamespace(status=400, headers=hdr, body={"__type": "UnknownOperationException", "message": f"The action {action} is not implemented."})
    try:
        return types.SimpleNamespace(status=200, headers=hdr, body=op(store, payload if isinstance(payload, dict) else {}))
    except DmsError as e:
        return types.SimpleNamespace(status=e.status, headers=hdr, body={"__type": e.code, "message": e.message})
