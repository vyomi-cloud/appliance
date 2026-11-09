"""Cloud Run / Functions GPU config: accepted + validated + stored, scheduled CPU-only and labelled (no passthrough).
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_run_gpu.py)"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_run_core as rn  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


L = "/v2/projects/p1/locations/us-central1"
st = rn.RunStore()


def call(method, path, body=None, query=None):
    r = rn.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def gpu_tpl(**over):
    lim = {"cpu": "4", "memory": "16Gi", "nvidia.com/gpu": "1"}
    lim.update(over.pop("limits", {}))
    t = {"containers": [{"image": "gcr.io/x/app:1", "resources": {"limits": lim}}], "nodeSelector": {"accelerator": "nvidia-l4"}}
    t.update(over)
    return t


def svc(sid, tpl):
    return call("POST", L + "/services", {"template": tpl}, {"serviceId": sid})


s, o = svc("g1", gpu_tpl(gpuZonalRedundancyDisabled=True))
t = o.get("response", {}).get("template", {})
check("GPU service accepted", s == 200, o)
check("accelerator + gpu limit round-trip", t.get("nodeSelector") == {"accelerator": "nvidia-l4"} and t["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "1" and t.get("gpuZonalRedundancyDisabled") is True, t)
check("labelled GPU simulated: no passthrough", "GPU simulated: no passthrough" in t.get("annotations", {}).get("vyomi.dev/gpu-simulated", ""), t)
s, o = call("GET", L + "/services/g1")
check("get still reports GPU config + label", s == 200 and o["template"]["nodeSelector"]["accelerator"] == "nvidia-l4" and "vyomi.dev/gpu-simulated" in o["template"]["annotations"], o)
s, o = svc("plain", {"containers": [{"image": "i"}]})
check("non-GPU service has no label", s == 200 and "vyomi.dev/gpu-simulated" not in o["response"]["template"].get("annotations", {}), o)
check("unknown accelerator rejected", svc("g2", gpu_tpl(nodeSelector={"accelerator": "nvidia-h100"}))[0] == 400)
check("limit without accelerator rejected", svc("g3", gpu_tpl(nodeSelector={}))[0] == 400)
check("accelerator without gpu limit rejected", svc("g4", {"containers": [{"image": "i"}], "nodeSelector": {"accelerator": "nvidia-l4"}})[0] == 400)
check("gpu count 2 rejected", svc("g5", gpu_tpl(limits={"nvidia.com/gpu": "2"}))[0] == 400)
check("under 4 CPU rejected", svc("g6", gpu_tpl(limits={"cpu": "2"}))[0] == 400)
check("under 16Gi rejected", svc("g7", gpu_tpl(limits={"memory": "8Gi"}))[0] == 400)
check("non-bool zonal redundancy rejected", svc("g8", gpu_tpl(gpuZonalRedundancyDisabled="yes"))[0] == 400)
print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
