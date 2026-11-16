"""Amazon OpenSearch Service + OpenSearch Serverless: control plane and the REST data-plane subset opensearch-py uses.

Substrate-independent (Nano Pyodide + Mesh). State lives in the S3 store's persisted account bag: ``store.account["opensearch"]``.

Control plane
  * ``opensearch`` (signing name ``es``, rest-json under /2021-01-01/): CreateDomain, DescribeDomain(s), DescribeDomainConfig, UpdateDomainConfig,
    DeleteDomain, ListDomainNames, ListVersions, AddTags/ListTags/RemoveTags, DescribeDomainHealth.
  * ``opensearchserverless`` (JSON 1.0, target ``OpenSearchServerless.*``): collections (the real rule is enforced: a collection needs a
    matching ENCRYPTION security policy first), security + access policies, tags, account settings.
Data plane (what opensearch-py / curl hit on the domain or collection endpoint)
  index create/get/head/delete, _mapping, _doc CRUD, _bulk (index/create/update/delete), _search (+ _count, _refresh, _delete_by_query,
  _cluster/health, _cat/indices). Query DSL: match_all, match, multi_match, match_phrase, term(s), range, exists, ids, prefix, wildcard,
  query_string (simple), bool, knn (field vector + k + filter; cosinesimil/l2/innerproduct), hybrid (min-max normalised mean of sub-queries).

Ranking engine = core/knowledge_core (SQLite FTS5 BM25 + cosine over stored vectors); no engine of our own.
Honest limits: one flat index namespace shared by every domain/collection endpoint; no aggregations/highlighting/scroll; kNN is an exact
scan (no HNSW), fine to ~10k docs; analyzers are the FTS5 unicode61 tokenizer; domains are metadata (no cluster is started).
"""
from __future__ import annotations

import fnmatch
import json
import random
import re
import string
import time
from datetime import datetime, timezone

try:
    from core import knowledge_core as kc
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import knowledge_core as kc  # type: ignore
    import llm_core as llm  # type: ignore

_ACCT = "123456789012"
_REGION = "us-east-1"
_JSON = {"content-type": "application/json"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _epoch():
    return time.time()


def _rid(n=10):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _resp(status, doc, headers=None):
    return {"status": status, "headers": {**_JSON, **(headers or {})}, "body": b"" if doc is None else json.dumps(doc).encode()}


def _state(store):
    st = store.account.setdefault("opensearch", {})
    for k in ("domains", "collections", "policies", "indices", "tags"):
        st.setdefault(k, {})
    return st


def _persist(store):
    try:
        store.persist()
    except Exception:  # noqa: BLE001
        pass


# ══════════════════════════════ control plane: OpenSearch Service ══════════════════════════════
class _CErr(Exception):
    def __init__(self, code, msg, status):
        self.code, self.msg, self.status = code, msg, status


def _cerr(e):
    return {"status": e.status, "headers": {**_JSON, "x-amzn-errortype": e.code}, "body": json.dumps({"message": e.msg}).encode()}


_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9\-]{2,27}$")
_VERSIONS = ["OpenSearch_2.17", "OpenSearch_2.15", "OpenSearch_2.13", "OpenSearch_2.11", "OpenSearch_2.9", "OpenSearch_1.3"]


