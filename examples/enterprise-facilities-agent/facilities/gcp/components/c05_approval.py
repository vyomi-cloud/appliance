"""C5: write actions behind a human approval, assembled from parts (the owner's chosen pattern, not a workflow orchestrator):
agent -> ledger row PENDING + message on the Pub/Sub request topic -> approver reads the approver-inbox subscription -> approval-decision Cloud Run function
checks and records APPROVED/REJECTED in the Firestore ledger -> the waiting caller polls the ledger -> create-work-order function runs only on APPROVED."""
import json, threading, time
from google.api_core import exceptions as gex
from ..runtime import NAMES, LANE, Blocked, need_grpc
from .. import deploy

APPROVER = "duty.manager@example.com"


def setup(ctx):
    def wired():
        need_grpc(ctx, "pubsub")
        need_grpc(ctx, "firestore")
        pub, sub = ctx.pubsub()
        pub.get_topic(request={"topic": ctx.state["topic"]})
        sub.get_subscription(request={"subscription": ctx.state["inbox"]})
        for k in ("decide_uri", "wo_uri"):
            assert ctx.state.get(k), f"{k} was not deployed (component 7)"
        return f"topic {NAMES['topic']} -> subscription {NAMES['inbox']}, decision + create-work-order functions, Firestore ledger {NAMES['ledger']}"
    ctx.step("approval path is wired: Pub/Sub topic + approver-inbox, decision and create-work-order functions, Firestore ledger", wired)


def _pull(ctx, rid):
    _, sub = ctx.pubsub()
    for _ in range(20):
        for m in sub.pull(request={"subscription": ctx.state["inbox"], "max_messages": 10}, timeout=15).received_messages:
            body = json.loads(m.message.data)
            if body.get("request_id") == rid:
                return body, m.ack_id
            sub.modify_ack_deadline(request={"subscription": ctx.state["inbox"], "ack_ids": [m.ack_id], "ack_deadline_seconds": 0})   # not ours: release it
        time.sleep(0.3)
    return None, None


def _wait_decision(ctx, rid, out, tries=80):
    """The waiting caller (the part of the agent run parked on the approval): polls the ledger until the status leaves PENDING."""
    ref = ctx.firestore().collection(NAMES["ledger"]).document(rid)
    for _ in range(tries):
        row = ref.get().to_dict() or {}
        if row.get("status") not in (None, "PENDING"):
            out["row"] = row
            return
        time.sleep(0.25)


