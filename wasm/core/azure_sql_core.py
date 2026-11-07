# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure SQL data-plane core — the Azure peer of AWS RDS + GCP Cloud SQL, closing
the cross-cloud relational-symmetry gap (PARITY P3 #13). Azure SQL had only an ARM
control-plane catalog and no data plane; this gives it a real one on the SAME
`SqlStore` seam the RDS/Cloud SQL cores use (stdlib sqlite3 in Nano; real Postgres
behind the seam in Pro/Max) — so `CREATE TABLE` / `INSERT` / `SELECT` actually run.

Azure SQL's native SDK speaks TDS (which can't traverse the HTTP relay), so this
core exposes the relational surface over a small REST/JSON wire — logical server +
database management and a `.../query` execute endpoint returning
`{columns, rows, rowCount}`. NO fastapi / pyodbc / socket imports → loads under
Pyodide. Databases live in the SqlStore keyed `azuresql:{server}/{database}`.

Scope (v1 slice): create/list/delete server + database, execute SQL (sync + async).
Elastic pools, geo-replication and the TDS wire slot in later.

DEPTH PASS (v2.7.0): the ARM control plane's `publicNetworkAccess` (server) and
`maxSizeBytes` (database) properties now actually constrain this data plane — the
same pattern `azure_blob_core.py` uses for CORS/lifecycle (`aws_wire_router.py`
passes the ARM core's `state` dict as `arm_state=`, read-only, never written back).
A real "Performance recommendations" engine also lives here: it watches the Query
editor's own statement log, detects WHERE-equality lookups that need a table scan
(via the SAME engine's `EXPLAIN QUERY PLAN`, not a guess) and proposes/creates
indexes — applied on request, or automatically when the database's
`automaticTuning.options.createIndex` is "On" (mirroring the real feature's name).

DEPTH PASS (wave 5): transparent data encryption's customer-managed key (BYOK)
protector now takes real effect. When a database's `transparentDataEncryption`
points at a Key Vault key (`keyVaultKeyUri`), the query data plane requires BOTH
a system-assigned managed identity on the database (the real precondition Azure
enforces before trusting a CMK protector) AND an enabled key in Key Vault — same
read-only-snapshot pattern, `aws_wire_router.py` also passes the Key Vault keys
core's store as `kv_store=`. Revoke the identity or disable the key and the
database goes the same "protector unavailable" route real Azure SQL does.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from core import azure_keyvault_keys_core as kv_keys
from core import azure_sql_ext_core as _ext
from core import azure_netaccess as _netaccess
from core.sql_store import SqlStore


@dataclass
class AzureSqlResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj: dict) -> AzureSqlResponse:
    return AzureSqlResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> AzureSqlResponse:
    return AzureSqlResponse(status=status, body=json.dumps({"error": {"code": code, "message": message}}).encode())


def _servers(store: SqlStore) -> dict:
    m = getattr(store, "_azure_sql_servers", None)
    if m is None:
        m = {}
        store._azure_sql_servers = m
    return m


def _db_id(server: str, database: str) -> str:
    return f"azuresql:{server}/{database}"


# ── ARM config lookup (publicNetworkAccess / maxSizeBytes / automaticTuning) ───────────
# Same read-only-snapshot pattern as azure_blob_core._arm_properties: the ARM core's
# `state` dict is keyed by lower-cased resource id with a `_type` discriminator, so a
# type + id-suffix match finds the server/database record without needing the
# subscription/resource-group this data plane never learns.
def _arm_record(arm_state: dict | None, full_type: str, id_suffix: str) -> dict | None:
    if not arm_state:
        return None
    want_id = f"/{id_suffix}".lower()
    for rec in arm_state.values():
        if rec.get("_type", "").lower() == full_type and rec.get("id", "").lower().endswith(want_id):
            return rec
    return None


def _server_props(arm_state: dict | None, server: str) -> dict:
    rec = _arm_record(arm_state, "microsoft.sql/servers", f"servers/{server}")
    return (rec or {}).get("properties", {}) or {}


def _database_props(arm_state: dict | None, server: str, database: str) -> dict:
    rec = _arm_record(arm_state, "microsoft.sql/servers/databases", f"servers/{server}/databases/{database}")
    return (rec or {}).get("properties", {}) or {}


def _database_record(arm_state: dict | None, server: str, database: str) -> dict:
    return _arm_record(arm_state, "microsoft.sql/servers/databases", f"servers/{server}/databases/{database}") or {}


def _parse_kv_key_uri(uri: str) -> tuple[str, str | None]:
    """'https://vault.vault.azure.net/keys/{name}[/{version}]' -> (name, version|None)."""
    parts = [p for p in str(uri or "").split("/") if p]
    try:
        i = parts.index("keys")
    except ValueError:
        return uri, None
    name = parts[i + 1] if len(parts) > i + 1 else uri
    version = parts[i + 2] if len(parts) > i + 2 else None
    return name, version


def _tde_protector_error(arm_state: dict | None, kv_store, server: str, database: str) -> AzureSqlResponse | None:
    """Customer-managed-key TDE (BYOK): a Key Vault-backed protector requires the database's
    OWN system-assigned managed identity (real Azure precondition) and a real, enabled key —
    both checked at connection time, same as the networking/size gates above. Service-managed
    keys (the default; no keyVaultKeyUri) and TDE turned Off are always available."""
    rec = _database_record(arm_state, server, database)
    tde = (rec.get("properties") or {}).get("transparentDataEncryption") or {}
    if tde.get("state") == "Disabled":
        return None
    key_uri = tde.get("keyVaultKeyUri")
    if not key_uri:
        return None
    identity = rec.get("identity") or {}
    if identity.get("type") != "SystemAssigned" or not identity.get("principalId"):
        return _err(403, "TdeProtectorUnavailable",
                    f"Database '{database}' uses a customer-managed Key Vault key for its "
                    "transparent data encryption protector, which requires a system-assigned "
                    "managed identity; none is configured, so the protector is unavailable.")
    if kv_store is None:
        return None
    name, version = _parse_kv_key_uri(key_uri)
    status = kv_keys.key_enabled(kv_store, name, version)
    if status is False:
        return _err(403, "TdeProtectorUnavailable",
                    f"The Key Vault key protecting database '{database}' with transparent "
                    "data encryption is disabled; the database is inaccessible until the key "
                    "is re-enabled or the protector is switched back to service-managed.")
    if status is None:
        return _err(403, "TdeProtectorUnavailable",
                    f"The Key Vault key configured as database '{database}'s transparent data "
                    "encryption protector was not found.")
    return None


# ── control plane ───────────────────────────────────────────────────────────
def _create_server(store: SqlStore, server: str) -> AzureSqlResponse:
    _servers(store).setdefault(server, {"name": server, "databases": []})
    return _json(201, {"name": server, "type": "Microsoft.Sql/servers",
                       "properties": {"state": "Ready"}})


def _create_database(store: SqlStore, server: str, database: str) -> AzureSqlResponse:
    srv = _servers(store).setdefault(server, {"name": server, "databases": []})
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        store.put_instance(db_id, {
            "db_instance_identifier": db_id, "engine": "sqlserver",
            "db_instance_status": "available", "server": server, "database": database})
        if database not in srv["databases"]:
            srv["databases"].append(database)
    return _json(201, {"name": database, "type": "Microsoft.Sql/servers/databases",
                       "properties": {"status": "Online"}})


def _list_databases(store: SqlStore, server: str) -> AzureSqlResponse:
    srv = _servers(store).get(server)
    if srv is None:
        return _err(404, "ResourceNotFound", f"Server '{server}' was not found.")
    return _json(200, {"value": [{"name": d, "properties": {"status": "Online"}}
                                 for d in srv["databases"]]})


def _delete_database(store: SqlStore, server: str, database: str) -> AzureSqlResponse:
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
    store.db_instances.pop(db_id, None)
    srv = _servers(store).get(server)
    if srv and database in srv["databases"]:
        srv["databases"].remove(database)
    return _json(200, {})


# ── data plane ──────────────────────────────────────────────────────────────
# ── Measured query telemetry (Query Performance Insight / Performance overview / auditing) ─────────
# Every statement run through the data plane is timed with perf_counter around the real engine call and
# appended to a per-database ring on the store. Nothing here is estimated; no statements -> empty views.
QLOG_CAP = 2000
_NUM_RE = re.compile(r"\b\d+(\.\d+)?\b")
_STR_RE = re.compile(r"'(?:[^']|'')*'")


def _qrings(store: SqlStore) -> dict:
    m = getattr(store, "_azure_sql_qtimings", None)
    if m is None:
        m = {}
        store._azure_sql_qtimings = m
    return m


def _record_timing(store, server, database, sql, t0, ok, rows, error=None) -> None:
    ms = round((time.perf_counter() - t0) * 1000.0, 3)
    ring = _qrings(store).setdefault(_db_id(server, database), [])
    norm = " ".join(_NUM_RE.sub("?", _STR_RE.sub("?", sql)).split())
    ring.append({"ts": time.time(), "sql": sql[:500], "queryText": norm[:500], "queryId": hashlib.sha1(norm.lower().encode()).hexdigest()[:12],
                 "ms": ms, "ok": bool(ok), "rows": int(rows or 0), "error": error})
    if len(ring) > QLOG_CAP:
        del ring[: len(ring) - QLOG_CAP]


def query_insights(store: SqlStore, server: str, database: str, window_s: float = 86400.0, now: float | None = None) -> dict:
    """QPI / performance overview / audit view of the MEASURED statement timings for one database."""
    now = now if now is not None else time.time()
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return None
    ring = [r for r in _qrings(store).get(db_id, []) if r["ts"] >= now - window_s]
    groups: dict = {}
    for r in ring:
        g = groups.setdefault(r["queryId"], {"queryId": r["queryId"], "queryText": r["queryText"], "executions": 0, "failures": 0,
                                             "totalMs": 0.0, "maxMs": 0.0, "rows": 0, "lat": []})
        g["executions"] += 1
        g["failures"] += 0 if r["ok"] else 1
        g["totalMs"] += r["ms"]
        g["maxMs"] = max(g["maxMs"], r["ms"])
        g["rows"] += r["rows"]
        g["lat"].append(r["ms"])
    top = []
    for g in groups.values():
        lat = sorted(g.pop("lat"))
        g["avgMs"] = round(g["totalMs"] / g["executions"], 3)
        g["p95Ms"] = lat[min(len(lat) - 1, int(0.95 * len(lat)))]
        g["totalMs"] = round(g["totalMs"], 3)
        top.append(g)
    top.sort(key=lambda g: g["totalMs"], reverse=True)
    lats = sorted(r["ms"] for r in ring)
    step = 60.0 if window_s <= 7200 else 3600.0
    tl: dict = {}
    for r in ring:
        b = tl.setdefault(int(r["ts"] // step) * step, {"ts": int(r["ts"] // step) * step, "count": 0, "errors": 0, "totalMs": 0.0})
        b["count"] += 1
        b["errors"] += 0 if r["ok"] else 1
        b["totalMs"] += r["ms"]
    timeline = [{**b, "avgMs": round(b["totalMs"] / b["count"], 3)} for b in sorted(tl.values(), key=lambda x: x["ts"])]
    return {"database": database, "server": server, "windowSeconds": window_s,
            "overview": {"statements": len(ring), "failed": sum(1 for r in ring if not r["ok"]),
                         "p50Ms": lats[len(lats) // 2] if lats else 0, "p95Ms": lats[min(len(lats) - 1, int(0.95 * len(lats)))] if lats else 0,
                         "maxMs": lats[-1] if lats else 0, "totalMs": round(sum(lats), 3), "sizeBytes": _db_size_bytes(store, db_id)},
            "topQueries": top[:25], "timeline": timeline,
            "audit": [{"eventTime": r["ts"], "actionName": "BATCH COMPLETED", "succeeded": r["ok"], "statement": r["sql"],
                       "durationMs": r["ms"], "rowCount": r["rows"], "errorMessage": r["error"]} for r in reversed(ring[-200:])]}


def execute_sql(store: SqlStore, server: str, database: str, sql: str,
                params: list | None = None) -> dict:
    """Run real SQL against the database's engine (sqlite3 in Nano; Postgres behind
    the seam in Pro/Max). Returns {ok, columns, rows, rowCount} or {ok: False}."""
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return {"ok": False, "code": "DatabaseNotFound",
                "message": f"Database {server}/{database} not found."}
    t0 = time.perf_counter()
    try:
        result = store.execute_sql(db_id, sql, params)
        _record_timing(store, server, database, sql, t0, True, result.get("rowcount", 0))
        return {"ok": True, "columns": result.get("columns", []),
                "rows": result.get("rows", []), "rowCount": result.get("rowcount", 0)}
    except Exception as e:
        _record_timing(store, server, database, sql, t0, False, 0, str(e))
        return {"ok": False, "code": "SQLError", "message": str(e)}


async def aexecute_sql(store: SqlStore, server: str, database: str, sql: str,
                       params: list | None = None) -> dict:
    """Async twin — awaits the engine so an async data-plane (PGlite/Postgres) can
    back Azure SQL in the browser; sync engines work unchanged."""
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return {"ok": False, "code": "DatabaseNotFound",
                "message": f"Database {server}/{database} not found."}
    t0 = time.perf_counter()
    try:
        result = await store.aexecute_sql(db_id, sql, params)
        _record_timing(store, server, database, sql, t0, True, result.get("rowcount", 0))
        return {"ok": True, "columns": result.get("columns", []),
                "rows": result.get("rows", []), "rowCount": result.get("rowcount", 0)}
    except Exception as e:
        _record_timing(store, server, database, sql, t0, False, 0, str(e))
        return {"ok": False, "code": "SQLError", "message": str(e)}


_WRITE_SQL_RE = re.compile(r"^\s*(insert|update|replace)\b", re.IGNORECASE)


def _db_size_bytes(store: SqlStore, db_id: str) -> int:
    """The database's current on-disk size, from the engine's OWN page accounting
    (sqlite `PRAGMA page_count` * `page_size`) — not an estimate."""
    try:
        pages = store.execute_sql(db_id, "PRAGMA page_count")["rows"][0][0]
        size = store.execute_sql(db_id, "PRAGMA page_size")["rows"][0][0]
        return int(pages) * int(size)
    except Exception:
        return 0


def _query(store: SqlStore, server: str, database: str, body: bytes,
          arm_state: dict | None = None, kv_store=None, headers: dict | None = None) -> AzureSqlResponse:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    sql = str(payload.get("sql") or payload.get("query") or "")
    if not sql:
        return _err(400, "BadRequest", "A 'sql' statement is required.")

    _na_ctx = _netaccess.caller_context(headers)
    _na_rec = _netaccess.find_arm(arm_state, "microsoft.sql/servers", f"servers/{server}") if _na_ctx else None
    if _na_rec is not None:
        # caller declared a network identity (x-vyomi-source-*): firewall / vnet rules / private endpoint are enforced
        _denied = _netaccess.check(arm_state, _na_rec["id"], "sql", _na_rec.get("properties") or {}, _na_ctx)
        if _denied:
            return _err(_denied[0], _denied[1], f"Cannot connect to server '{server}.database.windows.net': {_denied[2]}")
    elif _server_props(arm_state, server).get("publicNetworkAccess") == "Disabled":
        return _err(403, "PublicNetworkAccessDisabled",
                    f"Cannot connect to server '{server}.database.windows.net': "
                    "public network access is disabled.")

    tde_err = _tde_protector_error(arm_state, kv_store, server, database)
    if tde_err is not None:
        return tde_err

    db_id = _db_id(server, database)
    from core import azure_sqlbackup_core as sqlbk
    is_w = sqlbk.is_write(sql)
    if is_w and sqlbk.is_readonly(arm_state, server, database):
        return _err(400, "DatabaseReadOnly", f"Failed to update database '{database}' because the database is read-only "
                    "(error 3906): it is a geo-secondary. Fail over or terminate the replica link first.")
    if is_w:
        sqlbk.pre_write(store, server, database)
    if _WRITE_SQL_RE.match(sql) and store.instance_exists(db_id):
        max_size = _database_props(arm_state, server, database).get("maxSizeBytes")
        if max_size and _db_size_bytes(store, db_id) >= int(max_size):
            return _err(400, "DatabaseSizeQuotaExceeded",
                        f"The database '{database}' has reached its configured maximum "
                        f"size of {int(max_size)} bytes (Error 40544). Partition or delete "
                        "data, drop indexes, or increase the maximum size.")

    result = execute_sql(store, server, database, sql, payload.get("params"))
    if not result.get("ok"):
        return _err(400, result.get("code", "SQLError"), result.get("message", ""))

    if is_w:
        sqlbk.post_write(store, arm_state, server, database, sql, payload.get("params"))
    _log_select(store, db_id, sql)
    _auto_tune(store, arm_state, server, database)
    return _json(200, {"columns": result["columns"], "rows": result["rows"],
                       "rowCount": result["rowCount"],
                       "connection": _connection_route(arm_state, server, _na_ctx)})


def _connection_route(arm_state: dict | None, server: str, ctx: dict | None) -> dict:
    """azure.sql.connectivity: how the declared caller reaches the server under connectionPolicies/default. Default = Redirect for a
    caller INSIDE Azure (declared subnet / private endpoint / trusted service) and Proxy from outside; Proxy always goes through
    the gateway on 1433; Redirect goes to the node port range 11000-11999 after the gateway login."""
    srv = _netaccess.find_arm(arm_state, "microsoft.sql/servers", f"servers/{server}")
    pol = "Default"
    if srv:
        rec = (arm_state or {}).get((srv["id"] + "/connectionPolicies/default").lower())
        pol = ((rec or {}).get("properties") or {}).get("connectionType") or "Default"
    ctx = ctx or {}
    inside = bool(ctx.get("source_subnet") or ctx.get("private_endpoint") or ctx.get("trusted_service"))
    mode = "Redirect" if pol == "Redirect" or (pol == "Default" and inside) else "Proxy"
    host = f"{server}.database.windows.net"
    return {"policy": pol, "mode": mode, "endpoint": f"{host}:{'11000' if mode == 'Redirect' else '1433'}", "callerInsideAzure": inside}


# ── Performance recommendations (CREATE_INDEX, real EXPLAIN-QUERY-PLAN driven) ─────────
# A rolling log of SELECTs the Query editor has actually run, kept on the store (same
# home as the server/database catalog) so recommendations survive across requests.
_EQ_WHERE_RE = re.compile(r"\bfrom\s+([A-Za-z_]\w*)\b.*?\bwhere\b.*?\b([A-Za-z_]\w*)\s*=",
                          re.IGNORECASE | re.DOTALL)


def _query_log(store: SqlStore, db_id: str) -> list:
    m = getattr(store, "_azure_sql_query_log", None)
    if m is None:
        m = {}
        store._azure_sql_query_log = m
    return m.setdefault(db_id, [])


def _applied_recs(store: SqlStore, db_id: str) -> set:
    m = getattr(store, "_azure_sql_applied_recs", None)
    if m is None:
        m = {}
        store._azure_sql_applied_recs = m
    return m.setdefault(db_id, set())


def _log_select(store: SqlStore, db_id: str, sql: str) -> None:
    if not sql.strip().lower().startswith("select"):
        return
    log = _query_log(store, db_id)
    log.append(sql)
    del log[:-200]   # cap the log — only recent activity drives a recommendation


def _needs_table_scan(store: SqlStore, db_id: str, table: str, column: str) -> bool:
    """Ask the engine's REAL query planner whether `WHERE {column} = ?` on {table}
    currently needs a full scan — the same signal Azure's Query Store/DTA use, just
    read straight off sqlite's EXPLAIN QUERY PLAN instead of reimplementing it."""
    try:
        plan = store.execute_sql(db_id, f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE {column} = ?", [None])
    except Exception:
        return False
    for row in plan.get("rows", []):
        detail = str(row[-1] if row else "").upper()
        if detail.startswith("SCAN") and "USING INDEX" not in detail:
            return True
    return False


def _candidate_recommendations(store: SqlStore, db_id: str) -> list[dict]:
    counts: dict[tuple, int] = {}
    for sql in _query_log(store, db_id):
        m = _EQ_WHERE_RE.search(sql)
        if not m:
            continue
        key = (m.group(1), m.group(2))
        counts[key] = counts.get(key, 0) + 1
    applied = _applied_recs(store, db_id)
    recs = []
    for (table, column), count in counts.items():
        if count < 3:
            continue
        # "." not ":" — it survives encodeURIComponent() unescaped (the dev server/relay
        # never percent-decodes the path before splitting it on "/", so an escaped ":"
        # — %3A — would never match this plain id again).
        rec_id = f"{table}.{column}"
        if rec_id in applied or not _needs_table_scan(store, db_id, table, column):
            continue
        recs.append({"id": rec_id, "action": "CREATE_INDEX", "table": table, "column": column,
                     "script": f"CREATE INDEX ix_{table}_{column} ON {table}({column})",
                     "impactedQueries": count})
    recs.sort(key=lambda r: -r["impactedQueries"])
    return recs


def _apply_recommendation(store: SqlStore, db_id: str, rec_id: str) -> tuple[bool, str | None]:
    recs = {r["id"]: r for r in _candidate_recommendations(store, db_id)}
    rec = recs.get(rec_id)
    if rec is None:
        return False, "This recommendation no longer applies (it may already be indexed)."
    try:
        store.execute_sql(db_id, rec["script"])
    except Exception as e:
        return False, str(e)
    _applied_recs(store, db_id).add(rec_id)
    return True, None


def _auto_tune(store: SqlStore, arm_state: dict | None, server: str, database: str) -> None:
    """Automatic tuning > CREATE INDEX = On: apply every current candidate immediately,
    the same "automatic" promise the real feature makes. FORCE_LAST_GOOD_PLAN and
    DROP_INDEX stay config-only — no plan-regression detection or orphan-index pruning
    is modelled here."""
    opts = (_database_props(arm_state, server, database).get("automaticTuning") or {}).get("options") or {}
    if (opts.get("createIndex") or {}).get("desiredState") != "On":
        return
    db_id = _db_id(server, database)
    for rec in _candidate_recommendations(store, db_id):
        _apply_recommendation(store, db_id, rec["id"])


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: SqlStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", arm_state: dict | None = None, kv_store=None) -> AzureSqlResponse:
    """Native-ish Azure SQL REST wire:
        PUT    /servers/{server}                                   create server
        PUT    /servers/{server}/databases/{db}                     create database
        GET    /servers/{server}/databases                          list databases
        DELETE /servers/{server}/databases/{db}                     delete database
        POST   /servers/{server}/databases/{db}/query               execute SQL
        GET    /servers/{server}/databases/{db}/recommendations     tuning recommendations
        POST   /servers/{server}/databases/{db}/recommendations/{id}/apply   apply one

    `arm_state` is the Azure ARM core's resource map (read-only snapshot, same
    contract as azure_blob_core's CORS/lifecycle lookup) — it is how publicNetworkAccess,
    maxSizeBytes, automaticTuning and the TDE protector's identity/key reference reach
    this data plane. `kv_store` is the Key Vault keys core's store (same contract) — it
    is how a customer-managed TDE protector's enabled/disabled state reaches this data
    plane.
    """
    method = (method or "GET").upper()
    segs = [s for s in path.split("?", 1)[0].split("/") if s != ""]
    if len(segs) < 2 or segs[0] != "servers":
        return _err(404, "NotFound", f"Unknown path: {path}")
    server = segs[1]

    if len(segs) == 2:
        if method == "PUT":
            return _create_server(store, server)
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on server")

    if segs[2] == "databases":
        if len(segs) == 3:
            if method == "GET":
                return _list_databases(store, server)
            return _err(405, "MethodNotAllowed", f"Unsupported method {method} on databases")
        database = segs[3]
        if len(segs) == 4:
            if method == "PUT":
                return _create_database(store, server, database)
            if method == "DELETE":
                return _delete_database(store, server, database)
            return _err(405, "MethodNotAllowed", f"Unsupported method {method} on database")
        if len(segs) == 5 and segs[4] == "query" and method == "POST":
            return _query(store, server, database, body, arm_state, kv_store, headers)
        if len(segs) == 5 and segs[4] == "queryinsights" and method == "GET":
            try:
                w = float((query or {}).get("window") or 86400)
            except ValueError:
                w = 86400.0
            out = query_insights(store, server, database, w)
            if out is None:
                return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
            return _json(200, out)
        db_id0 = _db_id(server, database)
        if len(segs) >= 5 and segs[4] in ("watcher", "sync"):
            if not store.instance_exists(db_id0):
                return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
            try:
                if segs[4] == "watcher" and len(segs) == 6 and segs[5] == "collect" and method == "POST":
                    return _json(200, _ext.collect(store, db_id0, _qrings(store), _db_size_bytes))
                if segs[4] == "watcher" and len(segs) == 5 and method == "GET":
                    return _json(200, _ext.watch(store, db_id0))
                if segs[4] == "sync" and len(segs) == 5 and method == "GET":
                    return _json(200, {"syncs": _ext.sync_history(store, db_id0)})
                if segs[4] == "sync" and len(segs) == 5 and method == "POST":
                    b = json.loads(body.decode("utf-8")) if body else {}
                    member = _db_id(b.get("memberServer") or server, b.get("memberDatabase") or "")
                    if not b.get("memberDatabase") or not store.instance_exists(member):
                        return _err(404, "ResourceNotFound", "The member database was not found.")
                    if member == db_id0:
                        return _err(400, "BadRequest", "The member database must differ from the hub database.")
                    r = _ext.sync(store, db_id0, member, b.get("tables"), b.get("conflict", "hub-wins"), bool(b.get("deleteMissing")))
                    return _json(200, r) if r.get("ok") else _err(400, r["code"], r["message"])
            except Exception as e:                       # noqa: BLE001
                return _err(500, "InternalError", str(e))
            return _err(405, "MethodNotAllowed", f"Unsupported {method} on {segs[4]}")
        if len(segs) == 5 and segs[4] == "recommendations" and method == "GET":
            db_id = _db_id(server, database)
            if not store.instance_exists(db_id):
                return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
            return _json(200, {"value": _candidate_recommendations(store, db_id)})
        if len(segs) == 7 and segs[4] == "recommendations" and segs[6] == "apply" and method == "POST":
            db_id = _db_id(server, database)
            if not store.instance_exists(db_id):
                return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
            ok, message = _apply_recommendation(store, db_id, segs[5])
            if not ok:
                return _err(400, "RecommendationNotApplicable", message or "Could not apply recommendation.")
            return _json(200, {"applied": True})

    return _err(404, "NotFound", f"Unknown path: {path}")


# ── database export / import (.bacpac) — into / out of the SIMULATOR's own Azure
# Blob store. The storageUri host (`<account>.blob.core.windows.net`) is only parsed:
# the account must exist in the simulator (an ARM storage account, an account the
# blob store already holds containers for, or the emulator's devstoreaccount1) —
# it is never resolved or contacted. The .bacpac is a zip carrying the database as
# a replayable SQL script (model.sql) + Origin.json; SqlPackage's DACPAC model XML
# is not produced, so only simulator-written bacpacs import. ───────────────────
BACPAC_MODEL = "model.sql"


def _blob_target(blob_store, arm_state: dict | None, uri: str):
    """(account_arg, container_key, path_prefix, blob, error) for a storageUri."""
    from core import sql_store as sq
    try:
        account, container, blob = sq.parse_blob_uri(uri)
    except ValueError as e:
        return None, None, None, None, ("InvalidStorageUri", str(e))
    if account == "devstoreaccount1":
        acct_arg, key, prefix = None, container, "/devstoreaccount1"
    else:
        acct_arg, key, prefix = account, f"{account}/{container}", ""
        known = any(k.lower().endswith(f"/storageaccounts/{account}") for k in (arm_state or {})) or \
            any(str(c).startswith(account + "/") for c in getattr(blob_store, "containers", {}) or {})
        if not known:
            return None, None, None, None, ("StorageAccountNotFound",
                                            f"The storage account '{account}' does not exist in this simulator.")
    if not blob_store.container_exists(key):
        return None, None, None, None, ("ContainerNotFound",
                                        f"The container '{container}' does not exist in storage account '{account}'.")
    return acct_arg, key, prefix, f"{container}/{blob}", None


def export_database(store: SqlStore, server: str, database: str, blob_store, storage_uri: str,
                    arm_state: dict | None = None) -> tuple:
    """Write the database as a .bacpac blob. Returns (ok, error_code, message, size)."""
    import io
    import zipfile
    from core import sql_store as sq
    from core import azure_blob_core as blob
    if blob_store is None:
        return False, "StorageUnavailable", "No Blob store is attached to this Azure SQL engine.", 0
    acct, _key, prefix, path, err = _blob_target(blob_store, arm_state, storage_uri)
    if err:
        return False, err[0], err[1], 0
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        _create_database(store, server, database)
    if sq.is_async_engine(store):
        return False, "EngineUnavailable", "This database engine only answers asynchronously.", 0
    tables = sq.dump_tables(store, db_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Origin.json", json.dumps({"server": server, "database": database,
                                              "tables": [t["name"] for t in tables],
                                              "format": "vyomi-bacpac/1 (SQL script)"}, indent=2))
        z.writestr(BACPAC_MODEL, sq.sql_dump(tables, sq.engine_dialect(store),
                                             f"Azure SQL export of {server}/{database}"))
    data = buf.getvalue()
    r = blob.dispatch(blob_store, "PUT", f"{prefix}/{path}", {}, {"x-ms-blob-type": "BlockBlob",
                      "content-type": "application/octet-stream"}, data, account=acct)
    if r.status >= 300:
        return False, "BlobWriteFailed", f"Writing {storage_uri} failed ({r.status}).", 0
    return True, "", "", len(data)


def import_database(store: SqlStore, server: str, database: str, blob_store, storage_uri: str,
                    arm_state: dict | None = None) -> tuple:
    """Load a simulator .bacpac into the database. Returns (ok, error_code, message)."""
    import io
    import zipfile
    from core import sql_store as sq
    from core import azure_blob_core as blob
    if blob_store is None:
        return False, "StorageUnavailable", "No Blob store is attached to this Azure SQL engine."
    acct, _key, prefix, path, err = _blob_target(blob_store, arm_state, storage_uri)
    if err:
        return False, err[0], err[1]
    r = blob.dispatch(blob_store, "GET", f"{prefix}/{path}", {}, {}, b"", account=acct)
    if r.status != 200:
        return False, "BlobNotFound", f"The blob {storage_uri} does not exist."
    try:
        with zipfile.ZipFile(io.BytesIO(r.body)) as z:
            script = z.read(BACPAC_MODEL).decode("utf-8")
    except Exception:
        return False, "InvalidBacpac", ("The file is not a bacpac this simulator wrote (no model.sql); "
                                        "SqlPackage DACPAC models are not supported.")
    _create_database(store, server, database)
    db_id = _db_id(server, database)
    try:
        for stmt in sq.split_sql(script):
            store.execute_sql(db_id, stmt)
    except Exception as e:  # noqa: BLE001
        return False, "ImportFailed", f"Import failed: {e}"
    return True, "", ""
