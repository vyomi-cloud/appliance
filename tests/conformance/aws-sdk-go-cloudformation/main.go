// Real aws-sdk-go-v2 CloudFormation conformance probe against Vyomi.
// Only the endpoint is overridden. Prints one [PASS]/[FAIL] line per check and
// exits non-zero on any failure.
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
	"github.com/aws/aws-sdk-go-v2/service/cloudformation"
	"github.com/aws/aws-sdk-go-v2/service/cloudformation/types"
	"github.com/aws/smithy-go"
)

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fail++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func code(err error) string {
	var ae smithy.APIError
	if errors.As(err, &ae) {
		return ae.ErrorCode()
	}
	if err != nil {
		return err.Error()
	}
	return ""
}

const tmplYAML = `AWSTemplateFormatVersion: "2010-09-09"
Description: go conformance stack
Parameters:
  Env:
    Type: String
    Default: dev
    AllowedValues: [dev, prod]
Conditions:
  IsProd: !Equals [!Ref Env, prod]
Resources:
  Bucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "${AWS::StackName}-${Env}-data"
  Queue:
    Type: AWS::SQS::Queue
    DependsOn: Bucket
    Properties:
      QueueName: !Join ["-", [!Ref "AWS::StackName", q]]
  ProdTopic:
    Type: AWS::SNS::Topic
    Condition: IsProd
Outputs:
  BucketArn:
    Value: !GetAtt Bucket.Arn
    Export:
      Name: !Sub "${AWS::StackName}-bucket-arn"
  QueueUrl:
    Value: !Ref Queue
`

