"""Front Door / CDN edge: caching reverse proxy over Blob.  Run: PYTHONPATH=. python tests/conformance/test_azure_cdn_edge.py"""
import json
from core import azure_blob_core as bc
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


a = AzureArm()
RG = f"/subscriptions/{SUB}/resourceGroups/rg"
a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
CDN = RG + "/providers/Microsoft.Cdn/profiles/fd1"
def put(path, props, **kw):
    r = a.handle("PUT", path, {"api-version": "2024-02-01"}, {"properties": props, **kw})
    assert r["status"] in (200, 201), r
    return r["body"]
put(CDN, {}, location="global", sku={"name": "Standard_AzureFrontDoor"})
ep = put(CDN + "/afdEndpoints/ep1", {"enabledState": "Enabled"}, location="global")
host = ep["properties"]["hostName"]
og = put(CDN + "/originGroups/og1", {})["id"]
put(CDN + "/originGroups/og1/origins/o1", {"hostName": "edgeacct.blob.core.windows.net", "priority": 1, "weight": 1000})
put(CDN + "/originGroups/og1/origins/dead", {"hostName": "other.example.com", "priority": 2})
rs = put(CDN + "/ruleSets/rs1", {})["id"]
put(CDN + "/ruleSets/rs1/rules/shortimg", {"order": 1, "conditions": [{"name": "UrlFileExtension", "parameters": {"operator": "Equal", "matchValues": ["png"]}}],
    "actions": [{"name": "CacheExpiration", "parameters": {"cacheBehavior": "Override", "cacheDuration": "0.00:00:10"}}]})
put(CDN + "/ruleSets/rs1/rules/hdr", {"order": 2, "actions": [{"name": "ModifyResponseHeader", "parameters": {"headerAction": "Overwrite", "headerName": "X-Served-By", "value": "vyomi-edge"}}]})
put(CDN + "/afdEndpoints/ep1/routes/r1", {"originGroup": {"id": og}, "patternsToMatch": ["/*"], "ruleSets": [{"id": rs}], "cacheConfiguration": {"queryStringCachingBehavior": "IgnoreQueryString"}})
put(CDN + "/afdEndpoints/ep1/routes/nocache", {"originGroup": {"id": og}, "patternsToMatch": ["/live/*"]})

arm = a.state
st = bc.AzureBlobStore()
bc.dispatch(st, "PUT", "/site", {"restype": "container"}, {"x-ms-blob-public-access": "blob"}, b"", account="edgeacct", arm_state=arm)
def blob(name, data, ct="text/plain"):
    return bc.dispatch(st, "PUT", f"/site/{name}", {}, {"x-ms-blob-type": "BlockBlob", "content-type": ct}, data, account="edgeacct", arm_state=arm)
check("blob uploaded", blob("a.txt", b"v1").status == 201)
blob("logo.png", b"PNG", "image/png")
bc.dispatch(st, "PUT", "/live", {"restype": "container"}, {"x-ms-blob-public-access": "blob"}, b"", account="edgeacct", arm_state=arm)
bc.dispatch(st, "PUT", "/live/now.txt", {}, {"x-ms-blob-type": "BlockBlob"}, b"t1", account="edgeacct", arm_state=arm)
def get(path, q=None, h=None, m="GET", body=b""):
    return bc.dispatch(st, m, f"/_edge/{host}{path}", q or {}, h or {}, body, arm_state=arm)

r = get("/site/a.txt")
check("first request MISS from blob origin", r.status == 200 and r.body == b"v1" and r.headers["x-cache"] == "TCP_MISS")
r = get("/site/a.txt")
check("second request HIT", r.status == 200 and r.headers["x-cache"] == "TCP_HIT" and r.body == b"v1")
blob("a.txt", b"v2-new")
check("origin changed but edge still serves cached copy", get("/site/a.txt").body == b"v1")
check("rule set header applied", get("/site/a.txt").headers.get("x-served-by") == "vyomi-edge")
etag = get("/site/a.txt").headers["etag"]
check("conditional request 304 from edge", get("/site/a.txt", h={"If-None-Match": etag}).status == 304)
p = get("/__purge", m="POST", body=json.dumps({"contentPaths": ["/site/*"]}).encode())
check("purge evicts", p.status == 200 and json.loads(p.body)["purged"] >= 1)
r = get("/site/a.txt")
check("after purge fetches new content (MISS)", r.body == b"v2-new" and r.headers["x-cache"] == "TCP_MISS")
check("ignore-query-string shares the entry", get("/site/a.txt", {"x": "1"}).headers["x-cache"] == "TCP_HIT")
check("route without cacheConfiguration is never cached", get("/live/now.txt").headers["x-cache"] == "CONFIG_NOCACHE" and get("/live/now.txt").headers["x-cache"] == "CONFIG_NOCACHE")
bc.dispatch(st, "PUT", "/live/now.txt", {}, {"x-ms-blob-type": "BlockBlob"}, b"t2", account="edgeacct", arm_state=arm)
check("uncached route always shows the origin's current bytes", get("/live/now.txt").body == b"t2")
check("png TTL override: cached", get("/site/logo.png").headers["x-cache"] == "TCP_MISS" and get("/site/logo.png").headers["x-cache"] == "TCP_HIT")
import core.azure_cdn_edge_core as e
ent = next(v for k, v in st._edge_cache["entries"].items() if k[1].endswith("logo.png"))
check("TTL came from CacheExpiration action (10 s)", abs((ent["expires"] - ent["stored"]) - 10) < 0.01)
ent["expires"] = 0
check("expired entry is refetched", get("/site/logo.png").headers["x-cache"] == "TCP_MISS")
check("missing blob 404 passes through and is not cached", get("/site/none.txt").status == 404 and get("/site/none.txt").headers["x-cache"] == "TCP_MISS")
s = json.loads(get("/__stats").body)
check("stats count hits/misses/origin requests", s["hits"] >= 4 and s["misses"] >= 4 and s["originRequests"] == s["misses"] + s["bypass"])
check("unknown host 404", bc.dispatch(st, "GET", "/_edge/nope.z01.azurefd.net/x", {}, {}, b"", arm_state=arm).status == 404)
put(CDN + "/afdEndpoints/ep1/routes/r1", {"originGroup": {"id": og}, "patternsToMatch": ["/only/*"]})
check("no route matches the path -> 404 RouteNotFound", get("/site/zzz.txt").status == 404 and b"RouteNotFound" in get("/site/zzz.txt").body)
put(CDN + "/afdEndpoints/ep1", {"enabledState": "Disabled"}, location="global")
check("disabled endpoint 404", get("/site/a.txt").status == 404)
print("PASS")
