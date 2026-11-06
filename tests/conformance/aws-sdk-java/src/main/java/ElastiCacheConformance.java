// Real aws-sdk-java-v2 ElastiCache conformance probe against Vyomi.
//
// Unmodified software.amazon.awssdk.services.elasticache with only the endpoint
// overridden. One [PASS]/[FAIL] line per check; exit code 1 on any failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=ElastiCacheConformance

import java.net.URI;
import java.util.List;
import java.util.function.Supplier;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.elasticache.ElastiCacheClient;
import software.amazon.awssdk.services.elasticache.model.*;

public class ElastiCacheConformance {

    static int pass = 0;
    static int fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) {
            pass++;
            System.out.println("[PASS] " + name);
        } else {
            fail++;
            System.out.println("[FAIL] " + name + (detail == null || detail.isEmpty() ? "" : " :: " + detail));
        }
    }

    static <T> T run(String name, Supplier<T> fn) {
        try {
            T v = fn.get();
            chk(name, true, "");
            return v;
        } catch (Exception e) {
            chk(name, false, e.toString());
            return null;
        }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        ElastiCacheClient ec = ElastiCacheClient.builder()
                .endpointOverride(URI.create(endpoint))
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        String sfx = Long.toString(System.currentTimeMillis() % 1000000);
        String sg = "jsg-" + sfx, pg = "jpg-" + sfx, cl = "jcache-" + sfx, rg = "jrg-" + sfx, snap = "jsnap-" + sfx;

        run("CreateCacheSubnetGroup", () -> ec.createCacheSubnetGroup(CreateCacheSubnetGroupRequest.builder()
                .cacheSubnetGroupName(sg).cacheSubnetGroupDescription("java test")
                .subnetIds("subnet-aaa111", "subnet-bbb222").build()));
        DescribeCacheSubnetGroupsResponse sgs = run("DescribeCacheSubnetGroups", () ->
                ec.describeCacheSubnetGroups(DescribeCacheSubnetGroupsRequest.builder().cacheSubnetGroupName(sg).build()));
        chk("subnet group has 2 subnets", sgs != null && sgs.cacheSubnetGroups().get(0).subnets().size() == 2, "");

        run("CreateCacheParameterGroup", () -> ec.createCacheParameterGroup(CreateCacheParameterGroupRequest.builder()
                .cacheParameterGroupName(pg).cacheParameterGroupFamily("valkey8").description("java test").build()));
        run("ModifyCacheParameterGroup", () -> ec.modifyCacheParameterGroup(ModifyCacheParameterGroupRequest.builder()
                .cacheParameterGroupName(pg)
                .parameterNameValues(ParameterNameValue.builder().parameterName("timeout").parameterValue("30").build()).build()));
        DescribeCacheParametersResponse params = run("DescribeCacheParameters", () ->
                ec.describeCacheParameters(DescribeCacheParametersRequest.builder().cacheParameterGroupName(pg).build()));
        chk("modified parameter reads back",
                params != null && params.parameters().stream().anyMatch(p -> p.parameterName().equals("timeout") && "30".equals(p.parameterValue())), "");

        CreateCacheClusterResponse created = run("CreateCacheCluster", () -> ec.createCacheCluster(CreateCacheClusterRequest.builder()
                .cacheClusterId(cl).engine("valkey").cacheNodeType("cache.t3.micro").numCacheNodes(1)
                .cacheSubnetGroupName(sg).cacheParameterGroupName(pg)
                .tags(Tag.builder().key("env").value("test").build()).build()));
        chk("cluster is available", created != null && "available".equals(created.cacheCluster().cacheClusterStatus()), "");
        DescribeCacheClustersResponse desc = run("DescribeCacheClusters", () -> ec.describeCacheClusters(
                DescribeCacheClustersRequest.builder().cacheClusterId(cl).showCacheNodeInfo(true).build()));
        CacheCluster c = desc == null ? null : desc.cacheClusters().get(0);
        chk("cluster fields (engine/version/endpoint/arn)", c != null && "valkey".equals(c.engine())
                && c.engineVersion() != null && !c.cacheNodes().isEmpty()
                && c.cacheNodes().get(0).endpoint().port() > 0 && c.arn() != null, c == null ? "" : c.toString());
        chk("cluster uses requested subnet + parameter group", c != null && sg.equals(c.cacheSubnetGroupName())
                && pg.equals(c.cacheParameterGroup().cacheParameterGroupName()), "");

        run("ModifyCacheCluster (node type)", () -> ec.modifyCacheCluster(ModifyCacheClusterRequest.builder()
                .cacheClusterId(cl).cacheNodeType("cache.t3.small").applyImmediately(true).build()));
        DescribeCacheClustersResponse after = run("DescribeCacheClusters after modify", () -> ec.describeCacheClusters(
                DescribeCacheClustersRequest.builder().cacheClusterId(cl).build()));
        chk("node type changed", after != null && "cache.t3.small".equals(after.cacheClusters().get(0).cacheNodeType()), "");
        run("RebootCacheCluster", () -> ec.rebootCacheCluster(RebootCacheClusterRequest.builder()
                .cacheClusterId(cl).cacheNodeIdsToReboot("0001").build()));

        String arn = c == null ? "" : c.arn();
        run("AddTagsToResource", () -> ec.addTagsToResource(AddTagsToResourceRequest.builder()
                .resourceName(arn).tags(Tag.builder().key("team").value("platform").build()).build()));
        ListTagsForResourceResponse tags = run("ListTagsForResource", () -> ec.listTagsForResource(
                ListTagsForResourceRequest.builder().resourceName(arn).build()));
        chk("both tags present", tags != null && tags.tagList().size() == 2, "");
        run("RemoveTagsFromResource", () -> ec.removeTagsFromResource(RemoveTagsFromResourceRequest.builder()
                .resourceName(arn).tagKeys("team").build()));

        run("CreateSnapshot", () -> ec.createSnapshot(CreateSnapshotRequest.builder().snapshotName(snap).cacheClusterId(cl).build()));
        DescribeSnapshotsResponse snaps = run("DescribeSnapshots", () -> ec.describeSnapshots(
                DescribeSnapshotsRequest.builder().snapshotName(snap).build()));
        chk("snapshot is available", snaps != null && "available".equals(snaps.snapshots().get(0).snapshotStatus()), "");

        CreateReplicationGroupResponse rgr = run("CreateReplicationGroup", () -> ec.createReplicationGroup(
                CreateReplicationGroupRequest.builder().replicationGroupId(rg).replicationGroupDescription("java rg")
                        .engine("valkey").cacheNodeType("cache.t3.micro").numCacheClusters(2)
                        .automaticFailoverEnabled(true).build()));
        chk("replication group has 2 members + primary endpoint", rgr != null
                && rgr.replicationGroup().memberClusters().size() == 2
                && rgr.replicationGroup().nodeGroups().get(0).primaryEndpoint().address() != null, "");
        DescribeReplicationGroupsResponse rgd = run("DescribeReplicationGroups", () -> ec.describeReplicationGroups(
                DescribeReplicationGroupsRequest.builder().replicationGroupId(rg).build()));
        chk("replication group available", rgd != null && "available".equals(rgd.replicationGroups().get(0).status()), "");

        DescribeCacheEngineVersionsResponse ev = run("DescribeCacheEngineVersions", () -> ec.describeCacheEngineVersions(
                DescribeCacheEngineVersionsRequest.builder().engine("valkey").build()));
        chk("valkey versions listed", ev != null && !ev.cacheEngineVersions().isEmpty(), "");
        DescribeEventsResponse evs = run("DescribeEvents", () -> ec.describeEvents(DescribeEventsRequest.builder().build()));
        chk("events recorded", evs != null && !evs.events().isEmpty(), "");

        try {
            ec.describeCacheClusters(DescribeCacheClustersRequest.builder().cacheClusterId("nope-" + sfx).build());
            chk("missing cluster -> CacheClusterNotFoundException", false, "no error");
        } catch (CacheClusterNotFoundException e) {
            chk("missing cluster -> CacheClusterNotFoundException", true, "");
        } catch (Exception e) {
            chk("missing cluster -> CacheClusterNotFoundException", false, e.toString());
        }
        try {
            ec.createCacheCluster(CreateCacheClusterRequest.builder().cacheClusterId(cl).engine("valkey").build());
            chk("duplicate cluster -> CacheClusterAlreadyExistsException", false, "no error");
        } catch (CacheClusterAlreadyExistsException e) {
            chk("duplicate cluster -> CacheClusterAlreadyExistsException", true, "");
        } catch (Exception e) {
            chk("duplicate cluster -> CacheClusterAlreadyExistsException", false, e.toString());
        }

        run("DeleteSnapshot", () -> ec.deleteSnapshot(DeleteSnapshotRequest.builder().snapshotName(snap).build()));
        run("DeleteReplicationGroup", () -> ec.deleteReplicationGroup(DeleteReplicationGroupRequest.builder().replicationGroupId(rg).build()));
        run("DeleteCacheCluster", () -> ec.deleteCacheCluster(DeleteCacheClusterRequest.builder().cacheClusterId(cl).build()));
        run("DeleteCacheParameterGroup", () -> ec.deleteCacheParameterGroup(DeleteCacheParameterGroupRequest.builder().cacheParameterGroupName(pg).build()));
        run("DeleteCacheSubnetGroup", () -> ec.deleteCacheSubnetGroup(DeleteCacheSubnetGroupRequest.builder().cacheSubnetGroupName(sg).build()));
        DescribeCacheClustersResponse left = run("DescribeCacheClusters after delete", () -> ec.describeCacheClusters(
                DescribeCacheClustersRequest.builder().build()));
        chk("cluster gone", left != null && left.cacheClusters().stream().noneMatch(x -> x.cacheClusterId().equals(cl)), "");

        System.out.println("elasticache java: " + pass + " passed, " + fail + " failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}