const tmplIAM = `{"Resources":{"R":{"Type":"AWS::IAM::Role","Properties":{"AssumeRolePolicyDocument":{"Version":"2012-10-17","Statement":[]}}}}}`

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	cf := cloudformation.NewFromConfig(cfg, func(o *cloudformation.Options) { o.BaseEndpoint = aws.String(endpoint) })
	fmt.Printf("== aws-sdk-go-v2 cloudformation against %s ==\n", endpoint)

	name := fmt.Sprintf("go-cfn-%d", time.Now().UnixNano()%1000000000)

	v, err := cf.ValidateTemplate(ctx, &cloudformation.ValidateTemplateInput{TemplateBody: aws.String(tmplYAML)})
	chk("ValidateTemplate lists the Env parameter", err == nil && len(v.Parameters) == 1 && aws.ToString(v.Parameters[0].ParameterKey) == "Env", fmt.Sprint(err))

	_, err = cf.ValidateTemplate(ctx, &cloudformation.ValidateTemplateInput{TemplateBody: aws.String("{not json")})
	chk("ValidateTemplate rejects a malformed template (ValidationError)", code(err) == "ValidationError", code(err))

	cs, err := cf.CreateStack(ctx, &cloudformation.CreateStackInput{
		StackName: aws.String(name), TemplateBody: aws.String(tmplYAML),
		Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("platform")}},
	})
	chk("CreateStack returns a StackId", err == nil && strings.Contains(aws.ToString(cs.StackId), ":stack/"+name+"/"), fmt.Sprint(err))

	d, err := cf.DescribeStacks(ctx, &cloudformation.DescribeStacksInput{StackName: aws.String(name)})
	ok := err == nil && len(d.Stacks) == 1 && d.Stacks[0].StackStatus == types.StackStatusCreateComplete
	chk("DescribeStacks → CREATE_COMPLETE", ok, fmt.Sprint(err))
	if ok {
		st := d.Stacks[0]
		outs := map[string]string{}
		for _, o := range st.Outputs {
			outs[aws.ToString(o.OutputKey)] = aws.ToString(o.OutputValue)
		}
		chk("outputs resolved (GetAtt/Ref/Sub)", outs["BucketArn"] == "arn:aws:s3:::"+name+"-dev-data" && strings.HasSuffix(outs["QueueUrl"], "/"+name+"-q"), fmt.Sprint(outs))
		chk("parameter default recorded", len(st.Parameters) == 1 && aws.ToString(st.Parameters[0].ParameterValue) == "dev", fmt.Sprint(st.Parameters))
		chk("tags kept", len(st.Tags) == 1 && aws.ToString(st.Tags[0].Value) == "platform", fmt.Sprint(st.Tags))
	}

	r, err := cf.ListStackResources(ctx, &cloudformation.ListStackResourcesInput{StackName: aws.String(name)})
	chk("ListStackResources → 2 resources (condition false skips the topic)", err == nil && len(r.StackResourceSummaries) == 2, fmt.Sprint(err))
	rd, err := cf.DescribeStackResource(ctx, &cloudformation.DescribeStackResourceInput{StackName: aws.String(name), LogicalResourceId: aws.String("Bucket")})
	chk("DescribeStackResource Bucket physical id", err == nil && aws.ToString(rd.StackResourceDetail.PhysicalResourceId) == name+"-dev-data", fmt.Sprint(err))
	rs, err := cf.DescribeStackResources(ctx, &cloudformation.DescribeStackResourcesInput{StackName: aws.String(name)})
	chk("DescribeStackResources", err == nil && len(rs.StackResources) == 2, fmt.Sprint(err))

	ev, err := cf.DescribeStackEvents(ctx, &cloudformation.DescribeStackEventsInput{StackName: aws.String(name)})
	hasDone := false
	if err == nil {
		for _, e := range ev.StackEvents {
			if aws.ToString(e.LogicalResourceId) == name && e.ResourceStatus == types.ResourceStatusCreateComplete {
				hasDone = true
			}
		}
	}
	chk("DescribeStackEvents has the stack CREATE_COMPLETE event", hasDone, fmt.Sprint(err))

	gt, err := cf.GetTemplate(ctx, &cloudformation.GetTemplateInput{StackName: aws.String(name)})
	chk("GetTemplate returns the template body", err == nil && strings.Contains(aws.ToString(gt.TemplateBody), "go conformance stack"), fmt.Sprint(err))
	ts, err := cf.GetTemplateSummary(ctx, &cloudformation.GetTemplateSummaryInput{StackName: aws.String(name)})
	chk("GetTemplateSummary lists resource types", err == nil && len(ts.ResourceTypes) == 3, fmt.Sprint(err))

	ex, err := cf.ListExports(ctx, &cloudformation.ListExportsInput{})
	found := false
	if err == nil {
		for _, e := range ex.Exports {
			if aws.ToString(e.Name) == name+"-bucket-arn" {
				found = true
			}
		}
	}
	chk("ListExports shows the stack export", found, fmt.Sprint(err))

	_, err = cf.CreateStack(ctx, &cloudformation.CreateStackInput{StackName: aws.String(name), TemplateBody: aws.String(tmplYAML)})
	chk("duplicate CreateStack → AlreadyExistsException", code(err) == "AlreadyExistsException", code(err))

	_, err = cf.UpdateStack(ctx, &cloudformation.UpdateStackInput{StackName: aws.String(name), TemplateBody: aws.String(tmplYAML)})
	chk("UpdateStack with no change → ValidationError", code(err) == "ValidationError" && strings.Contains(fmt.Sprint(err), "No updates"), code(err))

	_, err = cf.UpdateStack(ctx, &cloudformation.UpdateStackInput{StackName: aws.String(name), TemplateBody: aws.String(tmplYAML),
		Parameters: []types.Parameter{{ParameterKey: aws.String("Env"), ParameterValue: aws.String("prod")}}})
	chk("UpdateStack Env=prod", err == nil, fmt.Sprint(err))
	d, err = cf.DescribeStacks(ctx, &cloudformation.DescribeStacksInput{StackName: aws.String(name)})
	chk("stack is UPDATE_COMPLETE with the prod topic created", err == nil && d.Stacks[0].StackStatus == types.StackStatusUpdateComplete, fmt.Sprint(err))
	r, _ = cf.ListStackResources(ctx, &cloudformation.ListStackResourcesInput{StackName: aws.String(name)})
	chk("3 resources after update", r != nil && len(r.StackResourceSummaries) == 3, "")

	csn := "go-cs-1"
	_, err = cf.CreateChangeSet(ctx, &cloudformation.CreateChangeSetInput{StackName: aws.String(name), ChangeSetName: aws.String(csn),
		TemplateBody: aws.String(tmplYAML), Parameters: []types.Parameter{{ParameterKey: aws.String("Env"), ParameterValue: aws.String("dev")}}})
	chk("CreateChangeSet (UPDATE)", err == nil, fmt.Sprint(err))
	dcs, err := cf.DescribeChangeSet(ctx, &cloudformation.DescribeChangeSetInput{StackName: aws.String(name), ChangeSetName: aws.String(csn)})
	chk("DescribeChangeSet shows Remove/Modify changes", err == nil && dcs.Status == types.ChangeSetStatusCreateComplete && len(dcs.Changes) >= 1, fmt.Sprint(err))
	lcs, err := cf.ListChangeSets(ctx, &cloudformation.ListChangeSetsInput{StackName: aws.String(name)})
	chk("ListChangeSets", err == nil && len(lcs.Summaries) == 1, fmt.Sprint(err))
	_, err = cf.ExecuteChangeSet(ctx, &cloudformation.ExecuteChangeSetInput{StackName: aws.String(name), ChangeSetName: aws.String(csn)})
	chk("ExecuteChangeSet", err == nil, fmt.Sprint(err))
	d, _ = cf.DescribeStacks(ctx, &cloudformation.DescribeStacksInput{StackName: aws.String(name)})
	r, _ = cf.ListStackResources(ctx, &cloudformation.ListStackResourcesInput{StackName: aws.String(name)})
	chk("change set applied (topic removed again)", d != nil && d.Stacks[0].StackStatus == types.StackStatusUpdateComplete && r != nil && len(r.StackResourceSummaries) == 2, "")

	_, err = cf.UpdateTerminationProtection(ctx, &cloudformation.UpdateTerminationProtectionInput{StackName: aws.String(name), EnableTerminationProtection: aws.Bool(true)})
	chk("UpdateTerminationProtection on", err == nil, fmt.Sprint(err))
	_, err = cf.DeleteStack(ctx, &cloudformation.DeleteStackInput{StackName: aws.String(name)})
	chk("DeleteStack blocked by termination protection", code(err) == "ValidationError", code(err))
	_, _ = cf.UpdateTerminationProtection(ctx, &cloudformation.UpdateTerminationProtectionInput{StackName: aws.String(name), EnableTerminationProtection: aws.Bool(false)})

	_, err = cf.CreateStack(ctx, &cloudformation.CreateStackInput{StackName: aws.String(name + "-iam"), TemplateBody: aws.String(tmplIAM)})
	chk("IAM resources without capabilities → InsufficientCapabilitiesException", code(err) == "InsufficientCapabilitiesException", code(err))

	_, err = cf.DeleteStack(ctx, &cloudformation.DeleteStackInput{StackName: aws.String(name)})
	chk("DeleteStack", err == nil, fmt.Sprint(err))
	_, err = cf.DescribeStacks(ctx, &cloudformation.DescribeStacksInput{StackName: aws.String(name)})
	chk("DescribeStacks after delete → ValidationError (does not exist)", code(err) == "ValidationError" && strings.Contains(fmt.Sprint(err), "does not exist"), code(err))
	ls, err := cf.ListStacks(ctx, &cloudformation.ListStacksInput{StackStatusFilter: []types.StackStatus{types.StackStatusDeleteComplete}})
	gone := false
	if err == nil {
		for _, s := range ls.StackSummaries {
			if aws.ToString(s.StackName) == name {
				gone = true
			}
		}
	}
	chk("ListStacks(DELETE_COMPLETE) keeps the deleted stack", gone, fmt.Sprint(err))

	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
