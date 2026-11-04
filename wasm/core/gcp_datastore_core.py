# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Cloud Datastore API v1 (Firestore in Datastore mode) — substrate-independent, stdlib only.

Speaks the native **Datastore REST API v1** (`POST /v1/projects/{p}:lookup|runQuery|runAggregationQuery|
commit|beginTransaction|rollback|allocateIds|reserveIds`, plus the Admin `projects/{p}/indexes`) so the
native `google-cloud-datastore` client (REST transport / `DATASTORE_EMULATOR_HOST`-style endpoint) works
unchanged. Entities live in the SAME FirestoreStore as the Firestore data plane: a Datastore-mode
database is a Firestore database with `type = DATASTORE_MODE`; an entity is a document whose relative
path is the key path (`Kind/name`, `Kind/__id123__`, ancestors prefixed) and whose entry carries the
Datastore entity. Native-mode databases refuse the Datastore API (FAILED_PRECONDITION) like Google Cloud.

Real behaviour: key validation + incomplete-key id allocation, insert/update/upsert/delete with
ALREADY_EXISTS / NOT_FOUND, versions + baseVersion conflicts, transactions (all-or-nothing commit),
property filters (= < <= > >= != IN NOT_IN HAS_ANCESTOR, composite AND/OR), multi-valued array
properties, ordering with Datastore's cross-type value order, limit/offset/cursors, projections,
keys-only, a GQL `SELECT` subset, aggregations (COUNT/SUM/AVG), namespaces, and composite-index
requirements (a query that needs a composite index fails FAILED_PRECONDITION until the index exists).
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

try:
    from core.gcp_firestore_core import FirestoreResponse, FirestoreStore
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_firestore_core import FirestoreResponse, FirestoreStore  # type: ignore


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status: int, gstatus: str, msg: str) -> FirestoreResponse:
    return FirestoreResponse(status, {"content-type": "application/json"},
                             json.dumps({"error": {"code": status, "message": msg, "status": gstatus}}).encode())


def _json(obj) -> FirestoreResponse:
    return FirestoreResponse(200, {"content-type": "application/json"}, json.dumps(obj).encode())


class _E(Exception):
    def __init__(self, status, gstatus, msg):
        self.r = _err(status, gstatus, msg)


# ── keys ───────────────────────────────────────────────────────────────────
def _key_rel(key: dict, *, allow_incomplete=False) -> str | None:
    """Relative path for a Key. None when the last element is incomplete (and allowed)."""
    path = key.get("path") or []
    if not path:
        raise _E(400, "INVALID_ARGUMENT", "Key path must not be empty.")
    parts = []
    for i, el in enumerate(path):
        kind = el.get("kind")
        if not kind or "/" in kind or kind.startswith("__") and kind.endswith("__"):
            raise _E(400, "INVALID_ARGUMENT", f"Invalid kind {kind!r} in key path element {i}.")
        if "name" in el and "id" in el:
            raise _E(400, "INVALID_ARGUMENT", "A key path element cannot have both id and name.")
        if "name" in el:
            if not el["name"] or len(el["name"].encode()) > 1500 or el["name"].startswith("__") and el["name"].endswith("__"):
                raise _E(400, "INVALID_ARGUMENT", f"Invalid key name {el['name']!r}.")
            parts += [kind, el["name"]]
        elif "id" in el:
            if int(el["id"]) <= 0:
                raise _E(400, "INVALID_ARGUMENT", "Key id must be positive.")
            parts += [kind, f"__id{int(el['id'])}__"]
        else:
            if i != len(path) - 1 or not allow_incomplete:
                raise _E(400, "INVALID_ARGUMENT", "Only the last path element of a key may be incomplete, and only on insert.")
            return None
    rel = "/".join(parts)
    ns = (key.get("partitionId") or {}).get("namespaceId")
    return f"@{ns}:{rel}" if ns else rel


