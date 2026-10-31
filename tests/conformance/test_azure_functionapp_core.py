"""Unit tests for core/azure_webapp_core.py (run: python3 tests/conformance/test_azure_functionapp_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_webapp_core as wc  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, chain, body=None, rg="rg1"):
    return wc.dispatch(st, method, "sub1", rg, chain, [], body or {})


SITE = {"location": "eastus", "kind": "functionapp", "properties": {"reserved": True, "siteConfig": {"_runtime": "Python", "_version": "3.12"}}}

st = {}
r = call(st, "PUT", ["sites", "fn1"], SITE)
p = r["body"]["properties"]
check("create returns 201 + an LRO, a default hostname and seeded app settings",
      r["status"] == 201 and r["lro"] and p["defaultHostName"] == "fn1.azurewebsites.net"
      and p["siteConfig"]["linuxFxVersion"] == "PYTHON|3.12", r["body"])
check("app settings seeded (listed via config/appsettings)",
      "FUNCTIONS_EXTENSION_VERSION" in call(st, "POST", ["sites", "fn1", "config", "appsettings"])["body"]["properties"])
check("invalid name rejected", call(st, "PUT", ["sites", "_bad_"], SITE)["body"]["error"]["code"] == "BadRequest")
check("404 shape", call(st, "GET", ["sites", "zzz"])["body"]["error"]["code"] == "ResourceNotFound")

# app settings / connection strings round-trip (PUT replaces the whole set)
r = call(st, "PUT", ["sites", "fn1", "config", "appsettings"], {"properties": {"A": "1", "B": "2"}})
check("appsettings PUT replaces the set", r["body"]["properties"] == {"A": "1", "B": "2"})
r = call(st, "PUT", ["sites", "fn1", "config", "connectionstrings"], {"properties": {"Sql": {"value": "server=x", "type": "SQLAzure"}}})
check("connection strings PUT round-trips", call(st, "POST", ["sites", "fn1", "config", "connectionstrings"])["body"]["properties"]["Sql"]["type"] == "SQLAzure")

# host keys
hk = call(st, "POST", ["sites", "fn1", "host", "default", "listkeys"])["body"]
check("host listKeys returns a masterKey + default function key", bool(hk["masterKey"]) and "default" in hk["functionKeys"], hk)
nk = call(st, "PUT", ["sites", "fn1", "host", "default", "functionkeys", "extra"])["body"]
check("new host function key created", "extra" in call(st, "POST", ["sites", "fn1", "host", "default", "listkeys"])["body"]["functionKeys"], nk)
check("host key deleted", call(st, "DELETE", ["sites", "fn1", "host", "default", "functionkeys", "extra"])["status"] == 200)

# functions: create, invoke (real sandboxed exec), keys, delete
FN = {"properties": {"entryPoint": "main", "files": {"__init__.py": "def main(req):\n    return {'doubled': req['body']['n'] * 2}\n"},
                     "config": {"bindings": [{"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["post"]}]}}}
r = call(st, "PUT", ["sites", "fn1", "functions", "double"], FN)
check("function created", r["status"] == 201 and r["body"]["properties"]["trigger"] == "httpTrigger", r["body"])
inv = call(st, "POST", ["sites", "fn1", "functions", "double", "invoke"], {"body": {"n": 21}})
check("function invoke runs the REAL code", inv["body"]["ok"] is True and inv["body"]["body"] == {"doubled": 42}, inv["body"])
BAD_FN = {"properties": {"files": {"__init__.py": "def main(req):\n    import os\n    return os.getcwd()\n"}}}
call(st, "PUT", ["sites", "fn1", "functions", "escape"], BAD_FN)
esc = call(st, "POST", ["sites", "fn1", "functions", "escape", "invoke"], {})
check("sandbox blocks disallowed imports", esc["body"]["ok"] is False and "ImportError" in esc["body"]["error"], esc["body"])
fk = call(st, "POST", ["sites", "fn1", "functions", "double", "listkeys"])["body"]
check("function-level default key", bool(fk.get("default")))
check("function deleted", call(st, "DELETE", ["sites", "fn1", "functions", "double"])["status"] == 200
      and call(st, "GET", ["sites", "fn1", "functions", "double"])["status"] == 404)

# locks
lk = call(st, "PUT", ["sites", "fn1", "locks", "no-delete"], {"properties": {"level": "CanNotDelete", "notes": "protect"}})
check("lock created", lk["body"]["properties"]["level"] == "CanNotDelete")
check("bad lock level rejected", call(st, "PUT", ["sites", "fn1", "locks", "x"], {"properties": {"level": "Nope"}})["status"] == 400)
check("locks listed", len(call(st, "GET", ["sites", "fn1", "locks"])["body"]["value"]) == 1)

# lock ENFORCEMENT: a CanNotDelete lock blocks delete but not writes; a ReadOnly lock blocks both
blocked_del = call(st, "DELETE", ["sites", "fn1"])
check("CanNotDelete lock blocks site delete", blocked_del["status"] == 409 and blocked_del["body"]["error"]["code"] == "ScopeLocked", blocked_del["body"])
ok_write = call(st, "PATCH", ["sites", "fn1"], {"tags": {"env": "prod"}})
check("CanNotDelete lock does not block a write", ok_write["status"] == 200 and ok_write["body"]["tags"]["env"] == "prod", ok_write["body"])
call(st, "PUT", ["sites", "fn1", "locks", "ro"], {"properties": {"level": "ReadOnly"}})
blocked_write = call(st, "PATCH", ["sites", "fn1"], {"tags": {"env": "blocked"}})
check("ReadOnly lock blocks a write too", blocked_write["status"] == 409 and blocked_write["body"]["error"]["code"] == "ScopeLocked", blocked_write["body"])
check("lock deleted", call(st, "DELETE", ["sites", "fn1", "locks", "no-delete"])["status"] == 200)
check("delete still blocked by the remaining ReadOnly lock", call(st, "DELETE", ["sites", "fn1"])["status"] == 409)
check("lock deleted (ReadOnly)", call(st, "DELETE", ["sites", "fn1", "locks", "ro"])["status"] == 200)
check("delete now succeeds once both locks are removed", call(st, "DELETE", ["sites", "fn1"])["status"] == 200)
# recreate fn1 — the rest of the suite (stop/start/publish/scale/delete) expects it to exist
call(st, "PUT", ["sites", "fn1"], SITE)

# start/stop/restart + publish profile
check("stop → state Stopped", call(st, "POST", ["sites", "fn1", "stop"])["status"] == 200
      and call(st, "GET", ["sites", "fn1"])["body"]["properties"]["state"] == "Stopped")
check("start → state Running", call(st, "POST", ["sites", "fn1", "start"])["status"] == 200
      and call(st, "GET", ["sites", "fn1"])["body"]["properties"]["state"] == "Running")
pub = call(st, "POST", ["sites", "fn1", "publishxml"])["body"]
check("publish profile contains the default hostname", "fn1.azurewebsites.net" in pub["value"], pub)

# scale and concurrency: a positive capacity round-trips (config_only); a capacity of
# exactly zero (maximumInstanceCount x perInstanceConcurrency) is ENFORCED against invoke.
r = call(st, "PATCH", ["sites", "fn1"], {"properties": {"functionAppConfig": {"scaleAndConcurrency": {"instanceMemoryMB": 4096, "maximumInstanceCount": 50}}}})
check("scale and concurrency PATCH round-trips", r["body"]["properties"]["functionAppConfig"]["scaleAndConcurrency"]["instanceMemoryMB"] == 4096, r["body"])
call(st, "PUT", ["sites", "fn1", "functions", "echo"], {"properties": {"files": {"__init__.py": "def main(req):\n    return {'ok': True}\n"}}})
live = call(st, "POST", ["sites", "fn1", "functions", "echo", "invoke"], {})
check("positive capacity never throttles (Vyomi invokes synchronously; nothing to run concurrently)", live["body"]["ok"] is True, live["body"])
call(st, "PATCH", ["sites", "fn1"], {"properties": {"functionAppConfig": {"scaleAndConcurrency": {"maximumInstanceCount": 0}}}})
zero = call(st, "POST", ["sites", "fn1", "functions", "echo", "invoke"], {})
check("scaled-to-zero capacity IS enforced: invoke throttled 429 FunctionsTooBusy",
      zero["body"]["ok"] is False and zero["body"]["status"] == 429, zero["body"])
call(st, "PATCH", ["sites", "fn1"], {"properties": {"functionAppConfig": {"scaleAndConcurrency": {"maximumInstanceCount": 50}}}})

check("subscription-scope list", len(wc.dispatch(st, "GET", "sub1", None, ["sites"], [])["body"]["value"]) == 1)
check("delete", call(st, "DELETE", ["sites", "fn1"])["status"] == 200 and call(st, "DELETE", ["sites", "zzz"])["status"] == 204)

# the Nano ARM class delegates to the same engine and keeps its map in the public `state`
arm = AzureArm()
base = "/subscriptions/s/resourceGroups/g/providers/Microsoft.Web"
r = arm.handle("PUT", base + "/sites/site1", {"api-version": "2023-12-01"}, SITE)
check("AzureArm (Nano) serves Microsoft.Web with LRO headers and public state",
      r["status"] == 200 and "Azure-AsyncOperation" in r["headers"] and any("microsoft.web/sites" in k for k in arm.state), r)
j = arm.handle("GET", base + "/sites/nope", {}, {})
check("AzureArm: unknown site → 404", j["status"] == 404)

# Activity log: Microsoft.Web mutations (site + sub-resource) land on the subscription-scoped
# Microsoft.Insights/eventtypes/management/values feed, filtered by resourceUri.
arm.handle("PUT", base + "/sites/site1/locks/lock1", {"api-version": "2023-12-01"}, {"properties": {"level": "ReadOnly"}})
site_rid = f"/subscriptions/s/resourceGroups/g/providers/Microsoft.Web/sites/site1"
events_path = "/subscriptions/s/providers/Microsoft.Insights/eventtypes/management/values"
ev = arm.handle("GET", events_path, {"api-version": "2015-04-01", "$filter": f"resourceUri eq '{site_rid}'"}, {})
ops = [e["operationName"]["value"] for e in ev["body"]["value"]]
check("activity log records the site create + the lock write, newest first",
      ev["status"] == 200 and ops[0] == "Microsoft.Web/sites/locks/lock1/write" and "Microsoft.Web/sites/write" in ops, ev["body"])
other = arm.handle("GET", events_path, {"api-version": "2015-04-01", "$filter": "resourceUri eq '/subscriptions/s/resourceGroups/g/providers/Microsoft.Web/sites/nope'"}, {})
check("activity log is scoped per resource (no cross-resource leakage)", other["body"]["value"] == [])

print(f"\n{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
