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
        cat = cs.NANO_CATALOG
        run_ = [e for e in cat if e["runnable"]]
        _check("nano catalog: runnable set = Alpine (default), Debian, Buildroot; Phase B 64-bit entries listed but not runnable",
               [e["key"] for e in run_] == ["alpine", "debian", "buildroot"] and [e["key"] for e in cat if not e["runnable"]] == ["debian64"] and cat[0]["default"])
        _check("nano catalog: every image states what it contains: its summary names each tool it claims, and a minimal image claims none",
               all(e["summary"] and all(t.lower() in e["summary"].lower() for t in e["tools"]) for e in run_)
               and all(e["claims"] == {"python": True, "pip": True, "git": True, "pkg": "apk" if e["key"] == "alpine" else "apt"} for e in run_ if e["key"] != "buildroot")
               and not any(cl for k, cl in cat[2]["claims"].items() if k != "pkg") and cat[2]["claims"]["pkg"] is None and "busybox shell only" in cat[2]["summary"])
        _check("nano catalog: Phase B reason is the exact owner text and the summary says riscv64 only in the description",
               all(e["reason"] == cs.PHASE_B_REASON for e in cat if not e["runnable"]) and "riscv64" in cat[3]["summary"])
        _check("nano: back-compat NANO_TOOLS / NANO_SUMMARY describe the default Alpine image", cs.NANO_TOOLS == ("Python 3", "pip", "apk", "git") and cs.NANO_SUMMARY == "Alpine Linux 3.21, 32-bit x86: Python 3, pip, apk, git")
        # AWS
        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "nano"
        s = types.SimpleNamespace()
        names, archs, body = _aws_images(s)
        _check("nano aws: the full AMI catalog is listed, every Nano catalog AMI present", all(e["aws"]["name"] in names for e in cat) and len(names) >= 10 and archs.count("i386") == len(run_))
        flags = re.findall(r"<name>([^<]*)</name>.*?<architecture>([^<]*)</architecture>.*?<vyomiRunnable>(\w+)</vyomiRunnable>", body, re.S)
        _check("nano aws: exactly the runnable catalog AMIs are flagged runnable, everything else false",
               sorted(f[0] for f in flags if f[2] == "true") == sorted(e["aws"]["name"] for e in run_) and len(flags) == len(names))
        _check("nano aws: substrate marker", "<vyomiSubstrate>nano</vyomiSubstrate>" in body)
        _check("nano aws: the disabled 64-bit AMI carries the Phase B reason", "<vyomiReason>%s</vyomiReason>" % cs.PHASE_B_REASON in body)
        for e in cat:
            _check("nano aws: DescribeImages carries the exact summary as description of %s" % e["key"], "<description>%s</description>" % e["summary"].replace("&", "&amp;") in body)
        for cloud in ("aws", "gcp", "azure"):
            _check("nano %s: spec list = catalog, first is the default Alpine" % cloud, [x["key"] for x in cs.nano_image_specs(cloud)] == [e["key"] for e in cat] and cs.NANO_IMAGES[cloud]["description"] == cs.NANO_SUMMARY)
        amis = {e["key"]: re.search(r"<imageId>([^<]+)</imageId>(?:(?!</item>).)*?<name>%s</name>" % re.escape(e["aws"]["name"]), body, re.S).group(1) for e in cat}
        ami = amis["alpine"]
        for e in run_:
            r = vpc.dispatch(s, {"Action": "RunInstances", "ImageId": amis[e["key"]], "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
            _check("nano aws: RunInstances with the %s AMI works, instance is i386" % e["key"], r.status == 200 and "<architecture>i386</architecture>" in r.body)
        r = vpc.dispatch(s, {"Action": "RunInstances", "ImageId": amis["debian64"], "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
        _check("nano aws: the 64-bit emulated Debian AMI is refused with Unsupported (400)", r.status == 400 and "<Code>Unsupported</Code>" in r.body)
        r = vpc.dispatch(s, {"Action": "RunInstances", "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
        _check("nano aws: no ImageId defaults to the Alpine AMI", r.status == 200 and ami in r.body)
        m = vpc._model(s)
        x86 = "ami-" + "0" * 17
        m["images"][x86] = {**m["images"][ami], "id": x86, "name": "Amazon Linux 2023", "architecture": "x86_64", "nano_key": None}
        r = vpc.dispatch(s, {"Action": "RunInstances", "ImageId": x86, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"})
        _check("nano aws: an x86_64 AMI is refused with Unsupported (400)", r.status == 400 and "<Code>Unsupported</Code>" in r.body)
        _check("nano aws: the x86_64 AMI is listed but flagged not runnable", x86 in _aws_images(s)[2])
        _check("nano aws: instance types advertise i386", "<item>i386</item>" in vpc.dispatch(s, {"Action": "DescribeInstanceTypes"}).body)
        # the VM host boots the image the instance uses: registry maps each instance to its catalog key
        try:
            from wasm.providers import registry as _reg
            for e in run_:
                inst_ = {"image_id": amis[e["key"]]}
                _check("nano registry: an instance of the %s AMI boots the %s image" % (e["key"], e["key"]), _reg._aws_image_key(m, inst_) == e["key"])
        except ImportError:
            pass
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
        by = {i["family"]: i for i in lst}
        _check("nano gcp: the Nano image project lists every catalog image, runnable exactly for the runnable ones",
               [i["name"] for i in lst] == [x["name"] for x in cs.nano_image_specs("gcp")] and all(by[x["family"]]["vyomiRunnable"] is x["runnable"] for x in cs.nano_image_specs("gcp")))
        _check("nano gcp: each image's description is its exact summary", all(by[x["family"]]["description"] == e["summary"] for x, e in zip(cs.nano_image_specs("gcp"), cat)))
        deb = json.loads(gce.dispatch(st, "GET", "/compute/v1/projects/debian-cloud/global/images", {}, {}, b"").body)["items"]
        _check("nano gcp: debian-cloud still lists, flagged not runnable", deb and all(i["vyomiRunnable"] is False for i in deb))
        for x in cs.nano_image_specs("gcp"):
            r_ = _gce_post(st, "i-" + x["key"], "projects/%s/global/images/family/%s" % (x["project"], x["family"]))
            _check("nano gcp: insert with the %s family %s" % (x["key"], "works" if x["runnable"] else "is refused"), (r_.status == 200) == x["runnable"])
        _check("nano gcp: the Phase B image carries its reason", by["debian-12-x86-64-emulated"]["vyomiReason"] == cs.PHASE_B_REASON)
        bad = _gce_post(st, "bad1", "projects/debian-cloud/global/images/family/debian-12")
        e = json.loads(bad.body)["error"]
        _check("nano gcp: debian-cloud image -> 404 NOT_FOUND with the Nano explanation", bad.status == 404 and e["status"] == "NOT_FOUND" and "cannot run on" in e["message"])
        inst = [v for v in st.instances.values()]
        _check("nano gcp: the booted image of an instance resolves per instance", sorted(gce.nano_image_key_of(st, i) for i in inst).count("debian") == 1 and sorted(gce.nano_image_key_of(st, i) for i in inst).count("buildroot") == 1)
        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "offline"
        st2 = gce.ComputeStore()
        _check("offline gcp: debian-12 still launches", _gce_post(st2, "d1", "projects/debian-cloud/global/images/family/debian-12").status == 200)
        _check("offline gcp: debian-cloud still lists", gce.dispatch(st2, "GET", "/compute/v1/projects/debian-cloud/global/images", {}, {}, b"").status == 200)
        # Azure
        z = a["azure"]
        ref = {"publisher": z["publisher"], "offer": z["offer"], "sku": z["sku"], "version": "latest"}
        refs = {x["key"]: {"publisher": x["publisher"], "offer": x["offer"], "sku": x["sku"], "version": "latest"} for x in cs.nano_image_specs("azure")}

        os.environ["VYOMI_COMPUTE_SUBSTRATE"] = "nano"
        _check("nano azure: runnable references allowed, the 64-bit emulated one refused",
               all(cs.azure_image_allowed(refs[e["key"]]) is e["runnable"] for e in cat))
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
