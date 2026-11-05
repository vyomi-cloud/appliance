# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Stream Analytics (Microsoft.StreamAnalytics), substrate-free: streamingjobs + inputs + outputs + transformations.

Real ARM behaviour: name rules, compatibility levels, SU counts, datasource/serialization validation per type, the
transformation query is PARSED and checked against the job (every ``FROM`` alias must be a defined input, every ``INTO`` a
defined output, no unsupported constructs), and the job state machine Created -> Starting -> Running -> Stopping -> Stopped
(start from Running/Starting is refused; ``outputStartMode`` CustomTime needs ``outputStartTime``; start needs >=1 input,
>=1 output and a transformation, like ARM).

A small REAL query runner executes the job on start: the Blob input (Microsoft.Storage/Blob, Json line-separated/array or
Csv with header, blobs under the container + path-pattern prefix) is loaded into an in-memory SQL engine, the query's
``SELECT .. FROM input [TIMESTAMP BY ts] [WHERE ..] [GROUP BY .. | TumblingWindow(second|minute|hour, n)]`` runs, and the result
rows are written as a line-separated JSON blob into the Blob output's container (``System.Timestamp()`` is the window end for
tumbling windows). The run is a batch over what is in the container at start, then the job stays Running with the summary
in ``properties.vyomiRun``.

NOT modelled (job Failed at start with the reason, never a fake Running): Event Hub / IoT Hub inputs and outputs (no Event Hubs
data plane), Cosmos DB / SQL / Power BI / other outputs, Hopping/Sliding/Session windows, JOINs, reference-data joins, UDF/UDA,
streaming continuity (no new events are picked up after start). ``dispatch`` returns {"status","headers","body"}.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

API = "2021-10-01-preview"
NS = "microsoft.streamanalytics"
JOB_T = "Microsoft.StreamAnalytics/streamingjobs"
COMPAT = ("1.0", "1.1", "1.2")
SU = (1, 3, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78, 84, 90, 96, 102, 108, 114, 120, 126, 132, 138, 144, 150, 156, 162, 168, 174, 180, 186, 192, 198, 204, 210, 216, 222, 228, 234, 240)
IN_TYPES = ("Microsoft.Storage/Blob", "Microsoft.ServiceBus/EventHub", "Microsoft.EventHub/EventHub", "Microsoft.Devices/IotHubs", "Microsoft.Sql/Server/Database", "Microsoft.Storage/Gen2FileSystem")
OUT_TYPES = ("Microsoft.Storage/Blob", "Microsoft.Storage/DocumentDB", "Microsoft.ServiceBus/EventHub", "Microsoft.EventHub/EventHub", "Microsoft.Sql/Server/Database",
             "Microsoft.ServiceBus/Queue", "Microsoft.ServiceBus/Topic", "Microsoft.Storage/Table", "PowerBI", "Microsoft.AzureFunction", "Microsoft.Storage/Gen2FileSystem")
SERIAL = ("Json", "Csv", "Avro", "Parquet", "CustomClr")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,62}$")


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _bad(m, code="InvalidParameter"):
    return _E(400, code, m)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body}


def _err(status, code, msg):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": msg}}}


def handles(namespace, chain):
    return namespace.lower() == NS and bool(chain) and chain[0].lower() == "streamingjobs"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ── datasource / serialization validation ───────────────────────────────────────────────
def _check_serialization(ser, what, required=True):
    if not ser:
        if required:
            raise _bad(f"{what}.serialization is required.")
        return
    t = ser.get("type")
    if t not in SERIAL:
        raise _bad(f"{what}.serialization.type '{t}' is invalid. Allowed: {', '.join(SERIAL)}.")
    p = ser.get("properties") or {}
    if t == "Json" and p.get("format") not in (None, "LineSeparated", "Array"):
        raise _bad("Json serialization format must be LineSeparated or Array.")
    if t == "Csv" and (not p.get("fieldDelimiter") or p.get("fieldDelimiter") not in (",", ";", "\t", " ", "|")):
        raise _bad("Csv serialization needs a fieldDelimiter (',', ';', tab, space or '|').")
    if t in ("Json", "Csv") and p.get("encoding") not in (None, "UTF8"):
        raise _bad("Only UTF8 encoding is supported.")