def run(ctx):
    res = ctx.state.get("result", {})
    ap = res.get("approval")
    if not ap:
        ctx.step("agent produced an approval request", lambda: (_ for _ in ()).throw(AssertionError("the agent run did not submit a work order request")))
        return
    rid = ap["request_id"]
    db = ctx.firestore()
    ledger = lambda r: (db.collection(NAMES["ledger"]).document(r).get().to_dict() or {})

    def pending():
        row = ledger(rid)
        assert row.get("status") == "PENDING", row
        return f"ledger {row['status']} for {rid}, requester {row.get('requester')}"
    ctx.step("agent write is parked: ledger PENDING (no work order yet)", pending)

    def no_wo_yet():
        wos = [d.to_dict() for d in db.collection(NAMES["work_orders"]).stream()]
        assert not [w for w in wos if w.get("requester") == ctx.state.get("user")], "work order exists before approval"
        return "no work order exists before approval"
    ctx.step("no write happens before approval", no_wo_yet)
    box = {}

    def inbox():
        body, ack = _pull(ctx, rid)
        assert body, "no approval message reached the approver inbox subscription"
        box.update(msg=body, ack=ack)
        return f"approval request delivered to {NAMES['inbox']}: {body.get('summary')[:60]}"
    ctx.step("pub/sub: approver inbox receives the approval request", inbox)

    def premature():
        out = deploy.call_function(ctx, ctx.state["wo_uri"], {"request_id": rid})
        assert out.get("ok") is False and "APPROVED" in out.get("error", ""), out
        assert not ledger(rid).get("work_order_id")
        return "create-work-order refuses while the ledger is PENDING"
    ctx.step("cloud run function: create-work-order refuses an unapproved request", premature, lane=LANE["sandbox"])

    def stranger():
        out = deploy.call_function(ctx, ctx.state["decide_uri"], {"request_id": rid, "decision": "APPROVE", "approver": "mallory@evil.test"})
        assert out.get("ok") is False and ledger(rid).get("status") == "PENDING", out
        return "an unauthorised approver cannot decide; ledger still PENDING"
    ctx.step("cloud run function: approval-decision rejects an unauthorised approver", stranger, lane=LANE["sandbox"])

    def approve():
        got = {}
        t = threading.Thread(target=_wait_decision, args=(ctx, rid, got))
        t.start()
        out = deploy.call_function(ctx, ctx.state["decide_uri"], {"request_id": rid, "decision": "APPROVE", "approver": APPROVER})
        assert out.get("ok") and out["status"] == "APPROVED", out
        t.join(timeout=30)
        assert got.get("row", {}).get("status") == "APPROVED", f"the waiting caller saw {got}"
        if box.get("ack"):
            ctx.pubsub()[1].acknowledge(request={"subscription": ctx.state["inbox"], "ack_ids": [box["ack"]]})
        wo = deploy.call_function(ctx, ctx.state["wo_uri"], {"request_id": rid})
        assert wo.get("ok"), wo
        ctx.state["work_order_id"] = wo["work_order_id"]
        row = ledger(rid)
        assert row["status"] == "EXECUTED" and row["work_order_id"] == wo["work_order_id"] and row["approver"] == APPROVER, row
        w = db.collection(NAMES["work_orders"]).document(wo["work_order_id"]).get().to_dict()
        assert w["asset_id"] == "B-12" and w["status"] == "OPEN", w
        return f"decision function -> ledger APPROVED -> caller saw it -> {wo['work_order_id']} created, ledger EXECUTED"
    ctx.step("approver approves: function records APPROVED, waiting caller proceeds, work order created", approve, lane=LANE["sandbox"])

    def idempotent():
        wo = deploy.call_function(ctx, ctx.state["wo_uri"], {"request_id": rid})
        n = [d for d in db.collection(NAMES["work_orders"]).stream() if d.to_dict().get("work_order_id") == ctx.state.get("work_order_id")]
        assert wo.get("ok") and wo.get("idempotent") and len(n) == 1, (wo, len(n))
        return "second create-work-order call is idempotent (one work order)"
    if ctx.state.get("work_order_id"):
        ctx.step("create-work-order is idempotent on an EXECUTED request", idempotent, lane=LANE["sandbox"])

    def reject():
        r2 = "req-reject01"
        ctx.io.start_approval(r2, {"request_id": r2, "asset_id": "EL-3", "summary": "Replace elevator 3 (should be rejected)", "priority": "P3", "requester": "test"})
        body, ack = _pull(ctx, r2)
        assert body, "the second request never reached the inbox"
        out = deploy.call_function(ctx, ctx.state["decide_uri"], {"request_id": r2, "decision": "REJECT", "approver": APPROVER})
        assert out.get("ok") and out["status"] == "REJECTED", out
        ctx.pubsub()[1].acknowledge(request={"subscription": ctx.state["inbox"], "ack_ids": [ack]})
        refused = deploy.call_function(ctx, ctx.state["wo_uri"], {"request_id": r2})
        assert refused.get("ok") is False, refused
        wos = [d.to_dict() for d in db.collection(NAMES["work_orders"]).stream()]
        assert not [w for w in wos if w["asset_id"] == "EL-3" and w.get("requester") == "test"], "work order created despite rejection"
        return "REJECTED in the ledger, create-work-order refuses, no work order written"
    ctx.step("approver rejects: ledger REJECTED, nothing is written", reject, lane=LANE["sandbox"])
