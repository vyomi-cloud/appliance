# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure managed disks (Microsoft.Compute/disks) + 'attach existing disk' on virtual machines, substrate-free (Nano / dev_server / offline ARM).

Real ARM resources with real validation and cross-resource checks, in the flat ARM state map used by azure_arm_core (hooks: handles /
validate / after_put / before_delete / on_delete, like azure_lb_core).

* ``disks`` -- sku (Standard_LRS, StandardSSD_LRS, Premium_LRS, StandardSSD_ZRS, Premium_ZRS, UltraSSD_LRS, PremiumV2_LRS),
  ``creationData.createOption`` Empty (needs diskSizeGB 1..32767) | Copy / Restore (``sourceResourceId`` must be an existing disk or
  snapshot, size defaults from it) | FromImage | Import | Upload; the size can only grow (shrinking is rejected), and growing a disk that
  is attached to a VM needs that VM stopped/deallocated; the SKU of an attached disk cannot change. Derived: ``diskState``
  (Unattached | Attached), ``managedBy`` / ``managedByExtended``, ``timeCreated``, ``uniqueId``, provisioned IOPS / MBps from the SKU+size tier.
* VM ``storageProfile.dataDisks`` with ``createOption: Attach`` + ``managedDisk.id`` -- the disk must exist, be in the VM's region, not be
  attached to another VM (409 ``DiskAlreadyAttached``), LUNs unique in 0..63; the disk's ``managedBy`` / ``diskState`` follow the VM list.
  A disk that is attached cannot be deleted (409 ``OperationNotAllowed``); deleting a VM detaches (never deletes) its attached data disks.

