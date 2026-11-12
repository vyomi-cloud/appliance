"""Cloud Run / Functions networking config: HTTP/2 end-to-end, session affinity, VPC egress, service mesh, custom audiences
(run: PYTHONPATH=. python3 tests/conformance/test_gcp_run_networking.py)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import gcp_run_core as rn  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


L = "/v2/projects/p1/locations/us-central1"
st = rn.RunStore()
st.refs = lambda kind, *a: {"vpcconn": lambda: a == ("p1", "us-central1", "conn1"), "subnet": lambda: a == ("p1", "us-central1", "sub1")}.get(kind, lambda: None)()


def call(method, path, body=None, query=None):
    r = rn.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def svc(sid, tpl, **top):
    base = {"containers": [{"image": "gcr.io/x/app:1"}]}
    base.update(tpl)
    return call("POST", L + "/services", {"template": base, **top}, {"serviceId": sid})


s, o = svc("h2", {"containers": [{"image": "i", "ports": [{"name": "h2c", "containerPort": 8080}]}]})
check("h2c port accepted + round-trips", s == 200 and o["response"]["template"]["containers"][0]["ports"][0]["name"] == "h2c", o)
check("bad port name", svc("h2b", {"containers": [{"image": "i", "ports": [{"name": "grpc", "containerPort": 80}]}]})[0] == 400)
check("two ports rejected", svc("h2c2", {"containers": [{"image": "i", "ports": [{"containerPort": 80}, {"containerPort": 81}]}]})[0] == 400)
check("port out of range", svc("h2d", {"containers": [{"image": "i", "ports": [{"containerPort": 70000}]}]})[0] == 400)
check("sidecar port rejected", svc("h2e", {"containers": [{"image": "i"}, {"image": "j", "ports": [{"containerPort": 9000}]}]})[0] == 400)
s, o = svc("aff", {"sessionAffinity": True})
check("sessionAffinity true", s == 200 and o["response"]["template"]["sessionAffinity"] is True)
check("sessionAffinity non-bool", svc("aff2", {"sessionAffinity": "yes"})[0] == 400)
s, o = svc("vc", {"vpcAccess": {"connector": "projects/p1/locations/us-central1/connectors/conn1", "egress": "ALL_TRAFFIC"}})
check("connector egress", s == 200 and o["response"]["template"]["vpcAccess"]["egress"] == "ALL_TRAFFIC", o)
check("missing connector", svc("vc2", {"vpcAccess": {"connector": "projects/p1/locations/us-central1/connectors/nope"}})[0] == 400)
check("connector wrong region", svc("vc3", {"vpcAccess": {"connector": "projects/p1/locations/europe-west1/connectors/conn1"}})[0] == 400)
check("bad connector name", svc("vc4", {"vpcAccess": {"connector": "conn1"}})[0] == 400)
check("bad egress", svc("vc5", {"vpcAccess": {"connector": "projects/p1/locations/us-central1/connectors/conn1", "egress": "SOME"}})[0] == 400)
check("connector + direct VPC rejected", svc("vc6", {"vpcAccess": {"connector": "projects/p1/locations/us-central1/connectors/conn1", "networkInterfaces": [{"network": "default"}]}})[0] == 400)
s, o = svc("dv", {"vpcAccess": {"egress": "PRIVATE_RANGES_ONLY", "networkInterfaces": [{"network": "default", "subnetwork": "sub1", "tags": ["egress"]}]}})
check("direct VPC egress with real subnet", s == 200, o)
check("direct VPC unknown subnet", svc("dv2", {"vpcAccess": {"networkInterfaces": [{"subnetwork": "ghost"}]}})[0] == 400)
check("egress without a network path", svc("dv3", {"vpcAccess": {"egress": "ALL_TRAFFIC"}})[0] == 400)
check("direct VPC bad tag", svc("dv4", {"vpcAccess": {"networkInterfaces": [{"network": "default", "tags": ["Bad Tag"]}]}})[0] == 400)
s, o = svc("mesh", {"serviceMesh": {"mesh": "projects/p1/locations/global/meshes/m1"}})
check("service mesh", s == 200)
check("bad mesh", svc("mesh2", {"serviceMesh": {"mesh": "m1"}})[0] == 400)
s, o = svc("aud", {}, customAudiences=["https://api.example.com", "svc.internal"])
check("custom audiences stored", s == 200 and o["response"]["customAudiences"] == ["https://api.example.com", "svc.internal"], o)
check("duplicate audiences", svc("aud2", {}, customAudiences=["a", "a"])[0] == 400)
s, o = call("PATCH", L + "/services/aud", {"customAudiences": ["only"]}, {"updateMask": "customAudiences"})
check("patch audiences", s == 200 and call("GET", L + "/services/aud")[1]["customAudiences"] == ["only"], o)
s, o = call("PATCH", L + "/services/h2", {"template": {"containers": [{"image": "i", "ports": [{"name": "http1", "containerPort": 8080}]}]}}, {"updateMask": "template"})
check("switching h2c -> http1 makes a new revision", s == 200 and call("GET", L + "/services/h2")[1]["template"]["containers"][0]["ports"][0]["name"] == "http1")
s, o = call("POST", L + "/jobs", {"template": {"template": {"containers": [{"image": "i", "ports": [{"containerPort": 80}]}]}}}, {"jobId": "j1"})
check("jobs reject ports", s == 400)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
