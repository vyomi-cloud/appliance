"""Azure SQL backup / restore / copy / geo-replication / long-term retention (Nano / dev_server / unified-ingress core,
substrate-free). Works on the same ARM state map as ``azure_arm_core`` and the same ``SqlStore`` data plane as
``azure_sql_core`` -- so every operation moves REAL table data.

Database ``createMode`` (validated like the real RP, honoured only at creation):

* ``Copy`` -- a transactionally-consistent copy of ``sourceDatabaseId`` (any server in the subscription) as a new database.
* ``PointInTimeRestore`` -- ``sourceDatabaseId`` + ``restorePointInTime`` (>= the source's earliestRestoreDate, within the
  short-term-retention window, not in the future, target name != source). The point in time is REAL: the data plane keeps a
  base snapshot plus a write-ahead log of every mutating statement the Query editor / data API ran, so PITR restores the latest
  base at or before the instant and replays the log up to it.
* ``Restore`` -- bring back a dropped database from ``restorableDroppedDatabases`` (snapshot taken when the database was
  deleted; the Blob artifact survives the delete).
* ``RestoreLongTermRetentionBackup`` -- restore from an LTR backup (``recoveryServicesRecoveryPointId``).
* ``Secondary`` / ``OnlineSecondary`` -- an active geo-replica on a DIFFERENT server (max 4 per primary). Seeded from the
  primary and kept in sync: every later write on the primary is replayed on the secondary; the secondary is read-only
  (error 3906) until failover or termination.

Sub-resources: ``replicaLinks`` (list/get/``failover``/``forceFailoverAllowDataLoss``/delete = terminate),
``backupShortTermRetentionPolicies/default`` (1-35 days, differential 12|24 h), ``backupLongTermRetentionPolicies/default``
(ISO-8601 weekly/monthly/yearly, weekOfYear), ``geoBackupPolicies/Default``, ``restorableDroppedDatabases`` and
``locations/{loc}/longTermRetention{Servers,Databases}/.../longTermRetentionBackups`` (list/get/delete).

Backup artifacts are SQL-script blobs in the simulator's Blob store (account ``vyomisqlbackup``, container ``sqlbackups``).

NOT modelled (honest limits): the data-plane WAL/base snapshots live in process memory beside the SqlStore (like the
databases themselves) so PITR does not survive an appliance restart, and writes made outside the query/data API (bulk
bacpac import) are not in the log; automatic backups are not scheduled by wall clock -- a base snapshot is taken before a
write when the newest one is older than 10 minutes. Only the first LTR backup is taken (when the policy is set) -- weekly
cadence is not simulated. Geo-replication is synchronous in-process (no replication lag; ``replicationState`` is always
``CATCH_UP`` or ``SEEDING`` reported honestly as CATCH_UP), "regions" are labels. Failover groups, Hyperscale named replicas
and elastic-pool restores are not modelled.
"""
from __future__ import annotations

import datetime
import json
import re
import uuid

SQLDB = "microsoft.sql/servers/databases"
ART_ACCOUNT = "vyomisqlbackup"
ART_CONTAINER = "sqlbackups"
CREATE_MODES = ("Default", "Copy", "PointInTimeRestore", "Restore", "Recovery", "RestoreExternalBackup", "Secondary",
                "OnlineSecondary", "RestoreLongTermRetentionBackup")
NEEDS_SOURCE = ("Copy", "PointInTimeRestore", "Secondary", "OnlineSecondary")
WRITE_RE = re.compile(r"^\s*(insert|update|delete|replace|create|drop|alter)\b", re.IGNORECASE)
BASE_EVERY_S = 600
MAX_REPLICAS = 4
MAX_BASES = 20
MAX_LOG = 5000


def _lazy(name):
    try:
        import importlib
        return importlib.import_module("core." + name)
    except ImportError:
        import importlib
        return importlib.import_module(name)


def _az():
    return _lazy("azure_sql_core")


def _sq():
    return _lazy("sql_store")


def _blob():
    return _lazy("azure_blob_core")


def _now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt=None):
    return (dt or _now_dt()).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(ts):
    try:
        d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles(full_type):
    return (full_type or "").lower() == SQLDB


