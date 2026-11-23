"""GCP request -> required IAM permission(s) + full resource name.

`required(method, url, body=None, host=None) -> [{"action","resource","service"}]`

Data-driven: core/iam_catalog/gcp/_methods.json is generated from the public Google API Discovery documents by
scripts/gen_iam_gcp_methods.py (method id, HTTP verb, path template, permission validated against the verbatim roles-permissions
catalog). Hand-written logic here is limited to: path matching, the Cloud Storage resource-name convention + XML API, and a few
request-body extras (iam.serviceAccounts.actAs). An empty list means the request needs no permission (testIamPermissions, tooling
paths) OR is unmapped (callers treat [] as "not gated"; use `describe()` to tell them apart).

Pure Python (json/re/os only): Pyodide-safe, vendored with the engine."""
from __future__ import annotations

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE_PATHS = (os.path.join(_HERE, "..", "iam_catalog", "gcp", "_methods.json"),
                os.path.join(_HERE, "iam_catalog", "gcp", "_methods.json"))
_STATE = {}
_SKIP_TOKENS = {"projects", "locations", "organizations", "folders", "regions", "zones", "global", "v1", "v2", "v1beta1", "beta"}
_VERSION_PREFIX = re.compile(r"^/(?:[a-z][a-z0-9]*/)?(?:v\d+(?:alpha\d*|beta\d*)?(?:p\d+\w*)?|beta|alpha)/")
_PERM_SET = {}


def _load():
    if _STATE:
        return _STATE
    data = None
    for p in _TABLE_PATHS:
        if os.path.exists(p):
            with open(p) as f:
                data = json.load(f)
            break
    if data is None:
        data = {"methods": []}
    by_method = {}
    hosts = set()
    for e in data["methods"]:
        tpl = e["p"]
        rx, lit = _compile(tpl)
        ent = dict(e, rx=rx, lit=lit, tokens={t.lower() for t in e["id"].split(".")[1:-1]} - _SKIP_TOKENS,
                   chain=[t.lower() for t in e["id"].split(".")[1:-1]])
        by_method.setdefault(e["m"], []).append(ent)
        hosts.add(e["h"])
    _STATE.update(by_method=by_method, hosts=hosts, data=data)
    return _STATE


_VER_SEG = re.compile(r"/(v\d+)(?:alpha\d*|beta\d*|p\d+\w*)?(?=/|:|$)")


def _version_tolerant(escaped, tpl):
    """The Discovery table lists one version per method (v1, v2, v1beta4); the same method is served under /v1beta1, /v1alpha,
    /compute/beta ...: accept the major version with any alpha/beta suffix, and Compute's /compute/{v1,beta,alpha}/."""
    if tpl.startswith("/compute/v1/"):
        return escaped.replace(re.escape("/compute/v1/"), "/compute/(?:v1|beta|alpha)/", 1)
    m = _VER_SEG.search(tpl)
    if not m or m.start() > 12:
        return escaped
    major = m.group(1)
    return escaped.replace(re.escape(m.group(0)), "/" + major + r"(?:alpha\d*|beta\d*|p\d+\w*)?", 1)


def _compile(tpl):
    out, lit, i = [], 0, 0
    for part in re.split(r"(\{[^}]+\})", tpl):
        if part.startswith("{"):
            name = part[1:-1]
            greedy = name.startswith("+") or name in ("object", "path", "objectName")
            out.append("(?P<%s>%s)" % (re.sub(r"\W", "_", name) + "_%d" % i, ".+" if greedy else "[^/]+"))
            i += 1
        else:
            out.append(re.escape(part))
            lit += len(part)
    return re.compile("^" + _version_tolerant("".join(out), tpl) + "$"), lit


def _split_url(url):
    host = None
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)(.*)$", url or "", re.I)
    if m:
        host, url = m.group(1).split(":")[0].lower(), m.group(2) or "/"
    path, _, query = (url or "/").partition("?")
    q = {}
    for kv in query.split("&"):
        if kv:
            k, _, v = kv.partition("=")
            q[k] = v
    return host, path or "/", q


