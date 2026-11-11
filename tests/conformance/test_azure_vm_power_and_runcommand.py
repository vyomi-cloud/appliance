"""Azure VM power actions drive the compute backend; runCommand execs in the guest container.
Metadata-only VMs (no container) keep the old behaviour. Uses a FAKE backend (no Docker).
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python tests/conformance/test_azure_vm_power_and_runcommand.py"""
import types
from core import azure_arm_core as m
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


class Fake:
    def __init__(self):
        self.calls, self.st, self.fail = [], "running", False

    def _c(self, n):
        self.calls.append(n)
        if self.fail:
            raise RuntimeError("boom")

    def stop(self, i): self._c("stop"); self.st = "stopped"
    def start(self, i): self._c("start"); self.st = "running"
    def reboot(self, i): self._c("reboot")
    def status(self, i): return self.st

    def exec(self, i, cmd, stdin=None):
        self.calls.append(("exec", cmd))
        return types.SimpleNamespace(returncode=3, stdout=b"hello\n", stderr=b"oops\n")


def run():
    V = {"api-version": "2023-09-01"}
    a = AzureArm()
    a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/g", {"api-version": "2021-04-01"}, {"location": "eastus"})
    base = f"/subscriptions/{SUB}/resourceGroups/g/providers/Microsoft.Compute/virtualMachines/"
    body = {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"},
            "osProfile": {"computerName": "v", "adminUsername": "u"}}}
    for n in ("dock", "meta"):
        _check("PUT " + n, a.handle("PUT", base + n, V, dict(body))["status"] in (200, 201))
    a.state[(base + "dock").lower()]["properties"]["runtime"] = {"backend": "docker", "containerName": "vyomi-i-az-1", "instanceId": "az-1"}
    a.state[(base + "meta").lower()]["properties"].pop("runtime", None)
    fake = Fake()
    orig = m._vm_compute
    m._vm_compute = lambda rec: (fake, object()) if (rec.get("properties", {}).get("runtime") or {}).get("containerName") else None
    try:
        post = lambda vm, act, b=None: a.handle("POST", base + vm + "/" + act, V, b)
        for act, calls, ps in (("powerOff", ["stop"], "stopped"), ("start", ["start"], "running"),
                               ("deallocate", ["stop"], "deallocated"), ("restart", ["start"], "running")):
            fake.calls.clear()
            r = post("dock", act)
            _check(f"{act} 200", r["status"] == 200)
            _check(f"{act} backend {calls}", fake.calls == calls)
            _check(f"{act} powerState", a.state[(base + "dock").lower()]["properties"]["powerState"] == "PowerState/" + ps)
        post("dock", "start"); fake.calls.clear()
        post("dock", "restart")
        _check("restart on running reboots", fake.calls == ["reboot"])
        fake.fail = True
        r = post("dock", "powerOff")
        _check("backend failure never 500s, ARM state kept",
               r["status"] == 200 and a.state[(base + "dock").lower()]["properties"]["powerState"] == "PowerState/stopped")
        fake.fail = False
        fake.calls.clear()
        r = post("meta", "powerOff")
        _check("metadata-only: no backend call, ARM state changes",
               r["status"] == 200 and fake.calls == [] and "metadata-only" in r["body"]["note"])
        post("meta", "start")

        post("dock", "start"); fake.calls.clear(); fake.st = "running"
        r = post("dock", "runCommand", {"commandId": "RunShellScript", "script": ["echo hi; exit 3"]})
        v = r["body"]["value"][0]
        _check("exec via backend with timeout+sh -c", fake.calls and fake.calls[0][1][:4] == ["timeout", "60", "sh", "-c"])
        _check("stdout/stderr formatted", "[stdout]\nhello\n" in v["message"] and "[stderr]\noops\n" in v["message"]
               and v["message"].startswith("Enable failed: "))
        fake.exec = lambda i, c, stdin=None: types.SimpleNamespace(returncode=0, stdout=b"ok\n", stderr=b"")
        v = post("dock", "runCommand", {"script": ["echo hi"]})["body"]["value"][0]
        _check("success shape", v["code"] == "ProvisioningState/succeeded" and v["level"] == "Info"
               and v["displayStatus"] == "Provisioning succeeded" and v["message"].startswith("Enable succeeded: \n[stdout]\nok\n"))
        # IMDS path unchanged: not run in guest
        fake.calls.clear()
        r = post("dock", "runCommand", {"script": ["curl -H Metadata:true 'http://169.254.169.254/metadata/identity/oauth2/token?resource=https://x/'"]})
        _check("IMDS emulation not sent to guest", not any(isinstance(c, tuple) for c in fake.calls)
               and "invalid_request" in r["body"]["value"][0]["message"])
        # no container: honest message
        r = post("meta", "runCommand", {"script": ["rm -rf /"]})
        _check("no container: honest not-recognized message, nothing executed",
               "nothing was executed" in r["body"]["value"][0]["message"])
        r = post("meta", "runCommand", {"script": ["hostname"]})
        _check("no container: emulated hostname", r["body"]["value"][0]["message"] == "v")
    finally:
        m._vm_compute = orig


if __name__ == "__main__":
    run()
    print("PASS")
