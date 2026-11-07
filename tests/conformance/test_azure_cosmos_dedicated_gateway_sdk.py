"""Cosmos dedicated gateway INTEGRATED CACHE, driven by the REAL azure-cosmos SDK over HTTP: cache hits cost 0 RU and report
x-ms-cosmos-cachehit, staleness honours x-ms-dedicatedgateway-max-age, the standard endpoint is never cached, writes through the
gateway are write-through for point reads while queries stay stale until TTL, and the endpoint is refused without a gateway.
Run: PYTHONPATH=. python tests/conformance/test_azure_cosmos_dedicated_gateway_sdk.py"""
import json
import urllib.request

from azure.cosmos import CosmosClient

from core import azure_cosmos_core as cosmos
from core.azure_arm_core import DEFAULT_SUBSCRIPTION as S
from tests.conformance._az_http_bridge import start, header_transport


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    router, srv, base = start()
    arm = router.az_arm
    RG = f"/subscriptions/{S}/resourceGroups/c-rg"
    arm.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    acct = RG + "/providers/Microsoft.DocumentDB/databaseAccounts/dgw1"
    arm.handle("PUT", acct, {"api-version": "2024-05-15"}, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {"databaseAccountOfferType": "Standard"}})
    seen = {}
    hook = lambda hdrs, body=None: seen.update(hdrs=dict(hdrs))
    def client(endpoint_hdr=None, max_age=None):
        h = {"x-vyomi-account": "dgw1", **({"x-vyomi-endpoint": "dedicated"} if endpoint_hdr else {}),
             **({"x-ms-dedicatedgateway-max-age": str(max_age)} if max_age is not None else {})}
        return CosmosClient(base, credential="a2V5", transport=header_transport(h), enable_endpoint_discovery=False)
    std = client()
    db = std.create_database("d"); c = db.create_container("c", partition_key={"paths": ["/pk"], "kind": "Hash"})
    c.upsert_item({"id": "1", "pk": "a", "v": 1})
    try:
        dg0 = client(True)
        dg0.get_database_client("d").get_container_client("c").read_item("1", "a", response_hook=hook)
        raise AssertionError("expected 503 without gateway")
    except Exception as e:
        _check("dedicated endpoint refused when no gateway is provisioned", "503" in str(e) or "not available" in str(e))
    r = arm.handle("PUT", acct + "/services/SqlDedicatedGateway", {"api-version": "2024-05-15"},
                   {"properties": {"serviceType": "SqlDedicatedGateway", "instanceSize": "Cosmos.D4s", "instanceCount": 1}})
    _check("gateway provisioned via ARM", r["status"] in (200, 201, 202))
    dg = client(True, 60000)
    cc = dg.get_database_client("d").get_container_client("c")
    cc.read_item("1", "a", response_hook=hook)
    _check("first read is a miss", seen["hdrs"].get("x-ms-cosmos-cachehit") == "False")
    cc.read_item("1", "a", response_hook=hook)
    _check("second read is a hit at 0 RU", seen["hdrs"].get("x-ms-cosmos-cachehit") == "True" and float(seen["hdrs"].get("x-ms-request-charge")) == 0.0)
    # change the item behind the gateway (standard endpoint): cached read stays stale
    std.get_database_client("d").get_container_client("c").upsert_item({"id": "1", "pk": "a", "v": 2})
    _check("cache serves stale data until staleness expires", cc.read_item("1", "a", response_hook=hook)["v"] == 1)
    # standard endpoint never cached
    sc = std.get_database_client("d").get_container_client("c")
    sc.read_item("1", "a", response_hook=hook)
    _check("standard endpoint is not cached", "x-ms-cosmos-cachehit" not in seen["hdrs"])
    # staleness 0 / bypass
    bp = client(True, 0).get_database_client("d").get_container_client("c")
    _check("max-age 0 bypasses the cache and sees fresh data", bp.read_item("1", "a", response_hook=hook)["v"] == 2)
    # write-through via the gateway
    cc.upsert_item({"id": "1", "pk": "a", "v": 3})
    _check("write through the gateway updates the point-read entry", cc.read_item("1", "a", response_hook=hook)["v"] == 3)
    # query cache stays stale until TTL
    q = lambda: list(cc.query_items("SELECT * FROM c WHERE c.pk = 'a'", partition_key="a", response_hook=hook))
    q(); first_hit = seen["hdrs"].get("x-ms-cosmos-cachehit")
    sc.upsert_item({"id": "2", "pk": "a", "v": 9})
    n = len(q())
    _check("query cache stale until TTL (new item not visible, hit reported)", n == 1 and seen["hdrs"].get("x-ms-cosmos-cachehit") == "True")
    # TTL expiry using the injected clock
    t0 = cosmos._clock()
    cosmos._clock = lambda: t0 + 120
    try:
        _check("after staleness elapses the query is a miss with fresh data", len(q()) == 2 and seen["hdrs"].get("x-ms-cosmos-cachehit") == "False")
    finally:
        cosmos._clock = __import__("time").time
    m = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/vyomi/dedicatedgateway/metrics", headers={"x-vyomi-account": "dgw1"})).read())["metrics"]
    mm = next(iter(m.values()))
    _check("hit/miss metrics exposed", mm["hits"] >= 3 and mm["misses"] >= 2 and mm["bypass"] >= 1 and mm["hitRatio"] is not None)
    srv.shutdown()
    print("PASS test_azure_cosmos_dedicated_gateway_sdk")


if __name__ == "__main__":
    run()
