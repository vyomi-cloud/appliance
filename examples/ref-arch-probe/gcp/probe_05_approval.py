"""C5 Approval (assembled pattern): Pub/Sub approver inbox + a Cloud Function that decides + a Firestore ledger, and a waiting caller that sees the decision.
Loop: request -> ledger PENDING -> publish -> approver pulls -> function decides -> decision written to Firestore -> ack -> waiting caller observes APPROVED."""
from _common import *
import json, threading, time

s = Step()
P = PROJECT
topic = f"projects/{P}/topics/approvals-{TAG}"
sname = f"projects/{P}/subscriptions/approver-{TAG}"
DECIDE = '''
import json

def handler(request):
    b = request.get_json(silent=True) or {}
    summary = (b.get("summary") or "").lower()
    ok = "boiler" in summary and float(b.get("cost", 0)) < 5000      # policy: facility repairs under 5k are auto-approvable by the duty manager
    return {"request_id": b.get("request_id"), "decision": "APPROVED" if ok else "REJECTED", "approver": "duty.manager@example.com"}
'''


def setup():
    pub, sub = pubsub()
    pub.create_topic(request={"name": topic})
    sub.create_subscription(request={"name": sname, "topic": topic, "ack_deadline_seconds": 30})
    deploy_function(f"decide-{TAG}", DECIDE)
    s.pub, s.sub, s.fs = pub, sub, firestore_rest()
    return "topic + subscription + decision function ready"


def loop():
    pub, sub, fs = s.pub, s.sub, s.fs
    rid = f"req-{TAG}"
    fs_set(fs, "ledger", rid, {"request_id": rid, "status": "PENDING", "summary": "replace boiler valve B-12", "cost": 1200})
    result = {}

    def waiting_caller():                     # the agent run is parked here (the Step Functions waitForTaskToken equivalent)
        for _ in range(60):
            row = fs_get(fs, "ledger", rid)
            if row["status"] != "PENDING":
                result["row"] = row
                return
            time.sleep(0.25)
    t = threading.Thread(target=waiting_caller)
    t.start()
    pub.publish(topic, json.dumps({"request_id": rid, "summary": "replace boiler valve B-12", "cost": 1200}).encode()).result(timeout=30)
    msgs = sub.pull(request={"subscription": sname, "max_messages": 5}, timeout=30).received_messages
    assert len(msgs) == 1, f"approver inbox got {len(msgs)} messages"
    req = json.loads(msgs[0].message.data)
    r = invoke_function(f"decide-{TAG}", req)
    assert r.status_code == 200, f"decision function HTTP {r.status_code} {r.text[:200]}"
    d = r.json()
    fs_set(fs, "ledger", rid, {"request_id": rid, "status": d["decision"], "approver": d["approver"], "summary": req["summary"], "cost": req["cost"]})
    sub.acknowledge(request={"subscription": sname, "ack_ids": [msgs[0].ack_id]})
    t.join(timeout=30)
    assert result.get("row", {}).get("status") == "APPROVED", f"waiting caller saw {result}"
    return f"waiting caller observed {result['row']['status']} by {result['row']['approver']}"


def fn_writes_ledger():
    """In the AWS app the approval Lambda itself writes the ledger. Can a Cloud Function do that here (needs outbound HTTP / google-cloud-firestore)?"""
    code = "import os\nfrom google.cloud import firestore\n\ndef handler(request):\n    return {'ok': True}\n"
    deploy_function(f"fnfs-{TAG}", code)
    r = invoke_function(f"fnfs-{TAG}", {})
    assert r.status_code == 200, f"function cannot import google-cloud-firestore: HTTP {r.status_code} {r.text[:160]}"
    return "function can import the Firestore SDK"


def highlevel_firestore():
    """A real app uses firestore.Client (gRPC only, no REST transport). Point it at the simulator the way users point it at an emulator."""
    from urllib.parse import urlparse
    os.environ["FIRESTORE_EMULATOR_HOST"] = urlparse(endpoint()).netloc
    from google.cloud import firestore
    from google.api_core import retry as _r
    c = firestore.Client(project=P)
    c.collection("ledger").document("hl").set({"x": 1}, timeout=8, retry=None)
    return "firestore.Client (gRPC) wrote to the simulator"


s("setup: Pub/Sub inbox + decision function (+ Firestore gapic REST client)", setup)
if hasattr(s, "fs"):
    s("full loop: request->PENDING->publish->pull->function decides->ledger APPROVED->waiting caller sees it", loop)
    s("function writes the ledger itself (import google-cloud-firestore inside a Cloud Function)", fn_writes_ledger)
s("high-level firestore.Client (gRPC) against the simulator front door", highlevel_firestore)
s.finish()
