# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""API Gateway API v1 (apigateway.googleapis.com) — substrate-independent, stdlib only.

`projects/{p}/locations/global/apis[/{api}/configs]` and `projects/{p}/locations/{region}/gateways`, the same wire the
google-cloud-api-gateway SDKs and `gcloud api-gateway` speak.

  * apis        create / get / list / patch / delete (delete refused while the API still has configs)
  * api configs create validates the OpenAPI 2.0 document for real (swagger "2.0", info.title, paths, an operationId and an
                https x-google-backend address per operation, duplicate operationIds); the routes it would serve are derived from it.
                `openapiDocuments[].document.contents` is base64 like the real API (raw text is accepted too).
                Delete is refused while a gateway serves the config.
  * gateways    create / get / list (`locations/-` = every region) / patch (apiConfig, displayName, labels) / delete; the gateway gets a
                `{id}-{hash}.{region code}.gateway.dev` default hostname and must point at an existing API config.
  * operations  every create/update/delete is a long-running operation that is already done (`done: true`); polling
                `.../operations/apigw-…` answers from the recorded operation.

State lives in `store.ext["apigw_*"]` of the monitoring store (persisted with it), same convention as the Eventarc core.
Honest limit: no traffic is proxied — a gateway has a hostname and a routing table, it does not forward requests to the backend.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

try:
    from core.gcp_firestore_core import FirestoreResponse
except ImportError:  # pragma: no cover - Pyodide flat layout
    from gcp_firestore_core import FirestoreResponse  # type: ignore

_ID = re.compile(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")
_REGION_CODE = {"us-central1": "uc", "us-east1": "ue", "us-east4": "ue", "us-west2": "uw", "us-west3": "uw", "us-west4": "uw",
                "europe-west1": "ew", "europe-west2": "ew", "europe-west4": "ew", "europe-west6": "ew", "europe-west12": "ew",
                "asia-east1": "de", "asia-northeast1": "an", "asia-northeast2": "an", "asia-southeast1": "as", "australia-southeast1": "ts"}
LOCATIONS = sorted(_REGION_CODE)
_METHODS = ("get", "put", "post", "delete", "patch", "options", "head")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status: int, gs: str, msg: str) -> FirestoreResponse:
    return FirestoreResponse(status, {"content-type": "application/json"},
                             json.dumps({"error": {"code": status, "message": msg, "status": gs}}).encode())


def _json(o) -> FirestoreResponse:
    return FirestoreResponse(200, {"content-type": "application/json"}, json.dumps(o).encode())


class _E(Exception):
    def __init__(self, status, gs, msg):
        self.r = _err(status, gs, msg)


def _coll(store, name: str) -> dict:
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("apigw_" + name, {})


def _view(r: dict, full: bool = False) -> dict:
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    if not full:
        out.pop("openapiDocuments", None)
    return out


def _lro(project, location, verb, response=None, target=None):
    oid = "apigw-" + uuid.uuid4().hex[:16]
    now = _now()
    return {"name": "projects/%s/locations/%s/operations/%s" % (project, location, oid),
            "metadata": {"@type": "type.googleapis.com/google.cloud.apigateway.v1.OperationMetadata", "createTime": now, "endTime": now,
                         "target": target or "", "verb": verb, "requestedCancellation": False, "apiVersion": "v1"},
            "done": True, **({"response": {"@type": "type.googleapis.com/google.cloud.apigateway.v1.Resource", **(response or {})}} if verb != "delete" else
                             {"response": {"@type": "type.googleapis.com/google.protobuf.Empty"}})}


def _check_id(kind: str, rid: str) -> None:
    if not _ID.match(rid or ""):
        raise _E(400, "INVALID_ARGUMENT", "Invalid %s ID '%s': 1-63 characters of lowercase letters, digits and hyphens, starting with a letter." % (kind, rid))


# ── OpenAPI 2.0 (JSON, or the block-style YAML subset API specs use) ────────────────────────
def _scalar(s: str):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if re.match(r"^-?\d+$", s):
        return int(s)
    return s


