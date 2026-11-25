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

Also modelled: Okapi BM25 text scoring, vector + hybrid (RRF) retrieval, the semantic reranker (core/azure_search_vector_core),
suggesters (suggest + autocomplete), synonym map + alias storage, and the NATIVE data-plane wire the unmodified azure-search-documents
clients speak (OData `indexes('x')`, `docs/search.post.search`, `search.index`, `search.run` ... : see `wire_dispatch`).
NOT modelled: skillsets run as AI enrichment beyond the embedding skill, analyzers beyond lower-casing + whitespace/punctuation
splitting, scoring profiles, geo and the Lucene query parser. Synonym maps are stored, not applied at query time.

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

try:
    from core import azure_search_vector_core as vec
    from core import azure_search_sources_core as srcs
    from core import knowledge_core as kc
except ImportError:  # Pyodide flat layout
    import azure_search_vector_core as vec  # type: ignore
    import azure_search_sources_core as srcs  # type: ignore
    import knowledge_core as kc  # type: ignore

NAMESPACE = "Microsoft.Search"
API_VERSION = "2023-11-01"
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$")
SKUS = {   # sku -> (max replicas, allowed partition counts, max indexes)
    "free": (1, (1,), 3), "basic": (3, (1,), 15),
    "standard": (12, (1, 2, 3, 4, 6, 12), 50), "standard2": (12, (1, 2, 3, 4, 6, 12), 200),
    "standard3": (12, (1, 2, 3, 4, 6, 12), 200), "storage_optimized_l1": (12, (1, 2, 3, 4, 6, 12), 10),
    "storage_optimized_l2": (12, (1, 2, 3, 4, 6, 12), 10),
}
FIELD_TYPES = ("Edm.String", "Edm.Int32", "Edm.Int64", "Edm.Double", "Edm.Boolean", "Edm.DateTimeOffset", "Collection(Edm.String)", "Collection(Edm.Single)")
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
        if f["type"] == "Collection(Edm.Single)":
            e = vec.validate_vector_field(f, body)
            if e:
                return e
            continue
        if f.get("searchable") and f["type"] not in ("Edm.String", "Collection(Edm.String)"):
            return f"Field '{n}' of type {f['type']} cannot be searchable."
        if f.get("facetable") and f.get("key"):
            return "A key field cannot be facetable."
    if keys != 1:
        return f"The index must have exactly one key field (found {keys})."
    return vec.validate_semantic(body)


def _norm_index(body, name):
    out = {"name": name, "fields": [], "@odata.etag": '"0x%s"' % uuid.uuid4().hex[:14].upper()}
    for f in body["fields"]:
        is_str = f["type"] in ("Edm.String", "Collection(Edm.String)")
        if f["type"] == "Collection(Edm.Single)":
            out["fields"].append({"name": f["name"], "type": f["type"], "key": False, "searchable": True, "filterable": False, "sortable": False,
                                  "facetable": False, "retrievable": bool(f.get("retrievable", True)), "dimensions": f["dimensions"],
                                  "vectorSearchProfile": f["vectorSearchProfile"]})
            continue
        out["fields"].append({"name": f["name"], "type": f["type"], "key": bool(f.get("key")),
                              "searchable": bool(f.get("searchable", is_str and not f.get("key"))),
                              "filterable": bool(f.get("filterable", True)), "sortable": bool(f.get("sortable", f["type"] != "Collection(Edm.String)")),
                              "facetable": bool(f.get("facetable", f["type"] != "Edm.DateTimeOffset" and not f.get("key"))),
                              "retrievable": bool(f.get("retrievable", True))})
    if body.get("vectorSearch"):
        out["vectorSearch"] = body["vectorSearch"]
    if body.get("semantic"):
        out["semantic"] = body["semantic"]
    for k in ("suggesters", "scoringProfiles", "defaultScoringProfile", "corsOptions", "analyzers", "tokenizers", "tokenFilters", "charFilters",
              "normalizers", "similarity", "encryptionKey"):
        if body.get(k) is not None:
            out[k] = body[k]
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


def _searchable_text(doc, idx, only=None):
    return " ".join(" ".join(v) if isinstance(v, list) else str(v) for f in idx["fields"] if f["searchable"] and f["type"] != "Collection(Edm.Single)"
                    and (not only or f["name"] in only)
                    for v in [doc.get(f["name"])] if v is not None)


