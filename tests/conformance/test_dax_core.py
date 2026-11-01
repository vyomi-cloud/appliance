"""DynamoDB Accelerator (DAX) conformance — control plane (AmazonDAXV3 JSON protocol)
+ cache engine (v4 depth: alarms + DAX).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dax_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json
import time

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as ddb
    from core import dax_core as dax
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as ddb  # type: ignore
    import dax_core as dax  # type: ignore

T = "AmazonDAXV3."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _call(store, action, payload):
    r = dax.dispatch(store, T + action, payload)
    return r.status, r.body


def run() -> int:
    st = dax.DaxStore()
    ddb_store = InMemoryNoSqlStore()
    st.ddb_store = ddb_store

    ddb.dispatch(ddb_store, "DynamoDB_20120810.CreateTable", {
        "TableName": "orders", "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
    })

    # ── subnet groups ───────────────────────────────────────────────────────
    status, body = _call(st, "CreateSubnetGroup", {
        "SubnetGroupName": "dax-subnets", "Description": "primary", "SubnetIds": ["subnet-a", "subnet-b"]})
    _check("CreateSubnetGroup 200", status == 200)
    _check("subnet group has 2 subnets", len(body["SubnetGroup"]["Subnets"]) == 2)
    status, body = _call(st, "CreateSubnetGroup", {"SubnetGroupName": "dax-subnets", "SubnetIds": ["subnet-a"]})
    _check("duplicate subnet group rejected", status == 400 and body["__type"] == "SubnetGroupAlreadyExistsFault")
    _call(st, "UpdateSubnetGroup", {"SubnetGroupName": "dax-subnets", "Description": "updated"})
    _, body = _call(st, "DescribeSubnetGroups", {})
    _check("DescribeSubnetGroups lists it", body["SubnetGroups"][0]["Description"] == "updated")

    # ── parameter groups ────────────────────────────────────────────────────
    _, body = _call(st, "DescribeDefaultParameters", {})
    _check("default parameter group has record/query TTL params",
           {p["ParameterName"] for p in body["Parameters"]} == {"record-ttl-millis", "query-ttl-millis"})
    status, body = _call(st, "CreateParameterGroup", {"ParameterGroupName": "fast-ttl", "Description": "short TTLs"})
    _check("CreateParameterGroup 200", status == 200)
    status, body = _call(st, "UpdateParameterGroup", {"ParameterGroupName": "fast-ttl", "ParameterNameValues": [
        {"ParameterName": "record-ttl-millis", "ParameterValue": "50"},
        {"ParameterName": "query-ttl-millis", "ParameterValue": "50"},
    ]})
    _check("UpdateParameterGroup 200", status == 200)
    status, _ = _call(st, "UpdateParameterGroup", {"ParameterGroupName": "fast-ttl", "ParameterNameValues": [
        {"ParameterName": "not-a-real-param", "ParameterValue": "1"}]})
    _check("invalid parameter name rejected", status == 400)
    status, _ = _call(st, "UpdateParameterGroup", {"ParameterGroupName": "default.dax1.0", "ParameterNameValues": [
        {"ParameterName": "record-ttl-millis", "ParameterValue": "1"}]})
    _check("default parameter group is immutable", status == 400)
    status, _ = _call(st, "DeleteParameterGroup", {"ParameterGroupName": "default.dax1.0"})
    _check("default parameter group cannot be deleted", status == 400)

    # ── clusters ─────────────────────────────────────────────────────────────
    status, body = _call(st, "CreateCluster", {
        "ClusterName": "orders-cache", "NodeType": "dax.t3.small", "ReplicationFactor": 2,
        "IamRoleArn": "arn:aws:iam::123456789012:role/dax", "SubnetGroupName": "dax-subnets",
        "ParameterGroupName": "fast-ttl", "Tags": [{"Key": "env", "Value": "prod"}],
    })
    _check("CreateCluster 200", status == 200)
    _check("cluster has 2 nodes", body["Cluster"]["TotalNodes"] == 2)
    _check("cluster endpoint present", body["Cluster"]["ClusterDiscoveryEndpoint"]["Port"] == 8111)
    _check("node endpoint present", body["Cluster"]["Nodes"][0]["Endpoint"]["Port"] == 8111)
    status, _ = _call(st, "CreateCluster", {"ClusterName": "orders-cache", "NodeType": "dax.t3.small"})
    _check("duplicate cluster rejected", status == 400)
    status, _ = _call(st, "CreateCluster", {"ClusterName": "bad", "NodeType": "dax.t3.small",
                                            "SubnetGroupName": "no-such-subnet-group"})
    _check("unknown subnet group rejected", status == 400)

    _, body = _call(st, "DescribeClusters", {})
    _check("DescribeClusters lists it", any(c["ClusterName"] == "orders-cache" for c in body["Clusters"]))

    status, body = _call(st, "IncreaseReplicationFactor", {"ClusterName": "orders-cache", "NewReplicationFactor": 4})
    _check("IncreaseReplicationFactor -> 4 nodes", status == 200 and body["Cluster"]["TotalNodes"] == 4)
    status, body = _call(st, "DecreaseReplicationFactor", {"ClusterName": "orders-cache", "NewReplicationFactor": 2})
    _check("DecreaseReplicationFactor -> 2 nodes", status == 200 and body["Cluster"]["TotalNodes"] == 2)

    node_id = body["Cluster"]["Nodes"][0]["NodeId"]
    status, _ = _call(st, "RebootNode", {"ClusterName": "orders-cache", "NodeId": node_id})
    _check("RebootNode 200", status == 200)
    status, _ = _call(st, "RebootNode", {"ClusterName": "orders-cache", "NodeId": "no-such-node"})
    _check("RebootNode unknown node -> NodeNotFoundFault", status == 400)

    # ── tags ─────────────────────────────────────────────────────────────────
    arn = f"arn:aws:dax:us-east-1:123456789012:cache/orders-cache"
    _, body = _call(st, "ListTags", {"ResourceName": arn})
    _check("CreateCluster Tags landed", {"Key": "env", "Value": "prod"} in body["Tags"])
    _call(st, "TagResource", {"ResourceName": arn, "Tags": [{"Key": "team", "Value": "payments"}]})
    _, body = _call(st, "ListTags", {"ResourceName": arn})
    _check("TagResource added a tag", {"Key": "team", "Value": "payments"} in body["Tags"])
    _call(st, "UntagResource", {"ResourceName": arn, "TagKeys": ["team"]})
    _, body = _call(st, "ListTags", {"ResourceName": arn})
    _check("UntagResource removed it", not any(t["Key"] == "team" for t in body["Tags"]))

    # ── events ───────────────────────────────────────────────────────────────
    _, body = _call(st, "DescribeEvents", {"SourceName": "orders-cache"})
    _check("cluster lifecycle events recorded", any("created" in e["Message"].lower() for e in body["Events"]))

    status, body = _call(st, "DeleteCluster", {"ClusterName": "orders-cache"})
    _check("DeleteCluster 200", status == 200 and body["Cluster"]["Status"] == "deleting")
    status, _ = _call(st, "DescribeClusters", {"ClusterNames": ["orders-cache"]})
    _, body = _call(st, "DescribeClusters", {})
    _check("deleted cluster is gone", not any(c["ClusterName"] == "orders-cache" for c in body["Clusters"]))

    # ── cache engine: read-through / write-through / TTL / consistency bypass ─
    _call(st, "CreateCluster", {"ClusterName": "c1", "NodeType": "dax.t3.small", "ReplicationFactor": 1,
                                "ParameterGroupName": "fast-ttl"})
    dax.put_item(st, "c1", "orders", {"id": {"S": "o1"}, "total": {"N": "10"}})
    item = dax.get_item(st, "c1", "orders", {"id": {"S": "o1"}})
    _check("write-through PutItem round-trips through the cache", item == {"id": {"S": "o1"}, "total": {"N": "10"}})
    _check("PutItem really landed in the DynamoDB store (not just the cache)",
           ddb.dispatch(ddb_store, "DynamoDB_20120810.GetItem",
                       {"TableName": "orders", "Key": {"id": {"S": "o1"}}}).body.get("Item") is not None)

    # Mutate the underlying table directly (bypassing DAX) to prove a cache HIT serves stale data.
    rec = next(iter(ddb_store.get_table("orders")["items"].values()))
    rec["av"]["total"] = {"N": "999"}
    stale = dax.get_item(st, "c1", "orders", {"id": {"S": "o1"}})
    _check("a cache hit serves the (now stale) cached value", stale["total"]["N"] == "10")
    fresh = dax.get_item(st, "c1", "orders", {"id": {"S": "o1"}}, consistent_read=True)
    _check("ConsistentRead bypasses the cache and reads the real store", fresh["total"]["N"] == "999")

    # record-ttl-millis=50 on this cluster's parameter group -> the cache entry expires.
    dax.put_item(st, "c1", "orders", {"id": {"S": "o2"}, "total": {"N": "5"}})
    rec2 = ddb_store.get_table("orders")["items"]
    rec2[next(k for k in rec2 if "o2" in k)]["av"]["total"] = {"N": "500"}
    time.sleep(0.08)
    expired = dax.get_item(st, "c1", "orders", {"id": {"S": "o2"}})
    _check("record-ttl-millis expiry forces a refetch from the real store", expired["total"]["N"] == "500")

    dax.delete_item(st, "c1", "orders", {"id": {"S": "o1"}})
    _check("DeleteItem removed it from the DAX item cache", ("orders", (("id", '{"S": "o1"}'),)) not in st._item_cache["c1"])
    _check("DeleteItem removed it from the real store",
           ddb.dispatch(ddb_store, "DynamoDB_20120810.GetItem",
                       {"TableName": "orders", "Key": {"id": {"S": "o1"}}}).body.get("Item") is None)

    # Query cache: populate, hit, then a write invalidates it.
    sig = {"KeyConditionExpression": "id = :v"}
    _check("query cache starts empty", dax.query(st, "c1", "orders", sig) is None)
    dax.put_query_result(st, "c1", "orders", sig, [{"id": {"S": "o2"}}])
    _check("query cache serves the cached result", dax.query(st, "c1", "orders", sig) == [{"id": {"S": "o2"}}])
    dax.put_item(st, "c1", "orders", {"id": {"S": "o3"}, "total": {"N": "1"}})
    _check("a write invalidates the whole query cache", dax.query(st, "c1", "orders", sig) is None)

    # LRU eviction sized by node type (dax.t3.small -> 200 entries).
    for i in range(205):
        dax.put_item(st, "c1", "orders", {"id": {"S": f"bulk-{i}"}, "n": {"N": str(i)}})
    _check("item cache is LRU-bounded by node type capacity", len(st._item_cache["c1"]) <= 200)

    # ── AWS/DAX CloudWatch metrics really move ────────────────────────────────
    from core import cloudwatch_core as cw
    st.cw_store = cw.CloudWatchStore()
    dax.put_item(st, "c1", "orders", {"id": {"S": "m1"}, "v": {"N": "1"}})
    dax.get_item(st, "c1", "orders", {"id": {"S": "m1"}})          # hit
    dax.get_item(st, "c1", "orders", {"id": {"S": "does-not-exist"}})  # miss
    now = time.time()
    hits = cw.op_get_metric_statistics(st.cw_store, {
        "Namespace": "AWS/DAX", "MetricName": "ItemCacheHits", "Dimensions": [{"Name": "ClusterId", "Value": "c1"}],
        "StartTime": now - 60, "EndTime": now + 1, "Period": 60, "Statistics": ["Sum"]})
    misses = cw.op_get_metric_statistics(st.cw_store, {
        "Namespace": "AWS/DAX", "MetricName": "ItemCacheMisses", "Dimensions": [{"Name": "ClusterId", "Value": "c1"}],
        "StartTime": now - 60, "EndTime": now + 1, "Period": 60, "Statistics": ["Sum"]})
    _check("ItemCacheHits recorded", sum(d["Sum"] or 0 for d in hits["Datapoints"]) >= 1)
    _check("ItemCacheMisses recorded", sum(d["Sum"] or 0 for d in misses["Datapoints"]) >= 1)

    print("\nDAX conformance (control plane + cache engine): ALL GREEN")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