def is_write(sql):
    return bool(WRITE_RE.match(sql or ""))


def _split(rid):
    parts = [x for x in rid.split("/") if x]
    low = [x.lower() for x in parts]
    return parts[low.index("servers") + 1], parts[low.index("databases") + 1], parts[low.index("resourcegroups") + 1], parts[low.index("subscriptions") + 1]


def _db_rid(sub, rg, server, db):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Sql/servers/{server}/databases/{db}"


# ── Blob artifacts ─────────────────────────────────────────────────────────────────────
def _art_put(blob_store, path, doc):
    data = json.dumps(doc).encode()
    if blob_store is None:
        return {"inline": doc}
    key = f"{ART_ACCOUNT}/{ART_CONTAINER}"
    if not blob_store.container_exists(key):
        blob_store.create_container(key)
    r = _blob().dispatch(blob_store, "PUT", f"/{ART_CONTAINER}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"}, data, account=ART_ACCOUNT)
    if r.status >= 300:
        return {"inline": doc}
    return {"blob": f"https://{ART_ACCOUNT}.blob.core.windows.net/{ART_CONTAINER}/{path}", "path": path}


def _art_get(blob_store, art):
    if "inline" in art:
        return art["inline"]
    if blob_store is None:
        return None
    r = _blob().dispatch(blob_store, "GET", f"/{ART_CONTAINER}/{art['path']}", {}, {}, b"", account=ART_ACCOUNT)
    return json.loads(r.body) if r.status == 200 else None


def _art_del(blob_store, art):
    if blob_store is not None and "blob" in art:
        _blob().dispatch(blob_store, "DELETE", f"/{ART_CONTAINER}/{art['path']}", {}, {}, b"", account=ART_ACCOUNT)


# ── data movement ──────────────────────────────────────────────────────────────────────
def _snapshot_script(sql_store, server, db):
    az, sq = _az(), _sq()
    db_id = az._db_id(server, db)
    if not sql_store.instance_exists(db_id):
        return ""
    if sq.is_async_engine(sql_store):
        raise RuntimeError("This database engine only answers asynchronously; backup/restore needs a synchronous engine.")
    tables = sq.dump_tables(sql_store, db_id)
    return sq.sql_dump(tables, sq.engine_dialect(sql_store), f"Azure SQL backup of {server}/{db}")


def _apply_script(sql_store, server, db, script):
    az, sq = _az(), _sq()
    az._create_database(sql_store, server, db)
    db_id = az._db_id(server, db)
    for stmt in sq.split_sql(script or ""):
        sql_store.execute_sql(db_id, stmt)


def _wal(store):
    st = getattr(store, "_azure_sql_wal", None)
    if st is None:
        st = {"bases": {}, "log": {}}
        store._azure_sql_wal = st
    return st


def pre_write(store, server, db):
    """Called by the data plane BEFORE a mutating statement: keep a base snapshot at most BASE_EVERY_S old."""
    try:
        az = _az()
        db_id = az._db_id(server, db)
        bases = _wal(store)["bases"].setdefault(db_id, [])
        now = _now_dt().timestamp()
        if not bases or now - bases[-1][0] > BASE_EVERY_S:
            bases.append((now, _snapshot_script(store, server, db)))
            del bases[:-MAX_BASES]
    except Exception:  # noqa: BLE001 - backups must never break a query
        pass


def post_write(store, arm_state, server, db, sql, params):
    """After a SUCCESSFUL mutating statement: append to the log and replay it on every geo-secondary."""
    az = _az()
    db_id = az._db_id(server, db)
    log = _wal(store)["log"].setdefault(db_id, [])
    log.append((_now_dt().timestamp(), sql, params))
    del log[:-MAX_LOG]
    rec = az._database_record(arm_state, server, db)
    if not rec:
        return
    pre = rec["id"].lower() + "/replicalinks/"
    for k, link in list((arm_state or {}).items()):
        if k.startswith(pre) and isinstance(link, dict) and link["properties"].get("role") == "Primary":
            try:
                az.execute_sql(store, link["properties"]["partnerServer"], link["properties"]["partnerDatabase"], sql, params)
            except Exception:  # noqa: BLE001
                link["properties"]["replicationState"] = "SUSPENDED"


