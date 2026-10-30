"""v4 C0 — behaviours ported from the retired offline handlers into the shared cores.

When the offline appliance switched its native S3 / GCS / DynamoDB wire from the
legacy handlers (routes/aws_s3.py, the GCS provider routes, DynamoDB Local) to the
shared conformance cores, every legacy behaviour the cores lacked was ported into
them. This suite pins each one, on the in-memory substrate AND the file-backed
(sqlite) substrate — the latter also proves the cores call `store.persist()` after
every mutation (bucket config included), so a fresh instance sees it.

Pure stdlib + cores → runs on host CPython and Pyodide.
Run:  PYTHONPATH=. python3 tests/conformance/test_c0_legacy_parity_core.py
"""
import json
import re

from core import dynamodb_core as ddb
from core import gcp_storage_core as gcs
from core import s3_object_core as s3
from core.nosql_store import InMemoryNoSqlStore
from core.object_store import InMemoryObjectStore
from core.persistent_store import PersistentNoSqlStore, PersistentObjectStore, SqliteStateBackend

NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'
T = "DynamoDB_20120810."


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


class _Recorder(InMemoryObjectStore):
    def __init__(self):
        super().__init__()
        self.events, self.persists = [], 0

    def emit_event(self, bucket, key, event_name, version=None, source=""):
        self.events.append((event_name, key))

    def persist(self):
        self.persists += 1


