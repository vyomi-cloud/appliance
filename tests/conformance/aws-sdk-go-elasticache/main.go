// Real aws-sdk-go-v2 ElastiCache conformance probe against Vyomi.
//
// Unmodified github.com/aws/aws-sdk-go-v2/service/elasticache with only
// BaseEndpoint overridden. One [PASS]/[FAIL] line per check; exit 1 on failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/elasticache"
	"github.com/aws/aws-sdk-go-v2/service/elasticache/types"
)

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fail++
	if detail != "" {
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	} else {
		fmt.Printf("[FAIL] %s\n", name)
	}
}

func step(name string, err error) bool {
	if err != nil {
		chk(name, false, err.Error())
		return false
	}
	chk(name, true, "")
	return true
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx,
		config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	ec := elasticache.NewFromConfig(cfg, func(o *elasticache.Options) { o.BaseEndpoint = aws.String(endpoint) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)
	sg, pg, cl, rg, snap := "gsg-"+sfx, "gpg-"+sfx, "gcache-"+sfx, "grg-"+sfx, "gsnap-"+sfx

	_, err = ec.CreateCacheSubnetGroup(ctx, &elasticache.CreateCacheSubnetGroupInput{
		CacheSubnetGroupName: &sg, CacheSubnetGroupDescription: aws.String("go test"),
		SubnetIds: []string{"subnet-aaa111", "subnet-bbb222"}})
	step("CreateCacheSubnetGroup", err)
	sgs, err := ec.DescribeCacheSubnetGroups(ctx, &elasticache.DescribeCacheSubnetGroupsInput{CacheSubnetGroupName: &sg})
	if step("DescribeCacheSubnetGroups", err) {
		chk("subnet group has 2 subnets", len(sgs.CacheSubnetGroups) == 1 && len(sgs.CacheSubnetGroups[0].Subnets) == 2, "")
	}

	_, err = ec.CreateCacheParameterGroup(ctx, &elasticache.CreateCacheParameterGroupInput{
		CacheParameterGroupName: &pg, CacheParameterGroupFamily: aws.String("valkey8"), Description: aws.String("go test")})
	step("CreateCacheParameterGroup", err)
	_, err = ec.ModifyCacheParameterGroup(ctx, &elasticache.ModifyCacheParameterGroupInput{
		CacheParameterGroupName: &pg,
		ParameterNameValues:     []types.ParameterNameValue{{ParameterName: aws.String("timeout"), ParameterValue: aws.String("45")}}})
	step("ModifyCacheParameterGroup", err)
	pr, err := ec.DescribeCacheParameters(ctx, &elasticache.DescribeCacheParametersInput{CacheParameterGroupName: &pg})
	if step("DescribeCacheParameters", err) {
		found := false
		for _, p := range pr.Parameters {
			if aws.ToString(p.ParameterName) == "timeout" && aws.ToString(p.ParameterValue) == "45" {
				found = true
			}
		}
		chk("modified parameter reads back", found, "")
	}

	cc, err := ec.CreateCacheCluster(ctx, &elasticache.CreateCacheClusterInput{
		CacheClusterId: &cl, Engine: aws.String("valkey"), CacheNodeType: aws.String("cache.t3.micro"),
		NumCacheNodes: aws.Int32(1), CacheSubnetGroupName: &sg, CacheParameterGroupName: &pg,
		Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("test")}}})
	if step("CreateCacheCluster", err) {
		chk("cluster is available", aws.ToString(cc.CacheCluster.CacheClusterStatus) == "available", "")
	}
	dc, err := ec.DescribeCacheClusters(ctx, &elasticache.DescribeCacheClustersInput{CacheClusterId: &cl, ShowCacheNodeInfo: aws.Bool(true)})
	arn := ""
	if step("DescribeCacheClusters", err) && len(dc.CacheClusters) == 1 {
		c := dc.CacheClusters[0]
		arn = aws.ToString(c.ARN)
		chk("cluster fields (engine/version/endpoint/arn)", aws.ToString(c.Engine) == "valkey" && aws.ToString(c.EngineVersion) != "" &&
			len(c.CacheNodes) == 1 && c.CacheNodes[0].Endpoint != nil && aws.ToInt32(c.CacheNodes[0].Endpoint.Port) > 0 && arn != "", "")
		chk("cluster uses requested subnet + parameter group", aws.ToString(c.CacheSubnetGroupName) == sg &&
			aws.ToString(c.CacheParameterGroup.CacheParameterGroupName) == pg, "")
	}

	_, err = ec.ModifyCacheCluster(ctx, &elasticache.ModifyCacheClusterInput{CacheClusterId: &cl,
		CacheNodeType: aws.String("cache.t3.small"), ApplyImmediately: aws.Bool(true)})
	step("ModifyCacheCluster (node type)", err)
	dc, err = ec.DescribeCacheClusters(ctx, &elasticache.DescribeCacheClustersInput{CacheClusterId: &cl})
	if step("DescribeCacheClusters after modify", err) {
		chk("node type changed", aws.ToString(dc.CacheClusters[0].CacheNodeType) == "cache.t3.small", "")
	}
	_, err = ec.RebootCacheCluster(ctx, &elasticache.RebootCacheClusterInput{CacheClusterId: &cl, CacheNodeIdsToReboot: []string{"0001"}})
	step("RebootCacheCluster", err)

	_, err = ec.AddTagsToResource(ctx, &elasticache.AddTagsToResourceInput{ResourceName: &arn,
		Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("platform")}}})
	step("AddTagsToResource", err)
	tg, err := ec.ListTagsForResource(ctx, &elasticache.ListTagsForResourceInput{ResourceName: &arn})
	if step("ListTagsForResource", err) {
		chk("both tags present", len(tg.TagList) == 2, "")
	}
	_, err = ec.RemoveTagsFromResource(ctx, &elasticache.RemoveTagsFromResourceInput{ResourceName: &arn, TagKeys: []string{"team"}})
	step("RemoveTagsFromResource", err)

	_, err = ec.CreateSnapshot(ctx, &elasticache.CreateSnapshotInput{SnapshotName: &snap, CacheClusterId: &cl})
	step("CreateSnapshot", err)
	sn, err := ec.DescribeSnapshots(ctx, &elasticache.DescribeSnapshotsInput{SnapshotName: &snap})
	if step("DescribeSnapshots", err) {
		chk("snapshot is available", len(sn.Snapshots) == 1 && aws.ToString(sn.Snapshots[0].SnapshotStatus) == "available", "")
	}

	rc, err := ec.CreateReplicationGroup(ctx, &elasticache.CreateReplicationGroupInput{ReplicationGroupId: &rg,
		ReplicationGroupDescription: aws.String("go rg"), Engine: aws.String("valkey"),
		CacheNodeType: aws.String("cache.t3.micro"), NumCacheClusters: aws.Int32(2), AutomaticFailoverEnabled: aws.Bool(true)})
	if step("CreateReplicationGroup", err) {
		g := rc.ReplicationGroup
		chk("replication group has 2 members + primary endpoint", len(g.MemberClusters) == 2 && len(g.NodeGroups) == 1 &&
			g.NodeGroups[0].PrimaryEndpoint != nil && aws.ToString(g.NodeGroups[0].PrimaryEndpoint.Address) != "", "")
	}
	rd, err := ec.DescribeReplicationGroups(ctx, &elasticache.DescribeReplicationGroupsInput{ReplicationGroupId: &rg})
	if step("DescribeReplicationGroups", err) {
		chk("replication group available", len(rd.ReplicationGroups) == 1 && aws.ToString(rd.ReplicationGroups[0].Status) == "available", "")
	}

	ev, err := ec.DescribeCacheEngineVersions(ctx, &elasticache.DescribeCacheEngineVersionsInput{Engine: aws.String("valkey")})
	if step("DescribeCacheEngineVersions", err) {
		chk("valkey versions listed", len(ev.CacheEngineVersions) > 0, "")
	}
	evs, err := ec.DescribeEvents(ctx, &elasticache.DescribeEventsInput{})
	if step("DescribeEvents", err) {
		chk("events recorded", len(evs.Events) > 0, "")
	}

	_, err = ec.DescribeCacheClusters(ctx, &elasticache.DescribeCacheClustersInput{CacheClusterId: aws.String("nope-" + sfx)})
	var nf *types.CacheClusterNotFoundFault
	chk("missing cluster -> CacheClusterNotFound", errors.As(err, &nf), fmt.Sprint(err))
	_, err = ec.CreateCacheCluster(ctx, &elasticache.CreateCacheClusterInput{CacheClusterId: &cl, Engine: aws.String("valkey")})
	var dup *types.CacheClusterAlreadyExistsFault
	chk("duplicate cluster -> CacheClusterAlreadyExists", errors.As(err, &dup), fmt.Sprint(err))

	_, err = ec.DeleteSnapshot(ctx, &elasticache.DeleteSnapshotInput{SnapshotName: &snap})
	step("DeleteSnapshot", err)
	_, err = ec.DeleteReplicationGroup(ctx, &elasticache.DeleteReplicationGroupInput{ReplicationGroupId: &rg})
	step("DeleteReplicationGroup", err)
	_, err = ec.DeleteCacheCluster(ctx, &elasticache.DeleteCacheClusterInput{CacheClusterId: &cl})
	step("DeleteCacheCluster", err)
	_, err = ec.DeleteCacheParameterGroup(ctx, &elasticache.DeleteCacheParameterGroupInput{CacheParameterGroupName: &pg})
	step("DeleteCacheParameterGroup", err)
	_, err = ec.DeleteCacheSubnetGroup(ctx, &elasticache.DeleteCacheSubnetGroupInput{CacheSubnetGroupName: &sg})
	step("DeleteCacheSubnetGroup", err)
	left, err := ec.DescribeCacheClusters(ctx, &elasticache.DescribeCacheClustersInput{})
	if step("DescribeCacheClusters after delete", err) {
		gone := true
		for _, c := range left.CacheClusters {
			if aws.ToString(c.CacheClusterId) == cl {
				gone = false
			}
		}
		chk("cluster gone", gone, "")
	}

	fmt.Printf("elasticache go: %d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
