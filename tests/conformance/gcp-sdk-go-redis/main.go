// Real cloud.google.com/go/redis (REST transport) conformance against Vyomi's Memorystore for
// Redis API. ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per
// check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	redis "cloud.google.com/go/redis/apiv1"
	"cloud.google.com/go/redis/apiv1/redispb"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/iterator"
	"google.golang.org/api/option"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
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
	project := env("PROJECT", "go-redis-proj")
	region := "us-central1"
	fmt.Printf("== cloud.google.com/go/redis (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	c, err := redis.NewCloudRedisRESTClient(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	defer c.Close()

	parent := fmt.Sprintf("projects/%s/locations/%s", project, region)
	id := fmt.Sprintf("go-redis-%d", time.Now().UnixNano()%1000000)
	name := parent + "/instances/" + id

	op, err := c.CreateInstance(ctx, &redispb.CreateInstanceRequest{Parent: parent, InstanceId: id, Instance: &redispb.Instance{
		DisplayName: "created by the Go SDK", Tier: redispb.Instance_BASIC, MemorySizeGb: 2,
		RedisVersion: "REDIS_7_0", Labels: map[string]string{"env": "dev"},
	}})
	var created *redispb.Instance
	if err == nil {
		created, err = op.Wait(ctx)
	}
	check("CreateInstance (LRO) -> Instance READY with host/port", err == nil && created.GetState() == redispb.Instance_READY &&
		created.GetHost() != "" && created.GetPort() == 6379 && created.GetName() == name, fmt.Sprintf("%v %v", err, created))

	_, err = c.CreateInstance(ctx, &redispb.CreateInstanceRequest{Parent: parent, InstanceId: id, Instance: &redispb.Instance{Tier: redispb.Instance_BASIC, MemorySizeGb: 1}})
	check("CreateInstance duplicate -> 409 ALREADY_EXISTS", err != nil && httpCode(err) == 409, fmt.Sprint(err))

	_, err = c.CreateInstance(ctx, &redispb.CreateInstanceRequest{Parent: parent, InstanceId: "Bad_Id", Instance: &redispb.Instance{Tier: redispb.Instance_BASIC, MemorySizeGb: 1}})
	check("CreateInstance bad id -> 400 INVALID_ARGUMENT", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	g, err := c.GetInstance(ctx, &redispb.GetInstanceRequest{Name: name})
	check("GetInstance (READY, 2 GB, BASIC, version, labels, node)", err == nil && g.GetState() == redispb.Instance_READY &&
		g.GetMemorySizeGb() == 2 && g.GetTier() == redispb.Instance_BASIC && g.GetRedisVersion() == "REDIS_7_0" &&
		g.GetLabels()["env"] == "dev" && len(g.GetNodes()) == 1 && g.GetDisplayName() == "created by the Go SDK", fmt.Sprintf("%v %v", err, g))

	_, err = c.GetInstance(ctx, &redispb.GetInstanceRequest{Name: parent + "/instances/missing-" + id})
	check("GetInstance missing -> 404 NOT_FOUND", err != nil && httpCode(err) == 404, fmt.Sprint(err))

	it := c.ListInstances(ctx, &redispb.ListInstancesRequest{Parent: parent})
	found := false
	var lerr error
	for {
		x, e := it.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			lerr = e
			break
		}
		found = found || x.GetName() == name
	}
	check("ListInstances contains the instance", lerr == nil && found, fmt.Sprint(lerr))

	uop, err := c.UpdateInstance(ctx, &redispb.UpdateInstanceRequest{
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"memory_size_gb", "labels"}},
		Instance:   &redispb.Instance{Name: name, MemorySizeGb: 5, Labels: map[string]string{"team": "core"}}})
	var updated *redispb.Instance
	if err == nil {
		updated, err = uop.Wait(ctx)
	}
	g2, _ := c.GetInstance(ctx, &redispb.GetInstanceRequest{Name: name})
	check("UpdateInstance (memory + labels) persisted", err == nil && updated.GetMemorySizeGb() == 5 && g2.GetMemorySizeGb() == 5 &&
		g2.GetLabels()["team"] == "core", fmt.Sprintf("%v %v", err, g2))

	_, err = c.UpdateInstance(ctx, &redispb.UpdateInstanceRequest{
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"tier"}}, Instance: &redispb.Instance{Name: name, Tier: redispb.Instance_STANDARD_HA}})
	check("UpdateInstance immutable field -> 400", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	_, err = c.FailoverInstance(ctx, &redispb.FailoverInstanceRequest{Name: name, DataProtectionMode: redispb.FailoverInstanceRequest_LIMITED_DATA_LOSS})
	check("FailoverInstance on BASIC -> 400 FAILED_PRECONDITION", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	haID := id + "-ha"
	haName := parent + "/instances/" + haID
	hop, err := c.CreateInstance(ctx, &redispb.CreateInstanceRequest{Parent: parent, InstanceId: haID, Instance: &redispb.Instance{
		Tier: redispb.Instance_STANDARD_HA, MemorySizeGb: 1, AuthEnabled: true, RedisVersion: "REDIS_6_X"}})
	var ha *redispb.Instance
	if err == nil {
		ha, err = hop.Wait(ctx)
	}
	check("CreateInstance STANDARD_HA (alt zone, 2 nodes, AUTH)", err == nil && ha.GetAlternativeLocationId() == region+"-b" &&
		len(ha.GetNodes()) == 2 && ha.GetAuthEnabled(), fmt.Sprintf("%v %v", err, ha))

	fop, err := c.FailoverInstance(ctx, &redispb.FailoverInstanceRequest{Name: haName, DataProtectionMode: redispb.FailoverInstanceRequest_LIMITED_DATA_LOSS})
	var failed *redispb.Instance
	if err == nil {
		failed, err = fop.Wait(ctx)
	}
	check("FailoverInstance swaps the primary zone", err == nil && failed.GetCurrentLocationId() == region+"-b", fmt.Sprintf("%v %v", err, failed))

	pop, err := c.UpgradeInstance(ctx, &redispb.UpgradeInstanceRequest{Name: haName, RedisVersion: "REDIS_7_2"})
	var up *redispb.Instance
	if err == nil {
		up, err = pop.Wait(ctx)
	}
	check("UpgradeInstance -> REDIS_7_2", err == nil && up.GetRedisVersion() == "REDIS_7_2", fmt.Sprintf("%v %v", err, up))

	as, err := c.GetInstanceAuthString(ctx, &redispb.GetInstanceAuthStringRequest{Name: haName})
	check("GetInstanceAuthString", err == nil && as.GetAuthString() != "", fmt.Sprint(err))
	_, err = c.GetInstanceAuthString(ctx, &redispb.GetInstanceAuthStringRequest{Name: name})
	check("GetInstanceAuthString without AUTH -> 400", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	eop, err := c.ExportInstance(ctx, &redispb.ExportInstanceRequest{Name: name, OutputConfig: &redispb.OutputConfig{
		Destination: &redispb.OutputConfig_GcsDestination{GcsDestination: &redispb.GcsDestination{Uri: "gs://go-redis-bkt/dump.rdb"}}}})
	if err == nil {
		_, err = eop.Wait(ctx)
	}
	iop, ierr := c.ImportInstance(ctx, &redispb.ImportInstanceRequest{Name: name, InputConfig: &redispb.InputConfig{
		Source: &redispb.InputConfig_GcsSource{GcsSource: &redispb.GcsSource{Uri: "gs://go-redis-bkt/dump.rdb"}}}})
	if ierr == nil {
		_, ierr = iop.Wait(ctx)
	}
	check("ExportInstance + ImportInstance (gs:// URIs)", err == nil && ierr == nil, fmt.Sprintf("%v / %v", err, ierr))

	_, derr := c.DeleteInstance(ctx, &redispb.DeleteInstanceRequest{Name: haName})
	dop, err := c.DeleteInstance(ctx, &redispb.DeleteInstanceRequest{Name: name})
	if err == nil {
		err = dop.Wait(ctx)
	}
	_, gerr := c.GetInstance(ctx, &redispb.GetInstanceRequest{Name: name})
	check("DeleteInstance (LRO) removes the instance", derr == nil && err == nil && httpCode(gerr) == 404, fmt.Sprintf("%v / %v / %v", derr, err, gerr))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
