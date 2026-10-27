// Real cloud.google.com/go/workflows (REST transport) conformance against Vyomi's Workflows API
// (the Go executions client is gRPC-only; executions are covered by the gcloud CLI suite). ENDPOINT (default http://127.0.0.1:9000),
// PROJECT. One [PASS]/[FAIL] line per check; exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	workflows "cloud.google.com/go/workflows/apiv1"
	"cloud.google.com/go/workflows/apiv1/workflowspb"
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

const src = "main:\n  steps:\n    - init:\n        assign:\n          - greeting: \"Hello from Go\"\n    - done:\n        return: ${greeting}\n"
const src2 = "main:\n  steps:\n    - done:\n        return: \"v2\"\n"

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	project := env("PROJECT", "go-wf-proj")
	region := "us-central1"
	fmt.Printf("== cloud.google.com/go/workflows (Go) against %s project=%s ==\n", endpoint, project)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	c, err := workflows.NewRESTClient(ctx, option.WithEndpoint(endpoint), option.WithoutAuthentication())
	if err != nil {
		fmt.Printf("[FAIL] client :: %v\n", err)
		os.Exit(1)
	}
	defer c.Close()

	parent := fmt.Sprintf("projects/%s/locations/%s", project, region)
	id := fmt.Sprintf("go-wf-%d", time.Now().UnixNano()%1000000)
	name := parent + "/workflows/" + id

	op, err := c.CreateWorkflow(ctx, &workflowspb.CreateWorkflowRequest{Parent: parent, WorkflowId: id, Workflow: &workflowspb.Workflow{
		Description: "created by the Go SDK", Labels: map[string]string{"env": "dev"},
		SourceCode: &workflowspb.Workflow_SourceContents{SourceContents: src},
	}})
	var created *workflowspb.Workflow
	if err == nil {
		created, err = op.Wait(ctx)
	}
	check("CreateWorkflow (LRO) -> Workflow ACTIVE with revision", err == nil && created.GetState() == workflowspb.Workflow_ACTIVE &&
		strings.HasPrefix(created.GetRevisionId(), "000001-") && created.GetName() == name, fmt.Sprintf("%v %v", err, created))

	_, err = c.CreateWorkflow(ctx, &workflowspb.CreateWorkflowRequest{Parent: parent, WorkflowId: id, Workflow: &workflowspb.Workflow{
		SourceCode: &workflowspb.Workflow_SourceContents{SourceContents: src}}})
	check("CreateWorkflow duplicate -> 409 ALREADY_EXISTS", err != nil && httpCode(err) == 409, fmt.Sprint(err))

	_, err = c.CreateWorkflow(ctx, &workflowspb.CreateWorkflowRequest{Parent: parent, WorkflowId: "1-bad", Workflow: &workflowspb.Workflow{
		SourceCode: &workflowspb.Workflow_SourceContents{SourceContents: src}}})
	check("CreateWorkflow bad id -> 400 INVALID_ARGUMENT", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	_, err = c.CreateWorkflow(ctx, &workflowspb.CreateWorkflowRequest{Parent: parent, WorkflowId: id + "-nosrc", Workflow: &workflowspb.Workflow{}})
	check("CreateWorkflow without source -> 400", err != nil && httpCode(err) == 400, fmt.Sprint(err))

	g, err := c.GetWorkflow(ctx, &workflowspb.GetWorkflowRequest{Name: name})
	check("GetWorkflow (ACTIVE, description, labels, source, service account)", err == nil && g.GetState() == workflowspb.Workflow_ACTIVE &&
		g.GetDescription() == "created by the Go SDK" && g.GetLabels()["env"] == "dev" && g.GetSourceContents() == src &&
		g.GetServiceAccount() != "", fmt.Sprintf("%v %v", err, g))

	_, err = c.GetWorkflow(ctx, &workflowspb.GetWorkflowRequest{Name: parent + "/workflows/missing-" + id})
	check("GetWorkflow missing -> 404 NOT_FOUND", err != nil && httpCode(err) == 404, fmt.Sprint(err))

	it := c.ListWorkflows(ctx, &workflowspb.ListWorkflowsRequest{Parent: parent})
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
	check("ListWorkflows contains the workflow", lerr == nil && found, fmt.Sprint(lerr))

	uop, err := c.UpdateWorkflow(ctx, &workflowspb.UpdateWorkflowRequest{
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"description", "labels"}},
		Workflow:   &workflowspb.Workflow{Name: name, Description: "updated", Labels: map[string]string{"team": "core"}}})
	var updated *workflowspb.Workflow
	if err == nil {
		updated, err = uop.Wait(ctx)
	}
	g2, _ := c.GetWorkflow(ctx, &workflowspb.GetWorkflowRequest{Name: name})
	check("UpdateWorkflow (description + labels) keeps the revision", err == nil && updated.GetDescription() == "updated" &&
		g2.GetLabels()["team"] == "core" && strings.HasPrefix(g2.GetRevisionId(), "000001-"), fmt.Sprintf("%v %v", err, g2))

	sop, err := c.UpdateWorkflow(ctx, &workflowspb.UpdateWorkflowRequest{
		UpdateMask: &fieldmaskpb.FieldMask{Paths: []string{"source_contents"}},
		Workflow:   &workflowspb.Workflow{Name: name, SourceCode: &workflowspb.Workflow_SourceContents{SourceContents: src2}}})
	var rev2 *workflowspb.Workflow
	if err == nil {
		rev2, err = sop.Wait(ctx)
	}
	check("UpdateWorkflow source bumps the revision", err == nil && strings.HasPrefix(rev2.GetRevisionId(), "000002-"), fmt.Sprintf("%v %v", err, rev2))

	dop, err := c.DeleteWorkflow(ctx, &workflowspb.DeleteWorkflowRequest{Name: name})
	if err == nil {
		err = dop.Wait(ctx)
	}
	_, gerr := c.GetWorkflow(ctx, &workflowspb.GetWorkflowRequest{Name: name})
	check("DeleteWorkflow (LRO) removes the workflow", err == nil && httpCode(gerr) == 404, fmt.Sprintf("%v / %v", err, gerr))

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