def _domain_status(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _create_domain(st, p):
    name = p.get("DomainName") or ""
    if not _DOMAIN_RE.match(name):
        raise _CErr("ValidationException", f"1 validation error detected: Value '{name}' at 'domainName' failed to satisfy constraint: "
                    "Member must satisfy regular expression pattern: [a-z][a-z0-9\\-]+ and have length 3..28", 400)
    if name in st["domains"]:
        raise _CErr("ResourceAlreadyExistsException", f"Domain with name {name} already exists", 409)
    ver = p.get("EngineVersion") or "OpenSearch_2.17"
    if ver not in _VERSIONS and not ver.startswith("Elasticsearch_"):
        raise _CErr("ValidationException", f"Invalid engine version {ver}", 400)
    did = _rid(12)
    d = {"DomainId": f"{_ACCT}/{name}", "DomainName": name, "ARN": f"arn:aws:es:{_REGION}:{_ACCT}:domain/{name}", "Created": True, "Deleted": False,
         "Endpoint": f"search-{name}-{did}.{_REGION}.es.amazonaws.com", "Processing": False, "UpgradeProcessing": False, "EngineVersion": ver,
         "ClusterConfig": {"InstanceType": "t3.small.search", "InstanceCount": 1, "DedicatedMasterEnabled": False, "ZoneAwarenessEnabled": False,
                           "WarmEnabled": False, "ColdStorageOptions": {"Enabled": False}, **(p.get("ClusterConfig") or {})},
         "EBSOptions": {"EBSEnabled": True, "VolumeType": "gp3", "VolumeSize": 10, **(p.get("EBSOptions") or {})},
         "AccessPolicies": p.get("AccessPolicies") or "", "IPAddressType": p.get("IPAddressType", "ipv4"),
         "SnapshotOptions": {"AutomatedSnapshotStartHour": 0}, "EncryptionAtRestOptions": p.get("EncryptionAtRestOptions") or {"Enabled": False},
         "NodeToNodeEncryptionOptions": p.get("NodeToNodeEncryptionOptions") or {"Enabled": False},
         "AdvancedOptions": p.get("AdvancedOptions") or {}, "DomainEndpointOptions": p.get("DomainEndpointOptions") or {"EnforceHTTPS": True},
         "AdvancedSecurityOptions": {"Enabled": bool((p.get("AdvancedSecurityOptions") or {}).get("Enabled")), "InternalUserDatabaseEnabled": False},
         "ServiceSoftwareOptions": {"CurrentVersion": "R20240101", "NewVersion": "", "UpdateAvailable": False, "Cancellable": False,
                                    "UpdateStatus": "COMPLETED", "Description": "There is no software update available for this domain.",
                                    "AutomatedUpdateDate": 0, "OptionalDeployment": True}}
    st["domains"][name] = d
    if p.get("TagList"):
        st["tags"][d["ARN"]] = list(p["TagList"])
    return _resp(200, {"DomainStatus": _domain_status(d)})


def _domain_config(d):
    def opt(v):
        return {"Options": v, "Status": {"CreationDate": _epoch(), "UpdateDate": _epoch(), "UpdateVersion": 1, "State": "Active", "PendingDeletion": False}}
    return {k: opt(d[k]) for k in ("EngineVersion", "ClusterConfig", "EBSOptions", "AccessPolicies", "IPAddressType", "SnapshotOptions",
                                    "EncryptionAtRestOptions", "NodeToNodeEncryptionOptions", "AdvancedOptions", "DomainEndpointOptions",
                                    "AdvancedSecurityOptions")}


def _find_domain(st, name):
    d = st["domains"].get(name)
    if not d:
        raise _CErr("ResourceNotFoundException", f"Domain not found: {name}", 409 if False else 409)
    return d


def control_dispatch(store, method, path, query, headers, body):
    st = _state(store)
    method = method.upper()
    path = path.split("?", 1)[0]
    try:
        p = json.loads(body) if body else {}
    except ValueError:
        return _resp(400, {"message": "Malformed request body"}, {"x-amzn-errortype": "ValidationException"})
    segs = [s for s in path.strip("/").split("/")]
    try:
        if path.rstrip("/") == "/2021-01-01/opensearch/domain" and method == "POST":
            out = _create_domain(st, p)
        elif path.rstrip("/") == "/2021-01-01/domain" and method == "GET":
            out = _resp(200, {"DomainNames": [{"DomainName": n, "EngineType": "OpenSearch" if d["EngineVersion"].startswith("Open") else "Elasticsearch"}
                                              for n, d in st["domains"].items()]})
        elif path.rstrip("/") == "/2021-01-01/opensearch/domain-info" and method == "POST":
            out = _resp(200, {"DomainStatusList": [_domain_status(st["domains"][n]) for n in p.get("DomainNames", []) if n in st["domains"]]})
        elif path.rstrip("/") == "/2021-01-01/opensearch/versions" and method == "GET":
            out = _resp(200, {"Versions": _VERSIONS})
        elif path.startswith("/2021-01-01/opensearch/domain/") and len(segs) >= 4:
            name = segs[3]
            d = _find_domain(st, name)
            if len(segs) == 4 and method == "GET":
                out = _resp(200, {"DomainStatus": _domain_status(d)})
            elif len(segs) == 4 and method == "DELETE":
                del st["domains"][name]
                out = _resp(200, {"DomainStatus": {**_domain_status(d), "Deleted": True}})
            elif segs[4:] == ["config"] and method == "GET":
                out = _resp(200, {"DomainConfig": _domain_config(d)})
            elif segs[4:] == ["config"] and method == "POST":
                for k in ("ClusterConfig", "EBSOptions", "AccessPolicies", "AdvancedOptions", "SnapshotOptions", "DomainEndpointOptions"):
                    if k in p:
                        d[k] = {**d[k], **p[k]} if isinstance(p[k], dict) and isinstance(d.get(k), dict) else p[k]
                out = _resp(200, {"DomainConfig": _domain_config(d)})
            elif segs[4:] == ["health"] and method == "GET":
                out = _resp(200, {"ClusterHealth": "Green", "ActiveAvailabilityZoneCount": "1", "StandByAvailabilityZoneCount": "0",
                                  "DataNodeCount": "1", "DedicatedMaster": False, "MasterEligibleNodeCount": "1", "WarmNodeCount": "0",
                                  "MasterNode": "Available", "ClusterStatuses": {}}) if False else _resp(200, {"ClusterHealth": "Green", "DataNodeCount": "1"})
            else:
                raise _CErr("UnknownOperationException", f"Unsupported OpenSearch operation: {method} {path}", 404)
        elif path.rstrip("/") == "/2021-01-01/tags" and method == "POST":
            arn = p.get("ARN", "")
            cur = {t["Key"]: t["Value"] for t in st["tags"].get(arn, [])}
            cur.update({t["Key"]: t["Value"] for t in p.get("TagList", [])})
            st["tags"][arn] = [{"Key": k, "Value": v} for k, v in cur.items()]
            out = _resp(200, None)
        elif path.rstrip("/") == "/2021-01-01/tags" and method == "GET":
            out = _resp(200, {"TagList": st["tags"].get((query or {}).get("arn", ""), [])})
        elif path.rstrip("/") == "/2021-01-01/tags-removal" and method == "POST":
            st["tags"][p.get("ARN", "")] = [t for t in st["tags"].get(p.get("ARN", ""), []) if t["Key"] not in p.get("TagKeys", [])]
            out = _resp(200, None)
        else:
            raise _CErr("UnknownOperationException", f"Unsupported OpenSearch operation: {method} {path}", 404)
    except _CErr as e:
        return _cerr(e)
    _persist(store)
    return out


# ══════════════════════════════ control plane: OpenSearch Serverless ══════════════════════════════
_COLL_NAME = re.compile(r"^[a-z][a-z0-9\-]{2,31}$")


def _res_matches(rules, name, rtype):
    for r in rules or []:
        if r.get("ResourceType") != rtype:
            continue
        for res in r.get("Resource") or []:
            if fnmatch.fnmatch(f"collection/{name}", res):
                return True
    return False


def _policy_matches(st, ptype, name, rtype="collection"):
    for pol in st["policies"].values():
        if pol["type"] != ptype or pol.get("_kind") != "security":
            continue
        try:
            doc = json.loads(pol["policy"]) if isinstance(pol["policy"], str) else pol["policy"]
        except ValueError:
            continue
        for stmt in doc if isinstance(doc, list) else [doc]:
            if _res_matches(stmt.get("Rules"), name, rtype):
                return True
    return False


def _coll_detail(c):
    return {k: v for k, v in c.items() if not k.startswith("_")}


def serverless_dispatch(store, target, body):
    st = _state(store)
    op = target.split(".", 1)[-1]
    try:
        p = json.loads(body) if body else {}
    except ValueError:
        return _serr("ValidationException", "Malformed request body", 400)
    try:
        out = _serverless(st, op, p)
    except _CErr as e:
        return _serr(e.code, e.msg, e.status)
    _persist(store)
    return {"status": 200, "headers": {"content-type": "application/x-amz-json-1.0"}, "body": json.dumps(out).encode()}


def _serr(code, msg, status):
    return {"status": status, "headers": {"content-type": "application/x-amz-json-1.0", "x-amzn-errortype": code},
            "body": json.dumps({"__type": code, "message": msg}).encode()}


def _coll_by(st, p):
    out = []
    for i in p.get("ids") or []:
        c = st["collections"].get(i)
        out.append(c)
    for n in p.get("names") or []:
        out.append(next((c for c in st["collections"].values() if c["name"] == n), None))
    return out


def _serverless(st, op, p):
    colls = st["collections"]
    if op == "CreateCollection":
        name = p.get("name") or ""
        if not _COLL_NAME.match(name):
            raise _CErr("ValidationException", f"1 validation error detected: Value '{name}' at 'name' failed to satisfy constraint: "
                        "Member must satisfy regular expression pattern: [a-z][a-z0-9-]+ and have length 3..32", 400)
        if any(c["name"] == name for c in colls.values()):
            raise _CErr("ConflictException", f"Collection with name {name} already exists", 409)
        if not _policy_matches(st, "encryption", name):
            raise _CErr("ValidationException", "No matching security policy of encryption type found for collection name: " + name +
                        ". Please create security policy of encryption type for this collection.", 400)
        cid = _rid(10)
        c = {"id": cid, "name": name, "status": "ACTIVE", "type": p.get("type", "SEARCH"), "description": p.get("description", ""),
             "arn": f"arn:aws:aoss:{_REGION}:{_ACCT}:collection/{cid}", "kmsKeyArn": "auto", "standbyReplicas": p.get("standbyReplicas", "ENABLED"),
             "createdDate": int(_epoch() * 1000), "lastModifiedDate": int(_epoch() * 1000),
             "collectionEndpoint": f"https://{cid}.{_REGION}.aoss.amazonaws.com", "dashboardEndpoint": f"https://{cid}.{_REGION}.aoss.amazonaws.com/_dashboards"}
        colls[cid] = c
        if p.get("tags"):
            st["tags"][c["arn"]] = list(p["tags"])
        return {"createCollectionDetail": {k: c[k] for k in ("id", "name", "status", "type", "description", "arn", "kmsKeyArn", "standbyReplicas",
                                                             "createdDate", "lastModifiedDate")}}
    if op == "BatchGetCollection":
        found = [c for c in _coll_by(st, p) if c]
        return {"collectionDetails": [_coll_detail(c) for c in found], "collectionErrorDetails": []}
    if op == "ListCollections":
        flt = (p.get("collectionFilters") or {}).get("name")
        return {"collectionSummaries": [{"id": c["id"], "name": c["name"], "arn": c["arn"], "status": c["status"]} for c in colls.values()
                                        if not flt or c["name"] == flt]}
    if op == "UpdateCollection":
        c = colls.get(p.get("id"))
        if not c:
            raise _CErr("ResourceNotFoundException", f"Collection {p.get('id')} not found", 404)
        if "description" in p:
            c["description"] = p["description"]
        c["lastModifiedDate"] = int(_epoch() * 1000)
        return {"updateCollectionDetail": {k: c[k] for k in ("id", "name", "status", "type", "description", "arn", "createdDate", "lastModifiedDate")}}
    if op == "DeleteCollection":
        c = colls.pop(p.get("id"), None)
        if not c:
            raise _CErr("ResourceNotFoundException", f"Collection {p.get('id')} not found", 404)
        return {"deleteCollectionDetail": {"id": c["id"], "name": c["name"], "status": "DELETING"}}
    if op in ("CreateSecurityPolicy", "CreateAccessPolicy"):
        kind = "security" if "Security" in op else "access"
        name, ptype = p.get("name") or "", p.get("type") or ""
        if not name or not p.get("policy"):
            raise _CErr("ValidationException", "name and policy are required", 400)
        if ptype not in (("encryption", "network") if kind == "security" else ("data",)):
            raise _CErr("ValidationException", f"Invalid policy type {ptype}", 400)
        if f"{kind}/{ptype}/{name}" in st["policies"]:
            raise _CErr("ConflictException", f"Policy with name {name} and type {ptype} already exists", 409)
        try:
            json.loads(p["policy"])
        except (TypeError, ValueError):
            raise _CErr("ValidationException", "policy must be valid JSON", 400)
        pol = {"_kind": kind, "type": ptype, "name": name, "policyVersion": _rid(16), "description": p.get("description", ""), "policy": p["policy"],
               "createdDate": int(_epoch() * 1000), "lastModifiedDate": int(_epoch() * 1000)}
        st["policies"][f"{kind}/{ptype}/{name}"] = pol
        return {("securityPolicyDetail" if kind == "security" else "accessPolicyDetail"): {k: v for k, v in pol.items() if k != "_kind"}}
    if op in ("GetSecurityPolicy", "GetAccessPolicy"):
        kind = "security" if "Security" in op else "access"
        pol = st["policies"].get(f"{kind}/{p.get('type')}/{p.get('name')}")
        if not pol:
            raise _CErr("ResourceNotFoundException", f"Policy {p.get('name')} of type {p.get('type')} not found", 404)
        return {("securityPolicyDetail" if kind == "security" else "accessPolicyDetail"): {k: v for k, v in pol.items() if k != "_kind"}}
    if op in ("ListSecurityPolicies", "ListAccessPolicies"):
        kind = "security" if "Security" in op else "access"
        items = [{k: v for k, v in pol.items() if k not in ("_kind", "policy")} for pol in st["policies"].values()
                 if pol["_kind"] == kind and pol["type"] == p.get("type")]
        return {("securityPolicySummaries" if kind == "security" else "accessPolicySummaries"): items}
    if op in ("UpdateSecurityPolicy", "UpdateAccessPolicy"):
        kind = "security" if "Security" in op else "access"
        pol = st["policies"].get(f"{kind}/{p.get('type')}/{p.get('name')}")
        if not pol:
            raise _CErr("ResourceNotFoundException", f"Policy {p.get('name')} of type {p.get('type')} not found", 404)
        pol.update(policy=p.get("policy", pol["policy"]), description=p.get("description", pol["description"]), policyVersion=_rid(16),
                   lastModifiedDate=int(_epoch() * 1000))
        return {("securityPolicyDetail" if kind == "security" else "accessPolicyDetail"): {k: v for k, v in pol.items() if k != "_kind"}}
    if op in ("DeleteSecurityPolicy", "DeleteAccessPolicy"):
        kind = "security" if "Security" in op else "access"
        if not st["policies"].pop(f"{kind}/{p.get('type')}/{p.get('name')}", None):
            raise _CErr("ResourceNotFoundException", f"Policy {p.get('name')} of type {p.get('type')} not found", 404)
        return {}
    if op == "TagResource":
        cur = {t["key"]: t["value"] for t in st["tags"].get(p.get("resourceArn"), [])}
        cur.update({t["key"]: t["value"] for t in p.get("tags", [])})
        st["tags"][p["resourceArn"]] = [{"key": k, "value": v} for k, v in cur.items()]
        return {}
    if op == "UntagResource":
        st["tags"][p["resourceArn"]] = [t for t in st["tags"].get(p["resourceArn"], []) if t["key"] not in p.get("tagKeys", [])]
        return {}
    if op == "ListTagsForResource":
        return {"tags": st["tags"].get(p.get("resourceArn"), [])}
    if op == "GetAccountSettings":
        return {"accountSettings": {"capacityLimits": {"maxIndexingCapacityInOCU": 10, "maxSearchCapacityInOCU": 10}}}
    raise _CErr("UnknownOperationException", f"Unsupported OpenSearch Serverless operation: {op}", 400)


# ══════════════════════════════ data plane ══════════════════════════════
def _oerr(status, etype, reason):
    return _resp(status, {"error": {"root_cause": [{"type": etype, "reason": reason}], "type": etype, "reason": reason}, "status": status})


class _DErr(Exception):
    def __init__(self, status, etype, reason):
        self.status, self.etype, self.reason = status, etype, reason


def _get(src, field):
    cur = src
    for part in field.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _vals(v):
    return v if isinstance(v, list) else [v]


class _Ctx:
    """Per-search context: the doc list, lazy per-field BM25 indexes, kNN precomputation."""

    def __init__(self, idx):
        self.docs = idx["docs"]
        self.mapping = (idx.get("mappings") or {}).get("properties") or {}
        self.ids = list(self.docs.keys())
        self.srcs = [self.docs[i] for i in self.ids]
        self._ti, self._cache = {}, {}

    def text_of(self, field):
        out = []
        for s in self.srcs:
            v = _get(s, field)
            out.append(" ".join(str(x) for x in _vals(v)) if v is not None else "")
        return out

    def lex(self, field, query):
        key = (field, query)
        if key not in self._cache:
            self._cache[key] = kc.text_index(self.text_of(field)).search(query)
        return self._cache[key]

    def space(self, field):
        m = (self.mapping.get(field) or {}).get("method") or {}
        return m.get("space_type", "cosinesimil")


def _kscore(space, q, v):
    if len(q) != len(v):
        return None
    if space == "l2":
        return 1.0 / (1.0 + sum((a - b) ** 2 for a, b in zip(q, v)))
    if space == "innerproduct":
        ip = sum(a * b for a, b in zip(q, v))
        return ip + 1 if ip >= 0 else 1.0 / (1 - ip)
    return (1.0 + llm.cosine(q, v)) / 2.0                       # cosinesimil -> OpenSearch score in [0, 1]


def _ev(q, i, cx):
    """Score of doc position ``i`` under query ``q`` (a float > 0) or None when it does not match."""
    if not isinstance(q, dict) or len(q) != 1:
        raise _DErr(400, "parsing_exception", "query malformed, must have exactly one query type")
    (kind, body), = q.items()
    src = cx.srcs[i]
    if kind == "match_all":
        return float(body.get("boost", 1.0)) if isinstance(body, dict) else 1.0
    if kind == "match_none":
        return None
    if kind in ("match", "match_phrase", "match_phrase_prefix"):
        (field, spec), = body.items()
        text = spec.get("query") if isinstance(spec, dict) else spec
        op = (spec.get("operator", "or") if isinstance(spec, dict) else "or").lower()
        sc = cx.lex(field, str(text)).get(i)
        if sc is None:
            return None
        toks = kc.tokens(str(_get(src, field) or ""))
        qt = kc.tokens(str(text))
        if kind == "match" and op == "and" and not all(t in toks for t in qt):
            return None
        if kind != "match" and " ".join(qt) not in " ".join(toks):
            return None
        return sc
    if kind in ("multi_match", "query_string", "simple_query_string"):
        text = body.get("query", "")
        fields = [f.split("^")[0] for f in (body.get("fields") or [])] or [k for k, v in src.items() if isinstance(v, str)]
        best = [cx.lex(f, str(text)).get(i) for f in fields]
        best = [b for b in best if b]
        return max(best) if best else None
    if kind in ("term", "terms", "prefix", "wildcard", "range", "exists", "ids"):
        if kind == "ids":
            return 1.0 if cx.ids[i] in [str(x) for x in body.get("values", [])] else None
        if kind == "exists":
            return 1.0 if _get(src, body["field"]) is not None else None
        field, spec = next((k, v) for k, v in body.items() if k not in ("boost", "_name"))
        field = field[:-8] if field.endswith(".keyword") else field
        have = _vals(_get(src, field))
        if kind == "terms":
            return 1.0 if any(h in spec for h in have if h is not None) else None
        if kind == "term":
            want = spec.get("value") if isinstance(spec, dict) else spec
            ci = isinstance(spec, dict) and spec.get("case_insensitive")
            ok = any((str(h).lower() == str(want).lower()) if ci else (h == want or str(h) == str(want)) for h in have if h is not None)
            return 1.0 if ok else None
        if kind == "prefix":
            want = spec.get("value") if isinstance(spec, dict) else spec
            return 1.0 if any(str(h).startswith(str(want)) for h in have if h is not None) else None
        if kind == "wildcard":
            want = spec.get("value") if isinstance(spec, dict) else spec
            return 1.0 if any(fnmatch.fnmatchcase(str(h), str(want)) for h in have if h is not None) else None
        for h in have:                                                    # range
            if h is None:
                continue
            try:
                if ("gt" in spec and not h > spec["gt"]) or ("gte" in spec and not h >= spec["gte"]) \
                        or ("lt" in spec and not h < spec["lt"]) or ("lte" in spec and not h <= spec["lte"]):
                    continue
            except TypeError:
                continue
            return 1.0
        return None
    if kind == "bool":
        total, matched_should = 0.0, 0
        for c in _vals(body.get("must", [])) if body.get("must") else []:
            s = _ev(c, i, cx)
            if s is None:
                return None
            total += s
        for c in _vals(body.get("filter", [])) if body.get("filter") else []:
            if _ev(c, i, cx) is None:
                return None
        for c in _vals(body.get("must_not", [])) if body.get("must_not") else []:
            if _ev(c, i, cx) is not None:
                return None
        shoulds = _vals(body.get("should", [])) if body.get("should") else []
        for c in shoulds:
            s = _ev(c, i, cx)
            if s is not None:
                total += s
                matched_should += 1
        msm = body.get("minimum_should_match")
        need = int(msm) if isinstance(msm, (int, str)) and str(msm).isdigit() else (1 if shoulds and not (body.get("must") or body.get("filter")) else 0)
        if matched_should < need:
            return None
        return total or 1.0
    if kind == "knn":
        key = id(body)
        if key not in cx._cache:
            (field, spec), = body.items()
            vec = spec.get("vector")
            if not isinstance(vec, list):
                raise _DErr(400, "parsing_exception", "[knn] requires a 'vector'")
            k = int(spec.get("k", 10))
            flt = spec.get("filter")
            sp = cx.space(field)
            cand = []
            for j, s in enumerate(cx.srcs):
                v = _get(s, field)
                if not isinstance(v, list):
                    continue
                if flt is not None and _ev(flt, j, cx) is None:
                    continue
                sc = _kscore(sp, vec, v)
                if sc is not None and sc >= float(spec.get("min_score", 0) or 0):
                    cand.append((sc, j))
            cand.sort(reverse=True)
            cx._cache[key] = {j: sc for sc, j in cand[:k]}
        return cx._cache[key].get(i)
    if kind == "hybrid":
        subs = body.get("queries") or []
        key = id(body)
        if key not in cx._cache:
            lists = []
            for sq in subs:
                raw = {j: _ev(sq, j, cx) for j in range(len(cx.srcs))}
                raw = {j: s for j, s in raw.items() if s is not None}
                if raw:
                    lo, hi = min(raw.values()), max(raw.values())
                    raw = {j: ((s - lo) / (hi - lo) if hi > lo else 1.0) for j, s in raw.items()}
                lists.append(raw)
            cx._cache[key] = {j: sum(l.get(j, 0.0) for l in lists) / max(len(lists), 1) for j in set().union(*[set(l) for l in lists]) if True} if lists else {}
        s = cx._cache[key].get(i)
        return None if s is None else max(s, 1e-6)
    raise _DErr(400, "parsing_exception", f"no [query] registered for [{kind}]")


def _project(src, spec):
    if spec is False:
        return None
    if spec is True or spec is None:
        return src
    inc = spec if isinstance(spec, list) else (spec.get("includes") or spec.get("include") or [] if isinstance(spec, dict) else [spec])
    exc = spec.get("excludes", []) if isinstance(spec, dict) else []
    out = {k: v for k, v in src.items() if (not inc or any(fnmatch.fnmatch(k, i) for i in inc)) and not any(fnmatch.fnmatch(k, e) for e in exc)}
    return out


def _search(idx_names, st, body, query):
    t0 = time.time()
    body = body or {}
    size = int(body.get("size", (query or {}).get("size", 10)))
    frm = int(body.get("from", (query or {}).get("from", 0)))
    hits = []
    for name in idx_names:
        idx = st["indices"].get(name)
        if idx is None:
            raise _DErr(404, "index_not_found_exception", f"no such index [{name}]")
        cx = _Ctx(idx)
        q = body.get("query") or {"match_all": {}}
        for i in range(len(cx.srcs)):
            s = _ev(q, i, cx)
            if s is None:
                continue
            pf = body.get("post_filter")
            if pf and _ev(pf, i, cx) is None:
                continue
            if body.get("min_score") is not None and s < float(body["min_score"]):
                continue
            hits.append((s, name, cx.ids[i], cx.srcs[i]))
    sort = body.get("sort")
    if sort and sort != "_score" and sort != ["_score"]:
        for spec in reversed(_vals(sort)):
            field, order = (list(spec.items())[0] if isinstance(spec, dict) else (spec, "asc"))
            order = order.get("order", "asc") if isinstance(order, dict) else order
            if field == "_score":
                hits.sort(key=lambda h: h[0], reverse=(order == "desc"))
            else:
                hits.sort(key=lambda h: (_get(h[3], field) is None, _get(h[3], field)), reverse=(order == "desc"))
    else:
        hits.sort(key=lambda h: -h[0])
    total = len(hits)
    page = hits[frm:frm + size]
    spec = body.get("_source", True)
    out = []
    for s, n, i, src in page:
        h = {"_index": n, "_id": i, "_score": round(s, 6)}
        pr = _project(src, spec)
        if pr is not None:
            h["_source"] = pr
        out.append(h)
    return {"took": int((time.time() - t0) * 1000), "timed_out": False, "_shards": {"total": len(idx_names), "successful": len(idx_names), "skipped": 0, "failed": 0},
            "hits": {"total": {"value": total, "relation": "eq"}, "max_score": round(hits[0][0], 6) if hits else None, "hits": out}}


def _body_json(raw):
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except ValueError:
        raise _DErr(400, "parse_exception", "Failed to parse content to map")
    if not isinstance(v, dict):
        raise _DErr(400, "parse_exception", "request body must be an object")
    return v


def _index(st, name, create=True):
    idx = st["indices"].get(name)
    if idx is None:
        if not create:
            raise _DErr(404, "index_not_found_exception", f"no such index [{name}]")
        idx = st["indices"][name] = {"settings": {}, "mappings": {}, "docs": {}, "versions": {}, "created": int(_epoch() * 1000)}
    return idx


def _write(idx, did, src, op="index", name=""):
    exists = did in idx["docs"]
    if op == "create" and exists:
        raise _DErr(409, "version_conflict_engine_exception", f"[{did}]: version conflict, document already exists")
    idx["docs"][did] = src
    idx["versions"][did] = idx["versions"].get(did, 0) + 1
    return {"_index": name, "_id": did, "_version": idx["versions"][did], "result": "updated" if exists else "created",
            "_shards": {"total": 2, "successful": 1, "failed": 0}, "_seq_no": idx["versions"][did] - 1, "_primary_term": 1}


def index_docs(store, index, docs, mappings=None):
    """Programmatic write path used by Bedrock KB ingestion: docs = [(id, source_dict)]."""
    st = _state(store)
    idx = _index(st, index)
    if mappings and not idx["mappings"]:
        idx["mappings"] = mappings
    for did, src in docs:
        _write(idx, did, src, "index", index)


def drop_docs(store, index, prefix):
    idx = _state(store)["indices"].get(index)
    if idx:
        for d in [d for d in idx["docs"] if d.startswith(prefix)]:
            idx["docs"].pop(d, None)


def data_dispatch(store, method, path, query, headers, body):
    st = _state(store)
    method = method.upper()
    path = path.split("?", 1)[0]
    segs = [s for s in re.sub(r"/{2,}", "/", path).strip("/").split("/") if s]
    q = query or {}
    try:
        out = _data(st, method, segs, q, body)
    except _DErr as e:
        return _oerr(e.status, e.etype, e.reason)
    if method != "GET" and method != "HEAD":
        _persist(store)
    return out


def _data(st, method, segs, q, raw):
    if not segs:
        return _resp(200, {"name": "vyomi-opensearch", "cluster_name": f"{_ACCT}:vyomi", "cluster_uuid": "vyomi0000000000000000",
                           "version": {"number": "2.17.0", "distribution": "opensearch", "build_type": "tar", "lucene_version": "9.11.1"},
                           "tagline": "The OpenSearch Project: https://opensearch.org/"})
    head = segs[0]
    if head == "_cluster" and segs[1:2] == ["health"]:
        return _resp(200, {"cluster_name": "vyomi", "status": "green", "timed_out": False, "number_of_nodes": 1, "number_of_data_nodes": 1,
                           "active_primary_shards": len(st["indices"]), "active_shards": len(st["indices"]), "unassigned_shards": 0})
    if head == "_cat" and segs[1:2] == ["indices"]:
        rows = [{"health": "green", "status": "open", "index": n, "docs.count": str(len(i["docs"])), "pri": "1", "rep": "0"} for n, i in st["indices"].items()]
        return _resp(200, rows)
    if head == "_bulk":
        return _bulk(st, None, raw)
    if head == "_search":
        return _resp(200, _search(list(st["indices"]), st, _body_json(raw), q))
    if head == "_aliases" or head == "_nodes" or head == "_cluster":
        return _resp(200, {})
    # index-scoped
    names = [n for n in head.split(",") if n]
    name = names[0]
    rest = segs[1:]
    if not rest:
        if method == "PUT":
            if name in st["indices"]:
                raise _DErr(400, "resource_already_exists_exception", f"index [{name}/{_rid(8)}] already exists")
            b = _body_json(raw)
            idx = _index(st, name)
            idx["settings"], idx["mappings"] = b.get("settings") or {}, b.get("mappings") or {}
            return _resp(200, {"acknowledged": True, "shards_acknowledged": True, "index": name})
        if method == "HEAD":
            return {"status": 200 if name in st["indices"] else 404, "headers": _JSON, "body": b""}
        if method == "GET":
            idx = _index(st, name, False)
            return _resp(200, {name: {"aliases": {}, "mappings": idx["mappings"], "settings": {"index": {"number_of_shards": "1", "number_of_replicas": "0",
                                                                                                       **(idx["settings"].get("index") or idx["settings"])}}}})
        if method == "DELETE":
            for n in names:
                if st["indices"].pop(n, None) is None:
                    raise _DErr(404, "index_not_found_exception", f"no such index [{n}]")
            return _resp(200, {"acknowledged": True})
    r0 = rest[0]
    if r0 == "_mapping":
        idx = _index(st, name, False)
        if method == "GET":
            return _resp(200, {name: {"mappings": idx["mappings"]}})
        b = _body_json(raw)
        props = idx["mappings"].setdefault("properties", {})
        props.update(b.get("properties") or {})
        return _resp(200, {"acknowledged": True})
    if r0 == "_settings":
        idx = _index(st, name, False)
        if method == "GET":
            return _resp(200, {name: {"settings": idx["settings"]}})
        idx["settings"] = {**idx["settings"], **_body_json(raw)}
        return _resp(200, {"acknowledged": True})
    if r0 == "_bulk":
        return _bulk(st, name, raw)
    if r0 in ("_refresh", "_flush", "_forcemerge"):
        _index(st, name, False)
        return _resp(200, {"_shards": {"total": 1, "successful": 1, "failed": 0}})
    if r0 == "_search":
        return _resp(200, _search(names, st, _body_json(raw), q))
    if r0 == "_count":
        b = _body_json(raw)
        r = _search(names, st, {**b, "size": 0}, q)
        return _resp(200, {"count": r["hits"]["total"]["value"], "_shards": r["_shards"]})
    if r0 == "_delete_by_query":
        idx = _index(st, name, False)
        cx = _Ctx(idx)
        q_ = _body_json(raw).get("query") or {"match_all": {}}
        kill = [cx.ids[i] for i in range(len(cx.srcs)) if _ev(q_, i, cx) is not None]
        for d in kill:
            idx["docs"].pop(d, None)
        return _resp(200, {"took": 1, "timed_out": False, "deleted": len(kill), "total": len(kill), "failures": []})
    if r0 in ("_doc", "_create", "_update"):
        idx = _index(st, name, method in ("PUT", "POST"))
        did = rest[1] if len(rest) > 1 else None
        if method in ("PUT", "POST") and r0 != "_update":
            src = _body_json(raw)
            if did is None:
                did = _rid(20)
            op = "create" if r0 == "_create" or q.get("op_type") == "create" else "index"
            res = _write(idx, did, src, op, name)
            return _resp(201 if res["result"] == "created" else 200, res)
        if r0 == "_update" and method == "POST":
            if did not in idx["docs"]:
                raise _DErr(404, "document_missing_exception", f"[{did}]: document missing")
            b = _body_json(raw)
            idx["docs"][did] = {**idx["docs"][did], **(b.get("doc") or {})}
            idx["versions"][did] += 1
            return _resp(200, {"_index": name, "_id": did, "_version": idx["versions"][did], "result": "updated"})
        if method == "GET" and did:
            if did not in idx["docs"]:
                return _resp(404, {"_index": name, "_id": did, "found": False})
            return _resp(200, {"_index": name, "_id": did, "_version": idx["versions"][did], "_seq_no": 0, "_primary_term": 1, "found": True,
                               "_source": idx["docs"][did]})
        if method == "HEAD" and did:
            return {"status": 200 if did in idx["docs"] else 404, "headers": _JSON, "body": b""}
        if method == "DELETE" and did:
            if did not in idx["docs"]:
                return _resp(404, {"_index": name, "_id": did, "result": "not_found"})
            del idx["docs"][did]
            return _resp(200, {"_index": name, "_id": did, "result": "deleted", "_version": idx["versions"].get(did, 1) + 1})
    raise _DErr(400, "illegal_argument_exception", f"unsupported request: {method} /{'/'.join(segs)}")


def _bulk(st, default_index, raw):
    lines = [l for l in (raw or b"").decode("utf-8").splitlines() if l.strip()]
    items, errors, i = [], False, 0
    while i < len(lines):
        try:
            act = json.loads(lines[i])
            (op, meta), = act.items()
        except (ValueError, TypeError):
            raise _DErr(400, "illegal_argument_exception", "Malformed action/metadata line")
        i += 1
        name = meta.get("_index") or default_index
        did = meta.get("_id")
        try:
            if not name:
                raise _DErr(400, "action_request_validation_exception", "index is missing")
            if op == "delete":
                idx = _index(st, name, False)
                ok = idx["docs"].pop(did, None) is not None
                res = {"_index": name, "_id": did, "result": "deleted" if ok else "not_found", "status": 200 if ok else 404}
            else:
                src = json.loads(lines[i])
                i += 1
                idx = _index(st, name)
                if op == "update":
                    if did not in idx["docs"]:
                        raise _DErr(404, "document_missing_exception", f"[{did}]: document missing")
                    idx["docs"][did] = {**idx["docs"][did], **(src.get("doc") or {})}
                    res = {"_index": name, "_id": did, "result": "updated", "status": 200}
                else:
                    did = did or _rid(20)
                    res = _write(idx, did, src, "create" if op == "create" else "index", name)
                    res["status"] = 201 if res["result"] == "created" else 200
        except _DErr as e:
            errors = True
            res = {"_index": name, "_id": did, "status": e.status, "error": {"type": e.etype, "reason": e.reason}}
        items.append({op: res})
    return _resp(200, {"took": 1, "errors": errors, "items": items})


# ══════════════════════════════ routing helpers ══════════════════════════════
def is_control_path(path: str) -> bool:
    return path.startswith("/2021-01-01/")


_DATA_HINT = re.compile(r"(^|/)_(search|bulk|doc|create|update|mapping|settings|count|refresh|cat|cluster|delete_by_query)(/|$)")


def looks_like_data_plane(path: str) -> bool:
    return bool(_DATA_HINT.search(path.split("?", 1)[0]))