def parse_openapi(text: str) -> dict:
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            return d
    except ValueError:
        pass
    lines = [ln.rstrip() for ln in str(text or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    root: dict = {}
    stack = [(-1, root)]
    for i, ln in enumerate(lines):
        ind, body = len(ln) - len(ln.lstrip()), ln.strip()
        while stack and stack[-1][0] >= ind:
            stack.pop()
        parent = stack[-1][1]
        if body.startswith("- "):
            item = body[2:]
            if not isinstance(parent, list):
                raise _E(400, "INVALID_ARGUMENT", "Cannot parse the OpenAPI document: unexpected list item at line %d." % (i + 1))
            if ":" in item and not item.startswith(("'", '"')):
                k, _, v = item.partition(":")
                d = {k.strip(): _scalar(v) if v.strip() else {}}
                parent.append(d)
                stack.append((ind, d))
            else:
                parent.append(_scalar(item))
            continue
        if ":" not in body or not isinstance(parent, dict):
            raise _E(400, "INVALID_ARGUMENT", "Cannot parse the OpenAPI document at line %d: '%s'." % (i + 1, body))
        k, _, v = body.partition(":")
        k = k.strip().strip("'\"")
        if v.strip():
            parent[k] = _scalar(v)
        else:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            child = [] if nxt.strip().startswith("- ") and len(nxt) - len(nxt.lstrip()) >= ind else {}
            parent[k] = child
            stack.append((ind, child))
    return root


def _validate_security_quota(doc: dict) -> None:
    """Validate securityDefinitions / security / x-google-management (metrics, quota) / x-google-quota."""
    def bad(msg):
        raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: " + msg)
    defs = doc.get("securityDefinitions") or {}
    if not isinstance(defs, dict):
        bad("'securityDefinitions' must be an object.")
    for name, d in defs.items():
        if not isinstance(d, dict) or d.get("type") not in ("apiKey", "oauth2", "basic"):
            bad("security definition '%s' needs a type of apiKey, oauth2 or basic." % name)
        if d["type"] == "apiKey":
            if not d.get("name"):
                bad("apiKey security definition '%s' requires 'name'." % name)
            if d.get("in") not in ("query", "header"):
                bad("apiKey security definition '%s' requires 'in' of query or header." % name)
        if d["type"] == "oauth2":
            if not d.get("x-google-issuer"):
                bad("oauth2 security definition '%s' requires 'x-google-issuer'." % name)
            j = d.get("x-google-jwks_uri")
            if j is not None and not str(j).startswith("https://"):
                bad("'x-google-jwks_uri' of '%s' must be an https:// URL." % name)
    def check_sec(sec, where):
        if sec is None:
            return
        if not isinstance(sec, list) or not all(isinstance(r, dict) for r in sec):
            bad("'security' %s must be a list of requirement objects." % where)
        for req in sec:
            for k in req:
                if k not in defs:
                    bad("'security' %s references security definition '%s', which is not defined." % (where, k))
    check_sec(doc.get("security"), "at the top level")
    mgmt = doc.get("x-google-management") or {}
    if not isinstance(mgmt, dict):
        bad("'x-google-management' must be an object.")
    metrics = {}
    for m in mgmt.get("metrics") or []:
        if not isinstance(m, dict) or not m.get("name"):
            bad("every x-google-management metric needs a 'name'.")
        if m.get("valueType", "INT64") != "INT64" or m.get("metricKind", "DELTA") != "DELTA":
            bad("metric '%s' must have valueType INT64 and metricKind DELTA." % m["name"])
        metrics[m["name"]] = m
    quota = mgmt.get("quota") or {}
    if not isinstance(quota, dict):
        bad("'x-google-management.quota' must be an object.")
    for lim in quota.get("limits") or []:
        if not isinstance(lim, dict) or not lim.get("name"):
            bad("every quota limit needs a 'name'.")
        if lim.get("metric") not in metrics:
            bad("quota limit '%s' references metric '%s', which is not defined." % (lim["name"], lim.get("metric")))
        if not lim.get("unit"):
            bad("quota limit '%s' requires 'unit' (e.g. 1/min/{project})." % lim["name"])
        vals = lim.get("values")
        if not isinstance(vals, dict) or not vals or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in vals.values()):
            bad("quota limit '%s' requires 'values' with non-negative integers (e.g. STANDARD: 1000)." % lim["name"])
    for path, ops in (doc.get("paths") or {}).items():
        for method, op in (ops or {}).items():
            if str(method).lower() not in _METHODS or not isinstance(op, dict):
                continue
            where = "on %s %s" % (str(method).upper(), path)
            check_sec(op.get("security"), where)
            costs = (op.get("x-google-quota") or {}).get("metricCosts") or {}
            if not isinstance(costs, dict):
                bad("'x-google-quota.metricCosts' %s must be an object." % where)
            for mk, cv in costs.items():
                if mk not in metrics:
                    bad("'x-google-quota' %s references metric '%s', which is not defined." % (where, mk))
                if not isinstance(cv, int) or isinstance(cv, bool) or cv < 0:
                    bad("metric cost for '%s' %s must be a non-negative integer." % (mk, where))


def openapi_routes(doc: dict) -> list:
    if str(doc.get("swagger") or "") != "2.0":
        raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: API Gateway requires an OpenAPI 2.0 document ('swagger: \"2.0\"').")
    if not (doc.get("info") or {}).get("title"):
        raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: 'info.title' is required.")
    paths = doc.get("paths") or {}
    if not isinstance(paths, dict) or not paths:
        raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: the document defines no paths.")
    _validate_security_quota(doc)
    default_backend = (doc.get("x-google-backend") or {}).get("address", "")
    out, seen = [], set()
    for path, ops in paths.items():
        if not str(path).startswith("/"):
            raise _E(400, "INVALID_ARGUMENT", "Path '%s' must start with '/'." % path)
        for method, op in (ops or {}).items():
            if str(method).lower() not in _METHODS:
                continue
            op = op or {}
            oid = op.get("operationId")
            if not oid:
                raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: %s %s has no operationId." % (str(method).upper(), path))
            if oid in seen:
                raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: duplicate operationId '%s'." % oid)
            seen.add(oid)
            backend = (op.get("x-google-backend") or {}).get("address") or default_backend
            if not backend or not str(backend).startswith("https://"):
                raise _E(400, "INVALID_ARGUMENT", "%s %s needs an x-google-backend address (an https:// URL)." % (str(method).upper(), path))
            out.append({"method": str(method).upper(), "path": path, "operationId": oid, "backend": backend})
    if not out:
        raise _E(400, "INVALID_ARGUMENT", "Cannot convert to service config: no operations under paths.")
    return out


def describe_policy(doc: dict) -> dict:
    """What the console shows for a config: the document's security schemes, quota limits and which operations they apply to (read-only
    summary parsed from the stored, already-validated document)."""
    mg = doc.get("x-google-management") or {}
    schemes = []
    for n, d in (doc.get("securityDefinitions") or {}).items():
        schemes.append({"name": n, "type": d.get("type"), "in": d.get("in"), "keyName": d.get("name"), "issuer": d.get("x-google-issuer"),
                        "jwksUri": d.get("x-google-jwks_uri"), "audiences": d.get("x-google-audiences")})
    ops = []
    for path, pops in (doc.get("paths") or {}).items():
        for method, op in (pops or {}).items():
            if str(method).lower() in _METHODS and isinstance(op, dict):
                sec = op["security"] if "security" in op else doc.get("security")
                ops.append({"operationId": op.get("operationId"), "method": str(method).upper(), "path": path,
                            "security": [list(r) for r in (sec or [])], "metricCosts": (op.get("x-google-quota") or {}).get("metricCosts") or {}})
    return {"securityDefinitions": schemes, "security": [list(r) for r in (doc.get("security") or [])],
            "metrics": [{"name": m.get("name"), "displayName": m.get("displayName")} for m in mg.get("metrics") or []],
            "quotaLimits": [{"name": l.get("name"), "metric": l.get("metric"), "unit": l.get("unit"), "values": l.get("values")}
                            for l in (mg.get("quota") or {}).get("limits") or []], "operations": ops}


def _decode(contents: str) -> str:
    try:
        raw = base64.b64decode(contents, validate=True).decode("utf-8")
        return raw
    except Exception:
        return contents   # raw text instead of base64


# ── paths ──────────────────────────────────────────────────────────────────────────────────
_ROOT = re.compile(r"^/v1/projects/([^/]+)/locations/([^/]+)/(apis|gateways|operations)(?:/([^/:]+))?(?:/(configs)(?:/([^/:]+))?)?(?::(\w+))?$")


def is_apigateway_path(path: str) -> bool:
    p = path.split("?", 1)[0]
    m = _ROOT.match(p)
    if not m:
        return False
    _proj, _loc, coll, rid = m.group(1), m.group(2), m.group(3), m.group(4)
    if coll == "operations":
        return bool(rid and rid.startswith("apigw-"))
    if coll == "apis":
        return _loc in ("global", "-")
    return True


def dispatch(store, method: str, path: str, query=None, headers=None, body: bytes = b"") -> FirestoreResponse:
    query = query or {}
    method = method.upper()
    m = _ROOT.match(path.split("?", 1)[0])
    if not m:
        return _err(404, "NOT_FOUND", "Unknown path: " + path)
    project, location, coll, rid, sub, cid, verb = m.groups()
    try:
        data = json.loads(body.decode() or "{}") if body else {}
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Request body is not valid JSON.")
    try:
        if coll == "operations":
            return _json({"name": "projects/%s/locations/%s/operations/%s" % (project, location, rid), "done": True,
                          "metadata": {"@type": "type.googleapis.com/google.cloud.apigateway.v1.OperationMetadata"}})
        if verb:
            return _err(400, "INVALID_ARGUMENT", "Unsupported method :%s." % verb)
        if coll == "apis" and sub is None:
            return _apis(store, method, project, location, rid, data, query)
        if coll == "apis":
            return _configs(store, method, project, rid, cid, data, query)
        return _gateways(store, method, project, location, rid, data, query)
    except _E as e:
        return e.r


def _apis(store, method, project, location, aid, data, query):
    if location not in ("global", "-"):
        raise _E(400, "INVALID_ARGUMENT", "APIs live in the 'global' location.")
    apis = _coll(store, "apis")
    prefix = "projects/%s/locations/global/apis/" % project
    if aid is None:
        if method == "POST":
            rid = str(query.get("apiId") or "").strip()
            _check_id("API", rid)
            full = prefix + rid
            if full in apis:
                raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
            now = _now()
            apis[full] = {"name": full, "createTime": now, "updateTime": now, "displayName": data.get("displayName") or rid,
                          "labels": data.get("labels") or {}, "state": "ACTIVE",
                          "managedService": "%s-%s.apigateway.%s.cloud.goog" % (rid, hashlib.sha256((project + rid).encode()).hexdigest()[:10], project)}
            return _json(_lro(project, "global", "create", _view(apis[full]), full))
        if method == "GET":
            return _json({"apis": sorted((_view(a) for n, a in apis.items() if n.startswith(prefix)), key=lambda a: a["createTime"])})
        raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)
    full = prefix + aid
    a = apis.get(full)
    if a is None:
        raise _E(404, "NOT_FOUND", "Resource '%s' was not found." % full)
    if method == "GET":
        return _json(_view(a))
    if method == "PATCH":
        for f in [x for x in str(query.get("updateMask") or "").split(",") if x] or [k for k in ("displayName", "labels") if k in data]:
            if f not in ("displayName", "labels"):
                raise _E(400, "INVALID_ARGUMENT", "Unsupported updateMask path %s." % f)
            a[f] = data.get(f, a.get(f))
        a["updateTime"] = _now()
        return _json(_lro(project, "global", "update", _view(a), full))
    if method == "DELETE":
        if any(c["name"].startswith(full + "/configs/") for c in _coll(store, "configs").values()):
            raise _E(400, "FAILED_PRECONDITION", "API '%s' still has API configs; delete them first." % full)
        apis.pop(full)
        return _json(_lro(project, "global", "delete", None, full))
    raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)