def _resource_path(path, kind, entry_p):
    """Concrete request path -> relative resource name (version prefix, custom verb and collection/action suffix removed)."""
    p = _VERSION_PREFIX.sub("", path, count=1).lstrip("/")
    has_verb = bool(re.search(r":[A-Za-z]+$", entry_p))
    p = re.sub(r":[A-Za-z]+$", "", p)
    last_tpl = re.sub(r":[A-Za-z]+$", "", entry_p.rstrip("/")).rsplit("/", 1)[-1]
    if has_verb or "{" in last_tpl or "/" not in p:
        return p                      # names the target resource itself
    if kind == "parent":
        return p.rsplit("/", 1)[0]    # collection-level list/create: the parent is the resource
    return p.rsplit("/", 1)[0]        # `.../instances/{i}/start`: drop the action segment


def _collections(path):
    p = re.sub(r":[A-Za-z]+$", "", _VERSION_PREFIX.sub("", path, count=1).lstrip("/"))
    return [x.lower() for x in p.split("/")[0::2]]


def _storage_name(rel):
    """b/{bucket}/o/{obj} -> projects/_/buckets/{bucket}/objects/{obj} (the Cloud Storage resource-name convention)."""
    m = re.match(r"^b/([^/]+)(?:/(.*))?$", rel)
    if not m:
        return rel
    rest = m.group(2) or ""
    base = "projects/_/buckets/" + m.group(1)
    if rest.startswith("o/"):
        return base + "/objects/" + rest[2:]
    if rest == "o":
        return base
    if rest.startswith("acl") or rest.startswith("defaultObjectAcl") or rest.startswith("notificationConfigs"):
        return base
    return base + ("/" + rest if rest else "")


def _is_perm(p):
    if not _PERM_SET:
        import glob
        for f in glob.glob(os.path.join(_HERE, "..", "iam_catalog", "gcp", "*.json")):
            if not os.path.basename(f).startswith("_"):
                with open(f) as fh:
                    _PERM_SET.update(dict.fromkeys(json.load(fh)["permissions"]))
    return p in _PERM_SET


def _extras(entry_id, body, project_rel):
    """Permissions implied by the request BODY (service-account attachment => actAs)."""
    out = []
    if not isinstance(body, dict):
        return out
    sas = []
    if entry_id in ("compute.instances.insert", "compute.instanceTemplates.insert"):
        props = body.get("properties") or body
        for sa in (props.get("serviceAccounts") or []):
            if isinstance(sa, dict) and sa.get("email"):
                sas.append(sa["email"])
    elif entry_id.startswith("run."):
        t = body.get("template") or (body.get("spec") or {}).get("template") or {}
        for v in (t.get("serviceAccount"), (t.get("spec") or {}).get("serviceAccountName"),
                  ((t.get("template") or {}).get("serviceAccount"))):
            if v:
                sas.append(v)
    elif entry_id.startswith("cloudfunctions."):
        v = body.get("serviceAccountEmail") or (body.get("serviceConfig") or {}).get("serviceAccountEmail")
        if v:
            sas.append(v)
    for sa in sas:
        proj = (sa.split("@", 1)[1].split(".")[0] if "@" in sa else "-")
        out.append({"action": "iam.serviceAccounts.actAs", "service": "iam.googleapis.com",
                    "resource": "//iam.googleapis.com/projects/%s/serviceAccounts/%s" % (proj, sa)})
    return out


