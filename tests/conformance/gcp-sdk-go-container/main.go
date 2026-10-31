// Real cloud.google.com/go/container (REST transport) conformance against Vyomi's Kubernetes
// Engine API. ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per
// check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	container "cloud.google.com/go/container/apiv1"
	"cloud.google.com/go/container/apiv1/containerpb"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/option"
)

var pass, fail int

func check(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
	} else {
		fail++
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	}
}

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func httpCode(err error) int {
	var ge *googleapi.Error
	if errors.As(err, &ge) {
		return ge.Code
	}
	return 0
}

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "vyomi-project")
	region := "us-central1"
	fmt.Printf("== cloud.google.com/go/container (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	c, err := container.NewClusterManagerRESTClient(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	defer c.Close()

	parent := fmt.Sprintf("projects/%s/locations/%s", project, region)
	id := fmt.Sprintf("go-gke-%d", time.Now().UnixNano()%1000000)
	name := parent + "/clusters/" + id

	op, err := c.CreateCluster(ctx, &containerpb.CreateClusterRequest{Parent: parent, Cluster: &containerpb.Cluster{
		Name: id, Description: "created by the Go SDK",
		NodePools: []*containerpb.NodePool{{Name: "default-pool", InitialNodeCount: 2,
			Config: &containerpb.NodeConfig{MachineType: "e2-standard-4"}}},
		ReleaseChannel: &containerpb.ReleaseChannel{Channel: containerpb.ReleaseChannel_STABLE},
	}})
	check("CreateCluster -> CREATE_CLUSTER operation, DONE", err == nil &&
		op.GetOperationType() == containerpb.Operation_CREATE_CLUSTER && op.GetStatus() == containerpb.Operation_DONE, fmt.Sprintf("%v %v", err, op))

	_, err = c.CreateCluster(ctx, &containerpb.CreateClusterRequest{Parent: parent, Cluster: &containerpb.Cluster{Name: id, InitialNodeCount: 1}})
	check("CreateCluster duplicate -> 409 ALREADY_EXISTS", err != nil && httpCode(err) == 409, fmt.Sprint(err))

	_, err = c.CreateCluster(ctx, &containerpb.CreateClusterRequest{Parent: parent, Cluster: &containerpb.Cluster{Name: "Bad_Name", InitialNodeCount: 1}})
	check("CreateCluster bad name -> 400 INVALID_ARGUMENT", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	g, err := c.GetCluster(ctx, &containerpb.GetClusterRequest{Name: name})
	check("GetCluster (RUNNING, endpoint, channel, machine type)", err == nil && g.GetStatus() == containerpb.Cluster_RUNNING &&
		g.GetEndpoint() != "" && g.GetReleaseChannel().GetChannel() == containerpb.ReleaseChannel_STABLE &&
		len(g.GetNodePools()) == 1 && g.GetNodePools()[0].GetConfig().GetMachineType() == "e2-standard-4" &&
		g.GetCurrentNodeCount() == 2, fmt.Sprintf("%v %v", err, g))

	_, err = c.GetCluster(ctx, &containerpb.GetClusterRequest{Name: parent + "/clusters/missing-" + id})
	check("GetCluster missing -> 404 NOT_FOUND", err != nil && httpCode(err) == 404, fmt.Sprint(err))

	l, err := c.ListClusters(ctx, &containerpb.ListClustersRequest{Parent: parent})
	found := false
	for _, x := range l.GetClusters() {
		found = found || x.GetName() == id
	}
	check("ListClusters contains the cluster", err == nil && found, fmt.Sprint(err))

	_, err = c.CreateNodePool(ctx, &containerpb.CreateNodePoolRequest{Parent: name, NodePool: &containerpb.NodePool{
		Name: "pool-2", InitialNodeCount: 1, Config: &containerpb.NodeConfig{MachineType: "e2-medium"},
		Autoscaling: &containerpb.NodePoolAutoscaling{Enabled: true, MinNodeCount: 1, MaxNodeCount: 5}}})
	np, gerr := c.GetNodePool(ctx, &containerpb.GetNodePoolRequest{Name: name + "/nodePools/pool-2"})
	check("CreateNodePool + GetNodePool (autoscaling)", err == nil && gerr == nil && np.GetAutoscaling().GetMaxNodeCount() == 5,
		fmt.Sprintf("%v %v %v", err, gerr, np))

	_, err = c.SetNodePoolSize(ctx, &containerpb.SetNodePoolSizeRequest{Name: name + "/nodePools/default-pool", NodeCount: 5})
	np, _ = c.GetNodePool(ctx, &containerpb.GetNodePoolRequest{Name: name + "/nodePools/default-pool"})
	check("SetNodePoolSize persisted", err == nil && np.GetInitialNodeCount() == 5, fmt.Sprintf("%v %v", err, np))

	pools, err := c.ListNodePools(ctx, &containerpb.ListNodePoolsRequest{Parent: name})
	check("ListNodePools (2 pools)", err == nil && len(pools.GetNodePools()) == 2, fmt.Sprint(err))

	_, err = c.SetLabels(ctx, &containerpb.SetLabelsRequest{Name: name, ResourceLabels: map[string]string{"team": "core"}, LabelFingerprint: g.GetLabelFingerprint()})
	g2, _ := c.GetCluster(ctx, &containerpb.GetClusterRequest{Name: name})
	check("SetLabels persisted", err == nil && g2.GetResourceLabels()["team"] == "core", fmt.Sprintf("%v %v", err, g2.GetResourceLabels()))

	_, err = c.SetLabels(ctx, &containerpb.SetLabelsRequest{Name: name, ResourceLabels: map[string]string{"x": "y"}, LabelFingerprint: "stale"})
	check("SetLabels stale fingerprint -> 409", err != nil && httpCode(err) == 409, fmt.Sprint(err))

	uop, err := c.UpdateCluster(ctx, &containerpb.UpdateClusterRequest{Name: name,
		Update: &containerpb.ClusterUpdate{DesiredMasterVersion: "1.31"}})
	g3, _ := c.GetCluster(ctx, &containerpb.GetClusterRequest{Name: name})
	check("UpdateCluster (upgrade master)", err == nil && uop.GetOperationType() == containerpb.Operation_UPGRADE_MASTER &&
		strings.HasPrefix(g3.GetCurrentMasterVersion(), "1.31"), fmt.Sprintf("%v %v", err, g3.GetCurrentMasterVersion()))

	ops, err := c.ListOperations(ctx, &containerpb.ListOperationsRequest{Parent: parent})
	ok := err == nil && len(ops.GetOperations()) > 0
	if ok {
		got, gerr := c.GetOperation(ctx, &containerpb.GetOperationRequest{Name: parent + "/operations/" + ops.GetOperations()[0].GetName()})
		ok = gerr == nil && got.GetStatus() == containerpb.Operation_DONE
	}
	check("ListOperations + GetOperation", ok, fmt.Sprint(err))

	sc, err := c.GetServerConfig(ctx, &containerpb.GetServerConfigRequest{Name: parent})
	check("GetServerConfig", err == nil && sc.GetDefaultClusterVersion() != "" && len(sc.GetValidMasterVersions()) > 0, fmt.Sprint(err))

	_, err = c.DeleteNodePool(ctx, &containerpb.DeleteNodePoolRequest{Name: name + "/nodePools/pool-2"})
	dop, derr := c.DeleteCluster(ctx, &containerpb.DeleteClusterRequest{Name: name})
	_, gerr = c.GetCluster(ctx, &containerpb.GetClusterRequest{Name: name})
	check("DeleteNodePool + DeleteCluster", err == nil && derr == nil && dop.GetOperationType() == containerpb.Operation_DELETE_CLUSTER && httpCode(gerr) == 404,
		fmt.Sprintf("%v / %v / %v", err, derr, gerr))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
