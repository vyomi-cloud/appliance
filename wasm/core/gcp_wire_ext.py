# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP wire gap-filler: serves the Google API methods the per-service cores do not (yet) implement.

Two parts, both pure Python (load under Pyodide), both fed by the same persisted account dict the cores use:

1. `pre()`  -- claims whole APIs that have a dedicated core here:
     Cloud Functions v1/v2 (core/gcp_functions_core, backed by the Cloud Run store), Cloud DNS (core/gcp_dns_core),
     Security Command Center v1 (core/gcp_scc_v1_core over the v2 engine) and the functions HTTPS trigger URL.
2. `fallback()` -- a schema-driven resource store for everything else.  When a request is addressed to a Google API method
   that the per-service cores answered with "unknown route", the method table generated from the discovery documents
   (core/gcp_ext_specs.py) is consulted.  CRUD is real state: create stores the resource under its resource name, get/list/
   patch/delete operate on what is stored (404 / 409 / paging behave like the API), long-running methods return a completed
   Operation that can be fetched later, IAM verbs keep a real policy with etag, setLabels merges labels, enable/disable/
   undelete/cancel move a real `state`.  Parents must exist (checked against this store and, for resources owned by a
   dedicated core, against that core through `primary_get`).
Honest limits: resources are records -- they do not (yet) drive data-plane behaviour in other engines; semantics beyond
shape/uniqueness/parent/state validation belong in a dedicated core (as Functions, DNS and SCC have).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone


UNWIRED = re.compile(
    r"Unsupported|No route|UnknownOperation|InvalidAction|not implemented|NotImplemented|Unknown path|Unknown operation|"
    r"not simulated|UnrecognizedOperation|ResourceTypeNotSupported|Not Found Handler|unknown route|is not supported by|unrecognized|"
    r"Unknown method|Method not allowed|Unknown (?:operations )?path|NoSuchBucket|InvalidBucketName", re.I)

_COMPILED = None


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _specs():
    global _COMPILED
    if _COMPILED is None:
        from core.gcp_ext_specs import SPECS   # big generated table: loaded on first use only
        _COMPILED = []
        for api, rows in SPECS.items():
            for (mid, http, rx, lk, kind, idp, resp) in rows:
                _COMPILED.append((api, mid, http, re.compile(rx), lk, kind, idp, resp))
    return _COMPILED


def _resp(status, obj, media="application/json"):
    return {"status": status, "headers": {"content-type": media}, "body": obj if isinstance(obj, (bytes, bytearray)) else json.dumps(obj).encode()}


def _error(status, code, msg):
    return _resp(status, {"error": {"code": status, "message": msg, "status": code,
                                    "errors": [{"message": msg, "domain": "global", "reason": code.lower()}]}})


def looks_unwired(res):
    if res is None:
        return True
    st = res.get("status", 200)
    if st < 400 and st != 501:
        return False
    b = (res.get("body") or b"")[:700].decode("utf8", "replace")
    return st == 501 or bool(UNWIRED.search(b)) or (b.startswith("<?xml") and "<Error><Code>" in b)


# ── (1) dedicated cores ─────────────────────────────────────────────────────────────────
def _base(headers):
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    host = h.get("host") or "localhost"
    proto = h.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.", "x", "0.0.0.0", "[::1]")) or ":" in host else "https")
    return "%s://%s" % (proto, host)


