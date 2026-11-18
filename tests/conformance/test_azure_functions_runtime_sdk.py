"""Azure Function Apps run real function code that reaches the simulator with the REAL Azure SDKs (v4 lane az-ref-runtime).

The test deploys function apps with the official `azure-mgmt-web` client + Kudu `zipdeploy`, then calls them over HTTP exactly as a
client of `https://<app>.azurewebsites.net/api/<route>` would (Host header form, function keys, master key), and runs non-HTTP
triggers (Service Bus topic, Event Grid, timer) through the invocation seam. INSIDE the functions it uses `azure.functions` (the
real package: v1 function.json and v2 decorators), `azure-storage-blob`, `azure-data-tables`, `azure-cosmos`, `azure-servicebus`,
`azure-identity` (DefaultAzureCredential through the managed-identity endpoint) and `requests`.
Also proves the sandbox: no arbitrary egress, no host filesystem, host environment not leaked, requirements.txt honoured.

Needs a venv with requirements.txt + azure-mgmt-web/-resource, azure-core, azure-functions.
Run: PYTHONPATH=. python tests/conformance/test_azure_functions_runtime_sdk.py   (PASS/FAIL lines; exit 1 on any FAIL; skips if a dep is missing)
"""
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
for _m in ("azure.mgmt.web", "azure.mgmt.resource", "azure.functions", "azure.identity", "azure.storage.blob", "requests"):
    try:
        __import__(_m)
    except ImportError as _e:
        print("SKIP: %s not installed (%s)" % (_m, _e))
        sys.exit(0)

_work = tempfile.mkdtemp(prefix="az-fn-runtime-")
os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(_work, "state.sqlite3"), "VYOMI_DATA_DIR": _work, "CLOUDLEARN_TIER_ENFORCE": "0",
                   "VYOMI_AZSB_DB": os.path.join(_work, "azsb.sqlite"), "VYOMI_HOST_SECRET_PROBE": "must-not-leak-into-functions"})
SUB, RG, LOC, TAG = "00000000-0000-0000-0000-cloudlearn01", "rg-fn", "eastus", uuid.uuid4().hex[:5]
RESULTS = []


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def start():
    """The real appliance app (server.py): wire ingress, /azure-data/*, the middleware that maps <app>.azurewebsites.net."""
    port, amqp = _free(), _free()
    os.environ.update({"VYOMI_AMQP_PORT": str(amqp), "VYOMI_AMQPS_PORT": "0", "VYOMI_AMQP_HOST": "127.0.0.1"})
    os.chdir(ROOT)
    import uvicorn
    import server
    try:
        from core import azure_arm_core
        azure_arm_core.AzureArm.STRICT_SUBSCRIPTION = False
    except Exception:
        pass
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    t0 = time.time()
    while not srv.started:
        if time.time() - t0 > 240:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    time.sleep(1.0)
    return "http://127.0.0.1:%d" % port


def check(name, fn):
    try:
        out = fn()
        print("[PASS] %s%s" % (name, (" -> " + str(out)[:220]) if out else ""), flush=True)
        RESULTS.append(True)
        return out
    except Exception as e:  # noqa: BLE001
        print("[FAIL] %s: %s: %s" % (name, type(e).__name__, str(e)[:500]), flush=True)
        RESULTS.append(False)


def must(cond, msg="assertion failed"):
    if not cond:
        raise AssertionError(msg)
    return True


class Cred:
    def get_token(self, *a, **k):
        from azure.core.credentials import AccessToken
        return AccessToken("vyomi-test-token", 4102444800)


def arm(cls, base):
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    return cls(Cred(), SUB, base_url=base, authentication_policy=SansIOHTTPPolicy(), polling_interval=0)


def make_zip(files):
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        for k, v in files.items():
            zf.writestr(k, v)
    return z.getvalue()