def _check_datasource(ds, what, allowed):
    t = (ds or {}).get("type")
    if t not in allowed:
        raise _bad(f"{what}.datasource.type '{t}' is invalid. Allowed: {', '.join(allowed)}.")
    p = ds.get("properties") or {}
    if t in ("Microsoft.Storage/Blob", "Microsoft.Storage/Gen2FileSystem"):
        accts = p.get("storageAccounts") or []
        if not accts or not accts[0].get("accountName"):
            raise _bad(f"{what}: Blob datasource needs properties.storageAccounts[0].accountName.")
        if not p.get("container"):
            raise _bad(f"{what}: Blob datasource needs properties.container.")
    elif t in ("Microsoft.ServiceBus/EventHub", "Microsoft.EventHub/EventHub"):
        if not p.get("serviceBusNamespace") and not p.get("fullyQualifiedNamespace"):
            raise _bad(f"{what}: Event Hub datasource needs serviceBusNamespace.")
        if not p.get("eventHubName"):
            raise _bad(f"{what}: Event Hub datasource needs eventHubName.")
    elif t == "Microsoft.Storage/DocumentDB":
        for k in ("accountId", "database"):
            if not p.get(k):
                raise _bad(f"{what}: Cosmos DB datasource needs {k}.")


def _child(kind, job, name, payload, old):
    if not _NAME.match(name):
        raise _bad(f"The {kind} name '{name}' is invalid (2-63 letters, digits, '-' or '_').")
    props = dict(payload.get("properties") or {})
    if kind == "inputs":
        typ = props.get("type")
        if typ not in ("Stream", "Reference"):
            raise _bad("input properties.type must be Stream or Reference.")
        ds = props.get("datasource") or {}
        _check_datasource(ds, "input", IN_TYPES)
        if typ == "Reference" and ds.get("type") not in ("Microsoft.Storage/Blob", "Microsoft.Sql/Server/Database"):
            raise _bad("A Reference input must use Blob or SQL Database.")
        _check_serialization(props.get("serialization"), "input", required=ds.get("type") != "Microsoft.Sql/Server/Database")
    else:
        _check_datasource(props.get("datasource"), "output", OUT_TYPES)
        _check_serialization(props.get("serialization"), "output", required=props["datasource"]["type"] in ("Microsoft.Storage/Blob", "Microsoft.ServiceBus/EventHub", "Microsoft.EventHub/EventHub"))
    props["diagnostics"] = {"conditions": []}
    props["etag"] = uuid.uuid4().hex
    t = "Microsoft.StreamAnalytics/streamingjobs/" + kind
    return {"id": f"{job['id']}/{kind}/{name}", "name": name, "type": t, "properties": props}


def _transformation(job, name, payload):
    props = dict(payload.get("properties") or {})
    q = props.get("query")
    if not q or not str(q).strip():
        raise _bad("transformation properties.query is required.")
    su = props.get("streamingUnits", 1)
    if su not in SU:
        raise _bad(f"streamingUnits {su} is invalid; allowed: 1, 3, 6, 12, 18, ... (multiples of 6).")
    props["streamingUnits"] = su
    props["etag"] = uuid.uuid4().hex
    return {"id": f"{job['id']}/transformations/{name}", "name": name, "type": "Microsoft.StreamAnalytics/streamingjobs/transformations", "properties": props}


