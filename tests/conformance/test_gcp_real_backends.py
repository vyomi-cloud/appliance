"""VYOMI_GCP_REAL_BACKENDS=1: the REAL Google Pub/Sub + Firestore emulators are the simulator's data plane.

Proves, with the unmodified Google client libraries:
  (a) default gRPC clients (pubsub_v1 / firestore.Client) against the emulator ports: publish/pull/ack,
      writes/reads/transactions/queries (the approval loop from docs/architecture/v4.0/REF-ARCH-PROBE-GCP.md 5b);
  (b) the simulator's REST surface sees the SAME data (REST transport of the same SDKs), and a topic / document
      created through the simulator's front door is visible to the gRPC clients;
  (c) simulator-side consumers keep working on this plane: a Cloud Run Eventarc Pub/Sub trigger fires for a
      REST publish AND for a publish made by a gRPC client (tap), Cloud Scheduler pubsubTarget delivery reaches the
      emulator, an Eventarc Firestore document trigger fires for a REST write.
Default behaviour with the flag off is covered too (the cores answer, nothing proxied).

Needs docker and the local image gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators (never pulled here) plus
google-cloud-pubsub and google-cloud-firestore; SKIPs cleanly (exit 0, "[SKIP]") when any is missing.
Containers are named vyomi-test-gcpreal-<tag>-{ps,fs}; only those exact names are removed.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_real_backends.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
IMG = "gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators"
TAG = uuid.uuid4().hex[:6]
NAMES = [f"vyomi-test-gcpreal-{TAG}-ps", f"vyomi-test-gcpreal-{TAG}-fs"]
PROJECT = "vyomi-project"   # the simulator's default project id
FAILS: list[str] = []


def ok(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f" -> {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def skip(why):
    print(f"[SKIP] {why}")
    sys.exit(0)


def sh(*a, timeout=120):
    return subprocess.run(a, capture_output=True, text=True, timeout=timeout)


def freeport():
    k = socket.socket()
    k.bind(("127.0.0.1", 0))
    p = k.getsockname()[1]
    k.close()
    return p


def wait_http(port, tries=90):
    import urllib.request
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            return True
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", 0):      # an HTTP error status still means the server is up
                return True
            time.sleep(1)
    return False


def start_emulators():
    try:
        if sh("docker", "info").returncode != 0:
            skip("docker daemon not running")
        if sh("docker", "image", "inspect", IMG).returncode != 0:
            skip(f"image {IMG} not present locally (this test never pulls it)")
    except FileNotFoundError:
        skip("docker CLI not installed")
    pp, fp = freeport(), freeport()
    r1 = sh("docker", "run", "-d", "--name", NAMES[0], "-p", f"127.0.0.1:{pp}:8085", IMG, "gcloud", "beta", "emulators",
            "pubsub", "start", "--host-port=0.0.0.0:8085", f"--project={PROJECT}")
    r2 = sh("docker", "run", "-d", "--name", NAMES[1], "-p", f"127.0.0.1:{fp}:8080", IMG, "gcloud", "beta", "emulators",
            "firestore", "start", "--host-port=0.0.0.0:8080")
    if r1.returncode or r2.returncode:
        raise RuntimeError(f"could not start emulators: {r1.stderr} {r2.stderr}")
    assert wait_http(pp) and wait_http(fp), "emulators did not come up"
    return pp, fp


def start_sim():
    work = tempfile.mkdtemp(prefix="gcpreal-")
    os.environ["CLOUDLEARN_STATE_FILE"] = os.path.join(work, "state.sqlite3")
    os.chdir(work)
    import asyncio
    import anyio
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        body = await request.body()
        return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))
    port = freeport()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"127.0.0.1:{port}", router


def main():
    try:
        import google.cloud.firestore  # noqa: F401
        import google.cloud.pubsub_v1  # noqa: F401
        import requests  # noqa: F401
    except Exception as e:  # noqa: BLE001
        skip(f"google-cloud-pubsub / google-cloud-firestore not installed ({e})")
    pp, fp = start_emulators()
    try:
        run(pp, fp)
    finally:
        for n in NAMES:
            sh("docker", "rm", "-f", n)
    print("\n" + ("ALL PASS" if not FAILS else f"FAILED: {FAILS}"))
    sys.exit(1 if FAILS else 0)


def run(pp, fp):
    os.environ["VYOMI_GCP_REAL_BACKENDS"] = "1"
    os.environ["PUBSUB_EMULATOR_HOST"] = f"127.0.0.1:{pp}"
    os.environ["FIRESTORE_EMULATOR_HOST"] = f"127.0.0.1:{fp}"
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT
    sim, router = start_sim()
    import requests
    from core import gcp_real_backends as rb
    ok("mode is on and installed", rb.status()["enabled"] and rb.status()["installed"], str(rb.status()))
    base = f"http://{sim}"

    # ---- (a) default gRPC clients straight on the emulator ports (what the reference app does) -------------------
    from google.api_core import exceptions as gex
    from google.cloud import firestore, pubsub_v1
    pub, sub = pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()
    topic = f"projects/{PROJECT}/topics/work-order-approval"
    sn = f"projects/{PROJECT}/subscriptions/approver-inbox"
    pub.create_topic(request={"name": topic})
    sub.create_subscription(request={"name": sn, "topic": topic})
    db = firestore.Client(project=PROJECT)
    led = db.collection("approval-ledger")
    led.document("r1").set({"status": "PENDING", "amount": 40})
    pub.publish(topic, b'{"request_id":"r1"}', kind="approval").result(timeout=20)
    got = sub.pull(request={"subscription": sn, "max_messages": 1}, timeout=20).received_messages
    ok("grpc publish -> pull", len(got) == 1 and got[0].message.attributes.get("kind") == "approval")

    @firestore.transactional
    def approve(tx, ref):
        snap = ref.get(transaction=tx)
        tx.update(ref, {"status": "APPROVED", "amount": snap.get("amount") + 1})
        return snap.get("status")
    prior = approve(db.transaction(), led.document("r1"))
    sub.acknowledge(request={"subscription": sn, "ack_ids": [got[0].ack_id]})
    ok("grpc firestore transaction + ack", prior == "PENDING" and led.document("r1").get().to_dict() == {"status": "APPROVED", "amount": 41})
    led.document("r2").set({"status": "PENDING", "amount": 900})
    q = [d.id for d in led.where("status", "==", "PENDING").stream()]
    ok("grpc firestore query", q == ["r2"], str(q))
    b = db.batch()
    b.set(led.document("r3"), {"status": "PENDING", "amount": 5})
    b.delete(led.document("r2"))
    b.commit()
    ok("grpc firestore batch", sorted(d.id for d in led.stream()) == ["r1", "r3"])

    # ---- (b) the simulator's REST surface sees the same data ----------------------------------------------------
    from google.auth.credentials import AnonymousCredentials
    saved = {k: os.environ.pop(k) for k in ("PUBSUB_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST")}   # the env var forces gRPC in the client ctors
    from google.cloud.firestore_v1.services.firestore import FirestoreClient
    from google.cloud.firestore_v1.services.firestore.transports.rest import FirestoreRestTransport
    from google.cloud.firestore_v1.types import GetDocumentRequest
    try:
        rpub = pubsub_v1.PublisherClient(transport="rest", credentials=AnonymousCredentials(), client_options={"api_endpoint": base})
        rfs = FirestoreClient(transport=FirestoreRestTransport(host=sim, url_scheme="http", credentials=AnonymousCredentials()))
    finally:
        os.environ.update(saved)             # the simulator itself reads the emulator hosts per request: put them back before calling
    names = [t.name for t in rpub.list_topics(request={"project": f"projects/{PROJECT}"})]
    ok("simulator REST (pubsub SDK rest transport) lists the topic made over gRPC", topic in names, str(names))
    rpub.create_topic(request={"name": f"projects/{PROJECT}/topics/viasim"})
    d = rfs.get_document(request=GetDocumentRequest(name=f"projects/{PROJECT}/databases/(default)/documents/approval-ledger/r1"))
    ok("simulator REST (firestore SDK rest transport) reads the doc made over gRPC", d.fields["status"].string_value == "APPROVED")
    ok("topic created through the simulator is in the emulator (gRPC list)", f"projects/{PROJECT}/topics/viasim" in
       [t.name for t in pub.list_topics(request={"project": f"projects/{PROJECT}"})])
    r = requests.patch(f"{base}/v1/projects/{PROJECT}/databases/(default)/documents/viasim/d1",
                       json={"fields": {"v": {"integerValue": "7"}}})
    ok("REST write through the simulator", r.status_code == 200, r.text[:120])
    ok("document written via the simulator is visible to the gRPC client", db.collection("viasim").document("d1").get().to_dict() == {"v": 7})
    r = requests.post(f"{base}/v1/projects/{PROJECT}/databases/(default)/documents:runQuery",
                      json={"structuredQuery": {"from": [{"collectionId": "viasim"}]}})
    ok("REST runQuery", r.status_code == 200 and any("document" in x for x in r.json()))

    # ---- (c) simulator-side consumers ---------------------------------------------------------------------------
    fire = []
    # Eventarc Firestore document trigger: register a listener on the same hook the core uses
    store = router.gcp_fs
    store.on_doc_event = lambda dbn, rel, old, new: fire.append((dbn, rel, old is None, new is None))
    requests.patch(f"{base}/v1/projects/{PROJECT}/databases/(default)/documents/viasim/d2",
                   json={"fields": {"v": {"integerValue": "1"}}})
    requests.delete(f"{base}/v1/projects/{PROJECT}/databases/(default)/documents/viasim/d2")
    ok("firestore document events fire for REST writes", fire == [("(default)", "viasim/d2", True, False), ("(default)", "viasim/d2", False, True)], str(fire))

    # Cloud Scheduler-style publish (the same dispatch seam) reaches the emulator + the trigger hook
    from core import gcp_pubsub_core as ps
    seen = []
    resp = ps.dispatch(router.gcp_msg, "POST", f"/v1/projects/{PROJECT}/topics/work-order-approval:publish", {}, {},
                       json.dumps({"messages": [{"data": "aGk=", "attributes": {"src": "sched"}}]}).encode(),
                       on_publish=lambda t, m: seen.append((t, m)))
    pulled = sub.pull(request={"subscription": sn, "max_messages": 5}, timeout=20).received_messages
    ok("core-seam publish lands in the emulator and fires on_publish",
       resp.status == 200 and len(seen) == 1 and seen[0][0] == topic and any(m.message.attributes.get("src") == "sched" for m in pulled))
    sub.acknowledge(request={"subscription": sn, "ack_ids": [m.ack_id for m in pulled]})

    # Eventarc topic existence check reads the shadow: a topic made by a gRPC client must be found
    ok("simulator-side get_topic finds a topic created by a gRPC client", router.gcp_msg.get_topic(topic) is not None)
    pub.create_topic(request={"name": f"projects/{PROJECT}/topics/grpc-only"})
    ok("...and one created after the shadow was warm", router.gcp_msg.get_topic(f"projects/{PROJECT}/topics/grpc-only") is not None)

    # Cloud Run Eventarc Pub/Sub trigger delivery: REST publish and gRPC publish (tap)
    deliveries = []
    from core import gcp_run_core as run
    orig_invoke = run.invoke_service
    run.invoke_service = lambda store_, project, location, sid, ev, internal=False: (deliveries.append(ev), {"status": 200, "body": {}})[1]
    try:
        from routes import gcp_run as run_routes
        rs = run_routes.store()
        rs.triggers["projects/%s/locations/us-central1/services/svc/triggers/t1" % PROJECT] = {
            "transport": {"pubsub": {"topic": topic}}, "eventType": "google.cloud.pubsub.topic.v1.messagePublished"}
        from routes import gcp_pubsub_unified as pu
        pu.ps("POST", f"/v1/projects/{PROJECT}/topics/work-order-approval:publish", {},
              json.dumps({"messages": [{"data": "cmVzdA=="}]}).encode())
        ok("Cloud Run trigger fires for a publish through the simulator", len(deliveries) == 1, str(len(deliveries)))
        pub.publish(topic, b"from-grpc").result(timeout=20)
        for _ in range(40):
            if len(deliveries) >= 2:
                break
            time.sleep(0.25)
        ok("Cloud Run trigger fires for a publish made by a gRPC client (tap), once", len(deliveries) == 2, str(len(deliveries)))
        time.sleep(1.5)
        ok("...and the REST publish is not delivered a second time", len(deliveries) == 2, str(len(deliveries)))
        hidden = [s.name for s in sub.list_subscriptions(request={"project": f"projects/{PROJECT}"}) if "vyomi-tap-" in s.name]
        rest_subs = requests.get(f"{base}/v1/projects/{PROJECT}/subscriptions").json().get("subscriptions", [])
        ok("tap subscription exists in the emulator but is hidden from the simulator's list",
           bool(hidden) and not any("vyomi-tap-" in s["name"] for s in rest_subs), str(hidden))
    finally:
        run.invoke_service = orig_invoke

    # core-only services stay on the simulator's own core
    r = requests.post(f"{base}/v1/projects/{PROJECT}/schemas?schemaId=s1", json={"type": "AVRO", "definition": '{"type":"record","name":"R","fields":[]}'})
    ok("schemas (not in the emulator) still served by the simulator core", r.status_code == 200, r.text[:100])

    # emulator down is reported, never faked
    os.environ["PUBSUB_EMULATOR_HOST"] = "127.0.0.1:1"
    r = requests.get(f"{base}/v1/projects/{PROJECT}/topics")
    ok("unreachable emulator -> 503 UNAVAILABLE (no silent fallback)", r.status_code == 503 and "not reachable" in r.text, r.text[:100])
    os.environ["PUBSUB_EMULATOR_HOST"] = f"127.0.0.1:{pp}"

    # flag off: the wrappers step aside and the cores answer
    os.environ["VYOMI_GCP_REAL_BACKENDS"] = "0"
    r = requests.put(f"{base}/v1/projects/{PROJECT}/topics/flagoff")
    names = [t.name for t in pub.list_topics(request={"project": f"projects/{PROJECT}"})]
    ok("flag off: topic goes to the simulator core, not the emulator", r.status_code == 200 and f"projects/{PROJECT}/topics/flagoff" not in names)
    os.environ["VYOMI_GCP_REAL_BACKENDS"] = "1"


if __name__ == "__main__":
    main()
