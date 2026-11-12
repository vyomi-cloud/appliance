"""VM adminPassword validation, $expand=instanceView, and OS/data disks as ARM resources (real ARM; Mesh run findings).
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python tests/conformance/test_azure_vm_password_expand_osdisk.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    V = {"api-version": "2023-09-01"}
    rg = f"/subscriptions/{SUB}/resourceGroups/dkrg"
    a.handle("PUT", rg, {"api-version": "2021-04-01"}, {"location": "eastus"})
    base = f"{rg}/providers/Microsoft.Compute/virtualMachines/"

    def put(name, pw, extra=None, **osp):
        o = {"computerName": name, "adminUsername": "u", **osp}
        if pw is not None:
            o["adminPassword"] = pw
        props = {"hardwareProfile": {"vmSize": "Standard_B1s"}, "osProfile": o, **(extra or {})}
        return a.handle("PUT", base + name, V, {"location": "eastus", "properties": props})

    for label, pw, kw in (("linux too short", "Ab1!", {}), ("linux 2 classes", "alllowercase12", {}),
                          ("windows 7 chars", "Ab1!xyz", {"windowsConfiguration": {}}),
                          ("windows 2 classes", "alllower123456", {"windowsConfiguration": {}}),
                          ("linux 73 chars", "Aa1" * 24 + "b", {})):
        r = put("bad", pw, **kw)
        _check(f"{label} -> 400 InvalidParameter", r["status"] == 400 and r["body"]["error"]["code"] == "InvalidParameter")
        _check(f"{label} message", "3 of password complexity" in r["body"]["error"]["message"])
    _check("linux 6 chars ok", put("l6", "Ab1xyz")["status"] in (200, 201))
    _check("windows 8 chars ok", put("w8", "Ab1xyz!q", windowsConfiguration={})["status"] in (200, 201))
    _check("ssh-only skips validation", put("ssh", "x", linuxConfiguration={"disablePasswordAuthentication": True})["status"] in (200, 201))
    _check("no password skips validation", put("nopw", None)["status"] in (200, 201))

    r = a.handle("GET", base + "l6", {**V, "$expand": "instanceView"}, None)
    iv = (r["body"]["properties"] or {}).get("instanceView") or {}
    codes = [s["code"] for s in iv.get("statuses", [])]
    _check("GET $expand=instanceView has ProvisioningState+PowerState", any(c.startswith("ProvisioningState/") for c in codes) and any(c.startswith("PowerState/") for c in codes))
    _check("GET without expand has no instanceView", "instanceView" not in (a.handle("GET", base + "l6", V, None)["body"]["properties"]))
    lst = a.handle("GET", base[:-1], {**V, "$expand": "instanceView"}, None)["body"]["value"]
    _check("list $expand=instanceView", lst and all("instanceView" in v["properties"] for v in lst))

    vm = a.handle("GET", base + "l6", V, None)["body"]
    did = vm["properties"]["storageProfile"]["osDisk"]["managedDisk"]["id"]
    D = {"api-version": "2023-04-02"}
    r = a.handle("GET", did, D, None)
    _check("OS disk GET 200", r["status"] == 200)
    b = r["body"]
    _check("disk fields", b["name"] == did.rsplit("/", 1)[-1] and b["location"] == "eastus" and b["sku"]["name"] and b["properties"]["diskSizeGB"]
           and b["properties"]["provisioningState"] == "Succeeded")
    _check("disk Attached + managedBy VM", b["properties"]["diskState"] in ("Attached", "Reserved") and b["managedBy"].lower() == vm["id"].lower())
    for path in (f"{rg}/providers/Microsoft.Compute/disks", f"/subscriptions/{SUB}/providers/Microsoft.Compute/disks"):
        _check("disk list contains it", any(d["id"].lower() == did.lower() for d in a.handle("GET", path, D, None)["body"]["value"]))
    a.handle("PUT", did, D, {"location": "eastus", "properties": {"diskSizeGB": 64, "creationData": {"createOption": "Empty"}}})
    _check("disk stays attached after disk re-PUT", a.handle("GET", did, D, None)["body"].get("managedBy"))
    a.handle("DELETE", base + "l6", V, None)
    _check("VM delete removes OS disk", a.handle("GET", did, D, None)["status"] == 404)


if __name__ == "__main__":
    run()
    print("PASS")
