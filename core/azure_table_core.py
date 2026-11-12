"""Azure Table Storage data-plane core — substrate-independent, the OData/JSON analogue of
core/azure_queue_core.py (which speaks Queue's XML wire). Speaks enough of the native
**Azure Table REST API** for the `azure-data-tables` SDK (TableServiceClient / TableClient)
to create tables, list them, and insert/get/update/merge/delete/query entities.

NO fastapi / azure-* / socket / subprocess imports → loads under Pyodide. Self-contained
in-memory `AzureTableStore`; nothing else is required.

Wire is JSON (OData). Scope:
  - create table    POST /Tables           body {"TableName": "t"}            -> 201
  - list tables     GET  /Tables                                              -> 200 {"value":[...]}
  - delete table    DELETE /Tables('t')                                       -> 204 / 404
  - insert entity   POST /{t}              body entity (PartitionKey/RowKey)  -> 201
  - query entities  GET  /{t}               optional $filter / $top           -> 200 {"value":[...]}
  - get entity      GET  /{t}(PartitionKey='pk',RowKey='rk')                  -> 200 / 404
  - replace entity  PUT  /{t}(PartitionKey='pk',RowKey='rk')                  -> 204 (insert-or-replace)
  - merge entity    MERGE /{t}(PartitionKey='pk',RowKey='rk')                 -> 204 (insert-or-merge)
  - delete entity   DELETE /{t}(PartitionKey='pk',RowKey='rk')                -> 204 / 404

An OPTIONAL leading /{account} segment (Azurite style) is tolerated. $filter supports a
conservative subset: `Field eq 'value'` terms joined by ` and `. Errors carry the native
OData shape `{"odata.error": {"code", "message": {"value"}}}` plus `x-ms-error-code`.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


def _rowkey(pk: str, rk: str) -> str:
    """A JSON-dict-safe (string) key for an entity — plain `(pk, rk)` tuples don't
    survive nano_persist's json.dumps round-trip (non-str dict keys), so entities are
    indexed by this string instead; PartitionKey/RowKey still live in the entity body."""
    return f"{pk}\x1f{rk}"


class AzureTableStore:
    """In-memory Table account. `tables` maps table name -> {_rowkey(pk, rk): entity}."""

    def __init__(self) -> None:
        self.tables: dict[str, dict] = {}

    def table_exists(self, name: str) -> bool:
        return name in self.tables

    def persist(self) -> None:
        """Write-through hook (no-op in-memory; a backed subclass overrides it)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "0000Z"


def _etag() -> str:
    return 'W/"0x' + uuid.uuid4().hex[:16].upper() + '"'


def _err(status: int, code: str, message: str) -> Response:
    body = json.dumps({"odata.error": {"code": code, "message": {"lang": "en-us", "value": message}}}).encode()
    return Response(status=status, headers={"x-ms-error-code": code}, body=body)


def _ok(status: int, obj: dict | None, headers: dict | None = None) -> Response:
    body = b"" if obj is None else json.dumps(obj).encode()
    return Response(status=status, headers=headers or {}, body=body)


def _strip_account(p: str) -> str:
    if p.startswith("/devstoreaccount1/"):
        return p[len("/devstoreaccount1"):]
    if p == "/devstoreaccount1":
        return "/"
    return p


_SEG_RE = re.compile(r"^([^(]+)(\(.*\))?$")
_TABLES_DELETE_RE = re.compile(r"^\('([^']*)'\)$")
_ENTITY_KEY_RE = re.compile(r"^\(PartitionKey='((?:[^']|'')*)',RowKey='((?:[^']|'')*)'\)$")


def _unescape(s: str) -> str:
    return s.replace("''", "'")


def _view(entity: dict) -> dict:
    out = dict(entity)
    out["odata.etag"] = entity.get("_etag", _etag())
    out["Timestamp"] = entity.get("_ts", _now_iso())
    out.pop("_etag", None)
    out.pop("_ts", None)
    return out