def search(index_rec, params, _trace=None):
    idx, docs = index_rec["_def"], index_rec["_docs"]
    text = (params.get("search") or "*").strip()
    fm = _fmap(idx)
    try:
        pred = compile_filter(params["$filter"] if params.get("$filter") else params.get("filter") or "", idx) if (params.get("$filter") or params.get("filter")) else (lambda d: True)
    except ValueError as e:
        return _err(400, "InvalidRequest", str(e))
    cand = [d for d in docs.values() if pred(d)]
    vq = params.get("vectorQueries")
    vranked = None
    if vq:
        if not isinstance(vq, list):
            return _err(400, "InvalidRequest", "vectorQueries must be an array.")
        vranked, verr = vec.vector_rank(idx, cand, vq)
        if verr:
            return _err(400, "InvalidRequest", verr)
    must, mustnot, terms = [], [], []
    if text != "*":
        for m in re.finditer(r'(-?)("([^"]+)"|\S+)', text):
            neg, raw, phrase = m.group(1), m.group(2), m.group(3)
            toks = tokenize(phrase or raw.lstrip("+"))
            if not toks:
                continue
            (mustnot if neg else (must if phrase else terms)).append(toks)
    sf = params.get("searchFields")
    only = {x.strip() for x in (sf.split(",") if isinstance(sf, str) else sf)} if sf else None
    if only and any(x not in fm for x in only):
        return _err(400, "InvalidRequest", f"Unknown field '{next(x for x in only if x not in fm)}' in searchFields.")
    corpus = {k: tokenize(_searchable_text(d, idx, only)) for k, d in docs.items()}
    if str(params.get("searchMode") or "any").lower() == "all":
        must, terms = must + [[t] for ph in terms for t in ph], []
    # keyword half = Okapi BM25 over the whole index (SQLite FTS5 bm25(), core/knowledge_core), as Azure AI Search scores text
    q_terms = [t for ph in must + terms for t in ph]
    if q_terms:
        order_keys = list(docs)
        bm = kc.bm25([" ".join(corpus[k]) for k in order_keys], " ".join(q_terms))
        bm_by_key = {order_keys[i]: sc for i, sc in bm.items()}
    else:
        bm_by_key = {}
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
            score = bm_by_key.get(d[keyf], 0.0)
            if (terms or must) and score == 0.0:
                continue
        scored.append((score, d))
    if _trace is not None:
        _trace["candidates"] = len(cand)
        _trace["keyword"] = {d[keyf]: s for s, d in scored} if text != "*" else {}
        _trace["vector"] = {d[keyf]: s for s, d in vranked} if vranked is not None else {}
    if vranked is not None:
        if text == "*":
            scored = vranked
        else:
            scored.sort(key=lambda sd: -sd[0])
            scored = vec.fuse(scored, vranked, keyf, vec.query_weight(vq))
        if _trace is not None:
            _trace["fused"] = {d[keyf]: s for s, d in scored}
    sem = None
    qtype = str(params.get("queryType") or "simple").lower()
    if qtype == "semantic":
        if text == "*":
            return _err(400, "InvalidRequest", "queryType 'semantic' requires a text query in 'search'.")
        sem_err = vec.semantic_check(idx, params)
        if sem_err:
            return _err(400, "InvalidRequest", sem_err)
        scored.sort(key=lambda sd: -sd[0])
        try:
            scored, sem = vec.semantic_rerank(index_rec, idx, text, scored, params)
        except vec.llm.LlmUnavailable as e:
            return _err(400, "InvalidRequest", f"The semantic ranker's embedding model is not available: {e}")
        if _trace is not None:
            _trace["reranker"] = {k: v["score"] for k, v in sem["docs"].items()}
    elif qtype not in ("simple", "full"):
        return _err(400, "InvalidRequest", f"Unsupported queryType '{qtype}'.")
    order = params.get("$orderby") or params.get("orderby")
    if order and not sem:
        for clause in reversed([c.strip() for c in order.split(",") if c.strip()]):
            fld, _, direction = clause.partition(" ")
            if fld not in fm or not fm[fld]["sortable"]:
                return _err(400, "InvalidRequest", f"Invalid expression: field '{fld}' is not sortable.")
            scored.sort(key=lambda sd: (sd[1].get(fld) is None, sd[1].get(fld)), reverse=direction.strip().lower() == "desc")
    elif not sem:
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
    if sem:
        for row, (_s, d) in zip(value, scored[skip:skip + top]):
            info = sem["docs"].get(d[keyf])
            if info:
                row["@search.rerankerScore"] = info["score"]
                if info.get("caption"):
                    row["@search.captions"] = [info["caption"]]
        if sem["answers"] is not None:
            body["@search.answers"] = sem["answers"]
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
                    clean[k] = vec.coerce_vector(fm[k], v) if fm[k]["type"] == "Collection(Edm.Single)" and v is not None else _coerce(fm[k]["type"], v)
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


def _mapping_fn(name, v):
    import urllib.parse as up
    if v is None:
        return None
    if name == "base64Encode":
        return base64.urlsafe_b64encode(str(v).encode()).decode()
    if name == "base64Decode":
        s = str(v)
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", "replace")
    if name == "urlEncode":
        return up.quote(str(v), safe="")
    if name == "urlDecode":
        return up.unquote(str(v))
    if name == "jsonArrayToStringCollection":
        arr = json.loads(v) if isinstance(v, str) else v
        return [str(x) for x in arr] if isinstance(arr, list) else None
    raise ValueError(f"Unsupported mapping function '{name}'.")