def is_readonly(arm_state, server, db):
    rec = _az()._database_record(arm_state, server, db)
    return bool(rec) and rec.get("_role") == "Secondary"


def _pitr_script(store, server, db, when, blob_store=None):
    """Script that reproduces the database as of `when` (aware datetime)."""
    az = _az()
    db_id = az._db_id(server, db)
    st = _wal(store)
    bases = st["bases"].get(db_id) or []
    log = st["log"].get(db_id) or []
    t = when.timestamp()
    if not bases:
        return _snapshot_script(store, server, db) if not log else "", []
    pick = None
    for b in bases:
        if b[0] <= t:
            pick = b
    if pick is None:
        pick = bases[0]
    replay = [e for e in log if pick[0] < e[0] <= t]
    return pick[1], replay


def _restore_into(sql_store, server, db, script, replay):
    _apply_script(sql_store, server, db, script)
    az = _az()
    for _ts, sql, params in replay:
        az.execute_sql(sql_store, server, db, sql, params)


# ── database PUT hooks ─────────────────────────────────────────────────────────────────
def _str_days(state, db_rec):
    pol = state.get(db_rec["id"].lower() + "/backupshorttermretentionpolicies/default")
    return (pol or {}).get("properties", {}).get("retentionDays", 7)


def _earliest(state, rec):
    created = _parse((rec.get("systemData") or {}).get("createdAt") or rec.get("_created")) or _now_dt()
    return max(created, _now_dt() - datetime.timedelta(days=_str_days(state, rec)))


def validate(state, full_type, rid, payload, prev, sub, rg, sql_store=None):
    p = (payload or {}).get("properties") or {}
    mode = p.get("createMode")
    if mode is None:
        return None
    if mode not in CREATE_MODES:
        return _err(400, "InvalidCreateMode", f"createMode '{mode}' is not supported. Valid: {', '.join(CREATE_MODES)}.")
    if prev is not None:
        if mode not in ("Default", (prev.get("properties") or {}).get("createMode")):
            return _err(400, "InvalidParameterCombination", "createMode can only be specified when the database is created.")
        return None
    if mode in ("Default", "Recovery", "RestoreExternalBackup"):
        return None
    server, db, _rg, _sub = _split(rid)
    if mode in NEEDS_SOURCE:
        sid = p.get("sourceDatabaseId") or ""
        src = state.get(sid.lower())
        if not sid or src is None or (src.get("_type") or "").lower() != SQLDB:
            return _err(400 if not sid else 404, "InvalidSourceDatabaseId" if not sid else "SourceDatabaseNotFound",
                        "sourceDatabaseId is required." if not sid else f"The source database '{sid}' does not exist.")
        s_server, s_db, _a, s_sub = _split(src["id"])
        if s_sub.lower() != sub.lower():
            return _err(400, "CrossSubscriptionNotSupported", "The source database must be in the same subscription.")
        if s_server.lower() == server.lower() and s_db.lower() == db.lower():
            return _err(400, "InvalidSourceDatabaseId", "A database cannot be its own source.")
        if mode == "PointInTimeRestore":
            if s_server.lower() != server.lower():
                return _err(400, "InvalidRestoreTarget", "A point-in-time restore must target the same server as the source database.")
            when = _parse(p.get("restorePointInTime"))
            if when is None:
                return _err(400, "MissingRestorePointInTime", "restorePointInTime (ISO-8601) is required for PointInTimeRestore.")
            earliest = _earliest(state, src)
            if when > _now_dt() + datetime.timedelta(seconds=1):
                return _err(400, "InvalidRestorePointInTime", f"The restore point {p['restorePointInTime']} is in the future.")
            if when < earliest:
                return _err(400, "InvalidRestorePointInTime", f"The restore point is before the earliest restore date {_iso(earliest)} for database '{s_db}'.")
        if mode in ("Secondary", "OnlineSecondary"):
            if s_server.lower() == server.lower():
                return _err(400, "InvalidSecondaryServer", "The secondary database must be on a different server than the primary.")
            if src.get("_role") == "Secondary":
                return _err(400, "SourceIsSecondary", "The source database is itself a secondary; create the replica from the primary.")
            n = sum(1 for k, v in state.items() if k.startswith(src["id"].lower() + "/replicalinks/") and v["properties"].get("role") == "Primary")
            if n >= MAX_REPLICAS:
                return _err(400, "TooManyReplicas", f"A primary database supports at most {MAX_REPLICAS} geo-secondaries.")
        return None
    if mode == "Restore":
        did = p.get("restorableDroppedDatabaseId") or p.get("sourceDatabaseId") or ""
        d = state.get(did.lower())
        if not did or d is None or not (d.get("type") or "").lower().endswith("restorabledroppeddatabases"):
            return _err(404, "RestorableDroppedDatabaseNotFound", f"restorableDroppedDatabaseId '{did}' does not exist.")
        return None
    if mode == "RestoreLongTermRetentionBackup":
        bid = p.get("recoveryServicesRecoveryPointId") or ""
        b = state.get(_ltr_key(bid))
        if not bid or b is None:
            return _err(404, "LongTermRetentionBackupNotFound", f"recoveryServicesRecoveryPointId '{bid}' does not exist.")
        return None
    return None


