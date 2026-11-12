"""The appliance's served ARM (providers/azure_services.py) drives Docker-backed Azure VMs: powerOff/deallocate stop the container,
start/restart follow, runCommand execs in the guest. (The earlier test only covered core.azure_arm_core, which the appliance does not
serve for these routes, so the bug survived it.) FAKE backend, no Docker.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python tests/conformance/test_azure_provider_vm_compute.py"""
import types
from core import azure_arm_core as core
from providers import azure_services as prov


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


class Fake:
    def __init__(self): self.calls, self.st = [], "running"
    def stop(self, i): self.calls.append("stop"); self.st = "stopped"
    def start(self, i): self.calls.append("start"); self.st = "running"
    def reboot(self, i): self.calls.append("reboot")
    def status(self, i): return self.st
    def exec(self, i, cmd, stdin=None):
        self.calls.append(("exec", cmd))
        return types.SimpleNamespace(returncode=0, stdout=b"hello\n", stderr=b"")


rid = "/subscriptions/s/resourceGroups/g/providers/Microsoft.Compute/virtualMachines/vm1"
rec = {"id": rid, "name": "vm1", "_type": "Microsoft.Compute/virtualMachines",
       "properties": {"runtime": {"backend": "docker", "containerName": "vyomi-i-az-1", "instanceId": "az-1"}}}
prov._state[rid.lower()] = rec
fake = Fake()
orig = core._vm_compute
core._vm_compute = lambda r: (fake, object()) if (r.get("properties", {}).get("runtime") or {}).get("backend") == "docker" else None
try:
    chain = ["Microsoft.Compute", "virtualMachines"]
    for act, calls, ps in (("poweroff", ["stop"], "stopped"), ("start", ["start"], "running"),
                           ("deallocate", ["stop"], "deallocated")):
        fake.calls.clear()
        prov._state[rid.lower()] = rec   # the module state can be reloaded between calls in a bare test process
        r = prov._arm_action(act, chain, "vm1", rid)
        _check(f"{act} 200 {r.body[:200]}", r.status_code == 200)
        _check(f"{act} drove backend {calls}", fake.calls == calls)
        _check(f"{act} powerState", rec["properties"]["powerState"] == "PowerState/" + ps)
    fake.calls.clear(); fake.st = "running"
    rc = prov._vm_run_executor(rec, "echo hello")
    _check("runCommand execs in the guest", rc == (0, "hello\n", "") and fake.calls and fake.calls[0][0] == "exec")
    fake.st = "stopped"
    _check("runCommand on a stopped VM -> not run", prov._vm_run_executor(rec, "echo hi") is None)
finally:
    core._vm_compute = orig
    prov._state.pop(rid.lower(), None)
print("PASS")

# ---- the served ARM view/validate/disks (same provider the Mesh serves) ----
import asyncio, json
from core import azure_compute_disks_vm as vmd
v = prov._view({"id": rid, "name": "vm1", "properties": {"osProfile": {"adminUsername": "u", "adminPassword": "Secret-Pass1!"}}})
assert "adminPassword" not in json.dumps(v) and v["properties"]["osProfile"]["adminUsername"] == "u"; print("  ok  GET/PUT view never echoes adminPassword")
bad = vmd.validate_password({"properties": {"osProfile": {"adminPassword": "123"}}})
assert bad and bad["status"] == 400 and bad["body"]["error"]["code"] == "InvalidParameter"; print("  ok  short password -> 400 InvalidParameter")
print("PASS provider view")
