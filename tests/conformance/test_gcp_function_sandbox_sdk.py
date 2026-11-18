"""Cloud Functions / Cloud Run functions can reach the simulator with the REAL Google client libraries (v4 lane gcp-ref-sandbox).

A function deployed through the official `google-cloud-functions` (v2) client, invoked over its HTTPS URL, and Pub/Sub / Cloud Storage
(Eventarc) triggered ones, run in the sandboxed subprocess runtime (core/gcp_function_runtime) and use, INSIDE the function:
google.auth.default() (metadata-server ADC), google-cloud-storage, google-cloud-firestore (gapic REST), google-cloud-pubsub (REST),
google-cloud-secret-manager (REST) and plain urllib/requests. Also proves the sandbox: no arbitrary egress, no host filesystem, no
subprocess, host environment not leaked, requirements.txt honoured against the pre-baked wheel set.

Needs a venv with requirements.txt + google-cloud-functions, google-cloud-secret-manager, google-cloud-storage, requests.
Run: PYTHONPATH=. python tests/conformance/test_gcp_function_sandbox_sdk.py   (prints PASS/FAIL lines; exit 1 on any FAIL)
"""
import asyncio
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
_work = tempfile.mkdtemp(prefix="gcp-fn-sandbox-")
os.environ["CLOUDLEARN_STATE_FILE"] = os.path.join(_work, "state.sqlite3")
os.environ["VYOMI_HOST_SECRET_PROBE"] = "must-not-leak-into-functions"      # a host secret the sandbox must scrub
os.environ.pop("VYOMI_GCP_FUNCTION_RUNTIME", None)

P, LOC, TAG = "vyomi-project", "us-central1", uuid.uuid4().hex[:6]
RESULTS = []


def start():
    import anyio
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    from core.aws_wire_router import AwsWireRouter
    AwsWireRouter.STRICT_GCP_PROJECT = False
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        body = await request.body()

        def work():
            from core import app_context
            app_context.REQUEST_PROVIDER.set("gcp")   # what core/middleware does for Google API requests on the real server
            return asyncio.run(wire_ingress.serve(router, request, body=body))
        return await anyio.to_thread.run_sync(work)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return "http://127.0.0.1:%d" % port


EP = None


def check(name, fn):
    try:
        out = fn()
        print("[PASS] %s%s" % (name, (" -> " + str(out)[:200]) if out else ""))
        RESULTS.append(True)
        return out
    except Exception as e:  # noqa: BLE001
        print("[FAIL] %s: %s: %s" % (name, type(e).__name__, str(e)[:400]))
        RESULTS.append(False)


def rest_client(cls):
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    return cls(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=EP))


def deploy(name, code, env=None, event_trigger=None, requirements="", extra=None):
    from google.cloud import functions_v2 as f2
    c = rest_client(f2.FunctionServiceClient)
    parent = "projects/%s/locations/%s" % (P, LOC)
    up = c.generate_upload_url(request={"parent": parent})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.py", code)
        z.writestr("requirements.txt", requirements)
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    import requests
    requests.put(up.upload_url, data=buf.getvalue(), headers={"content-type": "application/zip"}, timeout=60).raise_for_status()
    fn = f2.Function(name="%s/functions/%s" % (parent, name),
                     build_config=f2.BuildConfig(runtime="python312", entry_point="handler", source=f2.Source(storage_source=up.storage_source)),
                     service_config=f2.ServiceConfig(environment_variables=env or {}, available_memory="256M", timeout_seconds=60))
    if event_trigger:
        fn.event_trigger = event_trigger
    return c.create_function(request={"parent": parent, "function": fn, "function_id": name}).result(timeout=120)


def call(name, payload):
    import requests
    return requests.post("%s/gcf/%s/%s/%s" % (EP, P, LOC, name), json=payload, headers={"Authorization": "Bearer test-bearer-token-x"}, timeout=90)