def after_put(state, rec, payload, prev, sql_store=None, blob_store=None):
    """Move the data and build link records. Returns an error response or None."""
    p = rec["properties"]
    server, db, rg, sub = _split(rec["id"])
    p.setdefault("earliestRestoreDate", _iso(_earliest(state, rec)))
    p.setdefault("status", "Online")
    mode = ((payload or {}).get("properties") or {}).get("createMode")
    if prev is not None or mode in (None, "Default", "Recovery", "RestoreExternalBackup") or sql_store is None:
        return None
    pp = (payload or {}).get("properties") or {}
    p["createMode"] = mode
    try:
        if mode in ("Copy", "Secondary", "OnlineSecondary", "PointInTimeRestore"):
            src = state[pp["sourceDatabaseId"].lower()]
            s_server, s_db, _a, _b = _split(src["id"])
            p["sourceDatabaseId"] = src["id"]
            if mode == "PointInTimeRestore":
                when = _parse(pp["restorePointInTime"])
                script, replay = _pitr_script(sql_store, s_server, s_db, when, blob_store)
                _restore_into(sql_store, server, db, script, replay)
                p["restorePointInTime"] = _iso(when)
                p["sourceDatabaseDeletionDate"] = None
            else:
                _apply_script(sql_store, server, db, _snapshot_script(sql_store, s_server, s_db))
            if mode in ("Secondary", "OnlineSecondary"):
                _link(state, src, rec)
                p["secondaryType"] = pp.get("secondaryType") or "Geo"
        elif mode == "Restore":
            did = pp.get("restorableDroppedDatabaseId") or pp.get("sourceDatabaseId")
            d = state[did.lower()]
            doc = _art_get(blob_store, d["_artifact"])
            if doc is None:
                raise RuntimeError("The dropped database's backup artifact is missing from the vault storage.")
            when = _parse(pp.get("restorePointInTime"))
            _restore_into(sql_store, server, db, doc["script"], [] if when is None else [e for e in doc.get("log", []) if e[0] <= when.timestamp()])
            p["restorableDroppedDatabaseId"] = d["id"]
        elif mode == "RestoreLongTermRetentionBackup":
            b = state[_ltr_key(pp["recoveryServicesRecoveryPointId"])]
            doc = _art_get(blob_store, b["_artifact"])
            if doc is None:
                raise RuntimeError("The LTR backup artifact is missing.")
            _apply_script(sql_store, server, db, doc["script"])
            p["recoveryServicesRecoveryPointId"] = b["id"]
    except Exception as e:  # noqa: BLE001
        state.pop(rec["id"].lower(), None)
        return _err(500, "RestoreFailed", f"The {mode} operation failed: {e}")
    return None


