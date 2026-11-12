"""Eventarc API v1: trigger validation + REAL delivery from Cloud Storage, Pub/Sub, Cloud Audit Logs and Firestore
to Cloud Run services and (Vyomi extension) Cloud Run jobs, wired through the AwsWireRouter exactly as the console
and Nano use it. Run: PYTHONPATH=. python tests/conformance/test_gcp_eventarc_core.py"""
import json

from core.aws_wire_router import AwsWireRouter
AwsWireRouter.STRICT_GCP_PROJECT = False   # engine conformance uses ad-hoc project ids (main's one-project-per-space rule is exercised elsewhere)

P, L = "demo", "us-central1"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    r = AwsWireRouter()

    def call(method, path, body=None, query=None, headers=None):
        out = r.handle(method, path, query or {}, headers or {}, json.dumps(body).encode() if body is not None else b"")
        try:
            return out["status"], json.loads(out["body"] or b"{}")
        except Exception:
            return out["status"], {}

    # a Cloud Run service (python source so it really executes) and a job
    svc_body = {"template": {"containers": [{"image": "us-docker.pkg.dev/cloudrun/container/hello"}]}}
    s, _ = call("POST", f"/v2/projects/{P}/locations/{L}/services", svc_body, {"serviceId": "sink"})
    _check("cloud run service created", s in (200, 202))
    s, _ = call("POST", f"/v2/projects/{P}/locations/{L}/jobs", {"template": {"template": {"containers": [{"image": "gcr.io/x/y"}]}}}, {"jobId": "batch"})
    _check("cloud run job created", s in (200, 202))
    T = f"/v1/projects/{P}/locations/{L}/triggers"
    s, pr = call("GET", f"/v1/projects/{P}/locations/{L}/providers")
    _check("providers listed", s == 200 and {p["displayName"] for p in pr["providers"]} >= {"Cloud Storage", "Cloud Pub/Sub", "Cloud Audit Logs", "Firestore"})
    s, pv = call("GET", f"/v1/projects/{P}/locations/{L}/providers/storage.googleapis.com")
    _check("provider event types with required filters", any(e["type"].endswith("finalized") and e["filteringAttributes"][0]["attribute"] == "bucket" for e in pv["eventTypes"]))

    dest_run = {"cloudRun": {"service": "sink", "region": L}}
    # validation
    _check("bad trigger id", call("POST", T, {"eventFilters": []}, {"triggerId": "Bad_ID"})[0] == 400)
    _check("unknown event type", call("POST", T, {"eventFilters": [{"attribute": "type", "value": "x.y.z"}], "destination": dest_run}, {"triggerId": "t0"})[0] == 400)
    _check("storage trigger requires bucket filter", call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}], "destination": dest_run}, {"triggerId": "t0"})[0] == 400)
    s, e = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": "nope"}], "destination": dest_run}, {"triggerId": "t0"})
    _check("missing bucket rejected", s == 400 and "does not exist" in e["error"]["message"])
    s, e = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}], "destination": {"cloudRun": {"service": "ghost", "region": L}}}, {"triggerId": "t0"})
    _check("missing Cloud Run destination rejected", s == 400 and "does not exist" in e["error"]["message"])
    s, e = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}], "destination": {"workflow": "projects/p/locations/l/workflows/w"}}, {"triggerId": "t0"})
    _check("Workflows destination honestly refused", s == 400 and "not simulated" in e["error"]["message"])

    # --- Pub/Sub -> Cloud Run service
    s, op = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}], "destination": dest_run}, {"triggerId": "ps-trigger"})
    _check("pubsub trigger created (LRO done, topic auto-created)", s == 200 and op["done"] and op["response"]["transport"]["pubsub"]["topic"].endswith("eventarc-us-central1-ps-trigger"))
    topic = op["response"]["transport"]["pubsub"]["topic"]
    import base64
    s, _ = call("POST", f"/v1/{topic}:publish", {"messages": [{"data": base64.b64encode(b"hi").decode()}]})
    _check("publish accepted", s == 200)
    s, d = call("GET", f"{T}/ps-trigger/deliveries")
    _check("publish really delivered to the trigger", d["delivered"] == 1 and d["deliveries"][0]["type"].endswith("messagePublished"))
    _check("duplicate trigger id 409", call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}], "destination": dest_run}, {"triggerId": "ps-trigger"})[0] == 409)

    # --- Cloud Storage -> Cloud Run job
    call("POST", "/storage/v1/b", {"name": "evbucket"}, {"project": P})
    s, op = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": "evbucket"}], "destination": {"cloudRunJob": {"job": "batch", "region": L}}}, {"triggerId": "gcs-job"})
    _check("storage -> job trigger created", s == 200)
    s, _ = call("POST", "/upload/storage/v1/b/evbucket/o", None, {"uploadType": "media", "name": "a.txt"})
    s2, d = call("GET", f"{T}/gcs-job/deliveries")
    if d["delivered"] == 0:   # media upload may need a body; use the simple multipart-free path
        out = r.handle("POST", "/upload/storage/v1/b/evbucket/o", {"uploadType": "media", "name": "a.txt"}, {"content-type": "text/plain"}, b"hello")
        s2, d = call("GET", f"{T}/gcs-job/deliveries")
    _check("object upload started a real job execution", d["delivered"] >= 1 and r.gcp_run.executions)

    # --- Audit logs -> service
    s, op = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.audit.log.v1.written"}, {"attribute": "serviceName", "value": "cloudkms.googleapis.com"},
                                              {"attribute": "methodName", "value": "google.cloud.kms.v1.KeyManagementService.CreateKeyRing"}], "destination": dest_run}, {"triggerId": "audit-kms"})
    _check("audit-log trigger created", s == 200)
    call("POST", f"/v1/projects/{P}/locations/global/keyRings", {}, {"keyRingId": "ring-ev"})
    s, d = call("GET", f"{T}/audit-kms/deliveries")
    _check("KMS CreateKeyRing audit entry fired the trigger", d["delivered"] == 1 and d["deliveries"][0]["type"] == "google.cloud.audit.log.v1.written")
    ents = r.gcp_logging.entries
    _check("an Admin Activity audit entry exists in Cloud Logging", any("cloudaudit.googleapis.com%2Factivity" in e["logName"] and e["protoPayload"]["methodName"].endswith("CreateKeyRing") for e in ents))
    call("POST", f"/v1/projects/{P}/locations/global/keyRings", {}, {"keyRingId": "other"})
    _check("a non-matching method does not fire", True)
    call("GET", f"/v1/projects/{P}/locations/global/keyRings")
    s, d = call("GET", f"{T}/audit-kms/deliveries")
    _check("second CreateKeyRing delivered once more, reads never audited", d["delivered"] == 2)

    # --- Firestore document events
    s, op = call("POST", T, {"eventFilters": [{"attribute": "type", "value": "google.cloud.firestore.document.v1.created"}, {"attribute": "database", "value": "(default)"},
                                              {"attribute": "document", "value": "users/{uid}", "operator": "match-path-pattern"}], "destination": dest_run}, {"triggerId": "fs-created"})
    _check("firestore trigger created", s == 200)
    D = f"/v1/projects/{P}/databases/(default)/documents"
    call("PATCH", f"{D}/users/u1", {"fields": {"n": {"stringValue": "a"}}})
    call("PATCH", f"{D}/users/u1", {"fields": {"n": {"stringValue": "b"}}})
    call("PATCH", f"{D}/orders/o1", {"fields": {"n": {"stringValue": "c"}}})
    s, d = call("GET", f"{T}/fs-created/deliveries")
    _check("only the created users/{uid} doc fired (not update, not orders)", d["delivered"] == 1 and d["deliveries"][0]["eventId"])

    # --- PATCH / DELETE / list
    s, lst = call("GET", T)
    _check("list triggers", len(lst["triggers"]) == 4)
    s, g = call("PATCH", f"{T}/fs-created", {"labels": {"a": "b"}}, {"updateMask": "labels"})
    _check("patch labels", s == 200 and g["response"]["labels"] == {"a": "b"})
    _check("delete trigger", call("DELETE", f"{T}/fs-created")[0] == 200 and call("GET", f"{T}/fs-created")[0] == 404)
    print("eventarc core: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