def _apply_filter(rows: list, filt: str | None) -> list:
    if not filt:
        return rows
    terms = re.split(r"\s+and\s+", filt.strip())
    conds = []
    for t in terms:
        m = re.match(r"^(\w+)\s+eq\s+'((?:[^']|'')*)'$", t.strip())
        if m:
            conds.append((m.group(1), _unescape(m.group(2))))
    def keep(e):
        return all(str(e.get(f, "")) == v for f, v in conds)
    return [e for e in rows if keep(e)] if conds else rows


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: AzureTableStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> Response:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()
    if method == "POST" and headers.get("x-http-method", "").upper() == "MERGE":
        method = "MERGE"

    p = _strip_account(path.split("?", 1)[0])
    segs = [unquote(s) for s in p.split("/") if s != ""]
    if not segs:
        return _err(400, "InvalidInput", "No table specified.")

    m = _SEG_RE.match(segs[0])
    name, keypart = m.group(1), m.group(2)

    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        return _err(400, "InvalidInput", "Malformed JSON body.")

    # ---- Tables collection: /Tables or /Tables('name') ----
    if name == "Tables":
        if keypart is None:
            if method == "POST":
                tname = payload.get("TableName", "")
                if not tname:
                    return _err(400, "InvalidInput", "TableName is required.")
                if store.table_exists(tname):
                    return _err(409, "TableAlreadyExists", f"The table '{tname}' already exists.")
                store.tables[tname] = {}
                store.persist()
                return _ok(201, {"TableName": tname},
                           headers={"location": f"/Tables('{tname}')"})
            if method == "GET":
                rows = [{"TableName": t} for t in sorted(store.tables)]
                return _ok(200, {"value": rows})
            return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")
        dm = _TABLES_DELETE_RE.match(keypart)
        tname = dm.group(1) if dm else None
        if method == "DELETE" and tname is not None:
            if not store.table_exists(tname):
                return _err(404, "ResourceNotFound", f"The table '{tname}' does not exist.")
            store.tables.pop(tname, None)
            store.persist()
            return Response(status=204, body=b"", media_type=None)
        return _err(400, "InvalidInput", "Malformed Tables request.")

    # ---- entity ops: /{table}[(...)] ----
    table = name
    if not store.table_exists(table):
        return _err(404, "TableNotFound", f"The table '{table}' does not exist.")
    rows = store.tables[table]

    if keypart is None:
        if method == "POST":                      # insert entity
            pk, rk = payload.get("PartitionKey"), payload.get("RowKey")
            if pk is None or rk is None:
                return _err(400, "InvalidInput", "PartitionKey and RowKey are required.")
            if _rowkey(pk, rk) in rows:
                return _err(409, "EntityAlreadyExists", "The specified entity already exists.")
            entity = {k: v for k, v in payload.items() if not k.startswith("odata.")}
            entity["_etag"], entity["_ts"] = _etag(), _now_iso()
            rows[_rowkey(pk, rk)] = entity
            store.persist()
            v = _view(entity)
            return _ok(201, v, headers={"etag": v["odata.etag"]})
        if method == "GET":                        # query entities
            filt = query.get("$filter")
            out = _apply_filter([_view(e) for e in rows.values()], filt)
            top = query.get("$top")
            if top:
                try:
                    out = out[:int(top)]
                except ValueError:
                    pass
            return _ok(200, {"value": out})
        return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")

    em = _ENTITY_KEY_RE.match(keypart)
    if not em:
        return _err(400, "InvalidInput", "Malformed entity key.")
    pk, rk = _unescape(em.group(1)), _unescape(em.group(2))
    key = _rowkey(pk, rk)

    if method == "GET":
        if key not in rows:
            return _err(404, "ResourceNotFound", "The specified entity does not exist.")
        return _ok(200, _view(rows[key]))

    if method == "PUT":                             # insert-or-replace
        entity = {k: v for k, v in payload.items() if not k.startswith("odata.")}
        entity.setdefault("PartitionKey", pk)
        entity.setdefault("RowKey", rk)
        entity["_etag"], entity["_ts"] = _etag(), _now_iso()
        rows[key] = entity
        store.persist()
        return Response(status=204, headers={"etag": entity["_etag"]}, body=b"", media_type=None)

    if method == "MERGE":                           # insert-or-merge
        existing = dict(rows.get(key, {}))
        existing.update({k: v for k, v in payload.items() if not k.startswith("odata.")})
        existing.setdefault("PartitionKey", pk)
        existing.setdefault("RowKey", rk)
        existing["_etag"], existing["_ts"] = _etag(), _now_iso()
        rows[key] = existing
        store.persist()
        return Response(status=204, headers={"etag": existing["_etag"]}, body=b"", media_type=None)

    if method == "DELETE":
        if key not in rows:
            return _err(404, "ResourceNotFound", "The specified entity does not exist.")
        rows.pop(key, None)
        store.persist()
        return Response(status=204, body=b"", media_type=None)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")
