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
  - query entities  GET  /{t}() or /{t}    $filter (full OData) / $select / $top + continuation headers -> 200
  - batch           POST /$batch            multipart/mixed changeset (atomic, one partition)   -> 202
  - get entity      GET  /{t}(PartitionKey='pk',RowKey='rk')                  -> 200 / 404
  - replace entity  PUT  /{t}(PartitionKey='pk',RowKey='rk')                  -> 204 (insert-or-replace)
  - merge entity    MERGE|PATCH /{t}(PartitionKey='pk',RowKey='rk')           -> 204 (insert-or-merge)
  - optimistic concurrency: If-Match: <etag> -> 412 UpdateConditionNotSatisfied when stale; If-Match: * requires
    the entity to exist (404); no If-Match = insert-or-replace / insert-or-merge (the upsert modes)
  - delete entity   DELETE /{t}(PartitionKey='pk',RowKey='rk')                -> 204 / 404

An OPTIONAL leading /{account} segment (Azurite style) is tolerated. $filter supports the OData v3
subset Table storage defines: eq ne gt ge lt le, and / or / not, parentheses, string / int / long (123L) /
double / bool / datetime'..' / guid'..' literals. Errors carry the native
OData shape `{"odata.error": {"code", "message": {"value"}}}` plus `x-ms-error-code`.
"""
from __future__ import annotations

import copy
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


# ── $filter (OData v3 subset) ───────────────────────────────────────────────
_TOK = re.compile(r"""\s*(?:
    (?P<str>'(?:[^']|'')*')
  | (?P<dt>datetime'[^']*')
  | (?P<guid>guid'[^']*')
  | (?P<bin>(?:X|binary)'[^']*')
  | (?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?L?)
  | (?P<op>\(|\))
  | (?P<word>[A-Za-z_][A-Za-z0-9_.]*)
)""", re.X)


class _FilterError(ValueError):
    pass


def _tokenize(text: str) -> list:
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m or m.end() == pos:
            raise _FilterError(f"Invalid $filter near {text[pos:pos + 20]!r}.")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


def _parse_dt(v: str):
    v = v.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class _Filter:
    """Recursive-descent parser producing a predicate over an entity dict."""

    def __init__(self, text: str):
        self.t = _tokenize(text)
        self.i = 0
        self.node = self._or()
        if self.i != len(self.t):
            raise _FilterError("Invalid $filter: unexpected trailing tokens.")

    def _peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def _kw(self, *names):
        k, v = self._peek()
        return k == "word" and v.lower() in names

    def _or(self):
        left = self._and()
        while self._kw("or"):
            self.i += 1
            right = self._and()
            left = ("or", left, right)
        return left

    def _and(self):
        left = self._not()
        while self._kw("and"):
            self.i += 1
            right = self._not()
            left = ("and", left, right)
        return left

    def _not(self):
        if self._kw("not"):
            self.i += 1
            return ("not", self._not())
        return self._atom()

    def _atom(self):
        k, v = self._peek()
        if k == "op" and v == "(":
            self.i += 1
            n = self._or()
            if self._peek() != ("op", ")"):
                raise _FilterError("Invalid $filter: missing ')'.")
            self.i += 1
            return n
        left = self._operand()
        k, v = self._peek()
        if k != "word" or v.lower() not in ("eq", "ne", "gt", "ge", "lt", "le"):
            if left[0] == "lit" and isinstance(left[1], bool):      # a bare boolean literal / property
                return ("truth", left)
            if left[0] == "prop":
                return ("truth", left)
            raise _FilterError("Invalid $filter: comparison operator expected.")
        self.i += 1
        right = self._operand()
        return ("cmp", v.lower(), left, right)

    def _operand(self):
        k, v = self._peek()
        if k is None:
            raise _FilterError("Invalid $filter: operand expected.")
        self.i += 1
        if k == "str":
            return ("lit", _unescape(v[1:-1]), "str")
        if k == "dt":
            d = _parse_dt(v[len("datetime'"):-1])
            if d is None:
                raise _FilterError("Invalid datetime literal in $filter.")
            return ("lit", d, "dt")
        if k == "guid":
            return ("lit", v[len("guid'"):-1].lower(), "guid")
        if k == "bin":
            return ("lit", v[v.index("'") + 1:-1].lower(), "bin")
        if k == "num":
            if v.endswith("L"):
                return ("lit", int(v[:-1]), "int")
            return ("lit", float(v), "num") if re.search(r"[.eE]", v) else ("lit", int(v), "int")
        if k == "word":
            if v.lower() in ("true", "false"):
                return ("lit", v.lower() == "true", "bool")
            return ("prop", v)
        raise _FilterError("Invalid $filter.")


def _prop_value(e: dict, name: str):
    """(value, odata type) of an entity property, with Timestamp coming from the internal stamp."""
    if name == "Timestamp":
        return e.get("_ts", ""), "Edm.DateTime"
    return e.get(name), e.get(name + "@odata.type")


_MISSING = object()


def _coerce(val, vtype, lit_kind):
    """Bring a stored value to the literal's type so the two compare (None when impossible)."""
    if val is None:
        return _MISSING
    if lit_kind == "dt":
        return _parse_dt(val) if isinstance(val, str) else None
    if lit_kind in ("int", "num"):
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str) and vtype in ("Edm.Int64", "Edm.Double", "Edm.Int32"):
            try:
                return float(val) if vtype == "Edm.Double" else int(val)
            except ValueError:
                return None
        return None
    if lit_kind == "bool":
        return val if isinstance(val, bool) else None
    if lit_kind == "guid":
        return str(val).lower()
    if lit_kind == "bin":
        return str(val).lower()
    return val if isinstance(val, str) else None