# Everything below is the function's source: what a developer writes for real Cloud Functions, unmodified Google libraries.
APP_FN = '''
import json, os, urllib.request
import google.auth
import google.auth.transport.requests
from google.api_core.client_options import ClientOptions
from google.cloud import storage, pubsub_v1, secretmanager
from google.cloud.firestore_v1.services.firestore import FirestoreClient
from google.cloud.firestore_v1.types import Document, Value, Write

def _ep(): return ClientOptions(api_endpoint=os.environ["VYOMI_ENDPOINT"])

def handler(request):
    body = request.get_json(silent=True) or {}
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    creds, adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    out = {"adc_project": adc_project, "token_set": bool(creds.token), "k_service": os.environ["K_SERVICE"],
           "target": os.environ["FUNCTION_TARGET"], "sig": os.environ["FUNCTION_SIGNATURE_TYPE"], "my_env": os.environ.get("APP_MODE"),
           "sa": getattr(creds, "service_account_email", "")}
    # google-cloud-storage: unmodified client, STORAGE_EMULATOR_HOST set by the simulator
    gcs = storage.Client(project=project)
    out["gcs"] = gcs.bucket(body["bucket"]).blob(body["object"]).download_as_bytes().decode()
    # google-cloud-secret-manager (REST)
    sm = secretmanager.SecretManagerServiceClient(credentials=creds, transport="rest", client_options=_ep())
    out["secret"] = sm.access_secret_version(request={"name": body["secret"]}).payload.data.decode()
    # google-cloud-firestore (gapic REST): the ledger write
    fs = FirestoreClient(credentials=creds, transport="rest", client_options=_ep())
    db = "projects/%s/databases/(default)" % project
    doc = Document(name=db + "/documents/ledger/" + body["req"], fields={"status": Value(string_value="APPROVED"), "by": Value(string_value="fn")})
    fs.commit(request={"database": db, "writes": [Write(update=doc)]})
    out["ledger_read"] = fs.get_document(request={"name": doc.name}).fields["status"].string_value
    # google-cloud-pubsub (REST)
    pub = pubsub_v1.PublisherClient(credentials=creds, transport="rest", client_options=_ep())
    out["published"] = len(pub.publish(body["topic"], b"from-function").result(timeout=30)) > 0
    # plain urllib to the simulator
    out["urllib_status"] = urllib.request.urlopen(os.environ["VYOMI_ENDPOINT"] + "/storage/v1/b/" + body["bucket"], timeout=10).status
    print("function ran", flush=True)
    return out
'''

SANDBOX_FN = '''
import os, socket, subprocess, urllib.request

def attempt(f):
    try:
        f(); return "ALLOWED"
    except Exception as e:
        return "blocked:" + type(e).__name__

def handler(request):
    r = {}
    r["internet_http"] = attempt(lambda: urllib.request.urlopen("http://example.com", timeout=5))
    r["internet_ip"] = attempt(lambda: socket.create_connection(("93.184.216.34", 80), timeout=3))
    r["etc_passwd"] = attempt(lambda: open("/etc/passwd").read())
    r["home_ssh"] = attempt(lambda: os.listdir(os.path.expanduser("~/..")))
    r["write_outside"] = attempt(lambda: open("/tmp/vyomi-escape-%s" % os.getpid(), "w").write("x"))
    r["subprocess"] = attempt(lambda: subprocess.run(["id"]))
    r["os_system"] = attempt(lambda: os.system("id"))
    open("scratch.txt", "w").write("ok")           # the function's own directory is writable
    r["write_workdir"] = open("scratch.txt").read()
    r["host_secret"] = os.environ.get("VYOMI_HOST_SECRET_PROBE", "absent")
    r["helper"] = __import__("helper").VALUE
    return r
'''

EVENT_FN = '''
import json, base64, os
import functions_framework
import google.auth, google.auth.transport.requests
from google.api_core.client_options import ClientOptions
from google.cloud.firestore_v1.services.firestore import FirestoreClient
from google.cloud.firestore_v1.types import Document, Value, Write

@functions_framework.cloud_event
def handler(event):
    creds, project = google.auth.default()
    fs = FirestoreClient(credentials=creds, transport="rest", client_options=ClientOptions(api_endpoint=os.environ["VYOMI_ENDPOINT"]))
    db = "projects/%s/databases/(default)" % project
    data = event.data
    if "message" in data:   # Pub/Sub messagePublished
        key, val = "pubsub-" + os.environ["APP_TAG"], base64.b64decode(data["message"]["data"]).decode()
    else:                   # Cloud Storage finalized
        key, val = "gcs-" + os.environ["APP_TAG"], data["bucket"] + "/" + data["name"]
    doc = Document(name=db + "/documents/events/" + key, fields={"value": Value(string_value=val), "type": Value(string_value=event["type"])})
    fs.commit(request={"database": db, "writes": [Write(update=doc)]})
    print("event handled", key, flush=True)
'''