def pre(router, method, path, query, headers, body):
    """Return a router response dict for APIs owned by a dedicated core here, else None."""
    p = path.split("?", 1)[0]
    if not p.startswith(("/v1/", "/v2/", "/dns/", "/gcf", "/gcf-upload/")):
        return None
    from core import gcp_dns_core, gcp_functions_core, gcp_scc_v1_core
    bag = router.s3.account
    if gcp_dns_core.handles(p):
        r = gcp_dns_core.dispatch(bag, method, _norm(router, p), _normq(router, p, query), bytes(body))
        _persist(router)
        return {"status": r.status, "headers": {"content-type": "application/json"}, "body": r.body}
    if gcp_functions_core.handles(p) or p.startswith("/gcf/"):
        ctx = {"run": router.gcp_run, "gcs": router.gcs, "gcs_mod": _gcs_mod(), "topic_exists": router._run_topic_exists, "base": _base(headers)}
        if p.startswith("/gcf/"):
            r = gcp_functions_core.http_trigger(bag, method, p, _qs(query), {str(k).lower(): v for k, v in (headers or {}).items()}, bytes(body), ctx)
            if r is None:
                return None
            _persist(router)
            return {"status": r.status, "headers": dict(r.headers, **{"content-type": r.media_type}), "body": r.body}
        pp = _norm(router, p)
        r = gcp_functions_core.dispatch(bag, method, pp, _normq(router, p, query), headers, bytes(body), ctx)
        _persist(router)
        return {"status": r.status, "headers": dict(r.headers or {}, **{"content-type": r.media_type}), "body": r.body}
    if gcp_scc_v1_core.handles(p):
        sctx = dict(router.scc_ctx(), instances=router.gcp_compute_vm.instances, buckets=router.gcs.buckets,
                    firewalls=list(router.gcp_compute.firewalls.values()), run_services=router.gcp_run.services)
        r = gcp_scc_v1_core.dispatch(bag.setdefault("gcp_scc", {}), method, _norm(router, p), _normq(router, p, query), bytes(body), sctx)
        _persist(router)
        return {"status": r.status, "headers": {"content-type": "application/json"}, "body": r.body}
    return None


def _gcs_mod():
    from core import gcp_storage_core
    return gcp_storage_core


def _qs(query):
    return "&".join("%s=%s" % (k, v if not isinstance(v, list) else v[0]) for k, v in (query or {}).items())


def _norm(router, p):
    """Project number/ID normalisation shared with the other GCP cores (one project per space)."""
    from core import gcp_project as gp
    if getattr(router, "STRICT_GCP_PROJECT", False):
        proj = router.gcp_project() if callable(router.gcp_project) else router.gcp_project
        np_, _q, err = gp.normalize_request(p, {}, "GET", proj)
        if err is None:
            return np_
    return p


def _normq(router, p, query):
    from core import gcp_project as gp
    q = dict(query or {})
    if getattr(router, "STRICT_GCP_PROJECT", False):
        proj = router.gcp_project() if callable(router.gcp_project) else router.gcp_project
        _p, nq, err = gp.normalize_request(p, q, "GET", proj)
        if err is None:
            return nq
    return {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}


def _persist(router):
    try:
        router.s3.persist()
    except Exception:
        pass


# ── (2) schema-driven store ─────────────────────────────────────────────────────────────
def _st(bag):
    s = bag.setdefault("gcp_ext", {})
    s.setdefault("res", {})      # path (no verb, no query) -> resource
    s.setdefault("pol", {})      # path -> IAM policy
    s.setdefault("seq", 0)
    return s


def _singular(coll):
    if coll.endswith("ies"):
        return coll[:-3] + "y"
    if coll.endswith("sses"):
        return coll[:-2]
    return coll[:-1] if coll.endswith("s") else coll


def _kind_of(mid):
    last = mid.rsplit(".", 1)[-1]
    if last in ("list", "aggregatedList"):
        return "list"
    if last == "get":
        return "get"
    if last in ("create", "insert"):
        return "create"
    if last in ("patch", "update"):
        return "update"
    if last == "delete":
        return "delete"
    return last


def _match(method, p):
    for api, mid, http, rx, lk, kind, idp, resp in _specs():
        if http == method and rx.match(p):
            return api, mid, lk, kind, idp, resp
    return None


def _split_verb(p):
    head, _, last = p.rpartition("/")
    if ":" in last:
        last, _, verb = last.partition(":")
        return head + "/" + last, verb
    return p, ""


def _is_compute(api):
    return api.startswith("compute.")


def _children(s, coll):
    pre_ = coll + "/"
    return [(k, v) for k, v in sorted(s["res"].items()) if k.startswith(pre_) and "/" not in k[len(pre_):]]