def _norm_key(key: dict, project: str, db: str) -> dict:
    pid = {"projectId": project}
    if db != "(default)":
        pid["databaseId"] = db
    ns = (key.get("partitionId") or {}).get("namespaceId")
    if ns:
        pid["namespaceId"] = ns
    path = []
    for el in key["path"]:
        e = {"kind": el["kind"]}
        if "id" in el:
            e["id"] = str(int(el["id"]))
        elif "name" in el:
            e["name"] = el["name"]
        path.append(e)
    return {"partitionId": pid, "path": path}


# ── values: ordering, comparison, validation ───────────────────────────────
_RANK = {"nullValue": 0, "booleanValue": 1, "integerValue": 2, "doubleValue": 2, "timestampValue": 3,
         "stringValue": 4, "blobValue": 5, "keyValue": 6, "geoPointValue": 7, "entityValue": 8}


def _vkind(v: dict) -> str:
    for k in v:
        if k in _RANK or k == "arrayValue":
            return k
    return "nullValue"


def _sortkey(v: dict):
    k = _vkind(v)
    if k == "nullValue": return (0, 0)
    if k == "booleanValue": return (1, int(bool(v[k])))
    if k == "integerValue": return (2, int(v[k]))
    if k == "doubleValue": return (2, float(v[k]))
    if k == "timestampValue": return (3, v[k])
    if k == "stringValue": return (4, v[k])
    if k == "blobValue": return (5, v[k])
    if k == "keyValue": return (6, tuple((e["kind"], str(e.get("id", e.get("name", "")))) for e in v[k]["path"]))
    if k == "geoPointValue": return (7, (v[k].get("latitude", 0), v[k].get("longitude", 0)))
    return (8, json.dumps(v[k], sort_keys=True))


def _scalars(v: dict) -> list:
    return list(v["arrayValue"].get("values", [])) if "arrayValue" in v else [v]


def _prop_values(ent: dict, prop: str) -> list:
    if prop == "__key__":
        return [{"keyValue": ent["key"]}]
    cur = (ent.get("properties") or {})
    parts = prop.split(".")
    v = None
    for i, p in enumerate(parts):
        if p not in cur:
            return []
        v = cur[p]
        if i < len(parts) - 1:
            if "entityValue" not in v:
                return []
            cur = v["entityValue"].get("properties") or {}
    return _scalars(v)


def _cmp(a, b) -> int:
    return (a > b) - (a < b)


def _op_match(op: str, vals: list, want: dict) -> bool:
    if op in ("IN", "NOT_IN"):
        pool = [_sortkey(x) for x in _scalars(want)]
        hit = any(_sortkey(v) in pool for v in vals)
        return hit if op == "IN" else (bool(vals) and not hit)
    wk = _sortkey(want)
    if op == "NOT_EQUAL":
        return bool(vals) and all(_sortkey(v) != wk for v in vals)
    for v in vals:
        c = _cmp(_sortkey(v), wk)
        if op == "EQUAL" and c == 0: return True
        if op == "LESS_THAN" and c < 0: return True
        if op == "LESS_THAN_OR_EQUAL" and c <= 0: return True
        if op == "GREATER_THAN" and c > 0: return True
        if op == "GREATER_THAN_OR_EQUAL" and c >= 0: return True
    return False


def _filter_match(ent: dict, f: dict | None) -> bool:
    if not f:
        return True
    if "compositeFilter" in f:
        cf = f["compositeFilter"]
        rs = [_filter_match(ent, x) for x in cf.get("filters", [])]
        return any(rs) if cf.get("op") == "OR" else all(rs)
    pf = f.get("propertyFilter") or {}
    op = pf.get("op", "EQUAL")
    prop = (pf.get("property") or {}).get("name", "")
    if op == "HAS_ANCESTOR":
        want = pf["value"]["keyValue"]["path"]
        mine = ent["key"]["path"]
        return len(mine) >= len(want) and all(_same_el(a, b) for a, b in zip(mine, want))
    return _op_match(op, _prop_values(ent, prop), pf.get("value") or {})


