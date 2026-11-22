"""Eventarc API v1 -> Cloud Function destination (regression: the Eventarc core rewrite refused `destination.cloudFunction`,
so storage/Pub/Sub events never reached functions; offline-post-create-gcp-event-delivery failed).
Run: PYTHONPATH=. python tests/conformance/test_gcp_eventarc_function_dest.py"""
import json
import sys
import time

from core.aws_wire_router import AwsWireRouter
from core.app_context import gcp_functions_state, REQUEST_PROVIDER
AwsWireRouter.STRICT_GCP_PROJECT = False
REQUEST_PROVIDER.set("gcp")   # function state is space-scoped per provider

P, L = "demo", "us-central1"
PUBSUB = "google.cloud.pubsub.topic.v1.messagePublished"
fails = 0


def check(name, cond, extra=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}{'' if cond else ' :: ' + str(extra)}")
    fails += not cond


r = AwsWireRouter()


def call(method, path, body=None, query=None):
    out = r.handle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    try:
        return out["status"], json.loads(out["body"] or b"{}")
    except Exception:
        return out["status"], {}


T = f"/v1/projects/{P}/locations/{L}/triggers"
filt = [{"attribute": "type", "value": PUBSUB}]
fref = f"projects/{P}/locations/{L}/functions/evtfn"

s, e = call("POST", T, {"eventFilters": filt, "destination": {"cloudFunction": fref}}, {"triggerId": "ghost"})
check("missing function destination -> 400 FAILED_PRECONDITION", s == 400 and e["error"]["status"] == "FAILED_PRECONDITION", e)

gcp_functions_state.setdefault("functions", {})["evtfn"] = {
    "name": "evtfn", "runtime": "python312", "entryPoint": "e", "eventTrigger": {"eventType": PUBSUB},
    "code": "import functions_framework\n\n@functions_framework.cloud_event\ndef e(ce):\n    return {'type': ce['type']}\n"}
s, e = call("POST", T, {"eventFilters": filt, "destination": {"cloudFunction": fref}}, {"triggerId": "ftrig"})
check("trigger with existing function destination accepted", s in (200, 202), e)
topic = e["response"]["transport"]["pubsub"]["topic"] if s in (200, 202) else ""
call("POST", f"/v1/{topic}:publish", {"messages": [{"data": "cGluZw=="}]})
fn = gcp_functions_state["functions"]["evtfn"]
for _ in range(60):
    if any(i.get("source") == "eventarc" for i in fn.get("invocations", [])):
        break
    time.sleep(0.25)
inv = [i for i in fn.get("invocations", []) if i.get("source") == "eventarc"]
check("Pub/Sub publish delivered a CloudEvent to the function", bool(inv) and inv[-1]["status"] == "SUCCESS", inv)
sys.exit(1 if fails else 0)