def _configs(store, method, project, aid, cid, data, query):
    apis, cfgs = _coll(store, "apis"), _coll(store, "configs")
    afull = "projects/%s/locations/global/apis/%s" % (project, aid)
    if afull not in apis:
        raise _E(404, "NOT_FOUND", "Resource '%s' was not found." % afull)
    prefix = afull + "/configs/"
    if cid is None:
        if method == "POST":
            rid = str(query.get("apiConfigId") or "").strip()
            _check_id("API config", rid)
            full = prefix + rid
            if full in cfgs:
                raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
            docs = data.get("openapiDocuments") or []
            if not isinstance(docs, list) or not docs:
                raise _E(400, "INVALID_ARGUMENT", "openapiDocuments must contain at least one OpenAPI document.")
            routes: list = []
            policy: dict = {}
            for d in docs:
                contents = ((d or {}).get("document") or {}).get("contents")
                if not contents:
                    raise _E(400, "INVALID_ARGUMENT", "openapiDocuments[].document.contents is required (base64 of the OpenAPI document).")
                parsed = parse_openapi(_decode(contents))
                routes += openapi_routes(parsed)
                pol = describe_policy(parsed)
                for k, v in pol.items():
                    policy[k] = (policy.get(k) or []) + v if isinstance(v, list) else v
            sa = data.get("gatewayServiceAccount")
            if sa and not re.match(r"^(projects/[^/]+/serviceAccounts/)?[^@\s/]+@[^@\s/]+$", sa):
                raise _E(400, "INVALID_ARGUMENT", "gatewayServiceAccount must be a service account email or resource name, got '%s'." % sa)
            now = _now()
            cfgs[full] = {"name": full, "createTime": now, "updateTime": now, "displayName": data.get("displayName") or rid,
                          "labels": data.get("labels") or {}, "state": "ACTIVE", "gatewayServiceAccount": sa or "",
                          "serviceConfigId": "%s-%s" % (rid, hashlib.sha256((full + now).encode()).hexdigest()[:6]),
                          "openapiDocuments": docs, "_routes": routes, "_policy": policy}
            return _json(_lro(project, "global", "create", _view(cfgs[full]), full))
        if method == "GET":
            full_view = str(query.get("view") or "").upper() == "FULL"
            return _json({"apiConfigs": sorted((_view(c, full_view) for n, c in cfgs.items() if n.startswith(prefix)), key=lambda c: c["createTime"])})
        raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)
    full = prefix + cid
    c = cfgs.get(full)
    if c is None:
        raise _E(404, "NOT_FOUND", "Resource '%s' was not found." % full)
    if method == "GET":
        d = _view(c, str(query.get("view") or "").upper() == "FULL")
        d["routes"] = c["_routes"]   # Vyomi extension: the routes the document defines (the console's Routes table)
        d["policy"] = c.get("_policy") or {}   # Vyomi extension: security schemes + quota limits parsed from the document
        return _json(d)
    if method == "PATCH":
        for f in [x for x in str(query.get("updateMask") or "").split(",") if x] or [k for k in ("displayName", "labels") if k in data]:
            if f not in ("displayName", "labels"):
                raise _E(400, "INVALID_ARGUMENT", "Unsupported updateMask path %s." % f)
            c[f] = data.get(f, c.get(f))
        c["updateTime"] = _now()
        return _json(_lro(project, "global", "update", _view(c), full))
    if method == "DELETE":
        users = [g["name"].split("/")[-1] for g in _coll(store, "gateways").values() if g["apiConfig"] == full]
        if users:
            raise _E(400, "FAILED_PRECONDITION", "API config '%s' is in use by gateway %s." % (full, ", ".join(users)))
        cfgs.pop(full)
        return _json(_lro(project, "global", "delete", None, full))
    raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)


