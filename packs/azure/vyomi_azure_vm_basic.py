from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.vm.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "resourceType": "Microsoft.Compute/virtualMachines",
        "actions": [
            "VirtualMachines_CreateOrUpdate",
            "VirtualMachines_Get",
            "VirtualMachines_Delete",
            "VirtualMachines_List",
            "VirtualMachines_Start",
            "VirtualMachines_PowerOff",
            "VirtualMachines_Restart",
            "VirtualMachines_Deallocate",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2024-03-01",
        "dataPlane": "lxd/multipass (LXD-backed VMs with tier-mapped limits)",
    },
)
