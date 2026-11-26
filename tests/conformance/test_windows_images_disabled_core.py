"""Windows VM images are DISABLED (owner decision 2026-11-26), not removed: they stay listed, but launching one is refused with a
cloud-native 400 and Linux launches are unchanged.  Re-enable = flip core/compute_sizes.WINDOWS_IMAGES_ENABLED.
Run on host:  PYTHONPATH=. python3 tests/conformance/test_windows_images_disabled_core.py
"""
import json
import re
import types

from core import compute_sizes as cs, vpc_core as vpc, gcp_compute_instances_core as gce
from tests.azure_tf_seed import AzureArm, rgid


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _aws_run(s, ami):
    return vpc.dispatch(s, {"Action": "RunInstances", "ImageId": ami, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})


def _gce(st, name, image):
    body = {"name": name, "machineType": "zones/us-central1-a/machineTypes/e2-micro",
            "disks": [{"boot": True, "initializeParams": {"sourceImage": image, "diskSizeGb": "10"}}]}
    return gce.dispatch(st, "POST", "/compute/v1/projects/p/zones/us-central1-a/instances", {}, {"content-type": "application/json"}, json.dumps(body).encode())


def run() -> int:
    _check("flag is off", cs.WINDOWS_IMAGES_ENABLED is False and cs.windows_blocked(True) and not cs.windows_blocked(False))

    # AWS: the Windows AMI is still LISTED (describe unchanged) but cannot be launched
    s = types.SimpleNamespace()
    imgs = vpc.dispatch(s, {"Action": "DescribeImages"}).body
    _check("AWS: Windows AMI still listed by DescribeImages", "Microsoft Windows Server 2022 Base" in imgs)
    win_id = re.search(r"<imageId>(ami-[^<]+)</imageId>(?:(?!</item>).)*?<name>Microsoft Windows Server 2022 Base", imgs, re.S) \
        or re.search(r"<name>Microsoft Windows Server 2022 Base</name>(?:(?!</item>).)*?<imageId>(ami-[^<]+)</imageId>", imgs, re.S)
    _check("AWS: found Windows image id", bool(win_id))
    bad = _aws_run(s, win_id.group(1))
    _check("AWS: RunInstances Windows -> 400 UnsupportedOperation", bad.status == 400 and "<Code>UnsupportedOperation</Code>" in bad.body and "not supported yet" in bad.body)
    lin = re.search(r"<imageId>(ami-[^<]+)</imageId>(?:(?!</item>).)*?<name>Ubuntu Server 22.04", imgs, re.S) or re.search(r"<name>Ubuntu Server 22.04[^<]*</name>(?:(?!</item>).)*?<imageId>(ami-[^<]+)</imageId>", imgs, re.S)
    _check("AWS: Linux RunInstances still 200", _aws_run(s, lin.group(1)).status == 200)

    # GCP
    st = gce.ComputeStore()
    r = _gce(st, "win-vm", "projects/windows-cloud/global/images/family/windows-2022")
    e = json.loads(r.body)["error"]
    _check("GCP: Windows sourceImage -> 400 INVALID_ARGUMENT", r.status == 400 and e["status"] == "INVALID_ARGUMENT" and "not supported yet" in e["message"])
    _check("GCP: Debian still 200", _gce(st, "deb-vm", "projects/debian-cloud/global/images/family/debian-12").status == 200)

    # Azure
    a = AzureArm()
    a.handle("PUT", rgid("rg"), {"api-version": "2023-09-01"}, {"location": "eastus"})
    vm = lambda n, props: a.handle("PUT", rgid("rg") + "/providers/Microsoft.Compute/virtualMachines/" + n, {"api-version": "2023-09-01"},
                                   {"location": "eastus", "properties": props})
    rw = vm("winvm", {"hardwareProfile": {"vmSize": "Standard_B1s"}, "storageProfile": {"imageReference": {"publisher": "MicrosoftWindowsServer", "offer": "WindowsServer", "sku": "2022-datacenter-azure-edition", "version": "latest"}}})
    _check("Azure: Windows image -> 400 OperationNotAllowed", rw["status"] == 400 and rw["body"]["error"]["code"] == "OperationNotAllowed" and "not supported yet" in rw["body"]["error"]["message"])
    rw2 = vm("winvm2", {"hardwareProfile": {"vmSize": "Standard_B1s"}, "osProfile": {"windowsConfiguration": {}}})
    _check("Azure: windowsConfiguration -> 400", rw2["status"] == 400)
    ok = vm("linvm", {"hardwareProfile": {"vmSize": "Standard_B1s"}, "storageProfile": {"imageReference": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts", "version": "latest"}}})
    _check("Azure: Ubuntu still created", ok["status"] in (200, 201))

    # wizards keep the options, marked disabled
    from core import aws_wizards, azure_wizards
    flat = json.dumps([aws_wizards.WIZARDS["ec2"], azure_wizards.WIZARDS.get("vm") or azure_wizards.WIZARDS])
    _check("wizards: Windows options kept and marked disabled", flat.count('"disabled": true') >= 2 and "windows2022" in flat and "windows-2022" in flat)
    print("windows images disabled: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
