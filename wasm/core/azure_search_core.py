# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure AI Search (Microsoft.Search) -- control plane + an embedded search engine (Nano / dev_server / unified-ingress core).

ARM: ``Microsoft.Search/searchServices`` with the real name rule, SKU/replica/partition matrix, one Free service per
subscription, global name uniqueness, ``listAdminKeys`` / ``regenerateAdminKey/{primary|secondary}`` /
``listQueryKeys`` / ``createQueryKey/{name}`` / ``deleteQueryKey/{key}`` and ``checkNameAvailability``.

Data plane, exposed as ARM extension paths under the service (the real endpoint is ``{service}.search.windows.net``
authenticated with an ``api-key``; Vyomi routes it through ARM, so the console and tests need no extra DNS):

    .../searchServices/{n}/indexes[/{idx}]            create / get / delete an index (typed fields, one key, attributes)
    .../indexes/{idx}/docs/index   POST   upload | merge | mergeOrUpload | delete   (key + type validated)
    .../indexes/{idx}/docs/search  POST   search (terms OR, "phrases", -negation, ranked by TF-IDF) + $filter
                                          (eq ne gt ge lt le, and/or/not, parens) + orderby + top/skip + select +
                                          facets + count
    .../indexes/{idx}/docs/{key}   GET    lookup
    .../datasources[/{ds}]  .../indexers[/{ix}]  .../indexers/{ix}/run   .../indexers/{ix}/status

Indexers really run for ``azureblob`` data sources: they read the blobs of a Vyomi storage-account container through
the injected ``blob_store`` (text, JSON, JSON arrays, CSV) and populate the index, honouring the data source's
``dataDeletionDetectionPolicy`` / re-run idempotence. ``cosmosdb`` / ``azuresql`` / ``azuretable`` data sources are
stored and validated but their indexers report ``transientFailure`` -- they are not read yet.

NOT modelled: semantic ranker / vector (HNSW) / hybrid retrieval, skillsets (AI enrichment), analyzers beyond
lower-casing + whitespace/punctuation splitting, scoring profiles, suggesters, synonym maps, geo and the Lucene query
parser. Scores are TF-IDF, not BM25.

