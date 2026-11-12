"""Managed disks + attach-existing-disk on VMs: validation, attach/detach state, in-use guards.
Run: PYTHONPATH=. python tests/conformance/test_azure_disks_core.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    Q = {"api-version": "2023-04-02"}
    RG = f"/subscriptions/{SUB}/resourceGroups/d-rg"
    C = RG + "/providers/Microsoft.Compute"
    code = lambda r: (r["body"].get("error") or {}).get("code")
    put = lambda p, b: a.handle("PUT", p, Q, b)
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    _check("Empty needs a size", code(put(C + "/disks/d0", {"location": "eastus", "properties": {"creationData": {"createOption": "Empty"}}})) == "InvalidParameter")
    _check("bad sku rejected", code(put(C + "/disks/d0", {"location": "eastus", "sku": {"name": "Gold"}, "properties": {"diskSizeGB": 10, "creationData": {"createOption": "Empty"}}})) == "InvalidParameter")
    _check("copy source must exist", code(put(C + "/disks/d0", {"location": "eastus", "properties": {"creationData": {"createOption": "Copy", "sourceResourceId": C + "/disks/ghost"}}})) == "ReferencedResourceNotFound")
    r = put(C + "/disks/d1", {"location": "eastus", "sku": {"name": "Premium_LRS"}, "properties": {"diskSizeGB": 128, "creationData": {"createOption": "Empty"}}})
    p = r["body"]["properties"]
    _check("disk created Unattached with derived perf", r["status"] in (200, 201) and p["diskState"] == "Unattached" and p["diskIOPSReadWrite"] == 500 and p["diskSizeBytes"] == 128 * 1024 ** 3)
    r = put(C + "/disks/d2", {"location": "eastus", "properties": {"creationData": {"createOption": "Copy", "sourceResourceId": C + "/disks/d1"}}})
    _check("copy inherits size", r["body"]["properties"]["diskSizeGB"] == 128)
    _check("shrink rejected", code(put(C + "/disks/d1", {"location": "eastus", "sku": {"name": "Premium_LRS"}, "properties": {"diskSizeGB": 64, "creationData": {"createOption": "Empty"}}})) == "OperationNotAllowed")
    vm = lambda n, dd: put(C + f"/virtualMachines/{n}", {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}, "storageProfile": {"dataDisks": dd}}})
    att = lambda lun, d: {"lun": lun, "createOption": "Attach", "managedDisk": {"id": C + f"/disks/{d}"}}
    _check("attach a missing disk rejected", code(vm("vm1", [att(0, "ghost")])) == "ReferencedResourceNotFound")
    _check("duplicate LUN rejected", code(vm("vm1", [att(0, "d1"), att(0, "d2")])) == "InvalidParameter")
    _check("VM with attached disk accepted", vm("vm1", [att(0, "d1")])["status"] in (200, 201))
    g = a.handle("GET", C + "/disks/d1", Q)["body"]
    _check("disk is Attached with managedBy", g["properties"]["diskState"] == "Attached" and g["managedBy"].lower().endswith("/virtualmachines/vm1"))
    _check("same disk on a second VM -> 409", (lambda r: r["status"] == 409 and code(r) == "DiskAlreadyAttached")(vm("vm2", [att(0, "d1")])))
    _check("attached disk cannot be deleted", a.handle("DELETE", C + "/disks/d1", Q)["status"] == 409)
    _check("sku of an attached disk cannot change", code(put(C + "/disks/d1", {"location": "eastus", "sku": {"name": "Standard_LRS"}, "properties": {"diskSizeGB": 128, "creationData": {"createOption": "Empty"}}})) == "OperationNotAllowed")
    _check("grow while VM running rejected", code(put(C + "/disks/d1", {"location": "eastus", "sku": {"name": "Premium_LRS"}, "properties": {"diskSizeGB": 256, "creationData": {"createOption": "Empty"}}})) == "OperationNotAllowed")
    vm("vm1", [])
    g = a.handle("GET", C + "/disks/d1", Q)["body"]
    _check("detach clears managedBy", g["properties"]["diskState"] == "Unattached" and "managedBy" not in g)
    _check("detached disk can move to vm2", vm("vm2", [att(0, "d1")])["status"] in (200, 201))
    a.handle("DELETE", C + "/virtualMachines/vm2", Q)
    g = a.handle("GET", C + "/disks/d1", Q)["body"]
    _check("deleting the VM detaches (keeps) the disk", g["properties"]["diskState"] == "Unattached")
    _check("unattached disk deletes", a.handle("DELETE", C + "/disks/d1", Q)["status"] in (200, 204))
    print("disks core: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
