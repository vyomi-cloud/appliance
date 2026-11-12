"""REAL azure-mgmt-resource against the Azure wire, endpoint changed only: ResourceGroupsOperations.begin_delete(force_deletion_types=...) is validated
and changes how VMs in the group are torn down (graceful deallocate vs direct force delete, visible in the Activity log); the group's Insights page
is computed from the real resources. Run: PYTHONPATH=. <venv>/bin/python tests/conformance/test_azure_rgtools_sdk.py   (or pytest)"""
import time
import uuid

import requests
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.mgmt.resource.resources import ResourceManagementClient

from tests.conformance import _azure_http

SUB = "00000000-0000-0000-0000-cloudlearn01"
BASE, ROUTER = _azure_http.start()
SFX = uuid.uuid4().hex[:6]


class _Cred:
    def get_token(self, *a, **k):
        return AccessToken("t", int(time.time()) + 3600)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def mk(rg):
    requests.put(f"{BASE}/subscriptions/{SUB}/resourcegroups/{rg}", json={"location": "eastus"}, params={"api-version": "2021-04-01"}, timeout=30)
    vm = f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/vm"
    r = requests.put(BASE + vm, json={"location": "eastus", "tags": {"env": "t"}, "properties": {}}, params={"api-version": "2023-09-01"}, timeout=30)
    assert r.status_code < 300, r.text
    return vm


def exists(rm, rg):
    try:
        rm.resource_groups.get(rg)
        return True
    except HttpResponseError:
        return False


def vm_ops(vm):
    ev = [r for k, r in ROUTER.az_arm.state.items() if "/__event__/" in k and str(r.get("resourceId", "")).lower() == vm.lower()]
    return [e["operationName"]["localizedValue"] for e in sorted(ev, key=lambda e: e["_seq"])]


def test_force_delete_and_insights_sdk():
    rm = ResourceManagementClient(_Cred(), SUB, base_url=BASE, authentication_policy=SansIOHTTPPolicy())
    rg1, rg2, rg3 = f"rg-fd1-{SFX}", f"rg-fd2-{SFX}", f"rg-fd3-{SFX}"
    vm1, vm2, vm3 = mk(rg1), mk(rg2), mk(rg3)

    ins = requests.get(f"{BASE}/subscriptions/{SUB}/resourceGroups/{rg1}/providers/Microsoft.Vyomi/insights", params={"api-version": "2024-01-01"}, timeout=30).json()
    ok("Insights reflects the real VM", ins["inventory"]["resourceCount"] == 1 and ins["compute"]["virtualMachines"] == 1 and ins["tags"]["coveragePercent"] == 100, ins)

    try:
        rm.resource_groups.begin_delete(rg1, force_deletion_types="Microsoft.Storage/storageAccounts").result()
        ok("SDK: unsupported force type rejected", False)
    except HttpResponseError as e:
        ok("SDK: unsupported force type rejected", e.status_code == 400, e)
    ok("group survives the rejected delete", exists(rm, rg1))

    rm.resource_groups.begin_delete(rg2).result()
    ok("SDK: plain delete = graceful (deallocate, then delete)", vm_ops(vm2)[-2:] == ["Deallocate Virtual Machine", "Delete Virtual Machine"], vm_ops(vm2))
    rm.resource_groups.begin_delete(rg3, force_deletion_types="Microsoft.Compute/virtualMachines,Microsoft.Compute/virtualMachineScaleSets").result()
    ok("SDK: force delete = direct 'Force delete', no deallocate", vm_ops(vm3)[-1] == "Force delete Virtual Machine" and "Deallocate Virtual Machine" not in vm_ops(vm3), vm_ops(vm3))
    ok("groups gone", not exists(rm, rg2) and not exists(rm, rg3))


if __name__ == "__main__":
    test_force_delete_and_insights_sdk()
    print("PASS")
