// Real aws-sdk-go-v2 conformance for Amazon Kinesis Data Streams against Vyomi,
// with only the endpoint changed.
//
//	ENDPOINT=http://localhost:9000 GOFLAGS=-mod=mod go run .
//
// One [PASS]/[FAIL] line per check; exit 1 on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/kinesis"
	"github.com/aws/aws-sdk-go-v2/service/kinesis/types"
	"github.com/aws/smithy-go"
)

var fails int

func check(ok bool, what string, detail ...any) {
	if ok {
		fmt.Printf("[PASS] %s\n", what)
		return
	}
	fails++
	fmt.Printf("[FAIL] %s :: %v\n", what, detail)
}

func apiCode(err error) string {
	var ae smithy.APIError
	if errors.As(err, &ae) {
		return ae.ErrorCode()
	}
	return fmt.Sprint(err)
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://localhost:9000"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Minute)
	defer cancel()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	c := kinesis.NewFromConfig(cfg, func(o *kinesis.Options) { o.BaseEndpoint = aws.String(endpoint) })
	name := "go-kin-" + strconv.FormatInt(time.Now().UnixNano()%1_000_000_000, 36)

	_, err = c.CreateStream(ctx, &kinesis.CreateStreamInput{StreamName: &name, ShardCount: aws.Int32(2)})
	check(err == nil, "CreateStream", err)
	_, err = c.CreateStream(ctx, &kinesis.CreateStreamInput{StreamName: &name, ShardCount: aws.Int32(1)})
	check(err != nil && apiCode(err) == "ResourceInUseException", "duplicate CreateStream -> ResourceInUseException", apiCode(err))

	d, err := c.DescribeStream(ctx, &kinesis.DescribeStreamInput{StreamName: &name})
	check(err == nil && d.StreamDescription.StreamStatus == types.StreamStatusActive && len(d.StreamDescription.Shards) == 2,
		"DescribeStream is ACTIVE with 2 shards", err)
	arn := ""
	var shards []types.Shard
	if err == nil {
		arn = *d.StreamDescription.StreamARN
		shards = d.StreamDescription.Shards
	}
	s, err := c.DescribeStreamSummary(ctx, &kinesis.DescribeStreamSummaryInput{StreamName: &name})
	check(err == nil && *s.StreamDescriptionSummary.OpenShardCount == 2 && *s.StreamDescriptionSummary.RetentionPeriodHours == 24,
		"DescribeStreamSummary", err)
	l, err := c.ListStreams(ctx, &kinesis.ListStreamsInput{})
	found := false
	if err == nil {
		for _, n := range l.StreamNames {
			found = found || n == name
		}
	}
	check(found, "ListStreams contains the stream", err)

	p, err := c.PutRecord(ctx, &kinesis.PutRecordInput{StreamName: &name, PartitionKey: aws.String("pk-1"), Data: []byte("hello-go")})
	check(err == nil && p.ShardId != nil && len(*p.SequenceNumber) == 56, "PutRecord returns shard id and 56-digit sequence number", err)
	var entries []types.PutRecordsRequestEntry
	for i := 0; i < 5; i++ {
		entries = append(entries, types.PutRecordsRequestEntry{PartitionKey: aws.String(fmt.Sprintf("k%d", i)), Data: []byte(fmt.Sprintf("rec-%d", i))})
	}
	pr, err := c.PutRecords(ctx, &kinesis.PutRecordsInput{StreamName: &name, Records: entries})
	check(err == nil && *pr.FailedRecordCount == 0 && len(pr.Records) == 5, "PutRecords (5 records)", err)

	total := 0
	for _, sh := range shards {
		it, err := c.GetShardIterator(ctx, &kinesis.GetShardIteratorInput{StreamName: &name, ShardId: sh.ShardId, ShardIteratorType: types.ShardIteratorTypeTrimHorizon})
		if err != nil {
			check(false, "GetShardIterator TRIM_HORIZON", err)
			continue
		}
		g, err := c.GetRecords(ctx, &kinesis.GetRecordsInput{ShardIterator: it.ShardIterator})
		if err != nil {
			check(false, "GetRecords", err)
			continue
		}
		total += len(g.Records)
	}
	check(total == 6, "GetRecords reads back all 6 records across shards", total)
	if p != nil && p.ShardId != nil {
		it, _ := c.GetShardIterator(ctx, &kinesis.GetShardIteratorInput{StreamName: &name, ShardId: p.ShardId,
			ShardIteratorType: types.ShardIteratorTypeAtSequenceNumber, StartingSequenceNumber: p.SequenceNumber})
		g, err := c.GetRecords(ctx, &kinesis.GetRecordsInput{ShardIterator: it.ShardIterator, Limit: aws.Int32(1)})
		check(err == nil && len(g.Records) == 1 && string(g.Records[0].Data) == "hello-go" && *g.Records[0].PartitionKey == "pk-1",
			"AT_SEQUENCE_NUMBER returns the exact record with data and partition key", err)
	}
	_, err = c.GetRecords(ctx, &kinesis.GetRecordsInput{ShardIterator: aws.String("garbage")})
	check(err != nil && apiCode(err) == "InvalidArgumentException", "GetRecords with a bad iterator -> InvalidArgumentException", apiCode(err))

	ls, err := c.ListShards(ctx, &kinesis.ListShardsInput{StreamName: &name})
	check(err == nil && len(ls.Shards) == 2, "ListShards", err)
	_, err = c.UpdateShardCount(ctx, &kinesis.UpdateShardCountInput{StreamName: &name, TargetShardCount: aws.Int32(4), ScalingType: types.ScalingTypeUniformScaling})
	check(err == nil, "UpdateShardCount 2 -> 4", err)
	sm, err := c.DescribeStreamSummary(ctx, &kinesis.DescribeStreamSummaryInput{StreamName: &name})
	check(err == nil && *sm.StreamDescriptionSummary.OpenShardCount == 4, "open shard count is 4 after resharding", err)

	_, err = c.IncreaseStreamRetentionPeriod(ctx, &kinesis.IncreaseStreamRetentionPeriodInput{StreamName: &name, RetentionPeriodHours: aws.Int32(48)})
	check(err == nil, "IncreaseStreamRetentionPeriod", err)
	_, err = c.StartStreamEncryption(ctx, &kinesis.StartStreamEncryptionInput{StreamName: &name, EncryptionType: types.EncryptionTypeKms, KeyId: aws.String("alias/aws/kinesis")})
	check(err == nil, "StartStreamEncryption", err)
	s2, err := c.DescribeStreamSummary(ctx, &kinesis.DescribeStreamSummaryInput{StreamName: &name})
	check(err == nil && *s2.StreamDescriptionSummary.RetentionPeriodHours == 48 && s2.StreamDescriptionSummary.EncryptionType == types.EncryptionTypeKms,
		"retention and encryption are reflected", err)
	_, err = c.EnableEnhancedMonitoring(ctx, &kinesis.EnableEnhancedMonitoringInput{StreamName: &name, ShardLevelMetrics: []types.MetricsName{types.MetricsNameIncomingBytes}})
	check(err == nil, "EnableEnhancedMonitoring", err)

	_, err = c.AddTagsToStream(ctx, &kinesis.AddTagsToStreamInput{StreamName: &name, Tags: map[string]string{"env": "dev", "team": "core"}})
	check(err == nil, "AddTagsToStream", err)
	tg, err := c.ListTagsForStream(ctx, &kinesis.ListTagsForStreamInput{StreamName: &name})
	check(err == nil && len(tg.Tags) == 2, "ListTagsForStream", err)
	_, err = c.RemoveTagsFromStream(ctx, &kinesis.RemoveTagsFromStreamInput{StreamName: &name, TagKeys: []string{"team"}})
	check(err == nil, "RemoveTagsFromStream", err)

	if arn != "" {
		rc, err := c.RegisterStreamConsumer(ctx, &kinesis.RegisterStreamConsumerInput{StreamARN: &arn, ConsumerName: aws.String("analytics")})
		check(err == nil && rc.Consumer.ConsumerStatus == types.ConsumerStatusActive, "RegisterStreamConsumer", err)
		lc, err := c.ListStreamConsumers(ctx, &kinesis.ListStreamConsumersInput{StreamARN: &arn})
		check(err == nil && len(lc.Consumers) == 1, "ListStreamConsumers", err)
		_, err = c.DeleteStream(ctx, &kinesis.DeleteStreamInput{StreamName: &name})
		check(err != nil && apiCode(err) == "ResourceInUseException", "DeleteStream is blocked by a registered consumer", apiCode(err))
		_, err = c.DeregisterStreamConsumer(ctx, &kinesis.DeregisterStreamConsumerInput{StreamARN: &arn, ConsumerName: aws.String("analytics")})
		check(err == nil, "DeregisterStreamConsumer", err)
	}

	_, err = c.DeleteStream(ctx, &kinesis.DeleteStreamInput{StreamName: &name})
	check(err == nil, "DeleteStream", err)
	_, err = c.DescribeStream(ctx, &kinesis.DescribeStreamInput{StreamName: &name})
	check(err != nil && apiCode(err) == "ResourceNotFoundException", "DescribeStream after delete -> ResourceNotFoundException", apiCode(err))

	if fails > 0 {
		fmt.Printf("%d check(s) failed\n", fails)
		os.Exit(1)
	}
	fmt.Println("all checks passed")
}
