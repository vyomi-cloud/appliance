"""Compute sizes per substrate: one source (core/compute_sizes.py) drives the describe/list answers AND create-time enforcement.

Runs on host CPython and under Pyodide (the Nano engine): the substrate is forced with VYOMI_COMPUTE_SUBSTRATE and the Mesh budget
with VYOMI_MESH_CAP_MB / VYOMI_MESH_CPUS (the default 4 vCPU / 16 GB Codespace: cap 70% = 11468 MB, compute bucket half = 5734).
Run on host:  PYTHONPATH=. python3 tests/conformance/test_compute_sizes_core.py
"""
import json
import os
import re
import types

try:
    from core import compute_sizes as cs, vpc_core as vpc, gcp_compute_instances_core as gce
    from core import azure_arm_core as az
except ImportError:  # pragma: no cover - Pyodide flat layout
    import compute_sizes as cs  # type: ignore
    import vpc_core as vpc  # type: ignore
    import gcp_compute_instances_core as gce  # type: ignore
    import azure_arm_core as az  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _names(cloud, sub):
    return [r["name"] for r in cs.size_table(cloud, sub)]


def _env(sub):
    os.environ["VYOMI_COMPUTE_SUBSTRATE"] = sub
    os.environ["VYOMI_MESH_CAP_MB"] = "11468"      # 16 GB host * 70%
    os.environ["VYOMI_MESH_CPUS"] = "4"


def _aws_types(s):
    r = vpc.dispatch(s, {"Action": "DescribeInstanceTypes"})
    return re.findall(r"<instanceType>([^<]+)</instanceType>", r.body), r.body


def _run(s, itype):
    return vpc.dispatch(s, {"Action": "RunInstances", "InstanceType": itype, "MinCount": "1", "MaxCount": "1"})


def _gce_post(st, mt):
    body = {"name": "vm-" + re.sub(r"\W", "", mt), "machineType": "zones/us-central1-a/machineTypes/" + mt,
            "disks": [{"boot": True, "initializeParams": {"diskSizeGb": "10"}}]}
    return gce.dispatch(st, "POST", "/compute/v1/projects/p/zones/us-central1-a/instances", {}, {"content-type": "application/json"}, json.dumps(body).encode())


def _azure(a, method, path, body=None):
    return a.handle(method, path, {"api-version": "2023-09-01"}, body)