def _same_el(a, b):
    return a.get("kind") == b.get("kind") and str(a.get("id", a.get("name"))) == str(b.get("id", b.get("name")))


def _validate_value(v: dict, path="") -> None:
    if not isinstance(v, dict):
        raise _E(400, "INVALID_ARGUMENT", f"Invalid value for property {path}.")
    if "stringValue" in v and len(v["stringValue"].encode()) > 1048487:
        raise _E(400, "INVALID_ARGUMENT", "The value of property is too long. Maximum is 1048487 bytes.")
    if "arrayValue" in v:
        for x in v["arrayValue"].get("values", []):
            if "arrayValue" in x:
                raise _E(400, "INVALID_ARGUMENT", "Nested array values are not allowed.")
            _validate_value(x, path)
    if "entityValue" in v:
        for k, x in ((v["entityValue"].get("properties")) or {}).items():
            _validate_value(x, f"{path}.{k}")


# ── store helpers ──────────────────────────────────────────────────────────
def _db_for(store: FirestoreStore, project: str, body: dict, headers: dict | None) -> str:
    db = (body.get("databaseId")
          or ((body.get("partitionId") or {}).get("databaseId")))
    if not db:
        for k, v in (headers or {}).items():
            if str(k).lower() == "x-goog-request-params":
                m = re.search(r"database_id=([^&]+)", str(v))
                if m:
                    db = unquote(m.group(1))
    db = db or "(default)"
    rec = store.databases.get(db)
    if rec is None:
        raise _E(404 if db != "(default)" else 400, "NOT_FOUND" if db != "(default)" else "FAILED_PRECONDITION",
                 f"Datastore database {db} does not exist; create a Firestore database in Datastore mode first.")
    if rec.get("type") != "DATASTORE_MODE":
        raise _E(400, "FAILED_PRECONDITION", "The Cloud Datastore API is not available for Firestore in Native mode. "
                 "Create a database in Datastore mode to use it.")
    return db


def _ents(store: FirestoreStore, db: str, ns: str | None):
    pre = f"{db}/"
    for k, e in list(store.documents.items()):
        if not k.startswith(pre) or not isinstance(e, dict) or "datastore" not in e:
            continue
        ent = e["datastore"]
        if (ent["key"]["partitionId"].get("namespaceId") or None) != (ns or None):
            continue
        yield k[len(pre):], e


def _all_ents(store: FirestoreStore, db: str):
    pre = f"{db}/"
    for k, e in list(store.documents.items()):
        if k.startswith(pre) and isinstance(e, dict) and "datastore" in e:
            yield k[len(pre):], e


def _next_id(store: FirestoreStore, db: str) -> int:
    meta = store.documents.setdefault(f"{db}/__ds_meta__", {"nextId": 5629499534213120})
    meta["nextId"] += 1
    return meta["nextId"]


def _ns(body: dict) -> str | None:
    return (body.get("partitionId") or {}).get("namespaceId") or None