def s3_parity(store, fresh):
    c = lambda m, p, q=None, h=None, b=b"": s3.dispatch(store, m, p, q or {}, h or {}, b)
    # bucket create: validation, 409, legacy-shaped metadata
    _check("s3 invalid bucket name → 400", c("PUT", "/Bad_Name").status == 400)
    _check("s3 create bucket", c("PUT", "/par-bkt").status == 200)
    _check("s3 re-create → 409 BucketAlreadyOwnedByYou",
           c("PUT", "/par-bkt").status == 409 and b"BucketAlreadyOwnedByYou" in c("PUT", "/par-bkt").body)
    meta = store.buckets["par-bkt"]
    _check("s3 bucket meta has created/arn/notifications",
           meta.get("created") and meta.get("arn") == "arn:aws:s3:::par-bkt" and "notifications" in meta)
    # notifications round-trip
    notif = (f'<NotificationConfiguration {NS}><QueueConfiguration><Id>q1</Id><Queue>arn:aws:sqs:us-east-1:1:q</Queue>'
             '<Event>s3:ObjectCreated:*</Event><Filter><S3Key><FilterRule><Name>prefix</Name><Value>in/</Value>'
             '</FilterRule></S3Key></Filter></QueueConfiguration></NotificationConfiguration>').encode()
    _check("s3 PUT ?notification → 200", c("PUT", "/par-bkt", {"notification": ""}, {}, notif).status == 200)
    g = c("GET", "/par-bkt", {"notification": ""}).body.decode()
    _check("s3 GET ?notification round-trips queue+prefix",
           "<Queue>arn:aws:sqs:us-east-1:1:q</Queue>" in g and "<Value>in/</Value>" in g, g)
    _check("s3 notifications stored in the appliance shape",
           store.buckets["par-bkt"]["notifications"]["queueConfigurations"][0]["prefix"] == "in/")
    _check("s3 malformed notification → 400", c("PUT", "/par-bkt", {"notification": ""}, {}, b"<x").status == 400)
    # bucket ACL put/get
    acl = f'<AccessControlPolicy {NS}><Owner><ID>me</ID></Owner><AccessControlList/></AccessControlPolicy>'.encode()
    c("PUT", "/par-bkt", {"acl": ""}, {}, acl)
    _check("s3 bucket ACL PUT is stored", b"<ID>me</ID>" in c("GET", "/par-bkt", {"acl": ""}).body)
    # bucket tagging mirrors the dict the console reads
    tags = f'<Tagging {NS}><TagSet><Tag><Key>team</Key><Value>c0</Value></Tag></TagSet></Tagging>'.encode()
    c("PUT", "/par-bkt", {"tagging": ""}, {}, tags)
    _check("s3 bucket tagging also kept as meta['tags']", store.buckets["par-bkt"]["tags"] == {"team": "c0"})
    _check("s3 malformed lifecycle → MalformedXML", c("PUT", "/par-bkt", {"lifecycle": ""}, {}, b"<x").status == 400)
    # objects + object tagging / acl / x-amz-tagging
    c("PUT", "/par-bkt/in/a.txt", None, {"x-amz-tagging": "k=v"}, b"A")
    _check("s3 x-amz-tagging header tags the object",
           "<Key>k</Key><Value>v</Value>" in c("GET", "/par-bkt/in/a.txt", {"tagging": ""}).body.decode())
    c("PUT", "/par-bkt/in/a.txt", {"tagging": ""}, {},
      f'<Tagging {NS}><TagSet><Tag><Key>x</Key><Value>1</Value></Tag></TagSet></Tagging>'.encode())
    _check("s3 PUT object ?tagging does NOT overwrite the bytes",
           c("GET", "/par-bkt/in/a.txt").body == b"A")
    _check("s3 GET object ?tagging", "<Key>x</Key>" in c("GET", "/par-bkt/in/a.txt", {"tagging": ""}).body.decode())
    _check("s3 DELETE object ?tagging", c("DELETE", "/par-bkt/in/a.txt", {"tagging": ""}).status == 204
           and "<Tag>" not in c("GET", "/par-bkt/in/a.txt", {"tagging": ""}).body.decode())
    _check("s3 GET object ?acl", c("GET", "/par-bkt/in/a.txt", {"acl": ""}).status == 200)
    # ListObjects V1 + pagination; V2 continuation
    for i in range(5):
        c("PUT", f"/par-bkt/p/k{i}", None, None, b"x")
    v1 = c("GET", "/par-bkt", {"prefix": "p/", "max-keys": "2"}).body.decode()
    _check("s3 ListObjects V1 (Marker/NextMarker paging)",
           "<Marker></Marker>" in v1 and "<NextMarker>p/k1</NextMarker>" in v1 and "<IsTruncated>true" in v1, v1)
    v1b = c("GET", "/par-bkt", {"prefix": "p/", "marker": "p/k1"}).body.decode()
    _check("s3 ListObjects V1 marker resumes", re.findall(r"<Key>(.*?)</Key>", v1b) == ["p/k2", "p/k3", "p/k4"])
    v2 = c("GET", "/par-bkt", {"list-type": "2", "prefix": "p/", "max-keys": "3"}).body.decode()
    tok = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", v2).group(1)
    v2b = c("GET", "/par-bkt", {"list-type": "2", "prefix": "p/", "continuation-token": tok}).body.decode()
    _check("s3 ListObjectsV2 continuation-token paging", re.findall(r"<Key>(.*?)</Key>", v2b) == ["p/k3", "p/k4"])
    # DeleteObjects
    d = (f'<Delete {NS}><Object><Key>p/k0</Key></Object><Object><Key>p/k1</Key></Object></Delete>').encode()
    r = c("POST", "/par-bkt", {"delete": ""}, {}, d)
    _check("s3 DeleteObjects", r.status == 200 and r.body.decode().count("<Deleted>") == 2
           and c("GET", "/par-bkt/p/k0").status == 404)
    # ListMultipartUploads
    uid = re.search(r"<UploadId>(.*?)</UploadId>", c("POST", "/par-bkt/big", {"uploads": ""}).body.decode()).group(1)
    lmu = c("GET", "/par-bkt", {"uploads": ""}).body.decode()
    _check("s3 ListMultipartUploads", f"<UploadId>{uid}</UploadId>" in lmu, lmu)
    c("DELETE", "/par-bkt/big", {"uploadId": uid})
    # delete bucket semantics
    _check("s3 delete non-empty bucket → 409 BucketNotEmpty", c("DELETE", "/par-bkt").status == 409)
    _check("s3 delete missing bucket → 404", c("DELETE", "/nope-bkt").status == 404)
    # persistence of bucket config on a fresh instance (sqlite substrate)
    if fresh:
        f = fresh()
        _check("s3 fresh instance keeps notification config",
               f.buckets["par-bkt"]["notifications"]["queueConfigurations"][0]["queue"].endswith(":q"))
        _check("s3 fresh instance keeps bucket tags + ACL",
               f.buckets["par-bkt"]["tags"] == {"team": "c0"} and "<ID>me</ID>" in f.buckets["par-bkt"]["acl"])