def fs_get(path):
    from google.cloud.firestore_v1.services.firestore import FirestoreClient
    c = rest_client(FirestoreClient)
    try:
        d = c.get_document(request={"name": "projects/%s/databases/(default)/documents/%s" % (P, path)})
    except Exception:
        return None
    return {k: v.string_value for k, v in d.fields.items()}


def main():
    global EP
    EP = start()
    from google.cloud import storage, pubsub_v1, secretmanager
    from google.api_core.client_options import ClientOptions
    from google.auth.credentials import AnonymousCredentials
    gcs = storage.Client(project=P, credentials=AnonymousCredentials(), client_options=ClientOptions(api_endpoint=EP))
    bucket = "fn-b-" + TAG
    gcs.create_bucket(bucket)
    gcs.bucket(bucket).blob("sop/boiler.txt").upload_from_string(b"boiler limit 30 psi")
    opts = ClientOptions(api_endpoint=EP)
    sm = rest_client(secretmanager.SecretManagerServiceClient)
    sec = "projects/%s/secrets/s-%s" % (P, TAG)
    sm.create_secret(request={"parent": "projects/" + P, "secret_id": "s-" + TAG, "secret": {"replication": {"automatic": {}}}})
    sm.add_secret_version(request={"parent": sec, "payload": {"data": b"hunter2"}})
    pub = pubsub_v1.PublisherClient(credentials=AnonymousCredentials(), transport="rest", client_options=opts)
    sub = pubsub_v1.SubscriberClient(credentials=AnonymousCredentials(), transport="rest", client_options=opts)
    topic = "projects/%s/topics/out-%s" % (P, TAG)
    pub.create_topic(request={"name": topic})
    sub.create_subscription(request={"name": "projects/%s/subscriptions/out-%s" % (P, TAG), "topic": topic})

    check("deploy HTTP function with requirements.txt (requests, google-cloud-firestore) via google-cloud-functions v2",
          lambda: deploy("app-" + TAG, APP_FN, env={"APP_MODE": "ref"}, requirements="requests>=2.0\ngoogle-cloud-firestore>=2.16\ngoogle-cloud-pubsub\n").name)
    r = check("invoke over HTTPS: ADC + Storage + Secret Manager + Firestore + Pub/Sub + urllib from inside the function", lambda: call("app-" + TAG, {
        "bucket": bucket, "object": "sop/boiler.txt", "secret": sec + "/versions/latest", "req": "r1", "topic": topic}))
    if r is not None:
        def verify():
            assert r.status_code == 200, "HTTP %s %s" % (r.status_code, r.text[:500])
            o = r.json()
            assert o["adc_project"] == P and o["token_set"] and o["k_service"] == "app-" + TAG and o["target"] == "handler" and o["sig"] == "http", o
            assert o["my_env"] == "ref" and o["gcs"] == "boiler limit 30 psi" and o["secret"] == "hunter2", o
            assert o["ledger_read"] == "APPROVED" and o["published"] is True and o["urllib_status"] == 200, o
            return "all calls succeeded"
        check("function results (ledger written by the function itself)", verify)
        check("the Firestore ledger row is there when read from outside (real SDK)", lambda: fs_get("ledger/r1") == {"status": "APPROVED", "by": "fn"} or (_ for _ in ()).throw(AssertionError(fs_get("ledger/r1"))))
        check("the function's Pub/Sub publish is receivable", lambda: len(sub.pull(request={"subscription": "projects/%s/subscriptions/out-%s" % (P, TAG), "max_messages": 5}, timeout=20).received_messages) == 1 or (_ for _ in ()).throw(AssertionError("no message")))

    check("deploy function with a helper module in the zip", lambda: deploy("box-" + TAG, SANDBOX_FN, env={}, extra={"helper.py": "VALUE = 'helper-ok'\n"}).name)
    rb = check("sandbox invoke", lambda: call("box-" + TAG, {}))
    if rb is not None:
        def verify_box():
            assert rb.status_code == 200, "HTTP %s %s" % (rb.status_code, rb.text[:500])
            o = rb.json()
            for k in ("internet_http", "internet_ip", "etc_passwd", "home_ssh", "write_outside", "subprocess", "os_system"):
                assert o[k].startswith("blocked:"), "%s -> %s" % (k, o[k])
            assert o["write_workdir"] == "ok" and o["host_secret"] == "absent" and o["helper"] == "helper-ok", o
            assert not os.path.exists("/tmp/vyomi-escape-%s" % os.getpid())
            return "egress/fs/process blocked; own dir writable; host env scrubbed; helper module imported"
        check("sandbox: no internet, no host files, no subprocess, host env not leaked", verify_box)

    def bad_requirements():
        try:
            deploy("bad-" + TAG, "def handler(request):\n    return 'x'\n", requirements="definitely-not-a-real-package-xyz==1.0\n")
        except Exception as e:  # noqa: BLE001
            assert "requirements" in str(e).lower() and "pre-baked" in str(e), str(e)[:300]
            return "build fails honestly: " + str(e)[:120].replace("\n", " ")
        raise AssertionError("deploy with an unavailable package succeeded")
    check("requirements.txt that cannot be satisfied offline fails the build with the available libraries", bad_requirements)

    def nano_like():   # the in-interpreter sandbox (what Nano runs) has no SDKs and no network: same function, honest ImportError
        os.environ["VYOMI_GCP_FUNCTION_RUNTIME"] = "inproc"
        try:
            rn = call("app-" + TAG, {"bucket": bucket, "object": "sop/boiler.txt", "secret": sec + "/versions/latest", "req": "r2", "topic": topic})
        finally:
            os.environ.pop("VYOMI_GCP_FUNCTION_RUNTIME", None)
        assert rn.status_code == 500 and "not available in the function sandbox" in rn.text, (rn.status_code, rn.text[:300])
        return "in-interpreter (Nano) sandbox: " + rn.text[:90]
    check("Nano-style in-interpreter sandbox refuses google.cloud imports (documented difference)", nano_like)

    from google.cloud import functions_v2 as f2
    check("Pub/Sub-triggered function (Eventarc) writes Firestore from the event", lambda: _pubsub_event(f2, pub, P))
    check("Cloud Storage-finalize-triggered function (Eventarc) writes Firestore from the event", lambda: _gcs_event(gcs, bucket))
    bad = [i for i, ok in enumerate(RESULTS) if not ok]
    print("\n%d/%d passed" % (len(RESULTS) - len(bad), len(RESULTS)))
    return 1 if bad else 0


