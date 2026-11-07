"""Cloud Run / Functions advanced template settings (run: PYTHONPATH=. python3 tests/conformance/test_gcp_run_ext.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_run_core as rn  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:300] if detail and not ok else ''}")


L = "/v2/projects/p1/locations/us-central1"
st = rn.RunStore()
KMS = "projects/p1/locations/us-central1/keyRings/r/cryptoKeys/k"
def _refs(kind, *a):
    return {"sql": lambda: a[1] == "db1", "kms": lambda: a[0] == KMS, "bucket": lambda: a[0] == "bkt"}[kind]()


st.refs = _refs


def call(method, path, body=None, query=None):
    r = rn.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def svc(sid, tpl, **top):
    base = {"containers": [{"image": "gcr.io/x/app:1"}]}
    base.update(tpl)
    return call("POST", L + "/services", {"template": base, **top}, {"serviceId": sid})


# probes
probe = {"httpGet": {"path": "/healthz", "port": 8080}, "periodSeconds": 5, "timeoutSeconds": 2, "failureThreshold": 4}
s, o = svc("probe", {"containers": [{"image": "gcr.io/x/a:1", "startupProbe": probe, "livenessProbe": {"tcpSocket": {"port": 8080}}}]})
check("startup + liveness probes accepted and round-trip", s == 200 and o["response"]["template"]["containers"][0]["startupProbe"]["httpGet"]["path"] == "/healthz", o)
for nm, p in [("two kinds", {"httpGet": {}, "tcpSocket": {}}), ("timeout>period", {"httpGet": {}, "periodSeconds": 2, "timeoutSeconds": 5}),
              ("relative path", {"httpGet": {"path": "healthz"}}), ("period 0", {"httpGet": {}, "periodSeconds": 0}), ("none", {})]:
    check("probe rejected: " + nm, svc("bp-" + nm.replace(">", "gt").replace(" ", "").replace("0", "z"), {"containers": [{"image": "i", "startupProbe": p}]})[0] == 400)
# volumes + ephemeral disk
vol = {"volumes": [{"name": "scratch", "emptyDir": {"medium": "DISK", "sizeLimit": "10Gi"}}],
       "containers": [{"image": "i", "volumeMounts": [{"name": "scratch", "mountPath": "/tmp/work"}]}]}
s, o = svc("vol", vol)
check("ephemeral disk (emptyDir DISK 10Gi) accepted", s == 200 and o["response"]["template"]["volumes"][0]["emptyDir"]["sizeLimit"] == "10Gi", o)
check("ephemeral disk needs a size limit", svc("vol2", {**vol, "volumes": [{"name": "scratch", "emptyDir": {"medium": "DISK"}}]})[0] == 400)
check("ephemeral disk needs gen2", svc("vol3", {**vol, "executionEnvironment": "EXECUTION_ENVIRONMENT_GEN1"})[0] == 400)
check("mount of undefined volume -> 400", svc("vol4", {"containers": [{"image": "i", "volumeMounts": [{"name": "nope", "mountPath": "/x"}]}]})[0] == 400)
check("unmounted volume -> 400", svc("vol5", {"volumes": [{"name": "u", "emptyDir": {}}]})[0] == 400)
check("duplicate mount path -> 400", svc("vol6", {"volumes": [{"name": "a", "emptyDir": {}}, {"name": "b", "emptyDir": {}}],
      "containers": [{"image": "i", "volumeMounts": [{"name": "a", "mountPath": "/m"}, {"name": "b", "mountPath": "/m"}]}]})[0] == 400)
check("two volume kinds -> 400", svc("vol7", {"volumes": [{"name": "a", "emptyDir": {}, "nfs": {"server": "s", "path": "/p"}}]})[0] == 400)
mount_gcs = {"volumes": [{"name": "b", "gcs": {"bucket": "bkt"}}], "containers": [{"image": "i", "volumeMounts": [{"name": "b", "mountPath": "/data"}]}]}
check("GCS volume on an existing bucket ok", svc("gcsv", mount_gcs)[0] == 200)
mount_gcs["volumes"][0]["gcs"]["bucket"] = "ghost"
check("GCS volume on a missing bucket -> 400", svc("gcsv2", mount_gcs)[0] == 400)
# Cloud SQL
sqlv = {"volumes": [{"name": "cloudsql", "cloudSqlInstance": {"instances": ["p1:us-central1:db1"]}}],
        "containers": [{"image": "i", "volumeMounts": [{"name": "cloudsql", "mountPath": "/cloudsql"}]}]}
check("Cloud SQL volume on an existing instance ok", svc("sqlok", sqlv)[0] == 200)
sqlv["volumes"][0]["cloudSqlInstance"]["instances"] = ["p1:us-central1:ghost"]
check("Cloud SQL volume on a missing instance -> 400", svc("sqlbad", sqlv)[0] == 400)
sqlv["volumes"][0]["cloudSqlInstance"]["instances"] = ["not-a-connection-name"]
check("malformed connection name -> 400", svc("sqlbad2", sqlv)[0] == 400)
check("Cloud SQL must mount at /cloudsql", svc("sqlbad3", {**sqlv, "volumes": [{"name": "cloudsql", "cloudSqlInstance": {"instances": ["p1:us-central1:db1"]}}],
      "containers": [{"image": "i", "volumeMounts": [{"name": "cloudsql", "mountPath": "/sql"}]}]})[0] == 400)
check("annotation form (functions) validated", svc("sqlann", {"annotations": {"run.googleapis.com/cloudsql-instances": "p1:us-central1:ghost"}})[0] == 400)
# CMEK + BinAuthz
s, o = svc("cmek", {"encryptionKey": KMS, "encryptionKeyRevocationAction": "SHUTDOWN"}, binaryAuthorization={"useDefault": True})
check("CMEK + default Binary Authorization accepted", s == 200 and o["response"]["template"]["encryptionKey"] == KMS and o["response"]["binaryAuthorization"]["useDefault"], o)
check("missing KMS key -> 400", svc("cmek2", {"encryptionKey": KMS.replace("/k", "/zz")})[0] == 400)
check("KMS key in another region -> 400", svc("cmek3", {"encryptionKey": KMS.replace("us-central1", "europe-west1")})[0] == 400)
check("revocation action without a key -> 400", svc("cmek4", {"encryptionKeyRevocationAction": "SHUTDOWN"})[0] == 400)
check("binauthz needs exactly one of useDefault/policy", svc("ba", {}, binaryAuthorization={"useDefault": True, "policy": "projects/p/platforms/cloudRun/policies/x"})[0] == 400)
check("binauthz policy shape", svc("ba2", {}, binaryAuthorization={"policy": "bogus"})[0] == 400)
check("binauthz named policy must exist (enforced at deploy)", svc("ba3x", {}, binaryAuthorization={"policy": "projects/p1/platforms/cloudRun/policies/default"})[0] == 400)
from core import gcp_binauthz_core as _ba  # noqa: E402
_ba.dispatch(st, "POST", "/v1/projects/p1/platforms/cloudRun/policies", {"policyId": "default"}, {}, json.dumps({"defaultAdmissionRule": {"evaluationMode": "ALWAYS_ALLOW", "enforcementMode": "ENFORCED_BLOCK_AND_AUDIT_LOG"}}).encode())
check("binauthz policy accepted", svc("ba3", {}, binaryAuthorization={"policy": "projects/p1/platforms/cloudRun/policies/default"})[0] == 200)
# revision tags
s, o = svc("tg", {})
s2, o2 = call("PATCH", L + "/services/tg", {"template": {"containers": [{"image": "gcr.io/x/app:2"}]}, "traffic": [
    {"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100, "tag": "canary"}]}, {"updateMask": "template,traffic"})
s3, v = call("GET", L + "/services/tg")
ts = v.get("trafficStatuses", [{}])[0]
check("revision tag yields a tagged URL", s2 == 200 and ts.get("tag") == "canary" and "canary---" in ts.get("uri", ""), v)
check("bad tag rejected", call("PATCH", L + "/services/tg", {"traffic": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100, "tag": "Bad_Tag"}]}, {"updateMask": "traffic"})[0] == 400)
check("duplicate tag rejected", call("PATCH", L + "/services/tg", {"traffic": [
    {"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 50, "tag": "a"}, {"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 50, "tag": "a"}]}, {"updateMask": "traffic"})[0] == 400)
# autoscaling
t = {"scaling": {"minInstanceCount": 1, "maxInstanceCount": 10}, "maxInstanceRequestConcurrency": 10, "annotations": {rn._ANN_TARGET: "50"}}
check("scale: idle -> min", rn.desired_instances(t, 0, 0) == 1)
check("scale: 20 in flight @ conc 10 x 50% -> 4", rn.desired_instances(t, 20, 0) == 4, rn.desired_instances(t, 20, 0))
check("scale: capped at max", rn.desired_instances(t, 10000, 0) == 10)
check("autoscaling target out of range -> 400", svc("as", {"annotations": {rn._ANN_TARGET: "150"}})[0] == 400)
# job does not accept probes
s, o = call("POST", L + "/jobs", {"template": {"template": {"containers": [{"image": "i", "startupProbe": probe}]}}}, {"jobId": "j1"})
check("jobs reject probes", s == 400)
# Eventarc: Cloud Storage source, end to end through the real router (object upload -> function invoked)
from core.aws_wire_router import AwsWireRouter  # noqa: E402
R = AwsWireRouter()
from core import gcp_storage_core as G  # noqa: E402
G.dispatch(R.gcs, "POST", "/storage/v1/b", {"project": "p1"}, {}, json.dumps({"name": "evt-bkt"}).encode())
fn_ann = {"vyomi.dev/function-runtime": "Python 3.13", "vyomi.dev/function-entry-point": "handler",
          "vyomi.dev/function-source": "def handler(event):\n    return {'seen': event.get('subject')}\n"}
rs = R.gcp_run
def rcall(method, path, body=None, query=None):
    r = rn.dispatch(rs, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")
rcall("POST", L + "/services", {"template": {"containers": [{"image": "vyomi.dev/function-source/python-3-13:aaaa"}]}, "annotations": fn_ann}, {"serviceId": "onfile"})
s, t = rcall("POST", L + "/services/onfile/triggers", {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": "evt-bkt"}]}, {"triggerId": "t1"})
check("storage trigger created", s == 200 and t["eventType"].endswith("finalized") and t["bucket"] == "evt-bkt", t)
check("trigger on a missing bucket -> 400", rcall("POST", L + "/services/onfile/triggers", {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.finalized"}, {"attribute": "bucket", "value": "nope"}]}, {"triggerId": "t2"})[0] == 400)
check("storage trigger needs a bucket filter", rcall("POST", L + "/services/onfile/triggers", {"eventFilters": [{"attribute": "type", "value": "google.cloud.storage.object.v1.deleted"}]}, {"triggerId": "t3"})[0] == 400)
from core import gcp_storage_core as G  # noqa: E402
up = G.dispatch(R.gcs, "POST", "/upload/storage/v1/b/evt-bkt/o", {"name": "a.txt", "uploadType": "media"}, {"content-type": "text/plain"}, b"hello")
trg = rs.triggers[L[4:] + "/services/onfile/triggers/t1"]
check("object upload fires the Eventarc trigger (function invoked)", up.status == 200 and trg["_eventCount"] == 1 and not trg["_lastError"], (up.status, trg))
G.dispatch(R.gcs, "DELETE", "/storage/v1/b/evt-bkt/o/a.txt", {}, {}, b"")
check("object delete does not fire a finalize trigger", trg["_eventCount"] == 1)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