def apply_field_mappings(ix, row):
    """Indexer ``fieldMappings`` (sourceFieldName -> targetFieldName, optional mappingFunction); same-name fields map implicitly."""
    out = dict(row)
    for m in ix.get("fieldMappings") or []:
        src = m.get("sourceFieldName")
        if src not in row:
            continue
        fn = (m.get("mappingFunction") or {}).get("name")
        out[m.get("targetFieldName") or src] = _mapping_fn(fn, row[src]) if fn else row[src]
    return out


def _index_rows(svc, ix, idx_rec, ds, res, bname, rows, meta, path, seen):
    """Push the rows of ONE source item (a blob, or a Cosmos/SQL row) through mappings, the skillset and into the index."""
    keyf = next(f["name"] for f in idx_rec["_def"]["fields"] if f["key"])
    fm = _fmap(idx_rec["_def"])
    sk = svc.get("_skillsets", {}).get(ix.get("skillsetName") or "")
    for n, row in enumerate(rows):
        try:
            mapped = apply_field_mappings(ix, {**meta, **row})      # fieldMappings may name metadata_storage_* source fields
        except (ValueError, json.JSONDecodeError) as e:
            res["itemsFailed"] += 1
            res["errors"].append({"key": bname, "errorMessage": f"Field mapping failed: {e}"})
            continue
        doc = {k: v for k, v in mapped.items() if k in fm}
        for k, v in meta.items():
            if k in fm and k not in doc:
                doc[k] = v
        if keyf not in doc:
            if path is None:
                res["itemsFailed"] += 1
                res["errors"].append({"key": bname, "errorMessage": f"The document is missing the index key field '{keyf}'; map a source column to it with fieldMappings."})
                continue
            doc[keyf] = path if len(rows) == 1 else f"{path}_{n}"
        doc = {k: _soft(fm[k]["type"], v) for k, v in doc.items()}
        if sk:
            tree, serr = vec.run_skillset(sk, {**mapped, **meta})
            if serr:
                res["itemsFailed"] += 1
                res["errors"].append({"key": bname, "errorMessage": serr})
                continue
            for om in ix.get("outputFieldMappings") or []:
                tgt = om.get("targetFieldName")
                val = vec._get(tree, om.get("sourceFieldName") or "")
                if tgt in fm and val is not None:
                    doc[tgt] = _soft(fm[tgt]["type"], val) if fm[tgt]["type"] != "Collection(Edm.Single)" else val
            mode_p = ((sk.get("indexProjections") or {}).get("parameters") or {}).get("projectionMode", "includeIndexingParentDocuments")
            for tname, children in vec.project(sk, tree, doc[keyf]).items():
                trec = svc["_indexes"].get(tname)
                if trec is None:
                    res["itemsFailed"] += 1
                    res["errors"].append({"key": bname, "errorMessage": f"Projection target index '{tname}' does not exist."})
                    continue
                tkey = next(f["name"] for f in trec["_def"]["fields"] if f["key"])
                tfm = _fmap(trec["_def"])
                pk = [s2["parentKeyFieldName"] for s2 in sk["indexProjections"]["selectors"] if s2["targetIndexName"] == tname][0]
                for stale in [k for k, d in trec["_docs"].items() if d.get(pk) == doc[keyf]]:
                    trec["_docs"].pop(stale)   # re-index of a parent replaces its chunks
                for ch in children:
                    n_ord = ch.pop("__ordinal")
                    cdoc = {k: v for k, v in ch.items() if k in tfm}
                    cdoc[tkey] = vec.child_key(doc[keyf], n_ord)
                    cr = _docs_index(trec, {"value": [dict(cdoc, **{"@search.action": "mergeOrUpload"})]})["body"]["value"][0]
                    if cr["status"]:
                        res["itemsProcessed"] += 1
                    else:
                        res["itemsFailed"] += 1
                        res["errors"].append({"key": bname, "errorMessage": cr["errorMessage"]})
            if mode_p == "skipIndexingParentDocuments":
                seen.add(doc[keyf])
                continue
        r = _docs_index(idx_rec, {"value": [dict(doc, **{"@search.action": "mergeOrUpload"})]})["body"]["value"][0]
        seen.add(doc[keyf])
        if r["status"]:
            res["itemsProcessed"] += 1
        else:
            res["itemsFailed"] += 1
            res["errors"].append({"key": bname, "errorMessage": r["errorMessage"]})


