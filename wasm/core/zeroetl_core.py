# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Zero-ETL integrations (DynamoDB / RDS -> a "Redshift-lite" warehouse) + a Redshift Data API over it — substrate-independent.

Zero-ETL (Glue ``CreateIntegration`` / ``DescribeIntegrations`` / ``ModifyIntegration`` / ``DeleteIntegration``, target prefix
``AWSGlue``; RDS integrations live in rds_core and are picked up from the RDS store) really replicates: the source table rows are
copied into an in-process warehouse (sqlite3, in memory, rebuilt from the replicated copies) every time the integration, its
target or a query is touched ("sync on read", like DMS's CDC-lite) - so a PutItem / INSERT shows up in the next query.

Redshift Data API (target prefix ``RedshiftData``, signing name ``redshift-data``): ExecuteStatement / DescribeStatement /
GetStatementResult / ListDatabases / ListSchemas / ListTables / CancelStatement, async-shaped (every statement is FINISHED or
FAILED by the time it is described). Statements: ``CREATE DATABASE <name> FROM INTEGRATION '<integration id|arn>'`` (as in
Redshift, an integration's data is only queryable after this) and read-only ``SELECT``/``WITH``. Tables are addressed
``<database>.<table>`` (the ``public`` schema is accepted and ignored).

Replicated shapes follow AWS: a DynamoDB table -> table named after it with the partition key, the sort key and a ``value`` column
(the whole item as JSON, SUPER in Redshift; query it with ``json_extract(value, '$.attr')`` here); an RDS table -> same-named table
with the source columns.

Honest limits: the SQL dialect is SQLite's, not Redshift's (no distkeys/sortkeys, no PartiQL SUPER navigation, no Spectrum);
replication is poll-on-touch rather than a continuous stream; no data filters beyond table include/exclude by name; no encryption
or cross-account/region semantics; the warehouse is in memory (rebuilt from the sources on boot). State on the RDS store (``zeroetl``).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid

REGION, ACCT = "us-east-1", "123456789012"


class ZErr(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _st(rds) -> dict:
    s = rds.__dict__.setdefault("zeroetl", {})
    for k in ("glue", "databases", "statements"):
        s.setdefault(k, {})
    return s


def _ts():
    return time.time()


def _arn(name):
    return f"arn:aws:glue:{REGION}:{ACCT}:integration:{name}"


def _all(rds, st):
    """Every integration visible to the warehouse: Glue-created (DynamoDB/…) + the RDS ones recorded in rds_core."""
    out = list(st["glue"].values())
    try:
        for n in rds.integration_names():
            r = rds.get_integration(n) or {}
            out.append({"IntegrationName": n, "IntegrationArn": r.get("integration_arn", ""), "SourceArn": r.get("source_arn", ""),
                        "TargetArn": r.get("target_arn", ""), "Status": "ACTIVE" if r.get("status") == "active" else str(r.get("status", "")).upper(),
                        "CreateTime": r.get("created", ""), "_rds": True})
    except Exception:
        pass
    return out


def _find(rds, st, ident):
    for i in _all(rds, st):
        if ident in (i["IntegrationName"], i["IntegrationArn"]):
            return i
    return None


# ── source readers ──
def _ddb_rows(ddb, arn):
    mt = re.match(r"^arn:aws[-a-z]*:dynamodb:[^:]*:\d{12}:table/([^/]+)$", arn or "")
    if not mt:
        return None
    t = ddb.get_table(mt.group(1)) if ddb is not None else None
    if not t:
        return None
    pk, sk = t.get("partition_key_name"), t.get("sort_key_name")
    cols = [c for c in (pk, sk) if c] + ["value"]
    rows = []
    for rec in (t.get("items") or {}).values():
        item = rec.get("item") if isinstance(rec, dict) else None
        if not isinstance(item, dict):
            continue
        rows.append([_cell(item.get(pk))] + ([_cell(item.get(sk))] if sk else []) + [json.dumps(item, default=str, sort_keys=True)])
    return {mt.group(1): (cols, rows)}


def _cell(v):
    return v if isinstance(v, (int, float, str, type(None))) else json.dumps(v, default=str)


def _rds_rows(rds, arn):
    mt = re.match(r"^arn:aws[-a-z]*:rds:[^:]*:\d{12}:(?:db|cluster):([^:]+)$", arn or "")
    if not mt or not rds.instance_exists(mt.group(1)):
        return None
    dbid = mt.group(1)
    try:
        names = [x[0] for x in rds.execute_sql(dbid, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")["rows"]]
    except Exception:
        try:
            names = [x[0] for x in rds.execute_sql(dbid, "SELECT table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema')")["rows"]]
        except Exception:
            return {}
    out = {}
    for n in names:
        try:
            r = rds.execute_sql(dbid, f'SELECT * FROM "{n}"')
            out[n] = (list(r.get("columns") or []), [[_cell(c) for c in row] for row in r["rows"]])
        except Exception:
            continue
    return out


def _replicate(rds, ddb, integ):
    src = integ["SourceArn"]
    data = _ddb_rows(ddb, src) if ":dynamodb:" in src else _rds_rows(rds, src) if ":rds:" in src else None
    return data


def _is_active(i):
    return i.get("Status") in ("ACTIVE", "active", "CREATING")


# ── Glue integration API ──
def _view(i):
    return {k: v for k, v in i.items() if not k.startswith("_")}


def _create_integration(rds, ddb, st, p):
    name = (p.get("IntegrationName") or "").strip()
    if not name or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", name):
        raise ZErr("ValidationException", "IntegrationName must be 1-128 characters: letters, numbers, hyphens and underscores.")
    src, tgt = p.get("SourceArn") or "", p.get("TargetArn") or ""
    if not re.match(r"^arn:aws[-a-z]*:(dynamodb:[^:]*:\d{12}:table/[^/]+|rds:[^:]*:\d{12}:(db|cluster):[^:]+)$", src):
        raise ZErr("InvalidInputException", "SourceArn must be a DynamoDB table ARN or an RDS/Aurora ARN.")
    if not re.match(r"^arn:aws[-a-z]*:(redshift-serverless|redshift|glue|sagemaker)[^ ]*$", tgt):
        raise ZErr("InvalidInputException", "TargetArn must be a Redshift (provisioned/serverless) namespace ARN or a SageMaker lakehouse/Glue catalog ARN.")
    if _find(rds, st, name):
        raise ZErr("IntegrationConflictOperationFault", f"Integration {name} already exists.", 409)
    if ":dynamodb:" in src:
        mt = re.search(r"table/([^/]+)$", src)
        t = ddb.get_table(mt.group(1)) if ddb is not None else None
        if not t:
            raise ZErr("EntityNotFoundException", f"Source table {mt.group(1)} does not exist.", 404)
        if not t.get("pitr_enabled"):
            raise ZErr("IntegrationSourcePropertyException", "Point-in-time recovery must be enabled on the source DynamoDB table for a zero-ETL integration.")
    elif _rds_rows(rds, src) is None:
        raise ZErr("EntityNotFoundException", "Source RDS instance does not exist.", 404)
    i = {"IntegrationName": name, "IntegrationArn": _arn(name), "SourceArn": src, "TargetArn": tgt, "Description": p.get("Description", ""),
         "Status": "ACTIVE", "CreateTime": _ts(), "Tags": p.get("Tags") or [], "DataFilter": p.get("DataFilter", ""), "IntegrationConfig": p.get("IntegrationConfig") or {}}
    st["glue"][name] = i
    return _view(i)


def dispatch_glue(rds, ddb, target, p):
    """AWSGlue.* zero-ETL operations -> (status, doc). Every other Glue operation is not simulated."""
    op = target.split(".")[-1]
    st = _st(rds)
    try:
        if op == "CreateIntegration":
            return 200, _create_integration(rds, ddb, st, p)
        if op == "DescribeIntegrations":
            ident = p.get("IntegrationIdentifier")
            items = _all(rds, st)
            if ident:
                i = _find(rds, st, ident)
                if not i:
                    raise ZErr("EntityNotFoundException", f"Integration {ident} not found.", 404)
                items = [i]
            return 200, {"Integrations": [_view(i) for i in items]}
        if op == "ModifyIntegration":
            i = _find(rds, st, p.get("IntegrationIdentifier") or "")
            if not i or i.get("_rds"):
                raise ZErr("EntityNotFoundException", "Integration not found.", 404)
            for k in ("Description", "DataFilter", "IntegrationName"):
                if k in p:
                    i[k] = p[k]
            return 200, _view(i)
        if op == "DeleteIntegration":
            i = _find(rds, st, p.get("IntegrationIdentifier") or "")
            if not i or i.get("_rds"):
                raise ZErr("EntityNotFoundException", "Integration not found.", 404)
            st["glue"].pop(i["IntegrationName"], None)
            for d in list(st["databases"].values()):
                if d["integration"] == i["IntegrationName"]:
                    d["integration"] = None
            return 200, {}
    except ZErr as e:
        return e.status, {"__type": e.code, "message": e.message}
    return 400, {"__type": "UnknownOperationException", "message": f"Glue operation {op} is not simulated (only zero-ETL integrations are)."}


# ── the warehouse ──
def _build(rds, ddb, st, dbname):
    d = st["databases"][dbname]
    conn = sqlite3.connect(":memory:")
    if d["integration"]:
        i = _find(rds, st, d["integration"])
        data = _replicate(rds, ddb, i) if i and _is_active(i) else None
        for tname, (cols, rows) in (data or {}).items():
            q = ", ".join(f'"{c}"' for c in cols)
            conn.execute(f'CREATE TABLE "{tname}" ({q})')
            conn.executemany(f'INSERT INTO "{tname}" VALUES ({",".join("?" * len(cols))})', rows)
        d["tables"] = {t: len(r) for t, (c, r) in (data or {}).items()}
    return conn


def _typ(v):
    if v is None:
        return {"isNull": True}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"longValue": v}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _exec(rds, ddb, st, p):
    sql = (p.get("Sql") or "").strip().rstrip(";").strip()
    if not sql:
        raise ZErr("ValidationException", "Sql is required.")
    if not (p.get("WorkgroupName") or p.get("ClusterIdentifier")):
        raise ZErr("ValidationException", "Either WorkgroupName or ClusterIdentifier must be specified.")
    sid = str(uuid.uuid4())
    rec = {"Id": sid, "CreatedAt": _ts(), "UpdatedAt": _ts(), "Database": p.get("Database", "dev"), "QueryString": sql, "Status": "FINISHED",
           "HasResultSet": False, "ResultRows": -1, "ResultSize": -1, "Duration": 0, "_cols": [], "_rows": []}
    t0 = time.time()
    from core import redshift_core as _rs
    if _rs.has_cluster(rds, p.get("ClusterIdentifier") or ""):      # a real Redshift cluster: full SQL on its own engine
        try:
            cols, rows, n = _rs.run_sql(rds, p["ClusterIdentifier"], sql)
            rec["_cols"], rec["_rows"] = cols, rows
            rec.update(HasResultSet=bool(cols), ResultRows=len(rows) if cols else n,
                       ResultSize=len(json.dumps(rows, default=str)))
        except _rs.RsError as e:
            rec.update(Status="FAILED", Error=e.message)
        rec["Duration"] = int((time.time() - t0) * 1e9)
        st["statements"][sid] = rec
        return {"Id": sid, "CreatedAt": rec["CreatedAt"], "Database": rec["Database"], "WorkgroupName": p.get("WorkgroupName"), "ClusterIdentifier": p.get("ClusterIdentifier")}
    m = re.match(r"^create\s+database\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+integration\s+'([^']+)'(\s+database\s+'[^']*')?$", sql, re.I)
    try:
        if m:
            i = _find(rds, st, m.group(2))
            if not i:
                raise ZErr("ValidationException", f"Integration {m.group(2)} does not exist or is not ACTIVE.")
            if m.group(1) in st["databases"]:
                raise ZErr("ValidationException", f'database "{m.group(1)}" already exists')
            st["databases"][m.group(1)] = {"integration": i["IntegrationName"], "tables": {}, "created": _ts()}
            rec["ResultRows"] = 0
        elif re.match(r"^(select|with)\b", sql, re.I):
            dbs = st["databases"]
            conn = sqlite3.connect(":memory:")
            try:
                for dn in dbs:
                    c2 = _build(rds, ddb, st, dn)
                    # materialise each database as an attached in-memory schema
                    conn.execute(f'ATTACH DATABASE ":memory:" AS "{dn}"')
                    for (tn,) in c2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                        cols = [r[1] for r in c2.execute(f'PRAGMA table_info("{tn}")')]
                        conn.execute(f'CREATE TABLE "{dn}"."{tn}" ({", ".join(chr(34) + c + chr(34) for c in cols)})')
                        conn.executemany(f'INSERT INTO "{dn}"."{tn}" VALUES ({",".join("?" * len(cols))})', c2.execute(f'SELECT * FROM "{tn}"').fetchall())
                    c2.close()
                q = re.sub(r"(?i)\b(\"?[A-Za-z_][A-Za-z0-9_]*\"?)\.public\.", r"\1.", sql)
                q = re.sub(r"(?i)\bpublic\.", "", q)
                cur = conn.execute(q)
                rec["_cols"] = [c[0] for c in cur.description or []]
                rows = cur.fetchall()
                rec["_rows"] = [list(r) for r in rows]
                rec.update(HasResultSet=True, ResultRows=len(rows), ResultSize=len(json.dumps(rec["_rows"], default=str)))
            except sqlite3.Error as e:
                raise ZErr("ValidationException", f"ERROR: {e}")
            finally:
                conn.close()
        else:
            raise ZErr("ValidationException", "Only CREATE DATABASE ... FROM INTEGRATION and read-only SELECT/WITH statements are supported on a zero-ETL warehouse.")
    except ZErr as e:
        rec.update(Status="FAILED", Error=e.message)
    rec["Duration"] = int((time.time() - t0) * 1e9)
    st["statements"][sid] = rec
    return {"Id": sid, "CreatedAt": rec["CreatedAt"], "Database": rec["Database"], "WorkgroupName": p.get("WorkgroupName"), "ClusterIdentifier": p.get("ClusterIdentifier")}


def dispatch_redshift_data(rds, ddb, target, p):
    op = target.split(".")[-1]
    st = _st(rds)
    try:
        if op in ("ExecuteStatement", "BatchExecuteStatement"):
            if op == "BatchExecuteStatement":
                raise ZErr("ValidationException", "BatchExecuteStatement is not simulated; use ExecuteStatement.")
            return 200, _exec(rds, ddb, st, p)
        if op in ("DescribeStatement", "GetStatementResult", "CancelStatement"):
            s = st["statements"].get(p.get("Id") or "")
            if not s:
                raise ZErr("ResourceNotFoundException", f"Query does not exist: {p.get('Id')}", 404)
            if op == "CancelStatement":
                return 200, {"Status": False}
            if op == "DescribeStatement":
                d = {k: v for k, v in s.items() if not k.startswith("_")}
                d["UpdatedAt"] = s["UpdatedAt"]
                return 200, d
            if s["Status"] != "FINISHED":
                raise ZErr("ResourceNotFoundException", "Query did not finish successfully.", 404)
            return 200, {"ColumnMetadata": [{"name": c, "label": c, "typeName": "varchar"} for c in s["_cols"]],
                         "Records": [[_typ(v) for v in r] for r in s["_rows"]], "TotalNumRows": len(s["_rows"])}
        from core import redshift_core as _rs
        if op in ("ListDatabases", "ListSchemas", "ListTables") and _rs.has_cluster(rds, p.get("ClusterIdentifier") or ""):
            cl = _rs._get(rds, p["ClusterIdentifier"])
            if op == "ListDatabases":
                return 200, {"Databases": [cl["db_name"]]}
            if op == "ListSchemas":
                return 200, {"Schemas": ["public"]}
            return 200, {"Tables": [{"name": t, "schema": "public", "type": "TABLE"} for t in _rs.list_tables(rds, cl["id"])]}
        if op == "ListDatabases":
            return 200, {"Databases": ["dev"] + sorted(st["databases"])}
        if op == "ListSchemas":
            return 200, {"Schemas": ["public"]}
        if op == "ListTables":
            out = []
            for dn, d in st["databases"].items():
                if p.get("Database") and p["Database"] != dn:
                    continue
                _build(rds, ddb, st, dn).close()
                out += [{"name": t, "schema": "public", "type": "TABLE"} for t in sorted(d["tables"])]
            return 200, {"Tables": out}
    except ZErr as e:
        return e.status, {"__type": e.code, "message": e.message}
    return 400, {"__type": "UnknownOperationException", "message": f"Redshift Data operation {op} is not simulated."}
