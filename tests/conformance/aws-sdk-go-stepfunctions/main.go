// Real aws-sdk-go-v2 Step Functions conformance against Vyomi — only BaseEndpoint is overridden.
// One [PASS]/[FAIL] line per check; non-zero exit on any failure.
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
	"github.com/aws/aws-sdk-go-v2/service/sfn"
	"github.com/aws/aws-sdk-go-v2/service/sfn/types"
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

const role = "arn:aws:iam::000000000000:role/service-role/StepFunctions-ExecutionRole"
const def = `{"StartAt":"Add","States":{
 "Add":{"Type":"Pass","Result":{"sum":3},"ResultPath":"$.calc","Next":"Pick"},
 "Pick":{"Type":"Choice","Choices":[{"Variable":"$.go","BooleanEquals":true,"Next":"Ok"}],"Default":"Bad"},
 "Ok":{"Type":"Succeed"},
 "Bad":{"Type":"Fail","Error":"NotGo","Cause":"go was false"}}}`

func main() {
	ep := os.Getenv("ENDPOINT")
	if ep == "" {
		ep = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	c := sfn.NewFromConfig(cfg, func(o *sfn.Options) { o.BaseEndpoint = aws.String(ep) })
	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%100000)
	name := "go-sm-" + sfx

	sm, err := c.CreateStateMachine(ctx, &sfn.CreateStateMachineInput{
		Name: aws.String(name), Definition: aws.String(def), RoleArn: aws.String(role), Type: types.StateMachineTypeStandard,
		Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("test")}}})
	if !must("CreateStateMachine", err) {
		os.Exit(1)
	}
	arn := aws.ToString(sm.StateMachineArn)
	chk("CreateStateMachine returns an ARN + creationDate", strings.HasSuffix(arn, ":stateMachine:"+name) && sm.CreationDate != nil, arn)

	d, err := c.DescribeStateMachine(ctx, &sfn.DescribeStateMachineInput{StateMachineArn: &arn})
	if must("DescribeStateMachine", err) {
		chk("DescribeStateMachine fields", aws.ToString(d.Name) == name && d.Status == types.StateMachineStatusActive &&
			strings.Contains(aws.ToString(d.Definition), "Choice"), fmt.Sprint(d))
	}
	l, err := c.ListStateMachines(ctx, &sfn.ListStateMachinesInput{})
	found := false
	if err == nil {
		for _, s := range l.StateMachines {
			found = found || aws.ToString(s.StateMachineArn) == arn
		}
	}
	chk("ListStateMachines includes it", err == nil && found, fmt.Sprint(err))
	_, err = c.UpdateStateMachine(ctx, &sfn.UpdateStateMachineInput{StateMachineArn: &arn, RoleArn: aws.String(role + "2")})
	must("UpdateStateMachine", err)
	d, err = c.DescribeStateMachine(ctx, &sfn.DescribeStateMachineInput{StateMachineArn: &arn})
	chk("DescribeStateMachine shows the new role", err == nil && strings.HasSuffix(aws.ToString(d.RoleArn), "2"), fmt.Sprint(err))
	_, err = c.DescribeStateMachine(ctx, &sfn.DescribeStateMachineInput{StateMachineArn: aws.String(arn + "-nope")})
	var nf *types.StateMachineDoesNotExist
	chk("DescribeStateMachine unknown → StateMachineDoesNotExist", errors.As(err, &nf), fmt.Sprint(err))
	_, err = c.CreateStateMachine(ctx, &sfn.CreateStateMachineInput{Name: aws.String("bad-" + sfx),
		Definition: aws.String(`{"StartAt":"x","States":{}}`), RoleArn: aws.String(role)})
	var inv *types.InvalidDefinition
	chk("CreateStateMachine invalid definition → InvalidDefinition", errors.As(err, &inv), fmt.Sprint(err))

	ok, err := c.StartExecution(ctx, &sfn.StartExecutionInput{StateMachineArn: &arn, Name: aws.String("ok-" + sfx), Input: aws.String(`{"go":true}`)})
	if must("StartExecution", err) {
		e, err := c.DescribeExecution(ctx, &sfn.DescribeExecutionInput{ExecutionArn: ok.ExecutionArn})
		chk("DescribeExecution SUCCEEDED with ResultPath output", err == nil && e.Status == types.ExecutionStatusSucceeded &&
			strings.Contains(aws.ToString(e.Output), `"sum":3`), fmt.Sprint(e, err))
		h, err := c.GetExecutionHistory(ctx, &sfn.GetExecutionHistoryInput{ExecutionArn: ok.ExecutionArn})
		chk("GetExecutionHistory starts with ExecutionStarted, ends with ExecutionSucceeded", err == nil && len(h.Events) > 2 &&
			h.Events[0].Type == types.HistoryEventTypeExecutionStarted && h.Events[len(h.Events)-1].Type == types.HistoryEventTypeExecutionSucceeded, fmt.Sprint(err))
	}
	bad, err := c.StartExecution(ctx, &sfn.StartExecutionInput{StateMachineArn: &arn, Name: aws.String("bad-" + sfx), Input: aws.String(`{"go":false}`)})
	if must("StartExecution (failing path)", err) {
		e, err := c.DescribeExecution(ctx, &sfn.DescribeExecutionInput{ExecutionArn: bad.ExecutionArn})
		chk("Fail state → FAILED with error + cause", err == nil && e.Status == types.ExecutionStatusFailed &&
			aws.ToString(e.Error) == "NotGo" && aws.ToString(e.Cause) == "go was false", fmt.Sprint(e, err))
	}
	le, err := c.ListExecutions(ctx, &sfn.ListExecutionsInput{StateMachineArn: &arn, StatusFilter: types.ExecutionStatusFailed})
	chk("ListExecutions filtered by status", err == nil && len(le.Executions) == 1, fmt.Sprint(err))
	_, err = c.StartExecution(ctx, &sfn.StartExecutionInput{StateMachineArn: &arn, Name: aws.String("ok-" + sfx), Input: aws.String(`{"go":false}`)})
	var dup *types.ExecutionAlreadyExists
	chk("StartExecution duplicate name → ExecutionAlreadyExists", errors.As(err, &dup), fmt.Sprint(err))

	act, err := c.CreateActivity(ctx, &sfn.CreateActivityInput{Name: aws.String("go-act-" + sfx)})
	if must("CreateActivity", err) {
		adef := `{"StartAt":"W","States":{"W":{"Type":"Task","Resource":"` + aws.ToString(act.ActivityArn) + `","End":true}}}`
		asm, err := c.CreateStateMachine(ctx, &sfn.CreateStateMachineInput{Name: aws.String("go-act-sm-" + sfx), Definition: &adef, RoleArn: aws.String(role)})
		if must("CreateStateMachine (activity task)", err) {
			ae, err := c.StartExecution(ctx, &sfn.StartExecutionInput{StateMachineArn: asm.StateMachineArn, Input: aws.String(`{"job":7}`)})
			must("StartExecution (parks on activity)", err)
			e, _ := c.DescribeExecution(ctx, &sfn.DescribeExecutionInput{ExecutionArn: ae.ExecutionArn})
			chk("execution RUNNING while the activity task is pending", e != nil && e.Status == types.ExecutionStatusRunning, fmt.Sprint(e))
			t, err := c.GetActivityTask(ctx, &sfn.GetActivityTaskInput{ActivityArn: act.ActivityArn, WorkerName: aws.String("w1")})
			if chk("GetActivityTask returns token + input", err == nil && t.TaskToken != nil && strings.Contains(aws.ToString(t.Input), `"job":7`), fmt.Sprint(err)) {
				_, err = c.SendTaskSuccess(ctx, &sfn.SendTaskSuccessInput{TaskToken: t.TaskToken, Output: aws.String(`{"done":true}`)})
				must("SendTaskSuccess", err)
				e, _ = c.DescribeExecution(ctx, &sfn.DescribeExecutionInput{ExecutionArn: ae.ExecutionArn})
				chk("callback completes the execution", e != nil && e.Status == types.ExecutionStatusSucceeded, fmt.Sprint(e))
			}
			s, err := c.StartExecution(ctx, &sfn.StartExecutionInput{StateMachineArn: asm.StateMachineArn, Input: aws.String(`{}`)})
			if err == nil {
				_, err = c.StopExecution(ctx, &sfn.StopExecutionInput{ExecutionArn: s.ExecutionArn, Error: aws.String("E"), Cause: aws.String("because")})
				must("StopExecution", err)
				e, _ = c.DescribeExecution(ctx, &sfn.DescribeExecutionInput{ExecutionArn: s.ExecutionArn})
				chk("stopped execution is ABORTED", e != nil && e.Status == types.ExecutionStatusAborted, fmt.Sprint(e))
			}
			_, err = c.DeleteStateMachine(ctx, &sfn.DeleteStateMachineInput{StateMachineArn: asm.StateMachineArn})
			must("DeleteStateMachine (activity machine)", err)
		}
		_, err = c.DeleteActivity(ctx, &sfn.DeleteActivityInput{ActivityArn: act.ActivityArn})
		must("DeleteActivity", err)
	}

	ver, err := c.PublishStateMachineVersion(ctx, &sfn.PublishStateMachineVersionInput{StateMachineArn: &arn})
	if must("PublishStateMachineVersion", err) {
		lv, err := c.ListStateMachineVersions(ctx, &sfn.ListStateMachineVersionsInput{StateMachineArn: &arn})
		chk("ListStateMachineVersions", err == nil && len(lv.StateMachineVersions) == 1, fmt.Sprint(err))
		al, err := c.CreateStateMachineAlias(ctx, &sfn.CreateStateMachineAliasInput{Name: aws.String("prod"),
			RoutingConfiguration: []types.RoutingConfigurationListItem{{StateMachineVersionArn: ver.StateMachineVersionArn, Weight: 100}}})
		if must("CreateStateMachineAlias", err) {
			_, err = c.StartExecution(ctx, &sfn.StartExecutionInput{StateMachineArn: al.StateMachineAliasArn, Input: aws.String(`{"go":true}`)})
			must("StartExecution via alias", err)
			_, err = c.DeleteStateMachineAlias(ctx, &sfn.DeleteStateMachineAliasInput{StateMachineAliasArn: al.StateMachineAliasArn})
			must("DeleteStateMachineAlias", err)
		}
	}
	_, err = c.TagResource(ctx, &sfn.TagResourceInput{ResourceArn: &arn, Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("x")}}})
	must("TagResource", err)
	tg, err := c.ListTagsForResource(ctx, &sfn.ListTagsForResourceInput{ResourceArn: &arn})
	chk("ListTagsForResource", err == nil && len(tg.Tags) == 2, fmt.Sprint(err))
	_, err = c.UntagResource(ctx, &sfn.UntagResourceInput{ResourceArn: &arn, TagKeys: []string{"team"}})
	must("UntagResource", err)
	v, err := c.ValidateStateMachineDefinition(ctx, &sfn.ValidateStateMachineDefinitionInput{Definition: aws.String(`{"StartAt":"x","States":{}}`)})
	chk("ValidateStateMachineDefinition FAIL", err == nil && v.Result == types.ValidateStateMachineDefinitionResultCodeFail, fmt.Sprint(err))
	v, err = c.ValidateStateMachineDefinition(ctx, &sfn.ValidateStateMachineDefinitionInput{Definition: aws.String(def)})
	chk("ValidateStateMachineDefinition OK", err == nil && v.Result == types.ValidateStateMachineDefinitionResultCodeOk, fmt.Sprint(err))

	_, err = c.DeleteStateMachine(ctx, &sfn.DeleteStateMachineInput{StateMachineArn: &arn})
	must("DeleteStateMachine", err)
	_, err = c.DescribeStateMachine(ctx, &sfn.DescribeStateMachineInput{StateMachineArn: &arn})
	chk("DescribeStateMachine after delete → StateMachineDoesNotExist", errors.As(err, &nf), fmt.Sprint(err))

	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