def run_indexer(svc, ix_name, blob_store, account_lookup=None, cosmos_store=None, sql_store=None):
    ix = svc["_indexers"].get(ix_name)
    started = _now()
    status = svc["_ix_status"].setdefault(ix_name, {"status": "running", "lastResult": None, "executionHistory": []})
    res = {"status": "success", "errorMessage": None, "startTime": started, "endTime": None, "itemsProcessed": 0, "itemsFailed": 0, "errors": [],
           "initialTrackingState": None, "finalTrackingState": None}
    ds = svc["_datasources"].get(ix["dataSourceName"])
    idx_rec = svc["_indexes"].get(ix["targetIndexName"])
    if ds is None or idx_rec is None:
        res.update(status="transientFailure", errorMessage="The data source or target index no longer exists.")
    elif ds["type"] in ("cosmosdb", "azuresql"):
        wm = status.get("_hwm")
        res["initialTrackingState"] = None if wm is None else str(wm)
        rows, new_wm, err = srcs.read(ds, cosmos_store, sql_store, wm)
        if err:
            res.update(status="transientFailure", errorMessage=err)
        else:
            keyf = next(f["name"] for f in idx_rec["_def"]["fields"] if f["key"])
            seen = set()
            for n, row in enumerate(rows):
                if srcs.is_deleted(ds, row):
                    try:
                        k = apply_field_mappings(ix, row).get(keyf)
                    except (ValueError, json.JSONDecodeError):
                        k = None
                    if k is not None:
                        idx_rec["_docs"].pop(str(k), None)
                        res["itemsProcessed"] += 1
                    continue
                _index_rows(svc, ix, idx_rec, ds, res, str(row.get("id", row.get(keyf, n))), [row], {}, None, seen)
            status["_hwm"] = new_wm
            res["finalTrackingState"] = None if new_wm is None else str(new_wm)
            max_fail = (ix.get("parameters") or {}).get("maxFailedItems", 0)
            if res["itemsFailed"] > max_fail >= 0:
                res.update(status="transientFailure", errorMessage="Indexer failed: items failed exceeded maxFailedItems.")
    elif ds["type"] != "azureblob":
        res.update(status="transientFailure", errorMessage=f"Data source type '{ds['type']}' is not readable by Vyomi indexers (azureblob, cosmosdb and azuresql are).")
    elif blob_store is None:
        res.update(status="transientFailure", errorMessage="No Blob store is attached to this search service.")
    else:
        acct = _conn_account(ds["credentials"].get("connectionString", ""))
        cont = ds["container"]["name"]
        prefix = (ds["container"].get("query") or "")
        key = f"{acct}/{cont}" if acct and acct != "devstoreaccount1" else cont
        if not blob_store.container_exists(key) and (not acct or acct == "devstoreaccount1"):
            # "UseDevelopmentStorage=true" (no account name): the account is whichever one holds a container of that name (sole match)
            hits = [k for k in list(getattr(blob_store, "containers", {}) or {}) if k.endswith("/" + cont)]
            if len(hits) == 1:
                key, acct = hits[0], hits[0].rsplit("/", 1)[0]
        if not blob_store.container_exists(key):
            res.update(status="transientFailure", errorMessage=f"The container '{cont}' does not exist in storage account '{acct}'.")
        else:
            mode = ((ix.get("parameters") or {}).get("configuration") or {}).get("parsingMode", "default")
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
                meta = {"metadata_storage_name": bname.rsplit("/", 1)[-1], "metadata_storage_path": path,
                        "metadata_storage_size": len(data), "metadata_content_type": entry.get("content_type") or entry.get("content-type")}
                _index_rows(svc, ix, idx_rec, ds, res, bname, rows, meta, path, seen)
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


def dispatch(state, method, sub, rg, chain, payload, query, blob_store=None, base="", cosmos_store=None, sql_store=None):
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
    if op in ("datasources", "indexers", "skillsets"):
        rec.setdefault("_skillsets", {})
        return _ds_ix(rec, op, method, chain[3:], payload, blob_store, cosmos_store, sql_store)
    if op in ("synonymmaps", "aliases"):
        return _simple_store(rec, op, method, chain[3:], payload)
    if op == "stats" and method == "GET":
        q = SKUS[rec["sku"]["name"]][2]
        return _ok({"counters": {"documentCount": {"usage": sum(len(i["_docs"]) for i in rec["_indexes"].values()), "quota": None},
                                 "indexesCount": {"usage": len(rec["_indexes"]), "quota": q},
                                 "indexersCount": {"usage": len(rec["_indexers"]), "quota": q},
                                 "dataSourcesCount": {"usage": len(rec["_datasources"]), "quota": q},
                                 "aliasesCount": {"usage": len(rec.get("_aliases") or {}), "quota": q},
                                 "storageSize": {"usage": sum(len(json.dumps(d)) for i in rec["_indexes"].values() for d in i["_docs"].values()), "quota": None},
                                 "synonymMaps": {"usage": len(rec.get("_synonymmaps") or {}), "quota": q},
                                 "skillsetCount": {"usage": len(rec.get("_skillsets") or {}), "quota": q},
                                 "vectorIndexSize": {"usage": 0, "quota": None}},
                    "limits": {"maxFieldsPerIndex": 1000, "maxFieldNestingDepthPerIndex": 10, "maxComplexCollectionFieldsPerIndex": 40,
                               "maxComplexObjectsInCollectionsPerDocument": 3000}})
    return _err(404, "ResourceNotFound", f"Unknown search service operation '{chain[2]}'.")