# ── function code (what a function author writes; runs in the sandbox) ───────────────────────────────────────────
V1_LOOKUP = '''
import json, os, logging, base64
import azure.functions as func                       # the REAL azure.functions
import requests
from azure.identity import DefaultAzureCredential    # managed identity via IDENTITY_ENDPOINT
from azure.storage.blob import BlobServiceClient
import azure.data.tables, azure.cosmos, azure.servicebus      # these share the `azure` namespace with azure.functions

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("lookup invoked asset=%s", req.params.get("asset"))
    asset = req.params.get("asset") or (req.get_json() or {}).get("asset")
    tok = DefaultAzureCredential().get_token("https://management.azure.com/.default").token
    claims = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
    bs = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])
    c = bs.get_container_client("fnout")
    try:
        c.create_container()
    except Exception:
        pass
    c.upload_blob("last-%s" % asset, json.dumps({"asset": asset}), overwrite=True)
    back = c.download_blob("last-%s" % asset).readall().decode()
    health = requests.get(os.environ["VYOMI_ENDPOINT"] + "/healthz", timeout=10).status_code
    return func.HttpResponse(json.dumps({"asset": asset, "site": os.environ["WEBSITE_SITE_NAME"], "runtime": os.environ["FUNCTIONS_WORKER_RUNTIME"],
        "setting": os.environ.get("FACILITY"), "aud": claims["aud"], "blob": back, "healthz": health,
        "libs": [azure.data.tables.__name__, azure.cosmos.__name__, azure.servicebus.__name__], "url": req.url}), mimetype="application/json")
'''
V1_LOOKUP_JSON = {"scriptFile": "__init__.py", "bindings": [
    {"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["get", "post"], "route": "assets/lookup"},
    {"type": "http", "direction": "out", "name": "$return"}]}
V1_ADMIN = 'import azure.functions as func\ndef main(req): return func.HttpResponse("admin-ok")\n'
V1_ADMIN_JSON = {"bindings": [{"authLevel": "admin", "type": "httpTrigger", "direction": "in", "name": "req"}, {"type": "http", "direction": "out", "name": "$return"}]}
V1_OPEN = 'import azure.functions as func\ndef main(req): return func.HttpResponse("open", status_code=201, headers={"x-fn": "1"})\n'
V1_OPEN_JSON = {"bindings": [{"authLevel": "anonymous", "type": "httpTrigger", "direction": "in", "name": "req"}, {"type": "http", "direction": "out", "name": "$return"}]}
V1_HOSTILE = '''
import os, socket, urllib.request, subprocess, json
import azure.functions as func
def main(req):
    out = {}
    for k, fn in (("net", lambda: urllib.request.urlopen("http://1.1.1.1", timeout=3)), ("dns", lambda: socket.getaddrinfo("example.com", 80)),
                  ("passwd", lambda: open("/etc/passwd").read()), ("write", lambda: open("/tmp/x-fn", "w").write("x")),
                  ("proc", lambda: subprocess.run(["id"]))):
        try:
            fn(); out[k] = "ALLOWED"
        except Exception as e:
            out[k] = type(e).__name__
    out["host_secret"] = os.environ.get("VYOMI_HOST_SECRET_PROBE")
    return func.HttpResponse(json.dumps(out), mimetype="application/json")
'''
V2_APP = '''
import json, os, logging
import azure.functions as func
from azure.servicebus import ServiceBusMessage as _SBM          # real SDKs importable next to azure.functions
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

def _put(name, doc):
    c = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"]).get_container_client("fnout")
    try:
        c.create_container()
    except Exception:
        pass
    c.upload_blob(name, json.dumps(doc), overwrite=True)

@app.route(route="items/{id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_item(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"id": req.route_params["id"], "q": req.params.get("q")}), mimetype="application/json")

@app.service_bus_topic_trigger(arg_name="msg", topic_name="work-order-approval", subscription_name="approver-inbox", connection="SB_CONN")
def on_approval(msg: func.ServiceBusMessage):
    body = msg.get_body().decode()
    logging.info("approval message %s", body)
    _put("approval-" + TAGX, {"body": json.loads(body)})

@app.event_grid_trigger(arg_name="event")
def on_event(event: func.EventGridEvent):
    _put("event-" + TAGX, {"subject": event.subject, "type": event.event_type, "data": event.get_json()})

@app.timer_trigger(arg_name="timer", schedule="0 */5 * * * *")
def tick(timer: func.TimerRequest):
    _put("tick-" + TAGX, {"past_due": timer.past_due})

@app.route(route="boom", auth_level=func.AuthLevel.ANONYMOUS)
def boom(req: func.HttpRequest) -> func.HttpResponse:
    raise RuntimeError("kaboom")
'''.replace("TAGX", repr(TAG))


def main():
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.web import WebSiteManagementClient
    from azure.storage.blob import BlobServiceClient
    import requests

    base = start()
    os.environ["VYOMI_SELF_URL"] = base
    arm(ResourceManagementClient, base).resource_groups.create_or_update(RG, {"location": LOC})
    w = arm(WebSiteManagementClient, base)
    w.app_service_plans.begin_create_or_update(RG, "plan1", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
    pid = "/subscriptions/%s/resourceGroups/%s/providers/Microsoft.Web/serverfarms/plan1" % (SUB, RG)

    def create(name, settings):
        w.web_apps.begin_create_or_update(RG, name, {"location": LOC, "kind": "functionapp", "server_farm_id": pid, "identity": {"type": "SystemAssigned"}}).result()
        w.web_apps.update_application_settings(RG, name, {"properties": settings})

    def deploy(name, files):
        r = requests.post("%s/azure-data/functions/%s/api/zipdeploy" % (base, name), data=make_zip(files), timeout=240)
        must(r.status_code == 200, (r.status_code, r.text[:400]))

    app1, app2 = "facilities-tools", "fn-v2-" + TAG
    check("create function apps through azure-mgmt-web (system-assigned identity, app settings)", lambda: (
        create(app1, {"FACILITY": "hq-north", "FUNCTIONS_WORKER_RUNTIME": "python"}), create(app2, {"SB_CONN": "Endpoint=sb://x/"}), "ok")[-1])
    check("zipdeploy v1 app (function.json, requirements.txt satisfied from the pre-baked wheels)", lambda: deploy(app1, {
        "host.json": "{}", "requirements.txt": "azure-functions\nazure-storage-blob\nazure-identity\nrequests\nazure-data-tables\nazure-cosmos\nazure-servicebus\n",
        "lookup/__init__.py": V1_LOOKUP, "lookup/function.json": json.dumps(V1_LOOKUP_JSON), "adm/__init__.py": V1_ADMIN, "adm/function.json": json.dumps(V1_ADMIN_JSON),
        "open/__init__.py": V1_OPEN, "open/function.json": json.dumps(V1_OPEN_JSON), "hostile/__init__.py": V1_HOSTILE, "hostile/function.json": json.dumps(V1_OPEN_JSON)}))
    check("zipdeploy v2 app (decorators in function_app.py)", lambda: deploy(app2, {"host.json": "{}", "function_app.py": V2_APP}))

    # ── ARM: list/get functions, keys ──
    def arm_funcs():
        names = sorted(f.name.split("/")[-1] for f in w.web_apps.list_functions(RG, app1))
        must(names == ["adm", "hostile", "lookup", "open"], names)
        f = w.web_apps.get_function(RG, app1, "lookup")
        must(f.invoke_url_template == "https://facilities-tools.azurewebsites.net/api/assets/lookup", f.invoke_url_template)
        must(f.config["bindings"][0]["type"] == "httpTrigger")
        v2 = {f.name.split("/")[-1]: f for f in w.web_apps.list_functions(RG, app2)}
        must(sorted(v2) == ["boom", "get_item", "on_approval", "on_event", "tick"], sorted(v2))
        must(v2["on_approval"].config["bindings"][0]["type"] == "serviceBusTrigger")
        return names + sorted(v2)
    check("ARM list_functions / get_function show the deployed functions (v1 + v2) with bindings", arm_funcs)
    keys = {}

    def arm_keys():
        fk = w.web_apps.list_function_keys(RG, app1, "lookup")
        d = fk.as_dict()
        keys["fn"] = d.get("default") or (d.get("properties") or {}).get("default")
        hk = w.web_apps.list_host_keys(RG, app1)
        keys["master"], keys["host"] = hk.master_key, (hk.function_keys or {}).get("default")
        keys["fn"] = keys["fn"] or None
        must(keys["fn"] and keys["master"] and keys["host"], (fk.as_dict(), hk.as_dict()))
        return "fn key, host key, master key"
    check("ARM list_function_keys + list_host_keys return the keys", arm_keys)
    check("ARM create_or_update_function_secret then the key works", lambda: (
        w.web_apps.create_or_update_function_secret(RG, app1, "lookup", "ci", {"properties": {"name": "ci", "value": "ci-key-" + TAG}}), keys.update(ci="ci-key-" + TAG), "ok")[-1])

    # ── HTTP front door: path form and the real hostname form ──
    host = "%s.azurewebsites.net" % app1

    def call(path, key=None, hdr=True, host_form=True, **kw):
        h = dict(kw.pop("headers", {}))
        params = dict(kw.pop("params", {}) or {})
        if key:
            if hdr:
                h["x-functions-key"] = key
            else:
                params["code"] = key
        method = kw.pop("method", "GET")
        if host_form:
            h["Host"] = host
            return requests.request(method, base + path, headers=h, params=params, timeout=120, **kw)
        return requests.request(method, "%s/azure-data/functions/%s%s" % (base, app1, path), headers=h, params=params, timeout=120, **kw)

    check("function-level auth: no key -> 401", lambda: must(call("/api/assets/lookup", params={"asset": "a1"}).status_code == 401, "expected 401"))
    check("wrong key -> 401", lambda: must(call("/api/assets/lookup", key="nope", params={"asset": "a1"}).status_code == 401, "expected 401"))

    def lookup(**kw):
        r = call("/api/assets/lookup", params={"asset": "a1"}, **kw)
        must(r.status_code == 200, (r.status_code, r.text[:600]))
        j = r.json()
        must(j["asset"] == "a1" and j["site"] == app1 and j["runtime"] == "python" and j["setting"] == "hq-north", j)
        must(j["aud"].startswith("https://management.azure.com"), j["aud"])
        must(json.loads(j["blob"]) == {"asset": "a1"} and j["healthz"] == 200, j)
        must(j["libs"] == ["azure.data.tables", "azure.cosmos", "azure.servicebus"], j)
        return j["url"]
    check("host form https://<app>.azurewebsites.net/api/<route> + function key (header): real azure.functions, DefaultAzureCredential (MSI), "
          "blob SDK, requests, azure.data.tables/cosmos/servicebus importable", lambda: lookup(key=keys["fn"]))
    check("host key as ?code= query", lambda: lookup(key=keys["host"], hdr=False))
    check("master key opens a function-level function", lambda: lookup(key=keys["master"]))
    check("a key created through ARM works", lambda: lookup(key=keys["ci"]))
    check("simulator path form /azure-data/functions/<app>/api/<route> works with the key too", lambda: lookup(key=keys["fn"], host_form=False))
    check("admin auth level: a function key is rejected, the master key is accepted", lambda: must(
        call("/api/adm", key=keys["fn"]).status_code == 401 and call("/api/adm", key=keys["master"]).text == "admin-ok", "admin level"))
    check("anonymous function: no key; status code + headers pass through", lambda: must(
        (lambda r: (r.status_code, r.headers.get("x-fn"), r.text))(call("/api/open")) == (201, "1", "open"), "anonymous"))
    check("wrong HTTP method -> 404; unknown route -> 404", lambda: must(
        call("/api/assets/lookup", key=keys["fn"], method="DELETE").status_code == 404 and call("/api/nope").status_code == 404, "404s"))

    def sandbox():
        r = call("/api/hostile")
        must(r.status_code == 201 or r.status_code == 200, (r.status_code, r.text[:300]))
        d = r.json()
        must(all(d[k] != "ALLOWED" for k in ("net", "dns", "passwd", "write", "proc")), d)
        must(d["host_secret"] is None, d)
        return d
    check("sandbox: no internet (name/IP), no /etc/passwd, no writes outside the function dir, no subprocess, host env not leaked", sandbox)

    def unsatisfied():
        r = requests.post("%s/azure-data/functions/%s/api/zipdeploy" % (base, app1), data=make_zip({"function_app.py": "x=1", "requirements.txt": "pandas-nope-9\n"}), timeout=60)
        must(r.status_code == 400 and "pandas-nope-9" in r.text and "azure-cosmos" in r.text, (r.status_code, r.text[:300]))
        return "400 with the available libraries"
    check("requirements.txt that the pre-baked wheel set cannot satisfy fails the deploy and lists what is available", unsatisfied)

    # ── v2 app: routes with parameters, admin API, triggers via the seam ──
    host2 = "%s.azurewebsites.net" % app2
    keys2 = {"master": w.web_apps.list_host_keys(RG, app2).master_key}
    check("v2 route template items/{id} (anonymous) over the host form", lambda: must(
        requests.get(base + "/api/items/42", params={"q": "z"}, headers={"Host": host2}, timeout=120).json() == {"id": "42", "q": "z"}, "route"))
    check("an unhandled exception in the function is a 500, not a crash of the host", lambda: must(
        requests.get(base + "/api/boom", headers={"Host": host2}, timeout=120).status_code == 500, "500"))

    def admin_keys():
        h = {"Host": host2}
        must(requests.get(base + "/admin/host/keys", headers=h, timeout=30).status_code == 401, "no master key must be 401")
        h["x-functions-key"] = keys2["master"]
        r = requests.get(base + "/admin/host/keys", headers=h, timeout=30)
        names = [k["name"] for k in r.json()["keys"]]
        must(r.status_code == 200 and "default" in names and "_master" in names, r.text[:200])
        r = requests.put(base + "/admin/host/keys/mykey", headers=h, json={"value": "mine-" + TAG}, timeout=30)
        must(r.status_code in (200, 201) and r.json()["value"] == "mine-" + TAG)
        must("mykey" in (w.web_apps.list_host_keys(RG, app2).function_keys or {}), "ARM does not see the admin-API key")
        r = requests.get(base + "/admin/functions/get_item/keys", headers=h, timeout=30)
        must(r.status_code == 200 and r.json()["keys"][0]["name"] == "default", r.text[:200])
        must(requests.get(base + "/admin/host/status", headers=h, timeout=30).json()["state"] == "Running")
        return "host keys list/put (visible in ARM), function keys, host status"
    check("admin API /admin/host/keys, /admin/functions/<fn>/keys, /admin/host/status (master key)", admin_keys)

    acct = "vyomifn" + "".join(c for c in app2.lower() if c.isalnum())[:16]
    bs = BlobServiceClient.from_connection_string("DefaultEndpointsProtocol=http;AccountName=%s;AccountKey=a2V5;BlobEndpoint=%s/azure-data/blob/%s" % (acct, base, acct))
    fnout = bs.get_container_client("fnout")

    def wait_blob(name, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                return json.loads(fnout.download_blob(name).readall())
            except Exception:
                time.sleep(0.5)
        raise AssertionError("function did not write blob %s" % name)

    def admin_invoke():
        r = requests.post(base + "/admin/functions/tick", headers={"Host": host2, "x-functions-key": keys2["master"]}, json={"input": ""}, timeout=120)
        must(r.status_code == 202, (r.status_code, r.text[:200]))
        return wait_blob("tick-" + TAG)
    check("timer trigger run through POST /admin/functions/<fn> (the real manual-invoke call); the function writes with the blob SDK", admin_invoke)

    def seam():
        from core import azure_dataplane as dpl
        ev = {"id": "e1", "topic": "t", "subject": "/blobServices/default/containers/docs/blobs/a.pdf", "eventType": "Microsoft.Storage.BlobCreated",
              "eventTime": "2026-11-18T10:00:00Z", "dataVersion": "1", "data": {"url": "u"}}
        r = dpl.run_function_sync(app2, "on_event", "POST", [ev])
        must(r["ok"], r)
        must(wait_blob("event-" + TAG) == {"subject": ev["subject"], "type": ev["eventType"], "data": {"url": "u"}})
        return "Event Grid event -> eventGridTrigger function"
    check("invocation seam run_function_sync(app, fn, 'POST', events) runs an eventGridTrigger function with an azure.functions.EventGridEvent", seam)

    def sb_seam():
        from providers import azure_functions_host as fh
        from core import azure_dataplane as dpl
        rec = dpl._find_function_app(app2)
        fns = fh.functions_with_trigger(rec, "serviceBusTrigger", topicName="work-order-approval", subscriptionName="approver-inbox")
        must([f["name"] for f in fns] == ["on_approval"], fns)
        out = fh.invoke_trigger(rec, fns[0], {"body": {"order": "WO-1", "approved": True}, "content_type": "application/json"})
        must(out["ok"], out)
        must(wait_blob("approval-" + TAG) == {"body": {"order": "WO-1", "approved": True}})
        return "serviceBusTrigger match + invoke with azure.functions.ServiceBusMessage"
    check("seam for lane messaging: functions_with_trigger(serviceBusTrigger, topic/subscription) + invoke_trigger -> azure.functions.ServiceBusMessage", sb_seam)

    def logs():
        from core import azure_dataplane as dpl
        rec = dpl._find_function_app(app1)
        text = "\n".join(e["message"] for e in rec["_logstream"])
        must("lookup invoked asset=a1" in text and "Executed 'Functions.lookup' (Succeeded" in text, text[-400:])
        return "logging.info lines reach the site log stream"
    check("function logging.info and invocation results reach the site's log stream", logs)

    print("\n%d/%d passed" % (sum(RESULTS), len(RESULTS)), flush=True)
    os._exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