def _gateways(store, method, project, location, gid, data, query):
    gws, cfgs = _coll(store, "gateways"), _coll(store, "configs")
    if location != "-" and location not in _REGION_CODE:
        raise _E(400, "INVALID_ARGUMENT", "Location '%s' is not supported by API Gateway." % location)
    if gid is None:
        if method == "POST":
            if location == "-":
                raise _E(400, "INVALID_ARGUMENT", "A gateway is created in one region, not 'locations/-'.")
            rid = str(query.get("gatewayId") or "").strip()
            _check_id("gateway", rid)
            full = "projects/%s/locations/%s/gateways/%s" % (project, location, rid)
            if full in gws:
                raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
            cfg = str(data.get("apiConfig") or "")
            if not cfg:
                raise _E(400, "INVALID_ARGUMENT", "apiConfig is required.")
            if cfg not in cfgs:
                raise _E(404, "NOT_FOUND", "API config '%s' was not found." % cfg)
            now = _now()
            gws[full] = {"name": full, "createTime": now, "updateTime": now, "displayName": data.get("displayName") or rid,
                         "labels": data.get("labels") or {}, "apiConfig": cfg, "state": "ACTIVE",
                         "defaultHostname": "%s-%s.%s.gateway.dev" % (rid, hashlib.sha256((project + rid).encode()).hexdigest()[:8], _REGION_CODE[location])}
            return _json(_lro(project, location, "create", _view(gws[full]), full))
        if method == "GET":
            pre = "projects/%s/locations/%s/gateways/" % (project, location) if location != "-" else None
            return _json({"gateways": sorted((_view(g) for n, g in gws.items() if (n.startswith(pre) if pre else n.startswith("projects/%s/locations/" % project))),
                                              key=lambda g: g["createTime"])})
        raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)
    full = "projects/%s/locations/%s/gateways/%s" % (project, location, gid)
    g = gws.get(full)
    if g is None:
        raise _E(404, "NOT_FOUND", "Resource '%s' was not found." % full)
    if method == "GET":
        return _json(_view(g))
    if method == "PATCH":
        for f in [x for x in str(query.get("updateMask") or "").split(",") if x] or [k for k in ("apiConfig", "displayName", "labels") if k in data]:
            if f not in ("apiConfig", "displayName", "labels"):
                raise _E(400, "INVALID_ARGUMENT", "Unsupported updateMask path %s." % f)
            if f == "apiConfig" and data.get("apiConfig") not in cfgs:
                raise _E(404, "NOT_FOUND", "API config '%s' was not found." % data.get("apiConfig"))
            g[f] = data.get(f, g.get(f))
        g["updateTime"] = _now()
        return _json(_lro(project, location, "update", _view(g), full))
    if method == "DELETE":
        gws.pop(full)
        return _json(_lro(project, location, "delete", None, full))
    raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)