def _simple_store(svc, kind, method, rest, payload):
    """synonymmaps / aliases: validated + stored (CRUD with ETags); synonyms are not applied at query time."""
    st = svc.setdefault("_" + kind, {})
    if not rest:
        if method == "GET":
            return _ok({"value": list(st.values())})
        if method == "POST":
            rest = [(payload or {}).get("name")]
            method = "PUT"
        else:
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    name = rest[0]
    if method == "GET":
        return _ok(st[name]) if name in st else _err(404, "ResourceNotFound", f"{kind[:-1]} '{name}' was not found.")
    if method == "DELETE":
        if name not in st:
            return _err(404, "ResourceNotFound", f"{kind[:-1]} '{name}' was not found.")
        st.pop(name)
        return {"status": 204, "body": None}
    if method == "PUT":
        b = dict(payload or {})
        if not name or not re.match(r"^[a-z0-9][a-z0-9\-]{0,126}[a-z0-9]$|^[a-z0-9]$", name):
            return _err(400, "InvalidRequest", "Names are lower-case letters, digits and dashes.")
        if kind == "synonymmaps" and not isinstance(b.get("synonyms"), str):
            return _err(400, "InvalidRequest", "synonyms (Solr rules, newline separated) is required.")
        if kind == "aliases" and not (isinstance(b.get("indexes"), list) and len(b["indexes"]) == 1 and b["indexes"][0] in svc["_indexes"]):
            return _err(400, "InvalidRequest", "An alias maps to exactly one existing index.")
        existed = name in st
        b["name"] = name
        b["@odata.etag"] = '"0x%s"' % uuid.uuid4().hex[:14].upper()
        st[name] = b
        return _ok(b, 200 if existed else 201)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def suggest(index_rec, params, auto=False):
    """docs/search.post.suggest + search.post.autocomplete over the index's suggester (prefix match on words of the sourceFields)."""
    idx, docs = index_rec["_def"], index_rec["_docs"]
    params = params or {}
    sg = next((x for x in idx.get("suggesters") or [] if x.get("name") == params.get("suggesterName")), None)
    if sg is None:
        return _err(400, "InvalidRequest", f"The suggester '{params.get('suggesterName')}' was not found on the index.")
    q = str(params.get("search") or "").strip().lower()
    if not q:
        return _err(400, "InvalidRequest", "The 'search' parameter is required.")
    try:
        pred = compile_filter(params["filter"], idx) if params.get("filter") else (lambda d: True)
    except ValueError as e:
        return _err(400, "InvalidRequest", str(e))
    top = int(params.get("top") or 5)
    keyf = next(f["name"] for f in idx["fields"] if f["key"])
    cand = [d for d in docs.values() if pred(d)]
    if auto:
        head, _, last = q.rpartition(" ")
        mode = str(params.get("autocompleteMode") or "oneTerm").lower()
        counts = {}
        for d in cand:
            for fld in sg["sourceFields"]:
                v = d.get(fld)
                words = re.findall(r"[A-Za-z0-9_']+", " ".join(v) if isinstance(v, list) else str(v or ""))
                low = [w.lower() for w in words]
                for i, w in enumerate(low):
                    if w.startswith(last) and (not head or " ".join(low[max(0, i - len(head.split())):i]) == head):
                        c = w if mode == "oneterm" else (" ".join(low[i:i + 2]) if mode == "twoterms" else (head + " " + w).strip())
                        counts[c] = counts.get(c, 0) + 1
        comp = [c for c, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:top]
        return _ok({"value": [{"text": c, "queryPlusText": c if mode == "onetermwithcontext" else (head + " " + c).strip()} for c in comp]})
    sel = params.get("select")
    cols = [c.strip() for c in (sel.split(",") if isinstance(sel, str) else sel)] if sel else [keyf]
    out = []
    for d in cand:
        for fld in sg["sourceFields"]:
            v = d.get(fld)
            txt = " ".join(v) if isinstance(v, list) else str(v or "")
            if re.search(r"(?:^|\W)" + re.escape(q), txt.lower()):
                out.append(dict({"@search.text": txt}, **{c: d.get(c) for c in cols}))
                break
    return _ok({"value": out[:top]})


# ───────── native data-plane wire (azure-search-documents: SearchIndexClient / SearchClient / SearchIndexerClient) ─────────
WIRE_ROOTS = ("indexes", "datasources", "indexers", "skillsets", "synonymmaps", "aliases", "servicestats")


def wire_owns(path, query=None) -> bool:
    """A root-level Azure AI Search data-plane path (`/indexes('kb')/docs/search.post.search?api-version=...`)."""
    head = path.lstrip("/").split("/", 1)[0].split("(", 1)[0]
    return head in WIRE_ROOTS and "api-version" in (query or {})


_ODATA = re.compile(r"^([A-Za-z]+)\('((?:[^']|'')*)'\)$")


def wire_chain(path):
    """OData wire path -> the engine's chain tail: `indexes('kb')/docs/search.post.search` -> ['indexes','kb','docs','search']."""
    out = []
    for seg in [x for x in path.split("/") if x]:
        m = _ODATA.match(seg)
        if m:
            out += [m.group(1), m.group(2).replace("''", "'")]
            continue
        seg = {"$count": "count", "search.post.search": "search", "search.post.suggest": "suggest", "search.post.autocomplete": "autocomplete",
               "search.index": "index", "search.stats": "stats", "search.run": "run", "search.status": "status", "search.reset": "reset",
               "search.resetdocs": "resetdocs", "search.resync": "resync"}.get(seg, seg)
        out.append(seg)
    if out and out[0] == "servicestats":
        out = ["stats"]
    return out


