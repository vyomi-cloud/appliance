"""S3 sweep S3-4 — S3 Metadata (journal + live inventory), CloudTrail S3 data events, Transfer Acceleration,
bucket-level Storage Lens. Everything goes through AwsWireRouter (the Nano / unified-ingress entry).

Run: PYTHONPATH=. python3 tests/conformance/test_s3_sweeps3d_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter

S3 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0"
CT = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/cloudtrail/aws4_request, SignedHeaders=host, Signature=0"
H = {"x-amz-account-id": "123456789012"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def s3(r, method, path, query=None, body=b"", headers=None):
    if isinstance(body, str):
        body = body.encode()
    return r.handle(method, path, query or {}, {"authorization": S3, **(headers or {})}, body)


def vy(r, path, query=None):
    out = s3(r, "GET", "/v20180820/_vyomi/" + path, query, headers=H)
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def ct(r, action, payload=None):
    out = r.handle("POST", "/", {}, {"authorization": CT, "x-amz-target": f"com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101.{action}",
                                      "content-type": "application/x-amz-json-1.1"}, json.dumps(payload or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def mk(r, name):
    assert s3(r, "PUT", f"/{name}")["status"] == 200


V2 = ("<MetadataConfiguration><JournalTableConfiguration><RecordExpiration><Expiration>{exp}</Expiration>{days}</RecordExpiration>"
      "</JournalTableConfiguration><InventoryTableConfiguration><ConfigurationState>{inv}</ConfigurationState></InventoryTableConfiguration></MetadataConfiguration>")


def accelerate():
    r = AwsWireRouter()
    mk(r, "accel-bkt")
    g = s3(r, "GET", "/accel-bkt", {"accelerate": ""})
    _check("GetBucketAccelerateConfiguration on an unset bucket is an empty config", g["status"] == 200 and b"<Status>" not in g["body"] and b"AccelerateConfiguration" in g["body"])
    _check("bad Status is MalformedXML", s3(r, "PUT", "/accel-bkt", {"accelerate": ""}, "<AccelerateConfiguration><Status>Maybe</Status></AccelerateConfiguration>")["status"] == 400)
    _check("PutBucketAccelerateConfiguration Enabled", s3(r, "PUT", "/accel-bkt", {"accelerate": ""}, "<AccelerateConfiguration><Status>Enabled</Status></AccelerateConfiguration>")["status"] == 200)
    _check("Get round-trips Enabled", b"<Status>Enabled</Status>" in s3(r, "GET", "/accel-bkt", {"accelerate": ""})["body"])
    s3(r, "PUT", "/accel-bkt/k.txt", body=b"hello")
    a = s3(r, "GET", "/k.txt", headers={"host": "accel-bkt.s3-accelerate.amazonaws.com"})
    _check("s3-accelerate Host serves the object on an Enabled bucket", a["status"] == 200 and a["body"] == b"hello")
    a2 = s3(r, "GET", "/k.txt", headers={"host": "accel-bkt.s3-accelerate.dualstack.amazonaws.com"})
    _check("dualstack accelerate Host accepted", a2["status"] == 200)
    s3(r, "PUT", "/accel-bkt", {"accelerate": ""}, "<AccelerateConfiguration><Status>Suspended</Status></AccelerateConfiguration>")
    _check("Suspended is reported", b"<Status>Suspended</Status>" in s3(r, "GET", "/accel-bkt", {"accelerate": ""})["body"])
    bad = s3(r, "GET", "/k.txt", headers={"host": "accel-bkt.s3-accelerate.amazonaws.com"})
    _check("s3-accelerate Host on a Suspended bucket -> InvalidRequest", bad["status"] == 400 and b"InvalidRequest" in bad["body"])
    mk(r, "dots.bkt.example")
    d = s3(r, "PUT", "/dots.bkt.example", {"accelerate": ""}, "<AccelerateConfiguration><Status>Enabled</Status></AccelerateConfiguration>")
    _check("bucket names with periods cannot enable acceleration", d["status"] == 400 and b"periods" in d["body"])
    _check("missing bucket -> NoSuchBucket", s3(r, "GET", "/nope-bkt-x", {"accelerate": ""})["status"] == 404)


def metadata():
    r = AwsWireRouter()
    mk(r, "meta-bkt")
    _check("no config -> MetadataConfigurationNotFound", s3(r, "GET", "/meta-bkt", {"metadataConfiguration": ""})["status"] == 404)
    _check("malformed body", s3(r, "POST", "/meta-bkt", {"metadataConfiguration": ""}, "<nope/>")["status"] == 400)
    _check("expiry Days >= 7", s3(r, "POST", "/meta-bkt", {"metadataConfiguration": ""}, V2.format(exp="ENABLED", days="<Days>3</Days>", inv="ENABLED"))["status"] == 400)
    _check("CreateBucketMetadataConfiguration", s3(r, "POST", "/meta-bkt", {"metadataConfiguration": ""}, V2.format(exp="DISABLED", days="", inv="ENABLED"))["status"] == 200)
    _check("duplicate create -> 409", s3(r, "POST", "/meta-bkt", {"metadataConfiguration": ""}, V2.format(exp="DISABLED", days="", inv="ENABLED"))["status"] == 409)
    g = s3(r, "GET", "/meta-bkt", {"metadataConfiguration": ""})
    _check("Get returns journal + inventory results", g["status"] == 200 and b"JournalTableConfigurationResult" in g["body"]
           and b"<ConfigurationState>ENABLED</ConfigurationState>" in g["body"] and b"b_meta_bkt" in g["body"] and b"<TableStatus>ACTIVE</TableStatus>" in g["body"])
    s3(r, "PUT", "/meta-bkt/a/one.txt", body=b"1")
    s3(r, "PUT", "/meta-bkt/a/two.txt", body=b"22")
    s3(r, "DELETE", "/meta-bkt/a/one.txt")
    st, j = vy(r, "bucket-metadata/meta-bkt", {"table": "journal"})
    types = [(x["key"], x["record_type"]) for x in j["rows"]]
    _check("journal records CREATE/CREATE/DELETE newest first", st == 200 and j["total"] == 3 and types[0] == ("a/one.txt", "DELETE") and ("a/two.txt", "CREATE") in types)
    seqs = [x["sequence_number"] for x in j["rows"]]
    _check("journal sequence numbers strictly increase", seqs == sorted(seqs, reverse=True) and len(set(seqs)) == 3)
    _check("journal filters by recordType", vy(r, "bucket-metadata/meta-bkt", {"recordType": "DELETE"})[1]["total"] == 1)
    _check("journal filters by prefix", vy(r, "bucket-metadata/meta-bkt", {"prefix": "a/two"})[1]["total"] == 1)
    _, inv = vy(r, "bucket-metadata/meta-bkt", {"table": "inventory"})
    _check("inventory is computed from the live store (deleted object absent)", inv["total"] == 1 and inv["rows"][0]["key"] == "a/two.txt" and inv["rows"][0]["size"] == 2)
    _check("update inventory -> DISABLED", s3(r, "PUT", "/meta-bkt", {"metadataInventoryTable": ""}, "<InventoryTableConfiguration><ConfigurationState>DISABLED</ConfigurationState></InventoryTableConfiguration>")["status"] == 200)
    _check("disabled inventory has no rows", vy(r, "bucket-metadata/meta-bkt", {"table": "inventory"})[1]["total"] == 0)
    _check("update journal expiry", s3(r, "PUT", "/meta-bkt", {"metadataJournalTable": ""}, "<JournalTableConfiguration><RecordExpiration><Expiration>ENABLED</Expiration><Days>30</Days></RecordExpiration></JournalTableConfiguration>")["status"] == 200)
    _check("expiry reflected", b"<Days>30</Days>" in s3(r, "GET", "/meta-bkt", {"metadataConfiguration": ""})["body"])
    _check("DeleteBucketMetadataConfiguration", s3(r, "DELETE", "/meta-bkt", {"metadataConfiguration": ""})["status"] == 204)
    _check("journal route reports unconfigured after delete", vy(r, "bucket-metadata/meta-bkt")[1] == {"configured": False})
    # V1
    mk(r, "meta-v1")
    arn = "arn:aws:s3tables:us-east-1:123456789012:bucket/lake"
    body = f"<MetadataTableConfiguration><S3TablesDestination><TableBucketArn>{arn}</TableBucketArn><TableName>objs</TableName></S3TablesDestination></MetadataTableConfiguration>"
    _check("V1 CreateBucketMetadataTableConfiguration", s3(r, "POST", "/meta-v1", {"metadataTable": ""}, body)["status"] == 200)
    g1 = s3(r, "GET", "/meta-v1", {"metadataTable": ""})
    _check("V1 Get returns destination", b"<TableName>objs</TableName>" in g1["body"] and b"<Status>ACTIVE</Status>" in g1["body"])
    _check("V1 config is not visible through the V2 getter", s3(r, "GET", "/meta-v1", {"metadataConfiguration": ""})["status"] == 404)
    _check("V1 bad ARN rejected", s3(r, "POST", "/meta-v1", {"metadataTable": ""}, body.replace(arn, "nope"))["status"] in (400, 409))


def trails():
    r = AwsWireRouter()
    mk(r, "logs-bkt")
    mk(r, "data-bkt")
    mk(r, "other-bkt")
    _check("bad trail name", ct(r, "CreateTrail", {"Name": "a", "S3BucketName": "logs-bkt"})[0] == 400)
    _check("missing destination bucket", ct(r, "CreateTrail", {"Name": "trail1", "S3BucketName": "ghost-bkt"})[1]["__type"] == "S3BucketDoesNotExistException")
    st, c = ct(r, "CreateTrail", {"Name": "trail1", "S3BucketName": "logs-bkt"})
    _check("CreateTrail", st == 200 and c["TrailARN"] == "arn:aws:cloudtrail:us-east-1:123456789012:trail/trail1")
    _check("duplicate trail", ct(r, "CreateTrail", {"Name": "trail1", "S3BucketName": "logs-bkt"})[1]["__type"] == "TrailAlreadyExistsException")
    _check("DescribeTrails lists it", [t["Name"] for t in ct(r, "DescribeTrails")[1]["trailList"]] == ["trail1"])
    _check("GetTrailStatus IsLogging false", ct(r, "GetTrailStatus", {"Name": "trail1"})[1]["IsLogging"] is False)
    _check("invalid ReadWriteType", ct(r, "PutEventSelectors", {"TrailName": "trail1", "EventSelectors": [{"ReadWriteType": "Some"}]})[1]["__type"] == "InvalidEventSelectorsException")
    sel = [{"ReadWriteType": "All", "IncludeManagementEvents": False, "DataResources": [{"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::data-bkt/"]}]}]
    _check("PutEventSelectors", ct(r, "PutEventSelectors", {"TrailName": "trail1", "EventSelectors": sel})[0] == 200)
    _check("GetEventSelectors round-trips", ct(r, "GetEventSelectors", {"TrailName": "trail1"})[1]["EventSelectors"] == sel)
    s3(r, "PUT", "/data-bkt/before.txt", body=b"x")                    # trail not logging yet
    _check("not logging -> nothing recorded", vy(r, "bucket-trail/data-bkt")[1]["total"] == 0)
    ct(r, "StartLogging", {"Name": "trail1"})
    _check("GetTrailStatus IsLogging true", ct(r, "GetTrailStatus", {"Name": "trail1"})[1]["IsLogging"] is True)
    s3(r, "PUT", "/data-bkt/p/obj.txt", body=b"hello")
    s3(r, "GET", "/data-bkt/p/obj.txt")
    s3(r, "HEAD", "/data-bkt/p/obj.txt")
    s3(r, "GET", "/data-bkt/p/missing.txt")
    s3(r, "DELETE", "/data-bkt/p/obj.txt")
    s3(r, "PUT", "/other-bkt/o.txt", body=b"nope")
    st, v = vy(r, "bucket-trail/data-bkt")
    names = [e["eventName"] for e in reversed(v["events"])]
    _check("PutObject/GetObject/HeadObject/GetObject/DeleteObject recorded in order", names == ["PutObject", "GetObject", "HeadObject", "GetObject", "DeleteObject"])
    _check("bucket scoping: other bucket not recorded", vy(r, "bucket-trail/other-bkt")[1]["total"] == 0)
    e0 = v["events"][-1]
    _check("event has the CloudTrail data-event shape", e0["eventSource"] == "s3.amazonaws.com" and e0["eventCategory"] == "Data" and e0["managementEvent"] is False
           and e0["resources"][0] == {"type": "AWS::S3::Object", "ARN": "arn:aws:s3:::data-bkt/p/obj.txt"} and e0["readOnly"] is False)
    miss = [e for e in v["events"] if e["eventName"] == "GetObject" and e["requestParameters"]["key"] == "p/missing.txt"][0]
    _check("failed GET carries errorCode", miss["errorCode"] == "NoSuchKey")
    _check("trail listed for the bucket", [t["name"] for t in v["trails"]] == ["trail1"] and v["trails"][0]["logging"])
    ct(r, "PutEventSelectors", {"TrailName": "trail1", "EventSelectors": [dict(sel[0], ReadWriteType="ReadOnly")]})
    s3(r, "PUT", "/data-bkt/ro.txt", body=b"w")
    s3(r, "GET", "/data-bkt/ro.txt")
    _, v2 = vy(r, "bucket-trail/data-bkt")
    _check("ReadOnly selector records reads, not writes", v2["total"] == v["total"] + 1 and v2["events"][0]["eventName"] == "GetObject")
    adv = [{"Name": "s3", "FieldSelectors": [{"Field": "eventCategory", "Equals": ["Data"]}, {"Field": "resources.type", "Equals": ["AWS::S3::Object"]},
                                              {"Field": "resources.ARN", "StartsWith": ["arn:aws:s3:::other-bkt/"]}, {"Field": "eventName", "Equals": ["PutObject"]}]}]
    _check("advanced selectors need eventCategory", ct(r, "PutEventSelectors", {"TrailName": "trail1", "AdvancedEventSelectors": [{"FieldSelectors": [{"Field": "eventName", "Equals": ["x"]}]}]})[0] == 400)
    _check("PutEventSelectors advanced", ct(r, "PutEventSelectors", {"TrailName": "trail1", "AdvancedEventSelectors": adv})[0] == 200)
    s3(r, "PUT", "/other-bkt/adv.txt", body=b"a")
    s3(r, "GET", "/other-bkt/adv.txt")
    _, ov = vy(r, "bucket-trail/other-bkt")
    _check("advanced selector (PutObject on other-bkt only)", [e["eventName"] for e in ov["events"]] == ["PutObject"])
    ct(r, "StopLogging", {"Name": "trail1"})
    s3(r, "PUT", "/other-bkt/after.txt", body=b"a")
    _check("StopLogging halts recording", vy(r, "bucket-trail/other-bkt")[1]["total"] == 1)
    _check("filter by eventName", vy(r, "bucket-trail/data-bkt", {"eventName": "DeleteObject"})[1]["total"] == 1)
    _check("DeleteTrail", ct(r, "DeleteTrail", {"Name": "trail1"})[0] == 200 and ct(r, "GetTrail", {"Name": "trail1"})[1]["__type"] == "TrailNotFoundException")
    _check("unknown op", ct(r, "LookupEventsX")[1]["__type"] == "UnknownOperationException")


def lens():
    r = AwsWireRouter()
    mk(r, "lens-bkt")
    s3(r, "PUT", "/lens-bkt", {"versioning": ""}, "<VersioningConfiguration><Status>Enabled</Status></VersioningConfiguration>")
    s3(r, "PUT", "/lens-bkt/logs/a.txt", body=b"12345")
    s3(r, "PUT", "/lens-bkt/logs/a.txt", body=b"1234567890")
    s3(r, "PUT", "/lens-bkt/img/b.bin", body=b"x" * 100)
    s3(r, "GET", "/lens-bkt/logs/a.txt")
    s3(r, "GET", "/lens-bkt/logs/nope")
    s3(r, "DELETE", "/lens-bkt/img/b.bin")
    st, d = vy(r, "bucket-lens/lens-bkt")
    sto, act = d["storage"], d["activity"]
    _check("current bytes/objects from the real store", st == 200 and sto["currentBytes"] == 10 and sto["currentObjects"] == 1)
    _check("noncurrent version counted", sto["noncurrentBytes"] == 105 and sto["noncurrentObjects"] == 2 and sto["deleteMarkers"] == 1)
    _check("total and current-version %", sto["totalBytes"] == 115 and sto["currentVersionPct"] == round(100 * 10 / 115, 2))
    _check("storage class breakdown", d["byStorageClass"][0]["storageClass"] == "STANDARD" and d["byStorageClass"][0]["bytes"] == 115)
    _check("top prefixes", [p["prefix"] for p in d["topPrefixes"]] == ["logs/"])
    _check("request counters", act["PutRequests"] == 3 and act["GetRequests"] == 2 and act["DeleteRequests"] == 1 and act["4xxErrors"] == 1)
    _check("bytes uploaded / downloaded", act["BytesUploaded"] >= 115 and act["BytesDownloaded"] == 10)
    _check("daily series present", len(act["daily"]) == 1 and act["daily"][0]["GetRequests"] == 2)
    _check("unknown bucket 404", vy(r, "bucket-lens/ghost-bkt")[0] == 404)


if __name__ == "__main__":
    for fn in (accelerate, metadata, trails, lens):
        print(fn.__name__)
        fn()
    print("S3-4 core: all passed")
