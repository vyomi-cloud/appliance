"""Cosmos DB account enforcement: provisioned/autoscale RU/s -> 429 RequestRateTooLarge, IP/vnet/private-endpoint rules -> 403.
Run: PYTHONPATH=. python tests/conformance/test_azure_cosmos_limits.py"""
import json
try:
    from core import azure_cosmos_core as cc
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    import azure_cosmos_core as cc  # type: ignore
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    Q = {"api-version": "2024-05-15"}
    RG = f"/subscriptions/{SUB}/resourceGroups/rg"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    acct = RG + "/providers/Microsoft.DocumentDB/databaseAccounts/c1"
    a.handle("PUT", acct, Q, {"location": "eastus", "kind": "GlobalDocumentDB", "properties": {}})
    bad = a.handle("PUT", acct + "/sqlDatabases/db/throughputSettings/default", Q, {"properties": {"resource": {"throughput": 450}}})
    _check("throughput must be multiple of 100", bad["status"] == 400)
    bad = a.handle("PUT", acct + "/sqlDatabases/db/throughputSettings/default", Q, {"properties": {"resource": {"autoscaleSettings": {"maxThroughput": 1500}}}})
    _check("autoscale max multiple of 1000", bad["status"] == 400)
    bad = a.handle("PUT", acct + "/sqlDatabases/db/throughputSettings/default", Q, {"properties": {"resource": {"throughput": 400, "autoscaleSettings": {"maxThroughput": 1000}}}})
    _check("manual+autoscale rejected", bad["status"] == 400)
    ok = a.handle("PUT", acct + "/sqlDatabases/db/containers/items/throughputSettings/default", Q, {"properties": {"resource": {"throughput": 400}}})
    _check("manual offer accepted", ok["status"] in (200, 201))
    st = cc.CosmosStore()
    d = lambda m, p, b=None, h=None: cc.dispatch(st, m, p, {}, h or {}, json.dumps(b).encode() if b is not None else b"", arm_state=a.state)
    d("POST", "/dbs", {"id": "db"})
    d("POST", "/dbs/db/colls", {"id": "items", "partitionKey": {"paths": ["/id"], "kind": "Hash"}})
    t = [1000.0]
    cc._clock = lambda: t[0]
    # 1 KB-ish writes cost ~5 RU each; 400 RU/s -> ~80 writes per second
    codes = []
    for i in range(120):
        r = d("POST", "/dbs/db/colls/items/docs", {"id": f"d{i}", "v": "x"})
        codes.append(r.status)
        if r.status == 429:
            last = r
    _check("first writes succeed", codes[0] == 201)
    _check("burst beyond 400 RU/s gets 429", 429 in codes)
    _check("429 carries retry-after + RequestRateTooLarge", "x-ms-retry-after-ms" in last.headers and json.loads(last.body)["code"] == "RequestRateTooLarge")
    t[0] += 1.1
    r = d("POST", "/dbs/db/colls/items/docs", {"id": "after"})
    _check("budget refills after the second passes", r.status == 201 and float(r.headers["x-ms-request-charge"]) >= 5)
    # raising to autoscale 10000 lifts the limit
    a.handle("PUT", acct + "/sqlDatabases/db/containers/items/throughputSettings/default", Q, {"properties": {"resource": {"autoscaleSettings": {"maxThroughput": 10000}}}})
    codes = [d("POST", "/dbs/db/colls/items/docs", {"id": f"e{i}"}).status for i in range(120)]
    _check("autoscale max 10000 absorbs the burst", 429 not in codes)
    # no offer on another container -> unlimited
    d("POST", "/dbs/db/colls", {"id": "free", "partitionKey": {"paths": ["/id"], "kind": "Hash"}})
    codes = [d("POST", "/dbs/db/colls/free/docs", {"id": f"f{i}"}).status for i in range(150)]
    _check("container with no offer is not limited", 429 not in codes)
    # shared database offer
    a.handle("PUT", acct + "/sqlDatabases/db/throughputSettings/default", Q, {"properties": {"resource": {"throughput": 400}}})
    codes = [d("POST", "/dbs/db/colls/free/docs", {"id": f"g{i}"}).status for i in range(150)]
    _check("shared database offer limits its containers", 429 in codes)

    # network rules
    a.handle("PUT", acct, Q, {"location": "eastus", "properties": {"ipRules": [{"ipAddressOrRange": "203.0.113.0/24"}]}})
    t[0] += 5
    _check("undeclared caller keeps working", d("GET", "/dbs").status == 200)
    _check("allowed ip passes", d("GET", "/dbs", h={"x-vyomi-source-ip": "203.0.113.9"}).status == 200)
    r = d("GET", "/dbs", h={"x-vyomi-source-ip": "198.51.100.1"})
    _check("other ip is 403", r.status == 403 and "firewall" in json.loads(r.body)["message"])
    a.handle("PUT", acct, Q, {"location": "eastus", "properties": {"publicNetworkAccess": "Disabled"}})
    _check("public access disabled blocks", d("GET", "/dbs").status == 403)
    _check("no-arm-state dispatch unchanged", cc.dispatch(st, "GET", "/dbs").status == 200)
    cc._clock = __import__("time").time
    print("cosmos limits: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
