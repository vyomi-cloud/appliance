"""C5: write actions behind a human approval, ASSEMBLED from parts (the owner's chosen pattern, not a workflow orchestrator):
agent -> Table ledger row PENDING + message on the Service Bus request topic -> approver reads the approver-inbox subscription -> approval-decision Function records
APPROVED/REJECTED in the Azure Table ledger (ETag-conditional) -> the waiting caller polls the ledger -> create-work-order Function runs only on APPROVED."""
import json, threading, time
from ..runtime import NAMES, LANE, need_result
from .. import deploy

APPROVER = "duty.manager@example.com"
APP = NAMES["functions"]


def setup(ctx):
    def wired():
        ctx.table(NAMES["ledger"]).query_entities("PartitionKey eq 'req'")
        with ctx.servicebus() as c:
            with c.get_subscription_receiver(NAMES["topic"], NAMES["inbox"], max_wait_time=1) as r:
                r.receive_messages(max_message_count=1, max_wait_time=1)
        assert ctx.state.get("funcs_deployed"), "the tool functions were not deployed (component 7)"
        return f"topic {NAMES['topic']} -> subscription {NAMES['inbox']}, decision + create-work-order functions, Table ledger {NAMES['ledger']}"
    ctx.step("approval path is wired: Service Bus topic + approver-inbox, decision and create-work-order functions, Table ledger", wired, lane=LANE["messaging"])


def _pull(ctx, rid, tries=15):
    with ctx.servicebus() as c:
        for _ in range(tries):
            with c.get_subscription_receiver(NAMES["topic"], NAMES["inbox"], max_wait_time=2) as r:
                for m in r.receive_messages(max_message_count=10, max_wait_time=2):
                    body = json.loads(b"".join(m.body).decode())
                    if body.get("request_id") == rid:
                        r.complete_message(m)
                        return body
                    r.abandon_message(m)                     # not ours: put it back
    return None


def _wait_decision(ctx, rid, out, tries=80):
    """The waiting caller (the part of the agent run parked on the approval): polls the ledger until the status leaves PENDING."""
    t = ctx.table(NAMES["ledger"])
    for _ in range(tries):
        row = dict(t.get_entity("req", rid))
        if row.get("status") not in (None, "PENDING"):
            out["row"] = row
            return
        time.sleep(0.25)