def _eval(node, e: dict) -> bool:
    kind = node[0]
    if kind == "or":
        return _eval(node[1], e) or _eval(node[2], e)
    if kind == "and":
        return _eval(node[1], e) and _eval(node[2], e)
    if kind == "not":
        return not _eval(node[1], e)
    if kind == "truth":
        n = node[1]
        if n[0] == "lit":
            return bool(n[1])
        return _prop_value(e, n[1])[0] is True
    _, op, a, b = node
    if a[0] == "lit" and b[0] == "prop":      # `5 lt Age` -> `Age gt 5`
        a, b = b, a
        op = {"gt": "lt", "lt": "gt", "ge": "le", "le": "ge"}.get(op, op)
    if a[0] == "prop" and b[0] == "lit":
        val, vtype = _prop_value(e, a[1])
        lit = b[1]
        cv = _coerce(val, vtype, b[2])
        if cv is _MISSING:
            return op == "ne"
        if cv is None:
            return op == "ne"
    elif a[0] == "prop" and b[0] == "prop":
        cv, lit = _prop_value(e, a[1])[0], _prop_value(e, b[1])[0]
        if cv is None or lit is None:
            return op == "ne"
    else:
        cv, lit = a[1], b[1]
    try:
        if op == "eq":
            return cv == lit
        if op == "ne":
            return cv != lit
        if op == "gt":
            return cv > lit
        if op == "ge":
            return cv >= lit
        if op == "lt":
            return cv < lit
        return cv <= lit
    except TypeError:
        return False


def _apply_filter(rows: list, filt: str | None) -> list:
    """rows are raw stored entities."""
    if not filt:
        return rows
    node = _Filter(filt).node
    return [e for e in rows if _eval(node, e)]


def _select(view: dict, select: str | None) -> dict:
    if not select or select.strip() == "*":
        return view
    keep = {c.strip() for c in select.split(",") if c.strip()}
    out = {"odata.etag": view.get("odata.etag")}
    for k, v in view.items():
        base = k.split("@odata.")[0]
        if base in keep:
            out[k] = v
    return out


def _clean(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if not k.startswith("odata.")}


def _etag_ok(headers: dict, current: str | None) -> bool | None:
    """None: no If-Match header. True/False: the condition holds / fails."""
    im = headers.get("if-match")
    if im is None or str(im).strip() == "":
        return None
    im = str(im).strip()
    if im == "*":
        return current is not None
    return current is not None and im == current