# ── API Keys API v2 (apikeys.googleapis.com) — the keys an `apiKey` security definition is checked against ──────────────────
_KEYS = re.compile(r"^/v2/projects/([^/]+)/locations/global/keys(?:/([^/:]+))?(/keyString)?(?::(\w+))?$")


def is_apikeys_path(path: str) -> bool:
    return bool(_KEYS.match(path.split("?", 1)[0]))


def dispatch_keys(store, method: str, path: str, query=None, headers=None, body: bytes = b"") -> FirestoreResponse:
    query, method = query or {}, method.upper()
    m = _KEYS.match(path.split("?", 1)[0])
    project, kid, ks, verb = m.groups()
    try:
        data = json.loads(body.decode() or "{}") if body else {}
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Request body is not valid JSON.")
    try:
        keys, prefix = _coll(store, "keys"), "projects/%s/locations/global/keys/" % project
        if kid is None:
            if method == "POST":
                rid = str(query.get("keyId") or "").strip() or "key-" + uuid.uuid4().hex[:8]
                _check_id("key", rid)
                if prefix + rid in keys:
                    raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % (prefix + rid))
                now = _now()
                k = {"name": prefix + rid, "uid": uuid.uuid4().hex, "displayName": data.get("displayName") or rid, "createTime": now,
                     "updateTime": now, "restrictions": data.get("restrictions") or {}, "etag": uuid.uuid4().hex[:12],
                     "keyString": "AIza" + uuid.uuid4().hex[:35]}
                keys[k["name"]] = k
                oid = "projects/%s/locations/global/operations/apigw-%s" % (project, uuid.uuid4().hex[:16])
                return _json({"name": oid, "done": True, "metadata": {"@type": "type.googleapis.com/google.protobuf.Empty"},
                              "response": {"@type": "type.googleapis.com/google.api.apikeys.v2.Key", **{x: y for x, y in k.items() if x != "keyString"}}})
            if method == "GET":
                return _json({"keys": [{x: y for x, y in k.items() if x != "keyString"} for n, k in sorted(keys.items()) if n.startswith(prefix)]})
            raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)
        k = keys.get(prefix + kid)
        if k is None:
            raise _E(404, "NOT_FOUND", "Key '%s' was not found." % (prefix + kid))
        if ks and method == "GET":
            return _json({"keyString": k["keyString"]})
        if method == "GET":
            return _json({x: y for x, y in k.items() if x != "keyString"})
        if method == "DELETE":
            del keys[k["name"]]
            return _json({"name": "projects/%s/locations/global/operations/apigw-%s" % (project, uuid.uuid4().hex[:16]), "done": True})
        raise _E(400, "INVALID_ARGUMENT", "Unsupported method %s." % method)
    except _E as e:
        return e.r
