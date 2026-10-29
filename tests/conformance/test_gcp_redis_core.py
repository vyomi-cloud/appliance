"""Unit tests for core/gcp_redis_core.py (run: python3 tests/conformance/test_gcp_redis_core.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_redis_core as rc  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


L = "/v1/projects/p1/locations/us-central1"


def call(st, method, path, body=None, query=None):
    r = rc.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


st = rc.RedisStore()
s, op = call(st, "POST", L + "/instances", {"tier": "BASIC", "memorySizeGb": 2}, {"instanceId": "r1"})
check("create returns a done LRO with the Instance", s == 200 and op["done"] and op["response"]["name"].endswith("/instances/r1")
      and op["metadata"]["verb"] == "create" and "authString" not in op["response"], op)
s, i = call(st, "GET", L + "/instances/r1")
check("get: READY, host, port 6379, version, nodes", s == 200 and i["state"] == "READY" and i["host"] and i["port"] == 6379
      and i["redisVersion"] == "REDIS_7_0" and len(i["nodes"]) == 1 and i["currentLocationId"] == "us-central1-a", i)
check("duplicate -> 409 ALREADY_EXISTS", call(st, "POST", L + "/instances", {"memorySizeGb": 1}, {"instanceId": "r1"})[1]["error"]["status"] == "ALREADY_EXISTS")
check("bad id -> 400", call(st, "POST", L + "/instances", {"memorySizeGb": 1}, {"instanceId": "Bad_Id"})[0] == 400)
check("missing memorySizeGb -> 400", call(st, "POST", L + "/instances", {"tier": "BASIC"}, {"instanceId": "x"})[0] == 400)
check("bad region -> 400", call(st, "POST", "/v1/projects/p1/locations/mars-1/instances", {"memorySizeGb": 1}, {"instanceId": "x"})[0] == 400)
check("alt zone on BASIC -> 400", call(st, "POST", L + "/instances", {"memorySizeGb": 1, "alternativeLocationId": "us-central1-b"}, {"instanceId": "x"})[0] == 400)
check("get missing -> 404 NOT_FOUND", call(st, "GET", L + "/instances/nope")[1]["error"]["status"] == "NOT_FOUND")
s, ha = call(st, "POST", L + "/instances", {"tier": "STANDARD_HA", "memorySizeGb": 5, "authEnabled": True, "redisVersion": "REDIS_6_X"}, {"instanceId": "ha1"})
check("STANDARD_HA: alternative zone, 2 nodes, replicaCount 1", call(st, "GET", L + "/instances/ha1")[1]["alternativeLocationId"] == "us-central1-b"
      and len(call(st, "GET", L + "/instances/ha1")[1]["nodes"]) == 2 and call(st, "GET", L + "/instances/ha1")[1]["replicaCount"] == 1)
check("list (ordered, paged)", [x["name"].rsplit("/", 1)[1] for x in call(st, "GET", L + "/instances")[1]["instances"]] == ["ha1", "r1"]
      and call(st, "GET", L + "/instances", query={"pageSize": "1"})[1]["nextPageToken"] == "1")
check("list across locations '-'", len(call(st, "GET", "/v1/projects/p1/locations/-/instances")[1]["instances"]) == 2)
s, op = call(st, "PATCH", L + "/instances/r1", {"memorySizeGb": 4, "labels": {"env": "dev"}, "displayName": "cache"}, {"updateMask": "memorySizeGb,labels,displayName"})
g = call(st, "GET", L + "/instances/r1")[1]
check("patch memory, labels, displayName", s == 200 and g["memorySizeGb"] == 4 and g["labels"] == {"env": "dev"} and g["displayName"] == "cache", g)
check("patch needs updateMask", call(st, "PATCH", L + "/instances/r1", {"memorySizeGb": 4})[0] == 400)
check("patch immutable field (tier) -> 400", call(st, "PATCH", L + "/instances/r1", {"tier": "STANDARD_HA"}, {"updateMask": "tier"})[0] == 400)
call(st, "PATCH", L + "/instances/r1", {"redisConfigs": {"maxmemory-policy": "allkeys-lru"}}, {"updateMask": "redisConfigs"})
check("redisConfigs patched", call(st, "GET", L + "/instances/r1")[1]["redisConfigs"]["maxmemory-policy"] == "allkeys-lru")
check("bad redis config value -> 400", call(st, "PATCH", L + "/instances/r1", {"redisConfigs": {"maxmemory-policy": "bogus"}}, {"updateMask": "redisConfigs"})[0] == 400)
s, op = call(st, "POST", L + "/instances/ha1:failover", {"dataProtectionMode": "LIMITED_DATA_LOSS"})
g = call(st, "GET", L + "/instances/ha1")[1]
check("failover swaps zones", s == 200 and g["currentLocationId"] == "us-central1-b" and g["alternativeLocationId"] == "us-central1-a", g)
check("failover on BASIC -> 400 FAILED_PRECONDITION", call(st, "POST", L + "/instances/r1:failover", {})[1]["error"]["status"] == "FAILED_PRECONDITION")
check("upgrade to a newer version", call(st, "POST", L + "/instances/ha1:upgrade", {"redisVersion": "REDIS_7_2"})[0] == 200 and call(st, "GET", L + "/instances/ha1")[1]["redisVersion"] == "REDIS_7_2")
check("downgrade -> 400", call(st, "POST", L + "/instances/ha1:upgrade", {"redisVersion": "REDIS_5_0"})[0] == 400)
check("export / import", call(st, "POST", L + "/instances/r1:export", {"outputConfig": {"gcsDestination": {"uri": "gs://bkt/dump.rdb"}}})[0] == 200
      and call(st, "POST", L + "/instances/r1:import", {"inputConfig": {"gcsSource": {"uri": "gs://bkt/dump.rdb"}}})[0] == 200
      and call(st, "POST", L + "/instances/r1:export", {"outputConfig": {"gcsDestination": {"uri": "nope"}}})[0] == 400)
check("rescheduleMaintenance", call(st, "POST", L + "/instances/r1:rescheduleMaintenance", {"rescheduleType": "IMMEDIATE"})[0] == 200
      and "maintenanceSchedule" in call(st, "GET", L + "/instances/r1")[1])
s, a = call(st, "GET", L + "/instances/ha1/authString")
check("getAuthString on an AUTH instance", s == 200 and a["authString"].startswith("auth-"))
check("getAuthString without AUTH -> 400", call(st, "GET", L + "/instances/r1/authString")[0] == 400)
check("authString never in Instance", "authString" not in call(st, "GET", L + "/instances/ha1")[1])
s, ops = call(st, "GET", L + "/operations")
check("operations list + get", s == 200 and len(ops["operations"]) >= 8
      and call(st, "GET", "/v1/" + ops["operations"][0]["name"])[0] == 200)
check("operations cancel on a finished op -> 400", call(st, "POST", "/v1/" + ops["operations"][0]["name"] + ":cancel")[0] == 400)
s, op = call(st, "POST", L + "/instances", {"tier": "BASIC", "memorySizeGb": 1}, {"instanceId": "i1", "$alt": "json;enum-encoding=int"})
check("int enums on request (response.tier/state)", op["response"]["tier"] == 1 and op["response"]["state"] == 2, op)
check("int enums accepted in a request body", call(st, "POST", L + "/instances", {"tier": 3, "memorySizeGb": 1}, {"instanceId": "i2"})[0] == 200
      and call(st, "GET", L + "/instances/i2")[1]["tier"] == "STANDARD_HA")
rc.configure_data_plane("vyomi-valkey", 6379)
check("data plane host used for new instances", call(st, "POST", L + "/instances", {"memorySizeGb": 1}, {"instanceId": "dp"})[0] == 200
      and call(st, "GET", L + "/instances/dp")[1]["host"] == "vyomi-valkey")
rc.configure_data_plane(None)
v = rc.list_all(st)
blank = [(x["id"], k) for x in v for k in ("id", "region", "status", "tier_label", "version", "capacity", "endpoint", "replicas", "network", "auth", "created") if x.get(k) in (None, "", "-")]
check("console view: every grid column filled", not blank, blank)
check("delete", call(st, "DELETE", L + "/instances/r1")[1]["done"] and call(st, "GET", L + "/instances/r1")[0] == 404)
print(f"RESULT pass={PASS} fail={FAIL}")
sys.exit(1 if FAIL else 0)
