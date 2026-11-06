// Real aws-sdk-go-v2 conformance for Amazon ECS against the Vyomi appliance —
// only the endpoint is changed (BaseEndpoint). One [PASS]/[FAIL] line per check;
// exit 1 on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	"github.com/aws/aws-sdk-go-v2/service/ecs/types"
)

var fails int

func check(name string, err error, ok bool, detail string) {
	if err == nil && ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fails++
	if err != nil {
		detail = err.Error()
	}
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Printf("[FAIL] load config :: %v\n", err)
		os.Exit(1)
	}
	c := ecs.NewFromConfig(cfg, func(o *ecs.Options) { o.BaseEndpoint = aws.String(ep) })
	fmt.Printf("== aws-sdk-go-v2 ecs against %s ==\n", ep)

	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000000)
	cname, fam, svc := "go-smoke-"+sfx, "go-web-"+sfx, "go-svc-"+sfx
	net := &types.NetworkConfiguration{AwsvpcConfiguration: &types.AwsVpcConfiguration{Subnets: []string{"subnet-0a1b2c3d4e5f60718"}}}

	cc, err := c.CreateCluster(ctx, &ecs.CreateClusterInput{ClusterName: &cname,
		Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("test")}}})
	check("CreateCluster", err, err == nil && aws.ToString(cc.Cluster.ClusterName) == cname && aws.ToString(cc.Cluster.Status) == "ACTIVE", "unexpected cluster")
	arn := ""
	if cc != nil && cc.Cluster != nil {
		arn = aws.ToString(cc.Cluster.ClusterArn)
	}
	dc, err := c.DescribeClusters(ctx, &ecs.DescribeClustersInput{Clusters: []string{cname}, Include: []types.ClusterField{types.ClusterFieldTags}})
	check("DescribeClusters (with TAGS)", err, err == nil && len(dc.Clusters) == 1 && len(dc.Clusters[0].Tags) == 1, "cluster/tag missing")
	lc, err := c.ListClusters(ctx, &ecs.ListClustersInput{})
	check("ListClusters", err, err == nil && contains(lc.ClusterArns, arn), "arn not listed")
	_, err = c.UpdateCluster(ctx, &ecs.UpdateClusterInput{Cluster: &cname, Settings: []types.ClusterSetting{{Name: types.ClusterSettingNameContainerInsights, Value: aws.String("enabled")}}})
	check("UpdateCluster (containerInsights)", err, true, "")

	td, err := c.RegisterTaskDefinition(ctx, &ecs.RegisterTaskDefinitionInput{
		Family: &fam, Cpu: aws.String("256"), Memory: aws.String("512"), NetworkMode: types.NetworkModeAwsvpc,
		RequiresCompatibilities: []types.Compatibility{types.CompatibilityFargate},
		ContainerDefinitions: []types.ContainerDefinition{{Name: aws.String("web"), Image: aws.String("nginx:1.27"), Essential: aws.Bool(true),
			PortMappings: []types.PortMapping{{ContainerPort: aws.Int32(80)}}}}})
	check("RegisterTaskDefinition", err, err == nil && td.TaskDefinition.Revision == 1 && td.TaskDefinition.Status == types.TaskDefinitionStatusActive, "revision/status wrong")
	dt, err := c.DescribeTaskDefinition(ctx, &ecs.DescribeTaskDefinitionInput{TaskDefinition: &fam})
	check("DescribeTaskDefinition", err, err == nil && aws.ToString(dt.TaskDefinition.ContainerDefinitions[0].Image) == "nginx:1.27", "image mismatch")
	lt, err := c.ListTaskDefinitions(ctx, &ecs.ListTaskDefinitionsInput{FamilyPrefix: &fam})
	check("ListTaskDefinitions", err, err == nil && len(lt.TaskDefinitionArns) == 1, "expected 1 revision")

	cs, err := c.CreateService(ctx, &ecs.CreateServiceInput{Cluster: &cname, ServiceName: &svc, TaskDefinition: &fam,
		DesiredCount: aws.Int32(1), LaunchType: types.LaunchTypeFargate, NetworkConfiguration: net})
	check("CreateService", err, err == nil && aws.ToString(cs.Service.ServiceName) == svc && cs.Service.DesiredCount == 1, "service wrong")
	ds, err := c.DescribeServices(ctx, &ecs.DescribeServicesInput{Cluster: &cname, Services: []string{svc}})
	check("DescribeServices", err, err == nil && len(ds.Services) == 1 && aws.ToString(ds.Services[0].Status) == "ACTIVE", "service not ACTIVE")
	ls, err := c.ListServices(ctx, &ecs.ListServicesInput{Cluster: &cname})
	check("ListServices", err, err == nil && len(ls.ServiceArns) == 1, "expected 1 service")
	us, err := c.UpdateService(ctx, &ecs.UpdateServiceInput{Cluster: &cname, Service: &svc, DesiredCount: aws.Int32(2)})
	check("UpdateService (scale to 2)", err, err == nil && us.Service.DesiredCount == 2, "desiredCount not 2")

	rt, err := c.RunTask(ctx, &ecs.RunTaskInput{Cluster: &cname, TaskDefinition: &fam, LaunchType: types.LaunchTypeFargate, NetworkConfiguration: net})
	check("RunTask", err, err == nil && len(rt.Tasks) == 1 && len(rt.Failures) == 0, "no task started")
	taskArn := ""
	if rt != nil && len(rt.Tasks) > 0 {
		taskArn = aws.ToString(rt.Tasks[0].TaskArn)
	}
	lt2, err := c.ListTasks(ctx, &ecs.ListTasksInput{Cluster: &cname})
	check("ListTasks", err, err == nil && contains(lt2.TaskArns, taskArn), "task not listed")
	dts, err := c.DescribeTasks(ctx, &ecs.DescribeTasksInput{Cluster: &cname, Tasks: []string{taskArn}})
	check("DescribeTasks", err, err == nil && len(dts.Tasks) == 1 && aws.ToString(dts.Tasks[0].LastStatus) != "", "task/lastStatus missing")
	st, err := c.StopTask(ctx, &ecs.StopTaskInput{Cluster: &cname, Task: &taskArn, Reason: aws.String("smoke")})
	check("StopTask", err, err == nil && aws.ToString(st.Task.DesiredStatus) == "STOPPED", "desiredStatus not STOPPED")

	_, err = c.TagResource(ctx, &ecs.TagResourceInput{ResourceArn: &arn, Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("platform")}}})
	check("TagResource", err, true, "")
	tg, err := c.ListTagsForResource(ctx, &ecs.ListTagsForResourceInput{ResourceArn: &arn})
	check("ListTagsForResource", err, err == nil && len(tg.Tags) == 2, "expected 2 tags")
	_, err = c.UntagResource(ctx, &ecs.UntagResourceInput{ResourceArn: &arn, TagKeys: []string{"team"}})
	check("UntagResource", err, true, "")

	cp, err := c.PutClusterCapacityProviders(ctx, &ecs.PutClusterCapacityProvidersInput{Cluster: &cname,
		CapacityProviders: []string{"FARGATE", "FARGATE_SPOT"},
		DefaultCapacityProviderStrategy: []types.CapacityProviderStrategyItem{{CapacityProvider: aws.String("FARGATE"), Weight: 1}}})
	check("PutClusterCapacityProviders", err, err == nil && len(cp.Cluster.CapacityProviders) == 2, "providers not set")

	_, err = c.DescribeServices(ctx, &ecs.DescribeServicesInput{Cluster: aws.String("no-such-" + sfx), Services: []string{"x"}})
	var nf *types.ClusterNotFoundException
	check("missing cluster -> ClusterNotFoundException", nil, errors.As(err, &nf), fmt.Sprint(err))

	_, err = c.DeleteCluster(ctx, &ecs.DeleteClusterInput{Cluster: &cname})
	var inUse *types.ClusterContainsServicesException
	check("DeleteCluster with active service -> ClusterContainsServicesException", nil, errors.As(err, &inUse), fmt.Sprint(err))
	_, err = c.DeleteService(ctx, &ecs.DeleteServiceInput{Cluster: &cname, Service: &svc, Force: aws.Bool(true)})
	check("DeleteService (force)", err, true, "")
	dr, err := c.DeregisterTaskDefinition(ctx, &ecs.DeregisterTaskDefinitionInput{TaskDefinition: aws.String(fam + ":1")})
	check("DeregisterTaskDefinition", err, err == nil && dr.TaskDefinition.Status == types.TaskDefinitionStatusInactive, "not INACTIVE")
	dl, err := c.DeleteCluster(ctx, &ecs.DeleteClusterInput{Cluster: &cname})
	check("DeleteCluster", err, err == nil && aws.ToString(dl.Cluster.Status) == "INACTIVE", "not INACTIVE")
	lc, err = c.ListClusters(ctx, &ecs.ListClustersInput{})
	check("cluster gone after delete", err, err == nil && !contains(lc.ClusterArns, arn), "still listed")

	if fails > 0 {
		fmt.Printf("%d check(s) failed\n", fails)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}

func contains(xs []string, s string) bool {
	for _, x := range xs {
		if strings.EqualFold(x, s) {
			return true
		}
	}
	return false
}