def _xml_storage(method, path, q, host, headers_copy=None):
    """Cloud Storage XML API (path-style `/bucket/object` or virtual-host `bucket.storage.googleapis.com/object`)."""
    svc = "storage.googleapis.com"
    bucket, obj = None, ""
    if host and host != svc and host.endswith("." + svc):
        bucket, obj = host[: -len(svc) - 1], path.lstrip("/")
    else:
        parts = path.lstrip("/").split("/", 1)
        bucket = parts[0] or None
        obj = parts[1] if len(parts) > 1 else ""
    method = method.upper()

    def res(b, o=""):
        return "//%s/projects/_/buckets/%s%s" % (svc, b, ("/objects/" + o) if o else "")

    def one(a, r):
        return [{"action": a, "resource": r, "service": svc}]

    if not bucket:
        return one("storage.buckets.list", "//%s/projects/%s" % (svc, q.get("project", "_")))
    if not obj:
        if "acl" in q or "policy" in q:
            return one("storage.buckets.setIamPolicy" if method in ("PUT", "POST") else "storage.buckets.getIamPolicy", res(bucket))
        if method == "GET" and not any(k in q for k in ("location", "versioning", "cors", "lifecycle", "logging", "website",
                                                          "storageClass", "billing", "encryptionConfig", "tagging")):
            return one("storage.objects.list", res(bucket))
        if method in ("GET", "HEAD"):
            return one("storage.buckets.get", res(bucket))
        if method == "PUT" and not q:
            return one("storage.buckets.create", "//%s/projects/%s" % (svc, q.get("project", "_")))
        if method == "DELETE":
            return one("storage.buckets.delete", res(bucket))
        return one("storage.buckets.update", res(bucket))
    r = res(bucket, obj)
    if "acl" in q:
        return one("storage.objects.setIamPolicy" if method in ("PUT", "POST") else "storage.objects.getIamPolicy", r)
    if method in ("GET", "HEAD"):
        return one("storage.objects.get", r)
    if method == "DELETE" and "uploadId" not in q:
        return one("storage.objects.delete", r)
    if method == "DELETE":
        return one("storage.multipartUploads.abort", r)
    if method == "POST" and "uploadId" in q:
        return one("storage.objects.create", r)
    return one("storage.objects.create", r)        # PUT / POST object (upload, copy destination, multipart init)


def describe(method, url, body=None, host=None):
    """Like required() but returns {"method_id", "fallback", "matched": bool, "perms": [...]}; for diagnostics and tests."""
    st = _load()
    h, path, q = _split_url(url)
    h = host or h
    best = _match(st, method, path, h)
    return {"matched": best is not None, "method_id": best[0]["id"] if best else None,
            "fallback": bool(best and best[0].get("f")), "perms": [r["action"] for r in required(method, url, body, host)]}


def _match(st, method, path, host):
    path = re.sub(r"^/(?:upload|download)/", "/", path)
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    cands = st["by_method"].get(method.upper(), [])
    hostmatch = None
    if host:
        hh = host[:-0] if False else host
        hh = re.sub(r"^[a-z0-9]+-(?=[a-z]+\.googleapis\.com$)", "", hh)
        if hh in st["hosts"]:
            hostmatch = hh
    best, best_key = None, None
    colls = _collections(path)
    for e in cands:
        if hostmatch and e["h"] != hostmatch:
            continue
        m = e["rx"].match(path)
        if not m:
            continue
        segs = {s.lower() for s in re.split(r"[/:]", path) if s}
        score = len(e["tokens"] & segs)
        exact = 1 if e["chain"] == colls else 0
        key = (exact, score, e["lit"], -len(e["tokens"]))
        if best is None or key > best_key:
            best, best_key = (e, m), key
    return best


_DENY = re.compile(r"^/v2/policies/(.+?)/denypolicies(?:/([^/]+))?/?$")
_DENY_PERM = {("POST", False): "create", ("GET", False): "list", ("GET", True): "get", ("DELETE", True): "delete",
              ("PUT", True): "update", ("PATCH", True): "update"}


