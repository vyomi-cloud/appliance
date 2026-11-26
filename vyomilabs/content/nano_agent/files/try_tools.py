"""Run each tool by hand, before any model is involved. A tool must behave the same way no matter who calls it."""
import json

import seed
from aws import ddb, sqs
from data import QUEUE, RECORDS
from tools import REGISTRY, get_record

print("queue:", seed.seed())

text, ev = REGISTRY["search_docs"]("boiler pressure above 30 psi close the main steam valve")
assert "boiler-sop.md" in ev["docs"] and "30 psi" in text, text
print("search_docs found:", ev["docs"])

text, ev = REGISTRY["search_docs"]("company vacation policy")
assert ev["docs"] == [], "a question the handbook cannot answer must return no passage"
print("search_docs on an unsupported question: no passage")

text, ev = REGISTRY["lookup_record"]("AHU-7")
assert "DEGRADED" in text and ev["records"] == ["AHU-7"], text
text, ev = REGISTRY["lookup_record"]("AHU-99")
assert "no record" in text.lower() and ev["records"] == []
print("lookup_record: AHU-7 is DEGRADED, AHU-99 does not exist")


def queued():
    url = sqs.get_queue_url(QueueName=QUEUE)["QueueUrl"]
    return int(sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]["ApproximateNumberOfMessages"])


before = queued()
t1, e1 = REGISTRY["file_ticket"]("EL-3", "Door-zone sensor faulting (chapter 3 test)", "P2", session_id="chapter3")
t2, e2 = REGISTRY["file_ticket"]("EL-3", "Door-zone sensor faulting (chapter 3 test)", "P2", session_id="chapter3")
assert e1["ticket"] == e2["ticket"], "asking twice must give the same ticket"
assert queued() == before + 1, "the same ticket must reach the queue once"
print("file_ticket:", t1)
print("filed twice, queued once: idempotent")
bad, _ = REGISTRY["file_ticket"]("WO-000101", "x", "P2", session_id="chapter3")
assert bad.startswith("Cannot file"), bad
print("a work order id is refused as an asset")
print("tools ok")