NOT modelled: the disk's blocks (no filesystem is ever exposed to a guest), disk encryption sets / CMK, shared disks (maxShares), snapshots
and restore points beyond referencing them as a copy source, zone-redundant replication.
"""
from __future__ import annotations

import datetime
import uuid

DISK = "microsoft.compute/disks"
VM = "microsoft.compute/virtualmachines"
SKUS = ("Standard_LRS", "StandardSSD_LRS", "Premium_LRS", "StandardSSD_ZRS", "Premium_ZRS", "UltraSSD_LRS", "PremiumV2_LRS")
CREATE = ("Empty", "Copy", "Restore", "FromImage", "Import", "Upload", "ImportSecure", "UploadPreparedSecure")


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def handles(full_type: str) -> bool:
    return (full_type or "").lower() in (DISK, VM)


def _perf(sku: str, gb: int):
    tiers = [(4, 120, 25), (8, 120, 25), (16, 500, 100), (32, 120, 25), (64, 240, 50), (128, 500, 100), (256, 1100, 125), (512, 2300, 150), (1024, 5000, 200), (2048, 7500, 250), (4096, 7500, 250), (8192, 16000, 500), (16384, 18000, 750), (32767, 20000, 900)]
    if sku.startswith("Premium_"):
        tiers = [(4, 120, 25), (8, 120, 25), (16, 120, 25), (32, 120, 25), (64, 240, 50), (128, 500, 100), (256, 1100, 125), (512, 2300, 150), (1024, 5000, 200), (2048, 7500, 250), (4096, 7500, 250), (8192, 16000, 500), (16384, 18000, 750), (32767, 20000, 900)]
        for cap, iops, mbps in tiers:
            if gb <= cap:
                return {"diskIOPSReadWrite": {4: 120, 8: 120, 16: 120, 32: 120, 64: 240, 128: 500, 256: 1100, 512: 2300, 1024: 5000, 2048: 7500}.get(cap, iops), "diskMBpsReadWrite": mbps}
    if sku.startswith("Standard_"):
        return {"diskIOPSReadWrite": 500, "diskMBpsReadWrite": 60}
    for cap, iops, mbps in tiers:
        if gb <= cap:
            return {"diskIOPSReadWrite": min(iops, 6000), "diskMBpsReadWrite": min(mbps, 750)}
    return {"diskIOPSReadWrite": 500, "diskMBpsReadWrite": 60}


def _vm_attachments(state: dict) -> dict:
    """{disk id lower: vm record} for every managed data disk referenced by a VM."""
    out = {}
    for rec in state.values():
        if (rec.get("_type") or "").lower() != VM:
            continue
        for d in ((rec.get("properties") or {}).get("storageProfile") or {}).get("dataDisks") or []:
            mid = str(((d or {}).get("managedDisk") or {}).get("id") or "").lower()
            if mid:
                out[mid] = rec
    return out


def _vm_stopped(vm: dict) -> bool:
    ps = str((vm.get("properties") or {}).get("powerState") or "PowerState/running").lower()
    return "deallocated" in ps or "stopped" in ps


def _validate_disk(state, rid, payload, existing):
    p = (payload or {}).get("properties") or {}
    sku = ((payload or {}).get("sku") or (existing or {}).get("sku") or {}).get("name") or "Standard_LRS"
    if sku not in SKUS:
        return _err(400, "InvalidParameter", f"sku.name must be one of {', '.join(SKUS)}.")
    cd = p.get("creationData") or (existing or {}).get("properties", {}).get("creationData") or {}
    opt = cd.get("createOption") or ("Empty" if not existing else None)
    if opt not in CREATE:
        return _err(400, "InvalidParameter", f"creationData.createOption is required and must be one of {', '.join(CREATE)}.")
    size = p.get("diskSizeGB", (existing or {}).get("properties", {}).get("diskSizeGB"))
    src = None
    if opt in ("Copy", "Restore"):
        src = state.get(str(cd.get("sourceResourceId") or "").lower())
        if src is None or (src.get("_type") or "").lower() not in (DISK, "microsoft.compute/snapshots"):
            return _err(400, "ReferencedResourceNotFound", f"creationData.sourceResourceId '{cd.get('sourceResourceId')}' does not name an existing disk or snapshot.")
        if size is None:
            size = (src.get("properties") or {}).get("diskSizeGB")
        elif size < ((src.get("properties") or {}).get("diskSizeGB") or 0):
            return _err(400, "InvalidParameter", "diskSizeGB cannot be smaller than the source disk.")
    if opt == "Empty" and size is None:
        return _err(400, "InvalidParameter", "diskSizeGB is required when creationData.createOption is Empty.")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 32767):
        return _err(400, "InvalidParameter", "diskSizeGB must be an integer between 1 and 32767.")
    if existing:
        old = (existing.get("properties") or {}).get("diskSizeGB")
        att = _vm_attachments(state).get((existing.get("id") or rid).lower())
        if size is not None and old and size < old:
            return _err(400, "OperationNotAllowed", f"Disk size cannot be reduced (current {old} GiB, requested {size} GiB).")
        if att is not None and size is not None and old and size > old and not _vm_stopped(att):
            return _err(409, "OperationNotAllowed", f"Cannot resize a disk attached to the running VM '{att.get('name')}': deallocate it first.")
        if att is not None and (existing.get("sku") or {}).get("name") not in (None, sku):
            return _err(409, "OperationNotAllowed", f"The SKU of a disk attached to VM '{att.get('name')}' cannot be changed; detach it first.")
    zones = (payload or {}).get("zones")
    if zones is not None and (not isinstance(zones, list) or any(str(z) not in ("1", "2", "3") for z in zones)):
        return _err(400, "InvalidParameter", "zones must be a list of '1', '2' or '3'.")
    return None


def _validate_vm(state, rid, payload, existing):
    dd = (((payload or {}).get("properties") or {}).get("storageProfile") or {}).get("dataDisks")
    if dd is None:
        return None
    loc = ((payload or {}).get("location") or (existing or {}).get("location") or "").lower().replace(" ", "")
    att = _vm_attachments(state)
    luns = set()
    for d in dd:
        lun = (d or {}).get("lun")
        if not isinstance(lun, int) or isinstance(lun, bool) or not 0 <= lun <= 63:
            return _err(400, "InvalidParameter", "Every data disk needs an integer lun between 0 and 63.")
        if lun in luns:
            return _err(400, "InvalidParameter", f"Data disk LUN {lun} is used more than once.")
        luns.add(lun)
        mid = str(((d or {}).get("managedDisk") or {}).get("id") or "")
        if not mid:
            continue                                   # an inline (create-and-attach) disk
        disk = state.get(mid.lower())
        if disk is None or (disk.get("_type") or "").lower() != DISK:
            return _err(400, "ReferencedResourceNotFound", f"Managed disk '{mid}' (LUN {lun}) was not found.")
        dloc = (disk.get("location") or "").lower().replace(" ", "")
        if loc and dloc and loc != dloc:
            return _err(400, "OperationNotAllowed", f"Disk '{disk.get('name')}' is in '{dloc}' but the VM is in '{loc}'; a disk can only be attached to a VM in its own region.")
        other = att.get(mid.lower())
        if other is not None and (other.get("id") or "").lower() != rid.lower():
            return _err(409, "DiskAlreadyAttached", f"Disk '{disk.get('name')}' is already attached to virtual machine '{other.get('name')}'; detach it before attaching it elsewhere.")
    return None


def validate(state, full_type, rid, payload, existing, sub, rg):
    ft = full_type.lower()
    if ft == DISK:
        return _validate_disk(state, rid, payload, existing)
    if ft == VM:
        return _validate_vm(state, rid, payload, existing)
    return None


def _refresh(state):
    att = _vm_attachments(state)
    for rec in state.values():
        if (rec.get("_type") or "").lower() != DISK:
            continue
        p = rec.setdefault("properties", {})
        vm = att.get((rec.get("id") or "").lower())
        cd = p.get("creationData") or {}
        if p.get("diskSizeGB") is None and cd.get("createOption") in ("Copy", "Restore"):
            src = state.get(str(cd.get("sourceResourceId") or "").lower())
            p["diskSizeGB"] = ((src or {}).get("properties") or {}).get("diskSizeGB")
        gb = int(p.get("diskSizeGB") or 0)
        p["diskSizeBytes"] = gb * 1024 ** 3
        p["diskState"] = "Attached" if vm else "Unattached"
        p.setdefault("uniqueId", str(uuid.uuid4()))
        p.setdefault("timeCreated", datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"))
        p["provisioningState"] = "Succeeded"
        p.update(_perf((rec.get("sku") or {}).get("name") or "Standard_LRS", gb))
        if vm:
            rec["managedBy"] = vm.get("id")
        else:
            rec.pop("managedBy", None)


def after_put(state, rec, payload, prev=None):
    _refresh(state)
    if (rec.get("_type") or "").lower() == DISK:
        rec.setdefault("sku", {"name": "Standard_LRS"}).setdefault("tier", "Premium" if str(rec["sku"].get("name", "")).startswith("Premium") else "Standard")


def before_delete(state, rec):
    if (rec.get("_type") or "").lower() == DISK:
        vm = _vm_attachments(state).get((rec.get("id") or "").lower())
        if vm is not None:
            return _err(409, "OperationNotAllowed", f"Disk '{rec.get('name')}' is attached to virtual machine '{vm.get('name')}' and cannot be deleted; detach it first.")
    return None


def on_delete(state, rec):
    if (rec.get("_type") or "").lower() == VM:
        _refresh(state)
