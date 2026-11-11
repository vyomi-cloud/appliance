"""VM-side Azure Compute fidelity helpers: adminPassword validation, instanceView expand, OS/data disk resources."""
from __future__ import annotations

import datetime
import re
import uuid

VM = "microsoft.compute/virtualmachines"
DISK = "microsoft.compute/disks"


def _is_windows(props: dict) -> bool:
    osp = props.get("osProfile") or {}
    if osp.get("windowsConfiguration") is not None:
        return True
    return str(((props.get("storageProfile") or {}).get("osDisk") or {}).get("osType") or "").lower() == "windows"


def validate_password(payload: dict):
    """Real-ARM adminPassword rules; returns a 400 response dict or None."""
    props = (payload or {}).get("properties") or {}
    osp = props.get("osProfile") or {}
    pw = osp.get("adminPassword")
    if not pw or not isinstance(pw, str):
        return None
    if (osp.get("linuxConfiguration") or {}).get("disablePasswordAuthentication") is True:
        return None
    lo, hi = (8, 123) if _is_windows(props) else (6, 72)
    classes = sum(bool(x) for x in (re.search(r"[a-z]", pw), re.search(r"[A-Z]", pw), re.search(r"\d", pw),
                                    re.search(r"[^A-Za-z0-9\x00-\x1f\x7f]", pw)))
    if not lo <= len(pw) <= hi or classes < 3 or re.search(r"[\x00-\x1f\x7f]", pw):
        msg = (f"The supplied password must be between {lo}-{hi} characters long and must satisfy at least 3 of password "
               "complexity requirements from the following: 1) Contains an uppercase character 2) Contains a lowercase "
               "character 3) Contains a numeric digit 4) Contains a special character 5) Control characters are not allowed")
        return {"status": 400, "headers": {}, "body": {"error": {"code": "InvalidParameter", "message": msg,
                                                                  "target": "osProfile.adminPassword"}}}
    return None


def with_instance_view(view: dict, vm_rec: dict, instance_view_fn) -> dict:
    out = dict(view)
    out["properties"] = {**(view.get("properties") or {}), "instanceView": instance_view_fn(vm_rec)}
    return out


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure(state, vm, disk_id, name, size, sku, delete_option):
    key = disk_id.lower()
    if key in state:
        return
    state[key] = {"id": disk_id, "name": name, "type": "Microsoft.Compute/disks", "location": vm.get("location"),
                  "tags": {}, "sku": {"name": sku, "tier": "Premium" if sku.startswith("Premium") else "Standard"},
                  "properties": {"diskSizeGB": size, "creationData": {"createOption": "FromImage"},
                                 "provisioningState": "Succeeded"},
                  "_type": "Microsoft.Compute/disks", "_sub": vm.get("_sub"), "_rg": vm.get("_rg"), "_created": _now(),
                  "_vm_deleteOption": delete_option}


def ensure_vm_disks(state, vm) -> bool:
    """Create managed-disk records for the VM's OS disk and inline data disks (idempotent)."""
    props = vm.get("properties") or {}
    sp = props.setdefault("storageProfile", {})
    changed = False
    od = sp.setdefault("osDisk", {})
    md = od.setdefault("managedDisk", {})
    sku = md.get("storageAccountType") or "Premium_LRS"
    if not md.get("id"):
        nm = od.get("name") or f"{vm['name']}_OsDisk_1_{uuid.uuid4().hex}"
        od["name"] = nm
        md["id"] = f"/subscriptions/{vm['_sub']}/resourceGroups/{vm['_rg']}/providers/Microsoft.Compute/disks/{nm}"
    od.setdefault("createOption", "FromImage")
    nm = md["id"].rsplit("/", 1)[-1]
    _ensure(state, vm, md["id"], nm, od.get("diskSizeGB") or 30, sku, od.get("deleteOption") or "Delete")
    for d in sp.get("dataDisks") or []:
        dm = d.setdefault("managedDisk", {})
        if dm.get("id"):
            continue
        dn = d.get("name") or f"{vm['name']}_disk{d.get('lun', 0)}_{uuid.uuid4().hex[:12]}"
        d["name"] = dn
        dm["id"] = f"/subscriptions/{vm['_sub']}/resourceGroups/{vm['_rg']}/providers/Microsoft.Compute/disks/{dn}"
        _ensure(state, vm, dm["id"], dn, d.get("diskSizeGB") or 1, dm.get("storageAccountType") or "Standard_LRS",
                d.get("deleteOption") or "Detach")
        changed = True
    return True


def os_disk_id(vm):
    return str((((vm.get("properties") or {}).get("storageProfile") or {}).get("osDisk") or {}).get("managedDisk", {}).get("id") or "")


def delete_vm_disks(state, vm):
    """Real ARM: OS/data disks whose deleteOption is Delete go with the VM (OS default here is Delete)."""
    sp = (vm.get("properties") or {}).get("storageProfile") or {}
    od = sp.get("osDisk") or {}
    ids = []
    if str(od.get("deleteOption") or "Delete").lower() != "detach" and os_disk_id(vm):
        ids.append(os_disk_id(vm))
    for d in sp.get("dataDisks") or []:
        mid = (d.get("managedDisk") or {}).get("id")
        if mid and str(d.get("deleteOption") or "Detach").lower() == "delete":
            ids.append(mid)
    for i in ids:
        r = state.get(i.lower())
        if r is not None and (r.get("_type") or "").lower() == DISK:
            state.pop(i.lower(), None)
