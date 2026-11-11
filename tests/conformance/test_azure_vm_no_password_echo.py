"""A VM's osProfile.adminPassword is accepted on PUT but never returned by GET or list (real ARM). The stored value is untouched.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python tests/conformance/test_azure_vm_no_password_echo.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    V = {"api-version": "2023-09-01"}
    a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/pwrg", {"api-version": "2021-04-01"}, {"location": "eastus"})
    vm = f"/subscriptions/{SUB}/resourceGroups/pwrg/providers/Microsoft.Compute/virtualMachines/pwvm"
    body = {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"},
            "osProfile": {"computerName": "pwvm", "adminUsername": "u", "adminPassword": "Sup3r-Secret!x"}}}
    put = a.handle("PUT", vm, V, body)
    _check("PUT accepted", put["status"] in (200, 201))
    for label, r in (("PUT response", put), ("GET", a.handle("GET", vm, V, None))):
        osp = ((r["body"] or {}).get("properties") or {}).get("osProfile") or {}
        _check(f"{label} has no adminPassword", "adminPassword" not in osp)
        _check(f"{label} still has adminUsername", osp.get("adminUsername") == "u")
    lst = a.handle("GET", f"/subscriptions/{SUB}/resourceGroups/pwrg/providers/Microsoft.Compute/virtualMachines", V, None)
    _check("list has no adminPassword", "Sup3r-Secret" not in str(lst["body"]))
    stored = a.state.get(vm.lower())
    _check("the stored password is kept for the guest", ((stored or {}).get("properties", {}).get("osProfile") or {}).get("adminPassword") == "Sup3r-Secret!x")


if __name__ == "__main__":
    run()
    print("PASS")
