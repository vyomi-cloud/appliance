"""vyomi-endurance GCP estate regressions (F300-F399). Host + Pyodide where the core is shared.

    PYTHONPATH=. python3 tests/conformance/test_endurance_gcp_core.py
"""
import asyncio
import json


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


class _Req:
    def __init__(self, path, method="GET"):
        self.scope = {"path": path, "raw_path": path.encode(), "query_string": b"", "headers": []}
        self.method = method
        self.headers = {}


def t_f300():
    from core import middleware
    r = _Req("/v1/v1/locations/us-central1/keyRings/k/cryptoKeys/c/cryptoKeyVersions")
    middleware._collapse_doubled_version(r)
    _check("F300 /v1/v1/ (provider client appends the version to a custom endpoint) collapses to /v1/",
           r.scope["path"].startswith("/v1/locations/") and not r.scope["path"].startswith("/v1/v1"))
    r = _Req("/sql/v1beta4/sql/v1beta4/projects/p/instances")
    middleware._collapse_doubled_version(r)
    _check("F300 Cloud SQL /sql/v1beta4/sql/v1beta4/ collapses", r.scope["path"] == "/sql/v1beta4/projects/p/instances")


def t_router():
    from core import gcp_compute_core as c
    r = {"project": "p", "region": "r", "name": "x", "id": "1", "networkName": "n", "creationTimestamp": "t", "nats": []}
    _check("F301 router without bgp has no bgp block", "bgp" not in c._router_view(r))
    nats = c._norm_nats("p", "r", [{"name": "n1", "natIps": ["u"], "natIpAllocateOption": "MANUAL_ONLY"}])
    _check("F302 NAT keeps natIps and omits an unset logConfig", nats[0]["natIps"] == ["u"] and "logConfig" not in nats[0])
    nats = c._norm_nats("p", "r", [{"name": "n1", "logConfig": {"enable": True, "filter": "ERRORS_ONLY"}}])
    _check("F302 NAT keeps a set logConfig", nats[0]["logConfig"]["filter"] == "ERRORS_ONLY")


def t_f303_f305():
    import json as _j
    from core import gcp_firestore_core as fs, gcp_pubsub_core as ps, gcp_redis_core as rc
    st = fs.FirestoreStore() if hasattr(fs, "FirestoreStore") else None
    r = fs.dispatch(st, "POST", "/v1/projects/p/databases", {"databaseId": "(default)"}, {}, _j.dumps({"locationId": "nam5", "type": "FIRESTORE_NATIVE"}).encode())
    op = _j.loads(r.body)
    _check("F303 firestore database create is a done LRO carrying the Database",
           op["done"] is True and "/operations/" in op["name"] and op["response"]["locationId"] == "nam5")
    g = fs.dispatch(st, "GET", "/v1/" + op["name"], {}, {}, b"")
    _check("F303 the create operation is fetchable by name", g.status == 200 and _j.loads(g.body)["done"] is True)
    d = fs.dispatch(st, "DELETE", "/v1/projects/p/databases/(default)", {}, {}, b"")
    _check("F303 firestore database delete is an LRO", _j.loads(d.body)["done"] is True)


def t_f304_f305():
    import json as _j
    from core import gcp_pubsub_core as ps, gcp_redis_core as rc
    from core.messaging_store import InMemoryMessagingStore
    st = InMemoryMessagingStore()
    ps.dispatch(st, "POST", "/v1/projects/p/schemas", {"schemaId": "s1"}, {}, _j.dumps({"type": "AVRO", "definition": "{}"}).encode())
    g = _j.loads(ps.dispatch(st, "GET", "/v1/projects/p/schemas/s1", {}, {}, b"").body)
    _check("F304 schemas.get with no view returns the definition (the Terraform provider sends none)", g.get("definition") == "{}")
    rs = rc.RedisStore()
    rc.dispatch(rs, "POST", "/v1/projects/p/locations/us-central1/instances", {"instanceId": "r1"}, {}, _j.dumps({"memorySizeGb": 1}).encode())
    i = _j.loads(rc.dispatch(rs, "GET", "/v1/projects/p/locations/us-central1/instances/r1", {}, {}, b"").body)
    _check("F305 redis instance without displayName/redisConfigs reports neither", "displayName" not in i and i["redisConfigs"] == {})


