"""v4 C0e — the offline appliance serves AWS SQS (JSON + Query), SNS, EventBridge and
EventBridge Scheduler through the shared conformance cores over ONE messaging store shared
with the classic console REST, durably — so an EventBridge rule's SQS / SNS / Lambda targets
and an SNS topic's SQS subscriptions really deliver.

Boots the real server.py in-process (FastAPI TestClient) against a throwaway state file,
like tests/test_c0_unified_engine.py.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="vyomi-c0e-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_TEST_DIR / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_TEST_DIR / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_VAULT_URL", "http://127.0.0.1:1")
os.environ.setdefault("CLOUDLEARN_ELASTICMQ_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

SIG = ("AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/{svc}/aws4_request, "
       "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64)
S3H = {"Authorization": SIG.format(svc="s3")}
NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _u(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _sqs(client, op, body, prefix=""):
    r = client.post(prefix + "/", content=json.dumps(body), headers={
        "Authorization": SIG.format(svc="sqs"), "Content-Type": "application/x-amz-json-1.0",
        "X-Amz-Target": f"AmazonSQS.{op}"})
    return r


def _ev(client, op, body, prefix=""):
    return client.post(prefix + "/", content=json.dumps(body), headers={
        "Authorization": SIG.format(svc="events"), "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": f"AWSEvents.{op}"})


def _sns(client, action, params, prefix=""):
    return client.post(prefix + "/", data={"Action": action, **params},
                       headers={"Authorization": SIG.format(svc="sns")})


def _queue(client, name, attrs=None):
    url = _sqs(client, "CreateQueue", {"QueueName": name, **({"Attributes": attrs} if attrs else {})}).json()["QueueUrl"]
    arn = _sqs(client, "GetQueueAttributes", {"QueueUrl": url, "AttributeNames": ["QueueArn"]}).json()["Attributes"]["QueueArn"]
    return url, arn


def _recv(client, url, n=10):
    return _sqs(client, "ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": n}).json().get("Messages") or []


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


def _first_route(path: str, method: str):
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": method, "root_path": "", "query_string": b"", "headers": []}
    for r in server.app.routes:
        m, _ = r.matches(scope)
        if m == Match.FULL:
            return r
    return None


def test_route_precedence(client):
    mod = "routes.aws_messaging_unified"
    for p, m in (("/api/sqs/queues", "GET"), ("/api/sqs/queues", "POST"), ("/api/sqs/queues/q", "GET"),
                 ("/api/sqs/queues/q/messages", "POST"), ("/api/sqs/queues/q/receive", "POST"),
                 ("/api/eventbridge/rules", "GET"), ("/api/eventbridge/rules/r", "PUT"),
                 ("/api/eventbridge/rules/r/targets", "PUT"), ("/api/aws/extras/eventbridge/rules", "GET"),
                 ("/api/aws/extras/eventbridge/rules", "POST"), ("/api/aws/extras/eventbridge/event-buses", "GET"),
                 ("/api/aws/extras/eventbridge/rules/x", "DELETE"), ("/schedules", "GET"), ("/schedules/s", "POST"),
                 ("/schedule-groups/g", "POST")):
        assert _first_route(p, m).endpoint.__module__ == mod, (p, m)
    # the rest of the extras stubs stay on the generic backend
    assert _first_route("/api/aws/extras/eventbridge/connections", "GET").endpoint.__module__ == "routes.aws_extras"
    # native wire: POST / is the root dispatcher, which hands sqs / sns / events to the cores
    assert _first_route("/", "POST").endpoint.__name__ == "aws_query_root"


def test_sqs_json_query_and_queue_url_share_one_engine(client):
    name = _u("c0e-q")
    url, arn = _queue(client, name)
    assert url == f"http://testserver/123456789012/{name}"     # an endpoint the SDK can POST back to
    assert arn == f"arn:aws:sqs:us-east-1:123456789012:{name}"
    assert _sqs(client, "SendMessage", {"QueueUrl": url, "MessageBody": "json"}).status_code == 200
    # Query protocol, POSTed to the queue URL itself (Java v1 / .NET style), via /_wire too
    r = client.post(f"/_wire/123456789012/{name}", data={"Action": "SendMessage", "MessageBody": "query"},
                    headers={"Authorization": SIG.format(svc="sqs")})
    assert r.status_code == 200 and "<SendMessageResponse" in r.text
    # unsigned Query on GET /?Action=
    r = client.get("/", params={"Action": "ReceiveMessage", "QueueUrl": url, "MaxNumberOfMessages": "10"})
    root = ET.fromstring(r.text)
    assert sorted(e.text for e in root.iter("{http://queue.amazonaws.com/doc/2012-11-05/}Body")) == ["json", "query"]
    # error shapes: JSON __type + the query-compatible header; Query <ErrorResponse>
    nf = _sqs(client, "GetQueueUrl", {"QueueName": "nope-" + uuid.uuid4().hex[:6]})
    assert nf.status_code == 400 and nf.json()["__type"].endswith("QueueDoesNotExist")
    assert nf.headers["x-amzn-query-error"] == "AWS.SimpleQueueService.NonExistentQueue;Sender"
    r = client.post("/", data={"Action": "GetQueueUrl", "QueueName": "nope"}, headers={"Authorization": SIG.format(svc="sqs")})
    assert r.status_code == 400 and "AWS.SimpleQueueService.NonExistentQueue" in r.text
    # a pre-v4 style queue URL still resolves
    assert _sqs(client, "GetQueueAttributes", {"QueueUrl": f"http://127.0.0.1:9000/api/sqs/queues/{name}"}).status_code == 200


def test_sqs_native_and_console_share_state(client):
    # console → native
    name = _u("c0e-console")
    c = client.post("/api/sqs/queues", json={"queue_name": name, "visibility_timeout": 7, "tags": {"t": "1"}}).json()
    assert c["queue_name"] == name and c["attributes"]["VisibilityTimeout"] == "7" and c["queue_url"].endswith(f"/{name}")
    assert client.post("/api/sqs/queues", json={"queue_name": name}).status_code == 409
    sent = client.post(f"/api/sqs/queues/{name}/send", json={"message_body": "from-console", "message_attributes": {"k": "v"}}).json()
    assert sent["message"]["body"] == "from-console"
    got = _sqs(client, "ReceiveMessage", {"QueueUrl": name, "MessageAttributeNames": ["All"]}).json()["Messages"]
    assert got[0]["Body"] == "from-console" and got[0]["MessageAttributes"]["k"]["StringValue"] == "v"
    assert _sqs(client, "ListQueueTags", {"QueueUrl": name}).json()["Tags"] == {"t": "1"}
    # native → console
    url, _ = _queue(client, _u("c0e-native"))
    qn = url.rsplit("/", 1)[-1]
    _sqs(client, "SendMessage", {"QueueUrl": url, "MessageBody": "from-sdk"})
    rows = {q["queue_name"]: q for q in client.get("/api/sqs/queues").json()["queues"]}
    assert rows[qn]["message_count"] == 1 and rows[qn]["queue_type"] == "standard"
    rec = client.post(f"/api/sqs/queues/{qn}/receive", json={"max_number_of_messages": 5}).json()
    assert rec["messages"][0]["body"] == "from-sdk" and rec["messages"][0]["in_flight"]
    rh = rec["messages"][0]["receipt_handle"]
    assert client.delete(f"/api/sqs/queues/{qn}/messages/{rh}").json()["deleted"]
    assert _sqs(client, "GetQueueAttributes", {"QueueUrl": url}).json()["Attributes"]["ApproximateNumberOfMessagesNotVisible"] == "0"
    assert client.put(f"/api/sqs/queues/{qn}", json={"delay_seconds": 3}).json()["delay_seconds"] == 3
    assert _sqs(client, "GetQueueAttributes", {"QueueUrl": url}).json()["Attributes"]["DelaySeconds"] == "3"
    assert client.delete(f"/api/sqs/queues/{qn}").json()["deleted"]
    assert _sqs(client, "GetQueueUrl", {"QueueName": qn}).status_code == 400


def test_eventbridge_delivers_to_sqs_sns_and_lambda_targets(client):
    q_url, q_arn = _queue(client, _u("c0e-evq"))
    rule = _u("c0e-rule")
    r = _ev(client, "PutRule", {"Name": rule, "EventPattern": json.dumps({"source": ["c0e.test"]})}, prefix="/_wire")
    assert r.status_code == 200 and ":123456789012:rule/" in r.json()["RuleArn"]    # not 000000000000
    assert _ev(client, "PutTargets", {"Rule": rule, "Targets": [{"Id": "q", "Arn": q_arn}]}).json()["FailedEntryCount"] == 0
    # SNS topic target → its SQS subscription
    s_url, s_arn = _queue(client, _u("c0e-subq"))
    topic = ET.fromstring(_sns(client, "CreateTopic", {"Name": _u("c0e-topic")}).text).find(".//{*}TopicArn").text
    assert _sns(client, "Subscribe", {"TopicArn": topic, "Protocol": "sqs", "Endpoint": s_arn}).status_code == 200
    _ev(client, "PutTargets", {"Rule": rule, "Targets": [{"Id": "t", "Arn": topic}]})
    # Lambda target → the appliance's functions (since C0f: the lambda_core store, real runtime)
    fn = _u("c0e-fn")
    assert client.post("/2015-03-31/functions", json={"FunctionName": fn, "Runtime": "python3.12",
                                                     "Handler": "lambda_function.lambda_handler",
                                                     "Role": "arn:aws:iam::123456789012:role/r"}).status_code == 201
    _ev(client, "PutTargets", {"Rule": rule, "Targets": [{"Id": "l", "Arn": f"arn:aws:lambda:us-east-1:123456789012:function:{fn}"}]})
    before = len((server._lambda_find_function(fn) or {}).get("invocations") or [])
    out = _ev(client, "PutEvents", {"Entries": [{"Source": "c0e.test", "DetailType": "t", "Detail": json.dumps({"n": 1})},
                                                {"Source": "other", "DetailType": "t", "Detail": "{}"}]}).json()
    assert out["FailedEntryCount"] == 0 and len(out["Entries"]) == 2
    msgs = _recv(client, q_url)
    assert len(msgs) == 1 and json.loads(msgs[0]["Body"])["detail"] == {"n": 1}
    sub = _recv(client, s_url)
    assert len(sub) == 1 and json.loads(json.loads(sub[0]["Body"])["Message"])["source"] == "c0e.test"
    import time as _t
    for _ in range(50):   # an EventBridge target is an async (Event) invoke
        inv = (server._lambda_find_function(fn) or {}).get("invocations") or []
        if len(inv) >= before + 1:
            break
        _t.sleep(0.1)
    assert len(inv) == before + 1


def test_sns_fanout_into_sqs_on_the_shared_store(client):
    url, arn = _queue(client, _u("c0e-fan"))
    topic = ET.fromstring(_sns(client, "CreateTopic", {"Name": _u("c0e-fan-t")}).text).find(".//{*}TopicArn").text
    _sns(client, "Subscribe", {"TopicArn": topic, "Protocol": "sqs", "Endpoint": arn, "Attributes.entry.1.key": "RawMessageDelivery",
                               "Attributes.entry.1.value": "true"})
    assert _sns(client, "Publish", {"TopicArn": topic, "Message": "raw!"}).status_code == 200
    assert [m["Body"] for m in _recv(client, url)] == ["raw!"]
    # the classic SNS console REST sees the same topic + subscription
    topics = {t["arn"]: t for t in client.get("/api/aws/sns/topics").json()["topics"]}
    assert topics[topic]["subscriptions"] == 1


def test_s3_notifications_reach_sqs_sns_and_eventbridge(client):
    b = _u("c0e-notif")
    q_url, q_arn = _queue(client, _u("c0e-s3q"))
    e_url, e_arn = _queue(client, _u("c0e-s3ev"))
    rule = _u("c0e-s3rule")
    _ev(client, "PutRule", {"Name": rule, "EventPattern": json.dumps({"source": ["aws.s3"], "detail": {"bucket": {"name": [b]}}})})
    _ev(client, "PutTargets", {"Rule": rule, "Targets": [{"Id": "q", "Arn": e_arn}]})
    client.put(f"/{b}", headers=S3H)
    cfg = (f"<NotificationConfiguration {NS}><QueueConfiguration><Id>q</Id><Queue>{q_arn}</Queue>"
           "<Event>s3:ObjectCreated:*</Event></QueueConfiguration><EventBridgeConfiguration/></NotificationConfiguration>")
    assert client.put(f"/{b}?notification", headers=S3H, content=cfg).status_code == 200
    client.put(f"/{b}/obj.txt", headers=S3H, content=b"x")
    recs = [json.loads(m["Body"]).get("Records", [{}])[0] for m in _recv(client, q_url)]
    assert any(r.get("s3", {}).get("object", {}).get("key") == "obj.txt" for r in recs), recs
    evs = [json.loads(m["Body"]) for m in _recv(client, e_url)]
    assert len(evs) == 1, evs                       # the s3:TestEvent never goes to EventBridge
    ev = evs[0]
    assert ev["source"] == "aws.s3" and ev["detail-type"] == "Object Created" and ev["detail"]["object"]["key"] == "obj.txt"


def test_eventbridge_native_and_console_share_state(client):
    # classic console page (extras) → native
    name = _u("c0e-console-rule")
    q_url, q_arn = _queue(client, _u("c0e-cq"))
    row = client.post("/api/aws/extras/eventbridge/rules", json={"name": name, "target_arn": q_arn}).json()
    assert row["state"] == "ENABLED" and row["target_count"] == 1 and row["event_bus_name"] == "default"
    assert _ev(client, "ListTargetsByRule", {"Rule": name}).json()["Targets"][0]["Arn"] == q_arn
    bare = _u("c0e-bare")
    assert client.post("/api/aws/extras/eventbridge/rules", json={"name": bare}).json()["target_count"] == 0
    # native → classic REST + console pages
    nat = _u("c0e-native-rule")
    _ev(client, "PutRule", {"Name": nat, "EventPattern": json.dumps({"source": ["x"]}), "State": "DISABLED"})
    assert client.get(f"/api/eventbridge/rules/{nat}").json()["State"] == "DISABLED"
    rows = {r["name"]: r for r in client.get("/api/aws/extras/eventbridge/rules").json()["items"]}
    assert rows[nat]["state"] == "DISABLED" and rows[nat]["rule_type"] == "EventPattern"
    bus = _u("c0e-bus")
    _ev(client, "CreateEventBus", {"Name": bus})
    buses = {b["name"]: b for b in client.get("/api/aws/extras/eventbridge/event-buses").json()["items"]}
    assert buses[bus]["type"] == "Custom" and buses["default"]["type"] == "AWS"
    # the pre-v4 REST (core/nats_routes shapes) on the same rules
    rest = _u("c0e-rest")
    put = client.put(f"/api/eventbridge/rules/{rest}", json={"EventPattern": {"source": ["rest"]}}).json()
    assert put["Arn"].endswith(f":rule/{rest}") and put["State"] == "ENABLED"
    client.put(f"/api/eventbridge/rules/{rest}/targets", json={"Targets": [{"Id": "q", "Arn": q_arn}]})
    assert client.get(f"/api/eventbridge/rules/{rest}/targets").json()["Targets"][0]["Arn"] == q_arn
    _ev(client, "PutEvents", {"Entries": [{"Source": "rest", "DetailType": "t", "Detail": "{}"}]})
    assert json.loads(_recv(client, q_url)[0]["Body"])["source"] == "rest"
    assert client.delete(f"/api/eventbridge/rules/{rest}").json()["deleted"]
    assert _ev(client, "DescribeRule", {"Name": rest}).status_code == 400
    assert client.delete(f"/api/aws/extras/eventbridge/rules/{name}").json()["deleted"]
    assert name not in {r["name"] for r in client.get("/api/aws/extras/eventbridge/rules").json()["items"]}
    # archives page
    arch = _u("c0e-arch")
    assert client.post("/api/aws/extras/eventbridge/archives", json={"name": arch, "event_source": "default"}).json()["name"] == arch
    assert _ev(client, "DescribeArchive", {"ArchiveName": arch}).status_code == 200


def test_scheduler_is_routed_and_delivers(client):
    q_url, q_arn = _queue(client, _u("c0e-schq"))
    name = _u("c0e-sched")
    h = {"Authorization": SIG.format(svc="scheduler"), "Content-Type": "application/json"}
    r = client.post(f"/_wire/schedules/{name}", headers=h, content=json.dumps({
        "ScheduleExpression": "rate(1 minute)", "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {"Arn": q_arn, "RoleArn": "arn:aws:iam::123456789012:role/r", "Input": json.dumps({"tick": 1})}}))
    assert r.status_code == 200 and r.json()["ScheduleArn"].endswith(f"/default/{name}")
    from core import appliance_stores as aps
    sched = aps.scheduler_store().schedules[f"default/{name}"]
    json.dumps(sched)                                         # JSON-safe: the kernel state persists it
    sched["next_run_dt"] = 1.0                                # due
    assert name in [s["Name"] for s in client.get("/schedules", headers=h).json()["Schedules"]]
    assert [json.loads(m["Body"]) for m in _recv(client, q_url)] == [{"tick": 1}]
    # an S3 bucket called "schedules" is still S3 (signed for s3)
    assert client.put("/schedules", headers=S3H).status_code == 200


def test_state_is_durable_in_the_kernel_store(client):
    url, arn = _queue(client, _u("c0e-dur"))
    _sqs(client, "SendMessage", {"QueueUrl": url, "MessageBody": "durable"})
    rule = _u("c0e-dur-rule")
    _ev(client, "PutRule", {"Name": rule, "EventPattern": json.dumps({"source": ["d"]})})
    _ev(client, "PutTargets", {"Rule": rule, "Targets": [{"Id": "q", "Arn": arn}]})
    topic = ET.fromstring(_sns(client, "CreateTopic", {"Name": _u("c0e-dur-t")}).text).find(".//{*}TopicArn").text
    from core.vyomi_platform import SQLiteStateStore
    state = SQLiteStateStore(Path(os.environ["CLOUDLEARN_STATE_FILE"])).load_state(dict)
    q = rules = topics = None
    for sp in (state.get("spaces") or {}).get("spaces", {}).values():
        ss = sp.get("service_states") or {}
        q = q or ((ss.get("sqs") or {}).get("queues") or {}).get(url.rsplit("/", 1)[-1])
        rules = rules or (ss.get("eventbridge") or {}).get("rules")
        topics = topics or (ss.get("sns") or {}).get("topics")
    assert q and [m["body"] for m in q["messages"]] == ["durable"]
    assert rules and rules[f"default|{rule}"]["targets"]["q"]["Arn"] == arn
    assert topics and topic in topics


def test_upgrade_adopts_pre_v4_queues_and_rules_once(client):
    """A pre-v4 queue record (+ messages) and a classic-console EventBridge rule row in the
    space's state are adopted on first use; afterwards a deleted rule is not resurrected."""
    from core import app_context as ctx
    from core import wire_ingress
    st = wire_ingress.appliance_router().msg
    st.adopt()
    name = _u("legacy-q")
    ctx.sqs_state.setdefault("queues", {})[name] = {
        "queue_name": name, "queue_url": f"http://127.0.0.1:9000/api/sqs/queues/{name}",
        "queue_arn": f"arn:aws:sqs:us-east-1:123456789012:{name}", "fifo_queue": False, "visibility_timeout": 30,
        "redrive_policy": {}, "tags": {}, "attributes": {}, "created": "2026-01-01T00:00:00.000Z",
        "messages": [{"message_id": "msg-old", "body": "pre-v4", "sent_at": "2026-10-29T00:00:00.000Z",
                      "visible_at": "2026-10-29T00:00:00.000Z", "receive_count": 0, "in_flight": False, "deleted": False}]}
    rule = _u("legacy-rule")
    from core.appliance_stores import _proxy
    extras = _proxy("aws_extras", dict, None)._target()
    extras.setdefault("eventbridge/rules", {"items": {}, "seeded": True})["items"][rule] = {
        "name": rule, "event_bus_name": "default", "rule_type": "EventPattern", "state": "ENABLED",
        "target_arn": f"arn:aws:sqs:us-east-1:123456789012:{name}", "created": "2026-01-01T00:00:00Z"}
    # pre-v4 seed rows are demo data, never adopted
    extras["eventbridge/rules"]["items"]["ec2-state-changes"] = {"name": "ec2-state-changes", "state": "ENABLED"}
    eb = st._eb()
    eb["meta"].pop("adopted", None)                     # as on a space that never ran v4
    st._adopted.clear()
    got = _sqs(client, "ReceiveMessage", {"QueueUrl": f"http://127.0.0.1:9000/api/sqs/queues/{name}"}).json()["Messages"]
    assert got[0]["Body"] == "pre-v4"
    assert _ev(client, "ListTargetsByRule", {"Rule": rule}).json()["Targets"][0]["Arn"].endswith(f":{name}")
    assert _ev(client, "DescribeRule", {"Name": "ec2-state-changes"}).status_code == 400
    # once per space: delete it, adopt again → not resurrected
    client.delete(f"/api/aws/extras/eventbridge/rules/{rule}")
    st._adopted.clear()
    st.adopt()
    assert _ev(client, "DescribeRule", {"Name": rule}).status_code == 400


