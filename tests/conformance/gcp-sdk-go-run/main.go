// Real cloud.google.com/go/run (REST transport) conformance against Vyomi's Cloud Run Admin
// API v2. ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check;
// exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	iampb "cloud.google.com/go/iam/apiv1/iampb"
	run "cloud.google.com/go/run/apiv2"
	"cloud.google.com/go/run/apiv2/runpb"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/iterator"
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
	project := env("PROJECT", "go-run-proj")
	region := "us-central1"
	fmt.Printf("== cloud.google.com/go/run (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()
	opts := []option.ClientOption{option.WithEndpoint(endpoint), option.WithoutAuthentication()}

	sc, err := run.NewServicesRESTClient(ctx, opts...)
	if err != nil {
		fmt.Printf("[FAIL] services client :: %v\n", err)
		os.Exit(1)
	}
	defer sc.Close()
	rc, _ := run.NewRevisionsRESTClient(ctx, opts...)
	defer rc.Close()
	jc, _ := run.NewJobsRESTClient(ctx, opts...)
	defer jc.Close()
	ec, _ := run.NewExecutionsRESTClient(ctx, opts...)
	defer ec.Close()
	tc, _ := run.NewTasksRESTClient(ctx, opts...)
	defer tc.Close()

	parent := fmt.Sprintf("projects/%s/locations/%s", project, region)
	sid := fmt.Sprintf("go-svc-%d", time.Now().UnixNano()%1000000)
	sname := parent + "/services/" + sid

	// ── services ──────────────────────────────────────────────────────────
	op, err := sc.CreateService(ctx, &runpb.CreateServiceRequest{Parent: parent, ServiceId: sid, Service: &runpb.Service{
		Labels: map[string]string{"env": "dev"}, Description: "created by the Go SDK",
		Template: &runpb.RevisionTemplate{
			Containers: []*runpb.Container{{Image: "us-docker.pkg.dev/cloudrun/container/hello",
				Ports: []*runpb.ContainerPort{{ContainerPort: 8080}}}},
			Scaling: &runpb.RevisionScaling{MinInstanceCount: 0, MaxInstanceCount: 5},
		},
	}})
	var svc *runpb.Service
	if err == nil {
		svc, err = op.Wait(ctx)
	}
	check("CreateService -> LRO resolves to the Service", err == nil && svc.GetName() == sname, fmt.Sprintf("%v %v", err, svc))
	check("Service has URI, Ready condition, generation 1, latest ready revision", err == nil &&
		strings.HasSuffix(svc.GetUri(), ".run.app") && svc.GetTerminalCondition().GetState() == runpb.Condition_CONDITION_SUCCEEDED &&
		svc.GetGeneration() == 1 && svc.GetLatestReadyRevision() != "", fmt.Sprint(svc))

	_, err = sc.CreateService(ctx, &runpb.CreateServiceRequest{Parent: parent, ServiceId: sid, Service: &runpb.Service{
		Template: &runpb.RevisionTemplate{Containers: []*runpb.Container{{Image: "x"}}}}})
	check("CreateService duplicate -> 409 ALREADY_EXISTS", err != nil && httpCode(err) == 409, fmt.Sprint(err))
	_, err = sc.CreateService(ctx, &runpb.CreateServiceRequest{Parent: parent, ServiceId: "Bad_Name", Service: &runpb.Service{
		Template: &runpb.RevisionTemplate{Containers: []*runpb.Container{{Image: "x"}}}}})
	check("CreateService bad id -> 400 INVALID_ARGUMENT", err != nil && httpCode(err) == 400, fmt.Sprint(err))
	_, err = sc.CreateService(ctx, &runpb.CreateServiceRequest{Parent: parent, ServiceId: "noimg", Service: &runpb.Service{
		Template: &runpb.RevisionTemplate{Containers: []*runpb.Container{{}}}}})
	check("CreateService without image -> 400", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	got, err := sc.GetService(ctx, &runpb.GetServiceRequest{Name: sname})
	check("GetService round-trips template and labels", err == nil && got.GetLabels()["env"] == "dev" &&
		got.GetTemplate().GetContainers()[0].GetImage() == "us-docker.pkg.dev/cloudrun/container/hello" &&
		got.GetTemplate().GetScaling().GetMaxInstanceCount() == 5 && got.GetTemplate().GetTimeout().GetSeconds() == 300, fmt.Sprint(err, got))
	_, err = sc.GetService(ctx, &runpb.GetServiceRequest{Name: parent + "/services/nope"})
	check("GetService missing -> 404 NOT_FOUND", err != nil && httpCode(err) == 404, fmt.Sprint(err))

	found := false
	it := sc.ListServices(ctx, &runpb.ListServicesRequest{Parent: parent})
	for {
		s, e := it.Next()
		if e == iterator.Done {
			break
		}
		if e != nil {
			break
		}
		if s.GetName() == sname {
			found = true
		}
	}
	check("ListServices contains the service", found, "")

	uop, err := sc.UpdateService(ctx, &runpb.UpdateServiceRequest{Service: &runpb.Service{Name: sname,
		Template: &runpb.RevisionTemplate{Containers: []*runpb.Container{{Image: "us-docker.pkg.dev/cloudrun/container/hello:v2"}}}}})
	if err == nil {
		svc, err = uop.Wait(ctx)
	}
	check("UpdateService (new image) -> generation 2", err == nil && svc.GetGeneration() == 2 &&
		strings.HasSuffix(svc.GetTemplate().GetContainers()[0].GetImage(), ":v2"), fmt.Sprint(err, svc))

	var revs []*runpb.Revision
	rit := rc.ListRevisions(ctx, &runpb.ListRevisionsRequest{Parent: sname})
	for {
		r, e := rit.Next()
		if e != nil {
			break
		}
		revs = append(revs, r)
	}
	check("ListRevisions shows both revisions", len(revs) == 2, fmt.Sprint(len(revs)))
	if len(revs) == 2 {
		r, err := rc.GetRevision(ctx, &runpb.GetRevisionRequest{Name: revs[0].GetName()})
		check("GetRevision", err == nil && strings.HasPrefix(r.GetService(), parent), fmt.Sprint(err))
		old := revs[1]
		if old.GetName() == svc.GetLatestReadyRevision() {
			old = revs[0]
		}
		dop, err := rc.DeleteRevision(ctx, &runpb.DeleteRevisionRequest{Name: svc.GetLatestReadyRevision()})
		_ = dop
		check("DeleteRevision serving traffic -> 400 FAILED_PRECONDITION", err != nil && httpCode(err) == 400, fmt.Sprint(err))
		dop, err = rc.DeleteRevision(ctx, &runpb.DeleteRevisionRequest{Name: old.GetName()})
		if err == nil {
			_, err = dop.Wait(ctx)
		}
		check("DeleteRevision (old) succeeds", err == nil, fmt.Sprint(err))
	}

	pol, err := sc.GetIamPolicy(ctx, &iampb.GetIamPolicyRequest{Resource: sname})
	check("GetIamPolicy (empty)", err == nil && len(pol.GetBindings()) == 0, fmt.Sprint(err))
	pol, err = sc.SetIamPolicy(ctx, &iampb.SetIamPolicyRequest{Resource: sname, Policy: &iampb.Policy{
		Bindings: []*iampb.Binding{{Role: "roles/run.invoker", Members: []string{"allUsers"}}}}})
	check("SetIamPolicy allUsers invoker", err == nil && len(pol.GetBindings()) == 1, fmt.Sprint(err))
	pol, err = sc.GetIamPolicy(ctx, &iampb.GetIamPolicyRequest{Resource: sname})
	check("GetIamPolicy round-trips", err == nil && len(pol.GetBindings()) == 1 && pol.GetBindings()[0].GetMembers()[0] == "allUsers", fmt.Sprint(err))
	tp, err := sc.TestIamPermissions(ctx, &iampb.TestIamPermissionsRequest{Resource: sname, Permissions: []string{"run.services.get", "bogus.perm"}})
	check("TestIamPermissions filters unknown permissions", err == nil && len(tp.GetPermissions()) == 1, fmt.Sprint(err))

	// ── jobs / executions / tasks ─────────────────────────────────────────
	jid := fmt.Sprintf("go-job-%d", time.Now().UnixNano()%1000000)
	jname := parent + "/jobs/" + jid
	jop, err := jc.CreateJob(ctx, &runpb.CreateJobRequest{Parent: parent, JobId: jid, Job: &runpb.Job{
		Template: &runpb.ExecutionTemplate{TaskCount: 2, Template: &runpb.TaskTemplate{
			Retries:    &runpb.TaskTemplate_MaxRetries{MaxRetries: 1},
			Containers: []*runpb.Container{{Image: "us-docker.pkg.dev/cloudrun/container/job", Args: []string{"--once"}}}}}}})
	var job *runpb.Job
	if err == nil {
		job, err = jop.Wait(ctx)
	}
	check("CreateJob -> LRO resolves to the Job", err == nil && job.GetName() == jname && job.GetTemplate().GetTaskCount() == 2, fmt.Sprint(err, job))
	_, err = jc.CreateJob(ctx, &runpb.CreateJobRequest{Parent: parent, JobId: jid, Job: &runpb.Job{
		Template: &runpb.ExecutionTemplate{Template: &runpb.TaskTemplate{Containers: []*runpb.Container{{Image: "x"}}}}}})
	check("CreateJob duplicate -> 409", err != nil && httpCode(err) == 409, fmt.Sprint(err))
	jg, err := jc.GetJob(ctx, &runpb.GetJobRequest{Name: jname})
	check("GetJob", err == nil && jg.GetTemplate().GetTemplate().GetContainers()[0].GetArgs()[0] == "--once", fmt.Sprint(err))

	rop, err := jc.RunJob(ctx, &runpb.RunJobRequest{Name: jname})
	var ex *runpb.Execution
	if err == nil {
		ex, err = rop.Wait(ctx)
	}
	check("RunJob -> Execution (2 tasks succeeded)", err == nil && ex.GetTaskCount() == 2 && ex.GetSucceededCount() == 2, fmt.Sprint(err, ex))
	if ex != nil {
		eg, err := ec.GetExecution(ctx, &runpb.GetExecutionRequest{Name: ex.GetName()})
		check("GetExecution", err == nil && eg.GetJob() == jid, fmt.Sprint(err))
		n := 0
		xit := ec.ListExecutions(ctx, &runpb.ListExecutionsRequest{Parent: jname})
		for {
			if _, e := xit.Next(); e != nil {
				break
			}
			n++
		}
		check("ListExecutions", n == 1, fmt.Sprint(n))
		var tasks []*runpb.Task
		tit := tc.ListTasks(ctx, &runpb.ListTasksRequest{Parent: ex.GetName()})
		for {
			t, e := tit.Next()
			if e != nil {
				break
			}
			tasks = append(tasks, t)
		}
		check("ListTasks returns 2 completed tasks", len(tasks) == 2 && tasks[0].GetLastAttemptResult().GetStatus().GetCode() == 0, fmt.Sprint(len(tasks)))
		if len(tasks) > 0 {
			t, err := tc.GetTask(ctx, &runpb.GetTaskRequest{Name: tasks[0].GetName()})
			check("GetTask", err == nil && t.GetIndex() == 0, fmt.Sprint(err))
		}
		_, err = ec.CancelExecution(ctx, &runpb.CancelExecutionRequest{Name: ex.GetName()})
		check("CancelExecution on a completed execution -> 400 FAILED_PRECONDITION", err != nil && httpCode(err) == 400, fmt.Sprint(err))
		xop, err := ec.DeleteExecution(ctx, &runpb.DeleteExecutionRequest{Name: ex.GetName()})
		if err == nil {
			_, err = xop.Wait(ctx)
		}
		check("DeleteExecution", err == nil, fmt.Sprint(err))
	}
	uj, err := jc.UpdateJob(ctx, &runpb.UpdateJobRequest{Job: &runpb.Job{Name: jname, Labels: map[string]string{"team": "core"},
		Template: jg.GetTemplate()}})
	if err == nil {
		job, err = uj.Wait(ctx)
	}
	check("UpdateJob (labels) -> generation 2", err == nil && job.GetLabels()["team"] == "core" && job.GetGeneration() == 2, fmt.Sprint(err))
	jdel, err := jc.DeleteJob(ctx, &runpb.DeleteJobRequest{Name: jname})
	if err == nil {
		_, err = jdel.Wait(ctx)
	}
	_, gerr := jc.GetJob(ctx, &runpb.GetJobRequest{Name: jname})
	check("DeleteJob -> gone (404)", err == nil && httpCode(gerr) == 404, fmt.Sprint(err, gerr))

	// ── delete service ────────────────────────────────────────────────────
	dop, err := sc.DeleteService(ctx, &runpb.DeleteServiceRequest{Name: sname})
	if err == nil {
		svc, err = dop.Wait(ctx)
	}
	check("DeleteService -> LRO resolves to the deleted Service", err == nil && svc.GetName() == sname, fmt.Sprint(err))
	_, err = sc.GetService(ctx, &runpb.GetServiceRequest{Name: sname})
	check("deleted service is gone (404)", httpCode(err) == 404, fmt.Sprint(err))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