# ── queries ────────────────────────────────────────────────────────────────
def _gql_to_query(gql: str, named: dict, positional: list) -> dict:
    m = re.match(r"^\s*SELECT\s+(.*?)\s+FROM\s+(\w+)\s*(?:WHERE\s+(.*?))?\s*(?:ORDER\s+BY\s+(.*?))?\s*(?:LIMIT\s+(@?\w+))?\s*(?:OFFSET\s+(@?\w+))?\s*$", gql, re.I | re.S)
    if not m:
        raise _E(400, "INVALID_ARGUMENT", "Unsupported GQL; supported: SELECT <* | props | __key__> FROM <kind> [WHERE ...] [ORDER BY ...] [LIMIT n] [OFFSET n].")
    proj, kind, where, order, limit, offset = m.groups()
    q: dict = {"kind": [{"name": kind}]}
    if proj.strip() == "__key__":
        q["projection"] = [{"property": {"name": "__key__"}}]
    elif proj.strip() != "*":
        q["projection"] = [{"property": {"name": p.strip()}} for p in proj.split(",")]

    def val(tok: str) -> dict:
        tok = tok.strip()
        if tok.startswith("@"):
            nm = tok[1:]
            if nm.isdigit():
                return _gql_arg(positional[int(nm) - 1])
            return _gql_arg(named[nm])
        if tok[:1] in "'\"":
            return {"stringValue": tok[1:-1]}
        if tok.lower() in ("true", "false"):
            return {"booleanValue": tok.lower() == "true"}
        if tok.lower() == "null":
            return {"nullValue": None}
        return {"doubleValue": float(tok)} if "." in tok else {"integerValue": str(int(tok))}

    if where:
        fl = []
        for part in re.split(r"\s+AND\s+", where, flags=re.I):
            mm = re.match(r"^\s*(\S+?)\s*(=|!=|<=|>=|<|>|\s+IN\s+)\s*(.+?)\s*$", part, re.I)
            hm = re.match(r"^\s*__key__\s+HAS\s+ANCESTOR\s+(.+?)\s*$", part, re.I)
            if hm:
                fl.append({"propertyFilter": {"property": {"name": "__key__"}, "op": "HAS_ANCESTOR", "value": val(hm.group(1))}})
                continue
            if not mm:
                raise _E(400, "INVALID_ARGUMENT", f"Cannot parse GQL condition: {part.strip()}")
            op = {"=": "EQUAL", "!=": "NOT_EQUAL", "<": "LESS_THAN", "<=": "LESS_THAN_OR_EQUAL", ">": "GREATER_THAN",
                  ">=": "GREATER_THAN_OR_EQUAL"}.get(mm.group(2).strip(), "IN")
            v = mm.group(3)
            value = ({"arrayValue": {"values": [val(x) for x in v.strip("()[] ").split(",")]}} if op == "IN" else val(v))
            fl.append({"propertyFilter": {"property": {"name": mm.group(1)}, "op": op, "value": value}})
        q["filter"] = fl[0] if len(fl) == 1 else {"compositeFilter": {"op": "AND", "filters": fl}}
    if order:
        q["order"] = []
        for part in order.split(","):
            toks = part.split()
            q["order"].append({"property": {"name": toks[0]}, "direction": "DESCENDING" if len(toks) > 1 and toks[1].upper() == "DESC" else "ASCENDING"})
    if limit:
        q["limit"] = int(val(limit).get("integerValue", 0))
    if offset:
        q["offset"] = int(val(offset).get("integerValue", 0))
    return q


def _gql_arg(a: dict) -> dict:
    if "value" in a:
        return a["value"]
    if "cursor" in a:
        return {"stringValue": a["cursor"]}
    return a


