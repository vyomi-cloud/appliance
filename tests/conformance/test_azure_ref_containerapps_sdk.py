"""Azure reference app lane 7: a Container App really RUNS and answers on its ingress, through the real azure-mgmt-appcontainers client.
Image vyomi/python-app + a source bundle (env VYOMI_APP_SOURCE_B64) = a sandboxed Python process (no Docker needed). env/secretRef, revisions + traffic
weights, stop/start/delete, ingress by path / revision / Host header, sandbox egress + filesystem confinement.
Run: PYTHONPATH=. python tests/conformance/test_azure_ref_containerapps_sdk.py"""
import base64, io, json, os, sys, time, zipfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
PASS, FAIL = [], []

APP_SRC = r'''
import os, json, http.server, urllib.request
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): print("request", self.command, self.path, flush=True)
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/env"):
            return self._send(200, {k: os.environ.get(k) for k in ("PORT", "GREETING", "API_KEY", "CONTAINER_APP_NAME", "CONTAINER_APP_REVISION", "VYOMI_ENDPOINT", "HOST_SECRET_PROBE")} | {"host": self.headers.get("host")})
        if self.path.startswith("/sim"):
            return self._send(200, {"status": urllib.request.urlopen(os.environ["VYOMI_ENDPOINT"] + "/healthz", timeout=10).status})
        if self.path.startswith("/egress"):
            try: urllib.request.urlopen("http://example.com", timeout=5); return self._send(200, {"egress": True})
            except Exception as e: return self._send(200, {"egress": False, "err": type(e).__name__})
        if self.path.startswith("/file"):
            try: open("/etc/passwd").read(); return self._send(200, {"read": True})
            except Exception as e: return self._send(200, {"read": False, "err": type(e).__name__})
        self._send(200, {"ok": True, "path": self.path})
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0); body = self.rfile.read(n)
        self._send(200, {"echo": json.loads(body or "{}"), "path": self.path})
http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''


def step(name, fn):
    try:
        out = fn()
        PASS.append(name); print("PASS", name, "" if out is None else str(out)[:100])
    except Exception as e:  # noqa: BLE001
        FAIL.append(name); print("FAIL", name, type(e).__name__, str(e)[:300])


def bundle():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("app.py", APP_SRC)
    return base64.b64encode(b.getvalue()).decode()


def main():
    try:
        import azure.mgmt.appcontainers  # noqa: F401
    except ImportError as e:
        print("SKIP azure-mgmt-appcontainers missing:", e); return 0
    from tests.conformance._az_tls_server import start
    tls, http, ca = start()
    import requests
    from azure.core.credentials import AccessToken

    class Cred:
        def get_token(self, *a, **k): return AccessToken("t", int(time.time()) + 3600)
    SUB = "00000000-0000-0000-0000-cloudlearn01"
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    ResourceManagementClient(Cred(), SUB, base_url=tls).resource_groups.create_or_update("rg", {"location": "eastus"})
    ca_c = ContainerAppsAPIClient(Cred(), SUB, base_url=tls, polling_interval=0)
    S = {}
    ca_c.managed_environments.begin_create_or_update("rg", "facilities-env", {"location": "eastus", "properties": {}}).result()
    env_id = ca_c.managed_environments.get("rg", "facilities-env").id

    def body(greeting, mode="Single", weights=None):
        ing = {"external": True, "targetPort": 8080}
        if weights:
            ing["traffic"] = weights
        return {"location": "eastus", "properties": {"managedEnvironmentId": env_id, "configuration": {
            "activeRevisionsMode": mode, "ingress": ing, "secrets": [{"name": "api-key", "value": "s3cret-value"}]},
            "template": {"containers": [{"name": "supervisor", "image": "vyomi/python-app:latest", "env": [
                {"name": "VYOMI_APP_SOURCE_B64", "value": bundle()}, {"name": "GREETING", "value": greeting}, {"name": "API_KEY", "secretRef": "api-key"}]}],
                "scale": {"minReplicas": 1, "maxReplicas": 3}}}}

    def create():
        a = ca_c.container_apps.begin_create_or_update("rg", "facilities-supervisor", body("hello")).result()
        S["app"] = a
        assert a.latest_revision_fqdn and a.configuration.ingress.fqdn
        S["url"] = ca_c.container_apps.get("rg", "facilities-supervisor").as_dict()["vyomi_ingress_url"] if False else None
        return a.latest_revision_fqdn
    step("arm: managed environment + container app (vyomi/python-app + source bundle)", create)

    def url():
        import azure.core.rest as rest
        r = ca_c._client.send_request(rest.HttpRequest("GET", f"{tls}/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.App/containerApps/facilities-supervisor?api-version=2024-03-01"))
        d = r.json()
        S["url"] = d["properties"]["vyomiIngressUrl"]
        assert S["url"].endswith("/azure-data/containerapps/facilities-supervisor/")
        assert d["properties"]["vyomiRuntime"]["backend"] == "sandbox-process", d["properties"].get("vyomiRuntime")
        return S["url"]
    step("arm: the resource carries properties.vyomiIngressUrl + vyomiRuntime (sandbox-process)", url)

    def env():
        j = requests.get(S["url"] + "env", timeout=60).json()
        assert j["GREETING"] == "hello" and j["API_KEY"] == "s3cret-value", j            # env + secretRef resolved
        assert j["CONTAINER_APP_NAME"] == "facilities-supervisor" and j["PORT"], j
        return j["PORT"]
    step("ingress (path form): the app answers; env and secretRef reach the process", env)
    step("ingress: POST with a JSON body is proxied", lambda: requests.post(S["url"] + "query", json={"prompt": "hi"}, timeout=30).json()["echo"] == {"prompt": "hi"} or (_ for _ in ()).throw(AssertionError("echo")))
    step("ingress: Host header form (<app>.<domain>.azurecontainerapps.io)", lambda: requests.get(tls + "/env", headers={"Host": S["app"].configuration.ingress.fqdn}, timeout=30).json()["GREETING"] == "hello" or (_ for _ in ()).throw(AssertionError("host form")))
    step("sandbox: the app calls the simulator (loopback)", lambda: requests.get(S["url"] + "sim", timeout=30).json() == {"status": 200} or (_ for _ in ()).throw(AssertionError("sim")))
    step("sandbox: no internet egress", lambda: requests.get(S["url"] + "egress", timeout=30).json()["egress"] is False or (_ for _ in ()).throw(AssertionError("egress open")))
    step("sandbox: host files unreadable", lambda: requests.get(S["url"] + "file", timeout=30).json()["read"] is False or (_ for _ in ()).throw(AssertionError("read ok")))
    step("sandbox: host environment not inherited", lambda: requests.get(S["url"] + "env", timeout=30).json()["HOST_SECRET_PROBE"] is None or (_ for _ in ()).throw(AssertionError("leak")))

    def revisions():
        revs = list(ca_c.container_apps_revisions.list_revisions("rg", "facilities-supervisor"))
        assert revs and revs[0].active
        reps = ca_c.container_apps_revision_replicas.list_replicas("rg", "facilities-supervisor", revs[0].name)
        assert reps.value and reps.value[0].running_state, reps
        return f"{len(revs)} revision(s), replica {reps.value[0].running_state}"
    step("arm: revisions + replicas list shows the running replica", revisions)

    def traffic():
        a1 = ca_c.container_apps.get("rg", "facilities-supervisor"); r1 = a1.latest_revision_name
        a2 = ca_c.container_apps.begin_create_or_update("rg", "facilities-supervisor", body("v2", "Multiple", [{"revisionName": r1, "weight": 100}])).result()
        r2 = a2.latest_revision_name
        assert r1 != r2
        # the first (Single-mode) revision was deactivated by the switch to Multiple? re-activate both
        ca_c.container_apps_revisions.activate_revision("rg", "facilities-supervisor", r1)
        ca_c.container_apps.begin_create_or_update("rg", "facilities-supervisor", body("v2", "Multiple", [{"revisionName": r1, "weight": 100}, {"revisionName": r2, "weight": 0}])).result()
        seen = {requests.get(S["url"] + "env", timeout=60).headers.get("x-vyomi-revision") for _ in range(4)}
        assert seen == {r1}, seen
        ca_c.container_apps.begin_create_or_update("rg", "facilities-supervisor", body("v2", "Multiple", [{"revisionName": r1, "weight": 0}, {"revisionName": r2, "weight": 100}])).result()
        seen = {requests.get(S["url"] + "env", timeout=60).headers.get("x-vyomi-revision") for _ in range(4)}
        assert seen == {r2}, seen
        pinned = requests.get(tls + f"/azure-data/containerapps/facilities-supervisor--{r1.split('--')[1]}/env", timeout=30).headers.get("x-vyomi-revision")
        assert pinned == r1, pinned
        return f"100% -> {r1.split('--')[1]} then {r2.split('--')[1]}; revision pinning works"
    step("revisions + traffic weights: ingress routes by weight; <app>--<revision> pins", traffic)

    def lifecycle():
        ca_c.container_apps.begin_stop("rg", "facilities-supervisor").result()
        r = requests.get(S["url"] + "env", timeout=30)
        assert r.status_code == 503, r.status_code
        ca_c.container_apps.begin_start("rg", "facilities-supervisor").result() if hasattr(ca_c.container_apps, "begin_start") else None
        assert requests.get(S["url"] + "env", timeout=60).status_code == 200
    step("lifecycle: stop -> 503, start -> serving again", lifecycle)

    def delete():
        from providers import azure_app_runtime as rt
        pids = [p for p in list(rt._SB_PROCS)]
        ca_c.container_apps.begin_delete("rg", "facilities-supervisor").result()
        time.sleep(1)
        assert requests.get(S["url"] + "env", timeout=30).status_code == 404
        assert all(rt._SB_PROCS.get(p) is None or rt._SB_PROCS[p].poll() is not None for p in pids), "process still running"
    step("delete: the app and its processes are gone", delete)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush(); os._exit(rc)
