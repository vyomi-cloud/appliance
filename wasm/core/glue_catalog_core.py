# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Glue (target prefix AWSGlue, JSON 1.1): Data Catalog, crawlers, jobs, connections, triggers — substrate-independent
(no fastapi / boto3 / socket imports; loads under Pyodide). Zero-ETL integrations stay in core/zeroetl_core (this module hands
those operations through).

What is real:
  * Data Catalog — databases, tables (every UpdateTable appends a retrievable version), partitions (arity checked against the
    table's PartitionKeys), cascades on DeleteDatabase / DeleteTable, GetTables Expression filtering, BatchCreate/Delete/Get,
    partition Expression filtering (=, <>, <, >, <=, >=, LIKE joined by AND).
  * Crawlers — StartCrawler really reads the S3 objects under each S3 target of the simulator's S3 store, infers the format from
    the objects (CSV/TSV with header detection, JSON / JSON-lines), infers column types from the sampled rows, detects Hive-style
    `key=value/` partition directories, honours exclusions and the schema-change policy, and creates / updates catalog tables
    (+ partitions) the way real crawlers do; LastCrawl, metrics and created/updated counts are real.
  * Jobs — CreateJob / UpdateJob validate role + command + worker settings; StartJobRun reads the script from S3 (missing ->
    FAILED with ScriptNotFound) and checks a Python script compiles (SyntaxError -> FAILED); concurrency limits are enforced.
  * Connections, triggers, tags, resource policy, catalog encryption settings, security configurations: durable state with
    the API's validation and filtering.

Honest limits: scripts are VALIDATED, never executed (no Spark runtime, and the simulator does not run uploaded code on behalf of a
Glue job) — a run whose script exists and compiles is recorded as SUCCEEDED with ExecutionTime 0 and a note saying nothing ran;
JDBC / DynamoDB crawler targets, Parquet footer inference, Lake Formation, ML transforms, schema registry, interactive sessions,
workflows and data-quality rulesets are not implemented (they answer UnknownOperation, so the docs reference stays honest).
State: ``rds.glue_catalog`` (memory on Nano, persisted with the RDS store)."""
from __future__ import annotations

import csv
import io
import json
import re
import time
import uuid

REGION, ACCT = "us-east-1", "123456789012"


class GlueError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _st(rds) -> dict:
    d = rds.__dict__.setdefault("glue_catalog", {})
    for k in ("databases", "tables", "versions", "partitions", "crawlers", "jobs", "runs", "connections", "triggers", "tags",
              "security_configs"):
        d.setdefault(k, {})
    d.setdefault("policy", None)
    d.setdefault("encryption", {"EncryptionAtRest": {"CatalogEncryptionMode": "DISABLED"},
                                "ConnectionPasswordEncryption": {"ReturnConnectionPasswordEncrypted": False}})
    return d


def _ts():
    return time.time()


def _arn(kind, name):
    return f"arn:aws:glue:{REGION}:{ACCT}:{kind}/{name}"


def _need(p, *names):
    for n in names:
        if p.get(n) in (None, ""):
            raise GlueError("InvalidInputException", f"Missing required parameter: {n}")


def _name(v, what):
    if not v or len(str(v)) > 255 or str(v) != str(v).strip():
        raise GlueError("InvalidInputException", f"Invalid {what} name.")
    return str(v)


def _page(items, p, key, size=100):
    n = int(p.get("MaxResults") or size)
    start = int(p.get("NextToken") or 0)
    out = {key: items[start:start + n]}
    if start + n < len(items):
        out["NextToken"] = str(start + n)
    return out


# ───────────────────────── databases ─────────────────────────
def create_database(s, p, ctx):
    _need(p, "DatabaseInput")
    di = p["DatabaseInput"]
    name = _name(di.get("Name"), "database").lower()
    if name in s["databases"]:
        raise GlueError("AlreadyExistsException", f"Database {name} already exists.")
    s["databases"][name] = dict({k: v for k, v in di.items() if k != "Name"}, Name=name, CreateTime=_ts(), CatalogId=ACCT)
    if p.get("Tags"):
        s["tags"][_arn("database", name)] = dict(p["Tags"])
    return {}


def _db(s, name):
    d = s["databases"].get(str(name or "").lower())
    if d is None:
        raise GlueError("EntityNotFoundException", f"Database {name} not found.")
    return d


def get_database(s, p, ctx):
    _need(p, "Name")
    return {"Database": _db(s, p["Name"])}


def get_databases(s, p, ctx):
    return _page(list(s["databases"].values()), p, "DatabaseList")


def update_database(s, p, ctx):
    _need(p, "Name", "DatabaseInput")
    d = _db(s, p["Name"])
    di = dict(p["DatabaseInput"])
    if di.get("Name") and di["Name"].lower() != d["Name"]:
        raise GlueError("InvalidInputException", "Renaming a database is not supported.")
    di.pop("Name", None)
    d.update(di)
    return {}


def delete_database(s, p, ctx):
    _need(p, "Name")
    d = _db(s, p["Name"])
    for tk in [k for k in s["tables"] if k[0] == d["Name"]]:
        _drop_table(s, *tk)
    del s["databases"][d["Name"]]
    return {}


# ───────────────────────── tables ─────────────────────────
def _tkey(db, name):
    return (str(db).lower(), str(name).lower())


def _table(s, db, name):
    _db(s, db)
    t = s["tables"].get(_tkey(db, name))
    if t is None:
        raise GlueError("EntityNotFoundException", f"Table {name} not found.")
    return t


def _new_table(s, db, ti, created_by="user"):
    name = _name(ti.get("Name"), "table")
    rec = dict(ti, Name=name, DatabaseName=db.lower(), CreateTime=_ts(), UpdateTime=_ts(), CatalogId=ACCT,
               CreatedBy=f"arn:aws:iam::{ACCT}:user/{created_by}", IsRegisteredWithLakeFormation=False, VersionId="0")
    rec.setdefault("TableType", "EXTERNAL_TABLE")
    s["tables"][_tkey(db, name)] = rec
    s["versions"][_tkey(db, name)] = [dict(rec)]
    return rec


def create_table(s, p, ctx):
    _need(p, "DatabaseName", "TableInput")
    _db(s, p["DatabaseName"])
    ti = p["TableInput"]
    _name(ti.get("Name"), "table")
    if _tkey(p["DatabaseName"], ti["Name"]) in s["tables"]:
        raise GlueError("AlreadyExistsException", f"Table {ti['Name']} already exists.")
    _new_table(s, p["DatabaseName"], ti)
    return {}


def get_table(s, p, ctx):
    _need(p, "DatabaseName", "Name")
    return {"Table": _table(s, p["DatabaseName"], p["Name"])}


def _match(expr, name):
    if not expr:
        return True
    try:
        return re.fullmatch(expr, name, re.I) is not None
    except re.error:
        import fnmatch
        return fnmatch.fnmatch(name.lower(), expr.lower())


def get_tables(s, p, ctx):
    _need(p, "DatabaseName")
    _db(s, p["DatabaseName"])
    rows = [t for k, t in sorted(s["tables"].items()) if k[0] == p["DatabaseName"].lower() and _match(p.get("Expression"), t["Name"])]
    return _page(rows, p, "TableList")


def update_table(s, p, ctx):
    _need(p, "DatabaseName", "TableInput")
    t = _table(s, p["DatabaseName"], p["TableInput"].get("Name"))
    key = _tkey(p["DatabaseName"], t["Name"])
    if p.get("VersionId") and str(p["VersionId"]) != str(t.get("VersionId")):
        raise GlueError("ConcurrentModificationException", "The table was modified concurrently (VersionId mismatch).")
    new = dict(t, **p["TableInput"])
    new["UpdateTime"] = _ts()
    new["VersionId"] = str(int(t.get("VersionId", "0")) + 1)
    if not p.get("SkipArchive", False):
        s["versions"].setdefault(key, []).append(dict(new))
    else:
        s["versions"][key][-1:] = [dict(new)]
    s["tables"][key] = new
    return {}


def _drop_table(s, db, name):
    s["tables"].pop((db, name), None)
    s["versions"].pop((db, name), None)
    for pk in [k for k in s["partitions"] if k[:2] == (db, name)]:
        s["partitions"].pop(pk)


def delete_table(s, p, ctx):
    _need(p, "DatabaseName", "Name")
    t = _table(s, p["DatabaseName"], p["Name"])
    _drop_table(s, p["DatabaseName"].lower(), t["Name"].lower())
    return {}


def batch_delete_table(s, p, ctx):
    _need(p, "DatabaseName", "TablesToDelete")
    _db(s, p["DatabaseName"])
    errs = []
    for n in p["TablesToDelete"]:
        if _tkey(p["DatabaseName"], n) in s["tables"]:
            _drop_table(s, p["DatabaseName"].lower(), n.lower())
        else:
            errs.append({"TableName": n, "ErrorDetail": {"ErrorCode": "EntityNotFoundException", "ErrorMessage": f"Table {n} not found."}})
    return {"Errors": errs}


def get_table_versions(s, p, ctx):
    _need(p, "DatabaseName", "TableName")
    t = _table(s, p["DatabaseName"], p["TableName"])
    vs = s["versions"].get(_tkey(p["DatabaseName"], t["Name"]), [])
    return _page([{"Table": v, "VersionId": v["VersionId"]} for v in reversed(vs)], p, "TableVersions")


def get_table_version(s, p, ctx):
    _need(p, "DatabaseName", "TableName")
    t = _table(s, p["DatabaseName"], p["TableName"])
    vs = s["versions"].get(_tkey(p["DatabaseName"], t["Name"]), [])
    vid = str(p.get("VersionId") or t["VersionId"])
    v = next((x for x in vs if x["VersionId"] == vid), None)
    if v is None:
        raise GlueError("EntityNotFoundException", f"Version {vid} not found.")
    return {"TableVersion": {"Table": v, "VersionId": vid}}


def delete_table_version(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "VersionId")
    t = _table(s, p["DatabaseName"], p["TableName"])
    vs = s["versions"].get(_tkey(p["DatabaseName"], t["Name"]), [])
    if str(p["VersionId"]) == t["VersionId"]:
        raise GlueError("InvalidInputException", "The current table version cannot be deleted.")
    n = len(vs)
    vs[:] = [v for v in vs if v["VersionId"] != str(p["VersionId"])]
    if len(vs) == n:
        raise GlueError("EntityNotFoundException", f"Version {p['VersionId']} not found.")
    return {}


# ───────────────────────── partitions ─────────────────────────
def _pkey(db, tbl, values):
    return (db.lower(), tbl.lower(), tuple(str(v) for v in values))


def _mk_part(t, pi):
    pk = t.get("PartitionKeys") or []
    if len(pi.get("Values") or []) != len(pk):
        raise GlueError("InvalidInputException", f"Partition values must have {len(pk)} element(s) (table {t['Name']} has {len(pk)} partition keys).")
    return dict(pi, DatabaseName=t["DatabaseName"], TableName=t["Name"], CreationTime=_ts(), LastAccessTime=pi.get("LastAccessTime", _ts()), CatalogId=ACCT)


def create_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionInput")
    t = _table(s, p["DatabaseName"], p["TableName"])
    k = _pkey(p["DatabaseName"], p["TableName"], p["PartitionInput"].get("Values") or [])
    if k in s["partitions"]:
        raise GlueError("AlreadyExistsException", f"Partition {list(k[2])} already exists.")
    s["partitions"][k] = _mk_part(t, p["PartitionInput"])
    return {}


def batch_create_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionInputList")
    t = _table(s, p["DatabaseName"], p["TableName"])
    errs = []
    for pi in p["PartitionInputList"]:
        k = _pkey(p["DatabaseName"], p["TableName"], pi.get("Values") or [])
        try:
            if k in s["partitions"]:
                raise GlueError("AlreadyExistsException", "Partition already exists.")
            s["partitions"][k] = _mk_part(t, pi)
        except GlueError as e:
            errs.append({"PartitionValues": pi.get("Values"), "ErrorDetail": {"ErrorCode": e.code, "ErrorMessage": e.message}})
    return {"Errors": errs}


def get_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionValues")
    _table(s, p["DatabaseName"], p["TableName"])
    part = s["partitions"].get(_pkey(p["DatabaseName"], p["TableName"], p["PartitionValues"]))
    if part is None:
        raise GlueError("EntityNotFoundException", f"Partition {p['PartitionValues']} not found.")
    return {"Partition": part}


def _part_filter(t, expr):
    if not expr:
        return lambda part: True
    keys = [k["Name"] for k in t.get("PartitionKeys") or []]
    conds = []
    for piece in re.split(r"\s+and\s+", expr, flags=re.I):
        m = re.fullmatch(r"\s*(\w+)\s*(=|<>|!=|>=|<=|>|<|like)\s*(?:'([^']*)'|\"([^\"]*)\"|(-?[\d.]+))\s*", piece, re.I)
        if not m or m.group(1) not in keys:
            raise GlueError("InvalidInputException", f"Unsupported partition expression near '{piece.strip()}'.")
        lit = next(g for g in m.group(3, 4, 5) if g is not None)
        conds.append((keys.index(m.group(1)), m.group(2).lower(), lit))

    def ok(part):
        for i, op, lit in conds:
            v = str(part["Values"][i])
            numeric = re.fullmatch(r"-?[\d.]+", lit) and re.fullmatch(r"-?[\d.]+", v)
            a, b = (float(v), float(lit)) if numeric else (v, lit)
            if op == "=" and a != b or op in ("<>", "!=") and a == b or op == ">" and not a > b or op == "<" and not a < b \
                    or op == ">=" and not a >= b or op == "<=" and not a <= b \
                    or op == "like" and not re.fullmatch(re.escape(b).replace("%", ".*"), str(a)):
                return False
        return True
    return ok


def get_partitions(s, p, ctx):
    _need(p, "DatabaseName", "TableName")
    t = _table(s, p["DatabaseName"], p["TableName"])
    f = _part_filter(t, p.get("Expression"))
    rows = [v for k, v in sorted(s["partitions"].items()) if k[:2] == _tkey(p["DatabaseName"], t["Name"]) and f(v)]
    return _page(rows, p, "Partitions")


def batch_get_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionsToGet")
    _table(s, p["DatabaseName"], p["TableName"])
    got, miss = [], []
    for pv in p["PartitionsToGet"]:
        x = s["partitions"].get(_pkey(p["DatabaseName"], p["TableName"], pv.get("Values") or []))
        if x:
            got.append(x)
        else:
            miss.append({"Values": pv.get("Values")})
    return {"Partitions": got, "UnprocessedKeys": miss}


def update_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionValueList", "PartitionInput")
    t = _table(s, p["DatabaseName"], p["TableName"])
    k = _pkey(p["DatabaseName"], p["TableName"], p["PartitionValueList"])
    if k not in s["partitions"]:
        raise GlueError("EntityNotFoundException", "Partition not found.")
    new = _mk_part(t, p["PartitionInput"])
    new["CreationTime"] = s["partitions"][k]["CreationTime"]
    s["partitions"].pop(k)
    s["partitions"][_pkey(p["DatabaseName"], p["TableName"], new["Values"])] = new
    return {}


def delete_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionValues")
    _table(s, p["DatabaseName"], p["TableName"])
    if s["partitions"].pop(_pkey(p["DatabaseName"], p["TableName"], p["PartitionValues"]), None) is None:
        raise GlueError("EntityNotFoundException", "Partition not found.")
    return {}


def batch_delete_partition(s, p, ctx):
    _need(p, "DatabaseName", "TableName", "PartitionsToDelete")
    _table(s, p["DatabaseName"], p["TableName"])
    errs = []
    for pv in p["PartitionsToDelete"]:
        if s["partitions"].pop(_pkey(p["DatabaseName"], p["TableName"], pv.get("Values") or []), None) is None:
            errs.append({"PartitionValues": pv.get("Values"), "ErrorDetail": {"ErrorCode": "EntityNotFoundException", "ErrorMessage": "Partition not found."}})
    return {"Errors": errs}


# ───────────────────────── S3 helpers (crawlers + jobs) ─────────────────────────
def _split_s3(uri):
    m = re.match(r"^s3a?://([^/]+)/?(.*)$", uri or "")
    if not m:
        raise GlueError("InvalidInputException", f"'{uri}' is not an s3:// location.")
    return m.group(1), m.group(2)


def _obj_bytes(s3, bucket, key):
    ent = (s3.objects.get(bucket) or {}).get(key)
    if not ent:
        return None
    v = (ent.get("versions") or [None])[0]
    if not v or v.get("is_delete_marker"):
        return None
    data = v.get("data")
    if data is None:
        data = s3.fetch_bytes(bucket, key)
    return bytes(data) if data is not None else None


def _list_keys(s3, bucket, prefix):
    out = []
    for k, ent in (s3.objects.get(bucket) or {}).items():
        if k.startswith(prefix) and not k.endswith("/"):
            v = (ent.get("versions") or [None])[0]
            if v and not v.get("is_delete_marker"):
                out.append((k, int(v.get("size") or 0)))
    return sorted(out)


# ───────────────────────── crawlers ─────────────────────────
def _infer_type(vals):
    vals = [v for v in vals if v not in (None, "")]
    if not vals:
        return "string"
    if all(isinstance(v, bool) or str(v).lower() in ("true", "false") for v in vals):
        return "boolean"
    try:
        ints = [int(str(v)) for v in vals]
        return "bigint" if any(abs(i) > 2**31 for i in ints) else "int"
    except ValueError:
        pass
    try:
        [float(str(v)) for v in vals]
        return "double"
    except ValueError:
        return "string"


def _json_type(v):
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "bigint"
    if isinstance(v, float):
        return "double"
    if isinstance(v, list):
        return "array<%s>" % (_json_type(v[0]) if v else "string")
    if isinstance(v, dict):
        return "struct<%s>" % ",".join(f"{k}:{_json_type(x)}" for k, x in v.items())
    return "string"


def _sniff(path, data):
    """-> (classification, columns[{Name,Type}], record_count) or None."""
    low = path.lower()
    text = data.decode("utf-8", "replace")
    head = text.split("\n", 1)[0]
    if low.endswith((".json", ".jsonl", ".ndjson")) or text.lstrip().startswith(("{", "[")):
        rows = []
        try:
            doc = json.loads(text)
            rows = doc if isinstance(doc, list) else [doc]
        except ValueError:
            for ln in text.splitlines():
                if ln.strip():
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        return None
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            return None
        cols = {}
        for r in rows[:1000]:
            for k, v in r.items():
                cols.setdefault(k, _json_type(v))
        return "json", [{"Name": k, "Type": t} for k, t in cols.items()], len(rows)
    if low.endswith((".csv", ".tsv", ".txt")) or "," in head or "\t" in head:
        delim = "\t" if low.endswith(".tsv") or ("\t" in head and "," not in head) else ","
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if r]
        if not rows:
            return None
        first, body = rows[0], rows[1:]
        # a header row is all non-numeric text, with unique names, above rows that carry some non-text columns or the same text columns
        header = all(_infer_type([c]) == "string" for c in first) and len(set(first)) == len(first) and (
            not body or any(_infer_type([r[i] for r in body if i < len(r)]) != "string" for i in range(len(first))) or len(rows) > 1)
        names = [re.sub(r"\W+", "_", c.strip().lower()) or f"col{i}" for i, c in enumerate(first)] if header else [f"col{i}" for i in range(len(first))]
        body = rows[1:] if header else rows
        cols = [{"Name": n, "Type": _infer_type([r[i] for r in body[:1000] if i < len(r)])} for i, n in enumerate(names)]
        return ("tsv" if delim == "\t" else "csv"), cols, len(body)
    return None


_FORMATS = {
    "csv": ("org.apache.hadoop.mapred.TextInputFormat", "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "org.apache.hadoop.hive.serde2.OpenCSVSerde", {"separatorChar": ","}),
    "tsv": ("org.apache.hadoop.mapred.TextInputFormat", "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "org.apache.hadoop.hive.serde2.OpenCSVSerde", {"separatorChar": "\t"}),
    "json": ("org.apache.hadoop.mapred.TextInputFormat", "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
             "org.openx.data.jsonserde.JsonSerDe", {}),
}


def _crawl_s3_target(s, s3, crawler, tgt, stats):
    bucket, prefix = _split_s3(tgt.get("Path"))
    if not s3.bucket_exists(bucket):
        raise GlueError("EntityNotFoundException", f"S3 bucket {bucket} does not exist.")
    base = prefix.rstrip("/")
    keys = []
    for k, sz in _list_keys(s3, bucket, prefix):
        rel = k[len(base):].lstrip("/") if base else k
        if any(re.fullmatch(re.escape(e).replace(r"\*\*", ".*").replace(r"\*", "[^/]*"), rel) for e in tgt.get("Exclusions") or []):
            continue
        keys.append((k, sz, rel))
    groups = {}   # (table location, hive partition key names) -> {partition values -> [(key, size)]}
    for k, sz, rel in keys:
        parts = rel.split("/")[:-1]
        hive = [p.split("=", 1) for p in parts if re.fullmatch(r"[^=/]+=[^/]*", p)]
        plain = [p for p in parts if not re.fullmatch(r"[^=/]+=[^/]*", p)]
        loc = f"s3://{bucket}/" + "/".join(x for x in (base, plain[0] if plain else "") if x)
        groups.setdefault((loc, tuple(h[0] for h in hive)), {}).setdefault(tuple(h[1] for h in hive), []).append((k, sz))
    created = updated = 0
    for (loc, pkeys), parts in groups.items():
        last = loc.rstrip("/").rsplit("/", 1)[-1]
        tname = re.sub(r"\W+", "_", (crawler.get("TablePrefix") or "") + last).strip("_").lower()
        objs = [o for v in parts.values() for o in v]
        sniffed = None
        for k, _ in objs[:10]:
            sniffed = _sniff(k, _obj_bytes(s3, bucket, k) or b"")
            if sniffed:
                break
        if sniffed is None:
            continue
        cls, cols, _n = sniffed
        rc = sum((_sniff(k, _obj_bytes(s3, bucket, k) or b"") or (0, 0, 0))[2] for k, _ in objs)
        total = sum(sz for _, sz in objs)
        inf, outf, serde, sp = _FORMATS[cls]
        params = {"classification": cls, "recordCount": str(rc), "sizeKey": str(total), "objectCount": str(len(objs)),
                  "averageRecordSize": str(int(total / rc) if rc else 0), "compressionType": "none", "typeOfData": "file",
                  "UPDATED_BY_CRAWLER": crawler["Name"]}
        if cls in ("csv", "tsv"):
            params["skip.header.line.count"] = "1"
        key = _tkey(crawler["DatabaseName"], tname)
        sd = {"Columns": cols, "Location": loc, "InputFormat": inf, "OutputFormat": outf, "Compressed": False, "NumberOfBuckets": -1,
              "SerdeInfo": {"SerializationLibrary": serde, "Parameters": dict(sp)}, "StoredAsSubDirectories": False}
        pk_cols = [{"Name": n, "Type": _infer_type([v[i] for v in parts])} for i, n in enumerate(pkeys)]
        ti = {"Name": tname, "StorageDescriptor": sd, "PartitionKeys": pk_cols, "TableType": "EXTERNAL_TABLE", "Parameters": params}
        policy = crawler.get("SchemaChangePolicy") or {}
        if key not in s["tables"]:
            _new_table(s, crawler["DatabaseName"], ti, created_by="crawler/" + crawler["Name"])
            created += 1
        elif policy.get("UpdateBehavior") != "LOG":
            old = s["tables"][key]
            if old.get("StorageDescriptor", {}).get("Columns") != cols or old.get("Parameters", {}).get("recordCount") != str(rc):
                update_table(s, {"DatabaseName": crawler["DatabaseName"], "TableInput": dict(ti, Name=old["Name"])}, None)
                updated += 1
        t = s["tables"][key]
        for vals in parts:
            if vals and _pkey(crawler["DatabaseName"], t["Name"], vals) not in s["partitions"]:
                ploc = loc + "/" + "/".join(f"{pk}={v}" for pk, v in zip(pkeys, vals)) + "/"
                s["partitions"][_pkey(crawler["DatabaseName"], t["Name"], vals)] = _mk_part(t, {"Values": list(vals), "StorageDescriptor": dict(sd, Location=ploc)})
    stats["created"] += created
    stats["updated"] += updated


def _crawler_view(c):
    return {k: x for k, x in c.items() if not k.startswith("_")}


def create_crawler(s, p, ctx):
    _need(p, "Name", "Role", "Targets")
    name = _name(p["Name"], "crawler")
    if name in s["crawlers"]:
        raise GlueError("AlreadyExistsException", f"Crawler {name} already exists.")
    if not (p.get("DatabaseName") or "").strip():
        raise GlueError("InvalidInputException", "DatabaseName is required.")
    if not any(p["Targets"].get(k) for k in ("S3Targets", "JdbcTargets", "DynamoDBTargets", "CatalogTargets", "MongoDBTargets")):
        raise GlueError("InvalidInputException", "At least one crawler target is required.")
    rec = {k: v for k, v in p.items() if k != "Tags"}
    rec.update(State="READY", CreationTime=_ts(), LastUpdated=_ts(), Version=1, CrawlElapsedTime=0)
    rec.setdefault("SchemaChangePolicy", {"UpdateBehavior": "UPDATE_IN_DATABASE", "DeleteBehavior": "DEPRECATE_IN_DATABASE"})
    s["crawlers"][name] = rec
    if p.get("Tags"):
        s["tags"][_arn("crawler", name)] = dict(p["Tags"])
    return {}


def _crawler(s, name):
    c = s["crawlers"].get(name)
    if c is None:
        raise GlueError("EntityNotFoundException", f"Crawler {name} not found.")
    return c


def get_crawler(s, p, ctx):
    _need(p, "Name")
    return {"Crawler": _crawler_view(_crawler(s, p["Name"]))}


def get_crawlers(s, p, ctx):
    return _page([_crawler_view(c) for c in s["crawlers"].values()], p, "Crawlers")


def list_crawlers(s, p, ctx):
    names = [n for n in s["crawlers"] if not p.get("Tags") or all(s["tags"].get(_arn("crawler", n), {}).get(k) == v for k, v in p["Tags"].items())]
    return _page(names, p, "CrawlerNames")


def update_crawler(s, p, ctx):
    _need(p, "Name")
    c = _crawler(s, p["Name"])
    if c["State"] != "READY":
        raise GlueError("CrawlerRunningException", f"Crawler {p['Name']} is running.")
    c.update({k: v for k, v in p.items() if k != "Name"})
    c["LastUpdated"] = _ts()
    c["Version"] = c.get("Version", 1) + 1
    return {}


def delete_crawler(s, p, ctx):
    _need(p, "Name")
    c = _crawler(s, p["Name"])
    if c["State"] != "READY":
        raise GlueError("CrawlerRunningException", f"Crawler {p['Name']} is running.")
    del s["crawlers"][p["Name"]]
    return {}


def start_crawler(s, p, ctx):
    _need(p, "Name")
    c = _crawler(s, p["Name"])
    if c["State"] != "READY":
        raise GlueError("CrawlerRunningException", f"Crawler {p['Name']} is already running.")
    t0 = _ts()
    stats = {"created": 0, "updated": 0}
    err = None
    try:
        _db(s, c["DatabaseName"])
        if c["Targets"].get("JdbcTargets") or c["Targets"].get("DynamoDBTargets"):
            raise GlueError("InvalidInputException", "Only S3 crawler targets are supported by the simulator.")
        for tg in (c["Targets"].get("S3Targets") or []):
            _crawl_s3_target(s, ctx["s3"], c, tg, stats)
    except GlueError as e:
        err = e.message
    c["LastCrawl"] = {"Status": "FAILED" if err else "SUCCEEDED", "StartTime": t0, "LogGroup": "/aws-glue/crawlers", "LogStream": c["Name"]}
    if err:
        c["LastCrawl"]["ErrorMessage"] = err
    el = round(_ts() - t0, 3)
    c["_metrics"] = {"LastRuntimeSeconds": el, "TablesCreated": stats["created"], "TablesUpdated": stats["updated"], "TablesDeleted": 0,
                     "MedianRuntimeSeconds": el, "StillEstimating": False}
    c["CrawlElapsedTime"] = int(el * 1000)
    c["LastUpdated"] = _ts()
    return {}


def stop_crawler(s, p, ctx):
    _need(p, "Name")
    c = _crawler(s, p["Name"])
    if c["State"] == "READY":
        raise GlueError("CrawlerNotRunningException", f"Crawler {p['Name']} is not running.")
    c["State"] = "READY"
    return {}


def get_crawler_metrics(s, p, ctx):
    names = p.get("CrawlerNameList") or list(s["crawlers"])
    return {"CrawlerMetricsList": [dict({"CrawlerName": n, "TimeLeftSeconds": 0.0, "StillEstimating": False}, **(s["crawlers"][n].get("_metrics") or {}))
                                   for n in names if n in s["crawlers"]]}


# ───────────────────────── jobs ─────────────────────────
_COMMANDS = ("glueetl", "gluestreaming", "pythonshell", "glueray")


def _job_checks(j):
    role = str(j.get("Role") or "")
    if not re.fullmatch(r"(arn:aws:iam::\d{12}:role/)?[\w+=,.@/-]+", role):
        raise GlueError("InvalidInputException", "Role must be an IAM role name or ARN.")
    cmd = j.get("Command") or {}
    if cmd.get("Name") not in _COMMANDS:
        raise GlueError("InvalidInputException", f"Command.Name must be one of {', '.join(_COMMANDS)}.")
    if not cmd.get("ScriptLocation"):
        raise GlueError("InvalidInputException", "Command.ScriptLocation is required.")
    wt, n = j.get("WorkerType"), j.get("NumberOfWorkers")
    if wt and wt not in ("Standard", "G.1X", "G.2X", "G.025X", "G.4X", "G.8X", "Z.2X"):
        raise GlueError("InvalidInputException", f"Invalid WorkerType {wt}.")
    if (wt is None) != (n is None) and cmd.get("Name") != "pythonshell":
        raise GlueError("InvalidInputException", "WorkerType and NumberOfWorkers must be specified together.")


def create_job(s, p, ctx):
    _need(p, "Name", "Role", "Command")
    name = _name(p["Name"], "job")
    if name in s["jobs"]:
        raise GlueError("IdempotentParameterMismatchException", f"Job {name} already exists.")
    _job_checks(p)
    rec = {k: v for k, v in p.items() if k != "Tags"}
    rec.update(CreatedOn=_ts(), LastModifiedOn=_ts())
    rec.setdefault("MaxRetries", 0)
    rec.setdefault("Timeout", 2880)
    rec.setdefault("GlueVersion", "4.0" if rec["Command"]["Name"] != "pythonshell" else "3.0")
    rec.setdefault("ExecutionProperty", {"MaxConcurrentRuns": 1})
    s["jobs"][name] = rec
    if p.get("Tags"):
        s["tags"][_arn("job", name)] = dict(p["Tags"])
    return {"Name": name}


def _job(s, name):
    j = s["jobs"].get(name)
    if j is None:
        raise GlueError("EntityNotFoundException", f"Job {name} not found.")
    return j


def get_job(s, p, ctx):
    _need(p, "JobName")
    return {"Job": _job(s, p["JobName"])}


def get_jobs(s, p, ctx):
    return _page(list(s["jobs"].values()), p, "Jobs")


def list_jobs(s, p, ctx):
    names = [n for n in s["jobs"] if not p.get("Tags") or all(s["tags"].get(_arn("job", n), {}).get(k) == v for k, v in p["Tags"].items())]
    return _page(names, p, "JobNames")


def update_job(s, p, ctx):
    _need(p, "JobName", "JobUpdate")
    j = _job(s, p["JobName"])
    _job_checks(dict(j, **p["JobUpdate"]))
    j.update(p["JobUpdate"])
    j["LastModifiedOn"] = _ts()
    return {"JobName": p["JobName"]}


def delete_job(s, p, ctx):
    _need(p, "JobName")
    if p["JobName"] in s["jobs"]:
        del s["jobs"][p["JobName"]]
        for rid in [r for r, x in s["runs"].items() if x["JobName"] == p["JobName"]]:
            s["runs"].pop(rid)
    return {"JobName": p["JobName"]}


def start_job_run(s, p, ctx):
    _need(p, "JobName")
    j = _job(s, p["JobName"])
    active = [r for r in s["runs"].values() if r["JobName"] == j["Name"] and r["JobRunState"] in ("STARTING", "RUNNING")]
    if len(active) >= int((j.get("ExecutionProperty") or {}).get("MaxConcurrentRuns", 1)):
        raise GlueError("ConcurrentRunsExceededException", f"Job {j['Name']} has reached its maximum concurrent runs.")
    args = dict(j.get("DefaultArguments") or {}, **(p.get("Arguments") or {}))
    rid = "jr_" + uuid.uuid4().hex + uuid.uuid4().hex[:32]
    t0 = _ts()
    run = {"Id": rid, "Attempt": 0, "JobName": j["Name"], "StartedOn": t0, "JobRunState": "STARTING", "Arguments": args,
           "AllocatedCapacity": 2, "MaxCapacity": float(p.get("MaxCapacity") or j.get("MaxCapacity") or 2),
           "WorkerType": p.get("WorkerType") or j.get("WorkerType"), "NumberOfWorkers": p.get("NumberOfWorkers") or j.get("NumberOfWorkers"),
           "GlueVersion": j["GlueVersion"], "LogGroupName": "/aws-glue/python-jobs" if j["Command"]["Name"] == "pythonshell" else "/aws-glue/jobs",
           "Timeout": p.get("Timeout") or j.get("Timeout")}
    run = {k: v for k, v in run.items() if v is not None}
    loc = j["Command"]["ScriptLocation"]
    try:
        bucket, key = _split_s3(loc)
        src = _obj_bytes(ctx["s3"], bucket, key)
    except GlueError:
        src = None
    if src is None:
        run.update(JobRunState="FAILED", ErrorMessage=f"ScriptNotFound: {loc}")
    elif j["Command"]["Name"] in ("pythonshell", "glueetl", "gluestreaming") and key.endswith(".py"):
        try:
            compile(src.decode("utf-8", "replace"), key, "exec")
            run.update(JobRunState="SUCCEEDED", _note="Script found in S3 and compiles; the simulator validates but does not execute Glue scripts.")
        except SyntaxError as e:
            run.update(JobRunState="FAILED", ErrorMessage=f"SyntaxError: {e.msg} ({key}, line {e.lineno})")
    else:
        run.update(JobRunState="SUCCEEDED", _note="Script found in S3; the simulator validates but does not execute Glue scripts.")
    run["CompletedOn"] = _ts()
    run["ExecutionTime"] = 0
    run["LastModifiedOn"] = run["CompletedOn"]
    s["runs"][rid] = run
    return {"JobRunId": rid}


def _rview(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def get_job_run(s, p, ctx):
    _need(p, "JobName", "RunId")
    r = s["runs"].get(p["RunId"])
    if r is None or r["JobName"] != p["JobName"]:
        raise GlueError("EntityNotFoundException", f"Job run {p['RunId']} not found.")
    return {"JobRun": _rview(r)}


def get_job_runs(s, p, ctx):
    _need(p, "JobName")
    _job(s, p["JobName"])
    return _page([_rview(r) for r in sorted(s["runs"].values(), key=lambda r: -r["StartedOn"]) if r["JobName"] == p["JobName"]], p, "JobRuns")


def batch_stop_job_run(s, p, ctx):
    _need(p, "JobName", "JobRunIds")
    ok, err = [], []
    for rid in p["JobRunIds"]:
        r = s["runs"].get(rid)
        if r is None or r["JobName"] != p["JobName"]:
            err.append({"JobName": p["JobName"], "JobRunId": rid, "ErrorDetail": {"ErrorCode": "EntityNotFoundException", "ErrorMessage": "Run not found."}})
        else:
            if r["JobRunState"] in ("STARTING", "RUNNING"):
                r["JobRunState"] = "STOPPED"
            ok.append({"JobName": p["JobName"], "JobRunId": rid})
    return {"SuccessfulSubmissions": ok, "Errors": err}


def get_job_bookmark(s, p, ctx):
    _need(p, "JobName")
    _job(s, p["JobName"])
    return {"JobBookmarkEntry": {"JobName": p["JobName"], "Version": 0, "Run": 0, "Attempt": 0, "JobBookmark": "{}"}}


# ───────────────────────── connections / triggers / misc ─────────────────────────
def create_connection(s, p, ctx):
    _need(p, "ConnectionInput")
    ci = p["ConnectionInput"]
    name = _name(ci.get("Name"), "connection")
    if name in s["connections"]:
        raise GlueError("AlreadyExistsException", f"Connection {name} already exists.")
    if not ci.get("ConnectionType"):
        raise GlueError("InvalidInputException", "ConnectionType is required.")
    s["connections"][name] = dict(ci, CreationTime=_ts(), LastUpdatedTime=_ts())
    if p.get("Tags"):
        s["tags"][_arn("connection", name)] = dict(p["Tags"])
    return {"CreateConnectionStatus": "READY"}


def _conn(s, n):
    c = s["connections"].get(n)
    if c is None:
        raise GlueError("EntityNotFoundException", f"Connection {n} not found.")
    return c


def _conn_view(c, hide):
    c = dict(c)
    if hide and "ConnectionProperties" in c:
        c["ConnectionProperties"] = {k: v for k, v in c["ConnectionProperties"].items() if k not in ("PASSWORD", "ENCRYPTED_PASSWORD")}
    return c


def get_connection(s, p, ctx):
    _need(p, "Name")
    return {"Connection": _conn_view(_conn(s, p["Name"]), p.get("HidePassword"))}


def get_connections(s, p, ctx):
    return _page([_conn_view(c, p.get("HidePassword")) for c in s["connections"].values()], p, "ConnectionList")


def update_connection(s, p, ctx):
    _need(p, "Name", "ConnectionInput")
    c = _conn(s, p["Name"])
    c.update({k: v for k, v in p["ConnectionInput"].items() if k != "Name"})
    c["LastUpdatedTime"] = _ts()
    return {}


def delete_connection(s, p, ctx):
    _need(p, "ConnectionName")
    _conn(s, p["ConnectionName"])
    del s["connections"][p["ConnectionName"]]
    return {}


def create_trigger(s, p, ctx):
    _need(p, "Name", "Type", "Actions")
    name = _name(p["Name"], "trigger")
    if name in s["triggers"]:
        raise GlueError("AlreadyExistsException", f"Trigger {name} already exists.")
    if p["Type"] not in ("SCHEDULED", "CONDITIONAL", "ON_DEMAND", "EVENT"):
        raise GlueError("InvalidInputException", "Type must be SCHEDULED, CONDITIONAL, ON_DEMAND or EVENT.")
    if p["Type"] == "SCHEDULED" and not p.get("Schedule"):
        raise GlueError("InvalidInputException", "A SCHEDULED trigger needs a Schedule.")
    if p["Type"] == "CONDITIONAL" and not p.get("Predicate"):
        raise GlueError("InvalidInputException", "A CONDITIONAL trigger needs a Predicate.")
    for a in p["Actions"]:
        if a.get("JobName") and a["JobName"] not in s["jobs"]:
            raise GlueError("EntityNotFoundException", f"Job {a['JobName']} not found.")
        if a.get("CrawlerName") and a["CrawlerName"] not in s["crawlers"]:
            raise GlueError("EntityNotFoundException", f"Crawler {a['CrawlerName']} not found.")
    rec = {k: v for k, v in p.items() if k not in ("Tags", "StartOnCreation")}
    rec["State"] = "ACTIVATED" if p.get("StartOnCreation") else "CREATED"
    s["triggers"][name] = rec
    return {"Name": name}


def _trig(s, n):
    t = s["triggers"].get(n)
    if t is None:
        raise GlueError("EntityNotFoundException", f"Trigger {n} not found.")
    return t


def get_trigger(s, p, ctx):
    _need(p, "Name")
    return {"Trigger": _trig(s, p["Name"])}


def _dep(t, p):
    return not p.get("DependentJobName") or any(a.get("JobName") == p["DependentJobName"] for a in t["Actions"])


def get_triggers(s, p, ctx):
    return _page([t for t in s["triggers"].values() if _dep(t, p)], p, "Triggers")


def list_triggers(s, p, ctx):
    return _page([n for n, t in s["triggers"].items() if _dep(t, p)], p, "TriggerNames")


def start_trigger(s, p, ctx):
    _need(p, "Name")
    t = _trig(s, p["Name"])
    t["State"] = "ACTIVATED"
    if t["Type"] == "ON_DEMAND":
        for a in t["Actions"]:
            if a.get("JobName"):
                start_job_run(s, {"JobName": a["JobName"], "Arguments": a.get("Arguments")}, ctx)
            if a.get("CrawlerName"):
                start_crawler(s, {"Name": a["CrawlerName"]}, ctx)
    return {"Name": p["Name"]}


def stop_trigger(s, p, ctx):
    _need(p, "Name")
    _trig(s, p["Name"])["State"] = "DEACTIVATED"
    return {"Name": p["Name"]}


def delete_trigger(s, p, ctx):
    _need(p, "Name")
    _trig(s, p["Name"])
    del s["triggers"][p["Name"]]
    return {"Name": p["Name"]}


def update_trigger(s, p, ctx):
    _need(p, "Name", "TriggerUpdate")
    t = _trig(s, p["Name"])
    t.update(p["TriggerUpdate"])
    return {"Trigger": t}


def _resource_arn_ok(s, arn):
    m = re.match(r"^arn:aws:glue:[^:]*:\d{12}:(database|table|crawler|job|connection|trigger)/(.+)$", arn or "")
    if not m:
        raise GlueError("InvalidInputException", f"'{arn}' is not a Glue resource ARN.")
    kind, name = m.groups()
    known = {"database": s["databases"], "crawler": s["crawlers"], "job": s["jobs"], "connection": s["connections"], "trigger": s["triggers"],
             "table": {f"{k[0]}/{k[1]}": 1 for k in s["tables"]}}[kind]
    if (name.lower() if kind in ("database", "table") else name) not in known:
        raise GlueError("EntityNotFoundException", f"{kind} {name} not found.")


def tag_resource(s, p, ctx):
    _need(p, "ResourceArn", "TagsToAdd")
    _resource_arn_ok(s, p["ResourceArn"])
    s["tags"].setdefault(p["ResourceArn"], {}).update(p["TagsToAdd"])
    return {}


def untag_resource(s, p, ctx):
    _need(p, "ResourceArn", "TagsToRemove")
    _resource_arn_ok(s, p["ResourceArn"])
    for k in p["TagsToRemove"]:
        s["tags"].get(p["ResourceArn"], {}).pop(k, None)
    return {}


def get_tags(s, p, ctx):
    _need(p, "ResourceArn")
    _resource_arn_ok(s, p["ResourceArn"])
    return {"Tags": dict(s["tags"].get(p["ResourceArn"], {}))}


def put_resource_policy(s, p, ctx):
    _need(p, "PolicyInJson")
    try:
        json.loads(p["PolicyInJson"])
    except ValueError:
        raise GlueError("MalformedPolicyException", "PolicyInJson is not valid JSON.")
    s["policy"] = {"PolicyInJson": p["PolicyInJson"], "PolicyHash": uuid.uuid4().hex, "CreateTime": _ts(), "UpdateTime": _ts()}
    return {"PolicyHash": s["policy"]["PolicyHash"]}


def get_resource_policy(s, p, ctx):
    if not s["policy"]:
        raise GlueError("EntityNotFoundException", "Policy not found.")
    return dict(s["policy"])


def delete_resource_policy(s, p, ctx):
    if not s["policy"]:
        raise GlueError("EntityNotFoundException", "Policy not found.")
    s["policy"] = None
    return {}


def put_encryption(s, p, ctx):
    _need(p, "DataCatalogEncryptionSettings")
    s["encryption"] = p["DataCatalogEncryptionSettings"]
    return {}


def get_encryption(s, p, ctx):
    return {"DataCatalogEncryptionSettings": s["encryption"]}


def create_security_configuration(s, p, ctx):
    _need(p, "Name", "EncryptionConfiguration")
    if p["Name"] in s["security_configs"]:
        raise GlueError("AlreadyExistsException", f"Security configuration {p['Name']} already exists.")
    s["security_configs"][p["Name"]] = {"Name": p["Name"], "CreatedTimeStamp": _ts(), "EncryptionConfiguration": p["EncryptionConfiguration"]}
    return {"Name": p["Name"], "CreatedTimestamp": s["security_configs"][p["Name"]]["CreatedTimeStamp"]}


def get_security_configuration(s, p, ctx):
    _need(p, "Name")
    c = s["security_configs"].get(p["Name"])
    if c is None:
        raise GlueError("EntityNotFoundException", f"Security configuration {p['Name']} not found.")
    return {"SecurityConfiguration": c}


def get_security_configurations(s, p, ctx):
    return _page(list(s["security_configs"].values()), p, "SecurityConfigurations")


def delete_security_configuration(s, p, ctx):
    _need(p, "Name")
    if s["security_configs"].pop(p["Name"], None) is None:
        raise GlueError("EntityNotFoundException", f"Security configuration {p['Name']} not found.")
    return {}


def get_catalog_import_status(s, p, ctx):
    return {"ImportStatus": {"ImportCompleted": True, "ImportTime": _ts(), "ImportedBy": f"arn:aws:iam::{ACCT}:root"}}


OPS = {n: globals()[f] for n, f in (
    ("CreateDatabase", "create_database"), ("GetDatabase", "get_database"), ("GetDatabases", "get_databases"),
    ("UpdateDatabase", "update_database"), ("DeleteDatabase", "delete_database"),
    ("CreateTable", "create_table"), ("GetTable", "get_table"), ("GetTables", "get_tables"), ("UpdateTable", "update_table"),
    ("DeleteTable", "delete_table"), ("BatchDeleteTable", "batch_delete_table"), ("GetTableVersions", "get_table_versions"),
    ("GetTableVersion", "get_table_version"), ("DeleteTableVersion", "delete_table_version"),
    ("CreatePartition", "create_partition"), ("BatchCreatePartition", "batch_create_partition"), ("GetPartition", "get_partition"),
    ("GetPartitions", "get_partitions"), ("BatchGetPartition", "batch_get_partition"), ("UpdatePartition", "update_partition"),
    ("DeletePartition", "delete_partition"), ("BatchDeletePartition", "batch_delete_partition"),
    ("CreateCrawler", "create_crawler"), ("GetCrawler", "get_crawler"), ("GetCrawlers", "get_crawlers"), ("ListCrawlers", "list_crawlers"),
    ("UpdateCrawler", "update_crawler"), ("DeleteCrawler", "delete_crawler"), ("StartCrawler", "start_crawler"),
    ("StopCrawler", "stop_crawler"), ("GetCrawlerMetrics", "get_crawler_metrics"),
    ("CreateJob", "create_job"), ("GetJob", "get_job"), ("GetJobs", "get_jobs"), ("ListJobs", "list_jobs"), ("UpdateJob", "update_job"),
    ("DeleteJob", "delete_job"), ("StartJobRun", "start_job_run"), ("GetJobRun", "get_job_run"), ("GetJobRuns", "get_job_runs"),
    ("BatchStopJobRun", "batch_stop_job_run"), ("GetJobBookmark", "get_job_bookmark"),
    ("CreateConnection", "create_connection"), ("GetConnection", "get_connection"), ("GetConnections", "get_connections"),
    ("UpdateConnection", "update_connection"), ("DeleteConnection", "delete_connection"),
    ("CreateTrigger", "create_trigger"), ("GetTrigger", "get_trigger"), ("GetTriggers", "get_triggers"), ("ListTriggers", "list_triggers"),
    ("StartTrigger", "start_trigger"), ("StopTrigger", "stop_trigger"), ("DeleteTrigger", "delete_trigger"), ("UpdateTrigger", "update_trigger"),
    ("TagResource", "tag_resource"), ("UntagResource", "untag_resource"), ("GetTags", "get_tags"),
    ("PutResourcePolicy", "put_resource_policy"), ("GetResourcePolicy", "get_resource_policy"), ("DeleteResourcePolicy", "delete_resource_policy"),
    ("PutDataCatalogEncryptionSettings", "put_encryption"), ("GetDataCatalogEncryptionSettings", "get_encryption"),
    ("CreateSecurityConfiguration", "create_security_configuration"), ("GetSecurityConfiguration", "get_security_configuration"),
    ("GetSecurityConfigurations", "get_security_configurations"), ("DeleteSecurityConfiguration", "delete_security_configuration"),
    ("GetCatalogImportStatus", "get_catalog_import_status"))}


def dispatch(rds, s3, ddb, target, p, fallback=None):
    """-> (status, doc). Catalog / crawler / job operations here; anything else is handed to `fallback` (zero-ETL)."""
    op = OPS.get(target.split(".")[-1])
    if op is None:
        if fallback:
            return fallback(rds, ddb, target, p)
        return 400, {"__type": "UnknownOperationException", "message": f"Glue operation {target.split('.')[-1]} is not simulated."}
    try:
        return 200, op(_st(rds), p if isinstance(p, dict) else {}, {"s3": s3, "rds": rds, "ddb": ddb})
    except GlueError as e:
        return e.status, {"__type": e.code, "Message": e.message}
