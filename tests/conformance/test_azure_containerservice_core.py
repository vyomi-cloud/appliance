"""Unit tests for core/azure_containerservice_core.py (run: python3 tests/conformance/test_azure_containerservice_core.py)."""
import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_containerservice_core as ak  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1"):
    return ak.dispatch(st, method, "sub1", rg, chain, [], body or {})


C = {"location": "eastus", "sku": {"name": "Base", "tier": "Free"}, "identity": {"type": "SystemAssigned"},
     "properties": {"dnsPrefix": "aks1-dns", "kubernetesVersion": "1.29.9",
                    "agentPoolProfiles": [{"name": "nodepool1", "count": 2, "vmSize": "Standard_DS2_v2", "mode": "System"}]}}
st = {}
r = cp(st, "PUT", ["managedClusters", "aks1"], C)
p = r["body"]["properties"]
check("create → 201 + LRO, Succeeded, Running", r["status"] == 201 and r["lro"] and p["provisioningState"] == "Succeeded"
      and p["powerState"]["code"] == "Running", r["body"])
check("fqdn + nodeResourceGroup + identity", p["fqdn"].endswith(".hcp.eastus.azmk8s.io") and p["nodeResourceGroup"] == "MC_rg1_aks1_eastus"
      and r["body"]["identity"]["type"] == "SystemAssigned" and r["body"]["identity"]["principalId"], r["body"])
check("agentPoolProfiles mirrored", p["agentPoolProfiles"][0]["name"] == "nodepool1" and p["agentPoolProfiles"][0]["count"] == 2)
check("no private state leaks", not any(k.startswith("_") for k in r["body"]))
check("dnsPrefix required", cp(st, "PUT", ["managedClusters", "x"], {"location": "eastus", "properties": {"agentPoolProfiles": C["properties"]["agentPoolProfiles"]}})["status"] == 400)
check("agent pool required", cp(st, "PUT", ["managedClusters", "x"], {"location": "eastus", "properties": {"dnsPrefix": "x"}})["status"] == 400)
check("bad version", cp(st, "PUT", ["managedClusters", "x"], dict(C, properties=dict(C["properties"], kubernetesVersion="1.1.1")))["body"]["error"]["code"] == "K8sVersionNotSupported")
check("bad name", cp(st, "PUT", ["managedClusters", "-bad"], C)["status"] == 400)
check("bad vm size", cp(st, "PUT", ["managedClusters", "x"], dict(C, properties=dict(C["properties"], agentPoolProfiles=[{"name": "np", "vmSize": "Nope"}])))["status"] == 400)
check("get / list", cp(st, "GET", ["managedClusters", "aks1"])["status"] == 200 and len(cp(st, "GET", ["managedClusters"], rg=None)["body"]["value"]) == 1)
check("get missing → ResourceNotFound", cp(st, "GET", ["managedClusters", "nope"])["body"]["error"]["code"] == "ResourceNotFound")
r = cp(st, "PATCH", ["managedClusters", "aks1"], {"tags": {"env": "dev"}})
check("PATCH tags", r["body"]["tags"] == {"env": "dev"})

# agent pools
r = cp(st, "PUT", ["managedClusters", "aks1", "agentPools", "user1"], {"properties": {"count": 1, "vmSize": "Standard_D4s_v3", "mode": "User", "enableAutoScaling": True, "minCount": 1, "maxCount": 5}})
check("agent pool create", r["status"] == 201 and r["body"]["properties"]["vmSize"] == "Standard_D4s_v3" and r["body"]["properties"]["orchestratorVersion"] == "1.29.9", r["body"])
check("pool visible in cluster profile", len(cp(st, "GET", ["managedClusters", "aks1"])["body"]["properties"]["agentPoolProfiles"]) == 2)
check("autoscale needs min/max", cp(st, "PUT", ["managedClusters", "aks1", "agentPools", "u2"], {"properties": {"enableAutoScaling": True}})["status"] == 400)
check("pool name rule", cp(st, "PUT", ["managedClusters", "aks1", "agentPools", "Bad_Name"], {"properties": {}})["status"] == 400)
r = cp(st, "PUT", ["managedClusters", "aks1", "agentPools", "user1"], {"properties": {"count": 3}})
check("pool scale", r["status"] == 200 and r["body"]["properties"]["count"] == 3)
check("pool vmSize immutable", cp(st, "PUT", ["managedClusters", "aks1", "agentPools", "user1"], {"properties": {"vmSize": "Standard_B2s"}})["status"] == 400)
check("cannot delete last system pool", cp(st, "DELETE", ["managedClusters", "aks1", "agentPools", "nodepool1"])["status"] == 400)
check("pool upgrade profile", cp(st, "GET", ["managedClusters", "aks1", "agentPools", "user1", "upgradeProfiles", "default"])["body"]["properties"]["upgrades"])
check("cluster upgrade profile", cp(st, "GET", ["managedClusters", "aks1", "upgradeProfiles", "default"])["body"]["properties"]["controlPlaneProfile"]["upgrades"])