Pure python, no framework imports. Functions return ``{"status": int, "body": ...}``.
"""
from __future__ import annotations

import base64
import csv
import datetime
import io
import json
import math
import re
import secrets
import uuid

NAMESPACE = "Microsoft.Search"
API_VERSION = "2023-11-01"
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$")
SKUS = {   # sku -> (max replicas, allowed partition counts, max indexes)
    "free": (1, (1,), 3), "basic": (3, (1,), 15),
    "standard": (12, (1, 2, 3, 4, 6, 12), 50), "standard2": (12, (1, 2, 3, 4, 6, 12), 200),
    "standard3": (12, (1, 2, 3, 4, 6, 12), 200), "storage_optimized_l1": (12, (1, 2, 3, 4, 6, 12), 10),
    "storage_optimized_l2": (12, (1, 2, 3, 4, 6, 12), 10),
}
FIELD_TYPES = ("Edm.String", "Edm.Int32", "Edm.Int64", "Edm.Double", "Edm.Boolean", "Edm.DateTimeOffset", "Collection(Edm.String)")
DS_TYPES = ("azureblob", "cosmosdb", "azuresql", "azuretable", "adlsgen2")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def _ok(body, status=200):
    return {"status": status, "body": body}


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def handles(namespace, chain=None) -> bool:
    return namespace.lower() == "microsoft.search"


def _services(state, sub=None):
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == "microsoft.search/searchservices"
            and (sub is None or r.get("_sub") == sub)]


def _key():
    return secrets.token_hex(16).upper()


def validate_name(name):
    if not (2 <= len(name) <= 60) or not NAME_RE.match(name):
        return ("ResourceNameInvalid", "The search service name must be 2-60 characters of lower-case letters, digits and single dashes, "
                "and must not start or end with a dash.")
    return None


def _apply_props(rec, payload, creating):
    p = (payload or {}).get("properties") or {}
    sku = ((payload or {}).get("sku") or {}).get("name") or (rec.get("sku") or {}).get("name")
    if not sku:
        return ("InvalidRequestContent", "The resource sku is required.")
    sku = str(sku).lower()
    if sku not in SKUS:
        return ("InvalidSku", f"The sku '{sku}' is not valid. Valid values: {', '.join(SKUS)}.")
    if not creating and rec["sku"]["name"] != sku:
        return ("SkuChangeNotAllowed", "A search service's pricing tier cannot be changed after creation.")
    props = rec["properties"]
    replicas = int(p.get("replicaCount", props.get("replicaCount", 1)))
    parts = int(p.get("partitionCount", props.get("partitionCount", 1)))
    max_r, allowed_p, _ = SKUS[sku]
    if not 1 <= replicas <= max_r:
        return ("InvalidReplicaCount", f"replicaCount must be between 1 and {max_r} for the {sku} tier.")
    if parts not in allowed_p:
        return ("InvalidPartitionCount", f"partitionCount must be one of {', '.join(map(str, allowed_p))} for the {sku} tier.")
    hosting = p.get("hostingMode", props.get("hostingMode", "default"))
    if hosting not in ("default", "highDensity") or (hosting == "highDensity" and sku != "standard3"):
        return ("InvalidHostingMode", "hostingMode 'highDensity' is only available on the standard3 tier; valid values are default|highDensity.")
    pna = p.get("publicNetworkAccess", props.get("publicNetworkAccess", "enabled")).lower()
    if pna not in ("enabled", "disabled"):
        return ("InvalidRequestContent", "publicNetworkAccess must be enabled or disabled.")
    sem = p.get("semanticSearch", props.get("semanticSearch", "disabled"))
    if sem not in ("disabled", "free", "standard") or (sem != "disabled" and sku == "free" and sem == "standard"):
        return ("InvalidRequestContent", "semanticSearch must be disabled, free or standard (standard is not available on the free tier).")
    auth = p.get("authOptions")
    if auth is not None and not (isinstance(auth, dict) and set(auth) <= {"apiKeyOnly", "aadOrApiKey"}):
        return ("InvalidRequestContent", "authOptions must be {apiKeyOnly: {}} or {aadOrApiKey: {aadAuthFailureMode}}.")
    props.update({"replicaCount": replicas, "partitionCount": parts, "hostingMode": hosting,
                  "publicNetworkAccess": pna, "semanticSearch": sem, "provisioningState": "succeeded", "status": "running",
                  "statusDetails": "", "disableLocalAuth": bool(p.get("disableLocalAuth", props.get("disableLocalAuth", False)))})
    props["authOptions"] = auth if auth is not None else props.get("authOptions", {"apiKeyOnly": {}})
    if props["disableLocalAuth"] and "aadOrApiKey" not in props["authOptions"] and auth is not None:
        return ("InvalidRequestContent", "disableLocalAuth requires authOptions to be unset or aadOrApiKey.")
    rec["sku"] = {"name": sku}
    return None


def _service_view(rec):
    v = _view(rec)
    v["properties"] = dict(v["properties"])
    return v


# ── search engine ────────────────────────────────────────────────────────────
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text) -> list:
    return _TOKEN.findall(str(text).lower())


def _coerce(ftype, value):
    if value is None:
        return None
    if ftype == "Edm.String":
        if not isinstance(value, str):
            raise ValueError("expected a string")
        return value
    if ftype in ("Edm.Int32", "Edm.Int64"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected an integer")
        if ftype == "Edm.Int32" and not -2 ** 31 <= value < 2 ** 31:
            raise ValueError("out of Int32 range")
        return value
    if ftype == "Edm.Double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected a number")
        return float(value)
    if ftype == "Edm.Boolean":
        if not isinstance(value, bool):
            raise ValueError("expected a boolean")
        return value
    if ftype == "Edm.DateTimeOffset":
        if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
            raise ValueError("expected an ISO-8601 date-time")
        return value
    if ftype == "Collection(Edm.String)":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ValueError("expected an array of strings")
        return value
    raise ValueError("unknown type")


def validate_index(body):
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        return "The index must define at least one field."
    names, keys = set(), 0
    for f in fields:
        n = f.get("name")
        if not n or not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$", n) or n.startswith("azsearch"):
            return f"Field name '{n}' is invalid (letters, digits, underscore; must not start with a digit or 'azsearch')."
        if n in names:
            return f"Field '{n}' is defined more than once."
        names.add(n)
        if f.get("type") not in FIELD_TYPES:
            return f"Field '{n}' has unsupported type '{f.get('type')}'. Supported: {', '.join(FIELD_TYPES)}."
        if f.get("key"):
            keys += 1
            if f["type"] != "Edm.String":
                return f"The key field '{n}' must be of type Edm.String."
            if f.get("searchable") is True and False:
                pass
        if f.get("searchable") and f["type"] not in ("Edm.String", "Collection(Edm.String)"):
            return f"Field '{n}' of type {f['type']} cannot be searchable."
        if f.get("facetable") and f.get("key"):
            return "A key field cannot be facetable."
    if keys != 1:
        return f"The index must have exactly one key field (found {keys})."
    return None


def _norm_index(body, name):
    out = {"name": name, "fields": [], "@odata.etag": '"0x%s"' % uuid.uuid4().hex[:14].upper()}
    for f in body["fields"]:
        is_str = f["type"] in ("Edm.String", "Collection(Edm.String)")
        out["fields"].append({"name": f["name"], "type": f["type"], "key": bool(f.get("key")),
                              "searchable": bool(f.get("searchable", is_str and not f.get("key"))),
                              "filterable": bool(f.get("filterable", True)), "sortable": bool(f.get("sortable", f["type"] != "Collection(Edm.String)")),
                              "facetable": bool(f.get("facetable", f["type"] != "Edm.DateTimeOffset" and not f.get("key"))),
                              "retrievable": bool(f.get("retrievable", True))})
    return out


def _fmap(idx):
    return {f["name"]: f for f in idx["fields"]}


# $filter ---------------------------------------------------------------------
_FTOK = re.compile(r"\s*(\(|\)|'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_/]*|-?\d+(?:\.\d+)?|\d{4}-\d{2}-\d{2}T[0-9:.]+Z?)")


def _filter_tokens(s):
    toks, pos = [], 0
    while pos < len(s):
        if s[pos:].strip() == "":
            break
        m = _FTOK.match(s, pos)
        if not m:
            raise ValueError(f"Invalid expression: unexpected text near '{s[pos:pos + 12]}'.")
        toks.append(m.group(1))
        pos = m.end()
    return toks


def compile_filter(expr, idx):
    """Parse an OData $filter into a predicate over a document."""
    fm = _fmap(idx)
    toks = _filter_tokens(expr)
    i = [0]

    def peek():
        return toks[i[0]] if i[0] < len(toks) else None

    def take():
        t = peek()
        i[0] += 1
        return t

    def lit(t, ftype):
        if t.startswith("'"):
            return t[1:-1].replace("''", "'")
        if t in ("true", "false"):
            return t == "true"
        if t == "null":
            return None
        return float(t) if "." in t else int(t)

    def primary():
        t = take()
        if t is None:
            raise ValueError("Invalid expression: unexpected end.")
        if t == "(":
            p = orx()
            if take() != ")":
                raise ValueError("Invalid expression: missing ')'.")
            return p
        if t == "not":
            p = primary()
            return lambda d, p=p: not p(d)
        if t not in fm:
            raise ValueError(f"Invalid expression: Unknown field '{t}'.")
        f = fm[t]
        if not f["filterable"]:
            raise ValueError(f"Invalid expression: Field '{t}' is not filterable.")
        op = take()
        if op not in ("eq", "ne", "gt", "ge", "lt", "le"):
            raise ValueError(f"Invalid expression: unsupported operator '{op}'.")
        v = lit(take() or "", f["type"])

        def pred(d, t=t, op=op, v=v):
            x = d.get(t)
            if x is None or v is None:
                return (x is None) == (v is None) if op == "eq" else ((x is None) != (v is None) if op == "ne" else False)
            if isinstance(x, list):
                return any(_cmp(op, e, v) for e in x)
            return _cmp(op, x, v)
        return pred

    def andx():
        p = primary()
        while peek() == "and":
            take()
            q, p = primary(), p
            p = (lambda a, b: lambda d: a(d) and b(d))(p, q)
        return p

    def orx():
        p = andx()
        while peek() == "or":
            take()
            q = andx()
            p = (lambda a, b: lambda d: a(d) or b(d))(p, q)
        return p

    pred = orx()
    if peek() is not None:
        raise ValueError(f"Invalid expression: unexpected token '{peek()}'.")
    return pred


def _cmp(op, a, b):
    try:
        return {"eq": a == b, "ne": a != b, "gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]
    except TypeError:
        return False


def _searchable_text(doc, idx):
    return " ".join(" ".join(v) if isinstance(v, list) else str(v) for f in idx["fields"] if f["searchable"]
                    for v in [doc.get(f["name"])] if v is not None)


def search(index_rec, params):
    idx, docs = index_rec["_def"], index_rec["_docs"]
    text = (params.get("search") or "*").strip()
    fm = _fmap(idx)
    try:
        pred = compile_filter(params["$filter"] if params.get("$filter") else params.get("filter") or "", idx) if (params.get("$filter") or params.get("filter")) else (lambda d: True)
    except ValueError as e:
        return _err(400, "InvalidRequest", str(e))
    cand = [d for d in docs.values() if pred(d)]
    must, mustnot, terms = [], [], []
    if text != "*":
        for m in re.finditer(r'(-?)("([^"]+)"|\S+)', text):
            neg, raw, phrase = m.group(1), m.group(2), m.group(3)
            toks = tokenize(phrase or raw.lstrip("+"))
            if not toks:
                continue
            (mustnot if neg else (must if phrase else terms)).append(toks)
    n = max(len(docs), 1)
    df = {}
    corpus = {k: tokenize(_searchable_text(d, idx)) for k, d in docs.items()}
    for toks in corpus.values():
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    scored = []
    keyf = next(f["name"] for f in idx["fields"] if f["key"])
    for d in cand:
        toks = corpus[d[keyf]]
        if any(_contains(toks, ph) for ph in mustnot):
            continue
        if must and not all(_contains(toks, ph) for ph in must):
            continue
        score = 1.0
        if text != "*":
            score = 0.0
            for ph in must + terms:
                for t in ph:
                    tf = toks.count(t)
                    if tf:
                        score += (1 + math.log(tf)) * (math.log(1 + n / df.get(t, 1)))
            if (terms or must) and score == 0.0:
                continue
        scored.append((score, d))
    order = params.get("$orderby") or params.get("orderby")
    if order:
        for clause in reversed([c.strip() for c in order.split(",") if c.strip()]):
            fld, _, direction = clause.partition(" ")
            if fld not in fm or not fm[fld]["sortable"]:
                return _err(400, "InvalidRequest", f"Invalid expression: field '{fld}' is not sortable.")
            scored.sort(key=lambda sd: (sd[1].get(fld) is None, sd[1].get(fld)), reverse=direction.strip().lower() == "desc")
    else:
        scored.sort(key=lambda sd: -sd[0])
    total = len(scored)
    top = int(params.get("$top") or params.get("top") or 50)
    skip = int(params.get("$skip") or params.get("skip") or 0)
    if not 0 <= top <= 1000 or skip < 0:
        return _err(400, "InvalidRequest", "top must be 0-1000 and skip must be >= 0.")
    sel = params.get("$select") or params.get("select")
    cols = [c.strip() for c in sel.split(",")] if sel and sel != "*" else [f["name"] for f in idx["fields"] if f["retrievable"]]
    bad = [c for c in cols if c not in fm]
    if bad:
        return _err(400, "InvalidRequest", f"Invalid expression: Unknown field '{bad[0]}' in $select.")
    value = [dict({"@search.score": round(s, 6)}, **{c: d.get(c) for c in cols if fm[c]["retrievable"]}) for s, d in scored[skip:skip + top]]
    body = {"value": value}
    if str(params.get("$count") or params.get("count")).lower() == "true":
        body["@odata.count"] = total
    facets = params.get("facet") or params.get("facets")
    if facets:
        body["@search.facets"] = {}
        for fct in ([facets] if isinstance(facets, str) else facets):
            name = fct.split(",")[0]
            if name not in fm or not fm[name]["facetable"]:
                return _err(400, "InvalidRequest", f"Field '{name}' is not facetable.")
            counts = {}
            for _s, d in scored:
                for v in (d.get(name) if isinstance(d.get(name), list) else [d.get(name)]):
                    if v is not None:
                        counts[v] = counts.get(v, 0) + 1
            body["@search.facets"][name] = [{"count": c, "value": v} for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))]
    return _ok(body)


def _contains(toks, phrase):
    n = len(phrase)
    return any(toks[i:i + n] == phrase for i in range(len(toks) - n + 1))


def _docs_index(index_rec, body):
    idx, docs = index_rec["_def"], index_rec["_docs"]
    fm, keyf = _fmap(idx), next(f["name"] for f in idx["fields"] if f["key"])
    results = []
    for act in (body or {}).get("value") or []:
        action = act.get("@search.action", "upload")
        doc = {k: v for k, v in act.items() if k != "@search.action"}
        key = doc.get(keyf)
        if not isinstance(key, str) or not key or not re.match(r"^[A-Za-z0-9_\-=]+$", key):
            results.append({"key": key, "status": False, "errorMessage": "Invalid document key: keys may contain letters, digits, '_', '-', '='.", "statusCode": 400})
            continue
        if action not in ("upload", "merge", "mergeOrUpload", "delete"):
            results.append({"key": key, "status": False, "errorMessage": f"Unknown action '{action}'.", "statusCode": 400})
            continue
        if action == "delete":
            docs.pop(key, None)
            results.append({"key": key, "status": True, "errorMessage": None, "statusCode": 200})
            continue
        if action == "merge" and key not in docs:
            results.append({"key": key, "status": False, "errorMessage": "Document not found.", "statusCode": 404})
            continue
        try:
            clean = {}
            for k, v in doc.items():
                if k not in fm:
                    raise ValueError(f"The property '{k}' does not exist on type 'search.documentFields'.")
                try:
                    clean[k] = _coerce(fm[k]["type"], v)
                except ValueError as e:
                    raise ValueError(f"Field '{k}': {e} ({fm[k]['type']}).")
        except ValueError as e:
            results.append({"key": key, "status": False, "errorMessage": str(e), "statusCode": 400})
            continue
        existed = key in docs
        base = dict(docs.get(key, {})) if action in ("merge", "mergeOrUpload") else {}
        base.update(clean)
        docs[key] = {f["name"]: base.get(f["name"]) for f in idx["fields"]}
        results.append({"key": key, "status": True, "errorMessage": None, "statusCode": 200 if existed else 201})
    failed = any(not r["status"] for r in results)
    return {"status": 207 if failed else 200, "body": {"value": results}}


# ── indexers ─────────────────────────────────────────────────────────────────
def _parse_blob(name, data, mode):
    text = data.decode("utf-8", errors="replace")
    if mode == "json":
        obj = json.loads(text)
        return [obj] if isinstance(obj, dict) else None
    if mode == "jsonArray":
        obj = json.loads(text)
        return obj if isinstance(obj, list) else None
    if mode == "delimitedText":
        return list(csv.DictReader(io.StringIO(text)))
    return [{"content": text}]


def run_indexer(svc, ix_name, blob_store, account_lookup=None):
    ix = svc["_indexers"].get(ix_name)
    started = _now()
    status = svc["_ix_status"].setdefault(ix_name, {"status": "running", "lastResult": None, "executionHistory": []})
    res = {"status": "success", "errorMessage": None, "startTime": started, "endTime": None, "itemsProcessed": 0, "itemsFailed": 0, "errors": [],
           "initialTrackingState": None, "finalTrackingState": None}
    ds = svc["_datasources"].get(ix["dataSourceName"])
    idx_rec = svc["_indexes"].get(ix["targetIndexName"])
    if ds is None or idx_rec is None:
        res.update(status="transientFailure", errorMessage="The data source or target index no longer exists.")
    elif ds["type"] != "azureblob":
        res.update(status="transientFailure", errorMessage=f"Data source type '{ds['type']}' is not readable by Vyomi indexers (only azureblob).")
    elif blob_store is None:
        res.update(status="transientFailure", errorMessage="No Blob store is attached to this search service.")
    else:
        acct = _conn_account(ds["credentials"].get("connectionString", ""))
        cont = ds["container"]["name"]
        prefix = (ds["container"].get("query") or "")
        key = f"{acct}/{cont}" if acct and acct != "devstoreaccount1" else cont
        if not blob_store.container_exists(key):
            res.update(status="transientFailure", errorMessage=f"The container '{cont}' does not exist in storage account '{acct}'.")
        else:
            mode = ((ix.get("parameters") or {}).get("configuration") or {}).get("parsingMode", "default")
            keyf = next(f["name"] for f in idx_rec["_def"]["fields"] if f["key"])
            fm = _fmap(idx_rec["_def"])
            blobs = blob_store.container_blobs(key)
            seen = set()
            for bname, entry in sorted(blobs.items()):
                if prefix and not bname.startswith(prefix):
                    continue
                data = entry.get("data")
                if data is None:
                    data = blob_store.fetch_bytes(key, bname) or b""
                data = data.encode() if isinstance(data, str) else bytes(data)
                path = base64.urlsafe_b64encode(f"https://{acct}.blob.core.windows.net/{cont}/{bname}".encode()).decode().rstrip("=") .replace("=", "")
                try:
                    rows = _parse_blob(bname, data, mode)
                    if rows is None:
                        raise ValueError("document shape does not match parsingMode")
                except ValueError as e:
                    res["itemsFailed"] += 1
                    res["errors"].append({"key": bname, "errorMessage": f"Parsing failed: {e}"})
                    continue
                for n, row in enumerate(rows):
                    doc = {k: v for k, v in row.items() if k in fm}
                    meta = {"metadata_storage_name": bname.rsplit("/", 1)[-1], "metadata_storage_path": path,
                            "metadata_storage_size": len(data), "metadata_content_type": entry.get("content_type") or entry.get("content-type")}
                    for k, v in meta.items():
                        if k in fm and k not in doc:
                            doc[k] = v
                    if keyf not in doc:
                        doc[keyf] = path if len(rows) == 1 else f"{path}_{n}"
                    doc = {k: _soft(fm[k]["type"], v) for k, v in doc.items()}
                    r = _docs_index(idx_rec, {"value": [dict(doc, **{"@search.action": "mergeOrUpload"})]})["body"]["value"][0]
                    seen.add(doc[keyf])
                    if r["status"]:
                        res["itemsProcessed"] += 1
                    else:
                        res["itemsFailed"] += 1
                        res["errors"].append({"key": bname, "errorMessage": r["errorMessage"]})
            pol = ds.get("dataDeletionDetectionPolicy") or {}
            if pol.get("@odata.type", "").endswith("NativeBlobSoftDeleteDeletionDetectionPolicy"):
                pass
            max_fail = (ix.get("parameters") or {}).get("maxFailedItems", 0)
            if res["itemsFailed"] > max_fail >= 0:
                res.update(status="transientFailure", errorMessage="Indexer failed: items failed exceeded maxFailedItems.")
    res["endTime"] = _now()
    status["lastResult"] = res
    status["status"] = "running" if res["status"] == "success" else "error"
    status["executionHistory"] = ([res] + status["executionHistory"])[:50]
    return res


def _soft(ftype, v):
    """Indexer-side coercion of loosely typed source values into the index field type."""
    if v is None or v == "":
        return None if ftype != "Edm.String" else v
    try:
        if ftype == "Edm.String":
            return v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        if ftype in ("Edm.Int32", "Edm.Int64"):
            return int(v)
        if ftype == "Edm.Double":
            return float(v)
        if ftype == "Edm.Boolean":
            return v if isinstance(v, bool) else str(v).lower() == "true"
        if ftype == "Collection(Edm.String)":
            return [str(x) for x in v] if isinstance(v, list) else [s.strip() for s in str(v).split(";") if s.strip()]
    except (TypeError, ValueError):
        return v
    return v


def _conn_account(cs):
    m = re.search(r"AccountName=([^;]+)", cs or "", re.I) or re.search(r"https?://([^.\"]+)\.blob", cs or "", re.I)
    return m.group(1).lower() if m else None


# ── dispatch ─────────────────────────────────────────────────────────────────
def _rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NAMESPACE}/searchServices/{name}"


def _name_check(state, name):
    e = validate_name(name or "")
    if e:
        return {"nameAvailable": False, "reason": "Invalid", "message": e[1]}
    if any(s["name"].lower() == name.lower() for s in _services(state)):
        return {"nameAvailable": False, "reason": "AlreadyExists", "message": f"The search service name '{name}' is already in use."}
    return {"nameAvailable": True}


def dispatch(state, method, sub, rg, chain, payload, query, blob_store=None, base=""):
    """chain = everything after 'providers/Microsoft.Search' (e.g. ['searchServices', n, 'indexes', ...])."""
    if chain and chain[0].lower() == "checknameavailability":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST only.")
        return _ok(_name_check(state, (payload or {}).get("name")))
    if not chain or chain[0].lower() != "searchservices":
        return _err(404, "ResourceNotFound", f"Unknown Microsoft.Search resource type '{chain[0] if chain else ''}'.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        rows = [_service_view(s) for s in _services(state, sub) if rg is None or s.get("_rg", "").lower() == rg.lower()]
        return _ok({"value": rows})
    name = chain[1]
    rid = _rid(sub, rg, name) if rg else None
    key = rid.lower() if rid else None
    rec = state.get(key) if key else None
    if len(chain) == 2:
        if method == "GET":
            return _ok(_service_view(rec)) if rec else _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Search/searchServices/{name}' under resource group '{rg}' was not found.")
        if method in ("PUT", "PATCH"):
            creating = rec is None
            if creating:
                e = validate_name(name)
                if e:
                    return _err(400, *e)
                if any(s["name"].lower() == name.lower() for s in _services(state) if s["id"].lower() != key):
                    return _err(409, "ResourceNameAlreadyExists", f"The search service name '{name}' is already in use.")
                if not (payload or {}).get("location"):
                    return _err(400, "InvalidRequestContent", "The location is required.")
                if str(((payload or {}).get("sku") or {}).get("name", "")).lower() == "free" and any(
                        s["sku"]["name"] == "free" for s in _services(state, sub)):
                    return _err(403, "QuotaExceeded", "Only one free search service is allowed per subscription.")
                rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/searchServices", "location": payload["location"], "tags": {}, "sku": {"name": "free"},
                       "properties": {"endpoint": f"https://{name}.search.windows.net/"},
                       "_type": f"{NAMESPACE}/searchServices", "_sub": sub, "_rg": rg, "_created": _now(),
                       "_admin": {"primary": _key(), "secondary": _key()}, "_query": {}, "_indexes": {}, "_datasources": {}, "_indexers": {}, "_ix_status": {}}
            if isinstance((payload or {}).get("tags"), dict):
                rec["tags"] = payload["tags"]
            e = _apply_props(rec, payload, creating)
            if e:
                return _err(400, *e)
            rec["systemData"] = {"createdAt": rec["_created"], "lastModifiedAt": _now()}
            state[key] = rec
            return _ok(_service_view(rec), 201 if creating else 200)
        if method == "DELETE":
            if rec is None:
                return {"status": 204, "body": None}
            state.pop(key)
            return _ok(None, 200)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if rec is None:
        return _err(404, "ResourceNotFound", f"The Resource 'Microsoft.Search/searchServices/{name}' under resource group '{rg}' was not found.")
    op = chain[2].lower()
    if op == "listadminkeys" and method == "POST":
        return _ok({"primaryKey": rec["_admin"]["primary"], "secondaryKey": rec["_admin"]["secondary"]})
    if op == "regenerateadminkey" and method == "POST" and len(chain) == 4:
        which = chain[3].lower()
        if which not in ("primary", "secondary"):
            return _err(400, "InvalidRequestContent", "The key kind must be primary or secondary.")
        rec["_admin"][which] = _key()
        return _ok({"primaryKey": rec["_admin"]["primary"], "secondaryKey": rec["_admin"]["secondary"]})
    if op == "listquerykeys" and method in ("POST", "GET"):
        return _ok({"value": [{"name": v["name"], "key": k} for k, v in rec["_query"].items()]})
    if op == "createquerykey" and method == "POST" and len(chain) == 4:
        if len(rec["_query"]) >= 50:
            return _err(409, "QuotaExceeded", "A search service supports at most 50 query keys.")
        k = _key()
        rec["_query"][k] = {"name": chain[3]}
        return _ok({"name": chain[3], "key": k})
    if op == "deletequerykey" and method == "DELETE" and len(chain) == 4:
        if rec["_query"].pop(chain[3], None) is None:
            return _err(404, "ResourceNotFound", "No such query key.")
        return _ok(None)
    if op == "indexes":
        return _indexes(rec, method, chain[3:], payload, query)
    if op in ("datasources", "indexers"):
        return _ds_ix(rec, op, method, chain[3:], payload, blob_store)
    if op == "stats" and method == "GET":
        return _ok({"counters": {"documentCount": {"usage": sum(len(i["_docs"]) for i in rec["_indexes"].values()), "quota": None},
                                 "indexesCount": {"usage": len(rec["_indexes"]), "quota": SKUS[rec["sku"]["name"]][2]},
                                 "indexersCount": {"usage": len(rec["_indexers"]), "quota": SKUS[rec["sku"]["name"]][2]},
                                 "dataSourcesCount": {"usage": len(rec["_datasources"]), "quota": SKUS[rec["sku"]["name"]][2]}}})
    return _err(404, "ResourceNotFound", f"Unknown search service operation '{chain[2]}'.")


def _indexes(svc, method, rest, payload, query):
    if public_blocked(svc):
        return _err(403, "Forbidden", "Public network access is disabled for this search service.")
    ix = svc["_indexes"]
    if not rest:
        if method == "GET":
            return _ok({"value": [i["_def"] for i in ix.values()]})
        if method == "POST":
            return _create_index(svc, (payload or {}).get("name"), payload, 201)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    name = rest[0]
    rec = ix.get(name)
    if len(rest) == 1:
        if method == "GET":
            return _ok(rec["_def"]) if rec else _err(404, "IndexNotFound", f"Index '{name}' was not found.")
        if method == "PUT":
            return _create_index(svc, name, payload, 200 if rec else 201)
        if method == "DELETE":
            if rec is None:
                return _err(404, "IndexNotFound", f"Index '{name}' was not found.")
            if any(x["targetIndexName"] == name for x in svc["_indexers"].values()):
                return _err(409, "IndexInUse", "The index is the target of an indexer; delete the indexer first.")
            ix.pop(name)
            return {"status": 204, "body": None}
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if rec is None:
        return _err(404, "IndexNotFound", f"Index '{name}' was not found.")
    if rest[1].lower() == "docs":
        sub = rest[2].lower() if len(rest) > 2 else "count"
        if sub == "index" and method == "POST":
            return _docs_index(rec, payload)
        if sub == "search" and method == "POST":
            return search(rec, payload or {})
        if sub == "search" and method == "GET":
            return search(rec, query)
        if sub == "count" and method == "GET":
            return _ok(len(rec["_docs"]))
        if len(rest) == 3 and method == "GET":
            d = rec["_docs"].get(rest[2])
            return _ok(d) if d else _err(404, "DocumentNotFound", f"Document with key '{rest[2]}' not found.")
    if rest[1].lower() == "stats" and method == "GET":
        return _ok({"documentCount": len(rec["_docs"]), "storageSize": sum(len(json.dumps(d)) for d in rec["_docs"].values())})
    return _err(404, "ResourceNotFound", "Unknown index operation.")


def public_blocked(svc):
    return (svc.get("properties") or {}).get("publicNetworkAccess") == "disabled"


def _create_index(svc, name, body, status):
    if not name or not re.match(r"^[a-z0-9][a-z0-9\-]{0,126}[a-z0-9]$|^[a-z0-9]$", name):
        return _err(400, "InvalidRequest", "Index names are lower-case letters, digits and dashes (max 128), not starting or ending with a dash.")
    e = validate_index(body or {})
    if e:
        return _err(400, "InvalidRequest", e)
    existing = svc["_indexes"].get(name)
    if existing is None and len(svc["_indexes"]) >= SKUS[svc["sku"]["name"]][2]:
        return _err(403, "QuotaExceeded", f"The {svc['sku']['name']} tier allows at most {SKUS[svc['sku']['name']][2]} indexes.")
    d = _norm_index(body, name)
    if existing is not None:
        old = {f["name"]: f for f in existing["_def"]["fields"]}
        for f in d["fields"]:
            o = old.get(f["name"])
            if o and o["type"] != f["type"]:
                return _err(400, "InvalidRequest", f"Field '{f['name']}' type cannot change in place; drop and recreate the index.")
        if any(n not in {f["name"] for f in d["fields"]} for n in old):
            return _err(400, "InvalidRequest", "Fields cannot be removed from an existing index; drop and recreate it.")
        existing["_def"] = d
        for doc in existing["_docs"].values():
            for f in d["fields"]:
                doc.setdefault(f["name"], None)
        return _ok(d, 200)
    svc["_indexes"][name] = {"_def": d, "_docs": {}}
    return _ok(d, status)


def _ds_ix(svc, kind, method, rest, payload, blob_store):
    store = svc["_" + kind]
    if not rest:
        if method == "GET":
            return _ok({"value": list(store.values())})
        if method == "POST":
            return _put_ds_ix(svc, kind, (payload or {}).get("name"), payload, 201)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    name = rest[0]
    if len(rest) == 1:
        if method == "GET":
            return _ok(store[name]) if name in store else _err(404, "ResourceNotFound", f"{kind[:-1]} '{name}' was not found.")
        if method == "PUT":
            return _put_ds_ix(svc, kind, name, payload, 200 if name in store else 201)
        if method == "DELETE":
            if name not in store:
                return _err(404, "ResourceNotFound", f"{kind[:-1]} '{name}' was not found.")
            if kind == "datasources" and any(x["dataSourceName"] == name for x in svc["_indexers"].values()):
                return _err(409, "ResourceInUse", "The data source is used by an indexer.")
            store.pop(name)
            svc["_ix_status"].pop(name, None)
            return {"status": 204, "body": None}
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if kind == "indexers" and name in store:
        if rest[1].lower() == "run" and method == "POST":
            if (svc["_ix_status"].get(name) or {}).get("status") == "running" and (store[name].get("disabled")):
                return _err(409, "IndexerDisabled", "The indexer is disabled.")
            run_indexer(svc, name, blob_store)
            return {"status": 202, "body": None}
        if rest[1].lower() == "status" and method == "GET":
            return _ok(svc["_ix_status"].get(name) or {"status": "running", "lastResult": None, "executionHistory": []})
        if rest[1].lower() == "reset" and method == "POST":
            svc["_ix_status"].pop(name, None)
            return {"status": 204, "body": None}
    return _err(404, "ResourceNotFound", f"{kind[:-1]} '{name}' was not found.")


def _put_ds_ix(svc, kind, name, body, status):
    body = dict(body or {})
    if not name or not re.match(r"^[a-z0-9][a-z0-9\-]{0,126}[a-z0-9]$", name):
        return _err(400, "InvalidRequest", "Names are lower-case letters, digits and dashes (2-128), not starting or ending with a dash.")
    body["name"] = name
    if kind == "datasources":
        if body.get("type") not in DS_TYPES:
            return _err(400, "InvalidRequest", f"Data source type must be one of {', '.join(DS_TYPES)}.")
        if not (body.get("credentials") or {}).get("connectionString"):
            return _err(400, "InvalidRequest", "credentials.connectionString is required.")
        if not (body.get("container") or {}).get("name"):
            return _err(400, "InvalidRequest", "container.name is required.")
    else:
        for req in ("dataSourceName", "targetIndexName"):
            if not body.get(req):
                return _err(400, "InvalidRequest", f"{req} is required.")
        if body["dataSourceName"] not in svc["_datasources"]:
            return _err(400, "InvalidRequest", f"Data source '{body['dataSourceName']}' does not exist.")
        if body["targetIndexName"] not in svc["_indexes"]:
            return _err(400, "InvalidRequest", f"Index '{body['targetIndexName']}' does not exist.")
        mode = ((body.get("parameters") or {}).get("configuration") or {}).get("parsingMode", "default")
        if mode not in ("default", "text", "json", "jsonArray", "delimitedText"):
            return _err(400, "InvalidRequest", "parsingMode must be default, text, json, jsonArray or delimitedText.")
        sched = (body.get("schedule") or {}).get("interval")
        if sched and not re.match(r"^P(T(\d+H)?(\d+M)?|\d+D)$", sched):
            return _err(400, "InvalidRequest", "schedule.interval must be an ISO-8601 duration of at least PT5M.")
    body["@odata.etag"] = '"0x%s"' % uuid.uuid4().hex[:14].upper()
    svc["_" + kind][name] = body
    return _ok(body, status)