def s3_events():
    st = _Recorder()
    c = lambda m, p, q=None, h=None, b=b"": s3.dispatch(st, m, p, q or {}, h or {}, b)
    c("PUT", "/ev-bkt")
    c("PUT", "/ev-bkt", {"notification": ""}, {}, f"<NotificationConfiguration {NS}/>".encode())
    c("PUT", "/ev-bkt/a", None, None, b"1")
    c("PUT", "/ev-bkt/b", None, {"x-amz-copy-source": "/ev-bkt/a"})
    c("DELETE", "/ev-bkt/a")
    names = [e[0] for e in st.events]
    _check("s3 emits TestEvent / ObjectCreated:Put / :Copy / ObjectRemoved:Delete",
           names == ["s3:TestEvent", "s3:ObjectCreated:Put", "s3:ObjectCreated:Copy", "s3:ObjectRemoved:Delete"], names)
    _check("s3 core calls persist() after mutations", st.persists >= 5, st.persists)


def gcs_parity(store, fresh):
    c = lambda m, p, q=None, h=None, b=b"": gcs.dispatch(store, m, p, q or {}, h or {}, b)
    c("POST", "/storage/v1/b", {}, {}, json.dumps({"name": "par-gb", "labels": {"a": "1"},
                                                   "retentionPolicy": {"retentionPeriod": 30}}).encode())
    c("POST", "/upload/storage/v1/b/par-gb/o", {"uploadType": "media", "name": "x/1.txt"}, {"content-type": "text/plain"}, b"one")
    c("POST", "/upload/storage/v1/b/par-gb/o", {"uploadType": "media", "name": "x/2.txt"}, {"content-type": "text/plain"}, b"two")
    r = c("POST", "/storage/v1/b/par-gb/o/x%2Fall.txt/compose", {}, {},
          json.dumps({"sourceObjects": [{"name": "x/1.txt"}, {"name": "x/2.txt"}]}).encode())
    _check("gcs compose", r.status == 200 and
           c("GET", "/storage/v1/b/par-gb/o/x%2Fall.txt", {"alt": "media"}).body == b"onetwo")
    p = c("PATCH", "/storage/v1/b/par-gb/o/x%2F1.txt", {}, {},
          json.dumps({"metadata": {"k": "v"}, "contentType": "text/csv"}).encode())
    view = json.loads(p.body)
    _check("gcs objects.patch (metadata + contentType + metageneration)",
           view["metadata"] == {"k": "v"} and view["contentType"] == "text/csv" and view["metageneration"] == "2", view)
    rng = c("GET", "/storage/v1/b/par-gb/o/x%2Fall.txt", {"alt": "media"}, {"range": "bytes=3-5"})
    _check("gcs ranged alt=media → 206", rng.status == 206 and rng.body == b"two")
    folder = c("POST", "/upload/storage/v1/b/par-gb/o", {"uploadType": "media", "name": "reports/"}, {}, b"")
    _check("gcs folder placeholder object 'reports/' addressable",
           folder.status == 200 and c("GET", "/storage/v1/b/par-gb/o/reports%2F").status == 200)
    j = c("POST", "/storage/v1/b/par-gb/o", {}, {"content-type": "application/json"},
          json.dumps({"name": "console.txt", "data": "from-console", "contentType": "text/plain"}).encode())
    _check("gcs pre-v4 console JSON insert", j.status == 200 and
           c("GET", "/storage/v1/b/par-gb/o/console.txt", {"alt": "media"}).body == b"from-console")
    pol = {"bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"]}]}
    c("POST", "/storage/v1/b/par-gb/iam", {}, {}, json.dumps(pol).encode())
    _check("gcs setIamPolicy via POST alias",
           json.loads(c("GET", "/storage/v1/b/par-gb/iam").body)["bindings"][0]["members"] == ["allUsers"])
    store.bucket_objects("par-gb")["legacy.txt"] = {"contentType": "text/plain", "size": "3",
                                                     "data_b64": "b2xk", "timeCreated": "2026-01-01T00:00:00.000Z"}
    _check("gcs alt=media reads data_b64 (console facade objects)",
           c("GET", "/storage/v1/b/par-gb/o/legacy.txt", {"alt": "media"}).body == b"old")
    if fresh:
        f = fresh()
        _check("gcs fresh instance keeps labels + retention + IAM",
               f.buckets["par-gb"]["labels"] == {"a": "1"} and f.buckets["par-gb"]["retentionPolicy"]
               and f.buckets["par-gb"]["iamPolicy"]["bindings"])