def _precond(headers: dict, existing: dict | None):
    """The shared update/merge/delete precondition. Returns an error Response or None."""
    chk = _etag_ok(headers, existing.get("_etag") if existing is not None else None)
    if chk is None:
        return None
    if existing is None:
        return _err(404, "ResourceNotFound", "The specified resource does not exist.")
    if not chk:
        return _err(412, "UpdateConditionNotSatisfied", "The update condition specified in the request was not satisfied.")
    return None


# ── batch ($batch, multipart/mixed) ─────────────────────────────────────────
_REQLINE = re.compile(r"^([A-Z]+)\s+(\S+)\s+HTTP/1\.[01]\s*$")


def _boundary(ctype: str, body: bytes) -> str | None:
    m = re.search(r'boundary="?([^";]+)"?', ctype or "")
    if m:
        return m.group(1)
    mm = re.match(rb"\s*--([^\r\n]+)", body or b"")
    return mm.group(1).decode() if mm else None


def _split_parts(body: bytes, boundary: str) -> list:
    parts = []
    for chunk in body.split(b"--" + boundary.encode()):
        c = chunk.strip(b"\r\n")
        if not c or c == b"--" or c.startswith(b"--"):
            continue
        parts.append(c)
    return parts


def _parse_batch(body: bytes, ctype: str) -> list:
    """-> [{'method','path','query','headers','body','cid'}] flattened across changesets."""
    out: list = []
    b = _boundary(ctype, body)
    if not b:
        raise ValueError("The batch request has no multipart boundary.")
    for part in _split_parts(body, b):
        head, _, rest = part.partition(b"\r\n\r\n") if b"\r\n\r\n" in part else part.partition(b"\n\n")
        hdr = {}
        for ln in head.decode("utf-8", "replace").splitlines():
            if ":" in ln:
                k, _, v = ln.partition(":")
                hdr[k.strip().lower()] = v.strip()
        ct = hdr.get("content-type", "")
        if ct.lower().startswith("multipart/mixed"):
            out.extend(_parse_batch(rest, ct))
            continue
        text = rest.replace(b"\r\n", b"\n")
        top, _, payload = text.partition(b"\n\n")
        lines = top.decode("utf-8", "replace").split("\n")
        ri = next((i for i, ln in enumerate(lines) if _REQLINE.match(ln.strip())), None)
        if ri is None:
            continue
        mth, url = _REQLINE.match(lines[ri].strip()).groups()
        u = url.split("?", 1)
        path = "/" + url.split("//", 1)[1].split("/", 1)[1].split("?", 1)[0] if "://" in url else u[0]
        q = {}
        if "?" in url:
            for kv in url.split("?", 1)[1].split("&"):
                k, _, v = kv.partition("=")
                q[unquote(k)] = unquote(v)
        rh = {}
        for ln in lines[ri + 1:]:
            if ":" in ln:
                k, _, v = ln.partition(":")
                rh[k.strip().lower()] = v.strip()
        out.append({"method": mth, "path": unquote(path), "query": q, "headers": rh, "body": payload.strip(b"\n"),
                    "cid": hdr.get("content-id", "")})
    return out


_REASON = {200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request", 404: "Not Found", 409: "Conflict",
           412: "Precondition Failed"}


def _batch_response(results: list, failed_idx: int | None) -> Response:
    bid, cid = "batchresponse_" + str(uuid.uuid4()), "changesetresponse_" + str(uuid.uuid4())
    lines = [f"--{bid}", f"Content-Type: multipart/mixed; boundary={cid}", "", ]
    for n, r in enumerate(results):
        lines += [f"--{cid}", "Content-Type: application/http", "Content-Transfer-Encoding: binary", ""]
        lines.append(f"HTTP/1.1 {r.status} {_REASON.get(r.status, 'Status')}")
        lines.append(f"Content-ID: {n + 1}")
        lines += ["X-Content-Type-Options: nosniff", "Cache-Control: no-cache", "DataServiceVersion: 3.0;"]
        if r.headers.get("etag"):
            lines.append("ETag: " + r.headers["etag"])
        body = r.body.decode() if r.body else ""
        if body:
            lines.append("Content-Type: application/json;odata=minimalmetadata;streaming=true;charset=utf-8")
        lines += ["", body] if body else [""]
    lines += [f"--{cid}--", f"--{bid}--", ""]
    return Response(status=202, headers={"x-ms-version": "2019-02-02"}, body="\r\n".join(lines).encode(),
                    media_type=f"multipart/mixed; boundary={bid}")