def _deny_policy(method, path):
    """IAM v2 deny policies (iam.googleapis.com/v2; not in the v1 Discovery table): /v2/policies/{attachmentPoint}/denypolicies[/{id}]."""
    m = _DENY.match(path)
    if not m:
        return None
    verb = _DENY_PERM.get((method, bool(m.group(2))))
    if not verb:
        return None
    from urllib.parse import unquote
    return [{"action": "iam.denypolicies." + verb, "service": "iam.googleapis.com",
             "resource": "//iam.googleapis.com/policies/" + unquote(m.group(1)) + "/denypolicies" + ("/" + m.group(2) if m.group(2) else "")}]


# Vyomi's own aggregate surfaces (core/gcp_hub_core.py; Google has no public Discovery API for the Marketplace / Cloud Hub console pages).
# Each is mapped to the permission of the real product it stands for (reason per row); ids are `vyomi.*` pseudo method ids so the
# coverage report counts them like Discovery methods.
VYOMI_ROUTES = (
    ("vyomi.marketplace.products.list", "GET", r"^/vyomi/gcp/([^/]+)/marketplace/products/?$", ["commerceoffercatalog.offers.get"], "commerceoffercatalog.googleapis.com", "projects/{0}", "browsing the offer catalog needs offers.get (no list permission exists)"),
    ("vyomi.marketplace.products.get", "GET", r"^/vyomi/gcp/([^/]+)/marketplace/products/[^/]+/?$", ["commerceoffercatalog.offers.get"], "commerceoffercatalog.googleapis.com", "projects/{0}", "offer details"),
    ("vyomi.marketplace.subscriptions.create", "POST", r"^/vyomi/gcp/([^/]+)/marketplace/subscriptions/?$", ["consumerprocurement.orders.place"], "cloudcommerceconsumerprocurement.googleapis.com", "projects/{0}", "subscribing places an order"),
    ("vyomi.marketplace.subscriptions.list", "GET", r"^/vyomi/gcp/([^/]+)/marketplace/subscriptions/?$", ["consumerprocurement.orders.list"], "cloudcommerceconsumerprocurement.googleapis.com", "projects/{0}", "list orders"),
    ("vyomi.marketplace.subscriptions.get", "GET", r"^/vyomi/gcp/([^/]+)/marketplace/subscriptions/[^/]+/?$", ["consumerprocurement.orders.get"], "cloudcommerceconsumerprocurement.googleapis.com", "projects/{0}", "get order"),
    ("vyomi.marketplace.subscriptions.delete", "DELETE", r"^/vyomi/gcp/([^/]+)/marketplace/subscriptions/[^/]+/?$", ["consumerprocurement.orders.cancel"], "cloudcommerceconsumerprocurement.googleapis.com", "projects/{0}", "cancel order"),
    ("vyomi.hub.overview", "GET", r"^/vyomi/gcp/([^/]+)/hub/overview/?$", ["servicehealth.events.list", "apphub.applications.list"], "servicehealth.googleapis.com", "projects/{0}", "Cloud Hub overview = Service Health incidents + App Hub applications"),
)
_VYOMI = None


def _vyomi(method, path):
    global _VYOMI
    if _VYOMI is None:
        _VYOMI = [(r[0], r[1], re.compile(r[2]), r[3], r[4], r[5]) for r in VYOMI_ROUTES]
    for _id, m, rx, perms, host, res in _VYOMI:
        mm = rx.match(path) if m == method else None
        if mm:
            r = "//%s/%s" % (host, res.format(*mm.groups()))
            return [{"action": a, "resource": r, "service": host} for a in perms]
    return None


