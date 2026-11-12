"""Container Apps tools backed by REAL Docker containers: log stream, console (exec), restart, metrics (docker stats), events,
diagnose, job executions (one-shot containers with real exit codes + logs). Skips cleanly when Docker is unavailable.
Run: PYTHONPATH=. python3 -m pytest tests/conformance/test_azure_containerapps_runtime_tools.py"""
import shutil
import subprocess
import time
import pytest

import core.azure_arm_core as _a
_a.AzureArm.STRICT_SUBSCRIPTION = False
from core.azure_arm_core import AzureArm
from core import azure_app_core as core

IMAGE = "valkey/valkey:8.0.1-alpine"


def _docker_ok():
    if not shutil.which("docker"):
        return False
    p = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    return p.returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(), reason=f"Docker (or image {IMAGE}) not available")
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = f"/subscriptions/{SUB}/resourceGroups/rg1"
A = RG + "/providers/Microsoft.App"


@pytest.fixture(scope="module")
def arm():
    import os
    os.environ["VYOMI_AZURE_APP_RUNTIME"] = "docker"
    from providers import azure_app_runtime
    azure_app_runtime.attach()
    a = AzureArm()
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    yield a
    for r in list(a.state.values()):
        if isinstance(r, dict) and str(r.get("_type", "")).lower().endswith("/containerapps"):
            azure_app_runtime.deprovision_container_app(r)
    core.configure_runtime()


def c(arm, m, p, b=None):
    return arm.handle(m, A + p, {"api-version": "2024-03-01"}, b)


def test_tools_use_the_real_container(arm):
    assert c(arm, "PUT", "/managedEnvironments/env1", {"location": "eastus", "properties": {}})["status"] in (200, 201)
    env = c(arm, "GET", "/managedEnvironments/env1")["body"]["id"]
    r = c(arm, "PUT", "/containerApps/app1", {"location": "eastus", "properties": {"environmentId": env, "template": {
        "containers": [{"name": "main", "image": IMAGE, "env": [{"name": "GREETING", "value": "hello-from-env"}]}], "scale": {"minReplicas": 1, "maxReplicas": 2}}}})
    assert r["status"] in (200, 201), r
    app = next(x for x in arm.state.values() if isinstance(x, dict) and x.get("name") == "app1" and x.get("_type", "").lower().endswith("/containerapps"))
    assert app["_runtime"], app["properties"].get("vyomiRuntime")
    time.sleep(2)
    # Console/exec returns real container output
    r = c(arm, "POST", "/containerApps/app1/exec", {"command": "echo $GREETING; uname -s"})
    assert r["status"] == 200 and r["body"]["exitCode"] == 0 and "hello-from-env" in r["body"]["output"] and "Linux" in r["body"]["output"], r
    assert c(arm, "POST", "/containerApps/app1/exec", {"command": "exit 3"})["body"]["exitCode"] == 3
    # Log stream shows what the server process really logged
    r = c(arm, "GET", "/containerApps/app1/logstream")
    assert r["status"] == 200 and r["body"]["source"] == "docker" and any("Ready to accept connections" in l or "valkey" in l.lower() for l in r["body"]["lines"]), r
    # Metrics are docker stats
    assert c(arm, "GET", "/containerApps/app1/vyomiMetrics")["body"]["memoryUsage"]
    # Restart: the container really restarts (uptime resets -> container StartedAt changes)
    cid = list(app["_runtime"].values())[0]["id"]
    t0 = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", cid], capture_output=True, text=True).stdout.strip()
    time.sleep(1.1)
    rev = list(app["_revisions"])[0]
    assert c(arm, "POST", f"/containerApps/app1/revisions/{rev}/restart")["status"] == 200
    t1 = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", cid], capture_output=True, text=True).stdout.strip()
    assert t0 != t1
    ev = c(arm, "GET", "/containerApps/app1/events")["body"]["value"]
    reasons = {e["reason"] for e in ev}
    assert {"ContainerStarted", "ContainerRestarted", "ConsoleExec"} <= reasons, reasons
    dg = c(arm, "GET", "/containerApps/app1/diagnose")["body"]["value"]
    assert any(d["status"] == "Healthy" and "replica" in d["name"] for d in dg), dg
    # environment tools
    lg = c(arm, "POST", "/managedEnvironments/env1/logs", {"tail": 50})
    assert lg["status"] == 200 and lg["body"]["value"] and lg["body"]["value"][0]["app"] == "app1"
    assert any(d["name"].startswith("app1:") for d in c(arm, "GET", "/managedEnvironments/env1/diagnose")["body"]["value"])
    # stopped app: no running replica
    c(arm, "POST", "/containerApps/app1/stop")
    assert c(arm, "POST", "/containerApps/app1/exec", {"command": "true"})["status"] == 409


def test_job_executions_are_real_containers(arm):
    env = c(arm, "GET", "/managedEnvironments/env1")["body"]["id"]
    job = {"location": "eastus", "identity": {"type": "SystemAssigned"}, "properties": {"environmentId": env, "configuration": {"triggerType": "Manual"},
           "template": {"containers": [{"name": "j", "image": IMAGE, "command": ["sh", "-c", "echo job-says-$WHO; exit 0"], "env": [{"name": "WHO", "value": "hi"}]}]}}}
    r = c(arm, "PUT", "/jobs/job1", job)
    assert r["status"] in (200, 201) and r["body"]["identity"]["type"] == "SystemAssigned", r
    ex = c(arm, "POST", "/jobs/job1/start", {})["body"]["name"]
    assert c(arm, "GET", f"/jobs/job1/executions/{ex}")["body"]["properties"]["status"] == "Succeeded"
    lg = c(arm, "GET", f"/jobs/job1/executions/{ex}/logs")["body"]
    assert "job-says-hi" in "\n".join(lg["lines"]) and lg["exitCode"] == 0
    job["properties"]["template"]["containers"][0]["command"] = ["sh", "-c", "echo boom >&2; exit 7"]
    c(arm, "PUT", "/jobs/job1", job)
    ex2 = c(arm, "POST", "/jobs/job1/start", {})["body"]["name"]
    assert c(arm, "GET", f"/jobs/job1/executions/{ex2}")["body"]["properties"]["status"] == "Failed"
    assert c(arm, "GET", f"/jobs/job1/executions/{ex2}/logs")["body"]["exitCode"] == 7
    assert any(d["status"] == "Critical" for d in c(arm, "GET", "/jobs/job1/diagnose")["body"]["value"])
    assert {e["reason"] for e in c(arm, "GET", "/jobs/job1/events")["body"]["value"]} >= {"ExecutionSucceeded", "ExecutionFailed"}


def test_no_runtime_is_honest():
    core.configure_runtime()          # Nano / no Docker
    a = AzureArm()
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    c(a, "PUT", "/managedEnvironments/e", {"location": "eastus", "properties": {}})
    env = c(a, "GET", "/managedEnvironments/e")["body"]["id"]
    r0 = c(a, "PUT", "/containerApps/x", {"location": "eastus", "properties": {"environmentId": env, "template": {"containers": [{"name": "m", "image": "nginx"}], "scale": {"minReplicas": 1}}}})
    assert r0["status"] in (200, 201), r0
    r = c(a, "POST", "/containerApps/x/exec", {"command": "id"})
    assert r["status"] == 409 and r["body"]["error"]["code"] == "RuntimeUnavailable"