def _link(state, primary, secondary):
    lid = str(uuid.uuid4())
    ps, pd, _r, _s = _split(primary["id"])
    ss, sd, _r2, _s2 = _split(secondary["id"])
    now = _iso()

    def rec(owner, role, partner, pserver, pdb):
        return {"id": f"{owner['id']}/replicaLinks/{lid}", "name": lid, "type": "Microsoft.Sql/servers/databases/replicaLinks",
                "properties": {"partnerServer": pserver, "partnerDatabase": pdb, "partnerDatabaseId": partner["id"], "partnerLocation": partner.get("location"),
                               "role": role, "partnerRole": "Secondary" if role == "Primary" else "Primary", "replicationMode": "ASYNC",
                               "startTime": now, "percentComplete": 100, "replicationState": "CATCH_UP", "isTerminationAllowed": True, "linkType": "GEO"},
                "_kind": "link"}
    state[f"{primary['id']}/replicaLinks/{lid}".lower()] = rec(primary, "Primary", secondary, ss, sd)
    state[f"{secondary['id']}/replicaLinks/{lid}".lower()] = rec(secondary, "Secondary", primary, ps, pd)
    primary["_role"] = primary.get("_role") or "Primary"
    secondary["_role"] = "Secondary"


def before_delete(state, rec):
    links = [v for k, v in state.items() if k.startswith(rec["id"].lower() + "/replicalinks/") and v["properties"].get("role") == "Primary"]
    if links:
        return _err(409, "DatabaseHasActiveGeoReplicationLinks", f"The database '{rec['name']}' is the primary of {len(links)} active geo-replication link(s). Terminate (delete) the replica links first.")
    return None


def on_delete(state, rec, sql_store=None, blob_store=None):
    """Keep a restorable snapshot of a dropped database, and clean up a dropped secondary's links."""
    server, db, rg, sub = _split(rec["id"])
    for k in [k for k, v in state.items() if k.startswith(rec["id"].lower() + "/replicalinks/") and isinstance(v, dict)]:
        link = state.pop(k)
        other = state.get(link["properties"]["partnerDatabaseId"].lower() + "/replicalinks/" + link["name"].lower())
        if other is not None:
            state.pop(link["properties"]["partnerDatabaseId"].lower() + "/replicalinks/" + link["name"].lower(), None)
            pr = state.get(link["properties"]["partnerDatabaseId"].lower())
            if pr is not None and not any(x.startswith(pr["id"].lower() + "/replicalinks/") for x in state):
                pr["_role"] = None
    if sql_store is None:
        return
    try:
        script = _snapshot_script(sql_store, server, db)
        st = _wal(sql_store)
        db_id = _az()._db_id(server, db)
        log = st["log"].get(db_id, [])
        bases = st["bases"].get(db_id, [])
    except Exception:  # noqa: BLE001
        return
    epoch = int(_now_dt().timestamp())
    name = f"{db},{epoch}"
    srv_rid = rec["id"].split("/databases/")[0]
    art = _art_put(blob_store, f"dropped/{server}/{name}.json", {"script": script, "log": []})
    p = rec.get("properties") or {}
    state[f"{srv_rid}/restorableDroppedDatabases/{name}".lower()] = {
        "id": f"{srv_rid}/restorableDroppedDatabases/{name}", "name": name, "type": "Microsoft.Sql/servers/restorableDroppedDatabases",
        "location": rec.get("location"), "properties": {"databaseName": db, "edition": (rec.get("sku") or {}).get("tier", "Standard"),
                                                         "serviceLevelObjective": (rec.get("sku") or {}).get("name", "S0"), "maxSizeBytes": p.get("maxSizeBytes"),
                                                         "creationDate": (rec.get("systemData") or {}).get("createdAt"), "deletionDate": _iso(),
                                                         "earliestRestoreDate": p.get("earliestRestoreDate"), "backupStorageRedundancy": "Geo"},
        "_artifact": art, "_kind": "dropped"}
    st["bases"].pop(_az()._db_id(server, db), None)
    st["log"].pop(_az()._db_id(server, db), None)


# ── LTR helpers ────────────────────────────────────────────────────────────────────────
def _ltr_key(bid):
    return (bid or "").lower()


def _ltr_id(sub, loc, server, db, name):
    return (f"/subscriptions/{sub}/providers/Microsoft.Sql/locations/{loc}/longTermRetentionServers/{server}/"
            f"longTermRetentionDatabases/{db}/longTermRetentionBackups/{name}")


