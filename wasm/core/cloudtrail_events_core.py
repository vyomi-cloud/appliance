# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""CloudTrail LookupEvents (ai-approvals lane, component C13 governance).

The wire router records one event per AWS API call it serves (management-style audit: who called which API on which resource) into a
bounded ring; CloudTrail `LookupEvents` reads it with the real filter semantics (LookupAttributes, StartTime/EndTime, MaxResults, NextToken,
newest first). Pure Python, no extra deps: the same code runs in the Nano Pyodide router and the appliance.

Honest scope: events exist from the moment the router serves them (in-memory, process-local, cap CAP). Real CloudTrail delays delivery by
minutes, records only management events for LookupEvents, and keeps 90 days; here Bedrock/Lambda invocations (data events in AWS) are also
recorded so AI calls can be audited. S3 object traffic and CloudTrail's own calls are not recorded.
"""
from __future__ import annotations

import json
import re
import time
import uuid

CAP = 10000
_ACCOUNT, _REGION = "000000000000", "us-east-1"
_SOURCE = {"stepfunctions": "states", "dynamodb": "dynamodb", "sns": "sns", "sqs": "sqs", "kms": "kms", "lambda": "lambda",
           "bedrock": "bedrock", "secretsmanager": "secretsmanager", "events": "events", "iam": "iam", "sts": "sts", "logs": "logs",
           "ssm": "ssm", "cognito-idp": "cognito-idp", "ec2": "ec2", "rds": "rds", "monitoring": "monitoring", "xray": "xray"}
_READ = re.compile(r"^(Get|List|Describe|Lookup|BatchGet|Query|Scan|Head)")
_RES_KEYS = (("stateMachineArn", "AWS::StepFunctions::StateMachine"), ("executionArn", "AWS::StepFunctions::Execution"),
             ("TableName", "AWS::DynamoDB::Table"), ("TopicArn", "AWS::SNS::Topic"), ("QueueUrl", "AWS::SQS::Queue"),
             ("KeyId", "AWS::KMS::Key"), ("FunctionName", "AWS::Lambda::Function"), ("SecretId", "AWS::SecretsManager::Secret"))


class _Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def derive(svc, method, path, action, body):
    """-> (eventSource, eventName, resources) or None when the call is not auditable."""
    if svc in ("s3", "cloudtrail", "rds-data") or svc.startswith(("gcp", "az")):
        return None
    name = action
    res = []
    m = re.match(r"^/guardrail/([^/]+)/version/([^/]+)/apply$", path or "")
    if m:
        name, src = "ApplyGuardrail", "bedrock"
        res.append(("AWS::Bedrock::Guardrail", m.group(1)))
    else:
        mm = re.match(r"^/model/([^/]+)/(invoke|converse)(-stream|-with-response-stream)?$", path or "")
        if mm:
            name = {"invoke": "InvokeModel", "converse": "Converse"}[mm.group(2)] + ("Stream" if mm.group(3) else "")
            src = "bedrock"
            res.append(("AWS::Bedrock::Model", mm.group(1)))
        else:
            ml = re.match(r"^/2015-03-31/functions/([^/]+)/invocations$", path or "")
            if ml:
                name, src = "Invoke", "lambda"
                res.append(("AWS::Lambda::Function", ml.group(1)))
            else:
                src = _SOURCE.get(svc)
    if not name or not src:
        return None
    try:
        doc = json.loads(body) if body else {}
    except Exception:
        doc = {}
    if isinstance(doc, dict):
        for k, rt in _RES_KEYS:
            if isinstance(doc.get(k), str):
                res.append((rt, doc[k]))
    return f"{src}.amazonaws.com", name, res


_KMS_SKIP = {"Plaintext", "CiphertextBlob", "Message", "Mac", "Signature"}   # real CloudTrail never logs payload bytes


def _request_parameters(source, body):
    """requestParameters as CloudTrail shows them; for KMS the encryptionContext is the audit-relevant part."""
    try:
        doc = json.loads(body) if body else {}
    except Exception:
        return None
    if not isinstance(doc, dict) or source != "kms.amazonaws.com":
        return None
    return {k[0].lower() + k[1:]: v for k, v in doc.items() if k not in _KMS_SKIP} or None


def record(store: list, svc, method, path, action, body, akid, user, query_params=None):
    d = derive(svc, method, path, action, body)
    if d is None:
        return None
    source, name, res = d
    if query_params:
        for k, rt in (("TopicArn", "AWS::SNS::Topic"), ("QueueUrl", "AWS::SQS::Queue")):
            if query_params.get(k):
                res.append((rt, query_params[k]))
    now = time.time()
    rn = [{"ResourceType": t, "ResourceName": n} for t, n in res]
    for old in store[-3:]:   # a front door and the router can both see one request: record it once
        if now - old["EventTime"] < 0.05 and (old["EventName"], old["AccessKeyId"], old["Resources"]) == (name, akid or "", rn):
            return None
    eid = str(uuid.uuid4())
    ro = bool(_READ.match(name))
    ev = {"EventId": eid, "EventName": name, "ReadOnly": "true" if ro else "false", "AccessKeyId": akid or "", "EventTime": now,
          "EventSource": source, "Username": user or akid or "anonymous",
          "Resources": [{"ResourceType": t, "ResourceName": n} for t, n in res]}
    ev["CloudTrailEvent"] = json.dumps({
        "eventVersion": "1.09", "eventID": eid, "eventTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "eventSource": source,
        "eventName": name, "awsRegion": _REGION, "readOnly": ro, "eventType": "AwsApiCall", "managementEvent": True,
        "userIdentity": {"type": "IAMUser", "accessKeyId": akid or "", "userName": ev["Username"], "accountId": _ACCOUNT},
        "requestID": eid, "recipientAccountId": _ACCOUNT,
        "resources": [{"type": t, "ARN": n} for t, n in res]})
    rp = _request_parameters(source, body)
    if rp is not None:
        d2 = json.loads(ev["CloudTrailEvent"])
        d2["requestParameters"] = rp
        ev["CloudTrailEvent"] = json.dumps(d2)
    store.append(ev)
    if len(store) > CAP:
        del store[: len(store) - CAP]
    return ev


def lookup(store: list, p: dict) -> dict:
    mr = p.get("MaxResults", 50)
    if not isinstance(mr, int) or not 1 <= mr <= 50:
        raise _Err("InvalidMaxResultsException", "Invalid MaxResults: must be between 1 and 50.")
    attrs = p.get("LookupAttributes") or []
    if len(attrs) > 1:
        raise _Err("InvalidLookupAttributesException", "Please specify only one LookupAttribute.")
    t0, t1 = p.get("StartTime"), p.get("EndTime")
    if t0 is not None and t1 is not None and t0 > t1:
        raise _Err("InvalidTimeRangeException", "StartTime must be earlier than EndTime.")
    key = None
    if attrs:
        k, v = attrs[0].get("AttributeKey"), attrs[0].get("AttributeValue")
        field = {"EventId": "EventId", "EventName": "EventName", "ReadOnly": "ReadOnly", "Username": "Username",
                 "EventSource": "EventSource", "AccessKeyId": "AccessKeyId", "ResourceType": None, "ResourceName": None}
        if k not in field or not v:
            raise _Err("InvalidLookupAttributesException", f"Invalid LookupAttribute: {k!r}.")
        key = (k, v)
    out = []
    for ev in reversed(store):
        if t0 is not None and ev["EventTime"] < t0:
            continue
        if t1 is not None and ev["EventTime"] > t1:
            continue
        if key:
            k, v = key
            if k == "ResourceType":
                if not any(r["ResourceType"] == v for r in ev["Resources"]):
                    continue
            elif k == "ResourceName":
                if not any(r["ResourceName"] == v for r in ev["Resources"]):
                    continue
            elif ev[k] != v:
                continue
        out.append(ev)
    start = 0
    if p.get("NextToken"):
        try:
            start = int(p["NextToken"].split(":")[1])
        except Exception:
            raise _Err("InvalidNextTokenException", "Invalid NextToken.")
    page = out[start:start + mr]
    doc = {"Events": page}
    if start + mr < len(out):
        doc["NextToken"] = f"ct:{start + mr}"
    return doc


def dispatch_lookup(store: list, body: bytes):
    try:
        p = json.loads(body or b"{}")
    except ValueError:
        p = {}
    try:
        return 200, lookup(store, p if isinstance(p, dict) else {})
    except _Err as e:
        return 400, {"__type": e.code, "Message": e.msg}
