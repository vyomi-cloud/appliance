"""GCP Security Command Center-lite: threat + vulnerability findings, Container Analysis occurrences, Artifact Registry image scanning.
Run: PYTHONPATH=. <venv python> tests/conformance/test_gcp_secscan.py"""
import json
import sys

from core.aws_wire_router import AwsWireRouter
AwsWireRouter.STRICT_GCP_PROJECT = False   # engine conformance uses ad-hoc project ids (main's one-project-per-space rule is exercised elsewhere)
from core import gcp_artifactregistry_core as ar

n = 0


def check(c, m):
    global n
    if not c:
        print("FAIL:", m)
        sys.exit(1)
    n += 1


r = AwsWireRouter()
P = "vyomi-project"


def call(method, path, body=None, query=None):
    out = r.handle(method, path, query or {}, {"content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except ValueError:
        return out["status"], {}


st, _ = call("POST", f"/v1/projects/{P}/locations/us-central1/repositories", {"format": "DOCKER"}, {"repositoryId": "apps"})
check(st == 200, f"create repo {st}")
full = f"projects/{P}/locations/us-central1/repositories/apps"
cfg = {"history": [{"created_by": "/bin/sh -c pip install requests==2.19.0 pyyaml==5.3"}], "config": {"Env": ["PYTHON_VERSION=3.8.12"]}}
ver = ar.ingest_image(r.gcp_ar, full, "web", "v1")
ver["_config"] = cfg
st, d = call("GET", f"/v1/projects/{P}/securityPosture/vulnerabilities")
cats = {f["category"] for f in d["findings"]}
check(st == 200 and {"CVE-2018-18074", "CVE-2020-14343", "END_OF_LIFE_RUNTIME"} <= cats, f"image vulnerabilities {cats}")
check(all(f["findingClass"] == "VULNERABILITY" for f in d["findings"]), "finding class")
st, occ = call("GET", f"/v1/projects/{P}/occurrences")
check(st == 200 and occ["occurrences"][0]["kind"] == "VULNERABILITY" and occ["occurrences"][0]["vulnerability"]["packageIssue"][0]["fixedVersion"]["name"], "Container Analysis occurrences")
st, vo = call("GET", f"/v1/projects/{P}/occurrences", None, {"filter": 'kind="VULNERABILITY"'})
check(st == 200 and vo["occurrences"] and all(o["kind"] == "VULNERABILITY" for o in vo["occurrences"]), "kind=VULNERABILITY filter")
uri = vo["occurrences"][0]["resourceUri"]
st, one = call("GET", f"/v1/projects/{P}/occurrences", None, {"filter": f'kind="VULNERABILITY" AND resourceUrl="{uri}"'})
check(st == 200 and one["occurrences"] and all(o["resourceUri"] == uri for o in one["occurrences"]), "resourceUrl filter")
st, att = call("GET", f"/v1/projects/{P}/occurrences", None, {"filter": 'kind="ATTESTATION"'})
check(st == 200 and att["occurrences"] == [], "ATTESTATION filter excludes vulnerabilities")
st, summ = call("GET", f"/v1/projects/{P}/occurrences:vulnerabilitySummary")
check(st == 200 and summ["counts"], "vulnerability summary")
# disabling scanning on the repo removes the findings
r.gcp_ar.repos[full]["vulnerabilityScanningConfig"] = {"enablementConfig": "DISABLED"}
check(call("GET", f"/v1/projects/{P}/securityPosture/vulnerabilities")[1]["findings"] == [], "scanning disabled -> no findings")
r.gcp_ar.repos[full].pop("vulnerabilityScanningConfig")

# runtime detection: a bucket opened to allUsers
st, _ = call("POST", "/storage/v1/b", {"name": "leaky-bkt"}, {"project": P})
st, _ = call("PUT", "/storage/v1/b/leaky-bkt/iam", {"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]})
st, d = call("GET", f"/v1/projects/{P}/securityPosture/threats")
check(any(f["category"] == "PUBLIC_BUCKET_ACL_GRANTED" and f["findingClass"] == "THREAT" and f["detector"] == "vyomi-rules" for f in d["findings"]), f"threat finding {d}")
st, d = call("GET", f"/v1/projects/{P}/securityPosture/all")
check({"THREAT", "MISCONFIGURATION"} <= {f.get("findingClass", "MISCONFIGURATION") for f in d["findings"]} and d["summary"]["total"] == len(d["findings"]), "all = posture + threats + vulns")
print(f"OK {n} checks")