# ── query parsing + runner ──────────────────────────────────────────────────────────────
_TW = re.compile(r"TumblingWindow\s*\(\s*(second|minute|hour|day)\s*,\s*(\d+)\s*\)", re.I)
_UNSUP = [(re.compile(r"\b(HoppingWindow|SlidingWindow|SessionWindow|SnapshotWindow)\b", re.I), "Hopping/Sliding/Session/Snapshot windows"),
          (re.compile(r"\bJOIN\b", re.I), "JOIN"), (re.compile(r"\bOVER\s*\(", re.I), "OVER/LAG/analytic functions"),
          (re.compile(r"\bUDF\.|\bUDA\.", re.I), "user-defined functions")]
_UNIT = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_query(query):
    """-> (statements, error). Each statement: {select, into, frm, ts_by, where, group}. Raises _E on a bad query."""
    q = re.sub(r"--[^\n]*", "", query or "").strip().rstrip(";")
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", q):
        raise _bad("The query must start with SELECT (or WITH).", "InvalidQuery")
    if re.match(r"(?is)^\s*WITH\b", q):
        raise _bad("WITH (common table expressions) is not supported by this runner.", "UnsupportedQuery")
    for rx, what in _UNSUP:
        if rx.search(q):
            raise _bad(f"{what} is not supported by the Vyomi query runner.", "UnsupportedQuery")
    m = re.match(r"(?is)^SELECT\s+(?P<sel>.+?)\s+(?:INTO\s+(?P<into>\[[^\]]+\]|\w[\w-]*)\s+)?FROM\s+(?P<frm>\[[^\]]+\]|\w[\w-]*)"
                 r"(?:\s+TIMESTAMP\s+BY\s+(?P<ts>\[[^\]]+\]|\w+))?(?:\s+WHERE\s+(?P<where>.+?))?(?:\s+GROUP\s+BY\s+(?P<group>.+?))?\s*$", q)
    if not m:
        raise _bad("The query could not be parsed (expected SELECT .. [INTO out] FROM in [TIMESTAMP BY ts] [WHERE ..] [GROUP BY ..]).", "InvalidQuery")
    d = m.groupdict()
    for k in ("into", "frm", "ts"):
        if d[k]:
            d[k] = d[k].strip("[]")
    return d


def validate_query(job, query):
    d = parse_query(query)
    ins = {k.lower() for k in job["_inputs"]}
    outs = {k.lower() for k in job["_outputs"]}
    if d["frm"].lower() not in ins:
        raise _bad(f"Input '{d['frm']}' used in the query is not defined on the job.", "InvalidQuery")
    if d["into"] and d["into"].lower() not in outs:
        raise _bad(f"Output '{d['into']}' used in the query is not defined on the job.", "InvalidQuery")
    if not d["into"] and len(job["_outputs"]) != 1:
        raise _bad("A query without INTO needs the job to have exactly one output.", "InvalidQuery")
    return d


def _sql_for(d):
    ts = f'"{d["ts"]}"' if d["ts"] else None
    sel, grp, where = d["select"] if "select" in d else d["sel"], d["group"], d["where"]
    wid = None
    if grp and _TW.search(grp):
        tw = _TW.search(grp)
        if not ts:
            raise _bad("TumblingWindow needs TIMESTAMP BY <column> in this runner (no event enqueue time exists).", "UnsupportedQuery")
        size = _UNIT[tw.group(1).lower()] * int(tw.group(2))
        wid = f"(CAST(strftime('%s', {ts}) AS INTEGER)/{size})"
        grp = _TW.sub(wid, grp)
        sel = re.sub(r"System\.Timestamp\s*\(\s*\)", f"strftime('%Y-%m-%dT%H:%M:%SZ', ({wid}+1)*{size}, 'unixepoch')", sel, flags=re.I)
    elif re.search(r"System\.Timestamp", sel, re.I):
        sel = re.sub(r"System\.Timestamp\s*\(\s*\)", (f"{ts}" if ts else "NULL"), sel, flags=re.I)
    sel = sel.replace("[", '"').replace("]", '"')
    sql = f'SELECT {sel} FROM src' + (f" WHERE {where.replace('[', chr(34)).replace(']', chr(34))}" if where else "") + (f" GROUP BY {grp.replace('[', chr(34)).replace(']', chr(34))}" if grp else "")
    return sql