def wire_dispatch(state, svc_hint, method, path, query, headers, body, **stores):
    """Serve one native data-plane request: pick the service (hint = host / path prefix name; else the only service), check the
    api-key (admin or query key), translate the OData path, and run the same engine the ARM-extension path uses."""
    lh = {k.lower(): v for k, v in (headers or {}).items()}
    svcs = _services(state)
    if svc_hint and svc_hint != "_":
        svc = next((r for r in svcs if r["name"].lower() == svc_hint.lower()), None)
        if svc is None:
            return _err(404, "ResourceNotFound", f"The search service '{svc_hint}' was not found.")
    elif len(svcs) == 1:
        svc = svcs[0]
    elif not svcs:
        return _err(404, "ResourceNotFound", "No Azure AI Search service exists in this space.")
    else:
        return _err(400, "AmbiguousService", "Several search services exist; address one as <host>/azure-data/search/<service> or https://<service>.search.* .")
    key = lh.get("api-key")
    auth = lh.get("authorization", "")
    admin = auth.lower().startswith("bearer ") or key in (svc["_admin"]["primary"], svc["_admin"]["secondary"])
    if not admin and not (key and key in svc["_query"]):
        return _err(403, "Forbidden", "Access denied: a valid api-key (admin or query key) or bearer token is required.")
    method = method.upper()
    chain = wire_chain(path)
    payload = None
    if body:
        try:
            payload = json.loads(body)
        except ValueError:
            return _err(400, "InvalidRequest", "The request body is not valid JSON.")
    if not admin:         # query keys: read documents + run queries only
        okq = len(chain) >= 3 and chain[0] == "indexes" and chain[2] == "docs" and (
            method == "GET" or (method == "POST" and len(chain) == 4 and chain[3] in ("search", "suggest", "autocomplete")))
        if not okq:
            return _err(403, "Forbidden", "This operation requires an admin key.")
    r = dispatch(state, method, svc["_sub"], svc["_rg"], ["searchServices", svc["name"]] + chain, payload, query or {}, **stores)
    if chain[:1] == ["indexes"] and chain[2:4] == ["docs", "count"] and r["status"] == 200:
        r = dict(r, text=str(r["body"]))      # `docs/$count` answers the bare number as text/plain
    return r


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
        if sub in ("suggest", "autocomplete") and method in ("POST", "GET"):
            return suggest(rec, payload if method == "POST" else query, sub == "autocomplete")
        if sub == "count" and method == "GET":
            return _ok(len(rec["_docs"]))
        if len(rest) == 3 and method == "GET":
            d = rec["_docs"].get(rest[2])
            return _ok(d) if d else _err(404, "DocumentNotFound", f"Document with key '{rest[2]}' not found.")
    if rest[1].lower() in ("chunks", "retrieve-trace"):
        return inspect_index(rec, rest[1].lower(), method, payload, query)
    if rest[1].lower() == "stats" and method == "GET":
        return _ok({"documentCount": len(rec["_docs"]), "storageSize": sum(len(json.dumps(d)) for d in rec["_docs"].values()),
                    "vectorIndexSize": sum(4 * len(v) for d in rec["_docs"].values() for v in d.values() if isinstance(v, list) and v and isinstance(v[0], float))})
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