def fallback(router, method, path, query, headers, body, primary):
    """Serve `method path` from the method table if the dedicated cores did not. Returns a response dict or None."""
    p0 = path.split("?", 1)[0]
    if not p0.startswith(("/v1/", "/v2/", "/v3/", "/compute/", "/dns/")):
        return None
    method = method.upper()
    p, verb = _split_verb(p0)
    hit = _match(method, p0) or _match(method, p)
    if hit is None:
        return None
    api, mid, lk, kind, idp, resp = hit
    last = mid.rsplit(".", 1)[-1]
    if not verb and _kind_of(mid) not in ("list", "get", "create", "update", "delete") and p.endswith("/" + last):
        p, verb = p[: -len(last) - 1], last   # Compute spells custom methods as a trailing path segment (…/{resource}/setIamPolicy)
    s = _st(router.s3.account)
    q = {k: (v[0] if isinstance(v, list) else v) for k, v in (query or {}).items()}
    try:
        data = json.loads(bytes(body).decode("utf-8")) if body else {}
    except ValueError:
        return _error(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(data, dict):
        data = {}

    def primary_get(path_):
        try:
            r = router.handle("GET", path_, {}, {"host": "x"}, b"")
        except Exception:
            return None
        return r if r.get("status") == 200 else None

    try:
        out = _serve(router, s, api, mid, lk, kind, idp, resp, method, p, verb, q, data, primary_get, headers)
    except _Err as e:
        return _error(e.status, e.code, e.msg)
    _persist(router)
    return out


class _Err(Exception):
    def __init__(self, status, code, msg):
        self.status, self.code, self.msg = status, code, msg


def _name_of(api, p):
    """Resource name as the API reports it: path minus the version prefix (compute reports short names)."""
    n = re.sub(r"^/(?:compute/)?v[0-9a-z]+/", "", p)
    return n


def _op(s, api, p, resource, kind, mid, kind_resp, project_hint=""):
    """A completed operation for the mutation, stored so the API's operations.get returns it."""
    s["seq"] += 1
    n = s["seq"]
    if _is_compute(api):
        m = re.match(r"^(/compute/v1/projects/[^/]+)/(global|regions/[^/]+|zones/[^/]+)/", p)
        scope = m.group(2) if m else "global"
        base = m.group(1) if m else "/compute/v1/projects/-"
        name = "operation-%013d" % (1700000000000 + n)
        link = "https://www.googleapis.com" + base + "/" + scope + "/operations/" + name
        target = "https://www.googleapis.com" + p
        o = {"kind": "compute#operation", "id": str(5000000000000000000 + n), "name": name, "operationType": mid.rsplit(".", 1)[-1] if kind != "update" else "patch",
             "targetLink": target, "targetId": (resource or {}).get("id", ""), "status": "DONE", "user": "admin@vyomi.cloud", "progress": 100,
             "insertTime": _now(), "startTime": _now(), "endTime": _now(), "selfLink": link}
        if scope.startswith("regions/"):
            o["region"] = "https://www.googleapis.com" + base + "/" + scope
        elif scope.startswith("zones/"):
            o["zone"] = "https://www.googleapis.com" + base + "/" + scope
        s["res"][base + "/" + scope + "/operations/" + name] = o
        return o
    lm = re.match(r"^(/v[0-9a-z]+/(?:projects|folders|organizations|billingAccounts)/[^/]+/locations/[^/]+)", p)
    if lm:
        scope = lm.group(1)
    else:
        om = re.match(r"^(/v[0-9a-z]+/(?:projects|folders|organizations|billingAccounts|locations)/[^/]+)", p)
        scope = om.group(1) if om else re.match(r"^(/v[0-9a-z]+)", p).group(1)
    oid = "operation-%d-%012x" % (int(time.time() * 1000), n)
    path = scope + "/operations/" + oid
    o = {"name": _name_of(api, path), "metadata": {"@type": "type.googleapis.com/google.protobuf.Struct", "target": _name_of(api, p), "verb": mid.rsplit(".", 1)[-1],
                                                     "createTime": _now(), "endTime": _now(), "apiVersion": "v1"},
         "done": True}
    if kind_resp in ("res", "op") and resource is not None and kind != "delete":
        o["response"] = dict(resource, **{"@type": "type.googleapis.com/google.protobuf.Struct"})
    else:
        o["response"] = {"@type": "type.googleapis.com/google.protobuf.Empty"}
    s["res"][path] = o
    return o


def _view(api, p, r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _page(items, q):
    size = q.get("pageSize") or q.get("maxResults")
    try:
        size = int(size) if size else 0
        start = int(q.get("pageToken") or 0)
    except ValueError:
        raise _Err(400, "INVALID_ARGUMENT", "Invalid pageSize/pageToken.")
    if not size:
        return items, ""
    nxt = str(start + size) if start + size < len(items) else ""
    return items[start:start + size], nxt


def _parent_ok(s, api, p, primary_get):
    """The collection's parent must exist when it is itself a stored resource kind; dedicated-core / root parents are checked via primary."""
    coll = p.rsplit("/", 1)[0] if p.count("/") > 1 else p
    par = coll.rsplit("/", 1)[0]
    parts = par.strip("/").split("/")
    if len(parts) <= 3 or par in s["res"] or par.endswith("/global"):
        return
    if re.search(r"/(projects|folders|organizations|billingAccounts|locations|global|regions|zones|aggregated)/[^/]+$", par) and not re.search(r"/(sinks|buckets|views|exclusions|savedQueries|pools|providers)/[^/]+$", par):
        return
    if re.search(r"/(?:projects|folders|organizations|billingAccounts)/[^/]+/locations/[^/]+$", par):
        return
    if primary_get(par) is not None:
        return
    raise _Err(404, "NOT_FOUND", "Parent resource %s was not found." % _name_of("", par))


def _scope_of_list(p):
    return p


def _serve(router, s, api, mid, lk, kind, idp, resp, method, p, verb, q, data, primary_get, headers):
    res = s["res"]
    k = _kind_of(mid)
    comp = _is_compute(api)
    # ── list ──
    if k == "list":
        if mid.endswith("aggregatedList"):
            m = re.match(r"^(/compute/v1/projects/[^/]+)/aggregated/(.+)$", p)
            base, coll = (m.group(1), m.group(2)) if m else (p, "")
            items = {}
            for key, v in sorted(res.items()):
                mm = re.match(re.escape(base) + r"/(global|regions/[^/]+|zones/[^/]+)/" + re.escape(coll) + r"/[^/]+$", key)
                if mm:
                    items.setdefault(mm.group(1), []).append(_view(api, key, v))
            return _resp(200, {"kind": "compute#" + _singular(coll) + "AggregatedList", "id": "projects/x/aggregated/" + coll,
                               "items": {sc: {coll: v} for sc, v in items.items()}, "selfLink": "https://www.googleapis.com" + p})
        ch = _children(s, p)
        if comp and q.get("filter"):
            m = re.match(r'^\s*name\s*(=|eq)\s*"?([^"]+)"?\s*$', q["filter"])
            if m:
                ch = [(a, b) for a, b in ch if b.get("name") == m.group(2)]
        page, nxt = _page([_view(api, a, b) for a, b in ch], q)
        if comp:
            out = {"kind": "compute#" + _singular(p.rsplit("/", 1)[-1]) + "List", "id": p.strip("/"), "items": page, "selfLink": "https://www.googleapis.com" + p}
            if nxt:
                out["nextPageToken"] = nxt
            return _resp(200, out)
        out = {lk or p.rsplit("/", 1)[-1]: page}
        if nxt:
            out["nextPageToken"] = nxt
        return _resp(200, out)
    # ── get ──
    if k == "get" and not verb:
        r = res.get(p)
        if r is None:
            raise _Err(404, "NOT_FOUND", "The resource '%s' was not found" % _name_of(api, p))
        return _resp(200, _view(api, p, r))
    # ── create ──
    if k == "create" and not verb:
        _parent_ok(s, api, p + "/x", primary_get)
        cid = (q.get(idp) if idp else "") or data.get(idp[:-2] if idp.endswith("Id") else "") or ""
        if not cid:
            nm = data.get("name") or data.get("id") or data.get("displayName") or ""
            cid = str(nm).rsplit("/", 1)[-1]
        if not cid:
            s["seq"] += 1
            cid = "%s-%d" % (_singular(p.rsplit("/", 1)[-1])[:20].lower(), s["seq"])
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._~@+-]{0,127}$", cid):
            raise _Err(400, "INVALID_ARGUMENT", "Invalid resource id '%s'." % cid)
        key = p + "/" + cid
        if key in res:
            raise _Err(409, "ALREADY_EXISTS", "Resource '%s' already exists." % _name_of(api, key))
        r = dict(data)
        s["seq"] += 1
        if comp:
            base = "https://www.googleapis.com" + key
            r.update({"kind": "compute#" + _singular(p.rsplit("/", 1)[-1]), "id": str(4000000000000000000 + s["seq"]), "name": cid,
                      "creationTimestamp": _now(), "selfLink": base})
        else:
            r["name"] = _name_of(api, key)
            if "createTime" not in r:
                r["createTime"] = _now()
            r["updateTime"] = r["createTime"]
        res[key] = r
        if kind == "op":
            return _resp(200, _op(s, api, key, r, "create", mid, kind))
        return _resp(200, _view(api, key, r))
    # ── update ──
    if k == "update" and not verb:
        r = res.get(p)
        if r is None:
            raise _Err(404, "NOT_FOUND", "The resource '%s' was not found" % _name_of(api, p))
        mask = [x for x in (q.get("updateMask") or "").split(",") if x]
        for f, v in data.items():
            if f in ("name", "id", "kind", "selfLink", "creationTimestamp", "createTime"):
                continue
            if mask and f not in {m_.split(".")[0] for m_ in mask}:
                continue
            if isinstance(v, dict) and isinstance(r.get(f), dict) and method == "PATCH":
                r[f] = dict(r[f], **v)
            else:
                r[f] = v
        if "updateTime" in r or not comp:
            r["updateTime"] = _now()
        if "fingerprint" in r:
            r["fingerprint"] = "%x" % (hash(json.dumps(r, sort_keys=True, default=str)) & 0xffffffff)
        if kind == "op":
            return _resp(200, _op(s, api, p, r, "update", mid, kind))
        return _resp(200, _view(api, p, r))
    # ── delete ──
    if k == "delete" and not verb:
        if p not in res:
            raise _Err(404, "NOT_FOUND", "The resource '%s' was not found" % _name_of(api, p))
        r = res.pop(p)
        for ck in [x for x in res if x.startswith(p + "/")]:
            del res[ck]
        s["pol"].pop(p, None)
        if kind == "op":
            return _resp(200, _op(s, api, p, r, "delete", mid, kind))
        return _resp(200, {})
    # ── actions ──
    return _action(s, api, mid, lk, kind, resp, method, p, verb or k, q, data, primary_get)


def _action(s, api, mid, lk, kind, resp, method, p, verb, q, data, primary_get):
    res = s["res"]
    target = res.get(p)
    exists = target is not None or (primary_get(p) is not None if target is None else False)
    coll_level = p.rsplit("/", 1)[-1] in ("operations",) or (target is None and _children(s, p) and verb in ("search", "fetch", "group", "query", "list", "aggregatedList"))
    if verb in ("getIamPolicy", "setIamPolicy", "testIamPermissions"):
        if not exists:
            raise _Err(404, "NOT_FOUND", "The resource '%s' was not found" % _name_of(api, p))
        pol = s["pol"].setdefault(p, {"version": 1, "etag": "ACAB", "bindings": []})
        if verb == "getIamPolicy":
            return _resp(200, pol)
        if verb == "setIamPolicy":
            new = dict(data.get("policy") or {})
            for fld in ("bindings", "etag", "version", "auditConfigs"):   # compute's *SetPolicyRequest carries them at the top level
                if fld in data and fld not in new:
                    new[fld] = data[fld]
            if new.get("etag") and new["etag"] != pol["etag"] and pol["bindings"]:
                raise _Err(409, "ABORTED", "There were concurrent policy changes. Please retry the whole read-modify-write with exponential backoff.")
            new["bindings"] = new.get("bindings") or []
            new["version"] = new.get("version", 1)
            new["etag"] = "BwY%s=" % format(int(time.time() * 1000) & 0xffffff, "x")
            s["pol"][p] = new
            return _resp(200, new)
        return _resp(200, {"permissions": list(data.get("permissions") or [])})
    if verb == "cancel" and mid.endswith("operations.cancel"):
        if target is None:
            raise _Err(404, "NOT_FOUND", "Operation %s not found" % _name_of(api, p))
        return _resp(200, {})
    if target is None and exists and verb not in ("search", "fetch", "group", "query"):
        # the resource is owned by a dedicated core that does not implement this verb: say so rather than pretend
        raise _Err(501, "UNIMPLEMENTED", "Method %s is not implemented for %s (served by its own service core)." % (mid.rsplit(".", 1)[-1], _name_of(api, p)))
    if verb == "setLabels":
        if target is None and not exists:
            raise _Err(404, "NOT_FOUND", "The resource '%s' was not found" % _name_of(api, p))
        fp = target.get("labelFingerprint")
        if data.get("labelFingerprint") and fp and data["labelFingerprint"] != fp:
            raise _Err(412, "FAILED_PRECONDITION", "Labels fingerprint either invalid or resource labels have changed")
        target["labels"] = dict(data.get("labels") or {})
        target["labelFingerprint"] = "%x" % (hash(json.dumps(target["labels"], sort_keys=True)) & 0xffffffff)
        return _resp(200, _op(s, api, p, target, "update", mid, kind) if kind == "op" else _view(api, p, target))
    state_map = {"enable": "ENABLED", "disable": "DISABLED", "undelete": "ACTIVE", "cancel": "CANCELLED", "start": "RUNNING", "stop": "STOPPED",
                 "suspend": "SUSPENDED", "resume": "RUNNING", "retry": "ACTIVE", "activate": "ACTIVE", "deactivate": "INACTIVE"}
    if target is not None:
        if verb in state_map:
            if verb == "undelete":
                target.pop("deleteTime", None)
                target.pop("expireTime", None)
            if "deleted" in str(target.get("state", "")).lower() and verb != "undelete":
                raise _Err(400, "FAILED_PRECONDITION", "The resource is deleted.")
            target["state"] = state_map[verb]
            if verb in ("disable",) and "disabled" in target:
                target["disabled"] = True
        target.setdefault("_actions", []).append({"action": verb, "time": _now()})
        for f, v in data.items():
            if f not in ("name", "id", "kind", "selfLink") and not isinstance(v, (dict, list)) or (f in ("labels", "description") and f in data):
                target[f] = v
        target["updateTime"] = _now() if not _is_compute(api) else target.get("updateTime")
        if kind == "op":
            return _resp(200, _op(s, api, p, target, "update", mid, kind))
        if kind == "res":
            return _resp(200, _view(api, p, target))
        return _resp(200, {})
    if not exists and p.count("/") > 3 and not coll_level and not (lk and _children(s, p)):
        # a resource-level action on something that does not exist (collection-level ones return their list)
        if not lk:
            raise _Err(404, "NOT_FOUND", "The resource '%s' was not found" % _name_of(api, p))
    if lk:
        ch = _children(s, p)
        page, nxt = _page([_view(api, a, b) for a, b in ch], q)
        out = {lk: page}
        if nxt:
            out["nextPageToken"] = nxt
        return _resp(200, out)
    if kind == "op":
        return _resp(200, _op(s, api, p, None, "update", mid, kind))
    return _resp(200, {})
