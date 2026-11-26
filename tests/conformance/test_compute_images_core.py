"""Compute images per substrate: Nano lists/accepts ONLY the guest its in-browser VM boots (Alpine 3.21, 32-bit x86); Mesh/offline keep the catalog.

Substrate forced with VYOMI_COMPUTE_SUBSTRATE (same as test_compute_sizes_core.py).  Run: PYTHONPATH=. python3 tests/conformance/test_compute_images_core.py
"""
import json
import os
import re
import types

try:
    from core import compute_sizes as cs, vpc_core as vpc, gcp_compute_instances_core as gce
except ImportError:  # pragma: no cover - Pyodide flat layout
    import compute_sizes as cs  # type: ignore
    import vpc_core as vpc  # type: ignore
    import gcp_compute_instances_core as gce  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _aws_images(s):
    r = vpc.dispatch(s, {"Action": "DescribeImages", "Owner.1": "amazon", "Owner.2": "self"})
    return re.findall(r"<name>([^<]*)</name>", r.body), re.findall(r"<architecture>([^<]*)</architecture>", r.body), r.body


def _gce_post(st, name, src):
    d = {"boot": True, "initializeParams": {"diskSizeGb": "10"}}
    if src:
        d["initializeParams"]["sourceImage"] = src
    body = {"name": name, "machineType": "zones/us-central1-a/machineTypes/e2-micro", "disks": [d]}
    return gce.dispatch(st, "POST", "/compute/v1/projects/p/zones/us-central1-a/instances", {}, {"content-type": "application/json"}, json.dumps(body).encode())


def run() -> int:
    saved = os.environ.get("VYOMI_COMPUTE_SUBSTRATE")
    try:
        a = cs.NANO_IMAGES
        # AWS
        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "nano"
        s = types.SimpleNamespace()
        names, archs, body = _aws_images(s)
        _check("nano aws: only the Alpine i386 AMI is listed", names == [a["aws"]["name"]] and archs == ["i386"])
        _check("nano aws: substrate marker", "<vyomiSubstrate>nano</vyomiSubstrate>" in body)
        ami = re.search(r"<imageId>([^<]+)</imageId>", body).group(1)
        r = vpc.dispatch(s, {"Action": "RunInstances", "ImageId": ami, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
        _check("nano aws: RunInstances with the Alpine AMI works, instance is i386", r.status == 200 and "<architecture>i386</architecture>" in r.body)
        r = vpc.dispatch(s, {"Action": "RunInstances", "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
        _check("nano aws: no ImageId defaults to the Alpine AMI", r.status == 200 and ami in r.body)
        m = vpc._model(s)
        x86 = "ami-" + "0" * 17
        m["images"][x86] = {**m["images"][ami], "id": x86, "name": "Amazon Linux 2023", "architecture": "x86_64"}
        r = vpc.dispatch(s, {"Action": "RunInstances", "ImageId": x86, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
        _check("nano aws: an x86_64 AMI is refused with Unsupported (400)", r.status == 400 and "<Code>Unsupported</Code>" in r.body)
        _check("nano aws: the x86_64 AMI is not listed", x86 not in _aws_images(s)[2])
        _check("nano aws: instance types advertise i386", "<item>i386</item>" in vpc.dispatch(s, {"Action": "DescribeInstanceTypes"}).body)
        for sub in ("mesh", "offline"):
            os.environ["VYOMI_COMPUTE_SUBSTRATE"] = sub
            s2 = types.SimpleNamespace()
            names, archs, body = _aws_images(s2)
            _check(f"{sub} aws: full quick-start catalog (Amazon Linux, Ubuntu, Windows, ...)", len(names) >= 6 and "x86_64" in archs and "i386" not in archs and "vyomiSubstrate" not in body)
        # GCP
        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "nano"
        st = gce.ComputeStore()
        g = a["gcp"]
        lst = json.loads(gce.dispatch(st, "GET", "/compute/v1/projects/%s/global/images" % g["project"], {}, {}, b"").body)["items"]
        _check("nano gcp: the Nano image project lists only the Alpine image", [i["name"] for i in lst] == [g["name"]] and lst[0]["vyomiSubstrate"] == "nano")
        _check("nano gcp: debian-cloud lists no images", json.loads(gce.dispatch(st, "GET", "/compute/v1/projects/debian-cloud/global/images", {}, {}, b"").body).get("items", []) == [])
        ok = _gce_post(st, "ok1", "projects/%s/global/images/family/%s" % (g["project"], g["family"]))
        _check("nano gcp: insert with the Alpine family works", ok.status == 200)
        bad = _gce_post(st, "bad1", "projects/debian-cloud/global/images/family/debian-12")
        e = json.loads(bad.body)["error"]
        _check("nano gcp: debian image -> 404 NOT_FOUND with the Nano explanation", bad.status == 404 and e["status"] == "NOT_FOUND" and "cannot run on" in e["message"])
        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "offline"
        st2 = gce.ComputeStore()
        _check("offline gcp: debian-12 still launches", _gce_post(st2, "d1", "projects/debian-cloud/global/images/family/debian-12").status == 200)
        _check("offline gcp: debian-cloud still lists", gce.dispatch(st2, "GET", "/compute/v1/projects/debian-cloud/global/images", {}, {}, b"").status == 200)
        # Azure
        z = a["azure"]
        ref = {"publisher": z["publisher"], "offer": z["offer"], "sku": z["sku"], "version": "latest"}
        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "nano"
        _check("nano azure: the Alpine reference is allowed", cs.azure_image_allowed(ref) and cs.azure_image_allowed(None))
        _check("nano azure: Canonical Ubuntu is refused", not cs.azure_image_allowed({"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts"}))
        _check("nano azure: a custom image id is allowed", cs.azure_image_allowed({"id": "/subscriptions/s/resourceGroups/r/providers/Microsoft.Compute/images/mine"}))
        try:
            from core import azure_arm_core  # noqa: F401
            from tests.azure_tf_seed import AzureArm, rgid, SP
            arm = AzureArm()
            arm.handle("PUT", rgid("rg"), {"api-version": "2023-09-01"}, {"location": "eastus"})
            put = lambda n, rf: arm.handle("PUT", rgid("rg") + "/providers/Microsoft.Compute/virtualMachines/" + n, {"api-version": "2023-09-01"},
                                           {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"}, "storageProfile": {"imageReference": rf}}})
            _check("nano azure ARM: Alpine PUT ok", put("a1", ref)["status"] in (200, 201))
            rb = put("u1", {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts", "version": "latest"})
            _check("nano azure ARM: Ubuntu PUT -> 400 PlatformImageNotFound", rb["status"] == 400 and rb["body"]["error"]["code"] == "PlatformImageNotFound")
            os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "offline"
            _check("offline azure ARM: Ubuntu PUT ok", put("u2", {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts", "version": "latest"})["status"] in (200, 201))
        except ImportError:
            pass
        print("compute images core: all checks passed")
        return 0
    finally:
        if saved is None:
            os.environ.pop("VYOMI_COMPUTE_SUBSTRATE", None)
        else:
            os.environ["VYOMI_COMPUTE_SUBSTRATE"] = saved


def test_compute_images_core():
    assert run() == 0


if __name__ == "__main__":
    raise SystemExit(run())
