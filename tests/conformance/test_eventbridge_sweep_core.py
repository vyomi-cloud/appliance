"""AWS-08 EventBridge sweep — bus/archive KMS encryption, bus logs -> CloudWatch Logs, resource-policy enforcement.
Everything goes through AwsWireRouter (Nano / unified ingress entry).
Run: PYTHONPATH=. python3 tests/conformance/test_eventbridge_sweep_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter

def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def call(r, svc, target, payload=None, account=None):
    h = {"authorization": _auth(svc), "x-amz-target": target, "content-type": "application/x-amz-json-1.1"}
    if account:
        h["x-amz-account-id"] = account
    out = r.handle("POST", "/", {}, h, json.dumps(payload or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def eb(r, op, p=None, account=None):
    return call(r, "events", f"AWSEvents.{op}", p, account)


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def main():
    r = AwsWireRouter()
    st, k = call(r, "kms", "TrentService.CreateKey", {"Description": "eb"})
    kid = k["KeyMetadata"]["KeyId"]
    st, _ = eb(r, "CreateEventBus", {"Name": "enc", "KmsKeyIdentifier": "no-such-key"})
    _check("CreateEventBus with an unknown KMS key is rejected", st == 400)
    st, out = eb(r, "CreateEventBus", {"Name": "enc", "KmsKeyIdentifier": kid,
                                        "LogConfig": {"Level": "INFO", "IncludeDetail": "FULL"}})
    _check("CreateEventBus with KMS key + LogConfig", st == 200 and out["KmsKeyIdentifier"].endswith(kid) and out["LogConfig"]["Level"] == "INFO")
    st, d = eb(r, "DescribeEventBus", {"Name": "enc"})
    _check("DescribeEventBus returns KmsKeyIdentifier + LogConfig", d["KmsKeyIdentifier"].endswith(kid) and d["LogConfig"]["IncludeDetail"] == "FULL")
    st, _ = eb(r, "CreateArchive", {"ArchiveName": "enc-arch", "EventSourceArn": d["Arn"], "KmsKeyIdentifier": kid})
    _check("CreateArchive with a customer KMS key", st == 200)
    st, _ = eb(r, "CreateArchive", {"ArchiveName": "bad-arch", "EventSourceArn": d["Arn"], "KmsKeyIdentifier": "nope"})
    _check("CreateArchive with an unknown KMS key is rejected", st == 400)
    st, ar = eb(r, "DescribeArchive", {"ArchiveName": "enc-arch"})
    _check("DescribeArchive returns KmsKeyIdentifier", ar["KmsKeyIdentifier"].endswith(kid))

    st, out = eb(r, "PutEvents", {"Entries": [{"EventBusName": "enc", "Source": "app", "DetailType": "t", "Detail": json.dumps({"secret": "s3kr1t"})}]})
    _check("PutEvents on an encrypted bus succeeds", out["FailedEntryCount"] == 0)
    raw = r.msg.event_buses["enc"]["event_log"][-1]
    _check("event is stored as KMS ciphertext (no plaintext detail at rest)", "_enc" in raw and "s3kr1t" not in json.dumps(raw))
    st, ar = eb(r, "DescribeArchive", {"ArchiveName": "enc-arch"})
    _check("archive reads decrypt through KMS (EventCount)", ar["EventCount"] == 1)
    st, rp = eb(r, "StartReplay", {"ReplayName": "rp", "EventSourceArn": ar["ArchiveArn"], "EventStartTime": "2000-01-01T00:00:00Z", "EventEndTime": "2100-01-01T00:00:00Z",
                                    "Destination": {"Arn": d["Arn"]}})
    _check("StartReplay of an encrypted archive", st == 200)
    call(r, "kms", "TrentService.DisableKey", {"KeyId": kid})
    st, out = eb(r, "PutEvents", {"Entries": [{"EventBusName": "enc", "Source": "app", "DetailType": "t", "Detail": "{}"}]})
    _check("PutEvents is refused while the bus key is disabled", out["FailedEntryCount"] == 1)
    st, ar = eb(r, "DescribeArchive", {"ArchiveName": "enc-arch"})
    _check("archive payload unreadable while the key is disabled", ar["EventCount"] == 0)
    call(r, "kms", "TrentService.EnableKey", {"KeyId": kid})

    # logs
    st, g = call(r, "logs", "Logs_20140328.DescribeLogGroups", {"logGroupNamePrefix": "/aws/vendedlogs/events/event-bus/enc"})
    _check("bus log group exists in CloudWatch Logs", any(x["logGroupName"].endswith("/enc") for x in g["logGroups"]))
    st, ev = call(r, "logs", "Logs_20140328.FilterLogEvents", {"logGroupName": "/aws/vendedlogs/events/event-bus/enc"})
    msgs = [json.loads(e["message"]) for e in ev["events"]]
    _check("EVENT_RECEIVED logged with detail (IncludeDetail=FULL)", any(m["message_type"] == "EVENT_RECEIVED" and m.get("detail") == {"secret": "s3kr1t"} for m in msgs))
    eb(r, "UpdateEventBus", {"Name": "enc", "LogConfig": {"Level": "OFF", "IncludeDetail": "NONE"}})
    n = len(msgs)
    eb(r, "PutEvents", {"Entries": [{"EventBusName": "enc", "Source": "app", "DetailType": "t", "Detail": "{}"}]})
    st, ev = call(r, "logs", "Logs_20140328.FilterLogEvents", {"logGroupName": "/aws/vendedlogs/events/event-bus/enc"})
    _check("Level OFF stops logging", len(ev["events"]) == n)

    # policy
    eb(r, "CreateEventBus", {"Name": "shared"})
    put = {"Entries": [{"EventBusName": "shared", "Source": "x", "DetailType": "t", "Detail": "{}"}]}
    st, out = eb(r, "PutEvents", put, account="999999999999")
    _check("cross-account PutEvents is denied without a policy", out["Entries"][0].get("ErrorCode") == "AccessDeniedException")
    st, out = eb(r, "PutEvents", put)
    _check("same-account PutEvents is unaffected", out["FailedEntryCount"] == 0)
    st, _ = eb(r, "PutPermission", {"EventBusName": "shared", "StatementId": "allow999", "Principal": "999999999999", "Action": "events:PutEvents"})
    _check("PutPermission", st == 200)
    st, d = eb(r, "DescribeEventBus", {"Name": "shared"})
    _check("DescribeEventBus returns the policy statement", "allow999" in d["Policy"])
    st, out = eb(r, "PutEvents", put, account="999999999999")
    _check("cross-account PutEvents allowed by policy", out["FailedEntryCount"] == 0)
    st, out = eb(r, "PutEvents", put, account="888888888888")
    _check("a different account is still denied", out["FailedEntryCount"] == 1)
    eb(r, "RemovePermission", {"EventBusName": "shared", "StatementId": "allow999"})
    st, out = eb(r, "PutEvents", put, account="999999999999")
    _check("RemovePermission revokes access", out["FailedEntryCount"] == 1)
    st, _ = eb(r, "PutPermission", {"EventBusName": "shared", "Policy": json.dumps({"Version": "2012-10-17", "Statement": [
        {"Sid": "all", "Effect": "Allow", "Principal": "*", "Action": "events:PutEvents", "Resource": "*"}]})})
    st, out = eb(r, "PutEvents", put, account="888888888888")
    _check("full-document policy with Principal * allows any account", out["FailedEntryCount"] == 0)
    print("EventBridge sweep: all checks passed")


if __name__ == "__main__":
    main()
