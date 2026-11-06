"""ElastiCache engine conformance — host (CPython) and Pyodide.

Drives core/elasticache_core.py on the native Query wire (Action=...): cluster /
replication-group lifecycle, subnet + parameter groups, snapshots, tags, the
errors real SDKs branch on, and the console REST view built on the same engine.
"""
import re

try:
    from core import elasticache_core as ec
except ImportError:  # pragma: no cover - Pyodide flat layout
    import elasticache_core as ec  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or ec.ElastiCacheStore()

    def call(**p):
        return ec.dispatch(s, p)

    def ok(**p):
        r = call(**p)
        if r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        return r.body

    def code(**p):
        r = call(**p)
        return r.status, re.search(r"<Code>(.*?)</Code>", r.body).group(1)

    body = ok(Action="CreateCacheCluster", CacheClusterId="c1", Engine="valkey", CacheNodeType="cache.t3.micro")
    _check("create cluster is available", "<CacheClusterStatus>available</CacheClusterStatus>" in body)
    _check("cluster has an ARN", "arn:aws:elasticache:us-east-1:123456789012:cluster:c1" in body)
    _check("cluster has a node endpoint + port", "<Endpoint><Address>" in body and "<Port>6379</Port>" in body)
    _check("duplicate cluster", code(Action="CreateCacheCluster", CacheClusterId="c1") == (400, "CacheClusterAlreadyExists"))
    _check("missing cluster", code(Action="DescribeCacheClusters", CacheClusterId="zz") == (404, "CacheClusterNotFound"))
    _check("bad engine", code(Action="CreateCacheCluster", CacheClusterId="c2", Engine="nope")[1] == "InvalidParameterValue")

    ok(Action="ModifyCacheCluster", CacheClusterId="c1", CacheNodeType="cache.t3.small", ApplyImmediately="true")
    _check("modify node type", "cache.t3.small" in ok(Action="DescribeCacheClusters", CacheClusterId="c1"))

    # tags
    arn = re.search(r"<ARN>(.*?)</ARN>", body).group(1)
    ok(**{"Action": "AddTagsToResource", "ResourceName": arn, "Tags.Tag.1.Key": "a", "Tags.Tag.1.Value": "b"})
    _check("tag round trip", "<Key>a</Key><Value>b</Value>" in ok(Action="ListTagsForResource", ResourceName=arn))
    ok(**{"Action": "RemoveTagsFromResource", "ResourceName": arn, "TagKeys.member.1": "a"})
    _check("tag removed", "<Key>a</Key>" not in ok(Action="ListTagsForResource", ResourceName=arn))

    # subnet group (default exists, cannot be deleted; in-use groups are protected)
    _check("default subnet group", "<CacheSubnetGroupName>default</CacheSubnetGroupName>" in ok(Action="DescribeCacheSubnetGroups"))
    ok(**{"Action": "CreateCacheSubnetGroup", "CacheSubnetGroupName": "sg", "CacheSubnetGroupDescription": "d",
          "SubnetIds.SubnetIdentifier.1": "subnet-1", "SubnetIds.SubnetIdentifier.2": "subnet-2"})
    ok(Action="CreateCacheCluster", CacheClusterId="c3", Engine="redis", CacheSubnetGroupName="sg")
    _check("subnet group in use", code(Action="DeleteCacheSubnetGroup", CacheSubnetGroupName="sg")[1] == "CacheSubnetGroupInUse")
    ok(Action="DeleteCacheCluster", CacheClusterId="c3")
    ok(Action="DeleteCacheSubnetGroup", CacheSubnetGroupName="sg")

    # parameter group
    ok(Action="CreateCacheParameterGroup", CacheParameterGroupName="pg", CacheParameterGroupFamily="valkey8", Description="d")
    ok(**{"Action": "ModifyCacheParameterGroup", "CacheParameterGroupName": "pg",
          "ParameterNameValues.ParameterNameValue.1.ParameterName": "timeout",
          "ParameterNameValues.ParameterNameValue.1.ParameterValue": "9"})
    _check("parameter value stored", "<ParameterValue>9</ParameterValue>" in ok(Action="DescribeCacheParameters", CacheParameterGroupName="pg"))
    _check("default group is read-only", code(Action="DeleteCacheParameterGroup", CacheParameterGroupName="default.valkey8")[1] == "InvalidCacheParameterGroupState")

    # snapshot
    ok(Action="CreateSnapshot", SnapshotName="s1", CacheClusterId="c1")
    _check("snapshot listed", "<SnapshotName>s1</SnapshotName>" in ok(Action="DescribeSnapshots"))
    _check("duplicate snapshot", code(Action="CreateSnapshot", SnapshotName="s1", CacheClusterId="c1")[1] == "SnapshotAlreadyExistsFault")
    ok(Action="DeleteSnapshot", SnapshotName="s1")

    # replication group
    rg = ok(Action="CreateReplicationGroup", ReplicationGroupId="rg", ReplicationGroupDescription="d",
            Engine="valkey", NumCacheClusters="3", AutomaticFailoverEnabled="true")
    _check("rg has 3 members", rg.count("<ClusterId>") == 3)
    _check("rg has a primary endpoint", "<PrimaryEndpoint>" in rg)
    _check("rg members are clusters", "<CacheClusterId>rg-001</CacheClusterId>" in ok(Action="DescribeCacheClusters"))
    ok(Action="DeleteReplicationGroup", ReplicationGroupId="rg")
    _check("rg members removed with the group", "rg-001" not in ok(Action="DescribeCacheClusters"))
    _check("missing rg", code(Action="DescribeReplicationGroups", ReplicationGroupId="rg")[1] == "ReplicationGroupNotFoundFault")

    # console REST view
    row = ec.console_create(s, {"name": "ui"})
    _check("console create fills every field", all(v not in (None, "") for k, v in row.items() if k != "tags"))
    _check("console list has the cache", [r["name"] for r in ec.console_list(s)["items"]].count("ui") == 1)
    ec.console_delete(s, "ui")
    ok(Action="DeleteCacheCluster", CacheClusterId="c1")
    _check("clean slate", "<CacheCluster>" not in ok(Action="DescribeCacheClusters"))
    return s


def test_elasticache_core():
    run()


if __name__ == "__main__":
    run()
    print("elasticache core: ok")
