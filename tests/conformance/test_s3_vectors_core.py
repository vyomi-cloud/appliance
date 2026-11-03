"""S3 Vectors (AWS-01): buckets -> indexes -> vectors, exact kNN + metadata filter, via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_s3_vectors_core.py
"""
import json

from core.aws_wire_router import AwsWireRouter

SV = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/s3vectors/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(r, op, payload=None):
    out = r.handle("POST", "/" + op, {}, {"authorization": SV, "content-type": "application/json"}, json.dumps(payload or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def main():
    r = AwsWireRouter()
    s, o = call(r, "CreateVectorBucket", {"vectorBucketName": "vb-one"})
    _check("create bucket", s == 200 and o["vectorBucketArn"].endswith(":bucket/vb-one"))
    _check("duplicate bucket 409", call(r, "CreateVectorBucket", {"vectorBucketName": "vb-one"})[0] == 409)
    _check("bad bucket name 400", call(r, "CreateVectorBucket", {"vectorBucketName": "A_B"})[0] == 400)
    s, o = call(r, "GetVectorBucket", {"vectorBucketName": "vb-one"})
    _check("get bucket", s == 200 and o["vectorBucket"]["encryptionConfiguration"]["sseType"] == "AES256")
    _check("get missing 404", call(r, "GetVectorBucket", {"vectorBucketName": "nope-b"})[0] == 404)
    s, o = call(r, "ListVectorBuckets")
    _check("list buckets", [b["vectorBucketName"] for b in o["vectorBuckets"]] == ["vb-one"])

    s, o = call(r, "CreateIndex", {"vectorBucketName": "vb-one", "indexName": "idx", "dataType": "float32", "dimension": 3,
                                    "distanceMetric": "euclidean", "metadataConfiguration": {"nonFilterableMetadataKeys": ["text"]}})
    _check("create index", s == 200 and o["indexArn"].endswith("/index/idx"))
    _check("bad metric 400", call(r, "CreateIndex", {"vectorBucketName": "vb-one", "indexName": "bad", "dataType": "float32", "dimension": 3, "distanceMetric": "dot"})[0] == 400)
    s, o = call(r, "GetIndex", {"vectorBucketName": "vb-one", "indexName": "idx"})
    _check("get index", o["index"]["dimension"] == 3 and o["index"]["distanceMetric"] == "euclidean")
    _check("delete bucket with index 409", call(r, "DeleteVectorBucket", {"vectorBucketName": "vb-one"})[0] == 409)

    V = lambda k, v, m=None: {"key": k, "data": {"float32": v}, **({"metadata": m} if m else {})}
    s, _ = call(r, "PutVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "vectors": [
        V("a", [0, 0, 0], {"genre": "scifi", "year": 1999, "text": "x" * 100}),
        V("b", [1, 0, 0], {"genre": "drama", "year": 2005}),
        V("c", [5, 5, 5], {"genre": "scifi", "year": 2020}),
    ]})
    _check("put vectors", s == 200)
    _check("dim mismatch 400", call(r, "PutVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "vectors": [V("z", [1, 2])]})[0] == 400)
    _check("all-or-nothing batch", call(r, "PutVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "vectors": [V("ok", [1, 1, 1]), V("bad", [1])]})[0] == 400
           and call(r, "GetVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "keys": ["ok"]})[1]["vectors"] == [])

    q = lambda **kw: call(r, "QueryVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "queryVector": {"float32": [0.9, 0, 0]},
                                              "topK": 2, "returnDistance": True, "returnMetadata": True, **kw})[1]
    o = q()
    _check("nearest first", [v["key"] for v in o["vectors"]] == ["b", "a"] and o["distanceMetric"] == "euclidean")
    _check("distance value", abs(o["vectors"][0]["distance"] - 0.1) < 1e-9)
    _check("filter $eq", [v["key"] for v in q(filter={"genre": "scifi"})["vectors"]] == ["a", "c"])
    _check("filter $gt + $in", [v["key"] for v in q(filter={"year": {"$gt": 2000}, "genre": {"$in": ["drama", "scifi"]}})["vectors"]] == ["b", "c"])
    _check("filter $or", [v["key"] for v in q(filter={"$or": [{"year": 1999}, {"year": 2020}]})["vectors"]] == ["a", "c"])
    _check("filter $exists", len(q(filter={"text": {"$exists": True}})["vectors"]) == 1)
    _check("type-strict $eq", q(filter={"year": "1999"})["vectors"] == [])
    _check("bad operator 400", call(r, "QueryVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "queryVector": {"float32": [0, 0, 0]}, "topK": 1, "filter": {"year": {"$regex": "x"}}})[0] == 400)
    _check("topK > 100 400", call(r, "QueryVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "queryVector": {"float32": [0, 0, 0]}, "topK": 101})[0] == 400)

    s, o = call(r, "GetVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "keys": ["a", "missing"], "returnData": True, "returnMetadata": True})
    _check("get vectors (missing skipped)", [v["key"] for v in o["vectors"]] == ["a"] and o["vectors"][0]["data"]["float32"] == [0, 0, 0])
    s, o = call(r, "ListVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "maxResults": 2})
    _check("list vectors paginates", len(o["vectors"]) == 2 and o.get("nextToken"))
    s, o2 = call(r, "ListVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "maxResults": 2, "nextToken": o["nextToken"]})
    _check("list vectors page 2", [v["key"] for v in o2["vectors"]] == ["c"] and "nextToken" not in o2)
    _check("delete vectors", call(r, "DeleteVectors", {"vectorBucketName": "vb-one", "indexName": "idx", "keys": ["a", "nope"]})[0] == 200
           and [v["key"] for v in call(r, "ListVectors", {"vectorBucketName": "vb-one", "indexName": "idx"})[1]["vectors"]] == ["b", "c"])

    cos = call(r, "CreateIndex", {"vectorBucketName": "vb-one", "indexName": "cos", "dataType": "float32", "dimension": 2, "distanceMetric": "cosine"})
    call(r, "PutVectors", {"vectorBucketName": "vb-one", "indexName": "cos", "vectors": [V("x", [1, 0]), V("y", [0, 1]), V("z", [10, 0.1])]})
    o = call(r, "QueryVectors", {"vectorBucketName": "vb-one", "indexName": "cos", "queryVector": {"float32": [2, 0]}, "topK": 3, "returnDistance": True})[1]
    _check("cosine ignores magnitude", [v["key"] for v in o["vectors"]][-1] == "y" and abs(o["vectors"][0]["distance"]) < 1e-3)

    pol = json.dumps({"Version": "2012-10-17", "Statement": []})
    _check("policy put/get/delete", call(r, "PutVectorBucketPolicy", {"vectorBucketName": "vb-one", "policy": pol})[0] == 200
           and call(r, "GetVectorBucketPolicy", {"vectorBucketName": "vb-one"})[1]["policy"] == pol
           and call(r, "DeleteVectorBucketPolicy", {"vectorBucketName": "vb-one"})[0] == 200
           and call(r, "GetVectorBucketPolicy", {"vectorBucketName": "vb-one"})[0] == 404)

    for i in ("idx", "cos"):
        _check(f"delete index {i}", call(r, "DeleteIndex", {"vectorBucketName": "vb-one", "indexName": i})[0] == 200)
    _check("delete bucket", call(r, "DeleteVectorBucket", {"vectorBucketName": "vb-one"})[0] == 200
           and call(r, "ListVectorBuckets")[1]["vectorBuckets"] == [])
    print("S3 Vectors core: all green")


if __name__ == "__main__":
    main()
