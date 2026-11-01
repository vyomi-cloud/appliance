"""Unit tests for core/azure_appconfiguration_core.py (run: python3 tests/conformance/test_azure_appconfiguration_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_appconfiguration_core as ac  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1"):
    return ac.dispatch(st, method, "sub1", rg, chain, [], body or {})


def dp(st, store, method, path, query=None, body=None, headers=None):
    return ac.data_dispatch(st, store, method, path, query or {}, headers or {}, body, base="http://x/azure-data/appconfig/" + store)


st = {}
r = cp(st, "PUT", ["configurationStores", "cfg-one"], {"location": "eastus", "sku": {"name": "Standard"}})
p = r["body"]["properties"]
check("create → 201 + LRO, endpoint, soft delete defaults", r["status"] == 201 and r["lro"] and p["endpoint"] == "https://cfg-one.azconfig.io"
      and p["softDeleteRetentionInDays"] == 7 and r["body"]["sku"]["name"] == "Standard", r["body"])
check("name rules", cp(st, "PUT", ["configurationStores", "ab"], {"location": "eastus"})["body"]["error"]["code"] == "InvalidParameter")
check("name conflict across groups", cp(st, "PUT", ["configurationStores", "cfg-one"], {"location": "eastus"}, rg="rg2")["status"] == 409)
check("missing location", cp(st, "PUT", ["configurationStores", "cfg-two"], {})["status"] == 400)
check("bad sku", cp(st, "PUT", ["configurationStores", "cfg-two"], {"location": "eastus", "sku": {"name": "Gold"}})["body"]["error"]["code"] == "InvalidSku")
r = cp(st, "PATCH", ["configurationStores", "cfg-one"], {"tags": {"a": "b"}, "properties": {"disableLocalAuth": True}})
check("PATCH updates tags + disableLocalAuth", r["body"]["tags"] == {"a": "b"} and r["body"]["properties"]["disableLocalAuth"] is True, r["body"])
check("listKeys refused when local auth disabled", cp(st, "POST", ["configurationStores", "cfg-one", "listKeys"])["status"] == 400)
cp(st, "PATCH", ["configurationStores", "cfg-one"], {"properties": {"disableLocalAuth": False}})
keys = cp(st, "POST", ["configurationStores", "cfg-one", "listKeys"])["body"]["value"]
check("4 keys with connection strings", len(keys) == 4 and keys[0]["connectionString"].startswith("Endpoint=https://cfg-one.azconfig.io;Id=")
      and [k["readOnly"] for k in keys] == [False, False, True, True])
old = keys[0]["value"]
nk = cp(st, "POST", ["configurationStores", "cfg-one", "regenerateKey"], {"id": keys[0]["id"]})["body"]
check("regenerateKey rotates the secret", nk["value"] != old and nk["id"] == keys[0]["id"])
check("list by rg / subscription", len(cp(st, "GET", ["configurationStores"])["body"]["value"]) == 1
      and len(cp(st, "GET", ["configurationStores"], rg=None)["body"]["value"]) == 1)
check("checkNameAvailability", cp(st, "POST", ["checkNameAvailability"], {"name": "cfg-one", "type": "Microsoft.AppConfiguration/configurationStores"}, rg=None)["body"]["nameAvailable"] is False
      and cp(st, "POST", ["checkNameAvailability"], {"name": "cfg-free-1"}, rg=None)["body"]["nameAvailable"] is True)

# data plane
S = "cfg-one"
r = dp(st, S, "PUT", "/kv/app:color", {"label": "dev"}, {"value": "blue", "content_type": "text/plain", "tags": {"t": "1"}})
kv = r["body"]
check("PUT /kv returns the setting + ETag", r["status"] == 200 and kv["value"] == "blue" and kv["label"] == "dev" and kv["locked"] is False
      and r["headers"]["ETag"].strip('"') == kv["etag"], r)
check("GET /kv/{key}?label", dp(st, S, "GET", "/kv/app:color", {"label": "dev"})["body"]["value"] == "blue")
check("GET missing → 404 problem", dp(st, S, "GET", "/kv/app:color")["status"] == 404)
dp(st, S, "PUT", "/kv/app:color", {}, {"value": "red"})
dp(st, S, "PUT", "/kv/app:size", {"label": "dev"}, {"value": "L"})
dp(st, S, "PUT", "/kv/other", {}, {"value": "x"})
lst = lambda q, h=None: dp(st, S, "GET", "/kv", q, headers=h)["body"]["items"]
check("list key prefix", [i["key"] for i in lst({"key": "app:*"})] == ["app:color", "app:color", "app:size"])
check("list label filter / null label", [i["key"] for i in lst({"label": "dev"})] == ["app:color", "app:size"]
      and [i["key"] for i in lst({"label": "\0"})] == ["app:color", "other"])
check("$Select", set(lst({"key": "other", "$Select": "key,value"})[0]) == {"key", "value"})
check("key contains / comma list", [i["key"] for i in lst({"key": "*olo*"})] == ["app:color", "app:color"]
      and len(lst({"key": "other,app:size"})) == 2)
e = dp(st, S, "GET", "/kv/other")["body"]["etag"]
check("If-Match mismatch → 412", dp(st, S, "PUT", "/kv/other", {}, {"value": "y"}, {"if-match": '"nope"'})["status"] == 412)
check("If-Match match → 200", dp(st, S, "PUT", "/kv/other", {}, {"value": "y"}, {"if-match": f'"{e}"'})["status"] == 200)
check("If-None-Match * on existing → 412", dp(st, S, "PUT", "/kv/other", {}, {"value": "z"}, {"if-none-match": "*"})["status"] == 412)
check("lock blocks writes with key-locked", dp(st, S, "PUT", "/locks/other")["body"]["locked"] is True
      and dp(st, S, "PUT", "/kv/other", {}, {"value": "q"})["body"]["type"].endswith("key-locked")
      and dp(st, S, "DELETE", "/kv/other")["status"] == 409)
check("unlock", dp(st, S, "DELETE", "/locks/other")["body"]["locked"] is False and dp(st, S, "PUT", "/kv/other", {}, {"value": "q"})["status"] == 200)
check("keys / labels", [i["name"] for i in dp(st, S, "GET", "/keys")["body"]["items"]] == ["app:color", "app:size", "other"]
      and [i["name"] for i in dp(st, S, "GET", "/labels")["body"]["items"]] == ["dev"])
revs = dp(st, S, "GET", "/revisions", {"key": "other"})["body"]["items"]
check("revisions keep history newest first", len(revs) >= 4 and revs[0]["value"] == "q", revs)
snap = dp(st, S, "PUT", "/snapshots/s1", {}, {"filters": [{"key": "app:*"}], "composition_type": "key_label"})
check("snapshot create → 201 + Operation-Location", snap["status"] == 201 and "Operation-Location" in snap["headers"], snap)
check("operation poll", dp(st, S, "GET", "/operations", {"snapshot": "s1"})["body"]["status"] == "Succeeded")
dp(st, S, "PUT", "/kv/app:late", {}, {"value": "after"})
sn = dp(st, S, "GET", "/snapshots/s1")["body"]
check("snapshot is frozen + ready", sn["status"] == "ready" and sn["items_count"] == 3
      and "app:late" not in [i["key"] for i in lst({"snapshot": "s1"})], sn)
check("snapshot archive/recover", dp(st, S, "PATCH", "/snapshots/s1", {}, {"status": "archived"})["body"]["status"] == "archived"
      and dp(st, S, "PATCH", "/snapshots/s1", {}, {"status": "ready"})["body"]["status"] == "ready")
check("duplicate snapshot → 409", dp(st, S, "PUT", "/snapshots/s1", {}, {"filters": [{"key": "*"}]})["status"] == 409)
dp(st, S, "PUT", "/kv/tagged", {}, {"value": "t", "tags": {"env": "prod", "tier": "a"}})
check("tags filter (repeatable, AND)", [i["key"] for i in lst({"tags": ["env=prod", "tier=a"]})] == ["tagged"]
      and lst({"tags": "env=dev"}) == [])
for i in range(120):
    dp(st, S, "PUT", f"/kv/bulk/{i:03d}", {}, {"value": str(i)})
page = dp(st, S, "GET", "/kv", {"key": "bulk/*"})["body"]
check("paging: 100 items + @nextLink", len(page["items"]) == 100 and "@nextLink" in page, list(page))
nxt = page["@nextLink"].split("after=")[1]
check("paging: second page", len(dp(st, S, "GET", "/kv", {"key": "bulk/*", "after": nxt})["body"]["items"]) == 20)
check("DELETE returns the deleted setting; 204 when absent", dp(st, S, "DELETE", "/kv/bulk/001")["body"]["value"] == "1"
      and dp(st, S, "DELETE", "/kv/bulk/001")["status"] == 204)
check("unknown store → 404", dp(st, "nope", "GET", "/kv")["status"] == 404)
check("HMAC refused when local auth is disabled", (cp(st, "PATCH", ["configurationStores", S], {"properties": {"disableLocalAuth": True}}),
      dp(st, S, "GET", "/kv", headers={"Authorization": "HMAC-SHA256 Credential=x"}))[1]["status"] == 403)
cp(st, "PATCH", ["configurationStores", S], {"properties": {"disableLocalAuth": False}})

# ARM view of the same data
kvs = cp(st, "GET", ["configurationStores", S, "keyValues"])["body"]["value"]
check("ARM keyValues mirrors the data plane", any(v["name"] == "app:color$dev" and v["properties"]["value"] == "blue" for v in kvs), kvs[:2])
cp(st, "PUT", ["configurationStores", S, "keyValues", "arm:key"], {"properties": {"value": "v1", "contentType": "text/plain"}})
check("ARM PUT visible on the data plane", dp(st, S, "GET", "/kv/arm:key")["body"]["value"] == "v1")
check("listKeyValue", cp(st, "POST", ["configurationStores", S, "listKeyValue"], {"key": "arm:key"})["body"]["value"] == "v1")

# soft delete → recover / purge
cp(st, "DELETE", ["configurationStores", S])
check("soft-deleted listing", [x["name"] for x in cp(st, "GET", ["locations", "eastus", "deletedConfigurationStores"], rg=None)["body"]["value"]] == [S])
check("name stays reserved", cp(st, "PUT", ["configurationStores", S], {"location": "eastus"})["status"] == 409)
r = cp(st, "PUT", ["configurationStores", S], {"location": "eastus", "properties": {"createMode": "Recover"}})
check("recover brings the key-values back", r["status"] == 201 and dp(st, S, "GET", "/kv/arm:key")["body"]["value"] == "v1")
cp(st, "DELETE", ["configurationStores", S])
check("purge", cp(st, "POST", ["locations", "eastus", "deletedConfigurationStores", S, "purge"], rg=None)["status"] == 200
      and cp(st, "GET", ["locations", "eastus", "deletedConfigurationStores"], rg=None)["body"]["value"] == [])
cp(st, "PUT", ["configurationStores", "free-store"], {"location": "eastus", "sku": {"name": "Free"}})
cp(st, "DELETE", ["configurationStores", "free-store"])
check("Free tier deletes immediately", cp(st, "GET", ["locations", "eastus", "deletedConfigurationStores"], rg=None)["body"]["value"] == [])

# replicas (Geo-replication)
cp(st, "PUT", ["configurationStores", "cfg-repl"], {"location": "eastus", "sku": {"name": "Standard"}})
r = cp(st, "PUT", ["configurationStores", "cfg-repl", "replicas", "euro"], {"location": "westeurope"})
check("replica create → 201 + LRO + endpoint", r["status"] == 201 and r["lro"]
      and r["body"]["properties"]["endpoint"] == "https://cfg-repl-euro.westeurope.azconfig.io", r["body"])
reps = cp(st, "GET", ["configurationStores", "cfg-repl", "replicas"])["body"]["value"]
check("replica list shows it", len(reps) == 1 and reps[0]["name"] == "euro")
check("replica get", cp(st, "GET", ["configurationStores", "cfg-repl", "replicas", "euro"])["body"]["location"] == "westeurope")
check("replica delete", cp(st, "DELETE", ["configurationStores", "cfg-repl", "replicas", "euro"])["status"] == 200
      and cp(st, "GET", ["configurationStores", "cfg-repl", "replicas"])["body"]["value"] == [])
cp(st, "PUT", ["configurationStores", "cfg-repl-free"], {"location": "eastus", "sku": {"name": "Free"}})
check("replicas require Standard/Premium", cp(st, "PUT", ["configurationStores", "cfg-repl-free", "replicas", "euro"], {"location": "westeurope"})["body"]["error"]["code"] == "ReplicaNotSupported")

# through the Nano ARM dispatcher
arm = AzureArm()
rid = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.AppConfiguration/configurationStores/nano-cfg"
r = arm.handle("PUT", rid, {"api-version": "2024-05-01"}, {"location": "eastus", "sku": {"name": "Standard"}})
check("Nano ARM: create store with LRO header", r["status"] == 200 and "Azure-AsyncOperation" in r["headers"] and r["body"]["name"] == "nano-cfg", r)
r = arm.handle("PUT", rid + "/keyValues/k1$prod", {}, {"properties": {"value": "v"}})
check("Nano ARM: keyValues PUT/GET", arm.handle("GET", rid + "/keyValues/k1$prod")["body"]["properties"]["value"] == "v")
check("Nano ARM: state persists via the public map", rid.lower() in arm.state)
print(f"\n{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
