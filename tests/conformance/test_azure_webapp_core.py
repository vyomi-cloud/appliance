"""Unit tests for core/azure_webapp_core.py (run: python3 tests/conformance/test_azure_webapp_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_webapp_core as wc  # noqa: E402
from core import azure_monitor_core as mc  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, chain, body=None, rg="rg1"):
    return wc.dispatch(st, method, "sub1", rg, chain, [], body or {})


st = {}

# ── App Service plan ────────────────────────────────────────────────────────
r = call(st, "PUT", ["serverfarms", "plan1"], {"location": "eastus", "sku": {"name": "B1"}, "properties": {"reserved": True}})
plan_id = r["body"]["id"]
check("plan create: 201 + an LRO, Linux kind, Basic tier", r["status"] == 201 and r["lro"]
      and r["body"]["kind"] == "linux" and r["body"]["sku"]["tier"] == "Basic", r["body"])
check("plan numberOfSites starts at 0", call(st, "GET", ["serverfarms", "plan1"])["body"]["properties"]["numberOfSites"] == 0)

# ── Web app create ──────────────────────────────────────────────────────────
SITE = {"location": "eastus", "kind": "app,linux", "properties": {"serverFarmId": plan_id, "siteConfig": {"linuxFxVersion": "PYTHON|3.12"}}}
r = call(st, "PUT", ["sites", "app1"], SITE)
p = r["body"]["properties"]
check("site create: 201 + an LRO, running, default hostname, linux runtime carried through",
      r["status"] == 201 and r["lro"] and p["state"] == "Running" and p["defaultHostName"] == "app1.azurewebsites.net"
      and p["siteConfig"]["linuxFxVersion"] == "PYTHON|3.12", r["body"])
check("plan now reports the site", call(st, "GET", ["serverfarms", "plan1"])["body"]["properties"]["numberOfSites"] == 1)
check("app settings/connection strings never leak onto the site record", "_appsettings" not in r["body"] and "appSettings" not in p)

check("site create without serverFarmId auto-provisions a plan", call(st, "PUT", ["sites", "auto1"], {"location": "eastus"})["status"] == 201
      and call(st, "GET", ["serverfarms", "auto1-plan"])["status"] == 200)
check("site create with an unknown serverFarmId is rejected",
      call(st, "PUT", ["sites", "bad1"], {"location": "eastus", "properties": {"serverFarmId": plan_id + "-nope"}})["body"]["error"]["code"] == "ServerFarmNotFound")

# ── lifecycle actions ────────────────────────────────────────────────────────
check("stop sets state Stopped", call(st, "POST", ["sites", "app1", "stop"])["status"] == 200
      and call(st, "GET", ["sites", "app1"])["body"]["properties"]["state"] == "Stopped")
check("start sets state Running", call(st, "POST", ["sites", "app1", "start"])["status"] == 200
      and call(st, "GET", ["sites", "app1"])["body"]["properties"]["state"] == "Running")
check("restart leaves state Running", call(st, "POST", ["sites", "app1", "restart"])["status"] == 200
      and call(st, "GET", ["sites", "app1"])["body"]["properties"]["state"] == "Running")

# ── config/web, appsettings, connectionstrings, logs ────────────────────────
r = call(st, "PUT", ["sites", "app1", "config", "web"], {"properties": {"alwaysOn": True, "ftpsState": "FtpsOnly"}})
check("config/web PUT merges into siteConfig", r["body"]["properties"]["alwaysOn"] is True
      and call(st, "GET", ["sites", "app1"])["body"]["properties"]["siteConfig"]["ftpsState"] == "FtpsOnly")
r = call(st, "PUT", ["sites", "app1", "config", "appsettings"], {"properties": {"A": "1", "B": "2"}})
check("appsettings PUT replaces the set; GET and POST .../list agree", r["status"] == 200 and r["body"]["properties"] == {"A": "1", "B": "2"}
      and call(st, "GET", ["sites", "app1", "config", "appsettings"])["body"]["properties"] == {"A": "1", "B": "2"}
      and call(st, "POST", ["sites", "app1", "config", "appsettings", "list"])["body"]["properties"] == {"A": "1", "B": "2"})
r = call(st, "PUT", ["sites", "app1", "config", "connectionstrings"], {"properties": {"Db": {"value": "Server=x", "type": "SQLAzure"}}})
check("connectionstrings round-trip", call(st, "GET", ["sites", "app1", "config", "connectionstrings"])["body"]["properties"]["Db"]["value"] == "Server=x")
r = call(st, "PUT", ["sites", "app1", "config", "logs"], {"properties": {"applicationLogs": {"fileSystem": {"level": "Warning"}}}})
check("app service logs config merges", r["body"]["properties"]["applicationLogs"]["fileSystem"]["level"] == "Warning"
      and r["body"]["properties"]["httpLogs"]["fileSystem"]["retentionInMb"] == 35)

# ── deployment slots + swap ──────────────────────────────────────────────────
r = call(st, "PUT", ["sites", "app1", "slots", "staging"], {})
check("slot create: 201, own hostname, inherits prod config", r["status"] == 201
      and r["body"]["properties"]["defaultHostName"] == "app1-staging.azurewebsites.net"
      and r["body"]["properties"]["siteConfig"]["ftpsState"] == "FtpsOnly")
slot_before = call(st, "GET", ["sites", "app1", "slots", "staging"])["body"]["properties"]["siteConfig"]["ftpsState"]
call(st, "PUT", ["sites", "app1", "config", "appsettings"], {"properties": {"ENV": "prod"}})
r = call(st, "POST", ["sites", "app1", "slotsswap"], {"targetSlot": "staging"})
check("slotsswap exchanges app settings between production and the slot", r["status"] == 200
      and call(st, "GET", ["sites", "app1", "config", "appsettings"])["body"]["properties"] == {}
      and call(st, "GET", ["sites", "app1", "slots", "staging"])["body"]["properties"]["siteConfig"]["ftpsState"] == slot_before)
check("swap to an unknown slot 404s", call(st, "POST", ["sites", "app1", "slotsswap"], {"targetSlot": "nope"})["body"]["error"]["code"] == "SlotNotFound")
check("slot list shows the slot", len(call(st, "GET", ["sites", "app1", "slots"])["body"]["value"]) == 1)
check("slot delete", call(st, "DELETE", ["sites", "app1", "slots", "staging"])["status"] == 200
      and call(st, "GET", ["sites", "app1", "slots"])["body"]["value"] == [])

# ── custom domains (hostNameBindings) ────────────────────────────────────────
r = call(st, "PUT", ["sites", "app1", "hostNameBindings", "www.example.com"], {})
check("custom domain create is reflected on the site's hostNames", r["status"] == 201
      and "www.example.com" in call(st, "GET", ["sites", "app1"])["body"]["properties"]["hostNames"])
check("custom domain delete removes it", call(st, "DELETE", ["sites", "app1", "hostNameBindings", "www.example.com"])["status"] == 200
      and "www.example.com" not in call(st, "GET", ["sites", "app1"])["body"]["properties"]["hostNames"])

# ── locks ─────────────────────────────────────────────────────────────────────
r = call(st, "PUT", ["sites", "app1", "providers", "Microsoft.Authorization", "locks", "freeze"], {"properties": {"level": "CanNotDelete", "notes": "do not delete"}})
check("lock create", r["status"] == 201 and r["body"]["properties"]["level"] == "CanNotDelete")
check("bad lock level rejected", call(st, "PUT", ["sites", "app1", "providers", "Microsoft.Authorization", "locks", "bad"], {"properties": {"level": "Nope"}})["status"] == 400)
check("lock list", len(call(st, "GET", ["sites", "app1", "providers", "Microsoft.Authorization", "locks"])["body"]["value"]) == 1)
check("lock delete", call(st, "DELETE", ["sites", "app1", "providers", "Microsoft.Authorization", "locks", "freeze"])["status"] == 200)

# ── tags (generic PATCH) ─────────────────────────────────────────────────────
r = call(st, "PATCH", ["sites", "app1"], {"tags": {"env": "prod"}})
check("tags PATCH", r["status"] == 200 and r["body"]["tags"] == {"env": "prod"})

# ── delete + plan-in-use guard ────────────────────────────────────────────────
check("deleting a plan still in use is refused", call(st, "DELETE", ["serverfarms", "plan1"])["body"]["error"]["code"] == "ServerFarmInUse")
check("site delete", call(st, "DELETE", ["sites", "app1"])["status"] == 200
      and call(st, "GET", ["sites", "app1"])["body"]["error"]["code"] == "ResourceNotFound")
check("plan delete now succeeds", call(st, "DELETE", ["serverfarms", "plan1"])["status"] == 200)

# ── invalid name / unsupported type ──────────────────────────────────────────
check("invalid site name rejected", call(st, "PUT", ["sites", "-bad-"], {"location": "eastus"})["body"]["error"]["code"] == "InvalidResourceName")
check("unsupported top-level type", call(st, "GET", ["notathing"])["body"]["error"]["code"] == "ResourceTypeNotSupported")

# ── Activity log (Microsoft.Insights/eventtypes, read back through the monitor engine) ──────
st2 = {}
call(st2, "PUT", ["serverfarms", "plan2"], {"location": "eastus", "sku": {"name": "B1"}})
call(st2, "PUT", ["sites", "app2"], {"location": "eastus", "properties": {"serverFarmId": f"/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/serverfarms/plan2"}})
call(st2, "POST", ["sites", "app2", "stop"])
call(st2, "PUT", ["sites", "app2", "hostNameBindings", "live.example.com"])
site_id = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/sites/app2"
feed = mc.dispatch(st2, "GET", "sub1", None, ["eventtypes", "management", "values"], [], {},
                    {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{site_id}'"})
ops = [e["operationName"]["localizedValue"] for e in feed["body"]["value"]]
check("activity log records create + stop + custom-domain events for the site",
      feed["status"] == 200 and len(ops) == 3
      and any("live.example.com" in o for o in ops) and any("Stop" in o for o in ops) and any("Create Web App" in o for o in ops), ops)
other_feed = mc.dispatch(st2, "GET", "sub1", None, ["eventtypes", "management", "values"], [], {},
                          {"api-version": "2015-04-01", "$filter": "resourceUri eq '/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/sites/nope'"})
check("activity log filters strictly by resourceUri", other_feed["body"]["value"] == [])

# ── one engine, both kinds (web apps + function apps share Microsoft.Web/sites) ──────────
st3 = {}
call(st3, "PUT", ["serverfarms", "p3"], {"location": "eastus", "sku": {"name": "B1"}})
call(st3, "PUT", ["sites", "web3"], {"location": "eastus", "kind": "app", "properties": {
    "serverFarmId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/serverfarms/p3"}})
call(st3, "PUT", ["sites", "fn3"], {"location": "eastus", "kind": "functionapp", "properties": {"reserved": True}})
kinds = sorted(s["kind"] for s in call(st3, "GET", ["sites"])["body"]["value"])
check("sites list returns BOTH kinds (blades filter by kind)", kinds == ["app", "functionapp"], kinds)
check("function app gets functions defaults (FUNCTIONS_* settings, host keys)",
      "FUNCTIONS_WORKER_RUNTIME" in call(st3, "GET", ["sites", "fn3", "config", "appsettings"])["body"]["properties"]
      and bool(call(st3, "POST", ["sites", "fn3", "host", "default", "listkeys"])["body"]["masterKey"]))
check("function app lands on an auto-provisioned plan that exists",
      call(st3, "GET", ["serverfarms", call(st3, "GET", ["sites", "fn3"])["body"]["properties"]["serverFarmId"].rsplit("/", 1)[-1]])["status"] == 200)
check("web app has no Functions sub-resources", call(st3, "GET", ["sites", "web3", "functions"])["body"]["error"]["code"] == "ResourceTypeNotSupported")
check("function app has no deployment slots", call(st3, "PUT", ["sites", "fn3", "slots", "s1"], {})["body"]["error"]["code"] == "ResourceTypeNotSupported")
check("web app has no FUNCTIONS_* settings", call(st3, "GET", ["sites", "web3", "config", "appsettings"])["body"]["properties"] == {})
call(st3, "PUT", ["sites", "fn3", "locks", "short"], {"properties": {"level": "ReadOnly"}})
native = call(st3, "GET", ["sites", "fn3", "providers", "Microsoft.Authorization", "locks"])["body"]["value"]
check("legacy locks/{n} path and the native Microsoft.Authorization/locks path share ONE store",
      [l["name"] for l in native] == ["short"] and native[0]["type"] == "Microsoft.Authorization/locks", native)
r = call(st3, "PUT", ["sites", "fn3"], {"location": "westus", "kind": "app"})
check("PUT on an existing site never flips its kind", r["status"] == 200 and r["body"]["kind"] == "functionapp")
fn_feed = mc.dispatch(st3, "GET", "sub1", None, ["eventtypes", "management", "values"], [], {},
                      {"$filter": "resourceUri eq '/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/sites/fn3'"})["body"]["value"]
check("function app writes land on the same Activity log feed, newest first, labelled by kind",
      fn_feed[0]["operationName"]["localizedValue"] == "Update Function App 'fn3'"
      and fn_feed[1]["operationName"]["value"] == "Microsoft.Web/sites/locks/short/write", [e["operationName"] for e in fn_feed])
check("plan-in-use guard counts both kinds", call(st3, "DELETE", ["serverfarms", "p3"])["body"]["error"]["code"] == "ServerFarmInUse")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
