"""Chapter 3: the three tools. Each validates its input, talks to one AWS service and returns (text for the model, evidence for later checks).
search_docs is a plain keyword search for now; chapter 5 replaces it with real retrieval."""
import hashlib
import json
import re

from botocore.exceptions import ClientError

from aws import ddb, s3, sqs
from data import BUCKET, QUEUE, RECORDS

TOOLS = ("search_docs", "lookup_record", "file_ticket")
STOP = set("the a an of to in is are for and or on at by with what how do does when must should can i we you it that this as from my our your if there any".split())


def words(text):
    return set(w for w in re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower()) if w not in STOP)


def search_docs(query, **_):
    """Read every handbook document from S3 and score each line by the share of the query's words it contains."""
    q = words(query)
    best = []
    for obj in s3.list_objects_v2(Bucket=BUCKET, Prefix="docs/").get("Contents", []):
        name = obj["Key"].split("/")[-1]
        for line in s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read().decode().splitlines()[1:]:
            if line.strip() and q:
                best.append((len(q & words(line)) / len(q), name, line.strip()))
    best.sort(reverse=True)
    keep = [b for b in best[:2] if b[0] >= 0.5]
    if not keep:
        return "No passage in the handbook answers this. If the question names an asset or work order id, use lookup_record; otherwise refuse.", {"docs": []}
    return "\n".join('<doc name="%s">%s</doc>' % (n, t) for _, n, t in keep), {"docs": sorted(set(n for _, n, _ in keep))}


def _plain(item):
    return {k: (v.get("S") if "S" in v else v.get("N")) for k, v in item.items()}


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
    """Idempotent: the ticket id comes from the request itself, so asking twice files it once. (Nano re-runs a Lambda for every model call; so does any retry.)"""
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
