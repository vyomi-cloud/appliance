"""GCP Pub/Sub depth-wave-5b gap sweep: the four depth_targets in
consoles/agent-queue/gcp-pubsub.json that moved off not_simulated (see
core/capabilities/gcp/pubsub.json):

  - message transforms: a documented SUBSET of JavaScript UDFs is really parsed and
    executed at publish time (redact a field, drop a message) — core/gcp_pubsub_core.py's
    _compile_js_transform / _run_js_transform
  - topic ingestion: a topic configured with ingestionDataSourceSettings.cloudStorage
    really ingests objects from a real Cloud Storage bucket as messages (lazily, on the
    next get/publish/pull that touches the topic); any other declared source (AWS
    Kinesis, Azure Event Hubs, Kafka, CDC) is rejected — no connector exists for them
  - BigQuery / Cloud Storage subscription delivery: a cloudStorageConfig subscription
    really writes delivered messages as objects into a real GCS bucket; bigQueryConfig
    is rejected (no BigQuery core exists anywhere in Vyomi)
  - metrics: topic publish counts and subscription backlog / oldest-unacked-age are
    mirrored into the shared Cloud Monitoring store as real, queryable time series —
    core/gcp_pubsub_core.py's _sync_topic_metrics / _sync_subscription_metrics

Uses the SAME AwsWireRouter test pattern as test_gcp_logging_core.py (not the bare
gcp_pubsub_core.dispatch seam the base conformance file uses) because these features
cross into the shared GCS + Cloud Monitoring stores the router wires together.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_pubsub_depth_core.py
"""
import base64
import json

