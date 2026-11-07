"""Nano VM runtime: Container Apps replicas / job executions / Azure VM guest views / SSM Session Manager on the in-browser VM.

The page-side half (wasm/vm: v86 VM answering scripts) cannot run here, so this exercises the REAL engine half -- the NeedVm
queue/replay protocol, the shell scripts, the parsers -- against an Alpine userland (busybox, the same as the v86 guest) in a
Docker container standing in for the VM. Nothing is mocked in the engine: every assertion reads output the script really produced.
Skips cleanly (exit 0) when Docker or the alpine-based image is unavailable.
Run: PYTHONPATH=. python3 -m pytest tests/conformance/test_nano_vm_runtime.py"""
import json
import shutil
import subprocess
import time
import uuid

import pytest

import core.azure_arm_core as _a
_a.AzureArm.STRICT_SUBSCRIPTION = False
from core.azure_arm_core import AzureArm
from core import azure_app_core as core
from core import nano_vm_runtime_core as nvr

IMAGE = "valkey/valkey:8.0.1-alpine"      # an Alpine userland; used only as a stand-in VM, never as a Container Apps image


def _docker_ok():
    return bool(shutil.which("docker")) and subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="Docker (or the alpine image) not available")
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = f"/subscriptions/{SUB}/resourceGroups/rg1"
A = RG + "/providers/Microsoft.App"
STATE = {"vm": None, "running": True}


def vm_exec(script, timeout_ms=30000):
    p = subprocess.run(["docker", "exec", STATE["vm"], "sh", "-c", script], capture_output=True, text=True, timeout=timeout_ms / 1000 + 5)
    return {"exit_code": p.returncode, "stdout": (p.stdout or "") + (p.stderr or "")}


def page(fn):
    """What nano-boot.js does around one dispatch: replay on NeedVm after running the queued scripts, then run the post scripts."""
    nvr.begin()
    for _ in range(20):
        try:
            out = fn()
        except nvr.NeedVm:
            for r in nvr.take_need():
                nvr.set_result(r["key"], json.dumps(vm_exec(r["script"], r["timeout_ms"])))
            continue
        for p in nvr.take_post():
            vm_exec(p["script"], p["timeout_ms"])
        return out
    raise AssertionError("replay did not converge")


