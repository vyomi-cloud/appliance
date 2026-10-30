"""Unit tests for core/azure_app_core.py (run: python3 tests/conformance/test_azure_app_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_app_core as ac  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, chain, body=None, rg="rg1"):
    return ac.dispatch(st, method, "sub1", rg, chain, [], body or {})


APP = {"location": "eastus", "properties": {
    "configuration": {"ingress": {"external": True, "targetPort": 80}, "secrets": [{"name": "k", "value": "v"}]},
    "template": {"containers": [{"name": "web", "image": "nginx", "env": [{"name": "A", "secretRef": "k"}]}]}}}

st = {}
r = call(st, "PUT", ["containerApps", "web"], APP)
p = r["body"]["properties"]
check("create returns 201 + an LRO with a latest revision, fqdn and an auto-created environment",
      r["status"] == 201 and r["lro"] and p["latestRevisionName"].startswith("web--") and p["configuration"]["ingress"]["fqdn"].startswith("web.")
      and p["managedEnvironmentId"].endswith("/managedEnvironments/cae-rg1"), r["body"])
check("secret values never leave the GET", call(st, "GET", ["containerApps", "web"])["body"]["properties"]["configuration"]["secrets"] == [{"name": "k"}])
check("listSecrets returns them", call(st, "POST", ["containerApps", "web", "listSecrets"])["body"]["value"] == [{"name": "k", "value": "v"}])
rev1 = p["latestRevisionName"]

APP2 = {"location": "eastus", "properties": {"configuration": {"activeRevisionsMode": "Single", "secrets": [{"name": "k", "value": "v"}]},
                                                  "template": {"containers": [{"name": "web", "image": "nginx:1.27"}]}}}
r = call(st, "PUT", ["containerApps", "web"], APP2)
revs = call(st, "GET", ["containerApps", "web", "revisions"])["body"]["value"]
check("new template → new revision; Single mode leaves only the latest active",
      r["status"] == 200 and r["body"]["properties"]["latestRevisionName"] != rev1
      and [x["properties"]["active"] for x in revs if x["name"] == rev1] == [False], revs)
check("same template does not create a revision", call(st, "PUT", ["containerApps", "web"], APP2)["status"] == 200
      and len(call(st, "GET", ["containerApps", "web", "revisions"])["body"]["value"]) == 2)
check("deactivate is refused in Single mode", call(st, "POST", ["containerApps", "web", "revisions", rev1, "deactivate"])["status"] == 400)

for bad, code in (({"properties": {"template": {"containers": [{"image": "x", "resources": {"cpu": 0.5, "memory": "3Gi"}}]}}}, "ContainerAppInvalidResourceTotal"),
                  ({"properties": {"template": {"containers": [{"image": "x", "resources": {"cpu": 9}}]}}}, "InvalidParameterValueInContainerTemplate"),
                  ({"properties": {"template": {"containers": []}}}, "ContainerAppInvalidTemplate"),
                  ({"properties": {"managedEnvironmentId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.App/managedEnvironments/nope",
                                   "template": {"containers": [{"image": "x"}]}}}, "ManagedEnvironmentNotFound"),
                  ({"properties": {"configuration": {"ingress": {"targetPort": 80, "traffic": [{"latestRevision": True, "weight": 50}]}},
                                   "template": {"containers": [{"image": "x"}]}}}, "ContainerAppInvalidTraffic")):
    body = dict({"location": "eastus"}, **bad)
    r = call(st, "PUT", ["containerApps", "bad"], body)
    check(f"validation: {code}", r["status"] == 400 and r["body"]["error"]["code"] == code, r["body"])
check("invalid name", call(st, "PUT", ["containerApps", "Bad_Name"], APP)["body"]["error"]["code"] == "ContainerAppInvalidName")
check("404 shape", call(st, "GET", ["containerApps", "zzz"])["body"]["error"]["code"] == "ResourceNotFound")

# console forms submit strings
r = call(st, "PUT", ["containerApps", "form"], {"location": "eastus", "properties": {
    "configuration": {"ingress": {"targetPort": "8080", "external": "true"}},
    "template": {"containers": [{"image": "x/y"}], "scale": {"minReplicas": "1", "maxReplicas": "4"}}}})
ing = r["body"]["properties"]["configuration"]["ingress"]
check("string form values are coerced", ing["targetPort"] == 8080 and ing["external"] is True
      and r["body"]["properties"]["template"]["scale"]["maxReplicas"] == 4, r["body"])

# multiple revisions: traffic split + deactivate / restart / replicas
M = {"location": "eastus", "properties": {"configuration": {"activeRevisionsMode": "Multiple", "ingress": {"targetPort": 80}},
                                          "template": {"containers": [{"image": "a"}], "scale": {"minReplicas": 2, "maxReplicas": 3}}}}
call(st, "PUT", ["containerApps", "multi"], M)
M["properties"]["template"]["containers"][0]["image"] = "b"
call(st, "PUT", ["containerApps", "multi"], M)
revs = call(st, "GET", ["containerApps", "multi", "revisions"])["body"]["value"]
first = revs[0]["name"]
check("Multiple mode keeps both revisions active; traffic goes to the latest", len(revs) == 2 and sorted(x["properties"]["trafficWeight"] for x in revs) == [0, 100], revs)
check("deactivate then replicas drop to 0", call(st, "POST", ["containerApps", "multi", "revisions", first, "deactivate"])["status"] == 200
      and call(st, "GET", ["containerApps", "multi", "revisions", first, "replicas"])["body"]["value"] == [])
latest = [x for x in revs if x["name"] != first][0]["name"]
check("latest revision runs minReplicas replicas", len(call(st, "GET", ["containerApps", "multi", "revisions", latest, "replicas"])["body"]["value"]) == 2)
call(st, "POST", ["containerApps", "multi", "stop"])
check("stop → runningStatus Stopped and 0 replicas", call(st, "GET", ["containerApps", "multi"])["body"]["properties"]["runningStatus"] == "Stopped"
      and call(st, "GET", ["containerApps", "multi", "revisions", latest, "replicas"])["body"]["value"] == [])

# environments + children + jobs
check("environment with apps can't be deleted", call(st, "DELETE", ["managedEnvironments", "cae-rg1"])["status"] == 409)
env = call(st, "PUT", ["managedEnvironments", "env2"], {"location": "westeurope"})["body"]
check("environment has defaultDomain in its region + staticIp", env["properties"]["defaultDomain"].endswith(".westeurope.azurecontainerapps.io") and env["properties"]["staticIp"], env)
d = call(st, "PUT", ["managedEnvironments", "env2", "daprComponents", "state"], {"properties": {"componentType": "state.redis"}})
check("dapr component CRUD", d["status"] == 200 and call(st, "GET", ["managedEnvironments", "env2", "daprComponents"])["body"]["value"][0]["name"] == "state")
check("dapr component needs componentType", call(st, "PUT", ["managedEnvironments", "env2", "daprComponents", "x"], {"properties": {}})["status"] == 400)
J = {"location": "westeurope", "properties": {"environmentId": env["id"], "configuration": {"triggerType": "Manual"},
                                              "template": {"containers": [{"image": "busybox"}]}}}
call(st, "PUT", ["jobs", "j1"], J)
s = call(st, "POST", ["jobs", "j1", "start"], {})
check("job start → 202 execution; listed", s["status"] == 202 and s["body"]["name"].startswith("j1-")
      and call(st, "GET", ["jobs", "j1", "executions"])["body"]["value"][0]["properties"]["status"] == "Succeeded")
check("schedule job needs a cron expression", call(st, "PUT", ["jobs", "j2"], dict(J, properties=dict(J["properties"], configuration={"triggerType": "Schedule"})))["status"] == 400)
check("subscription-scope list", len(ac.dispatch(st, "GET", "sub1", None, ["containerApps"], [])["body"]["value"]) == 3)
check("deletes", call(st, "DELETE", ["jobs", "j1"])["status"] == 200 and call(st, "DELETE", ["containerApps", "zzz"])["status"] == 204)

# the Nano ARM class delegates to the same engine and keeps its map in the public `state`
arm = AzureArm()
base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/g/providers/Microsoft.App"
r = arm.handle("PUT", base + "/containerApps/a1", {"api-version": "2024-03-01"}, APP)
check("AzureArm (Nano) serves Microsoft.App with LRO headers and public state",
      r["status"] == 200 and "Azure-AsyncOperation" in r["headers"] and any("containerapps" in k for k in arm.state), r)
j = arm.handle("POST", base + "/jobs/none/start", {}, {})
check("AzureArm: unknown job → 404", j["status"] == 404)

print(f"\n{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