def t_f306_f308():
    import json as _j
    from core import gcp_logging_core as lg, gcp_compute_instances_core as ci
    st = lg.LoggingStore()
    def call(method, path, body=None, query=None):
        r = lg.dispatch(st, method, path, query or {}, {}, _j.dumps(body or {}).encode())
        return r.status, _j.loads(r.body or b"{}")
    s_, m = call("POST", "/v2/projects/p/metrics", {"name": "errs", "filter": "severity>=ERROR"})
    _check("F307 LogMetric.name on the wire is the short id", m["name"] == "errs")
    _check("F307 metric GET by that name works", call("GET", "/v2/projects/p/metrics/errs")[1]["name"] == "errs")
    s_, op = call("POST", "/v2/projects/p/locations/global/buckets:createAsync", {"retentionDays": 30}, {"bucketId": "ops"})
    _check("F308 buckets:createAsync returns a done operation with the bucket", op["done"] and op["response"]["name"].endswith("/buckets/ops"))
    _check("F308 the operation is fetchable", call("GET", "/v2/" + op["name"])[1]["done"] is True)
    cs = ci.ComputeStore()
    ci.set_common_instance_metadata(cs, "p", {"items": [None, {"key": "k", "value": "v"}]})
    _check("F310 null metadata items are dropped", ci.get_project(cs, "p")["commonInstanceMetadata"]["items"] == [{"key": "k", "value": "v"}])
    op = ci.insert_instance_template(cs, "p", {"name": "t1", "properties": {"machineType": "e2-small"}})
    tpl = cs.instance_templates["projects/p/global/instanceTemplates/t1"]
    _check("F309 insert op targetId is the template id and GET by that id works",
           op["targetId"] == str(tpl["id"]) and ci.get_instance_template(cs, "p", op["targetId"]).status == 200)
    imgs = ci.public_images("debian-cloud")
    _check("F306 debian-cloud serves a debian-12 family image", any(i["family"] == "debian-12" for i in imgs))


def t_f313():
    import json as _j
    from core import gcp_run_core as rc
    st = rc.RunStore()
    body = {"template": {"containers": [{"image": "us-docker.pkg.dev/cloudrun/container/hello"}]}}
    r = rc.dispatch(st, "POST", "/v2/projects/p/locations/us-central1/services", {"serviceId": "s1"}, {}, _j.dumps(body).encode())
    g = _j.loads(rc.dispatch(st, "GET", "/v2/projects/p/locations/us-central1/services/s1", {}, {}, b"").body)
    c0 = g["template"]["containers"][0]
    _check("F313 v2 wire view hides simulator-filled container name / cpuIdle / executionEnvironment",
           "name" not in c0 and "cpuIdle" not in c0.get("resources", {}) and "executionEnvironment" not in g["template"] and "_auto" not in _j.dumps(g))
    body["template"]["containers"][0]["name"] = "web"
    rc.dispatch(st, "POST", "/v2/projects/p/locations/us-central1/services", {"serviceId": "s2"}, {}, _j.dumps(body).encode())
    g2 = _j.loads(rc.dispatch(st, "GET", "/v2/projects/p/locations/us-central1/services/s2", {}, {}, b"").body)
    _check("F313 an explicitly set container name is kept", g2["template"]["containers"][0]["name"] == "web")


def run():
    t_f313()
    t_f306_f308()
    t_f304_f305()
    t_f300()
    t_router()
    t_f303_f305()


if __name__ == "__main__":
    run()
    print("OK")