@pytest.fixture(scope="module")
def arm():
    STATE["vm"] = "vyomi-nanovm-" + uuid.uuid4().hex[:6]
    subprocess.run(["docker", "run", "-d", "--name", STATE["vm"], IMAGE, "sleep", "900"], check=True, capture_output=True)
    nvr.attach(lambda: {"id": STATE["vm"], "cloud": "azure", "ref": "vm1"} if STATE["running"] else None,
               lambda cloud: [{"ref": "i-0123456789abcdef0", "name": "web", "ip": "10.0.0.5"}] if STATE["running"] else [])
    a = AzureArm()
    page(lambda: a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"}))
    yield a
    core.configure_runtime()
    subprocess.run(["docker", "rm", "-f", STATE["vm"]], capture_output=True)


def c(arm, m, p, b=None):
    return page(lambda: arm.handle(m, A + p, {"api-version": "2024-03-01"}, b))


def test_container_app_replica_is_a_vm_process(arm):
    assert c(arm, "PUT", "/managedEnvironments/env1", {"location": "eastus", "properties": {}})["status"] in (200, 201)
    env = c(arm, "GET", "/managedEnvironments/env1")["body"]["id"]
    r = c(arm, "PUT", "/containerApps/app1", {"location": "eastus", "properties": {"environmentId": env, "template": {
        "containers": [{"name": "main", "image": "registry.example/never-pulled:1", "command": ["sh", "-c", "echo hello-$GREETING; while true; do echo tick; sleep 1; done"],
                        "env": [{"name": "GREETING", "value": "from-env"}]}], "scale": {"minReplicas": 1, "maxReplicas": 1}}}})
    assert r["status"] in (200, 201), r
    app = next(x for x in arm.state.values() if isinstance(x, dict) and x.get("name") == "app1" and x.get("_type", "").lower().endswith("/containerapps"))
    assert app["_runtime"] and list(app["_runtime"].values())[0]["backend"] == "nano-vm", app
    time.sleep(2.5)
    # log stream = the process's real stdout
    ls = c(arm, "GET", "/containerApps/app1/logstream")
    assert ls["status"] == 200 and ls["body"]["source"] == "nano-vm", ls
    assert "hello-from-env" in ls["body"]["lines"] and "tick" in ls["body"]["lines"], ls["body"]["lines"]
    # console = a command in the VM with the container's env
    ex = c(arm, "POST", "/containerApps/app1/exec", {"command": "echo $GREETING; uname -s"})["body"]
    assert ex["exitCode"] == 0 and "from-env" in ex["output"] and "Linux" in ex["output"], ex
    assert c(arm, "POST", "/containerApps/app1/exec", {"command": "exit 3"})["body"]["exitCode"] == 3
    # replica state is the real process state
    rev = list(app["_revisions"])[0]
    reps = c(arm, "GET", f"/containerApps/app1/revisions/{rev}/replicas")["body"]["value"]
    assert reps and reps[0]["properties"]["runningState"] == "Running", reps
    assert c(arm, "GET", "/containerApps/app1/vyomiMetrics")["body"]["memoryUsage"]
    # restart really relaunches the process (new pid)
    cid = list(app["_runtime"].values())[0]["id"]
    pid0 = vm_exec(f"cat {nvr.ROOT}/{cid}/pid")["stdout"].strip()
    assert c(arm, "POST", f"/containerApps/app1/revisions/{rev}/restart")["status"] == 200
    time.sleep(1)
    pid1 = vm_exec(f"cat {nvr.ROOT}/{cid}/pid")["stdout"].strip()
    assert pid0 and pid1 and pid0 != pid1
    reasons = {e["reason"] for e in c(arm, "GET", "/containerApps/app1/events")["body"]["value"]}
    assert {"ContainerStarted", "ContainerRestarted", "ConsoleExec"} <= reasons, reasons
    dg = c(arm, "GET", "/containerApps/app1/diagnose")["body"]["value"]
    assert any(d["status"] == "Healthy" and "replica" in d["name"] for d in dg), dg
    lg = c(arm, "POST", "/managedEnvironments/env1/logs", {"tail": 50, "contains": "tick"})
    assert lg["status"] == 200 and lg["body"]["value"] and lg["body"]["value"][0]["app"] == "app1" and lg["body"]["source"] == "nano-vm"
    # stop kills the process
    c(arm, "POST", "/containerApps/app1/stop")
    time.sleep(1)
    assert "gone" in vm_exec(f"[ -d {nvr.ROOT}/{cid} ] && echo here || echo gone")["stdout"]
    assert c(arm, "POST", "/containerApps/app1/exec", {"command": "true"})["status"] == 409


def test_image_only_app_fails_honestly(arm):
    env = c(arm, "GET", "/managedEnvironments/env1")["body"]["id"]
    c(arm, "PUT", "/containerApps/imgonly", {"location": "eastus", "properties": {"environmentId": env, "template": {
        "containers": [{"name": "m", "image": "nginx:latest"}], "scale": {"minReplicas": 1}}}})
    app = next(x for x in arm.state.values() if isinstance(x, dict) and x.get("name") == "imgonly" and x.get("_type", "").lower().endswith("/containerapps"))
    err = app["properties"]["vyomiRuntime"]["error"]
    assert "not pulled" in err and "Docker" in err and not app["_runtime"], app["properties"]
    assert app["properties"]["runningStatus"] == "Failed"


def test_job_executions_are_one_shot_commands(arm):
    env = c(arm, "GET", "/managedEnvironments/env1")["body"]["id"]
    job = {"location": "eastus", "properties": {"environmentId": env, "configuration": {"triggerType": "Manual"},
           "template": {"containers": [{"name": "j", "image": "registry.example/job:1", "command": ["sh", "-c", "echo job-says-$WHO; exit 0"], "env": [{"name": "WHO", "value": "hi"}]}]}}}
    assert c(arm, "PUT", "/jobs/job1", job)["status"] in (200, 201)
    ex = c(arm, "POST", "/jobs/job1/start", {})["body"]["name"]
    assert c(arm, "GET", f"/jobs/job1/executions/{ex}")["body"]["properties"]["status"] == "Succeeded"
    lg = c(arm, "GET", f"/jobs/job1/executions/{ex}/logs")["body"]
    assert "job-says-hi" in "\n".join(lg["lines"]) and lg["exitCode"] == 0 and lg["source"] == "nano-vm" and "not pulled" in lg["lines"][0]
    job["properties"]["template"]["containers"][0]["command"] = ["sh", "-c", "echo boom >&2; exit 7"]
    c(arm, "PUT", "/jobs/job1", job)
    ex2 = c(arm, "POST", "/jobs/job1/start", {})["body"]["name"]
    assert c(arm, "GET", f"/jobs/job1/executions/{ex2}")["body"]["properties"]["status"] == "Failed"
    assert c(arm, "GET", f"/jobs/job1/executions/{ex2}/logs")["body"]["exitCode"] == 7
    assert len(c(arm, "GET", "/jobs/job1/executions")["body"]["value"]) == 2      # replays never double-record an execution
    assert any(d["status"] == "Critical" for d in c(arm, "GET", "/jobs/job1/diagnose")["body"]["value"])


def test_no_running_vm_is_honest(arm):
    STATE["running"] = False
    try:
        r = c(arm, "POST", "/containerApps/app1/exec", {"command": "id"})
        assert r["status"] == 409 and r["body"]["error"]["code"] == "RuntimeUnavailable" and "in-browser VM" in r["body"]["error"]["message"], r
        env = c(arm, "GET", "/managedEnvironments/env1")["body"]["id"]
        j = c(arm, "PUT", "/jobs/nojob", {"location": "eastus", "properties": {"environmentId": env, "configuration": {"triggerType": "Manual"},
              "template": {"containers": [{"name": "j", "image": "x", "command": ["true"]}]}}})
        ex = c(arm, "POST", "/jobs/nojob/start", {})["body"]["name"]
        assert c(arm, "GET", f"/jobs/nojob/executions/{ex}/logs")["status"] == 409      # recorded only, no output invented
        assert nvr.ssm_instances() == {}
    finally:
        STATE["running"] = True


def test_guest_views_read_the_vm():
    inv = json.loads(nvr.guest_parse("inventory", vm_exec(nvr.guest_command("inventory"))["stdout"]))
    assert inv["packageManager"] == "apk" and inv["packageCount"] > 5 and inv["os"]["kernel"], inv["os"]
    perf = json.loads(nvr.guest_parse("performance", vm_exec(nvr.guest_command("performance"))["stdout"]))
    assert perf["memTotalBytes"] > 0 and perf["cpus"] >= 1 and len(perf["loadAvg"]) == 3 and perf["topProcesses"]
    upd = json.loads(nvr.guest_parse("updates", vm_exec(nvr.guest_command("updates", "{}"))["stdout"]))
    assert upd["packageManager"] == "apk" and upd["supported"] and "pendingCount" in upd


def test_ssm_session_manager_targets_the_vm(arm):
    from core import ssm_core
    store = ssm_core.SsmStore()
    info = ssm_core._OPS["DescribeInstanceInformation"](store, {})["InstanceInformationList"]
    assert [i["InstanceId"] for i in info] == ["i-0123456789abcdef0"] and info[0]["PingStatus"] == "Online"
    s = json.loads(nvr.ssm_op("Start", json.dumps({"target": "i-0123456789abcdef0"})))
    assert s["ok"] and s["SessionId"]
    assert json.loads(nvr.ssm_op("Target", json.dumps({"session_id": s["SessionId"]})))["target"] == "i-0123456789abcdef0"
    bad = json.loads(nvr.ssm_op("Start", json.dumps({"target": "i-nope"})))
    assert not bad["ok"] and bad["code"] == "TargetNotConnected"
    assert [x["SessionId"] for x in json.loads(nvr.ssm_op("List", "{}"))["Sessions"]] == [s["SessionId"]]
    assert json.loads(nvr.ssm_op("Terminate", json.dumps({"session_id": s["SessionId"]})))["ok"]
