#!/usr/bin/env python3
"""Post-create probe (offline): an Azure Container App must really run its image.

  python3 azure_container_app.py http://localhost:9000

PUT containerApps (nginx:alpine, external ingress, targetPort 80) -> a docker container exists -> the shown
`properties.vyomiEndpoint` serves nginx's page from THIS machine -> replica state is the container's real state
-> stop removes it -> start recreates it -> DELETE removes it (no leak). Findings: POST_CREATE_UNUSABLE.
"""
import json, os, subprocess, sys, time, urllib.request

BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
SUB, RG, APP, API = "00000000-0000-0000-0000-cloudlearn01", "probe-ca-rg", "probeca", "2024-03-01"
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1
    return ok


def call(method, path, body=None, timeout=150):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = r.read()
        return json.loads(d) if d else {}


def containers(app_id):
    out = subprocess.run(["docker", "ps", "-aq", "--filter", f"label=vyomi.azure.app={app_id}"], capture_output=True, text=True).stdout
    return out.split()


def fetch(url):
    for _ in range(15):
        try:
            return urllib.request.urlopen(url, timeout=5).read().decode()
        except Exception:
            time.sleep(1)
    return ""


call("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}?api-version=2021-04-01", {"location": "eastus"})
P = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.App/containerApps/{APP}"
try:
    app = call("PUT", f"{P}?api-version={API}", {"location": "eastus", "properties": {
        "configuration": {"ingress": {"external": True, "targetPort": 80}},
        "template": {"containers": [{"name": "web", "image": "nginx:alpine", "env": [{"name": "FOO", "value": "bar"}]}]}}})
    aid = app["id"]
    check(len(containers(aid)) == 1, "a container exists for the app", f"containers={containers(aid)}")
    ep = app["properties"].get("vyomiEndpoint")
    check(bool(ep), "the app shows a reachable endpoint (properties.vyomiEndpoint)", str(app["properties"].get("vyomiRuntime")))
    check("nginx" in fetch(ep or "http://127.0.0.1:1").lower(), "GET endpoint from this machine returns nginx's page")
    cid = (containers(aid) or [""])[0]
    env = subprocess.run(["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", cid], capture_output=True, text=True).stdout
    check("FOO=bar" in env, "app env vars reach the container")
    rev = app["properties"]["latestRevisionName"]
    reps = call("GET", f"{P}/revisions/{rev}/replicas?api-version={API}")["value"]
    check(bool(reps) and reps[0]["properties"]["runningState"] == "Running", "replica runningState is the container's real state")
    call("POST", f"{P}/stop?api-version={API}", {})
    check(len(containers(aid)) == 0, "stop removes the container", str(containers(aid)))
    app2 = call("POST", f"{P}/start?api-version={API}", {})
    check(len(containers(aid)) == 1, "start runs it again", str(containers(aid)))
    call("DELETE", f"{P}?api-version={API}")
    check(len(containers(aid)) == 0, "DELETE removes the container (no leak)", str(containers(aid)))
    bad = call("PUT", f"{P}x?api-version={API}", {"location": "eastus", "properties": {
        "configuration": {"ingress": {"external": True, "targetPort": 80}},
        "template": {"containers": [{"name": "web", "image": "vyomi.invalid/nope:0"}]}}}, timeout=200)
    check(bad["properties"].get("runningStatus") == "Failed", "an image that cannot start is reported Failed, not Running", str(bad["properties"].get("vyomiRuntime")))
    call("DELETE", f"{P}x?api-version={API}")
finally:
    try:
        call("DELETE", f"/subscriptions/{SUB}/resourcegroups/{RG}?api-version=2021-04-01")
    except Exception:
        pass
sys.exit(1 if fails else 0)