def required(method, url, body=None, host=None):
    st = _load()
    h, path, q = _split_url(url)
    h = host or h
    method = (method or "GET").upper()
    if path.startswith("/vyomi/gcp/"):
        vy = _vyomi(method, path)
        if vy is not None:
            return vy
    if h and (h == "storage.googleapis.com" or h.endswith(".storage.googleapis.com")) \
            and not re.match(r"^/(?:upload/|download/)?storage/v1/", path):
        return _xml_storage(method, path, q, h)
    dp = _deny_policy(method, path)
    if dp:
        return dp
    best = _match(st, method, path, h)
    if not best:
        return []
    e, _m = best
    rel = _resource_path(re.sub(r"^/(?:upload|download)/", "/", path), e["k"], e["p"])
    svc = e["h"]
    if e["svc"] == "storage":
        rel = _storage_name(rel) if not rel.startswith("projects/") else rel
        if e["id"] in ("storage.buckets.insert", "storage.buckets.list") or rel == "b":
            rel = "projects/" + (q.get("project") or "_")
    resource = "//%s/%s" % (svc, rel)
    perms = list(e["perm"])
    if e["id"].startswith("firestore.projects.databases.documents.") and "/documents/" in path + "/" and ":" not in path.rsplit("/", 1)[-1]:
        # Firestore document names are variable depth; collection vs document is decided by segment parity after `/documents`.
        tail = re.split(r"/documents/?", path, maxsplit=1)[1].strip("/")
        is_doc = bool(tail) and len(tail.split("/")) % 2 == 0
        if method == "GET":
            perms = ["datastore.entities.get"] if is_doc else ["datastore.entities.list"]
        elif method == "POST":
            perms = ["datastore.entities.create"]
        if is_doc:
            resource = "//%s/%s" % (svc, rel)
        elif tail:
            resource = "//%s/%s" % (svc, rel)
    out = [{"action": p, "resource": resource, "service": svc} for p in perms]
    if e["id"] == "storage.objects.insert" and q.get("name") is not None and e["k"] == "parent":
        out = [{"action": "storage.objects.create", "service": svc,
                "resource": "//%s/%s/objects/%s" % (svc, rel, q["name"])}]
    if e["id"] in ("storage.objects.copy", "storage.objects.rewrite", "storage.objects.compose"):
        out = [{"action": e["perm"][0], "resource": resource, "service": svc}] if e["perm"] else []
        out.append({"action": "storage.objects.create", "resource": resource, "service": svc})
    out += [x for x in _extras(e["id"], body, rel) if _is_perm(x["action"])]
    return out


# --------------------------------------------------------------------------- coverage (used by scripts/gen_iam_coverage.py and tests)

def _synth(tpl):
    """A concrete request path for a method template (every {var} filled; `{+x}` gets a multi-segment name)."""
    n = [0]

    def f(m):
        n[0] += 1
        v = m.group(1)
        return ("projects/p/locations/l/things/t%d" % n[0]) if v.startswith("+") else "n%d" % n[0]
    return re.sub(r"\{([^}]+)\}", f, tpl)


def surface():
    """Every method the table knows, one record each: {"id","api","mapped","perm"} where mapped = a synthesized request for the method
    resolves back to the method's own permission set (round trip through required()); methods that need no permission
    (testIamPermissions) count as mapped. Discovery methods with no catalog permission are listed as unmapped ("unmatched")."""
    st = _load()
    data = st["data"]
    seen, out = set(), []
    for e in data["methods"]:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        got = {r["action"] for r in required(e["m"], _synth(e["p"]), host=e["h"])}
        want = set(e["perm"])
        ok = (got >= want) and (bool(want) or e["id"].endswith(".testIamPermissions"))
        out.append({"id": e["id"], "api": e["id"].split(".")[0], "mapped": bool(ok), "perm": sorted(want), "heuristic": bool(e.get("f"))})
    for mid in data.get("unmatched", []):
        out.append({"id": mid, "api": mid.split(".")[0], "mapped": False, "perm": [], "heuristic": False})
    for r in VYOMI_ROUTES:
        url = "/vyomi/gcp/p/" + r[2].split("/vyomi/gcp/([^/]+)/", 1)[1].replace("[^/]+", "x").replace("/?$", "")
        got = {x["action"] for x in required(r[1], url)}
        out.append({"id": r[0], "api": r[0].split(".")[1], "mapped": got >= set(r[3]), "perm": sorted(r[3]), "heuristic": False})
    return out