def test_legacy_opt_out_restores_the_pre_v4_handlers(monkeypatch):
    from core import wire_ingress
    from routes import aws_messaging_unified as amu
    monkeypatch.setenv("VYOMI_UNIFIED_INGRESS_SERVICES", "s3,dynamodb,gcs")
    for svc in ("sqs", "sns", "events", "scheduler"):
        assert not wire_ingress.is_unified(svc)
    from fastapi import FastAPI
    app = FastAPI()
    amu.register(app)
    assert not [r for r in app.routes if getattr(r, "endpoint", None) and r.endpoint.__module__ == amu.__name__]
    from core import nats_routes
    app2, disp = FastAPI(), {}
    nats_routes.register(app2, aws_dispatchers=disp)
    assert disp["AWSEvents"] is nats_routes._aws_eventbridge_dispatch
    assert ("/api/eventbridge/rules", "core.nats_routes") in {(r.path, r.endpoint.__module__) for r in app2.routes
                                                              if getattr(r, "endpoint", None)}
    from routes import aws_sns
    assert aws_sns._store() is aws_sns.STORE
    monkeypatch.setenv("VYOMI_LEGACY_WIRE", "1")
    monkeypatch.delenv("VYOMI_UNIFIED_INGRESS_SERVICES")
    assert not wire_ingress.is_unified("sqs") and not wire_ingress.is_unified("events")
    monkeypatch.delenv("VYOMI_LEGACY_WIRE")
    app3 = FastAPI()
    amu.register(app3)
    paths = {r.path for r in app3.routes}
    assert {"/api/sqs/queues", "/api/eventbridge/rules", "/schedules"} <= paths
