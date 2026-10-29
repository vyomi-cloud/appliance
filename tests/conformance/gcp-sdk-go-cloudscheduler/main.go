// Real cloud.google.com/go/scheduler (REST transport) conformance against Vyomi's Cloud
// Scheduler API. ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line
// per check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	scheduler "cloud.google.com/go/scheduler/apiv1"
	"cloud.google.com/go/scheduler/apiv1/schedulerpb"
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
	project := env("PROJECT", "go-sched-proj")
	region := "us-central1"
	fmt.Printf("== cloud.google.com/go/scheduler (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	c, err := scheduler.NewCloudSchedulerRESTClient(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	defer c.Close()

	parent := fmt.Sprintf("projects/%s/locations/%s", project, region)
	id := fmt.Sprintf("go-job-%d", time.Now().UnixNano()%1000000)
	name := parent + "/jobs/" + id

	j, err := c.CreateJob(ctx, &schedulerpb.CreateJobRequest{Parent: parent, Job: &schedulerpb.Job{
		Name: name, Description: "created by the Go SDK", Schedule: "30 2 * * *", TimeZone: "Europe/London",
		Target: &schedulerpb.Job_HttpTarget{HttpTarget: &schedulerpb.HttpTarget{
			Uri: "https://example.com/hook", HttpMethod: schedulerpb.HttpMethod_PUT, Body: []byte(`{"k":"v"}`),
			Headers: map[string]string{"Content-Type": "application/json"}}},
		RetryConfig: &schedulerpb.RetryConfig{RetryCount: 3},
	}})
	check("CreateJob (http target)", err == nil && j.GetName() == name && j.GetState() == schedulerpb.Job_ENABLED &&
		j.GetTimeZone() == "Europe/London" && j.GetScheduleTime() != nil && j.GetHttpTarget().GetHttpMethod() == schedulerpb.HttpMethod_PUT,
		fmt.Sprintf("%v %v", err, j))

	_, err = c.CreateJob(ctx, &schedulerpb.CreateJobRequest{Parent: parent, Job: &schedulerpb.Job{
		Name: name, Schedule: "* * * * *",
		Target: &schedulerpb.Job_HttpTarget{HttpTarget: &schedulerpb.HttpTarget{Uri: "https://example.com/"}}}})
	check("CreateJob duplicate -> 409 ALREADY_EXISTS", err != nil && httpCode(err) == 409, fmt.Sprint(err))

	_, err = c.CreateJob(ctx, &schedulerpb.CreateJobRequest{Parent: parent, Job: &schedulerpb.Job{
		Name: name + "-bad", Schedule: "99 99 * * *",
		Target: &schedulerpb.Job_HttpTarget{HttpTarget: &schedulerpb.HttpTarget{Uri: "https://example.com/"}}}})
	check("CreateJob bad schedule -> 400 INVALID_ARGUMENT", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	g, err := c.GetJob(ctx, &schedulerpb.GetJobRequest{Name: name})
	check("GetJob", err == nil && g.GetDescription() == "created by the Go SDK" &&
		string(g.GetHttpTarget().GetBody()) == `{"k":"v"}` && g.GetHttpTarget().GetHeaders()["Content-Type"] == "application/json" &&
		g.GetRetryConfig().GetRetryCount() == 3, fmt.Sprintf("%v %v", err, g))

	_, err = c.GetJob(ctx, &schedulerpb.GetJobRequest{Name: parent + "/jobs/missing-" + id})
	check("GetJob missing -> 404 NOT_FOUND", err != nil && httpCode(err) == 404, fmt.Sprint(err))

	_, err = c.CreateJob(ctx, &schedulerpb.CreateJobRequest{Parent: parent, Job: &schedulerpb.Job{
		Name: name + "-ps", Schedule: "@hourly",
		Target: &schedulerpb.Job_PubsubTarget{PubsubTarget: &schedulerpb.PubsubTarget{
			TopicName: "projects/" + project + "/topics/t1", Data: []byte("tick"), Attributes: map[string]string{"a": "b"}}}}})
	check("CreateJob (pubsub target)", err == nil, fmt.Sprint(err))

	found := map[string]bool{}
	it := c.ListJobs(ctx, &schedulerpb.ListJobsRequest{Parent: parent, PageSize: 1})
	for {
		jb, e := it.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			err = e
			break
		}
		found[jb.GetName()] = true
	}
	check("ListJobs (paged)", found[name] && found[name+"-ps"], fmt.Sprintf("%v %v", err, found))

	u, err := c.UpdateJob(ctx, &schedulerpb.UpdateJobRequest{
		Job:        &schedulerpb.Job{Name: name, Schedule: "0 0 * * 0", Description: "updated"},
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"schedule", "description"}}})
	check("UpdateJob (patch)", err == nil && u.GetSchedule() == "0 0 * * 0" && u.GetDescription() == "updated" &&
		u.GetHttpTarget().GetUri() == "https://example.com/hook", fmt.Sprintf("%v %v", err, u))

	p, err := c.PauseJob(ctx, &schedulerpb.PauseJobRequest{Name: name})
	check("PauseJob", err == nil && p.GetState() == schedulerpb.Job_PAUSED, fmt.Sprintf("%v %v", err, p.GetState()))

	_, err = c.RunJob(ctx, &schedulerpb.RunJobRequest{Name: name})
	check("RunJob on paused job -> 400 FAILED_PRECONDITION", err != nil && httpCode(err) == 400 && strings.Contains(err.Error(), "not ENABLED"), fmt.Sprint(err))

	r, err := c.ResumeJob(ctx, &schedulerpb.ResumeJobRequest{Name: name})
	check("ResumeJob", err == nil && r.GetState() == schedulerpb.Job_ENABLED && r.GetScheduleTime() != nil, fmt.Sprintf("%v", err))

	rn, err := c.RunJob(ctx, &schedulerpb.RunJobRequest{Name: name})
	check("RunJob stamps lastAttemptTime", err == nil && rn.GetLastAttemptTime() != nil, fmt.Sprintf("%v", err))

	err = c.DeleteJob(ctx, &schedulerpb.DeleteJobRequest{Name: name})
	_ = c.DeleteJob(ctx, &schedulerpb.DeleteJobRequest{Name: name + "-ps"})
	_, gerr := c.GetJob(ctx, &schedulerpb.GetJobRequest{Name: name})
	check("DeleteJob", err == nil && httpCode(gerr) == 404, fmt.Sprintf("%v / %v", err, gerr))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