def _needs_index(q: dict) -> list | None:
    """Return the property list a composite index must cover, or None when built-in indexes suffice."""
    props_ineq, props_eq, orders = [], [], q.get("order") or []

    def walk(f):
        if not f:
            return
        if "compositeFilter" in f:
            for x in f["compositeFilter"].get("filters", []):
                walk(x)
            return
        pf = f.get("propertyFilter") or {}
        name = (pf.get("property") or {}).get("name")
        if pf.get("op") == "HAS_ANCESTOR" or name == "__key__":
            return
        (props_ineq if pf.get("op") in ("LESS_THAN", "LESS_THAN_OR_EQUAL", "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "NOT_EQUAL", "NOT_IN") else props_eq).append(name)
    walk(q.get("filter"))
    ordered = [(o.get("property") or {}).get("name") for o in orders if (o.get("property") or {}).get("name") != "__key__"]
    ineq = sorted(set(props_ineq))
    if len(ineq) > 1:
        return ineq
    # inequality on X must be ordered by X first; ordering by anything else needs a composite index
    if ineq and ordered and ordered[0] != ineq[0]:
        return ineq + ordered
    if len(ordered) > 1:
        return ordered
    if ordered and props_eq and any(p != ordered[0] for p in props_eq):
        return sorted(set(props_eq)) + ordered
    return None


def _index_covers(idx: dict, kind: str, need: list, ordered_dirs: list) -> bool:
    if idx.get("kind") != kind or idx.get("state") != "READY":
        return False
    names = [p["name"] for p in idx.get("properties") or []]
    return all(n in names for n in need)


def _run_query(store, db, project, body, headers) -> FirestoreResponse:
    ns = _ns(body)
    q = body.get("query")
    if "gqlQuery" in body:
        g = body["gqlQuery"]
        q = _gql_to_query(g.get("queryString", ""), g.get("namedBindings") or {}, g.get("positionalBindings") or [])
    if not q:
        raise _E(400, "INVALID_ARGUMENT", "query or gqlQuery is required.")
    kinds = [k["name"] for k in q.get("kind") or []]
    if len(kinds) > 1:
        raise _E(400, "INVALID_ARGUMENT", "Only one kind per query is supported.")
    if kinds and kinds[0] in ("__kind__", "__namespace__"):     # metadata queries (Datastore Studio's kind picker)
        names = sorted({(e["datastore"]["key"]["path"][-1]["kind"] if kinds[0] == "__kind__" else
                         (e["datastore"]["key"]["partitionId"].get("namespaceId") or ""))
                        for _r, e in _ents(store, db, ns if kinds[0] == "__kind__" else "\0all")} if kinds[0] == "__kind__" else
                       {(e["datastore"]["key"]["partitionId"].get("namespaceId") or "") for _r, e in _all_ents(store, db)})
        res = [{"entity": {"key": {"partitionId": {"projectId": project}, "path": [{"kind": kinds[0], **({"name": n} if n else {"id": "1"})}]}}, "version": "1"} for n in names]
        return _json({"batch": {"entityResultType": "KEY_ONLY", "entityResults": res, "moreResults": "NO_MORE_RESULTS",
                                "endCursor": _encode_cursor(len(res)), "snapshotVersion": "1", "readTime": _now()}})
    need = _needs_index(q)
    if need and kinds:
        if not any(_index_covers(i, kinds[0], need, []) for i in _indexes(store, db).values()):
            raise _E(400, "FAILED_PRECONDITION",
                     "no matching index found. recommended index is:\n- kind: %s\n  properties:\n%s" % (
                         kinds[0], "\n".join(f"  - name: {n}" for n in need)))
    rows = []
    for rel, e in _ents(store, db, ns):
        ent = e["datastore"]
        if kinds and ent["key"]["path"][-1]["kind"] != kinds[0]:
            continue
        # entities missing an ordered/filtered property are excluded (Datastore semantics)
        ok = _filter_match(ent, q.get("filter"))
        if ok and all(_prop_values(ent, (o["property"])["name"]) for o in q.get("order") or [] if o["property"]["name"] != "__key__"):
            rows.append((rel, e))
    orders = q.get("order") or []

    # Python can't mix asc/desc in one sort key; stable multi-pass sort from last to first order
    rows.sort(key=lambda it: _sortkey({"keyValue": it[1]["datastore"]["key"]}))
    for o in reversed(orders):
        name, desc = o["property"]["name"], o.get("direction") == "DESCENDING"
        rows.sort(key=lambda it, name=name, desc=desc: (lambda vs: (max(vs) if desc else min(vs)))(
            [_sortkey(v) for v in _prop_values(it[1]["datastore"], name)] or [(-1, 0)]), reverse=desc)
    start = 0
    sc = q.get("startCursor")
    if sc:
        start = _decode_cursor(sc)
    total_after_start = rows[start:]
    off = int(q.get("offset") or 0)
    window = total_after_start[off:]
    lim = q.get("limit")
    lim = lim.get("value") if isinstance(lim, dict) else lim
    page = window[: int(lim)] if lim is not None else window
    more = "MORE_RESULTS_AFTER_LIMIT" if lim is not None and len(window) > int(lim) else "NO_MORE_RESULTS"
    proj = q.get("projection")
    keys_only = bool(proj) and all(p["property"]["name"] == "__key__" for p in proj)
    results = []
    for i, (rel, e) in enumerate(page):
        ent = json.loads(json.dumps(e["datastore"]))
        if keys_only:
            ent = {"key": ent["key"]}
        elif proj:
            names = [p["property"]["name"] for p in proj]
            ent["properties"] = {n: ent["properties"][n] for n in names if n in ent.get("properties", {})}
            for n, v in list(ent["properties"].items()):
                if "arrayValue" in v:
                    vs = v["arrayValue"].get("values", [])
                    ent["properties"][n] = vs[0] if vs else {"nullValue": None}
        results.append({"entity": ent, "version": str(e.get("version", 1)), "updateTime": e.get("updateTime"),
                        "createTime": e.get("createTime"), "cursor": _encode_cursor(start + off + i + 1)})
    end = _encode_cursor(start + off + len(page))
    return _json({"batch": {"entityResultType": "KEY_ONLY" if keys_only else ("PROJECTION" if proj else "FULL"),
                            "entityResults": results, "endCursor": end, "moreResults": more,
                            "skippedResults": min(off, len(total_after_start)), "snapshotVersion": "1", "readTime": _now()}})


def _encode_cursor(n: int) -> str:
    return base64.urlsafe_b64encode(f"vyomi-cursor:{n}".encode()).decode()


def _decode_cursor(c: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode().split(":")[1])
    except Exception:
        raise _E(400, "INVALID_ARGUMENT", "Invalid cursor.")


def _aggregate(store, db, project, body, headers) -> FirestoreResponse:
    agg = body.get("aggregationQuery") or {}
    inner = {"partitionId": body.get("partitionId"), "query": agg.get("nestedQuery") or {}}
    if "gqlQuery" in body or "gqlQuery" in agg:
        inner = {"partitionId": body.get("partitionId"), "gqlQuery": body.get("gqlQuery") or agg["gqlQuery"]}
    res = json.loads(_run_query(store, db, project, inner, headers).body)
    ents = [r["entity"] for r in res["batch"]["entityResults"]]
    props: dict = {}
    for a in agg.get("aggregations") or []:
        alias = a.get("alias") or "property_1"
        if "count" in a:
            up = (a["count"] or {}).get("upTo")
            n = len(ents)
            props[alias] = {"integerValue": str(min(n, int(up)) if up else n)}
        else:
            kind = "sum" if "sum" in a else "avg"
            prop = a[kind]["property"]["name"]
            nums = [float(v.get("integerValue", v.get("doubleValue", 0))) for e in ents for v in _prop_values(e, prop)
                    if "integerValue" in v or "doubleValue" in v]
            if kind == "sum":
                s = sum(nums)
                props[alias] = {"integerValue": str(int(s))} if all(float(x).is_integer() for x in nums) else {"doubleValue": s}
            else:
                props[alias] = {"doubleValue": sum(nums) / len(nums)} if nums else {"nullValue": None}
    return _json({"batch": {"aggregationResults": [{"aggregateProperties": props}], "moreResults": "NO_MORE_RESULTS", "readTime": _now()}})


# ── lookup / commit ────────────────────────────────────────────────────────
def _lookup(store, db, project, body) -> FirestoreResponse:
    found, missing = [], []
    for key in body.get("keys") or []:
        rel = _key_rel(key)
        e = store.documents.get(f"{db}/{rel}")
        if isinstance(e, dict) and "datastore" in e:
            found.append({"entity": e["datastore"], "version": str(e.get("version", 1)),
                          "createTime": e.get("createTime"), "updateTime": e.get("updateTime")})
        else:
            missing.append({"entity": {"key": _norm_key(key, project, db)}, "version": "1"})
    return _json({"found": found, "missing": missing, "readTime": _now()})


def _commit(store, db, project, body) -> FirestoreResponse:
    mode = body.get("mode", "TRANSACTIONAL")
    txn = body.get("transaction")
    if txn and txn not in _txns(store):
        raise _E(400, "INVALID_ARGUMENT", "Invalid transaction.")
    staged: dict = {}      # rel -> entry | None
    results = []
    ts = _now()

    def cur(rel):
        if rel in staged:
            return staged[rel]
        e = store.documents.get(f"{db}/{rel}")
        return e if isinstance(e, dict) and "datastore" in e else None

    for m in body.get("mutations") or []:
        op = next((k for k in ("insert", "update", "upsert", "delete") if k in m), None)
        if op is None:
            raise _E(400, "INVALID_ARGUMENT", "Mutation must set one of insert/update/upsert/delete.")
        if op == "delete":
            key = m["delete"]
            rel = _key_rel(key)
            c = cur(rel)
            _check_base(m, c)
            staged[rel] = None
            results.append({"key": None, "version": "1" if c is None else str(c.get("version", 1) + 1), "conflictDetected": False})
            continue
        ent = json.loads(json.dumps(m[op]))
        key = ent.get("key") or {}
        for n, v in (ent.get("properties") or {}).items():
            _validate_value(v, n)
        rel = _key_rel(key, allow_incomplete=(op in ("insert", "upsert")))
        allocated = False
        if rel is None:
            new_id = _next_id(store, db)
            key["path"][-1]["id"] = str(new_id)
            rel = _key_rel(key)
            allocated = True
        ent["key"] = _norm_key(key, project, db)
        c = cur(rel)
        if op == "insert" and c is not None:
            raise _E(409, "ALREADY_EXISTS", "entity already exists: " + json.dumps(ent["key"]["path"]))
        if op == "update" and c is None:
            raise _E(404, "NOT_FOUND", "no entity to update: " + json.dumps(ent["key"]["path"]))
        _check_base(m, c)
        ver = (c.get("version", 1) + 1) if c else 1
        staged[rel] = {"datastore": ent, "version": ver, "createTime": (c or {}).get("createTime", ts), "updateTime": ts}
        results.append({"key": ent["key"] if allocated else None, "version": str(ver), "conflictDetected": False,
                        "createTime": staged[rel]["createTime"], "updateTime": ts})
    for rel, e in staged.items():
        if e is None:
            store.delete(db, rel)
        else:
            store.put(db, rel, e)
    if txn:
        _txns(store).pop(txn, None)
    idx_updates = sum(len(((e or {}).get("datastore") or {}).get("properties") or {}) for e in staged.values())
    return _json({"mutationResults": results, "indexUpdates": idx_updates, "commitTime": ts})


def _check_base(m, c):
    bv = m.get("baseVersion")
    if bv is not None and (c is None or str(c.get("version", 1)) != str(bv)):
        raise _E(409, "ABORTED", "Aborted due to cross-transaction contention: the entity changed since baseVersion.")


def _txns(store) -> dict:
    return store.documents.setdefault("__ds_txns__", {})


# ── indexes (Admin API) ─────────────────────────────────────────────────────
def _indexes(store, db) -> dict:
    return store.indexes.setdefault(f"__ds__{db}", {})


def _admin(store, project, method, segs, body) -> FirestoreResponse:
    db = "(default)"
    idx = _indexes(store, db)
    if len(segs) == 1:
        if method == "GET":
            return _json({"indexes": sorted(idx.values(), key=lambda i: i["indexId"])})
        if method == "POST":
            if not body.get("kind") or not body.get("properties"):
                return _err(400, "INVALID_ARGUMENT", "kind and properties are required.")
            for p in body["properties"]:
                if p.get("direction") not in (None, "ASCENDING", "DESCENDING"):
                    return _err(400, "INVALID_ARGUMENT", "direction must be ASCENDING or DESCENDING.")
            sig = (body["kind"], body.get("ancestor", "NONE"), tuple((p["name"], p.get("direction", "ASCENDING")) for p in body["properties"]))
            for i in idx.values():
                if (i["kind"], i.get("ancestor", "NONE"), tuple((p["name"], p.get("direction", "ASCENDING")) for p in i["properties"])) == sig:
                    return _err(409, "ALREADY_EXISTS", "An index with this definition already exists.")
            iid = str(uuid.uuid4().int)[:16]
            rec = {"projectId": project, "indexId": iid, "kind": body["kind"], "ancestor": body.get("ancestor", "NONE"),
                   "properties": [{"name": p["name"], "direction": p.get("direction", "ASCENDING")} for p in body["properties"]],
                   "state": "READY"}
            idx[iid] = rec
            return _json({"name": f"projects/{project}/operations/{iid}", "metadata": {"@type": "type.googleapis.com/google.datastore.admin.v1.IndexOperationMetadata", "indexId": iid},
                          "done": True, "response": {"@type": "type.googleapis.com/google.datastore.admin.v1.Index", **rec}})
    elif len(segs) == 2:
        rec = idx.get(segs[1])
        if rec is None:
            return _err(404, "NOT_FOUND", f"Index {segs[1]} not found.")
        if method == "GET":
            return _json(rec)
        if method == "DELETE":
            idx.pop(segs[1])
            return _json({"name": f"projects/{project}/operations/{segs[1]}", "done": True})
    return _err(400, "INVALID_ARGUMENT", "Unsupported datastore admin request.")


# ── dispatch ───────────────────────────────────────────────────────────────
def is_datastore_path(path: str) -> bool:
    return bool(re.match(r"^/v1/projects/[^/:]+(:(lookup|runQuery|runAggregationQuery|commit|beginTransaction|rollback|allocateIds|reserveIds)|/indexes([/?]|$))", path.split("?", 1)[0]))


def dispatch(store: FirestoreStore, method: str, path: str, query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> FirestoreResponse:
    p = path.split("?", 1)[0]
    m = re.match(r"^/v1/projects/([^/:]+)(?::(\w+)|/(indexes(?:/[^/]+)?))$", p)
    if not m:
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project, verb, admin = m.group(1), m.group(2), m.group(3)
    try:
        data = json.loads(body.decode() or "{}") if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Request body is not valid JSON.")
    try:
        if admin:
            _db_for(store, project, {}, None)
            out = _admin(store, project, method.upper(), admin.split("/"), data)
        else:
            if method.upper() != "POST":
                return _err(405, "UNIMPLEMENTED", f"{verb} requires POST.")
            db = _db_for(store, project, data, headers)
            if verb == "lookup":
                out = _lookup(store, db, project, data)
            elif verb == "runQuery":
                out = _run_query(store, db, project, data, headers)
            elif verb == "runAggregationQuery":
                out = _aggregate(store, db, project, data, headers)
            elif verb == "commit":
                out = _commit(store, db, project, data)
            elif verb == "beginTransaction":
                tid = base64.b64encode(uuid.uuid4().bytes).decode()
                _txns(store)[tid] = {"at": _now()}
                out = _json({"transaction": tid})
            elif verb == "rollback":
                _txns(store).pop(data.get("transaction", ""), None)
                out = _json({})
            elif verb == "allocateIds":
                ks = []
                for k in data.get("keys") or []:
                    if _key_rel(k, allow_incomplete=True) is not None:
                        raise _E(400, "INVALID_ARGUMENT", "allocateIds requires incomplete keys.")
                    k = json.loads(json.dumps(k))
                    k["path"][-1]["id"] = str(_next_id(store, db))
                    ks.append(_norm_key(k, project, db))
                out = _json({"keys": ks})
            elif verb == "reserveIds":
                out = _json({})
            else:
                return _err(404, "NOT_FOUND", f"Unknown method {verb}")
    except _E as e:
        return e.r
    if method.upper() != "GET":
        store.persist()
    return out
