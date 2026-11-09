"""GCP: simulated Service Health feed (servicehealth v1): empty by default, inject / resolve test incidents.
Run: PYTHONPATH=. python3 tests/conformance/test_gcp_servicehealth.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.aws_wire_router import AwsWireRouter  # noqa: E402

AwsWireRouter.STRICT_GCP_PROJECT = False
R = AwsWireRouter()
PASS = FAIL = 0
P = "svch-proj-1"
B = f"/v1/projects/{P}/locations/global"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


def call(method, path, body=None, query=None):
    out = R.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


s, d = call("GET", f"{B}/events")
check("empty incident history by default", s == 200 and d.get("events") == [], d)
s, d = call("GET", f"{B}/vyomiServiceStatus")
check("every simulated service AVAILABLE by default", s == 200 and d["services"] and all(x["status"] == "AVAILABLE" for x in d["services"]) and d["source"] == "Dev Simplified", d)

s, d = call("POST", f"{B}/events", {"title": "Compute degraded", "products": ["Compute Engine"], "severity": "OUTAGE", "locations": ["us-central1"]})
eid = d.get("name", "").rsplit("/", 1)[-1]
check("inject incident", s == 200 and d["state"] == "ACTIVE" and d["vyomiSimulated"] is True and d["vyomiSource"] == "Dev Simplified", d)
s, d = call("GET", f"{B}/events", query={"filter": "state=ACTIVE"})
check("list ACTIVE", s == 200 and len(d["events"]) == 1, d)
s, d = call("GET", f"{B}/vyomiServiceStatus")
st = {x["service"]: x["status"] for x in d["services"]}
check("service status reflects outage", st["Compute Engine"] == "SERVICE_OUTAGE" and st["Cloud Storage"] == "AVAILABLE", st)
s, d = call("POST", f"{B}/events/{eid}:addUpdate", {"description": "Investigating"})
check("add update", s == 200 and len(d["updates"]) == 2, d)
s, d = call("POST", f"{B}/events/{eid}:resolve", {})
check("resolve", s == 200 and d["state"] == "CLOSED" and d["detailedState"] == "RESOLVED" and "endTime" in d, d)
s, d = call("POST", f"{B}/events/{eid}:resolve", {})
check("double resolve is FAILED_PRECONDITION", s == 409, d)
s, d = call("GET", f"{B}/events", query={"filter": "state=ACTIVE"})
check("no ACTIVE after resolve", d["events"] == [], d)
s, d = call("GET", f"{B}/events", query={"filter": "state=CLOSED"})
check("history keeps CLOSED", len(d["events"]) == 1, d)
s, d = call("GET", f"{B}/vyomiServiceStatus")
check("status back to AVAILABLE", all(x["status"] == "AVAILABLE" for x in d["services"]), d)
s, d = call("POST", f"{B}/events", {"title": "x", "products": ["Nope"]})
check("unknown service rejected", s == 400, d)
s, d = call("POST", f"{B}/events", {"products": ["Compute Engine"]})
check("title required", s == 400, d)
s, d = call("GET", f"{B}/events/{eid}")
check("get one", s == 200 and d["name"].endswith(eid), d)
s, d = call("DELETE", f"{B}/events/{eid}")
check("delete", s == 200, d)
s, d = call("GET", f"{B}/events/{eid}")
check("deleted is 404", s == 404, d)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
