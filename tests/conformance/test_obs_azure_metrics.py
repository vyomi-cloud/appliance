"""Azure per-resource metrics fed by the observability recorder (Key Vault / Service Bus / Cosmos / Function App ...). Hermetic."""
import time
from core import observability_core as O, azure_monitor_core as M

F = []
def ck(n, c):
    print(("PASS " if c else "FAIL ") + n)
    if not c: F.append(n)

obs = O.ObsStore()
M.resource_metric_defs = O.azure_metric_defs
M.resource_series = lambda *a: O.azure_series(obs, *a)
now = time.time()
SUB = "/subscriptions/s1/resourceGroups/rg"
def rid(t, n): return f"{SUB}/providers/{t}/{n}"
state = {}
for t, n in [("Microsoft.KeyVault/vaults", "kv1"), ("Microsoft.ServiceBus/namespaces", "sb1"), ("Microsoft.DocumentDB/databaseAccounts", "cos1"),
             ("Microsoft.Web/sites", "fn1"), ("Microsoft.ContainerRegistry/registries", "acr1")]:
    state[rid(t, n).lower()] = {"_type": t, "name": n, "id": rid(t, n)}
for i in range(10):
    O.record(obs, "azure", "az-kv-secrets", "kv1", "GET", 200 if i < 8 else 404, 10 + i, ts=now - 60 + i)
O.record(obs, "azure", "keyvault", "kv1", "GET", 500, 40, ts=now - 30)
O.record(obs, "azure", "az-servicebus", "sb1", "POST", 201, 5, ts=now - 50)
O.record(obs, "azure", "az-servicebus", "sb1", "POST", 400, 5, ts=now - 49)
O.record(obs, "azure", "az-cosmos", "", "POST", 201, 7, ts=now - 20, nbytes_in=2048)   # unattributable -> only account of the type
O.record(obs, "azure", "functionapp", "fn1", "GET", 500, 120, ts=now - 20)
O.record(obs, "azure", "keyvault", "kv1", "MonitorRead", 200, 1, ts=now - 5)
ck("extract host", O.extract_resource("azure", "az-kv-secrets", "GET", "/secrets", {"host": "myv.vault.azure.net"})[0] == "myv")
ck("extract arm", O.extract_resource("azure", "keyvault", "PUT", "/subscriptions/s/resourceGroups/r/providers/Microsoft.KeyVault/vaults/v9")[0] == "v9")
ck("extract monitor read excluded", O.extract_resource("azure", "keyvault", "GET", "/subscriptions/s/resourceGroups/r/providers/Microsoft.KeyVault/vaults/v9/providers/Microsoft.Insights/metrics")[1] == "MonitorRead")
def js(r):
    return r["body"]
d = js(M.list_metric_definitions(state, rid("Microsoft.KeyVault/vaults", "kv1")))
names = [x["name"]["value"] for x in d["value"]]
ck("defs keep ActivityOperations + real", "ActivityOperations" in names and "ServiceApiHit" in names and "SuccessE2ELatency" in names)
ck("acr offers generic request metrics", "Requests" in [x["name"]["value"] for x in js(M.list_metric_definitions(state, rid("Microsoft.ContainerRegistry/registries", "acr1")))["value"]])
def q(t, n, m, agg="Total", interval="PT1M"):
    res = js(M.get_metrics(state, rid(t, n), {"metricnames": m, "aggregation": agg, "interval": interval, "timespan": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600)) + "/" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 60))}))
    return res["value"][0]["timeseries"][0]["data"]
hits = q("Microsoft.KeyVault/vaults", "kv1", "ServiceApiHit")
ck("kv hits total 11 (monitor read excluded)", sum(p["total"] for p in hits) == 11)
ck("kv errors 3", sum(p["total"] for p in q("Microsoft.KeyVault/vaults", "kv1", "Errors")) == 3)
lat = q("Microsoft.KeyVault/vaults", "kv1", "SuccessE2ELatency", "Average", "PT1H")
ck("kv success latency avg of 2xx only", len(lat) >= 1 and 13 <= lat[0]["average"] <= 15)
av = q("Microsoft.KeyVault/vaults", "kv1", "Availability", "Average", "PT1H")
ck("kv availability < 100 with a 5xx", av and 90 <= av[0]["average"] < 100)
ck("sb success/user errors", sum(p["total"] for p in q("Microsoft.ServiceBus/namespaces", "sb1", "SuccessfulRequests")) == 1 and sum(p["total"] for p in q("Microsoft.ServiceBus/namespaces", "sb1", "UserErrors")) == 1)
ru = q("Microsoft.DocumentDB/databaseAccounts", "cos1", "TotalRequestUnits")
ck("cosmos RU modelled from size, unnamed request attributed to the sole account", ru and ru[0]["total"] == 10.0)
ck("fn 5xx", sum(p["total"] for p in q("Microsoft.Web/sites", "fn1", "Http5xx")) == 1)
ck("idle resource: empty series", q("Microsoft.ContainerRegistry/registries", "acr1", "Requests") == [])
ck("unknown metric 400", M.get_metrics(state, rid("Microsoft.KeyVault/vaults", "kv1"), {"metricnames": "Nope"})["status"] == 400)
ck("ActivityOperations still served", "value" in js(M.get_metrics(state, rid("Microsoft.KeyVault/vaults", "kv1"), {})))
print("FAILED:", F) if F else print("ALL PASS")
raise SystemExit(1 if F else 0)
