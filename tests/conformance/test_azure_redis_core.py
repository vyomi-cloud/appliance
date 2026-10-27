"""Unit tests for core/azure_redis_core.py (run: python3 tests/conformance/test_azure_redis_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_redis_core as rc  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, query=None, rg="rg1"):
    return rc.dispatch(st, method, "sub1", rg, chain, [], body or {}, query or {})


def sku(n="Basic", c=0, f=None):
    return {"name": n, "family": f or ("P" if n == "Premium" else "C"), "capacity": c}


st = {}
r = cp(st, "PUT", ["redis", "cache1"], {"location": "eastus", "tags": {"a": "b"}, "properties": {"sku": sku()}})
p = r["body"]["properties"]
check("create → 201 + LRO, hostName, ports, keys", r["status"] == 201 and r["lro"] and p["hostName"] == "cache1.redis.cache.windows.net"
      and p["sslPort"] == 6380 and p["port"] == 6379 and len(p["accessKeys"]["primaryKey"]) == 44 and r["body"]["type"] == "Microsoft.Cache/Redis", r["body"])
check("computed redisConfiguration (maxclients 256 for C0)", p["redisConfiguration"]["maxclients"] == "256" and p["redisConfiguration"]["maxmemory-policy"] == "volatile-lru")
g = cp(st, "GET", ["redis", "cache1"])
check("get hides access keys, Succeeded", g["status"] == 200 and "accessKeys" not in g["body"]["properties"] and g["body"]["properties"]["provisioningState"] == "Succeeded")
check("get missing → 404 ResourceNotFound", cp(st, "GET", ["redis", "nope"])["body"]["error"]["code"] == "ResourceNotFound")
check("sku required", cp(st, "PUT", ["redis", "c2"], {"location": "eastus", "properties": {}})["status"] == 400)
check("location required", cp(st, "PUT", ["redis", "c2"], {"properties": {"sku": sku()}})["body"]["error"]["code"] == "LocationRequired")
check("bad name (double hyphen) → 400", cp(st, "PUT", ["redis", "a--b"], {"location": "eastus", "properties": {"sku": sku()}})["status"] == 400)
check("Basic capacity 7 → 400", cp(st, "PUT", ["redis", "c3"], {"location": "eastus", "properties": {"sku": sku("Basic", 7)}})["status"] == 400)
check("Premium needs family P, capacity ≥1", cp(st, "PUT", ["redis", "c3"], {"location": "eastus", "properties": {"sku": sku("Premium", 0)}})["status"] == 400
      and cp(st, "PUT", ["redis", "c3"], {"location": "eastus", "properties": {"sku": {"name": "Premium", "family": "C", "capacity": 1}}})["status"] == 400)
check("name is globally unique → 409 in another resource group", cp(st, "PUT", ["redis", "CACHE1"], {"location": "eastus", "properties": {"sku": sku()}}, rg="other")["status"] == 409)
check("shardCount on Basic → 400", cp(st, "PUT", ["redis", "c4"], {"location": "eastus", "properties": {"sku": sku(), "shardCount": 2}})["status"] == 400)
check("unknown redis config → 400", cp(st, "PUT", ["redis", "c4"], {"location": "eastus", "properties": {"sku": sku(), "redisConfiguration": {"bogus": "1"}}})["status"] == 400)
check("invalid eviction policy → 400", cp(st, "PATCH", ["redis", "cache1"], {"properties": {"redisConfiguration": {"maxmemory-policy": "nope"}}})["status"] == 400)
check("rdb backup config needs Premium", cp(st, "PATCH", ["redis", "cache1"], {"properties": {"redisConfiguration": {"rdb-backup-enabled": "true"}}})["status"] == 400)

r = cp(st, "PATCH", ["redis", "cache1"], {"tags": {"c": "d"}, "properties": {"enableNonSslPort": True, "redisConfiguration": {"maxmemory-policy": "allkeys-lru"}}})
check("PATCH updates flags, config and tags", r["status"] == 200 and r["body"]["properties"]["enableNonSslPort"] is True
      and r["body"]["properties"]["redisConfiguration"]["maxmemory-policy"] == "allkeys-lru" and r["body"]["tags"] == {"c": "d"}, r["body"])
r = cp(st, "PATCH", ["redis", "cache1"], {"properties": {"sku": sku("Standard", 1)}})
check("scale Basic C0 → Standard C1", r["status"] == 200 and r["body"]["properties"]["sku"]["capacity"] == 1 and r["body"]["properties"]["redisConfiguration"]["maxclients"] == "1000"
      and r["body"]["properties"]["redisConfiguration"]["maxmemory-policy"] == "allkeys-lru", r["body"])
check("scaling down tier → 400", cp(st, "PATCH", ["redis", "cache1"], {"properties": {"sku": sku("Basic", 1)}})["status"] == 400)
check("scaling down size → 400", cp(st, "PATCH", ["redis", "cache1"], {"properties": {"sku": sku("Standard", 0)}})["status"] == 400)
check("PATCH missing → 404", cp(st, "PATCH", ["redis", "nope"], {"tags": {}})["status"] == 404)

k0 = cp(st, "POST", ["redis", "cache1", "listKeys"])["body"]
k1 = cp(st, "POST", ["redis", "cache1", "regenerateKey"], {"keyType": "Primary"})["body"]
check("regenerateKey changes only the chosen key", k1["primaryKey"] != k0["primaryKey"] and k1["secondaryKey"] == k0["secondaryKey"])
check("regenerateKey bad type → 400", cp(st, "POST", ["redis", "cache1", "regenerateKey"], {"keyType": "x"})["status"] == 400)
check("listKeys persists the regenerated key", cp(st, "POST", ["redis", "cache1", "listKeys"])["body"] == k1)
check("forceReboot → message", "message" in cp(st, "POST", ["redis", "cache1", "forceReboot"], {"rebootType": "AllNodes"})["body"])
check("forceReboot bad type → 400", cp(st, "POST", ["redis", "cache1", "forceReboot"], {"rebootType": "x"})["status"] == 400)
cp(st, "PUT", ["redis", "basic1"], {"location": "eastus", "properties": {"sku": sku()}})
check("Basic: SecondaryNode reboot → 400", cp(st, "POST", ["redis", "basic1", "forceReboot"], {"rebootType": "SecondaryNode"})["status"] == 400)
check("Standard: SecondaryNode reboot → 200", cp(st, "POST", ["redis", "cache1", "forceReboot"], {"rebootType": "SecondaryNode"})["status"] == 200)
cp(st, "DELETE", ["redis", "basic1"])
check("import needs Premium", cp(st, "POST", ["redis", "cache1", "import"], {"files": ["https://x/y.rdb"]})["status"] == 400)

# firewall rules
R = ["redis", "cache1", "firewallRules"]
r = cp(st, "PUT", R + ["office"], {"properties": {"startIP": "10.0.0.1", "endIP": "10.0.0.9"}})
check("firewall rule create → 201", r["status"] == 201 and r["body"]["properties"]["endIP"] == "10.0.0.9" and r["body"]["type"].endswith("/firewallRules"), r["body"])
check("firewall rule update → 200", cp(st, "PUT", R + ["office"], {"properties": {"startIP": "10.0.0.1", "endIP": "10.0.0.20"}})["status"] == 200)
check("firewall rule bad ip → 400", cp(st, "PUT", R + ["x"], {"properties": {"startIP": "zz", "endIP": "10.0.0.20"}})["status"] == 400)
check("firewall rule start > end → 400", cp(st, "PUT", R + ["x"], {"properties": {"startIP": "10.0.0.9", "endIP": "10.0.0.1"}})["status"] == 400)
check("firewall rule list", len(cp(st, "GET", R)["body"]["value"]) == 1 and cp(st, "GET", R + ["office"])["status"] == 200)
check("firewall rule delete → 200 then 204", cp(st, "DELETE", R + ["office"])["status"] == 200 and cp(st, "DELETE", R + ["office"])["status"] == 204)
check("firewall rule get missing → 404", cp(st, "GET", R + ["office"])["status"] == 404)

# premium: patch schedules, shards, import/export, linked servers
r = cp(st, "PUT", ["redis", "prem1"], {"location": "eastus", "zones": ["1"], "properties": {"sku": sku("Premium", 1), "shardCount": 2, "redisConfiguration": {"rdb-backup-enabled": "true", "rdb-backup-frequency": "60"}}})
check("premium create with shards → 2 instances", r["status"] == 201 and len(r["body"]["properties"]["instances"]) == 2 and r["body"]["properties"]["shardCount"] == 2, r["body"])
check("patch schedule needs Premium", cp(st, "PUT", ["redis", "cache1", "patchSchedules", "default"], {"properties": {"scheduleEntries": [{"dayOfWeek": "Monday", "startHourUtc": 3}]}})["status"] == 400)
PS = ["redis", "prem1", "patchSchedules"]
check("patch schedule get before create → 404", cp(st, "GET", PS + ["default"])["status"] == 404)
r = cp(st, "PUT", PS + ["default"], {"properties": {"scheduleEntries": [{"dayOfWeek": "monday", "startHourUtc": 3, "maintenanceWindow": "PT5H"}]}})
check("patch schedule create → 201, day normalised", r["status"] == 201 and r["body"]["properties"]["scheduleEntries"][0]["dayOfWeek"] == "Monday", r["body"])
check("patch schedule bad hour → 400", cp(st, "PUT", PS + ["default"], {"properties": {"scheduleEntries": [{"dayOfWeek": "Monday", "startHourUtc": 30}]}})["status"] == 400)
check("patch schedule name must be default", cp(st, "PUT", PS + ["other"], {"properties": {"scheduleEntries": [{"dayOfWeek": "Monday", "startHourUtc": 1}]}})["status"] == 400)
check("patch schedule delete", cp(st, "DELETE", PS + ["default"])["status"] == 200 and cp(st, "GET", PS + ["default"])["status"] == 404)
r = cp(st, "POST", ["redis", "prem1", "export"], {"format": "RDB", "prefix": "bk", "container": "https://sa.blob.core.windows.net/c"})
check("export → 202 LRO", r["status"] == 202 and r["lro"], r)
check("export needs prefix + container", cp(st, "POST", ["redis", "prem1", "export"], {"format": "RDB"})["status"] == 400)
check("import → 202 LRO", cp(st, "POST", ["redis", "prem1", "import"], {"files": ["https://sa/x.rdb"]})["status"] == 202)
check("import needs files", cp(st, "POST", ["redis", "prem1", "import"], {})["status"] == 400)
check("Premium forceReboot with shardId", cp(st, "POST", ["redis", "prem1", "forceReboot"], {"rebootType": "PrimaryNode", "shardId": 1})["status"] == 200
      and cp(st, "POST", ["redis", "prem1", "forceReboot"], {"rebootType": "PrimaryNode", "shardId": 5})["status"] == 400)

cp(st, "PUT", ["redis", "prem2"], {"location": "westus", "properties": {"sku": sku("Premium", 1)}})
prem2 = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Cache/Redis/prem2"
LS = ["redis", "prem1", "linkedServers"]
r = cp(st, "PUT", LS + ["prem2"], {"properties": {"linkedRedisCacheId": prem2, "linkedRedisCacheLocation": "westus", "serverRole": "Secondary"}})
check("linked server create → 201 LRO, listed on the cache", r["status"] == 201 and r["lro"] and r["body"]["properties"]["serverRole"] == "Secondary"
      and cp(st, "GET", ["redis", "prem1"])["body"]["properties"]["linkedServers"] == [{"id": prem2}], r["body"])
check("linked server name must match cache", cp(st, "PUT", LS + ["zzz"], {"properties": {"linkedRedisCacheId": prem2, "linkedRedisCacheLocation": "westus", "serverRole": "Secondary"}})["status"] == 400)
check("linked server needs Premium", cp(st, "PUT", ["redis", "cache1", "linkedServers", "prem2"], {"properties": {"linkedRedisCacheId": prem2, "linkedRedisCacheLocation": "westus", "serverRole": "Secondary"}})["status"] == 400)
check("linked server list/get", len(cp(st, "GET", LS)["body"]["value"]) == 1 and cp(st, "GET", LS + ["prem2"])["status"] == 200)
check("linked server delete", cp(st, "DELETE", LS + ["prem2"])["status"] == 200 and cp(st, "GET", ["redis", "prem1"])["body"]["properties"]["linkedServers"] == [])

# listing + name check
check("list by resource group", len(cp(st, "GET", ["redis"])["body"]["value"]) == 3)
check("list by subscription", len(cp(st, "GET", ["redis"], rg=None)["body"]["value"]) == 3)
check("other rg lists nothing", cp(st, "GET", ["redis"], rg="zzz")["body"]["value"] == [])
chk = lambda n, t="Microsoft.Cache/Redis": cp(st, "POST", ["checkNameAvailability"], {"type": t, "name": n}, rg=None)
check("checkNameAvailability: free → 200", chk("free-name")["status"] == 200)
check("checkNameAvailability: taken → 409", chk("cache1")["status"] == 409)
check("checkNameAvailability: bad name / type → 400", chk("-x")["status"] == 400 and chk("ok", "Microsoft.Foo/bar")["status"] == 400)
check("connection info (control plane only without Valkey)", cp(st, "GET", ["redis", "cache1", "connectionInfo"])["body"]["dataPlaneHost"] is None)
rc.configure_data_plane("vyomi-valkey", 6379)
ci = cp(st, "GET", ["redis", "cache1", "connectionInfo"])["body"]
check("connection info points at the Valkey container when configured", ci["dataPlaneHost"] == "vyomi-valkey" and "redis-cli -h vyomi-valkey -p 6379" in ci["redisCli"], ci)
rc.configure_data_plane(None)
r = cp(st, "DELETE", ["redis", "cache1"])
check("delete → 200 LRO, then gone, then 204", r["status"] == 200 and r["lro"] and cp(st, "GET", ["redis", "cache1"])["status"] == 404 and cp(st, "DELETE", ["redis", "cache1"])["status"] == 204)

# through the Nano ARM wire
arm = AzureArm()
P = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Cache"
r = arm.handle("PUT", P + "/Redis/nano-cache", {}, {"location": "eastus", "properties": {"sku": sku()}})
check("Nano ARM: cache create (LRO headers)", r["status"] == 201 and "Azure-AsyncOperation" in r["headers"] and r["body"]["name"] == "nano-cache", r)
r = arm.handle("POST", P + "/redis/nano-cache/listKeys", {}, {})
check("Nano ARM: listKeys", r["status"] == 200 and r["body"]["primaryKey"], r)
check("Nano ARM: lowercase type path lists", len(arm.handle("GET", P + "/redis", {}, None)["body"]["value"]) == 1)
r = arm.handle("POST", "/subscriptions/s/providers/Microsoft.Cache/CheckNameAvailability", {}, {"type": "Microsoft.Cache/Redis", "name": "nano-cache"})
check("Nano ARM: checkNameAvailability 409", r["status"] == 409, r)
r = arm.handle("DELETE", P + "/Redis/nano-cache", {}, None)
check("Nano ARM: cache delete", r["status"] == 200 and "Azure-AsyncOperation" in r["headers"], r)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