def _ds_ix(svc, kind, method, rest, payload, blob_store, cosmos_store=None, sql_store=None):
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
            if kind == "skillsets" and any(x.get("skillsetName") == name for x in svc["_indexers"].values()):
                return _err(409, "ResourceInUse", "The skillset is used by an indexer.")
            store.pop(name)
            svc["_ix_status"].pop(name, None)
            return {"status": 204, "body": None}
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    if kind == "indexers" and name in store:
        if rest[1].lower() == "run" and method == "POST":
            if (svc["_ix_status"].get(name) or {}).get("status") == "running" and (store[name].get("disabled")):
                return _err(409, "IndexerDisabled", "The indexer is disabled.")
            run_indexer(svc, name, blob_store, cosmos_store=cosmos_store, sql_store=sql_store)
            return {"status": 202, "body": None}
        if rest[1].lower() == "status" and method == "GET":
            st_ = svc["_ix_status"].get(name) or {"status": "running", "lastResult": None, "executionHistory": []}
            return _ok({k: v for k, v in st_.items() if not k.startswith("_")})
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
        pol = body.get("dataChangeDetectionPolicy")
        if pol:
            if not str(pol.get("@odata.type", "")).endswith(("HighWaterMarkChangeDetectionPolicy", "SqlIntegratedChangeTrackingPolicy")):
                return _err(400, "InvalidRequest", "dataChangeDetectionPolicy must be a HighWaterMarkChangeDetectionPolicy or SqlIntegratedChangeTrackingPolicy.")
            if str(pol["@odata.type"]).endswith("HighWaterMarkChangeDetectionPolicy") and not pol.get("highWaterMarkColumnName"):
                return _err(400, "InvalidRequest", "highWaterMarkColumnName is required.")
        dpol = body.get("dataDeletionDetectionPolicy")
        if dpol and str(dpol.get("@odata.type", "")).endswith("SoftDeleteColumnDeletionDetectionPolicy") and not dpol.get("softDeleteColumnName"):
            return _err(400, "InvalidRequest", "softDeleteColumnName is required.")
    elif kind == "skillsets":
        e = vec.validate_skillset(body)
        if e:
            return _err(400, "InvalidRequest", e)
    else:
        if body.get("skillsetName") and body["skillsetName"] not in svc.get("_skillsets", {}):
            return _err(400, "InvalidRequest", f"Skillset '{body['skillsetName']}' does not exist.")
        for req in ("dataSourceName", "targetIndexName"):
            if not body.get(req):
                return _err(400, "InvalidRequest", f"{req} is required.")
        if body["dataSourceName"] not in svc["_datasources"]:
            return _err(400, "InvalidRequest", f"Data source '{body['dataSourceName']}' does not exist.")
        if body["targetIndexName"] not in svc["_indexes"]:
            return _err(400, "InvalidRequest", f"Index '{body['targetIndexName']}' does not exist.")
        for m in (body.get("fieldMappings") or []) + (body.get("outputFieldMappings") or []):
            if not m.get("sourceFieldName"):
                return _err(400, "InvalidRequest", "Every field mapping needs a sourceFieldName.")
            fn = (m.get("mappingFunction") or {}).get("name")
            if fn and fn not in ("base64Encode", "base64Decode", "urlEncode", "urlDecode", "jsonArrayToStringCollection"):
                return _err(400, "InvalidRequest", f"Mapping function '{fn}' is not supported (base64Encode, base64Decode, urlEncode, urlDecode, jsonArrayToStringCollection).")
        mode = ((body.get("parameters") or {}).get("configuration") or {}).get("parsingMode", "default")
        if mode not in ("default", "text", "json", "jsonArray", "delimitedText"):
            return _err(400, "InvalidRequest", "parsingMode must be default, text, json, jsonArray or delimitedText.")
        sched = (body.get("schedule") or {}).get("interval")
        if sched and not re.match(r"^P(T(\d+H)?(\d+M)?|\d+D)$", sched):
            return _err(400, "InvalidRequest", "schedule.interval must be an ISO-8601 duration of at least PT5M.")
    body["@odata.etag"] = '"0x%s"' % uuid.uuid4().hex[:14].upper()
    svc["_" + kind][name] = body
    return _ok(body, status)


# ───────────────────────── Vyomi inspect extension (RAG Studio) ─────────────────────────
# GET  /_vyomi/azure/search/{svc}/indexes/{ix}/chunks[?vectors=true]   (also ARM-extension path .../searchServices/{svc}/indexes/{ix}/chunks)
# POST /_vyomi/azure/search/{svc}/indexes/{ix}/retrieve-trace          (body = a normal docs/search body; plain search output is unchanged)
def _first(idx, pred):
    return next((f for f in idx["fields"] if pred(f)), None)


def _project2d(rows, vecs):
    """2-D PCA projection (power iteration, pure Python): same maths as core/bedrock_agents_core._project2d."""
    n = len(vecs)
    if n < 2:
        for r in rows:
            r["projection2d"] = [0.0, 0.0]
        return
    d = len(vecs[0])
    mean = [sum(v[j] for v in vecs) / n for j in range(d)]
    X = [[v[j] - mean[j] for j in range(d)] for v in vecs]
    comps = []
    for c in range(2):
        w = [((j * 7919 + c * 104729) % 1000) / 1000.0 - 0.5 for j in range(d)]
        for _ in range(25):
            t = [sum(x[j] * w[j] for j in range(d)) for x in X]
            nw = [sum(X[i][j] * t[i] for i in range(n)) for j in range(d)]
            norm = sum(a * a for a in nw) ** 0.5 or 1.0
            w = [a / norm for a in nw]
        comps.append(w)
        X = [[x[j] - sum(x[m] * w[m] for m in range(d)) * w[j] for j in range(d)] for x in X]
    for i, r in enumerate(rows):
        c = [v - m for v, m in zip(vecs[i], mean)]
        r["projection2d"] = [round(sum(c[j] * comps[k][j] for j in range(d)), 6) for k in range(2)]


_PII = (("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")), ("phone", re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b")), ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")))