def _read_rows(blob_store, blob_mod, acct, container, prefix, ser):
    key = f"{acct}/{container}"
    if blob_store is None or not blob_store.container_exists(key):
        raise _E(400, "InputContainerNotFound", f"The input container '{container}' in storage account '{acct}' does not exist.")
    rows, files = [], 0
    for name in sorted(blob_store.container_blobs(key)):
        if prefix and not name.startswith(prefix):
            continue
        r = blob_mod.dispatch(blob_store, "GET", f"/{container}/{name}", {}, {}, b"", account=acct)
        if r.status != 200:
            continue
        text = r.body.decode("utf-8-sig") if isinstance(r.body, (bytes, bytearray)) else str(r.body)
        files += 1
        t = ser.get("type")
        if t == "Json":
            s = text.strip()
            if s.startswith("["):
                rows += [x for x in json.loads(s) if isinstance(x, dict)]
            else:
                for ln in s.splitlines():
                    if ln.strip():
                        try:
                            o = json.loads(ln)
                        except ValueError:
                            raise _E(400, "InputDeserializationError", f"Blob '{name}' contains a line that is not valid JSON.")
                        if isinstance(o, dict):
                            rows.append(o)
        elif t == "Csv":
            rows += list(csv.DictReader(io.StringIO(text), delimiter=(ser.get("properties") or {}).get("fieldDelimiter", ",")))
        else:
            raise _E(400, "UnsupportedSerialization", f"{t} input deserialization is not supported by the runner.")
    return rows, files


def run_job(job, blob_store, blob_mod):
    """Execute the job's transformation over its Blob input; returns the run summary. Raises _E for an honest failure."""
    tr = next(iter(job["_transformation"].values()), None)
    d = validate_query(job, tr["properties"]["query"])
    inp = next(v for k, v in job["_inputs"].items() if k.lower() == d["frm"].lower())["properties"]
    ids = inp["datasource"]
    if ids["type"] != "Microsoft.Storage/Blob":
        raise _E(400, "InputNotSupported", f"Input '{d['frm']}' is {ids['type']}: Vyomi has no Event Hubs / IoT Hub / SQL streaming data plane, so only Blob inputs are processed.")
    outn = d["into"] or next(iter(job["_outputs"]))
    out = next(v for k, v in job["_outputs"].items() if k.lower() == outn.lower())["properties"]
    ods = out["datasource"]
    if ods["type"] != "Microsoft.Storage/Blob":
        raise _E(400, "OutputNotSupported", f"Output '{outn}' is {ods['type']}: the runner can only write Blob outputs (line-separated JSON).")
    ip = ids["properties"]
    prefix = re.split(r"\{", ip.get("pathPattern") or "")[0]
    rows, files = _read_rows(blob_store, blob_mod, ip["storageAccounts"][0]["accountName"], ip["container"], prefix, inp["serialization"])
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE src (" + ", ".join(f'"{c}"' for c in cols or ["_"]) + ")")
        for r in rows:
            db.execute(f"INSERT INTO src VALUES ({','.join('?' * len(cols))})", [json.dumps(r[c]) if isinstance(r.get(c), (dict, list)) else r.get(c) for c in cols])
        try:
            cur = db.execute(_sql_for(d))
        except sqlite3.Error as e:
            raise _E(400, "InvalidQuery", f"The query failed to execute: {e}")
        names = [c[0] for c in cur.description]
        result = [dict(zip(names, row)) for row in cur.fetchall()]
    finally:
        db.close()
    op = ods["properties"]
    oacct, ocont = op["storageAccounts"][0]["accountName"], op["container"]
    okey = f"{oacct}/{ocont}"
    if blob_store is None:
        raise _E(400, "OutputUnavailable", "No Blob store is attached.")
    if not blob_store.container_exists(okey):
        blob_store.create_container(okey)
    path = (re.split(r"\{", op.get("pathPattern") or "")[0] or "") + f"{job['name']}-{outn}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    body = "\n".join(json.dumps(r) for r in result).encode()
    r = blob_mod.dispatch(blob_store, "PUT", f"/{ocont}/{path}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": "application/json"}, body, account=oacct)
    if r.status >= 300:
        raise _E(400, "OutputWriteFailed", f"Writing the output blob failed ({r.status}).")
    return {"inputFiles": files, "inputEvents": len(rows), "outputEvents": len(result), "outputBlob": f"https://{oacct}.blob.core.windows.net/{ocont}/{path}", "ranAt": _now()}


