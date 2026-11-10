// Real aws-sdk-go-v2 CloudWatch Logs conformance against Vyomi (BaseEndpoint override only).
//
//	ENDPOINT=http://127.0.0.1:9000 GOFLAGS=-mod=mod go run .
//
// One [PASS]/[FAIL] line per check; exits non-zero on any failure.
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
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs/types"
)

var failed int

func check(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	failed++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Printf("[FAIL] load config :: %v\n", err)
		os.Exit(1)
	}
	c := cloudwatchlogs.NewFromConfig(cfg, func(o *cloudwatchlogs.Options) { o.BaseEndpoint = aws.String(endpoint) })

	group := fmt.Sprintf("/vyomi/go-%d", time.Now().UnixNano())
	stream := "worker-1"
	now := time.Now().UnixMilli()

	_, err = c.CreateLogGroup(ctx, &cloudwatchlogs.CreateLogGroupInput{LogGroupName: aws.String(group), Tags: map[string]string{"env": "dev"}})
	check("CreateLogGroup", err == nil, fmt.Sprint(err))
	_, err = c.CreateLogGroup(ctx, &cloudwatchlogs.CreateLogGroupInput{LogGroupName: aws.String(group)})
	var exists *types.ResourceAlreadyExistsException
	check("duplicate CreateLogGroup → ResourceAlreadyExistsException", errors.As(err, &exists), fmt.Sprint(err))

	dg, err := c.DescribeLogGroups(ctx, &cloudwatchlogs.DescribeLogGroupsInput{LogGroupNamePrefix: aws.String(group)})
	check("DescribeLogGroups", err == nil && len(dg.LogGroups) == 1 && aws.ToString(dg.LogGroups[0].LogGroupName) == group, fmt.Sprint(err))

	_, err = c.PutRetentionPolicy(ctx, &cloudwatchlogs.PutRetentionPolicyInput{LogGroupName: aws.String(group), RetentionInDays: aws.Int32(14)})
	check("PutRetentionPolicy", err == nil, fmt.Sprint(err))
	dg, _ = c.DescribeLogGroups(ctx, &cloudwatchlogs.DescribeLogGroupsInput{LogGroupNamePrefix: aws.String(group)})
	check("retention visible", dg != nil && len(dg.LogGroups) == 1 && aws.ToInt32(dg.LogGroups[0].RetentionInDays) == 14, "")

	_, err = c.CreateLogStream(ctx, &cloudwatchlogs.CreateLogStreamInput{LogGroupName: aws.String(group), LogStreamName: aws.String(stream)})
	check("CreateLogStream", err == nil, fmt.Sprint(err))

	pe, err := c.PutLogEvents(ctx, &cloudwatchlogs.PutLogEventsInput{LogGroupName: aws.String(group), LogStreamName: aws.String(stream),
		LogEvents: []types.InputLogEvent{
			{Timestamp: aws.Int64(now), Message: aws.String("job started")},
			{Timestamp: aws.Int64(now + 1), Message: aws.String("job failed ERROR timeout")},
			{Timestamp: aws.Int64(now + 2), Message: aws.String("job finished")},
		}})
	check("PutLogEvents", err == nil && pe.NextSequenceToken != nil, fmt.Sprint(err))

	ge, err := c.GetLogEvents(ctx, &cloudwatchlogs.GetLogEventsInput{LogGroupName: aws.String(group), LogStreamName: aws.String(stream), StartFromHead: aws.Bool(true)})
	check("GetLogEvents returns events in order", err == nil && len(ge.Events) == 3 && aws.ToString(ge.Events[0].Message) == "job started", fmt.Sprint(err))

	fe, err := c.FilterLogEvents(ctx, &cloudwatchlogs.FilterLogEventsInput{LogGroupName: aws.String(group), FilterPattern: aws.String("ERROR")})
	check("FilterLogEvents ERROR", err == nil && len(fe.Events) == 1 && strings.Contains(aws.ToString(fe.Events[0].Message), "timeout"), fmt.Sprint(err))

	ds, err := c.DescribeLogStreams(ctx, &cloudwatchlogs.DescribeLogStreamsInput{LogGroupName: aws.String(group)})
	check("DescribeLogStreams", err == nil && len(ds.LogStreams) == 1 && aws.ToInt64(ds.LogStreams[0].StoredBytes) > 0, fmt.Sprint(err))

	_, err = c.PutMetricFilter(ctx, &cloudwatchlogs.PutMetricFilterInput{LogGroupName: aws.String(group), FilterName: aws.String("errors"), FilterPattern: aws.String("ERROR"),
		MetricTransformations: []types.MetricTransformation{{MetricName: aws.String("Errors"), MetricNamespace: aws.String("Vyomi"), MetricValue: aws.String("1")}}})
	check("PutMetricFilter", err == nil, fmt.Sprint(err))
	mf, err := c.DescribeMetricFilters(ctx, &cloudwatchlogs.DescribeMetricFiltersInput{LogGroupName: aws.String(group)})
	check("DescribeMetricFilters", err == nil && len(mf.MetricFilters) == 1, fmt.Sprint(err))

	_, err = c.TagResource(ctx, &cloudwatchlogs.TagResourceInput{ResourceArn: dg.LogGroups[0].LogGroupArn, Tags: map[string]string{"team": "obs"}})
	check("TagResource", err == nil, fmt.Sprint(err))
	lt, err := c.ListTagsForResource(ctx, &cloudwatchlogs.ListTagsForResourceInput{ResourceArn: dg.LogGroups[0].LogGroupArn})
	check("ListTagsForResource", err == nil && lt.Tags["team"] == "obs" && lt.Tags["env"] == "dev", fmt.Sprint(err))

	sq, err := c.StartQuery(ctx, &cloudwatchlogs.StartQueryInput{LogGroupName: aws.String(group), StartTime: aws.Int64(now/1000 - 60), EndTime: aws.Int64(now/1000 + 60),
		QueryString: aws.String("fields @message | filter @message like /ERROR/")})
	check("StartQuery", err == nil && sq.QueryId != nil, fmt.Sprint(err))
	if sq != nil && sq.QueryId != nil {
		qr, err := c.GetQueryResults(ctx, &cloudwatchlogs.GetQueryResultsInput{QueryId: sq.QueryId})
		check("GetQueryResults", err == nil && qr.Status == types.QueryStatusComplete && len(qr.Results) == 1, fmt.Sprint(err))
	}

	kmsArn := "arn:aws:kms:us-east-1:000000000000:key/1234abcd-12ab-34cd-56ef-1234567890ab"
	_, err = c.AssociateKmsKey(ctx, &cloudwatchlogs.AssociateKmsKeyInput{LogGroupName: aws.String(group), KmsKeyId: aws.String(kmsArn)})
	check("AssociateKmsKey", err == nil, fmt.Sprint(err))
	dg, _ = c.DescribeLogGroups(ctx, &cloudwatchlogs.DescribeLogGroupsInput{LogGroupNamePrefix: aws.String(group)})
	check("kmsKeyId visible after AssociateKmsKey", dg != nil && len(dg.LogGroups) == 1 && aws.ToString(dg.LogGroups[0].KmsKeyId) == kmsArn, "")
	_, err = c.DisassociateKmsKey(ctx, &cloudwatchlogs.DisassociateKmsKeyInput{LogGroupName: aws.String(group)})
	check("DisassociateKmsKey", err == nil, fmt.Sprint(err))
	dg, _ = c.DescribeLogGroups(ctx, &cloudwatchlogs.DescribeLogGroupsInput{LogGroupNamePrefix: aws.String(group)})
	check("kmsKeyId cleared after DisassociateKmsKey", dg != nil && len(dg.LogGroups) == 1 && dg.LogGroups[0].KmsKeyId == nil, "")

	_, err = c.TagLogGroup(ctx, &cloudwatchlogs.TagLogGroupInput{LogGroupName: aws.String(group), Tags: map[string]string{"legacy": "yes"}})
	check("TagLogGroup", err == nil, fmt.Sprint(err))
	_, err = c.UntagLogGroup(ctx, &cloudwatchlogs.UntagLogGroupInput{LogGroupName: aws.String(group), Tags: []string{"legacy"}})
	check("UntagLogGroup", err == nil, fmt.Sprint(err))
	tl, err := c.ListTagsLogGroup(ctx, &cloudwatchlogs.ListTagsLogGroupInput{LogGroupName: aws.String(group)})
	_, hasLegacy := tl.Tags["legacy"]
	check("UntagLogGroup removed the tag", err == nil && !hasLegacy && tl.Tags["env"] == "dev", fmt.Sprint(err))

	if sq != nil && sq.QueryId != nil {
		dq, err := c.DescribeQueries(ctx, &cloudwatchlogs.DescribeQueriesInput{LogGroupName: aws.String(group)})
		found := false
		if err == nil {
			for _, q := range dq.Queries {
				if aws.ToString(q.QueryId) == aws.ToString(sq.QueryId) {
					found = true
				}
			}
		}
		check("DescribeQueries lists the started query", found, fmt.Sprint(err))
		st, err := c.StopQuery(ctx, &cloudwatchlogs.StopQueryInput{QueryId: sq.QueryId})
		check("StopQuery on a completed query → Success=false", err == nil && !st.Success, fmt.Sprint(err))
	}
	_, err = c.StopQuery(ctx, &cloudwatchlogs.StopQueryInput{QueryId: aws.String("00000000-0000-0000-0000-000000000000")})
	check("StopQuery unknown id → ResourceNotFoundException", errors.As(err, new(*types.ResourceNotFoundException)), fmt.Sprint(err))

	_, err = c.DeleteLogStream(ctx, &cloudwatchlogs.DeleteLogStreamInput{LogGroupName: aws.String(group), LogStreamName: aws.String(stream)})
	check("DeleteLogStream", err == nil, fmt.Sprint(err))
	_, err = c.DeleteLogGroup(ctx, &cloudwatchlogs.DeleteLogGroupInput{LogGroupName: aws.String(group)})
	check("DeleteLogGroup", err == nil, fmt.Sprint(err))
	_, err = c.DeleteLogGroup(ctx, &cloudwatchlogs.DeleteLogGroupInput{LogGroupName: aws.String(group)})
	var nf *types.ResourceNotFoundException
	check("deleted group → ResourceNotFoundException", errors.As(err, &nf), fmt.Sprint(err))

	if failed > 0 {
		os.Exit(1)
	}
}
