"""Azure VM run-command + NSG<->NIC back-references over the ARM wire (azure-core client,
endpoint changed only).

Covers the engine operations RunCommandAction (POST .../virtualMachines/{vm}/runCommand,
the `az vm run-command invoke` call) and SetBackrefList (a NIC attached to an NSG shows up
in the NSG's networkInterfaces list and disappears again on delete).
Run: VYOMI_BASE_URL=http://localhost:9000 python3 tests/conformance/test_azure_vm_runcommand_sdk.py
"""
import json
import os
import sys
import uuid

from azure.core import PipelineClient
from azure.core.pipeline.policies import HeadersPolicy, RetryPolicy
from azure.core.rest import HttpRequest

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
SUB = os.environ.get("SUB", "00000000-0000-0000-0000-cloudlearn01")
failed = 0


def check(name, ok, detail=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    failed += 0 if ok else 1


client = PipelineClient(BASE, policies=[HeadersPolicy(), RetryPolicy(retry_total=0)])


def call(method, path, body=None, av="2023-09-01"):
    sep = "&" if "?" in path else "?"
    resp = client.send_request(HttpRequest(method, f"{BASE}{path}{sep}api-version={av}", json=body))
    text = resp.read() if hasattr(resp, "read") else b""
    try:
        return resp.status_code, json.loads(text or b"{}")
    except ValueError:
        return resp.status_code, {}


def main():
    sfx = uuid.uuid4().hex[:6]
    rg = f"rg-rc-{sfx}"
    base = f"/subscriptions/{SUB}/resourceGroups/{rg}"
    call("PUT", base, {"location": "eastus"}, "2021-04-01")
    net = base + "/providers/Microsoft.Network"
    nsg_id = f"{net}/networkSecurityGroups/nsg{sfx}"
    s, _ = call("PUT", nsg_id, {"location": "eastus"}, "2023-11-01")
    check("create NSG", s in (200, 201), s)
    s, vn = call("PUT", f"{net}/virtualNetworks/vn{sfx}", {"location": "eastus", "properties": {
        "addressSpace": {"addressPrefixes": ["10.7.0.0/16"]},
        "subnets": [{"name": "s1", "properties": {"addressPrefix": "10.7.1.0/24"}}]}}, "2023-11-01")
    check("create vnet", s in (200, 201), vn)
    sub_id = f"{net}/virtualNetworks/vn{sfx}/subnets/s1"
    nic_id = f"{net}/networkInterfaces/nic{sfx}"
    s, nic = call("PUT", nic_id, {"location": "eastus", "properties": {
        "networkSecurityGroup": {"id": nsg_id},
        "ipConfigurations": [{"name": "c", "properties": {"subnet": {"id": sub_id}}}]}}, "2023-11-01")
    check("create NIC with NSG", s in (200, 201), nic)
    s, nsg = call("GET", nsg_id, None, "2023-11-01")
    check("NSG lists the NIC (set_backref_list add)",
          any(x["id"].lower() == nic_id.lower() for x in nsg.get("properties", {}).get("networkInterfaces", [])), nsg)

    vm = f"{base}/providers/Microsoft.Compute/virtualMachines/vm{sfx}"
    s, b = call("PUT", vm, {"location": "eastus", "properties": {
        "hardwareProfile": {"vmSize": "Standard_B1s"}, "osProfile": {"adminUsername": "azureuser"},
        "networkProfile": {"networkInterfaces": [{"id": nic_id}]}}})
    check("create VM", s in (200, 201), b)

    s, r = call("POST", vm + "/runCommand", {"commandId": "RunShellScript", "script": ["id"]})
    check("runCommand action returns a status value[]", s == 200 and isinstance(r.get("value"), list) and r["value"], r)
    check("no guest runtime -> failed status, nothing invented",
          s == 200 and r["value"][0]["code"] == "ProvisioningState/failed", r)
    s, r = call("POST", vm + "/runCommand", {"commandId": "RunShellScript"})
    check("runCommand without script is 400 InvalidParameter", s == 400 and r["error"]["code"] == "InvalidParameter", r)
    call("POST", vm + "/powerOff", {})
    s, r = call("POST", vm + "/runCommand", {"commandId": "RunShellScript", "script": ["id"]})
    check("runCommand on a stopped VM is 409 OperationNotAllowed", s == 409 and r["error"]["code"] == "OperationNotAllowed", r)

    call("DELETE", vm)
    s, _ = call("DELETE", nic_id, None, "2023-11-01")
    check("delete NIC", s in (200, 202, 204), s)
    s, nsg = call("GET", nsg_id, None, "2023-11-01")
    check("NSG no longer lists the NIC (set_backref_list remove)",
          not any(x["id"].lower() == nic_id.lower() for x in nsg.get("properties", {}).get("networkInterfaces", [])), nsg)
    call("DELETE", base, None, "2021-04-01")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