# ── ARM surface ─────────────────────────────────────────────────────────────────────────
def _rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{JOB_T}/{name}"


def _new_job(sub, rg, name, payload):
    if not _NAME.match(name):
        raise _bad(f"The streaming job name '{name}' is invalid (2-63 letters, digits, '-' or '_').")
    if not payload.get("location"):
        raise _bad("The location property is required for this definition.", "LocationRequired")
    pr = payload.get("properties") or {}
    cl = str(pr.get("compatibilityLevel") or "1.2")
    if cl not in COMPAT:
        raise _bad(f"compatibilityLevel '{cl}' is invalid. Allowed: {', '.join(COMPAT)}.")
    jt = pr.get("jobType") or "Cloud"
    if jt not in ("Cloud", "Edge"):
        raise _bad("jobType must be Cloud or Edge.")
    sku = (payload.get("sku") or {}).get("name") or "Standard"
    if sku not in ("Standard", "StandardV2"):
        raise _bad("sku.name must be Standard or StandardV2.")
    rid = _rid(sub, rg, name)
    rec = {"id": rid, "name": name, "type": JOB_T, "location": payload["location"], "tags": dict(payload.get("tags") or {}), "sku": {"name": sku},
           "identity": payload.get("identity") or None,
           "properties": {"jobId": str(uuid.uuid4()), "provisioningState": "Succeeded", "jobState": "Created", "jobType": jt, "dataLocale": pr.get("dataLocale") or "en-US",
                          "outputStartMode": pr.get("outputStartMode") or "JobStartTime", "eventsOutOfOrderPolicy": pr.get("eventsOutOfOrderPolicy") or "Adjust",
                          "outputErrorPolicy": pr.get("outputErrorPolicy") or "Stop", "eventsOutOfOrderMaxDelayInSeconds": pr.get("eventsOutOfOrderMaxDelayInSeconds", 0),
                          "eventsLateArrivalMaxDelayInSeconds": pr.get("eventsLateArrivalMaxDelayInSeconds", 5), "compatibilityLevel": cl,
                          "createdDate": _now(), "etag": uuid.uuid4().hex},
           "_type": JOB_T, "_sub": sub, "_rg": rg, "_inputs": {}, "_outputs": {}, "_transformation": {}}
    for k, bucket in (("inputs", "_inputs"), ("outputs", "_outputs")):
        for c in pr.get(k) or []:
            rec[bucket][c["name"]] = _child(k, rec, c["name"], c, None)
    if pr.get("transformation"):
        rec["_transformation"]["Transformation"] = _transformation(rec, pr["transformation"].get("name") or "Transformation", pr["transformation"])
        rec["_transformation"]["Transformation"]["name"] = pr["transformation"].get("name") or "Transformation"
    return rec


def _job_view(rec):
    v = _view(rec)
    v["properties"] = dict(rec["properties"])
    v["properties"]["inputs"] = list(rec["_inputs"].values())
    v["properties"]["outputs"] = list(rec["_outputs"].values())
    tr = next(iter(rec["_transformation"].values()), None)
    v["properties"]["transformation"] = tr
    return v