def run(ctx):
    res = ctx.state.get("result", {})
    ap = res.get("approval")
    if not ap:
        def _no_request():
            need_result(ctx, "approve")
            raise AssertionError("the agent run did not submit a work order request")
        ctx.step("agent produced an approval request", _no_request)
        return
    rid = ap["request_id"]
    ledger = lambda r: dict(ctx.table(NAMES["ledger"]).get_entity("req", r))
    wos = lambda: [dict(e) for e in ctx.table(NAMES["work_orders"]).list_entities()]

    def pending():
        row = ledger(rid)
        assert row.get("status") == "PENDING", row
        return f"ledger {row['status']} for {rid}, requester {row.get('requester')}"
    ctx.step("agent write is parked: ledger PENDING (no work order yet)", pending)

    def no_wo_yet():
        assert not [w for w in wos() if w.get("requester") == ctx.state.get("user")], "work order exists before approval"
        return "no work order exists before approval"
    ctx.step("no write happens before approval", no_wo_yet)
    box = {}

    def inbox():
        body = _pull(ctx, rid)
        assert body, "no approval message reached the approver inbox subscription"
        box["msg"] = body
        return f"approval request delivered to {NAMES['inbox']}: {body.get('summary')[:60]}"
    ctx.step("service bus: approver inbox receives the approval request (AMQP)", inbox, lane=LANE["messaging"])

    call = lambda fn, payload: deploy.call_function(ctx, APP, fn, payload)

    def premature():
        out = call("create-work-order", {"request_id": rid})
        assert out.get("ok") is False and "APPROVED" in out.get("error", ""), out
        assert not ledger(rid).get("work_order_id")
        return "create-work-order refuses while the ledger is PENDING"
    ctx.step("function: create-work-order refuses an unapproved request", premature, lane=LANE["runtime"])

    def stranger():
        out = call("approval-decision", {"request_id": rid, "decision": "APPROVE", "approver": "mallory@evil.test"})
        assert out.get("ok") is False and ledger(rid).get("status") == "PENDING", out
        return "an unauthorised approver cannot decide; ledger still PENDING"
    ctx.step("function: approval-decision rejects an unauthorised approver", stranger, lane=LANE["runtime"])

    def approve():
        got = {}
        t = threading.Thread(target=_wait_decision, args=(ctx, rid, got))
        t.start()
        out = call("approval-decision", {"request_id": rid, "decision": "APPROVE", "approver": APPROVER})
        assert out.get("ok") and out["status"] == "APPROVED", out
        t.join(timeout=30)
        assert got.get("row", {}).get("status") == "APPROVED", f"the waiting caller saw {got}"
        wo = call("create-work-order", {"request_id": rid})
        assert wo.get("ok"), wo
        ctx.state["work_order_id"] = wo["work_order_id"]
        row = ledger(rid)
        assert row["status"] == "EXECUTED" and row["work_order_id"] == wo["work_order_id"] and row["approver"] == APPROVER, row
        w = [x for x in wos() if x["work_order_id"] == wo["work_order_id"]][0]
        assert w["asset_id"] == "B-12" and w["status"] == "OPEN", w
        return f"decision function -> ledger APPROVED -> caller saw it -> {wo['work_order_id']} created, ledger EXECUTED"
    ctx.step("approver approves: function records APPROVED, waiting caller proceeds, work order created", approve, lane=LANE["runtime"])

    def idempotent():
        wo = call("create-work-order", {"request_id": rid})
        n = [w for w in wos() if w["work_order_id"] == ctx.state.get("work_order_id")]
        assert wo.get("ok") and wo.get("idempotent") and len(n) == 1, (wo, len(n))
        return "second create-work-order call is idempotent (one work order)"
    if ctx.state.get("work_order_id"):
        ctx.step("create-work-order is idempotent on an EXECUTED request", idempotent, lane=LANE["runtime"])

    def concurrent_decision():
        """Optimistic concurrency on the ledger: a decision written with a stale ETag is refused (412), so two approvers cannot both decide."""
        from azure.core import MatchConditions
        from azure.core.exceptions import HttpResponseError
        from azure.data.tables import UpdateMode
        t = ctx.table(NAMES["ledger"])
        e = t.get_entity("req", rid)
        t.update_entity({"PartitionKey": "req", "RowKey": rid, "note": "touched"}, mode=UpdateMode.MERGE)
        try:
            t.update_entity({"PartitionKey": "req", "RowKey": rid, "status": "REJECTED"}, mode=UpdateMode.MERGE, etag=e.metadata["etag"], match_condition=MatchConditions.IfNotModified)
        except HttpResponseError as ex:
            assert ex.status_code == 412, ex.status_code
            return "stale ETag decision refused with 412 (Precondition Failed)"
        raise AssertionError("a decision with a stale ETag was accepted")
    ctx.step("table ledger: a decision with a stale ETag is refused (412)", concurrent_decision, lane=LANE["data"])

    def reject():
        r2 = "req-reject01"
        ctx.io.start_approval(r2, {"request_id": r2, "asset_id": "EL-3", "summary": "Replace elevator 3 (should be rejected)", "priority": "P3", "requester": "test"})
        body = _pull(ctx, r2)
        assert body, "the second request never reached the inbox"
        out = call("approval-decision", {"request_id": r2, "decision": "REJECT", "approver": APPROVER})
        assert out.get("ok") and out["status"] == "REJECTED", out
        refused = call("create-work-order", {"request_id": r2})
        assert refused.get("ok") is False, refused
        assert not [w for w in wos() if w["asset_id"] == "EL-3" and w.get("requester") == "test"], "work order created despite rejection"
        return "REJECTED in the ledger, create-work-order refuses, no work order written"
    ctx.step("approver rejects: ledger REJECTED, nothing is written", reject, lane=LANE["messaging"])
    ctx.note("Approval is assembled (Service Bus + Function + Table ledger), not a workflow orchestrator. Service Bus and Cosmos are Vyomi's own cores (Service Bus with a real AMQP 1.0 wire); "
             "Table is a real engine (Azurite) only when VYOMI_AZURE_REAL_BACKENDS=1 on a substrate that can run it." + (" This run: real backends ON." if ctx.real_backends else " This run: real backends OFF."))