def inspect_index(index_rec, what, method, payload, query):
    idx = index_rec["_def"]
    vf = _first(idx, lambda f: f["type"] == "Collection(Edm.Single)")
    keyf = next(f["name"] for f in idx["fields"] if f["key"])
    strs = [f["name"] for f in idx["fields"] if f["type"] == "Edm.String" and not f["key"]]
    textf = next((n for n in ("chunk", "content", "text") if n in strs), strs[0] if strs else keyf)
    urif = next((n for n in ("parent_id", "title", "metadata_storage_path", "source") if any(f["name"] == n for f in idx["fields"])), None)
    if what == "chunks":
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET only.")
        want_vec = str((query or {}).get("vectors", "false")).lower() == "true"
        docs = list(index_rec["_docs"].values())
        meta_skip = {keyf, textf, vf["name"] if vf else None}
        rows, vecs = [], []
        for d in docs:
            t = str(d.get(textf) or "")
            pii = [n for n, rx in _PII if rx.search(t)]
            rows.append({"id": d[keyf], "documentUri": str(d.get(urif) or d[keyf]) if urif else d[keyf], "text": t, "tokenCount": len(tokenize(t)),
                         "metadata": {k: v for k, v in d.items() if k not in meta_skip and not isinstance(v, (list, dict))}, "section": str(d.get("title") or ""),
                         "pii": pii or "ok", "projection2d": None, "vector": d.get(vf["name"]) if (vf and want_vec) else None})
            if vf and d.get(vf["name"]):
                vecs.append(d[vf["name"]])
        if len(vecs) == len(rows):
            _project2d(rows, vecs)
        else:
            for r in rows:
                r["projection2d"] = [0.0, 0.0]
        return _ok({"index": idx["name"], "count": len(rows), "dimensions": vf["dimensions"] if vf else 0, "textField": textf, "vectorField": vf["name"] if vf else None, "chunks": rows})
    if method != "POST":
        return _err(405, "MethodNotAllowed", "POST only.")
    p = {k: v for k, v in dict(payload or {}).items() if k not in ("$select", "select")}
    tr = {}
    r = search(index_rec, dict(p, **{"$top": p.get("$top") or p.get("top") or 50}), _trace=tr)
    if r["status"] != 200:
        return r
    fmap = {d[keyf]: d for d in index_rec["_docs"].values()}
    def rank(m):
        return {k: i for i, (k, _v) in enumerate(sorted(m.items(), key=lambda kv: -kv[1]), 1)}
    kr, vr = rank(tr.get("keyword", {})), rank(tr.get("vector", {}))
    fr, rr = rank(tr.get("fused", {})), rank(tr.get("reranker", {}))
    finals = [row.get(keyf) for row in r["body"]["value"]]
    if vf:
        for row in r["body"]["value"]:
            row.pop(vf["name"], None)
    k = int(p.get("$top") or p.get("top") or 50)
    keys = list(dict.fromkeys(finals + list(fr) + list(kr) + list(vr)))[: max(k * 3, 30)]
    cand = []
    for key in keys:
        d = fmap.get(key, {})
        cand.append({"chunkId": key, "uri": str(d.get(urif) or key) if urif else key, "text": str(d.get(textf) or ""),
                     "keyword_score": tr.get("keyword", {}).get(key), "keyword_rank": kr.get(key),
                     "vector_score": tr.get("vector", {}).get(key), "vector_rank": vr.get(key),
                     "fused_score": tr.get("fused", {}).get(key), "fused_rank": fr.get(key),
                     "reranker_score": tr.get("reranker", {}).get(key), "reranker_rank": rr.get(key),
                     "final_rank": finals.index(key) + 1 if key in finals else None})
    return _ok({"value": r["body"]["value"], "trace": {"candidates": cand, "filtered": tr.get("candidates"), "finalOrder": finals, "total": len(fmap),
                                                      "semanticRanker": "approximation" if "reranker" in tr else None,
                                                      "searchType": "hybrid" if tr.get("keyword") and tr.get("vector") else "vector" if tr.get("vector") else "keyword"}})


def inspect_dispatch(state, svc_name, method, path, query, body, headers=None, **_stores):
    """Vyomi extension route: /_vyomi/azure/search/{svc}/indexes/{ix}/(chunks|retrieve-trace). `path` is the part after the service name."""
    svc = next((r for r in _services(state) if r["name"].lower() == (svc_name or "").lower()), None)
    if svc is None:
        return _err(404, "ResourceNotFound", f"The search service '{svc_name}' was not found.")
    lh = {k.lower(): v for k, v in (headers or {}).items()}
    if not (lh.get("authorization", "").lower().startswith("bearer ") or lh.get("api-key") in (svc["_admin"]["primary"], svc["_admin"]["secondary"])):
        return _err(403, "Forbidden", "Access denied: an admin api-key or bearer token is required.")
    segs = [x for x in path.strip("/").split("/") if x]
    if len(segs) != 3 or segs[0] != "indexes" or segs[2] not in ("chunks", "retrieve-trace"):
        return _err(404, "ResourceNotFound", f"Unsupported inspect route: {method} {path}")
    ix = svc["_indexes"].get(segs[1])
    if ix is None:
        return _err(404, "IndexNotFound", f"Index '{segs[1]}' was not found.")
    payload = None
    if body:
        try:
            payload = json.loads(body)
        except ValueError:
            return _err(400, "InvalidRequest", "The request body is not valid JSON.")
    return inspect_index(ix, segs[2], method.upper(), payload, query or {})
