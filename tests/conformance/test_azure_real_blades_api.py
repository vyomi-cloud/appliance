"""Azure console blades show THIS resource's real ARM data — checked against the running
appliance (VYOMI_BASE_URL, default http://localhost:9000) and in the console sources.

Static (no server needed):
  * the shared REAL-BLADES block is byte-identical in static/azure-console.html (offline)
    and wasm/azure-console.html (Nano), so both consoles render the same blades;
  * no sub-blade of a converted service is a placeholder ("stub") any more.
Live (skipped when the appliance is unreachable): for a VM and a storage account the
routes each blade reads return that resource's data — locks, identity, health, NIC/IP,
instance view, run commands, schedules, keys, SAS, geo-replication.

    VYOMI_BASE_URL=http://localhost:9000 python3 tests/conformance/test_azure_real_blades_api.py
"""
import os
import re
import sys
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "cloudlearn-rg"
P = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"
failed = False

# Services whose blades are all backed by ARM data (metrics chart blades excepted).
CONVERTED = ["vm", "storage", "sql", "cosmos", "functionapp"]


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:300]}")
    failed = failed or not ok


def _block(path):
    s = open(os.path.join(ROOT, path), encoding="utf-8").read()
    m = re.search(r"// ===== REAL-BLADES:BEGIN.*?// ===== REAL-BLADES:END =====", s, re.S)
    return m.group(0) if m else None


def static_checks():
    a, b = _block("static/azure-console.html"), _block("wasm/azure-console.html")
    check("REAL-BLADES block present in both consoles", bool(a) and bool(b))
    check("REAL-BLADES block identical offline and in Nano", a == b)
    from core.azure_subblades import SUB_BLADES
    for key in CONVERTED:
        flat = []
        for node in SUB_BLADES[key]:
            flat += node.get("items", []) if "group" in node else [node]
        stubs = [i["label"] for i in flat if i.get("type") == "stub"]
        check(f"{key}: no placeholder sub-blades", not stubs, stubs)


def live_checks():
    try:
        import requests
        requests.get(BASE + "/api/azure/catalog", timeout=5).raise_for_status()
    except Exception as e:  # pragma: no cover - environment
        print(f"[SKIP] live checks: appliance not reachable at {BASE} ({e})")
        return
    s = requests.Session()

    def call(method, path, body=None, av="2023-11-01"):
        r = s.request(method, BASE + path, params={"api-version": av}, json=body, timeout=60)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None

    tag = uuid.uuid4().hex[:6]
    vm = f"{P}/Microsoft.Compute/virtualMachines/blades-{tag}"
    vnet = f"{P}/Microsoft.Network/virtualNetworks/blades-{tag}-vnet"
    call("PUT", vnet, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.9.0.0/16"]},
                       "subnets": [{"name": "default", "properties": {"addressPrefix": "10.9.0.0/24"}}]}})
    st, pip = call("PUT", f"{P}/Microsoft.Network/publicIPAddresses/blades-{tag}-ip", {"location": "eastus", "sku": {"name": "Standard"}})
    st, nic = call("PUT", f"{P}/Microsoft.Network/networkInterfaces/blades-{tag}-nic", {"location": "eastus", "properties": {
        "ipConfigurations": [{"name": "ipconfig1", "properties": {"subnet": {"id": vnet + "/subnets/default"},
                              "publicIPAddress": {"id": pip["id"], "properties": {"deleteOption": "Delete"}}}}]}})
    check("NIC gets a private IP from its subnet",
          st == 201 and nic["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"].startswith("10.9.0."), nic)
    st, v = call("PUT", vm, {"location": "eastus", "identity": {"type": "SystemAssigned"}, "properties": {
        "hardwareProfile": {"vmSize": "Standard_B1s"},
        "networkProfile": {"networkInterfaces": [{"id": nic["id"], "properties": {"deleteOption": "Delete"}}]}}}, "2023-09-01")
    check("VM created with a system-assigned identity", st in (200, 201) and len(v["identity"]["principalId"]) == 36, v)
    st, n = call("GET", nic["id"])
    check("Networking blade: NIC is attached to the VM", n["properties"].get("virtualMachine", {}).get("id") == vm, n)
    st, iv = call("GET", vm + "/instanceView", av="2023-09-01")
    check("Connect blade: instanceView power state", any(x["code"].startswith("PowerState/") for x in iv.get("statuses", [])), iv)
    st, h = call("GET", vm + "/providers/Microsoft.ResourceHealth/availabilityStatuses/current", av="2023-07-01-preview")
    check("Diagnose blade: resource health", h["properties"]["availabilityState"] in ("Available", "Unavailable"), h)
    st, lk = call("PUT", vm + "/providers/Microsoft.Authorization/locks/keep", {"properties": {"level": "CanNotDelete"}}, "2016-09-01")
    st, b = call("DELETE", vm, av="2023-09-01")
    check("Locks blade: a CanNotDelete lock blocks delete (409 ScopeLocked)", st == 409, b)
    st, ll = call("GET", vm + "/providers/Microsoft.Authorization/locks", av="2016-09-01")
    check("Locks blade lists the lock", [x["name"] for x in ll["value"]] == ["keep"], ll)
    call("DELETE", lk["id"], av="2016-09-01")
    st, rc = call("PUT", vm + "/runCommands/r1", {"location": "eastus", "properties": {"source": {"script": "uname -a"}}}, "2024-03-01")
    check("Run command blade: the run is recorded with its instance view",
          st in (200, 201) and rc["properties"]["instanceView"]["executionState"] in ("Succeeded", "Failed"), rc)
    st, sc = call("PUT", f"{P}/Microsoft.DevTestLab/schedules/shutdown-computevm-blades-{tag}", {"location": "eastus", "properties": {
        "status": "Enabled", "dailyRecurrence": {"time": "1900"}, "targetResourceId": vm}}, "2018-09-15")
    check("Auto-shutdown blade: schedule stored", st in (200, 201), sc)
    st, b = call("DELETE", vm, av="2023-09-01")
    check("VM delete cascades its NIC + public IP", st == 200 and call("GET", nic["id"])[0] == 404 and call("GET", pip["id"])[0] == 404)
    call("DELETE", vnet)

    acct = f"{P}/Microsoft.Storage/storageAccounts/stb{tag}"
    call("PUT", acct, {"location": "eastus", "sku": {"name": "Standard_RAGRS"}, "kind": "StorageV2"}, "2023-01-01")
    st, k = call("POST", acct + "/listKeys", {}, "2023-01-01")
    check("Access keys blade: two account keys", st == 200 and len(k["keys"]) == 2, k)
    st, sas = call("POST", acct + "/ListAccountSas", {"signedServices": "b", "signedResourceTypes": "sco",
                   "signedPermission": "rl", "signedExpiry": "2030-01-01T00:00:00Z"}, "2023-01-01")
    check("SAS blade: account SAS token signed", st == 200 and "sig=" in sas["accountSasToken"], sas)
    st, a = call("GET", acct, av="2023-01-01")
    check("Geo-replication blade: RA-GRS has a secondary region", a["properties"].get("secondaryLocation") == "westus", a)
    call("DELETE", acct, av="2023-01-01")


if __name__ == "__main__":
    static_checks()
    live_checks()
    sys.exit(1 if failed else 0)