_ISO_DUR = re.compile(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$")


def _dur_days(s):
    """ISO-8601 duration -> (days, kind) or None when invalid. 'PT0S' / 'P0D' = 0."""
    if s in (None, "", "PT0S"):
        return 0
    m = _ISO_DUR.match(str(s))
    if not m or not any(m.groups()):
        return None
    y, mo, w, d = (int(x or 0) for x in m.groups())
    return y * 365 + mo * 30 + w * 7 + d


def _ltr_policy(state, method, sub, rg, server, db, db_rec, payload, sql_store, blob_store):
    key = f"{db_rec['id']}/backupLongTermRetentionPolicies/default".lower()
    cur = state.get(key)
    if method == "GET":
        if cur is None:
            cur = {"id": f"{db_rec['id']}/backupLongTermRetentionPolicies/default", "name": "default", "type": "Microsoft.Sql/servers/databases/backupLongTermRetentionPolicies",
                   "properties": {"weeklyRetention": "PT0S", "monthlyRetention": "PT0S", "yearlyRetention": "PT0S", "weekOfYear": 0}}
        return _ok(_view(cur))
    if method in ("PUT", "PATCH"):
        p = dict(((cur or {}).get("properties")) or {"weeklyRetention": "PT0S", "monthlyRetention": "PT0S", "yearlyRetention": "PT0S", "weekOfYear": 0})
        p.update((payload or {}).get("properties") or {})
        limits = {"weeklyRetention": 520 * 7, "monthlyRetention": 120 * 30, "yearlyRetention": 10 * 365}
        for k, lim in limits.items():
            d = _dur_days(p.get(k))
            if d is None:
                return _err(400, "InvalidLongTermRetentionPolicy", f"{k} must be an ISO-8601 duration such as P4W, P12M or P5Y (or PT0S).")
            if d > lim:
                return _err(400, "InvalidLongTermRetentionPolicy", f"{k} exceeds the maximum ({'520 weeks' if k[0] == 'w' else '120 months' if k[0] == 'm' else '10 years'}).")
        if _dur_days(p.get("yearlyRetention")) and not 1 <= int(p.get("weekOfYear") or 0) <= 52:
            return _err(400, "InvalidLongTermRetentionPolicy", "weekOfYear (1-52) is required when yearlyRetention is set.")
        rec = {"id": f"{db_rec['id']}/backupLongTermRetentionPolicies/default", "name": "default",
               "type": "Microsoft.Sql/servers/databases/backupLongTermRetentionPolicies", "properties": p}
        state[key] = rec
        if any(_dur_days(p.get(k)) for k in limits):
            _take_ltr(state, sub, server, db, db_rec, p, sql_store, blob_store)
        return _ok(_view(rec))
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _take_ltr(state, sub, server, db, db_rec, pol, sql_store, blob_store):
    if sql_store is None:
        return
    days = max(_dur_days(pol.get(k)) or 0 for k in ("weeklyRetention", "monthlyRetention", "yearlyRetention"))
    name = str(uuid.uuid4())
    art = _art_put(blob_store, f"ltr/{server}/{db}/{name}.json", {"script": _snapshot_script(sql_store, server, db)})
    loc = (db_rec.get("location") or "eastus").lower().replace(" ", "")
    bid = _ltr_id(sub, loc, server, db, name)
    srv_rec = state.get(db_rec["id"].split("/databases/")[0].lower()) or {}
    state[bid.lower()] = {"id": bid, "name": name, "type": "Microsoft.Sql/locations/longTermRetentionServers/longTermRetentionDatabases/longTermRetentionBackups",
                          "properties": {"serverName": server, "serverCreateTime": (srv_rec.get("systemData") or {}).get("createdAt"), "databaseName": db,
                                         "databaseDeletionTime": None, "backupTime": _iso(), "backupExpirationTime": _iso(_now_dt() + datetime.timedelta(days=days)),
                                         "backupStorageRedundancy": "Geo", "requestedBackupStorageRedundancy": "Geo"},
                          "_artifact": art, "_kind": "ltr", "_srv": server.lower(), "_db": db.lower(), "_loc": loc}


def _ltr_dispatch(state, method, sub, chain, blob_store):
    """chain after 'locations': {loc}/longTermRetentionServers/{s}[/longTermRetentionDatabases/{d}]/longTermRetentionBackups[/{n}]"""
    loc = chain[0].lower().replace(" ", "")
    low = [c.lower() for c in chain]
    rows = [b for b in state.values() if isinstance(b, dict) and b.get("_kind") == "ltr" and b["_loc"] == loc and b["id"].lower().startswith(f"/subscriptions/{sub}/".lower())]
    srv = db = None
    i = 1
    if len(chain) > i + 1 and low[i] == "longtermretentionservers":
        srv = low[i + 1]
        i += 2
    if len(chain) > i + 1 and low[i] == "longtermretentiondatabases":
        db = low[i + 1]
        i += 2
    if len(chain) <= i or low[i] != "longtermretentionbackups":
        return _err(404, "ResourceNotFound", "Unknown long-term retention path.")
    if srv:
        rows = [b for b in rows if b["_srv"] == srv]
    if db:
        rows = [b for b in rows if b["_db"] == db]
    if len(chain) == i + 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_view(b) for b in sorted(rows, key=lambda b: b["properties"]["backupTime"], reverse=True)]})
    name = chain[i + 1]
    b = next((b for b in rows if b["name"].lower() == name.lower()), None)
    if method == "GET":
        return _ok(_view(b)) if b else _err(404, "LongTermRetentionBackupNotFound", f"The long term retention backup '{name}' was not found.")
    if method == "DELETE":
        if b is None:
            return {"status": 204, "body": None}
        _art_del(blob_store, b["_artifact"])
        state.pop(b["id"].lower(), None)
        return _ok(None)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── sub-resource dispatch ──────────────────────────────────────────────────────────────
