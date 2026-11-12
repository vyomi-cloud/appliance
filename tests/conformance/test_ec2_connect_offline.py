"""EC2 Connect on the offline appliance (AWS-05): connect-info returns the working ssh command + key download for a Docker-backed
instance, the console exec endpoint runs commands through the compute backend, a stopped/unknown instance is refused, and the
metrics sampler publishes the container's counters. The Docker daemon is replaced by a recording stub so the test is hermetic
(the same endpoints were also verified against a live container by the worker).

Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ec2_connect_offline.py
"""
import os
import subprocess
import sys

os.environ.setdefault("CLOUDLEARN_READINESS_GATE", "disabled")
sys.dont_write_bytecode = True

import server as S  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import ec2_metrics_core as em  # noqa: E402


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.cpu = {}      # per-instance counters: stale instances restored from local state share this stub
        self.n = {}

    def ssh_info(self, inst):
        return {"user": "ubuntu", "container_ip": "172.17.0.9", "routable_ip": None, "published_port": 43999}

    def ipv4(self, inst):
        return "172.17.0.9"

    def status(self, inst):
        return "running"

    def exec(self, inst, cmd, stdin=None):
        self.calls.append(cmd)
        if cmd == em.READ_COUNTERS_CMD:
            key = inst.instance_id
            self.cpu[key] = self.cpu.get(key, 1_000_000) + 6_000_000
            self.n[key] = n = self.n.get(key, 0) + 1
            out = (f"Inter-|\n face |\n  eth0: {1000 * n} 10 0 0 0 0 0 0 {500 * n} 5 0 0 0 0 0 0\n{em.SECTION_CPU}\nusage_usec {self.cpu[key]}\n"
                   f"{em.SECTION_IO}\n254:0 rbytes=0 wbytes={4096 * n} rios=0 wios={n}\n")
            return subprocess.CompletedProcess(cmd, 0, out.encode(), b"")
        return subprocess.CompletedProcess(cmd, 0, b"hello-from-container\n__VYOMI_CWD__/root\n", b"")


def main():
    fake = FakeDocker()
    S._docker_compute = lambda: fake
    iid = "i-0conformtest0001"
    S.ec2_state.setdefault("instances", {}).pop("gce-d52dcadb8b79", None)   # leftover from a manual live check, if any
    S.ec2_state.setdefault("instances", {})[iid] = {"instance_id": iid, "state": "running", "console_backend": "docker-exec", "runtime_backend": "docker",
                                                    "vcpus": 2, "ssh_host_port": 43999, "container_name": "vyomi-" + iid, "monitoring": True}
    c = TestClient(S.app)

    r = c.get(f"/api/aws/ec2/instances/{iid}/connect-info")
    j = r.json()
    _check("connect-info ok for a running Docker instance", r.status_code == 200 and j["ok"] and j["backend"] == "docker")
    _check("ssh command targets the published port as ubuntu", "-p 43999" in j["ssh"]["command"] and j["ssh"]["user"] == "ubuntu")
    _check("private key downloadable", c.get(j["ssh"]["key_download_url"]).status_code == 200)
    _check("unknown instance is a 404", c.get("/api/aws/ec2/instances/i-nope/connect-info").status_code == 404)

    r = c.post(f"/api/ec2/instances/{iid}/console/exec", json={"command": "echo hello-from-container"})
    _check("console exec runs through the compute backend", r.status_code == 200 and "hello-from-container" in r.json().get("output", ""))

    S.ec2_state["instances"][iid]["state"] = "stopped"
    _check("stopped instance refuses connect (409)", c.get(f"/api/aws/ec2/instances/{iid}/connect-info").status_code == 409)
    S.ec2_state["instances"][iid]["state"] = "running"

    # metrics sampler: two passes -> CloudWatch gets real deltas
    S._EC2_METRICS_PREV.clear()
    t = 1_000_000.0
    first = S._ec2_collect_metrics_once(now=t, force=True)
    _check("first pass samples the running Docker instance (baseline)", iid in first)
    _check("second pass samples it again", iid in S._ec2_collect_metrics_once(now=t + 60, force=True))
    from core import cloudwatch_core as cw
    from routes import aws_cloudwatch
    s = cw._series(aws_cloudwatch.get_store(), "AWS/EC2", "CPUUtilization", [{"Name": "InstanceId", "Value": iid}], create=False)
    _check("CPUUtilization published = 6 s CPU / (60 s x 2 vCPUs) = 5%", s and abs(s["points"][-1][1] - 5.0) < 1e-6)
    _check("EBS volume series published for the root volume",
           cw._series(aws_cloudwatch.get_store(), "AWS/EBS", "VolumeWriteOps", [{"Name": "VolumeId", "Value": "vol-" + iid.replace("i-", "")}], create=False) is not None)
    S.ec2_state["instances"].pop(iid, None)
    print("EC2 Connect + metrics sampler (offline): all green")


if __name__ == "__main__":
    main()
