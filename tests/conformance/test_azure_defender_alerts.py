"""Defender for Cloud alerts (deterministic detector over the ARM audit feed) + ACR image vulnerability assessments.
Run: PYTHONPATH=. <venv python> tests/conformance/test_azure_defender_alerts.py"""
import hashlib
import json

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
from core import azure_acr_core as acr

SUB, RG = DEFAULT_SUBSCRIPTION, "alert-rg"
SEC = f"/subscriptions/{SUB}/providers/Microsoft.Security"
n = 0


def check(name, c):
    global n
    if not c:
        raise AssertionError(name)
    n += 1
    print("  ok ", name)


arm = AzureArm()
arm.acr_store = acr.AcrRegistryStore()
arm.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})
st = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/alertsa"
arm.handle("PUT", st, {"api-version": "2023-01-01"}, {"location": "eastus", "properties": {"allowBlobPublicAccess": False}})
alerts = lambda: arm.handle("GET", SEC + "/alerts", {"api-version": "2022-01-01"})["body"]["value"]
check("no alerts on a quiet subscription", alerts() == [])
arm.handle("PATCH", st, {"api-version": "2023-01-01"}, {"properties": {"allowBlobPublicAccess": True}})
check("plan off -> no alert (gated like Azure)", alerts() == [])
arm.handle("PUT", SEC + "/pricings/StorageAccounts", {}, {"properties": {"pricingTier": "Standard"}})
a = alerts()
check("Defender for Storage on -> storage alert from the recorded change", len(a) == 1 and a[0]["properties"]["alertType"] == "VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED"
      and a[0]["properties"]["vendorName"] == "Vyomi" and a[0]["properties"]["status"] == "Active" and a[0]["properties"]["compromisedEntity"].lower() == st.lower())
check("deterministic", alerts() == a)
arm.handle("PUT", SEC + "/pricings/Arm", {}, {"properties": {"pricingTier": "Standard"}})
nsg = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network/networkSecurityGroups/n1"
arm.handle("PUT", nsg, {"api-version": "2023-11-01"}, {"location": "eastus"})
arm.handle("PUT", nsg + "/securityRules/ssh", {"api-version": "2023-11-01"}, {"properties": {"direction": "Inbound", "access": "Allow", "protocol": "Tcp", "priority": 300,
           "sourceAddressPrefix": "*", "sourcePortRange": "*", "destinationAddressPrefix": "*", "destinationPortRange": "22"}})
ra = f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleAssignments/ra1"
arm.handle("PUT", ra, {"api-version": "2022-04-01"}, {"properties": {"roleDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635", "principalId": "p1"}})
types = {x["properties"]["alertType"] for x in alerts()}
check("NSG exposure alert", "VYOMI_ARM_MANAGEMENT_PORT_EXPOSED" in types)
check("Owner assignment alert (when the engine accepts the assignment)", "VYOMI_ARM_PRIVILEGED_ROLE_ASSIGNED" in types)
al = [x for x in alerts() if x["properties"]["alertType"] == "VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED"][0]
base = al["id"]
check("dismiss -> 204 and status changes", arm.handle("POST", base + "/dismiss", {"api-version": "2022-01-01"})["status"] == 204
      and [x for x in alerts() if x["name"] == al["name"]][0]["properties"]["status"] == "Dismissed")
arm.handle("POST", base + "/activate", {"api-version": "2022-01-01"})
check("activate restores", [x for x in alerts() if x["name"] == al["name"]][0]["properties"]["status"] == "Active")
check("GET one", arm.handle("GET", base, {"api-version": "2022-01-01"})["body"]["name"] == al["name"])
ip = arm.handle("POST", base + "/inprogress", {"api-version": "2022-01-01"})
cur = [x for x in alerts() if x["name"] == al["name"]][0]
check("inprogress sets InProgress and records history", ip["status"] == 204 and cur["properties"]["status"] == "InProgress"
      and [h["action"] for h in json.loads(cur["properties"]["extendedProperties"]["statusHistory"])][-3:] == ["dismiss", "activate", "inprogress"])
rm = arm.handle("POST", base + "/remediate", {"api-version": "2022-01-01"})
cur = [x for x in alerts() if x["name"] == al["name"]][0]
check("remediate closes public access on the account and resolves", rm["status"] == 204 and cur["properties"]["status"] == "Resolved"
      and arm.state[st.lower()]["properties"]["allowBlobPublicAccess"] is False and "allowBlobPublicAccess" in cur["properties"]["extendedProperties"]["remediation"])
nal = [x for x in alerts() if x["properties"]["alertType"] == "VYOMI_ARM_MANAGEMENT_PORT_EXPOSED"][0]
check("remediate NSG rule -> Deny", arm.handle("POST", nal["id"] + "/remediate", {})["status"] == 204)
pal = [x for x in alerts() if x["properties"]["alertType"] == "VYOMI_ARM_PRIVILEGED_ROLE_ASSIGNED"][0]
check("remediate role assignment deletes it", arm.handle("POST", pal["id"] + "/remediate", {})["status"] == 204 and ra.lower() not in arm.state)
check("remediate again on a gone resource -> 409", arm.handle("POST", pal["id"] + "/remediate", {})["status"] == 409)
check("unknown action 404", arm.handle("POST", base + "/explode", {})["status"] == 404)
json.dumps(arm.state)
check("state stays JSON-safe", True)

# ── ACR image vulnerabilities ──────────────────────────────────────────────
reg = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.ContainerRegistry/registries/vyomireg"
arm.handle("PUT", reg, {"api-version": "2023-07-01"}, {"location": "eastus", "sku": {"name": "Standard"}})
cfg = json.dumps({"architecture": "amd64", "os": "linux", "config": {"Env": ["PYTHON_VERSION=3.8.12"]},
                  "history": [{"created_by": "/bin/sh -c pip install requests==2.19.0"}]}).encode()
cd = "sha256:" + hashlib.sha256(cfg).hexdigest()
man = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json", "config": {"digest": cd, "size": len(cfg)}, "layers": []}).encode()
repo = acr._get_or_create_repo(arm.acr_store, "web")
repo["blobs"][cd] = cfg
acr._push_manifest(arm.acr_store, "web", "v1", man, "application/vnd.docker.distribution.manifest.v2+json")
vul = lambda: [v for v in arm.handle("GET", SEC + "/assessments", {"api-version": "2021-06-01"})["body"]["value"] if v["properties"]["displayName"].startswith("Container registry images")]
check("Containers plan off -> no image assessment", vul() == [])
arm.handle("PUT", SEC + "/pricings/Containers", {}, {"properties": {"pricingTier": "Standard"}})
v = vul()
check("image assessment Unhealthy on the registry", len(v) == 1 and v[0]["properties"]["status"]["code"] == "Unhealthy" and v[0]["properties"]["resourceDetails"]["Id"].lower() == reg.lower())
subs = arm.handle("GET", v[0]["id"] + "/subAssessments", {"api-version": "2019-01-01-preview"})["body"]["value"]
ids = {s["properties"]["id"] for s in subs}
check("sub-assessment per CVE with fixed version", "CVE-2018-18074" in ids and any(s["properties"]["additionalData"]["fixedVersion"] == "2.20.0" for s in subs))
print(f"OK {n} checks")