def ddb_parity(store):
    d = lambda op, body: ddb.dispatch(store, T + op, body)
    d("CreateTable", {"TableName": "par", "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"},
                                                         {"AttributeName": "sk", "KeyType": "RANGE"}],
                      "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"},
                                               {"AttributeName": "sk", "AttributeType": "N"}]})
    for i in (1, 2, 9, 10, 11):
        d("PutItem", {"TableName": "par", "Item": {"pk": {"S": "u"}, "sk": {"N": str(i)}, "n": {"N": str(i)},
                                                   "tag": {"S": "even" if i % 2 == 0 else "odd"}}})
    q = d("Query", {"TableName": "par", "KeyConditionExpression": "pk = :p AND sk >= :s",
                    "ExpressionAttributeValues": {":p": {"S": "u"}, ":s": {"N": "9"}}}).body
    _check("ddb key condition >= with NUMERIC ordering (9,10,11)",
           [i["sk"]["N"] for i in q["Items"]] == ["9", "10", "11"], q)
    q = d("Query", {"TableName": "par", "KeyConditionExpression": "pk = :p",
                    "FilterExpression": "#t = :e", "ExpressionAttributeNames": {"#t": "tag"},
                    "ExpressionAttributeValues": {":p": {"S": "u"}, ":e": {"S": "even"}},
                    "ScanIndexForward": False}).body
    _check("ddb FilterExpression + ScanIndexForward=false",
           [i["sk"]["N"] for i in q["Items"]] == ["10", "2"] and q["ScannedCount"] == 5, q)
    p1 = d("Scan", {"TableName": "par", "Limit": 2}).body
    p2 = d("Scan", {"TableName": "par", "Limit": 10, "ExclusiveStartKey": p1["LastEvaluatedKey"]}).body
    _check("ddb Scan pagination (Limit + LastEvaluatedKey/ExclusiveStartKey)",
           p1["Count"] == 2 and p2["Count"] == 3 and "LastEvaluatedKey" not in p2, (p1, p2))
    for i in range(120):
        d("PutItem", {"TableName": "par", "Item": {"pk": {"S": "bulk"}, "sk": {"N": str(i)}}})
    _check("ddb Scan without Limit is not capped at 100", d("Scan", {"TableName": "par"}).body["Count"] == 125)
    r = d("PutItem", {"TableName": "par", "Item": {"pk": {"S": "u"}, "sk": {"N": "1"}},
                      "ConditionExpression": "attribute_not_exists(pk)"})
    _check("ddb PutItem ConditionExpression → ConditionalCheckFailedException",
           r.status == 400 and "ConditionalCheckFailed" in r.body["__type"], r.body)
    u = d("UpdateItem", {"TableName": "par", "Key": {"pk": {"S": "u"}, "sk": {"N": "1"}},
                         "UpdateExpression": "SET n = n + :one, lst = list_append(if_not_exists(lst, :e), :l) "
                                             "REMOVE tag ADD cnt :one",
                         "ExpressionAttributeValues": {":one": {"N": "1"}, ":e": {"L": []}, ":l": {"L": [{"N": "7"}]}},
                         "ReturnValues": "ALL_NEW"}).body["Attributes"]
    _check("ddb UpdateExpression SET arithmetic / list_append / if_not_exists / REMOVE / ADD",
           u["n"] == {"N": "2"} and u["cnt"] == {"N": "1"} and "tag" not in u and u["lst"] == {"NS": ["7"]}, u)
    r = d("UpdateItem", {"TableName": "par", "Key": {"pk": {"S": "u"}, "sk": {"N": "1"}},
                         "UpdateExpression": "SET n = :z", "ConditionExpression": "n > :big",
                         "ExpressionAttributeValues": {":z": {"N": "0"}, ":big": {"N": "100"}}})
    _check("ddb UpdateItem ConditionExpression guards the write", r.status == 400)
    r = d("UpdateItem", {"TableName": "par", "Key": {"pk": {"S": "u"}, "sk": {"N": "2"}},
                         "UpdateExpression": "SET n = :z", "ExpressionAttributeValues": {":z": {"N": "5"}},
                         "ReturnValues": "NONE"})
    _check("ddb ReturnValues=NONE returns no Attributes", r.status == 200 and "Attributes" not in r.body)
    g = d("GetItem", {"TableName": "par", "Key": {"pk": {"S": "u"}, "sk": {"N": "2"}}}).body["Item"]
    q = d("Query", {"TableName": "par", "KeyConditionExpression": "pk = :p AND sk BETWEEN :a AND :b",
                    "ProjectionExpression": "sk, n", "ExpressionAttributeValues":
                    {":p": {"S": "u"}, ":a": {"N": "2"}, ":b": {"N": "9"}}}).body
    _check("ddb BETWEEN (numeric) + ProjectionExpression",
           g["n"] == {"N": "5"} and q["Items"] == [{"sk": {"N": "2"}, "n": {"N": "5"}}, {"sk": {"N": "9"}, "n": {"N": "9"}}], q)
    r = d("DeleteItem", {"TableName": "par", "Key": {"pk": {"S": "u"}, "sk": {"N": "9"}},
                         "ConditionExpression": "attribute_exists(nope)"})
    _check("ddb DeleteItem ConditionExpression", r.status == 400)
    r = d("Query", {"TableName": "par", "KeyConditionExpression": "pk = :p AND",
                    "ExpressionAttributeValues": {":p": {"S": "u"}}})
    _check("ddb malformed expression → ValidationException", r.status == 400 and "Validation" in r.body["__type"])


def run() -> int:
    print("[in-memory substrate]")
    s3_parity(InMemoryObjectStore(), None)
    s3_events()
    gcs_parity(InMemoryObjectStore(), None)
    ddb_parity(InMemoryNoSqlStore())
    print("[sqlite substrate — fresh-instance durability]")
    be = SqliteStateBackend(":memory:")
    s3_parity(PersistentObjectStore(be, "s3"), lambda: PersistentObjectStore(be, "s3"))
    gcs_parity(PersistentObjectStore(be, "gcs"), lambda: PersistentObjectStore(be, "gcs"))
    ddb_parity(PersistentNoSqlStore(be, "ddb"))
    print("\nRESULT: PASS — C0 legacy-parity behaviours hold in the shared cores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