def _do_batch(store: "AzureTableStore", headers: dict, body: bytes, prefix_account: bool) -> Response:
    try:
        ops = _parse_batch(body, headers.get("content-type", ""))
    except ValueError as exc:
        return _err(400, "InvalidInput", str(exc))
    if not ops:
        return _err(400, "InvalidInput", "The batch contains no operations.")
    if len(ops) > 100:
        return _err(400, "InvalidInput", "The batch contains more than 100 operations.")
    tables = {_SEG_RE.match([s for s in _strip_account(o["path"]).split("/") if s][0]).group(1) for o in ops}
    if len(tables) != 1:
        return _err(400, "InvalidInput", "All operations in a batch must target the same table.")
    table = next(iter(tables))
    if not store.table_exists(table):
        return _err(404, "TableNotFound", f"The table '{table}' does not exist.")
    snapshot = copy.deepcopy(store.tables[table])
    pkeys = set()
    for o in ops:
        m = _ENTITY_KEY_RE.search(o["path"].split("/")[-1])
        if m:
            pkeys.add(_unescape(m.group(1)))
        else:
            try:
                v = json.loads(o["body"] or b"{}").get("PartitionKey")
            except ValueError:
                v = None
            if v is not None:
                pkeys.add(v)
    if len(pkeys) > 1:
        return _err(400, "CommandsInBatchActOnDifferentPartitions",
                    "All commands in a batch must operate on same partition key.")
    results: list = []
    for idx, o in enumerate(ops):
        r = _dispatch(store, o["method"], o["path"], o["query"], o["headers"], o["body"], _in_batch=True)
        if r.status >= 400:
            store.tables[table] = snapshot            # atomic: roll the whole changeset back
            store.persist()
            try:
                msg = json.loads(r.body)["odata.error"]["message"]["value"]
            except Exception:
                msg = "The batch operation failed."
            code = r.headers.get("x-ms-error-code", "InvalidInput")
            err = _err(r.status, code, f"{idx}:{msg}")
            return _batch_response([err], idx)
        results.append(r)
    store.persist()
    return _batch_response(results, None)


# ── dispatch ────────────────────────────────────────────────────────────────
def _page_size(query: dict) -> int:
    try:
        top = int(query.get("$top") or 0)
    except ValueError:
        top = 0
    return min(top, 1000) if top > 0 else 1000


def _sort_key(e: dict):
    return (str(e.get("PartitionKey", "")), str(e.get("RowKey", "")))