_DB_SUBS = ("replicalinks", "replicationlinks", "backupshorttermretentionpolicies", "backuplongtermretentionpolicies", "geobackuppolicies")


def owns(chain):
    low = [c.lower() for c in chain]
    if low[:1] == ["locations"] and len(low) >= 3 and low[2].startswith("longtermretention"):
        return True
    if low[:1] == ["servers"] and len(low) >= 5 and low[2] == "databases" and low[4] in _DB_SUBS:
        return True
    return low[:1] == ["servers"] and len(low) >= 3 and low[2] == "restorabledroppeddatabases"


def dispatch(state, method, sub, rg, chain, payload, query, sql_store=None, blob_store=None):
    low = [c.lower() for c in chain]
    if low[0] == "locations":
        return _ltr_dispatch(state, method, sub, chain[1:], blob_store) if len(chain) >= 3 else _err(404, "ResourceNotFound", "Unknown path.")
    if rg is None:
        return _err(400, "InvalidRequest", "A resource group is required.")
    server = chain[1]
    srv_rid = f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Sql/servers/{server}"
    if state.get(srv_rid.lower()) is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Sql/servers/{server}' under resource group '{rg}' was not found.")
    if low[2] == "restorabledroppeddatabases":
        pre = srv_rid.lower() + "/restorabledroppeddatabases/"
        rows = [r for k, r in state.items() if isinstance(r, dict) and k.startswith(pre) and "/" not in k[len(pre):]]
        if len(chain) == 3:
            return _ok({"value": [_view(r) for r in rows]})
        r = state.get(f"{srv_rid}/restorableDroppedDatabases/{chain[3]}".lower())
        return _ok(_view(r)) if r else _err(404, "ResourceNotFound", f"The restorable dropped database '{chain[3]}' was not found.")
    db = chain[3]
    db_rec = state.get(_db_rid(sub, rg, server, db).lower())
    if db_rec is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Sql/servers/{server}/databases/{db}' under resource group '{rg}' was not found.")
    k = low[4]
    rest = chain[5:]
    if k == "backuplongtermretentionpolicies":
        return _ltr_policy(state, method, sub, rg, server, db, db_rec, payload, sql_store, blob_store)
    if k == "backupshorttermretentionpolicies":
        key = f"{db_rec['id']}/backupShortTermRetentionPolicies/default".lower()
        cur = state.get(key) or {"id": f"{db_rec['id']}/backupShortTermRetentionPolicies/default", "name": "default",
                                 "type": "Microsoft.Sql/servers/databases/backupShortTermRetentionPolicies",
                                 "properties": {"retentionDays": 7, "diffBackupIntervalInHours": 12}}
        if method == "GET":
            return _ok(_view(cur))
        if method in ("PUT", "PATCH"):
            p = dict(cur["properties"])
            p.update((payload or {}).get("properties") or {})
            if not isinstance(p["retentionDays"], int) or not 1 <= p["retentionDays"] <= 35:
                return _err(400, "InvalidBackupRetention", "retentionDays must be between 1 and 35.")
            if p.get("diffBackupIntervalInHours") not in (12, 24):
                return _err(400, "InvalidBackupRetention", "diffBackupIntervalInHours must be 12 or 24.")
            cur = dict(cur, properties=p)
            state[key] = cur
            db_rec["properties"]["earliestRestoreDate"] = _iso(_earliest(state, db_rec))
            return _ok(_view(cur))
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if k == "geobackuppolicies":
        key = f"{db_rec['id']}/geoBackupPolicies/Default".lower()
        cur = state.get(key) or {"id": f"{db_rec['id']}/geoBackupPolicies/Default", "name": "Default", "type": "Microsoft.Sql/servers/databases/geoBackupPolicies",
                                 "kind": "geo", "location": db_rec.get("location"), "properties": {"state": "Enabled", "storageType": "Geo"}}
        if method == "GET":
            return _ok({"value": [_view(cur)]} if len(chain) == 5 else _view(cur))
        if method in ("PUT", "PATCH"):
            st = ((payload or {}).get("properties") or {}).get("state")
            if st not in ("Enabled", "Disabled"):
                return _err(400, "InvalidParameterValue", "properties.state must be Enabled or Disabled.")
            cur = dict(cur, properties=dict(cur["properties"], state=st))
            state[key] = cur
            return _ok(_view(cur))
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    # replica links
    pre = db_rec["id"].lower() + "/replicalinks/"
    links = [v for kk, v in state.items() if kk.startswith(pre) and isinstance(v, dict)]
    if not rest:
        return _ok({"value": [_view(v) for v in links]}) if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
    link = next((v for v in links if v["name"].lower() == rest[0].lower()), None)
    if link is None:
        return {"status": 204, "body": None} if method == "DELETE" else _err(404, "ResourceNotFound", f"The replica link '{rest[0]}' was not found.")
    if len(rest) == 1:
        if method == "GET":
            return _ok(_view(link))
        if method == "DELETE":
            partner = state.get(link["properties"]["partnerDatabaseId"].lower())
            state.pop(link["id"].lower(), None)
            state.pop(f"{link['properties']['partnerDatabaseId']}/replicaLinks/{link['name']}".lower(), None)
            for r in (db_rec, partner):
                if r is not None:
                    r["_role"] = "Primary" if any(x.startswith(r["id"].lower() + "/replicalinks/") for x in state) and r.get("_role") == "Primary" else None
            return _ok(None)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    act = rest[1].lower()
    if method == "POST" and act in ("failover", "forcefailoverallowdataloss"):
        if link["properties"]["role"] != "Secondary":
            return _err(400, "FailoverNotAllowed", "Failover must be issued against the secondary database's replica link.")
        partner = state.get(link["properties"]["partnerDatabaseId"].lower())
        plink = state.get(f"{link['properties']['partnerDatabaseId']}/replicaLinks/{link['name']}".lower())
        if partner is None or plink is None:
            return _err(409, "ReplicaLinkBroken", "The partner database no longer exists.")
        if sum(1 for kk, v in state.items() if kk.startswith(partner["id"].lower() + "/replicalinks/") and v["properties"].get("role") == "Primary") > 1:
            return _err(400, "FailoverNotAllowed", "The primary has other geo-secondaries; terminate them before failing over (Vyomi re-points a single replica link only).")
        link["properties"].update(role="Primary", partnerRole="Secondary")
        plink["properties"].update(role="Secondary", partnerRole="Primary")
        db_rec["_role"], partner["_role"] = "Primary", "Secondary"
        # siblings: other secondaries of the old primary are re-pointed to the new primary
        return _ok(None, 200)
    return _err(404, "ResourceNotFound", f"Unknown replica link action '{rest[1]}'.")
