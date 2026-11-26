"""The three tools. Each one validates its input, talks to one AWS service and returns (text for the model, evidence for the guardrails)."""
import hashlib
import json

from botocore.exceptions import ClientError

from aws import ddb, sqs
from data import MEMORY, QUEUE, RECORDS
from rag import SUPPORT_MIN, search

TOOLS = ("search_docs", "lookup_record", "file_ticket")


def _plain(item):
    return {k: (v.get("S") if "S" in v else v.get("N")) for k, v in item.items()}


def search_docs(query, **_):
    hits = search(query, k=3)
    best = hits[0]["score"] if hits else 0.0
    if best < SUPPORT_MIN:
        return "No passage in the handbook answers this (best score %.2f). If the question names an asset or work order id, use lookup_record; otherwise refuse." % best, {"docs": [], "best": best}
    keep = [h for h in hits if h["score"] >= SUPPORT_MIN][:2]
    text = "\n".join('<doc name="%s">%s</doc>' % (h["doc"], h["text"]) for h in keep)
    return text, {"docs": [h["doc"] for h in keep], "best": best}


def get_record(rid):
    got = ddb.get_item(TableName=RECORDS, Key={"id": {"S": rid.upper()}}).get("Item")
    return _plain(got) if got else None


def lookup_record(id, **_):
    rec = get_record(id)
    if not rec:
        return "There is no record with id %s." % id, {"records": []}
    fields = "; ".join("%s=%s" % (k, v) for k, v in rec.items() if k != "id")
    return '<record id="%s">%s</record>' % (rec["id"], fields), {"records": [rec["id"]]}


def file_ticket(asset_id, summary, priority, session_id="", **_):
    """Idempotent: the ticket id comes from the request itself, so asking twice files it once. (Nano re-runs a Lambda per model call; so does any retry.)"""
    asset = get_record(asset_id)
    if not asset or asset.get("kind") != "asset":
        return "Cannot file a ticket: %s is not an asset id." % asset_id, {}
    tid = "TK-" + hashlib.sha1(("%s|%s|%s|%s" % (session_id, asset["id"], priority, summary)).encode()).hexdigest()[:8]
    try:
        ddb.put_item(TableName=RECORDS, ConditionExpression="attribute_not_exists(id)",
                     Item={"id": {"S": tid}, "kind": {"S": "ticket"}, "asset_id": {"S": asset["id"]}, "priority": {"S": priority}, "summary": {"S": summary}, "status": {"S": "QUEUED"}})
        url = sqs.get_queue_url(QueueName=QUEUE)["QueueUrl"]
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"ticket": tid, "asset_id": asset["id"], "priority": priority, "summary": summary}))
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
    return "Ticket %s filed for %s, priority %s: %s" % (tid, asset["id"], priority, summary), {"ticket": tid, "ticket_text": "Ticket %s filed for %s, priority %s: %s" % (tid, asset["id"], priority, summary)}


REGISTRY = {"search_docs": search_docs, "lookup_record": lookup_record, "file_ticket": file_ticket}