def dispatch(state, method, sub, rg, namespace, chain, payload=None, query=None, blob_store=None, blob_mod=None):
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, blob_store, blob_mod)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _jobs(state):
    return [r for r in state.values() if isinstance(r, dict) and r.get("_type") == JOB_T]


def _dispatch(state, method, sub, rg, chain, payload, blob_store, blob_mod):
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_job_view(r) for r in _jobs(state) if r["_sub"] == sub and (rg is None or r["_rg"].lower() == rg.lower())]})
    if rg is None:
        return _err(400, "InvalidResourceId", "Streaming jobs must be addressed in a resource group.")
    name = chain[1]
    rid = _rid(sub, rg, name)
    rec = state.get(rid.lower())
    low = [c.lower() for c in chain]
    if len(chain) == 2:
        if method == "GET":
            if rec is None:
                raise _E(404, "ResourceNotFound", f"The Resource '{JOB_T}/{name}' under resource group '{rg}' was not found.")
            return _ok(_job_view(rec))
        if method in ("PUT", "PATCH"):
            if rec is None and method == "PATCH":
                raise _E(404, "ResourceNotFound", f"The Resource '{JOB_T}/{name}' under resource group '{rg}' was not found.")
            if rec is None:
                rec = _new_job(sub, rg, name, payload)
                state[rid.lower()] = rec
                return _ok(_job_view(rec), 201)
            if rec["properties"]["jobState"] in ("Running", "Starting"):
                raise _E(409, "JobMustBeStopped", "The streaming job must be stopped before its properties can be changed.")
            pr = payload.get("properties") or {}
            for k in ("dataLocale", "eventsOutOfOrderPolicy", "outputErrorPolicy", "eventsOutOfOrderMaxDelayInSeconds", "eventsLateArrivalMaxDelayInSeconds", "compatibilityLevel", "outputStartMode"):
                if k in pr:
                    if k == "compatibilityLevel" and str(pr[k]) not in COMPAT:
                        raise _bad(f"compatibilityLevel '{pr[k]}' is invalid. Allowed: {', '.join(COMPAT)}.")
                    rec["properties"][k] = pr[k]
            if "tags" in payload:
                rec["tags"] = dict(payload["tags"] or {})
            return _ok(_job_view(rec))
        if method == "DELETE":
            if rec is not None and rec["properties"]["jobState"] in ("Running", "Starting"):
                raise _E(409, "JobMustBeStopped", "A running streaming job cannot be deleted; stop it first.")
            state.pop(rid.lower(), None)
            return _ok(None, 200 if rec is not None else 204)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if rec is None:
        raise _E(404, "ResourceNotFound", f"The Resource '{JOB_T}/{name}' under resource group '{rg}' was not found.")
    st = rec["properties"]
    if low[2] in ("start", "stop") and len(chain) == 3:
        if method != "POST":
            return _err(405, "MethodNotAllowed", "Use POST.")
        if low[2] == "start":
            if st["jobState"] in ("Running", "Starting"):
                raise _E(409, "JobStateConflict", f"The job is already {st['jobState']}.")
            mode = payload.get("outputStartMode") or st["outputStartMode"]
            if mode not in ("JobStartTime", "CustomTime", "LastOutputEventTime"):
                raise _bad("outputStartMode must be JobStartTime, CustomTime or LastOutputEventTime.")
            if mode == "CustomTime" and not payload.get("outputStartTime"):
                raise _bad("outputStartMode CustomTime requires outputStartTime.")
            if mode == "LastOutputEventTime" and not st.get("lastOutputEventTime"):
                raise _bad("LastOutputEventTime is not valid: the job has not produced output yet.")
            if not rec["_inputs"] or not rec["_outputs"] or not rec["_transformation"]:
                raise _E(400, "JobIncomplete", "A streaming job needs at least one input, one output and a transformation before it can start.")
            st["outputStartMode"] = mode
            try:
                st["vyomiRun"] = run_job(rec, blob_store, blob_mod)
                st["jobState"], st["lastOutputEventTime"] = "Running", _now()
                st.pop("vyomiError", None)
            except _E as e:
                st["jobState"], st["vyomiError"] = "Failed", {"code": e.code, "message": e.message}
                return _err(e.status, e.code, e.message)
            return _ok(None, 200)
        if st["jobState"] not in ("Running", "Starting", "Failed"):
            raise _E(409, "JobStateConflict", f"The job is {st['jobState']}; only a running job can be stopped.")
        st["jobState"] = "Stopped"
        return _ok(None, 200)
    if low[2] in ("inputs", "outputs"):
        bucket = rec["_inputs" if low[2] == "inputs" else "_outputs"]
        if len(chain) == 3:
            return _ok({"value": list(bucket.values())}) if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
        cn = chain[3]
        cur = next((v for k, v in bucket.items() if k.lower() == cn.lower()), None)
        if len(chain) == 5 and low[4] == "test" and method == "POST":
            if cur is None:
                raise _E(404, "ResourceNotFound", f"{low[2][:-1]} '{cn}' was not found.")
            ds = cur["properties"]["datasource"]
            if ds["type"] != "Microsoft.Storage/Blob":
                return _ok({"status": "TestFailed", "error": {"message": f"Connectivity test for {ds['type']} is not available: no such data plane in Vyomi."}})
            p = ds["properties"]
            ok = blob_store is not None and blob_store.container_exists(f"{p['storageAccounts'][0]['accountName']}/{p['container']}")
            return _ok({"status": "TestSucceeded" if ok else "TestFailed", **({} if ok else {"error": {"message": f"Container '{p['container']}' does not exist."}})})
        if len(chain) != 4:
            return _err(404, "ResourceTypeNotSupported", "Unsupported path.")
        if method == "GET":
            if cur is None:
                raise _E(404, "ResourceNotFound", f"{low[2][:-1]} '{cn}' was not found.")
            return _ok(cur)
        if method in ("PUT", "PATCH"):
            if st["jobState"] in ("Running", "Starting"):
                raise _E(409, "JobMustBeStopped", "Stop the streaming job before changing its inputs or outputs.")
            c = _child(low[2], rec, cn, payload, cur)
            bucket[cn] = c
            return _ok(c, 200 if cur else 201)
        if method == "DELETE":
            if st["jobState"] in ("Running", "Starting"):
                raise _E(409, "JobMustBeStopped", "Stop the streaming job before changing its inputs or outputs.")
            if cur is not None:
                bucket.pop(cur["name"], None)
            return _ok(None, 200 if cur else 204)
    if low[2] == "transformations":
        if len(chain) == 3:
            return _ok({"value": list(rec["_transformation"].values())}) if method == "GET" else _err(405, "MethodNotAllowed", "Collection supports GET only.")
        tn = chain[3]
        if method == "GET":
            cur = rec["_transformation"].get(tn)
            if cur is None:
                raise _E(404, "ResourceNotFound", f"transformation '{tn}' was not found.")
            return _ok(cur)
        if method in ("PUT", "PATCH"):
            if st["jobState"] in ("Running", "Starting"):
                raise _E(409, "JobMustBeStopped", "Stop the streaming job before changing its transformation.")
            if rec["_transformation"] and tn not in rec["_transformation"]:
                raise _E(409, "Conflict", "A streaming job has exactly one transformation.")
            t = _transformation(rec, tn, payload)
            try:
                validate_query(rec, t["properties"]["query"])
            except _E as e:
                raise _E(400, e.code, e.message)
            rec["_transformation"][tn] = t
            return _ok(t)
    if low[2] == "testquery" and method == "POST":
        q = (payload.get("query") or "")
        try:
            validate_query(rec, q)
        except _E as e:
            return _ok({"status": "TestFailed", "error": {"code": e.code, "message": e.message}})
        return _ok({"status": "TestSucceeded"})
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(chain[2:])}' is not supported on streaming jobs.")


def resource_types():
    return [(JOB_T, API)]
