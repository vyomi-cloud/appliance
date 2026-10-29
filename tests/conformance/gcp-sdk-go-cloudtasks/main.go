// Real cloud.google.com/go/cloudtasks (REST transport) conformance against Vyomi — only the
// endpoint is overridden. One [PASS]/[FAIL] line per check; non-zero exit on any failure.
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
package main

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	cloudtasks "cloud.google.com/go/cloudtasks/apiv2"
	taskspb "cloud.google.com/go/cloudtasks/apiv2/cloudtaskspb"
	"google.golang.org/api/iterator"
	"google.golang.org/api/option"
	"google.golang.org/genproto/googleapis/iam/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/fieldmaskpb"
	"google.golang.org/protobuf/types/known/timestamppb"
	"google.golang.org/api/googleapi"
	"errors"
)

var pass, fail int

func chk(name string, ok bool, detail string) bool {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
	} else {
		fail++
		fmt.Printf("[FAIL] %s :: %s\n", name, detail)
	}
	return ok
}

func must(name string, err error) bool {
	if err != nil {
		return chk(name, false, err.Error())
	}
	return chk(name, true, "")
}

// isCode reports whether err is a Cloud Tasks API error carrying the HTTP status.
func isHTTP(err error, code int) bool {
	var ge *googleapi.Error
	if errors.As(err, &ge) {
		return ge.Code == code
	}
	return false
}

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	project := os.Getenv("PROJECT")
	if project == "" {
		project = "cloudlearn"
	}
	ctx := context.Background()
	c, err := cloudtasks.NewRESTClient(ctx, option.WithEndpoint(ep), option.WithoutAuthentication())
	if err != nil {
		fmt.Println("[FAIL] NewRESTClient ::", err)
		os.Exit(1)
	}
	defer c.Close()

	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000)
	parent := "projects/" + project + "/locations/us-central1"
	qname := parent + "/queues/go-q-" + sfx

	// locations
	locs := c.ListLocations(ctx, nil)
	_ = locs
	// queues
	q, err := c.CreateQueue(ctx, &taskspb.CreateQueueRequest{Parent: parent, Queue: &taskspb.Queue{
		Name: qname,
		RateLimits: &taskspb.RateLimits{MaxDispatchesPerSecond: 50, MaxConcurrentDispatches: 10},
		RetryConfig: &taskspb.RetryConfig{MaxAttempts: 5, MinBackoff: durationpb.New(2 * time.Second), MaxBackoff: durationpb.New(60 * time.Second)},
	}})
	if must("CreateQueue", err) {
		chk("CreateQueue echoes the name and RUNNING state", q.Name == qname && q.State == taskspb.Queue_RUNNING, fmt.Sprint(q.Name, q.State))
		chk("CreateQueue keeps rate limits", q.RateLimits.MaxDispatchesPerSecond == 50 && q.RateLimits.MaxConcurrentDispatches == 10, q.RateLimits.String())
		chk("CreateQueue keeps retry config", q.RetryConfig.MaxAttempts == 5 && q.RetryConfig.MinBackoff.AsDuration() == 2*time.Second, q.RetryConfig.String())
	}
	_, err = c.CreateQueue(ctx, &taskspb.CreateQueueRequest{Parent: parent, Queue: &taskspb.Queue{Name: qname}})
	chk("CreateQueue duplicate → ALREADY_EXISTS (409)", isHTTP(err, 409), fmt.Sprint(err))
	_, err = c.CreateQueue(ctx, &taskspb.CreateQueueRequest{Parent: parent, Queue: &taskspb.Queue{Name: parent + "/queues/bad_name"}})
	chk("CreateQueue invalid id → INVALID_ARGUMENT (400)", isHTTP(err, 400), fmt.Sprint(err))

	got, err := c.GetQueue(ctx, &taskspb.GetQueueRequest{Name: qname})
	if must("GetQueue", err) {
		chk("GetQueue returns the queue", got.Name == qname, got.Name)
	}
	_, err = c.GetQueue(ctx, &taskspb.GetQueueRequest{Name: parent + "/queues/missing-" + sfx})
	chk("GetQueue missing → NOT_FOUND (404)", isHTTP(err, 404), fmt.Sprint(err))

	it := c.ListQueues(ctx, &taskspb.ListQueuesRequest{Parent: parent})
	found := false
	for {
		x, e := it.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			chk("ListQueues", false, e.Error())
			break
		}
		if x.Name == qname {
			found = true
		}
	}
	chk("ListQueues lists the new queue", found, "not listed")

	up, err := c.UpdateQueue(ctx, &taskspb.UpdateQueueRequest{
		Queue:      &taskspb.Queue{Name: qname, RateLimits: &taskspb.RateLimits{MaxDispatchesPerSecond: 7}},
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"rate_limits.max_dispatches_per_second"}},
	})
	if must("UpdateQueue", err) {
		chk("UpdateQueue applied the masked field", up.RateLimits.MaxDispatchesPerSecond == 7, up.RateLimits.String())
		chk("UpdateQueue left unmasked fields", up.RateLimits.MaxConcurrentDispatches == 10, up.RateLimits.String())
	}

	p, err := c.PauseQueue(ctx, &taskspb.PauseQueueRequest{Name: qname})
	if must("PauseQueue", err) {
		chk("PauseQueue → PAUSED", p.State == taskspb.Queue_PAUSED, p.State.String())
	}
	r, err := c.ResumeQueue(ctx, &taskspb.ResumeQueueRequest{Name: qname})
	if must("ResumeQueue", err) {
		chk("ResumeQueue → RUNNING", r.State == taskspb.Queue_RUNNING, r.State.String())
	}

	// IAM
	_, err = c.SetIamPolicy(ctx, &iam.SetIamPolicyRequest{Resource: qname, Policy: &iam.Policy{Bindings: []*iam.Binding{
		{Role: "roles/cloudtasks.enqueuer", Members: []string{"user:dev@example.com"}}}}})
	must("SetIamPolicy", err)
	pol, err := c.GetIamPolicy(ctx, &iam.GetIamPolicyRequest{Resource: qname})
	if must("GetIamPolicy", err) {
		chk("GetIamPolicy returns the binding", len(pol.Bindings) == 1 && pol.Bindings[0].Role == "roles/cloudtasks.enqueuer", pol.String())
	}
	perm, err := c.TestIamPermissions(ctx, &iam.TestIamPermissionsRequest{Resource: qname, Permissions: []string{"cloudtasks.tasks.create"}})
	if must("TestIamPermissions", err) {
		chk("TestIamPermissions grants the permission", len(perm.Permissions) == 1, perm.String())
	}

	// tasks
	t1, err := c.CreateTask(ctx, &taskspb.CreateTaskRequest{Parent: qname, Task: &taskspb.Task{
		MessageType: &taskspb.Task_HttpRequest{HttpRequest: &taskspb.HttpRequest{
			Url: "https://example.com/handler", HttpMethod: taskspb.HttpMethod_POST,
			Headers: map[string]string{"X-Test": "1"}, Body: []byte("hello-task")}},
		ScheduleTime: timestamppb.New(time.Now().Add(time.Hour)),
	}})
	var t1name string
	if must("CreateTask", err) {
		t1name = t1.Name
		chk("CreateTask assigns an id under the queue", strings.HasPrefix(t1.Name, qname+"/tasks/"), t1.Name)
		chk("CreateTask BASIC view hides the body", len(t1.GetHttpRequest().GetBody()) == 0, "body leaked")
		chk("CreateTask keeps method and URL", t1.GetHttpRequest().GetUrl() == "https://example.com/handler" && t1.GetHttpRequest().GetHttpMethod() == taskspb.HttpMethod_POST, t1.String())
	}
	named := qname + "/tasks/named-" + sfx
	_, err = c.CreateTask(ctx, &taskspb.CreateTaskRequest{Parent: qname, Task: &taskspb.Task{Name: named,
		MessageType: &taskspb.Task_HttpRequest{HttpRequest: &taskspb.HttpRequest{Url: "https://example.com/n"}},
		ScheduleTime: timestamppb.New(time.Now().Add(time.Hour))}})
	must("CreateTask with an explicit name", err)
	_, err = c.CreateTask(ctx, &taskspb.CreateTaskRequest{Parent: qname, Task: &taskspb.Task{Name: named,
		MessageType: &taskspb.Task_HttpRequest{HttpRequest: &taskspb.HttpRequest{Url: "https://example.com/n"}},
		ScheduleTime: timestamppb.New(time.Now().Add(time.Hour))}})
	chk("CreateTask duplicate name → ALREADY_EXISTS (409)", isHTTP(err, 409), fmt.Sprint(err))
	_, err = c.CreateTask(ctx, &taskspb.CreateTaskRequest{Parent: qname, Task: &taskspb.Task{
		MessageType: &taskspb.Task_HttpRequest{HttpRequest: &taskspb.HttpRequest{Url: "ftp://nope"}}}})
	chk("CreateTask bad URL → INVALID_ARGUMENT (400)", isHTTP(err, 400), fmt.Sprint(err))

	if t1name != "" {
		full, err := c.GetTask(ctx, &taskspb.GetTaskRequest{Name: t1name, ResponseView: taskspb.Task_FULL})
		if must("GetTask FULL", err) {
			chk("GetTask FULL returns the body", string(full.GetHttpRequest().GetBody()) == "hello-task", string(full.GetHttpRequest().GetBody()))
			chk("GetTask returns custom headers", full.GetHttpRequest().GetHeaders()["X-Test"] == "1", fmt.Sprint(full.GetHttpRequest().GetHeaders()))
		}
	}
	n := 0
	tit := c.ListTasks(ctx, &taskspb.ListTasksRequest{Parent: qname})
	for {
		_, e := tit.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			chk("ListTasks", false, e.Error())
			break
		}
		n++
	}
	chk("ListTasks lists both tasks", n == 2, fmt.Sprint(n))

	ran, err := c.RunTask(ctx, &taskspb.RunTaskRequest{Name: named})
	if must("RunTask", err) {
		chk("RunTask records a dispatch", ran.DispatchCount == 1, fmt.Sprint(ran.DispatchCount))
	}
	_, err = c.GetTask(ctx, &taskspb.GetTaskRequest{Name: named})
	chk("a completed task is removed → NOT_FOUND", isHTTP(err, 404), fmt.Sprint(err))
	if t1name != "" {
		must("DeleteTask", c.DeleteTask(ctx, &taskspb.DeleteTaskRequest{Name: t1name}))
		_, err = c.GetTask(ctx, &taskspb.GetTaskRequest{Name: t1name})
		chk("GetTask after delete → NOT_FOUND", isHTTP(err, 404), fmt.Sprint(err))
	}
	c.CreateTask(ctx, &taskspb.CreateTaskRequest{Parent: qname, Task: &taskspb.Task{
		MessageType: &taskspb.Task_HttpRequest{HttpRequest: &taskspb.HttpRequest{Url: "https://example.com/p"}},
		ScheduleTime: timestamppb.New(time.Now().Add(time.Hour))}})
	must("PurgeQueue", func() error { _, e := c.PurgeQueue(ctx, &taskspb.PurgeQueueRequest{Name: qname}); return e }())
	tit = c.ListTasks(ctx, &taskspb.ListTasksRequest{Parent: qname})
	_, e := tit.Next()
	chk("PurgeQueue empties the queue", e == iterator.Done, fmt.Sprint(e))

	must("DeleteQueue", c.DeleteQueue(ctx, &taskspb.DeleteQueueRequest{Name: qname}))
	_, err = c.GetQueue(ctx, &taskspb.GetQueueRequest{Name: qname})
	chk("GetQueue after delete → NOT_FOUND", isHTTP(err, 404), fmt.Sprint(err))

	_ = codes.OK
	_ = status.Code
	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
