// Real aws-sdk-go-v2 conformance probe against the CloudLearn simulator.
//
// Proves whether UNMODIFIED Amazon Go clients work pointed at the simulator
// via BaseEndpoint overrides. Mirrors the pattern of gcp-sdk-go (Google) and
// azure-sdk-go (Azure) tests.
//
// Run (dockerized, on the appliance):
//
//	docker run --rm --network host \
//	  -e ENDPOINT=http://127.0.0.1:9000 \
//	  -e GOFLAGS=-mod=mod \
//	  -v /workspace/cloud-learn/tests/conformance/aws-sdk-go:/app -w /app \
//	  golang:1.22 sh -c "go mod tidy && go run ."
//
// Exit code is 0 on all-pass, non-zero on any fail.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	dynamodbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/iam"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
)

var (
	pass int
	fail int
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func chk(name string, err error, extra ...string) {
	if err == nil {
		pass++
		fmt.Printf("PASS %s\n", name)
		return
	}
	fail++
	fmt.Printf("FAIL %s :: %v\n", name, err)
	for _, e := range extra {
		fmt.Printf("    %s\n", e)
	}
}

func main() {
	endpoint := env("ENDPOINT", "http://127.0.0.1:9000")
	ctx := context.Background()

	fmt.Printf("== aws-sdk-go-v2 against %s ==\n", endpoint)

	// Shared config: bogus creds (simulator ignores them), us-east-1, sim endpoint.
	cfg, err := config.LoadDefaultConfig(ctx,
		config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")),
	)
	if err != nil {
		fmt.Printf("FAIL config.LoadDefaultConfig :: %v\n", err)
		os.Exit(1)
	}

	// Switch to an AWS space first — S3 ops are space-scoped.
	switchToAwsSpace(endpoint)

	bucketName := fmt.Sprintf("sdk-go-smoke-%d", time.Now().Unix())

	// --- S3 ---
	s3cli := s3.NewFromConfig(cfg, func(o *s3.Options) {
		o.BaseEndpoint = aws.String(endpoint)
		o.UsePathStyle = true
	})

	_, err = s3cli.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: aws.String(bucketName)})
	chk("s3 CreateBucket", err)

	body := bytes.NewReader([]byte("hello-from-aws-sdk-go-v2"))
	_, err = s3cli.PutObject(ctx, &s3.PutObjectInput{
		Bucket: aws.String(bucketName),
		Key:    aws.String("obj.txt"),
		Body:   body,
	})
	chk("s3 PutObject", err)

	out, err := s3cli.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucketName),
		Key:    aws.String("obj.txt"),
	})
	if err != nil {
		chk("s3 GetObject", err)
	} else {
		gotBytes, _ := io.ReadAll(out.Body)
		got := string(gotBytes)
		if got == "hello-from-aws-sdk-go-v2" {
			chk("s3 GetObject round-trip", nil)
		} else {
			chk("s3 GetObject round-trip", fmt.Errorf("got %q", got))
		}
		out.Body.Close()
	}

	_, err = s3cli.DeleteObject(ctx, &s3.DeleteObjectInput{
		Bucket: aws.String(bucketName), Key: aws.String("obj.txt"),
	})
	chk("s3 DeleteObject", err)

	_, err = s3cli.DeleteBucket(ctx, &s3.DeleteBucketInput{Bucket: aws.String(bucketName)})
	chk("s3 DeleteBucket", err)

	// --- IAM ---
	iamcli := iam.NewFromConfig(cfg, func(o *iam.Options) {
		o.BaseEndpoint = aws.String(endpoint)
	})

	userName := fmt.Sprintf("sdk-go-user-%d", time.Now().Unix())
	_, err = iamcli.CreateUser(ctx, &iam.CreateUserInput{UserName: aws.String(userName)})
	chk("iam CreateUser", err)

	listOut, err := iamcli.ListUsers(ctx, &iam.ListUsersInput{})
	if err != nil {
		chk("iam ListUsers", err)
	} else {
		found := false
		for _, u := range listOut.Users {
			if aws.ToString(u.UserName) == userName {
				found = true
				break
			}
		}
		if found {
			chk("iam ListUsers contains new user", nil)
		} else {
			chk("iam ListUsers contains new user", fmt.Errorf("not in %d users", len(listOut.Users)))
		}
	}

	_, err = iamcli.DeleteUser(ctx, &iam.DeleteUserInput{UserName: aws.String(userName)})
	chk("iam DeleteUser", err)

	// --- EC2 ---
	ec2cli := ec2.NewFromConfig(cfg, func(o *ec2.Options) {
		o.BaseEndpoint = aws.String(endpoint)
	})

	_, err = ec2cli.DescribeInstances(ctx, &ec2.DescribeInstancesInput{})
	chk("ec2 DescribeInstances", err)

	// --- DynamoDB (proxied to DDB Local) ---
	ddbcli := dynamodb.NewFromConfig(cfg, func(o *dynamodb.Options) {
		o.BaseEndpoint = aws.String(endpoint)
	})

	tableName := fmt.Sprintf("sdk-go-tbl-%d", time.Now().Unix())
	_, err = ddbcli.CreateTable(ctx, &dynamodb.CreateTableInput{
		TableName: aws.String(tableName),
		KeySchema: []dynamodbtypes.KeySchemaElement{
			{AttributeName: aws.String("id"), KeyType: dynamodbtypes.KeyTypeHash},
		},
		AttributeDefinitions: []dynamodbtypes.AttributeDefinition{
			{AttributeName: aws.String("id"), AttributeType: dynamodbtypes.ScalarAttributeTypeS},
		},
		BillingMode: dynamodbtypes.BillingModePayPerRequest,
	})
	chk("dynamodb CreateTable (via DDB Local proxy)", err)

	_, err = ddbcli.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: aws.String(tableName),
		Item: map[string]dynamodbtypes.AttributeValue{
			"id": &dynamodbtypes.AttributeValueMemberS{Value: "k1"},
			"v":  &dynamodbtypes.AttributeValueMemberS{Value: "sdk-go-roundtrip"},
		},
	})
	chk("dynamodb PutItem", err)

	getOut, err := ddbcli.GetItem(ctx, &dynamodb.GetItemInput{
		TableName: aws.String(tableName),
		Key: map[string]dynamodbtypes.AttributeValue{
			"id": &dynamodbtypes.AttributeValueMemberS{Value: "k1"},
		},
	})
	if err != nil {
		chk("dynamodb GetItem round-trip", err)
	} else {
		vAttr, ok := getOut.Item["v"].(*dynamodbtypes.AttributeValueMemberS)
		if ok && vAttr.Value == "sdk-go-roundtrip" {
			chk("dynamodb GetItem round-trip", nil)
		} else {
			chk("dynamodb GetItem round-trip", fmt.Errorf("got %+v", getOut.Item))
		}
	}

	_, _ = ddbcli.DeleteTable(ctx, &dynamodb.DeleteTableInput{TableName: aws.String(tableName)})

	// --- SQS (modern boto3 uses JSON-RPC which stays in-memory; legacy query
	// reaches ElasticMQ. aws-sdk-go-v2 SQS uses JSON-RPC by default. We accept
	// EITHER path here — the simulator returns valid SQS responses both ways.)
	sqscli := sqs.NewFromConfig(cfg, func(o *sqs.Options) {
		o.BaseEndpoint = aws.String(endpoint)
	})
	qName := fmt.Sprintf("sdk-go-q-%d", time.Now().Unix())
	createQ, err := sqscli.CreateQueue(ctx, &sqs.CreateQueueInput{QueueName: aws.String(qName)})
	chk("sqs CreateQueue", err)
	if err == nil && createQ.QueueUrl != nil && !strings.Contains(*createQ.QueueUrl, qName) {
		fmt.Printf("    note: QueueUrl=%s\n", *createQ.QueueUrl)
	}

	_, err = sqscli.ListQueues(ctx, &sqs.ListQueuesInput{})
	chk("sqs ListQueues", err)

	fmt.Printf("RESULT pass=%d fail=%d\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}

// switchToAwsSpace POSTs /api/spaces/{id}/switch for the first space whose
// provider is "aws" (so S3 bucket ops land in an AWS-scoped space).
func switchToAwsSpace(endpoint string) {
	type space struct {
		SpaceID  string `json:"space_id"`
		Provider string `json:"provider"`
	}
	type spaces struct {
		Spaces []space `json:"spaces"`
	}
	resp, err := http.Get(endpoint + "/api/spaces")
	if err != nil {
		return
	}
	defer resp.Body.Close()
	var s spaces
	if err := json.NewDecoder(resp.Body).Decode(&s); err != nil {
		return
	}
	for _, sp := range s.Spaces {
		if sp.Provider == "aws" {
			req, _ := http.NewRequest("POST", endpoint+"/api/spaces/"+sp.SpaceID+"/switch", nil)
			r, err := http.DefaultClient.Do(req)
			if err == nil {
				r.Body.Close()
			}
			fmt.Printf("switched to AWS space: %s\n", sp.SpaceID)
			return
		}
	}
}