# upgrades (an update without agentPoolProfiles leaves the pools alone)
U = lambda v: dict(C, properties={"dnsPrefix": "aks1-dns", "kubernetesVersion": v})
check("skip a minor version rejected", cp(st, "PUT", ["managedClusters", "aks1"], U("1.31.1"))["body"]["error"]["code"] == "UpgradeNotAllowed")
r = cp(st, "PUT", ["managedClusters", "aks1"], U("1.30")) 
check("upgrade one minor version", r["status"] == 200 and r["body"]["properties"]["kubernetesVersion"] == "1.30.5", r["body"])
check("upgrade rolls pools", cp(st, "GET", ["managedClusters", "aks1", "agentPools", "user1"])["body"]["properties"]["orchestratorVersion"] == "1.30.5")
check("downgrade rejected", cp(st, "PUT", ["managedClusters", "aks1"], U("1.28.14"))["body"]["error"]["code"] == "DowngradeNotAllowed")

# credentials
k = cp(st, "POST", ["managedClusters", "aks1", "listClusterAdminCredential"])["body"]["kubeconfigs"][0]
txt = base64.b64decode(k["value"]).decode()
check("admin kubeconfig", "kind: Config" in txt and "clusterAdmin_rg1_aks1" in txt and "azmk8s.io" in txt, txt)
check("user kubeconfig", "clusterUser_rg1_aks1" in base64.b64decode(cp(st, "POST", ["managedClusters", "aks1", "listClusterUserCredential"])["body"]["kubeconfigs"][0]["value"]).decode())
check("monitoring kubeconfig", cp(st, "POST", ["managedClusters", "aks1", "listClusterMonitoringUserCredential"])["status"] == 200)

# stop / start
check("stop", cp(st, "POST", ["managedClusters", "aks1", "stop"])["status"] == 202 and cp(st, "GET", ["managedClusters", "aks1"])["body"]["properties"]["powerState"]["code"] == "Stopped")
check("rotate certs needs running", cp(st, "POST", ["managedClusters", "aks1", "rotateClusterCertificates"])["status"] == 400)
check("start", cp(st, "POST", ["managedClusters", "aks1", "start"])["status"] == 202 and cp(st, "GET", ["managedClusters", "aks1"])["body"]["properties"]["powerState"]["code"] == "Running")
check("rotate certs", cp(st, "POST", ["managedClusters", "aks1", "rotateClusterCertificates"])["status"] == 202)

# maintenance / trusted access / snapshots
M = {"properties": {"timeInWeek": [{"day": "Sunday", "hourSlots": [1, 2]}]}}
check("maintenance config", cp(st, "PUT", ["managedClusters", "aks1", "maintenanceConfigurations", "default"], M)["status"] == 200
      and len(cp(st, "GET", ["managedClusters", "aks1", "maintenanceConfigurations"])["body"]["value"]) == 1)
check("maintenance name validated", cp(st, "PUT", ["managedClusters", "aks1", "maintenanceConfigurations", "weird"], M)["status"] == 400)
check("trusted access binding", cp(st, "PUT", ["managedClusters", "aks1", "trustedAccessRoleBindings", "b1"], {"properties": {"sourceResourceId": "/subscriptions/s/x", "roles": ["Microsoft.X/y/r"]}})["status"] in (200, 201))
sn = cp(st, "PUT", ["snapshots", "snap1"], {"location": "eastus", "properties": {"creationData": {"sourceResourceId": r["body"]["id"] + "/agentPools/user1"}}})
check("snapshot from node pool", sn["status"] == 201 and sn["body"]["properties"]["vmSize"] == "Standard_D4s_v3", sn["body"])
check("snapshot list in subscription", len(cp(st, "GET", ["snapshots"], rg=None)["body"]["value"]) == 1)
check("snapshot delete", cp(st, "DELETE", ["snapshots", "snap1"])["status"] == 200)
check("kubernetesVersions", len(cp(st, "GET", ["locations", "eastus", "kubernetesVersions"], rg=None)["body"]["values"]) >= 3)
check("orchestrators", cp(st, "GET", ["locations", "eastus", "orchestrators"], rg=None)["status"] == 200)
check("osOptions", cp(st, "GET", ["locations", "eastus", "osOptions"], rg=None)["status"] == 200)

check("delete", cp(st, "DELETE", ["managedClusters", "aks1"])["status"] == 202 and cp(st, "GET", ["managedClusters", "aks1"])["status"] == 404)
check("delete missing → 204", cp(st, "DELETE", ["managedClusters", "ghost"])["status"] == 204)

arm = AzureArm()
base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/viaarm"
resp = arm.handle("PUT", base, {"api-version": ak.API_VERSION}, C)
check("ARM dispatcher delegates to the engine", resp["status"] in (200, 201) and resp["body"]["properties"]["fqdn"], resp)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