def run() -> int:
    saved = {k: os.environ.get(k) for k in ("VYOMI_COMPUTE_SUBSTRATE", "VYOMI_MESH_CAP_MB", "VYOMI_MESH_CPUS")}
    try:
        # 1. the tables
        _env("nano")
        _check("nano aws", _names("aws", "nano") == ["t2.nano", "t3.nano", "t3a.nano", "t2.micro", "t3.micro", "t3a.micro"])
        _check("nano gcp", _names("gcp", "nano") == ["f1-micro", "e2-micro"])
        _check("nano azure", _names("azure", "nano") == ["Standard_B1ls", "Standard_B1s"])
        _check("nano is 1 vCPU and <= 1024 MiB everywhere",
               all(r["run_vcpu"] == 1 and r["run_mem_mb"] <= 1024 for c in ("aws", "gcp", "azure") for r in cs.size_table(c, "nano")))
        _check("nano keeps the REAL spec next to the honoured one", next(r for r in cs.size_table("aws", "nano") if r["name"] == "t3.micro")
               == {"name": "t3.micro", "vcpu": 2, "mem_mb": 1024, "run_vcpu": 1, "run_mem_mb": 1024})
        _check("nano VM RAM follows the size", cs.nano_vm_mem_mb("t3.micro") == 1024 and cs.nano_vm_mem_mb("t3.nano") == 512
               and cs.nano_vm_mem_mb("m5.24xlarge") is None)
        _env("mesh")
        lim = cs.limits("mesh")
        _check("mesh per-instance cap derived from the 16 GB budget", lim["compute_bucket_mb"] == 5734 and lim["max_mem_mb"] == 4300 and lim["vcpu"] == 4)
        _check("mesh aws up to 4 GiB", max(r["mem_mb"] for r in cs.size_table("aws", "mesh")) == 4096 and "t3.medium" in _names("aws", "mesh")
               and "t3.large" not in _names("aws", "mesh"))
        _check("mesh gcp", _names("gcp", "mesh") == ["f1-micro", "e2-micro", "g1-small", "e2-small", "e2-medium"])
        _check("mesh azure", "Standard_B2s" in _names("azure", "mesh") and "Standard_B2ms" not in _names("azure", "mesh"))
        os.environ["VYOMI_MESH_CAP_MB"] = "8192"          # a 2-core / 8 GB Codespace: the list shrinks, it is not hard-coded
        os.environ["VYOMI_MESH_CPUS"] = "2"
        _check("mesh list shrinks on a small host", "t3.medium" not in _names("aws", "mesh") and "t3.small" in _names("aws", "mesh"))
        _env("offline")
        _check("offline appliance stays unrestricted", cs.allowed_names("aws") is None and cs.is_allowed("aws", "m5.8xlarge"))

        # 2. AWS: describe lists only runnable sizes; RunInstances refuses the rest (EC2 `Unsupported`)
        for sub in ("nano", "mesh"):
            _env(sub)
            s = types.SimpleNamespace()
            listed, body = _aws_types(s)
            _check(f"{sub}: DescribeInstanceTypes == the table", sorted(listed) == sorted(n for n in _names("aws", sub) if n in vpc._INSTANCE_TYPES))
            _check(f"{sub}: no big type listed", not any(t in listed for t in ("m5.2xlarge", "r5.xlarge", "m5.xlarge", "c5.xlarge")))
            _check(f"{sub}: substrate marker", f"<vyomiSubstrate>{sub}</vyomiSubstrate>" in body)
            bad = _run(s, "m5.2xlarge")
            _check(f"{sub}: RunInstances m5.2xlarge refused", bad.status == 400 and "<Code>Unsupported</Code>" in bad.body)
            ok = _run(s, "t3.micro")
            _check(f"{sub}: RunInstances t3.micro works", ok.status == 200)
        _env("offline")
        _check("offline: m5.2xlarge still lists", "m5.2xlarge" in _aws_types(types.SimpleNamespace())[0])

        # 3. GCP
        for sub, good, bad in (("nano", "e2-micro", "e2-medium"), ("mesh", "e2-medium", "e2-standard-4")):
            _env(sub)
            st = gce.ComputeStore()
            r = gce.dispatch(st, "GET", "/compute/v1/projects/p/zones/us-central1-a/machineTypes", {}, {}, b"")
            got = [m["name"] for m in json.loads(r.body)["items"]]
            _check(f"{sub}: machineTypes.list == the table", got == _names("gcp", sub) or sorted(got) == sorted(_names("gcp", sub)))
            _check(f"{sub}: machineTypes.get big type 404", gce.dispatch(st, "GET", "/compute/v1/projects/p/zones/us-central1-a/machineTypes/" + bad, {}, {}, b"").status == 404)
            _check(f"{sub}: insert {good} ok", _gce_post(st, good).status == 200)
            rb = _gce_post(st, bad)
            e = json.loads(rb.body)["error"]
            _check(f"{sub}: insert {bad} -> 400 INVALID_ARGUMENT", rb.status == 400 and e["status"] == "INVALID_ARGUMENT" and "cannot run on" in e["message"])
        _env("offline")
        _check("offline: insert e2-standard-4 ok", _gce_post(gce.ComputeStore(), "e2-standard-4").status == 200)

        # 4. Azure
        try:
            from tests.azure_tf_seed import AzureArm, rgid, SP   # host only (Pyodide runs the AWS/GCP halves + tables)
            azure_cases = (("nano", "Standard_B1s", "Standard_B2s"), ("mesh", "Standard_B2s", "Standard_D4s_v5"))
        except ImportError:
            azure_cases = ()
        for sub, good, bad in azure_cases:
            _env(sub)
            a = AzureArm()
            _azure(a, "PUT", rgid("rg"), {"location": "eastus"})
            r = _azure(a, "GET", SP + "/providers/Microsoft.Compute/locations/eastus/vmSizes")
            got = [v["name"] for v in r["body"]["value"]]
            _check(f"{sub}: vmSizes == the table", sorted(got) == sorted(_names("azure", sub)))
            vm = lambda n, s_: _azure(a, "PUT", rgid("rg") + "/providers/Microsoft.Compute/virtualMachines/" + n,
                                      {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": s_}}})
            _check(f"{sub}: PUT {good} ok", vm("ok", good)["status"] in (200, 201))
            rb = vm("big", bad)
            _check(f"{sub}: PUT {bad} -> 409 SkuNotAvailable", rb["status"] == 409 and rb["body"]["error"]["code"] == "SkuNotAvailable")
        print("compute sizes core: all checks passed")
        return 0
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_compute_sizes_core():
    assert run() == 0


if __name__ == "__main__":
    raise SystemExit(run())
