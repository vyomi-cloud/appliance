"""AWS-13 EventBridge partner event sources: partner create -> customer bus association -> PutPartnerEvents delivery to a rule target.
Via AwsWireRouter. Run: PYTHONPATH=. python3 tests/conformance/test_eventbridge_partner_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def call(r, svc, target, body):
    h = {"authorization": _auth(svc), "x-amz-target": target, "content-type": "application/x-amz-json-1.1" if svc == "events" else "application/x-amz-json-1.0"}
    out = r.handle("POST", "/", {}, h, json.dumps(body).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def ev(r, op, body):
    return call(r, "events", "AWSEvents." + op, body)


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


SRC = "aws.partner/vyomi.cloud/shop-1/orders"


def main():
    r = AwsWireRouter()
    st, o = ev(r, "CreatePartnerEventSource", {"Name": "bad-name", "Account": "123456789012"})
    _check("invalid partner source name -> ValidationException", st == 400 and o["__type"] == "ValidationException")
    st, o = ev(r, "CreatePartnerEventSource", {"Name": SRC, "Account": "12"})
    _check("invalid account -> ValidationException", st == 400)
    st, o = ev(r, "CreatePartnerEventSource", {"Name": SRC, "Account": "123456789012"})
    _check("CreatePartnerEventSource returns an event-source ARN", st == 200 and o["EventSourceArn"].endswith("event-source/" + SRC))
    st, o = ev(r, "CreatePartnerEventSource", {"Name": SRC, "Account": "123456789012"})
    _check("duplicate -> ResourceAlreadyExistsException", st == 400 and o["__type"] == "ResourceAlreadyExistsException")
    st, o = ev(r, "ListPartnerEventSources", {})
    _check("ListPartnerEventSources requires NamePrefix", st == 400)
    st, o = ev(r, "ListPartnerEventSources", {"NamePrefix": "aws.partner/vyomi.cloud"})
    _check("ListPartnerEventSources by prefix", [x["Name"] for x in o["PartnerEventSources"]] == [SRC])
    st, o = ev(r, "ListPartnerEventSourceAccounts", {"EventSourceName": SRC})
    _check("source accounts show PENDING", o["PartnerEventSourceAccounts"][0]["State"] == "PENDING")
    st, o = ev(r, "ListEventSources", {})
    _check("customer sees the source PENDING", o["EventSources"][0]["State"] == "PENDING" and o["EventSources"][0]["CreatedBy"] == "vyomi.cloud")
    st, o = ev(r, "PutPartnerEvents", {"Entries": [{"Source": SRC, "DetailType": "Order", "Detail": "{}"}]})
    _check("PutPartnerEvents on PENDING source fails per entry", o["FailedEntryCount"] == 1 and o["Entries"][0]["ErrorCode"] == "InvalidStateException")
    st, o = ev(r, "ActivateEventSource", {"Name": SRC})
    _check("Activate with no associated bus -> InvalidStateException", st == 400 and o["__type"] == "InvalidStateException")
    st, o = ev(r, "CreateEventBus", {"Name": "other", "EventSourceName": SRC})
    _check("bus name must equal source name", st == 400)
    st, o = ev(r, "CreateEventBus", {"Name": SRC, "EventSourceName": SRC})
    _check("CreateEventBus with EventSourceName", st == 200)
    st, o = ev(r, "DescribeEventSource", {"Name": SRC})
    _check("source becomes ACTIVE once a bus exists", o["State"] == "ACTIVE")

    # real delivery: bus rule -> SQS queue
    sqs = lambda op, b: call(r, "sqs", "AmazonSQS." + op, b)
    st, q = sqs("CreateQueue", {"QueueName": "partner-q"})
    url = q["QueueUrl"]
    st, a = sqs("GetQueueAttributes", {"QueueUrl": url, "AttributeNames": ["QueueArn"]})
    arn = a["Attributes"]["QueueArn"]
    ev(r, "PutRule", {"Name": "r1", "EventBusName": SRC, "EventPattern": json.dumps({"source": [SRC]})})
    ev(r, "PutTargets", {"Rule": "r1", "EventBusName": SRC, "Targets": [{"Id": "t", "Arn": arn}]})
    st, o = ev(r, "PutPartnerEvents", {"Entries": [{"Source": SRC, "DetailType": "Order", "Detail": json.dumps({"id": 7})}, {"Source": "aws.partner/x/y", "DetailType": "d", "Detail": "{}"}]})
    _check("PutPartnerEvents: one delivered, unknown source fails", o["FailedEntryCount"] == 1 and "EventId" in o["Entries"][0] and o["Entries"][0 + 1]["ErrorCode"] == "ResourceNotFoundException")
    st, m = sqs("ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 5})
    body = json.loads(m["Messages"][0]["Body"]) if m.get("Messages") else {}
    _check("the partner event reached the rule target with source + detail", body.get("source") == SRC and body.get("detail") == {"id": 7})
    st, o = ev(r, "DeactivateEventSource", {"Name": SRC})
    _check("DeactivateEventSource", st == 200)
    st, o = ev(r, "PutPartnerEvents", {"Entries": [{"Source": SRC, "DetailType": "Order", "Detail": "{}"}]})
    _check("deactivated source rejects events", o["FailedEntryCount"] == 1)
    ev(r, "ActivateEventSource", {"Name": SRC})
    st, o = ev(r, "DeleteEventBus", {"Name": SRC})
    st, o = ev(r, "ListPartnerEventSourceAccounts", {"EventSourceName": SRC})
    _check("deleting the bus deletes the source for the customer", st == 400)
    st, o = ev(r, "CreatePartnerEventSource", {"Name": SRC, "Account": "123456789012"})
    st, o = ev(r, "DeletePartnerEventSource", {"Name": SRC, "Account": "123456789012"})
    _check("DeletePartnerEventSource", st == 200)
    print("PASS eventbridge partner event sources")


if __name__ == "__main__":
    main()