def dispatch(store: AzureTableStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> Response:
    return _dispatch(store, method, path, query, headers, body)


def _dispatch(store: AzureTableStore, method: str, path: str,
              query: dict | None = None, headers: dict | None = None,
              body: bytes = b"", _in_batch: bool = False) -> Response:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()
    if method == "POST" and headers.get("x-http-method", "").upper() in ("MERGE", "PATCH"):
        method = "MERGE"
    if method == "PATCH":
        method = "MERGE"

    p = _strip_account(path.split("?", 1)[0])
    segs = [unquote(s) for s in p.split("/") if s != ""]
    if not segs:
        return _err(400, "InvalidInput", "No table specified.")
    if segs[0] == "$batch" and method == "POST" and not _in_batch:
        return _do_batch(store, headers, body, False)

    m = _SEG_RE.match(segs[0])
    name, keypart = m.group(1), m.group(2)
    if keypart == "()":
        keypart = None

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
                if "return-no-content" in str(headers.get("prefer", "")).lower():
                    return Response(status=204, headers={"location": f"/Tables('{tname}')", "preference-applied": "return-no-content"},
                                    body=b"", media_type=None)
                return _ok(201, {"TableName": tname},
                           headers={"location": f"/Tables('{tname}')"})
            if method == "GET":
                rows = [{"TableName": t} for t in sorted(store.tables)]
                flt = query.get("$filter")
                if flt:
                    mm = re.match(r"^\s*TableName\s+eq\s+'((?:[^']|'')*)'\s*$", flt)
                    if mm:
                        rows = [r for r in rows if r["TableName"] == _unescape(mm.group(1))]
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
            entity = _clean(payload)
            entity["_etag"], entity["_ts"] = _etag(), _now_iso()
            rows[_rowkey(pk, rk)] = entity
            store.persist()
            v = _view(entity)
            if "return-no-content" in str(headers.get("prefer", "")).lower():
                return Response(status=204, headers={"etag": v["odata.etag"], "preference-applied": "return-no-content"},
                                body=b"", media_type=None)
            return _ok(201, v, headers={"etag": v["odata.etag"]})
        if method == "GET":                        # query entities
            try:
                matched = _apply_filter(list(rows.values()), query.get("$filter"))
            except _FilterError as exc:
                return _err(400, "InvalidInput", str(exc))
            matched.sort(key=_sort_key)
            npk, nrk = query.get("NextPartitionKey"), query.get("NextRowKey")
            if npk is not None:
                matched = [e for e in matched if (_sort_key(e)) >= (npk, nrk or "")]
            size = _page_size(query)
            page, more = matched[:size], matched[size:]
            out = [_select(_view(e), query.get("$select")) for e in page]
            hdrs = {}
            if more:
                hdrs["x-ms-continuation-NextPartitionKey"] = str(more[0].get("PartitionKey", ""))
                hdrs["x-ms-continuation-NextRowKey"] = str(more[0].get("RowKey", ""))
            return _ok(200, {"odata.metadata": f"/{table}/@Element", "value": out}, headers=hdrs)
        return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")

    em = _ENTITY_KEY_RE.match(keypart)
    if not em:
        return _err(400, "InvalidInput", "Malformed entity key.")
    pk, rk = _unescape(em.group(1)), _unescape(em.group(2))
    key = _rowkey(pk, rk)
    existing = rows.get(key)

    if method == "GET":
        if existing is None:
            return _err(404, "ResourceNotFound", "The specified entity does not exist.")
        v = _select(_view(existing), query.get("$select"))
        return _ok(200, v, headers={"etag": existing.get("_etag", "")})

    if method == "PUT":                             # insert-or-replace; with If-Match: replace-existing only
        bad = _precond(headers, existing)
        if bad is not None:
            return bad
        entity = _clean(payload)
        entity.setdefault("PartitionKey", pk)
        entity.setdefault("RowKey", rk)
        entity["_etag"], entity["_ts"] = _etag(), _now_iso()
        rows[key] = entity
        store.persist()
        return Response(status=204, headers={"etag": entity["_etag"]}, body=b"", media_type=None)

    if method == "MERGE":                           # insert-or-merge; with If-Match: merge-existing only
        bad = _precond(headers, existing)
        if bad is not None:
            return bad
        merged = dict(existing or {})
        merged.update(_clean(payload))
        merged.setdefault("PartitionKey", pk)
        merged.setdefault("RowKey", rk)
        merged["_etag"], merged["_ts"] = _etag(), _now_iso()
        rows[key] = merged
        store.persist()
        return Response(status=204, headers={"etag": merged["_etag"]}, body=b"", media_type=None)

    if method == "DELETE":
        if existing is None:
            return _err(404, "ResourceNotFound", "The specified entity does not exist.")
        bad = _precond(headers, existing)
        if bad is not None:
            return bad
        rows.pop(key, None)
        store.persist()
        return Response(status=204, body=b"", media_type=None)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")