try:
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    r = AwsWireRouter()
    r.gcp_msg.set_time(1_000_000.0)

    def call(method, path, query=None, body=None, raw=None):
        b = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        out = r.handle(method, path, query or {}, {}, b)
        try:
            j = json.loads(out["body"] or b"{}")
        except Exception:
            j = out["body"]
        return out["status"], j

    P = "demo"

    # ── 1. message transforms: redact a field ──────────────────────────────────────
    redact_code = """
    function redact(message, metadata) {
      const data = JSON.parse(message.data);
      delete data.ssn;
      message.data = JSON.stringify(data);
      message.attributes = {...message.attributes, redacted: "true"};
      return message;
    }
    """
    st, b = call("PUT", f"/v1/projects/{P}/topics/udf-topic",
                 body={"messageTransforms": [{"javascriptUdf": {"functionName": "redact", "code": redact_code}}]})
    _check("create topic with a message transform", st == 200 and "messageTransforms" in b)

    st, b = call("PUT", f"/v1/projects/{P}/subscriptions/udf-sub", body={"topic": f"projects/{P}/topics/udf-topic"})
    _check("create subscription for transform topic", st == 200)

    payload = json.dumps({"ssn": "123-45-6789", "name": "bob"}).encode()
    st, b = call("POST", f"/v1/projects/{P}/topics/udf-topic:publish",
                 body={"messages": [{"data": base64.b64encode(payload).decode()}]})
    _check("publish through a transform", st == 200 and b["messageIds"])

    st, b = call("POST", f"/v1/projects/{P}/subscriptions/udf-sub:pull", body={"maxMessages": 10})
    msgs = b.get("receivedMessages", [])
    decoded = json.loads(base64.b64decode(msgs[0]["message"]["data"])) if msgs else {}
    _check("transform really redacted ssn", len(msgs) == 1 and "ssn" not in decoded and decoded.get("name") == "bob")
    _check("transform really added an attribute", msgs[0]["message"]["attributes"].get("redacted") == "true")

    # ── 1b. message transforms: drop a message ─────────────────────────────────────
    drop_code = """
    function dropTest(message, metadata) {
      const data = JSON.parse(message.data);
      if (data.test === true) {
        return null;
      }
      return message;
    }
    """
    call("PUT", f"/v1/projects/{P}/topics/drop-topic",
         body={"messageTransforms": [{"javascriptUdf": {"code": drop_code}}]})
    call("PUT", f"/v1/projects/{P}/subscriptions/drop-sub", body={"topic": f"projects/{P}/topics/drop-topic"})
    p1 = base64.b64encode(json.dumps({"test": True}).encode()).decode()
    p2 = base64.b64encode(json.dumps({"test": False}).encode()).decode()
    st, b = call("POST", f"/v1/projects/{P}/topics/drop-topic:publish", body={"messages": [{"data": p1}, {"data": p2}]})
    _check("publish with a dropping transform still 200s", st == 200 and len(b["messageIds"]) == 1)
    st, b = call("POST", f"/v1/projects/{P}/subscriptions/drop-sub:pull", body={"maxMessages": 10})
    _check("dropped message never delivered", len(b.get("receivedMessages", [])) == 1)

    # ── 1c. a transform that fails to parse is rejected at create time ──────────────
    st, b = call("PUT", f"/v1/projects/{P}/topics/bad-udf", body={"messageTransforms": [{"javascriptUdf": {"code": "function f(m) { retrun m; }"}}]})
    _check("unparsable transform rejected 400", st == 400 and b["error"]["status"] == "INVALID_ARGUMENT")

    # ── 2. topic ingestion from Cloud Storage ───────────────────────────────────────
    st, _ = call("POST", "/storage/v1/b", query={"project": P}, body={"name": "ingest-bucket"})
    _check("create the source GCS bucket", st == 200)

    st, _ = call("PUT", f"/v1/projects/{P}/topics/ingest-topic",
                 body={"ingestionDataSourceSettings": {"cloudStorage": {"bucket": "ingest-bucket"}}})
    _check("create topic with Cloud Storage ingestion", st == 200)
    st, _ = call("PUT", f"/v1/projects/{P}/subscriptions/ingest-sub", body={"topic": f"projects/{P}/topics/ingest-topic"})
    _check("create subscription before the object lands", st == 200)

    st, _ = call("POST", "/upload/storage/v1/b/ingest-bucket/o", query={"uploadType": "media", "name": "orders/a.txt"},
                 raw=b"hello from gcs")
    _check("write the object that will be ingested", st == 200)

    st, b = call("GET", f"/v1/projects/{P}/topics/ingest-topic")
    _check("reading the topic lazily syncs ingestion", st == 200)
    st, b = call("POST", f"/v1/projects/{P}/subscriptions/ingest-sub:pull", body={"maxMessages": 10})
    msgs = b.get("receivedMessages", [])
    _check("the GCS object arrived as a real message", len(msgs) == 1
           and base64.b64decode(msgs[0]["message"]["data"]) == b"hello from gcs"
           and msgs[0]["message"]["attributes"]["objectId"] == "orders/a.txt")

    # re-syncing without a new object doesn't re-deliver it
    call("GET", f"/v1/projects/{P}/topics/ingest-topic")
    st, b = call("POST", f"/v1/projects/{P}/subscriptions/ingest-sub:pull", body={"maxMessages": 10})
    _check("an already-ingested object is never re-delivered", len(b.get("receivedMessages", [])) == 0)

    # any other declared source is rejected — no connector for it anywhere in Vyomi
    st, b = call("PUT", f"/v1/projects/{P}/topics/kafka-topic",
                 body={"ingestionDataSourceSettings": {"confluentCloud": {"bootstrapServer": "x"}}})
    _check("a non-Cloud-Storage ingestion source is rejected 400", st == 400 and b["error"]["status"] == "INVALID_ARGUMENT")

    # ── 3. subscription delivery: Cloud Storage real, BigQuery honestly rejected ────
    st, _ = call("POST", "/storage/v1/b", query={"project": P}, body={"name": "delivery-bucket"})
    _check("create the delivery GCS bucket", st == 200)
    call("PUT", f"/v1/projects/{P}/topics/deliver-topic", body={})
    st, b = call("PUT", f"/v1/projects/{P}/subscriptions/deliver-sub",
                 body={"topic": f"projects/{P}/topics/deliver-topic",
                       "cloudStorageConfig": {"bucket": "delivery-bucket", "filenamePrefix": "out/"}})
    _check("create a Cloud Storage delivery subscription", st == 200 and b["cloudStorageConfig"]["bucket"] == "delivery-bucket")

    st, b = call("POST", f"/v1/projects/{P}/topics/deliver-topic:publish",
                 body={"messages": [{"data": base64.b64encode(b"row one").decode()}]})
    _check("publish to a Cloud Storage delivery subscription", st == 200)
    objs = r.gcs.bucket_objects("delivery-bucket")
    written = [k for k in objs if k.startswith("out/")]
    _check("the message landed as a REAL object in the bucket, not queued",
           len(written) == 1 and objs[written[0]]["data"] == b"row one\n")
    sub = r.gcp_msg.get_queue(f"projects/{P}/subscriptions/deliver-sub")
    _check("a Cloud Storage subscription never queues the message itself", not sub.get("messages"))

    st, b = call("PUT", f"/v1/projects/{P}/subscriptions/bq-sub",
                 body={"topic": f"projects/{P}/topics/deliver-topic", "bigQueryConfig": {"table": "p.d.t"}})
    _check("bigQueryConfig delivery is honestly rejected (no BigQuery core exists)",
           st == 400 and b["error"]["status"] == "INVALID_ARGUMENT")

    st, b = call("PUT", f"/v1/projects/{P}/subscriptions/nobucket-sub",
                 body={"topic": f"projects/{P}/topics/deliver-topic", "cloudStorageConfig": {"bucket": "does-not-exist"}})
    _check("cloudStorageConfig naming a bucket that doesn't exist is rejected 404", st == 404)

    # ── 4. metrics mirrored into Cloud Monitoring ───────────────────────────────────
    call("PUT", f"/v1/projects/{P}/topics/metric-topic", body={})
    r.gcp_msg.advance(1)
    call("PUT", f"/v1/projects/{P}/subscriptions/metric-sub", body={"topic": f"projects/{P}/topics/metric-topic"})
    r.gcp_msg.advance(1)
    call("POST", f"/v1/projects/{P}/topics/metric-topic:publish", body={"messages": [{"data": base64.b64encode(b"m").decode()}]})

    st, b = call("GET", f"/v3/projects/{P}/timeSeries", query={
        "filter": 'metric.type = "pubsub.googleapis.com/topic/send_message_operation_count" AND resource.labels.topic_id = "metric-topic"',
        "interval.startTime": "1970-01-01T00:00:00.000000Z", "interval.endTime": "2070-01-01T00:00:00.000000Z"})
    pts = b["timeSeries"][0]["points"] if st == 200 and b.get("timeSeries") else []
    _check("topic publish count is a REAL, queryable Monitoring time series",
           st == 200 and pts and int(pts[0]["value"]["int64Value"]) == 1)

    st, b = call("GET", f"/v3/projects/{P}/timeSeries", query={
        "filter": 'metric.type = "pubsub.googleapis.com/subscription/num_undelivered_messages" AND resource.labels.subscription_id = "metric-sub"',
        "interval.startTime": "1970-01-01T00:00:00.000000Z", "interval.endTime": "2070-01-01T00:00:00.000000Z"})
    pts = b["timeSeries"][0]["points"] if st == 200 and b.get("timeSeries") else []
    _check("subscription backlog is a REAL, queryable Monitoring time series (1 unacked message)",
           st == 200 and pts and int(pts[0]["value"]["int64Value"]) == 1)

    r.gcp_msg.advance(1)
    call("POST", f"/v1/projects/{P}/subscriptions/metric-sub:pull", body={"maxMessages": 10})
    st, b = call("GET", f"/v3/projects/{P}/timeSeries", query={
        "filter": 'metric.type = "pubsub.googleapis.com/subscription/oldest_unacked_message_age" AND resource.labels.subscription_id = "metric-sub"',
        "interval.startTime": "1970-01-01T00:00:00.000000Z", "interval.endTime": "2070-01-01T00:00:00.000000Z"})
    pts = b["timeSeries"][0]["points"] if st == 200 and b.get("timeSeries") else []
    _check("oldest-unacked-age metric exists and is non-negative", st == 200 and pts and float(pts[-1]["value"]["int64Value"]) >= 0)

    # a usage alert can reference the live backlog metric exactly like the real console does
    st, b = call("POST", f"/v3/projects/{P}/alertPolicies", body={
        "displayName": "backlog high", "combiner": "OR",
        "conditions": [{"displayName": "backlog", "conditionThreshold": {
            "filter": 'metric.type = "pubsub.googleapis.com/subscription/num_undelivered_messages" AND resource.labels.subscription_id = "metric-sub"',
            "comparison": "COMPARISON_GE", "thresholdValue": 0, "duration": "0s"}}],
    })
    _check("a real alert policy can be created against the live backlog metric", st == 200)

    print("\nRESULT: PASS — every Pub/Sub depth-wave-5b gap holds on a real backend")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