def _pubsub_event(f2, pub, project):
    topic = "projects/%s/topics/in-%s" % (project, TAG)
    pub.create_topic(request={"name": topic})
    et = f2.EventTrigger(event_type="google.cloud.pubsub.topic.v1.messagePublished", pubsub_topic=topic)
    deploy("evps-" + TAG, EVENT_FN, env={"APP_TAG": TAG}, event_trigger=et)
    pub.publish(topic, b"approve-1234").result(timeout=30)
    for _ in range(40):
        row = fs_get("events/pubsub-" + TAG)
        if row:
            assert row["value"] == "approve-1234" and row["type"].endswith("messagePublished"), row
            return row
        time.sleep(0.5)
    raise AssertionError("the event function never wrote the Firestore row (delivery or sandbox failure)")


def _gcs_event(gcs, bucket):
    from google.cloud import functions_v2 as f2
    et = f2.EventTrigger(event_type="google.cloud.storage.object.v1.finalized",
                         event_filters=[f2.EventFilter(attribute="bucket", value=bucket)])
    deploy("evgcs-" + TAG, EVENT_FN, env={"APP_TAG": TAG}, event_trigger=et)
    gcs.bucket(bucket).blob("sop/second.txt").upload_from_string(b"second")
    for _ in range(40):
        row = fs_get("events/gcs-" + TAG)
        if row:
            assert row["value"] == bucket + "/sop/second.txt" and row["type"].endswith("finalized"), row
            return row
        time.sleep(0.5)
    raise AssertionError("the GCS event function never wrote the Firestore row")


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
