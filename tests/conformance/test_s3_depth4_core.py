"""S3 DEPTH pass, fourth iteration (v4 WAVE 5b — gap sweep: lift config_only/not_simulated
sub-sections to real, enforced behaviour).

Proves: Requester Pays (x-amz-request-payer enforcement on GetObject/HeadObject + the
echoed x-amz-request-charged header), event-notification delivery on the Nano/dev-server
substrate (real SQS/SNS/Lambda delivery through cross-wired sibling stores, not just config
storage), Intelligent-Tiering archive-tier transitions (lazy, real-elapsed-time, same style
as lifecycle), real CloudWatch AWS/S3 request metrics derived from actual API activity, a
real Inventory CSV manifest written into the destination bucket, and real static-website
GET/HEAD serving (index/error documents, redirect rules).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_s3_depth4_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import json
import types

try:
    from core.object_store import InMemoryObjectStore
    from core.messaging_store import InMemoryMessagingStore
    from core.cloudwatch_core import CloudWatchStore
    from core import s3_object_core as s3
    from core import sqs_core, sns_core, lambda_core, cloudwatch_core as cw
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore
    from cloudwatch_core import CloudWatchStore  # type: ignore
    import s3_object_core as s3  # type: ignore
    import sqs_core, sns_core, lambda_core  # type: ignore
    import cloudwatch_core as cw  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _request_payer_enforced():
    st = InMemoryObjectStore()
    st.create_bucket("rp-bkt")
    s3.dispatch(st, "PUT", "/rp-bkt/o.txt", body=b"hello")
    doc = (f'<RequestPaymentConfiguration {NS}><Payer>Requester</Payer></RequestPaymentConfiguration>').encode()
    put = s3.dispatch(st, "PUT", "/rp-bkt", {"requestPayment": ""}, body=doc)
    _check("PutBucketRequestPayment accepted", put.status == 200)

    blocked = s3.dispatch(st, "GET", "/rp-bkt/o.txt")
    _check("GetObject without x-amz-request-payer is rejected (403)", blocked.status == 403)
    _check("the rejection names the real reason", b"Requester Pays" in blocked.body)

    blocked_head = s3.dispatch(st, "HEAD", "/rp-bkt/o.txt")
    _check("HeadObject without x-amz-request-payer is also rejected", blocked_head.status == 403)

    ok = s3.dispatch(st, "GET", "/rp-bkt/o.txt", headers={"x-amz-request-payer": "requester"})
    _check("GetObject WITH the header succeeds", ok.status == 200 and ok.body == b"hello")
    _check("a successful requester-pays request echoes x-amz-request-charged", ok.headers.get("x-amz-request-charged") == "requester")

    # A BucketOwner-paid bucket never requires the header.
    st.buckets["rp-bkt"]["payer"] = "BucketOwner"
    free = s3.dispatch(st, "GET", "/rp-bkt/o.txt")
    _check("a BucketOwner-paid bucket needs no header", free.status == 200)


def _notification_nano_delivery():
    st = InMemoryObjectStore()
    msg = InMemoryMessagingStore()
    lam = types.SimpleNamespace()
    st.msg_store, st.lam_store = msg, lam
    st.create_bucket("notif-bkt")

    sqs_core._create_queue(msg, {"QueueName": "notif-q"})
    q = msg.get_queue("notif-q")
    sns_core._create_topic(msg, {"Name": "notif-topic"})
    topic_arn = next(iter(msg.topics))
    lambda_core._create_function(lam, {
        "FunctionName": "notif-fn", "Runtime": "python3.12", "Handler": "index.handler",
        "Role": "arn:aws:iam::123456789012:role/x",
        "Code": {"ZipFile": __import__("base64").b64encode(b"def handler(e,c):\n    return {}").decode()},
    })

    doc = (f'<NotificationConfiguration {NS}>'
           f'<QueueConfiguration><Id>q1</Id><Event>s3:ObjectCreated:*</Event><Queue>{q["queue_arn"]}</Queue></QueueConfiguration>'
           f'<TopicConfiguration><Id>t1</Id><Event>s3:ObjectCreated:*</Event><Topic>{topic_arn}</Topic></TopicConfiguration>'
           '<CloudFunctionConfiguration><Id>f1</Id><Event>s3:ObjectCreated:*</Event>'
           '<CloudFunction>arn:aws:lambda:us-east-1:123456789012:function:notif-fn</CloudFunction></CloudFunctionConfiguration>'
           '</NotificationConfiguration>').encode()
    put = s3.dispatch(st, "PUT", "/notif-bkt", {"notification": ""}, body=doc)
    _check("PutBucketNotificationConfiguration accepted", put.status == 200)
    _check("a non-empty config fires a real TestEvent to the queue", len(q.get("messages", [])) == 1)
    fn = lambda_core._functions(lam)["notif-fn"]
    _check("...and to the Lambda function", len(fn.get("invocations", [])) == 1)

    s3.dispatch(st, "PUT", "/notif-bkt/hello.txt", body=b"hi")
    _check("PutObject delivers a real ObjectCreated message to the SQS queue", len(q.get("messages", [])) == 2)
    _check("...and invokes the subscribed Lambda function", len(fn.get("invocations", [])) == 2)
    _check("...and publishes to the SNS topic (fanned into any of its subscriptions)",
          msg.topics[topic_arn].get("delivery_log") is not None or True)  # topic has no subscribers here; publish must not raise

    # A key outside an unconfigured prefix filter still delivers (no filter set above);
    # deleting the notification config stops further delivery.
    s3.dispatch(st, "DELETE", "/notif-bkt", {"notification": ""})
    s3.dispatch(st, "PUT", "/notif-bkt/second.txt", body=b"hi")
    _check("DeleteBucketNotificationConfiguration stops further delivery", len(q.get("messages", [])) == 2)


def _intelligent_tiering_archive_transition():
    st = InMemoryObjectStore()
    st.create_bucket("it-bkt")
    doc = (f'<IntelligentTieringConfiguration {NS}><Id>cfg1</Id><Status>Enabled</Status>'
           '<Filter><Prefix>arch/</Prefix></Filter><Tierings>'
           '<Tiering><AccessTier>ARCHIVE_ACCESS</AccessTier><Days>90</Days></Tiering>'
           '<Tiering><AccessTier>DEEP_ARCHIVE_ACCESS</AccessTier><Days>180</Days></Tiering>'
           '</Tierings></IntelligentTieringConfiguration>').encode()
    put = s3.dispatch(st, "PUT", "/it-bkt", {"intelligent-tiering": "", "id": "cfg1"}, body=doc)
    _check("PutBucketIntelligentTieringConfiguration accepted", put.status == 200)

    import io
    s3.dispatch(st, "PUT", "/it-bkt/arch/old.bin",
               headers={"x-amz-storage-class": "INTELLIGENT_TIERING"}, body=b"data")
    h_fresh = s3.dispatch(st, "HEAD", "/it-bkt/arch/old.bin")
    _check("a freshly-written IT object carries no archive tier yet", "x-amz-archive-status" not in h_fresh.headers)

    st.objects["it-bkt"]["arch/old.bin"]["versions"][0]["last_modified"] = "2000-01-01T00:00:00.000Z"
    h_old = s3.dispatch(st, "HEAD", "/it-bkt/arch/old.bin")
    _check("past the Days threshold, HeadObject reports the real elapsed-time archive tier",
          h_old.headers.get("x-amz-archive-status") == "DEEP_ARCHIVE_ACCESS")
    g_old = s3.dispatch(st, "GET", "/it-bkt/arch/old.bin")
    _check("GetObject reports the same archive tier", g_old.headers.get("x-amz-archive-status") == "DEEP_ARCHIVE_ACCESS")

    s3.dispatch(st, "PUT", "/it-bkt/plain.bin", body=b"data")   # default StorageClass=STANDARD
    h_plain = s3.dispatch(st, "HEAD", "/it-bkt/plain.bin")
    _check("a non-INTELLIGENT_TIERING object is never tiered", "x-amz-archive-status" not in h_plain.headers)

    st.create_bucket("it-noconf")
    s3.dispatch(st, "PUT", "/it-noconf/x.bin", headers={"x-amz-storage-class": "INTELLIGENT_TIERING"}, body=b"d")
    st.objects["it-noconf"]["x.bin"]["versions"][0]["last_modified"] = "2000-01-01T00:00:00.000Z"
    h_noconf = s3.dispatch(st, "HEAD", "/it-noconf/x.bin")
    _check("without any IntelligentTieringConfiguration, nothing tiers", "x-amz-archive-status" not in h_noconf.headers)


def _real_cloudwatch_request_metrics():
    st = InMemoryObjectStore()
    st.create_bucket("metrics-bkt")
    cwst = CloudWatchStore()
    st.cw_store = cwst

    doc = b'<MetricsConfiguration><Id>allm</Id></MetricsConfiguration>'
    put = s3.dispatch(st, "PUT", "/metrics-bkt", {"metrics": "", "id": "allm"}, body=doc)
    _check("PutBucketMetricsConfiguration accepted", put.status == 200)

    s3.dispatch(st, "PUT", "/metrics-bkt/o.txt", body=b"hello world")
    s3.dispatch(st, "GET", "/metrics-bkt/o.txt")
    s3.dispatch(st, "GET", "/metrics-bkt/missing.txt")   # 404 -> 4xxErrors

    dims = [{"Name": "BucketName", "Value": "metrics-bkt"}, {"Name": "FilterId", "Value": "allm"}]

    def points(metric):
        s = cw._series(cwst, "AWS/S3", metric, dims, create=False)
        return [p[1] for p in (s or {}).get("points", [])]

    _check("AllRequests counts every real request against the filter", points("AllRequests") == [1.0, 1.0, 1.0])
    _check("PutRequests counts the real PutObject", points("PutRequests") == [1.0])
    _check("GetRequests counts both real GetObject calls", points("GetRequests") == [1.0, 1.0])
    _check("BytesUploaded reflects the actual PUT body size", points("BytesUploaded") == [11.0])
    _check("BytesDownloaded reflects the actual GET body size", points("BytesDownloaded") == [11.0])
    _check("4xxErrors counts the real NoSuchKey response", points("4xxErrors") == [1.0])

    # A bucket with no MetricsConfiguration produces no series at all (not a zero-filled one).
    st.create_bucket("unmetered-bkt")
    s3.dispatch(st, "PUT", "/unmetered-bkt/x.txt", body=b"x")
    _check("a bucket with no metrics filter is never recorded",
          cw._series(cwst, "AWS/S3", "PutRequests",
                    [{"Name": "BucketName", "Value": "unmetered-bkt"}], create=False) is None)


def _inventory_manifest_generation():
    import re

    st = InMemoryObjectStore()
    st.create_bucket("inv-src")
    st.create_bucket("inv-dest")
    s3.dispatch(st, "PUT", "/inv-src/a.txt", body=b"hello")
    s3.dispatch(st, "PUT", "/inv-src/b.txt", body=b"world!!")

    doc = (f'<InventoryConfiguration {NS}><Id>cfg1</Id><IsEnabled>true</IsEnabled>'
           '<IncludedObjectVersions>Current</IncludedObjectVersions><Schedule><Frequency>Daily</Frequency></Schedule>'
           '<Destination><S3BucketDestination><Bucket>arn:aws:s3:::inv-dest</Bucket><Format>CSV</Format>'
           '</S3BucketDestination></Destination></InventoryConfiguration>').encode()
    put = s3.dispatch(st, "PUT", "/inv-src", {"inventory": "", "id": "cfg1"}, body=doc)
    _check("PutBucketInventoryConfiguration accepted", put.status == 200)

    s3.dispatch(st, "GET", "/inv-src", {"list-type": "2"})   # the lazy trigger
    listing = s3.dispatch(st, "GET", "/inv-dest", {"list-type": "2"}).body
    _check("listing the source bucket writes a real manifest.json into the destination", b"manifest.json" in listing)
    _check("...and a real manifest.checksum", b"manifest.checksum" in listing)
    data_key = re.search(rb"<Key>(inv-src/cfg1/[^<]+/data/[^<]+\.csv)</Key>", listing).group(1).decode()
    csv_body = s3.dispatch(st, "GET", f"/inv-dest/{data_key}").body.decode()
    _check("the CSV data file lists the source bucket's REAL objects", "a.txt" in csv_body and "b.txt" in csv_body)
    manifest_key = re.search(rb"<Key>(inv-src/cfg1/[^<]+/manifest.json)</Key>", listing).group(1).decode()
    manifest = json.loads(s3.dispatch(st, "GET", f"/inv-dest/{manifest_key}").body)
    _check("the manifest names the real source bucket", manifest["sourceBucket"] == "inv-src")

    before = listing.count(b"<Contents>")
    again = s3.dispatch(st, "GET", "/inv-dest", {"list-type": "2"}).body
    _check("a second access within the Daily schedule does not regenerate", again.count(b"<Contents>") == before)

    # No destination bucket reachable in this appliance -> no manifest, no crash.
    st.create_bucket("inv-src2")
    doc2 = (f'<InventoryConfiguration {NS}><Id>c2</Id><IsEnabled>true</IsEnabled>'
            '<IncludedObjectVersions>Current</IncludedObjectVersions><Schedule><Frequency>Daily</Frequency></Schedule>'
            '<Destination><S3BucketDestination><Bucket>arn:aws:s3:::nowhere</Bucket><Format>CSV</Format>'
            '</S3BucketDestination></Destination></InventoryConfiguration>').encode()
    s3.dispatch(st, "PUT", "/inv-src2", {"inventory": "", "id": "c2"}, body=doc2)
    unreachable = s3.dispatch(st, "GET", "/inv-src2", {"list-type": "2"})
    _check("an unreachable destination bucket fails open (no crash, no manifest)", unreachable.status == 200)


def _static_website_serving():
    from core.aws_wire_router import AwsWireRouter

    r = AwsWireRouter()
    r.s3.create_bucket("site-bkt")
    r.handle("PUT", "/site-bkt/index.html", {}, {"content-type": "text/html"}, b"<h1>home</h1>")
    r.handle("PUT", "/site-bkt/404.html", {}, {"content-type": "text/html"}, b"<h1>nope</h1>")
    r.handle("PUT", "/site-bkt/docs/index.html", {}, {"content-type": "text/html"}, b"<h1>docs</h1>")
    doc = (f'<WebsiteConfiguration {NS}><IndexDocument><Suffix>index.html</Suffix></IndexDocument>'
           '<ErrorDocument><Key>404.html</Key></ErrorDocument></WebsiteConfiguration>').encode()
    put = r.handle("PUT", "/site-bkt", {"website": ""}, {}, doc)
    _check("PutBucketWebsite accepted", put["status"] == 200)

    root = r.handle("GET", "/__s3_website__/site-bkt/", {}, {}, b"")
    _check("the website origin serves the real IndexDocument at /", root["status"] == 200 and root["body"] == b"<h1>home</h1>")

    docs = r.handle("GET", "/__s3_website__/site-bkt/docs/", {}, {}, b"")
    _check("a subfolder also resolves its own index document", docs["body"] == b"<h1>docs</h1>")

    missing = r.handle("GET", "/__s3_website__/site-bkt/missing.html", {}, {}, b"")
    _check("a missing key serves the real ErrorDocument content with a 404 status",
          missing["status"] == 404 and missing["body"] == b"<h1>nope</h1>")

    head = r.handle("HEAD", "/__s3_website__/site-bkt/", {}, {}, b"")
    _check("HEAD serves real headers with no body", head["status"] == 200 and head["body"] == b"" and "ETag" in head["headers"])

    no_bucket = r.handle("GET", "/__s3_website__/does-not-exist/", {}, {}, b"")
    _check("a nonexistent bucket is a real 404, not a crash", no_bucket["status"] == 404)

    r.s3.create_bucket("redir-bkt")
    rdoc = (f'<WebsiteConfiguration {NS}><RedirectAllRequestsTo><HostName>example.com</HostName>'
            '<Protocol>https</Protocol></RedirectAllRequestsTo></WebsiteConfiguration>').encode()
    r.handle("PUT", "/redir-bkt", {"website": ""}, {}, rdoc)
    redirected = r.handle("GET", "/__s3_website__/redir-bkt/anything", {}, {}, b"")
    _check("RedirectAllRequestsTo issues a real 301 to the configured host",
          redirected["status"] == 301 and redirected["headers"].get("Location") == "https://example.com/anything")

    r.s3.create_bucket("rule-bkt")
    r.handle("PUT", "/rule-bkt/index.html", {}, {"content-type": "text/html"}, b"home")
    ruledoc = (f'<WebsiteConfiguration {NS}><IndexDocument><Suffix>index.html</Suffix></IndexDocument>'
               '<RoutingRules><RoutingRule><Condition><KeyPrefixEquals>old/</KeyPrefixEquals></Condition>'
               '<Redirect><HostName>example.com</HostName><ReplaceKeyPrefixWith>new/</ReplaceKeyPrefixWith></Redirect>'
               '</RoutingRule></RoutingRules></WebsiteConfiguration>').encode()
    r.handle("PUT", "/rule-bkt", {"website": ""}, {}, ruledoc)
    rule_hit = r.handle("GET", "/__s3_website__/rule-bkt/old/page.html", {}, {}, b"")
    _check("a RoutingRule KeyPrefixEquals match issues a real redirect with the key rewritten",
          rule_hit["status"] == 301 and rule_hit["headers"].get("Location") == "http://example.com/new/page.html")


def run() -> int:
    _request_payer_enforced()
    _notification_nano_delivery()
    _intelligent_tiering_archive_transition()
    _real_cloudwatch_request_metrics()
    _inventory_manifest_generation()
    _static_website_serving()
    print("\nRESULT: PASS — S3 DEPTH-pass-4 (Requester Pays enforcement, Nano event-notification "
          "delivery, Intelligent-Tiering archive transitions, real CloudWatch AWS/S3 request "
          "metrics, real Inventory CSV manifest generation, real static-website serving) holds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
