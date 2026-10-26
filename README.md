# Vyomi Conformance — hourly report

Run **2026-10-26T08:05:52+00:00** · commit `18e4b086a48d` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 9/20 | 147 | 220 | 0/43 | 1/38 | 86 | 10.3% (33/319) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 1/6 | 32 | 32 | 0/12 | 0/12 | 25 |
| [GCP](#gcp) | 4/4 | 17 | 0 | 0/12 | 0/12 | 25 |
| [Azure](#azure) | 4/5 | 28 | 2 | 0/19 | 1/14 | 36 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 3.2 |
| ❌ | `offline-cli-aws` | offline | cli | 6 | 9 | 14.7 |
| ❌ | `offline-sdk-go-aws` | offline | sdk-go | 6 | 8 | 40.9 |
| ❌ | `offline-sdk-java-aws` | offline | sdk-java | 6 | 7 | 13.7 |
| ❌ | `offline-sdk-python-aws` | offline | sdk-python | 9 | 7 | 309.1 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 0 | 0 | 12.4 |

<details><summary>❌ <code>offline-sdk-python-aws</code> log</summary>

```
  s3      parity  50.0%   pass=1 warn(deviation)=0 fail=1
  iam     parity 100.0%   pass=4 warn(deviation)=0 fail=0
  ec2     parity 100.0%   pass=2 warn(deviation)=0 fail=0
  sqs     parity   0.0%   pass=0 warn(deviation)=0 fail=1
  rds     parity  50.0%   pass=1 warn(deviation)=0 fail=1
  dynamodb  parity   0.0%   pass=0 warn(deviation)=0 fail=2
  gcp.storage  parity   0.0%   pass=0 warn(deviation)=4 fail=0
  gcp.vpc  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.compute  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.sql  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.pubsub  parity   0.0%   pass=0 warn(deviation)=4 fail=0
  gcp.firestore  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.functions  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.iam  parity  16.7%   pass=1 warn(deviation)=5 fail=0
  azure.spaces  parity   0.0%   pass=0 warn(deviation)=0 fail=1
  azure.sql  parity   0.0%   pass=0 warn(deviation)=3 fail=0
  azure.keyvault  parity   0.0%   pass=0 warn(deviation)=4 fail=0
  aws.kms  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  aws.secretsmanager  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.kms  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.secretmanager  parity   0.0%   pass=0 warn(deviation)=3 fail=0
  nats    parity   0.0%   pass=0 warn(deviation)=1 fail=0
  aws.eventbridge  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  gcp.eventarc  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  azure.eventgrid  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  aws.iam  parity   0.0%   pass=0 warn(deviation)=3 fail=0
  azure.rbac  parity   0.0%   pass=0 warn(deviation)=2 fail=0
  aws.s3.minio  parity   0.0%   pass=0 warn(deviation)=3 fail=1
  ----  OVERALL parity  12.9%  pass=9 warn=54 fail=7 skip=0
===========================================================
```

</details>

<details><summary>❌ <code>offline-sdk-go-aws</code> log</summary>

```
FAIL dynamodb PutItem :: operation error DynamoDB: PutItem, https response error StatusCode: 403, RequestID: , api error UnknownError: UnknownError
FAIL dynamodb GetItem round-trip :: operation error DynamoDB: GetItem, https response error StatusCode: 403, RequestID: , api error UnknownError: UnknownError
PASS sqs CreateQueue
PASS sqs ListQueues
RESULT pass=6 fail=8
go: downloading github.com/aws/aws-sdk-go-v2 v1.30.0
go: downloading github.com/aws/aws-sdk-go-v2/config v1.27.0
go: downloading github.com/aws/aws-sdk-go-v2/credentials v1.17.0
go: downloading github.com/aws/aws-sdk-go-v2/service/dynamodb v1.32.0
go: downloading github.com/aws/aws-sdk-go-v2/service/ec2 v1.160.0
go: downloading github.com/aws/aws-sdk-go-v2/service/iam v1.34.0
go: downloading github.com/aws/aws-sdk-go-v2/service/s3 v1.55.0
go: downloading github.com/aws/aws-sdk-go-v2/service/sqs v1.32.0
go: downloading github.com/aws/smithy-go v1.20.2
go: downloading github.com/aws/aws-sdk-go-v2/feature/ec2/imds v1.15.0
go: downloading github.com/aws/aws-sdk-go-v2/internal/ini v1.8.0
go: downloading github.com/aws/aws-sdk-go-v2/service/sso v1.19.0
go: downloading github.com/aws/aws-sdk-go-v2/service/ssooidc v1.22.0
go: downloading github.com/aws/aws-sdk-go-v2/service/sts v1.27.0
go: downloading github.com/aws/aws-sdk-go-v2/internal/configsources v1.3.12
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/accept-encoding v1.11.2
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/endpoint-discovery v1.9.6
go: downloading github.com/jmespath/go-jmespath v0.4.0
go: downloading github.com/aws/aws-sdk-go-v2/aws/protocol/eventstream v1.6.2
go: downloading github.com/aws/aws-sdk-go-v2/internal/v4a v1.3.8
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/checksum v1.3.10
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/presigned-url v1.11.10
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/s3shared v1.17.8
go: downloading github.com/aws/aws-sdk-go-v2/internal/endpoints/v2 v2.6.12
exit status 1
```

</details>

<details><summary>❌ <code>offline-sdk-java-aws</code> log</summary>

```
== aws-sdk-java-v2 against http://localhost:9000 ==
switched to AWS space: space-legacy
SLF4J: Failed to load class "org.slf4j.impl.StaticLoggerBinder".
SLF4J: Defaulting to no-operation (NOP) logger implementation
SLF4J: See http://www.slf4j.org/codes.html#StaticLoggerBinder for further details.
FAIL s3 CreateBucket :: null (Service: S3, Status Code: 403, Request ID: null)
FAIL s3 PutObject :: The specified bucket does not exist. (Service: S3, Status Code: 404, Request ID: 5DB323E8550C4AA4, Extended Request ID: bb076dee950d4913a556cfc5e2701c92)
FAIL s3 GetObject round-trip :: null (Service: S3, Status Code: 400, Request ID: null)
FAIL s3 Delete (object+bucket) :: The specified bucket does not exist. (Service: S3, Status Code: 404, Request ID: F4FB889EDECC4A91, Extended Request ID: 26d6e54324e6486d8541ee4892885dd2)
PASS iam CreateUser
PASS iam ListUsers contains new user
PASS iam DeleteUser
PASS ec2 DescribeInstances
FAIL dynamodb CreateTable (via DDB Local proxy) :: Service returned HTTP status code 403 (Service: DynamoDb, Status Code: 403, Request ID: null)
FAIL dynamodb PutItem :: Service returned HTTP status code 403 (Service: DynamoDb, Status Code: 403, Request ID: null)
FAIL dynamodb GetItem round-trip :: Service returned HTTP status code 403 (Service: DynamoDb, Status Code: 403, Request ID: null)
PASS sqs CreateQueue
PASS sqs ListQueues
RESULT pass=6 fail=7
```

</details>

<details><summary>❌ <code>offline-cli-aws</code> log</summary>

```
== aws-cli against http://localhost:9000 ==
aws-cli/2.37.13 Python/3.14.6 Linux/6.17.0-1022-azure exe/x86_64.ubuntu.24
switched to AWS space: space-legacy
FAIL s3 mb (create bucket) :: make_bucket failed: s3://cli-smoke-1793001624 An error occurred (403) when calling the CreateBucket operation: Forbidden
FAIL s3 ls (list buckets shows new one) :: 2026-10-26 07:52:48 vyomi-conf-s3-df73f2d2
FAIL s3 cp (upload) :: Completed 19 Bytes/19 Bytes (607 Bytes/s) with 1 file(s) remaining
upload failed: ../../../../../tmp/aws-cli-obj.txt to s3://cli-smoke-1793001624/obj.txt An error occurred (NoSuchBucket) when calling the PutObject operation: The specified bucket does not exist.
FAIL s3 cp (download to stdout) :: download failed: s3://cli-smoke-1793001624/obj.txt to - An error occurred (404) when calling the HeadObject operation: Not Found
FAIL s3 rm :: delete failed: s3://cli-smoke-1793001624/obj.txt An error occurred (NoSuchBucket) when calling the DeleteObject operation: The specified bucket does not exist.
FAIL s3 rb (delete bucket) :: remove_bucket failed: s3://cli-smoke-1793001624 An error occurred (NoSuchBucket) when calling the DeleteBucket operation: The specified bucket does not exist.
PASS iam create-user
PASS iam list-users contains new user
PASS iam delete-user
PASS ec2 describe-instances
FAIL dynamodb create-table (via DDB Local proxy) :: 
aws: [ERROR]: An error occurred (403) when calling the CreateTable operation:
FAIL dynamodb put-item :: 
aws: [ERROR]: An error occurred (403) when calling the PutItem operation:
FAIL dynamodb get-item round-trip :: 
aws: [ERROR]: An error occurred (403) when calling the GetItem operation:
PASS sqs create-queue
PASS sqs list-queues
RESULT pass=6 fail=9
```

</details>

<details><summary>❌ <code>nano-ui-aws-api</code> log</summary>

```
===== AWS core services — API create→list round-trip =====
  [PASS] S3         create:200 listed:true count:1 
  [PASS] DynamoDB   create:200 listed:true count:1 
  [PASS] SQS        create:200 listed:true count:1 
  [FAIL] KMS        create:200 listed:false count:1 
  [PASS] Secrets    create:200 listed:true count:1 
  [PASS] IAM        create:200 listed:true count:1 

5/6 AWS core services round-trip at the API
```

</details>

**UI findings: 25**

<details><summary><b>EC2</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_5XX` |  | during create: /api/ec2/instances → 500 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>EC2</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Lambda</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_FAILED` |  | create with defaults failed: locator.click: Timeout 3000ms exceeded. |

</details>

<details><summary><b>S3</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>RDS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>DynamoDB</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>SQS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Gateway</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>EventBridge</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>VPC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>IAM</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>KMS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Lambda</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_FAILED` |  | create with defaults failed: locator.click: Timeout 3000ms exceeded. |

</details>

<details><summary><b>S3</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>RDS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>DynamoDB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>SQS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Gateway</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>EventBridge</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>VPC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>IAM</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>KMS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 0 | 0 | 3.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 7.7 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 14.0 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 5.0 |

**UI findings: 25**

<details><summary><b>Compute Engine</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_5XX` |  | during create: /api/gcp/compute/v1/projects/123456789012/zones/us-central1-a/instances → 500 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Compute Engine</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud Functions</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud Storage</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud SQL</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Firestore</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>VPC Network</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Pub/Sub</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>API Gateway</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Eventarc</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Secret Manager</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud KMS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM & Admin</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud Functions</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud Storage</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud SQL</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Firestore</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>VPC Network</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Pub/Sub</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>API Gateway</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Eventarc</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Secret Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Cloud KMS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM & Admin</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-cli-azure` | offline | cli | 4 | 2 | 8.3 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.7 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 0 | 0 | 17.3 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 9.5 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 21.2 |

<details><summary>❌ <code>offline-cli-azure</code> log</summary>

```
== az against http://localhost:9000 subscription=sub-001 ==
azure-cli                         2.91.0
switched to Azure space: space-azure-default
FAIL az rest PUT Microsoft.Compute/virtualMachines :: ERROR: Forbidden({"detail":{"ok":false,"code":"tier_quantity_limit","reason":"free tier allows max 1 vm(s) per space; you have 1","upgrade_to":"pro","resource_type":"vm","limit":1,"current":1,"active_tier":"free","docs":"https://cloudlearn.io/docs/tiers"}})
PASS az rest GET VM round-trip
FAIL az rest PUT Microsoft.Storage/storageAccounts :: ERROR: Forbidden({"detail":{"ok":false,"code":"tier_quantity_limit","reason":"free tier allows max 1 bucket(s) per space; you have 1","upgrade_to":"pro","resource_type":"bucket","limit":1,"current":1,"active_tier":"free","docs":"https://cloudlearn.io/docs/tiers"}})
PASS az rest PUT Microsoft.Sql/servers
PASS az rest PUT Microsoft.Sql/.../databases (real Postgres)
PASS az SQL DB connectionInfo surfaces real Postgres engine
RESULT pass=4 fail=2
```

</details>

**UI findings: 36**

<details><summary><b>Resource groups</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined?api-version=2023-01-01 → 404 |
| `HTTP_404` |  | /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined?api-version=2023-01-01 → 404 |
| `HTTP_404` |  | /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined?api-version=2023-01-01 → 404 |
| `HTTP_404` |  | /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined?api-version=2023-01-01 → 404 |
| `HTTP_404` |  | /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined?api-version=2023-01-01 → 404 |

</details>

<details><summary><b>Virtual Machines</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_FAILED` |  | create with defaults failed: locator.click: Timeout 3000ms exceeded. |

</details>

<details><summary><b>Storage accounts</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>SQL servers</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Service Bus</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Cosmos DB</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Function apps</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Management</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Virtual networks</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Network Security Group</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Event Grid topics</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Key vaults</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Role Definition</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Entra ID / RBAC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Blob containers</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Cosmos databases</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Key Vault secrets</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Key Vault keys</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Storage queues</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Virtual Machines</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_FAILED` |  | create with defaults failed: locator.click: Timeout 3000ms exceeded. |

</details>

<details><summary><b>Storage accounts</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>SQL servers</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Service Bus</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Cosmos DB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Function apps</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Management</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Virtual networks</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Network Security Group</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Event Grid topics</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Key vaults</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Role Definition</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Entra ID / RBAC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-cores` | nano | core | 0 | 8 | 1.1 |
| ❌ | `nano-ui-crawl` | nano | ui | 0 | 43 | 253.3 |
| ❌ | `offline-console-actions` | offline | api | 67 | 93 | 4.5 |
| ❌ | `offline-cost-savings` | offline | api | 2 | 5 | 38.5 |
| ❌ | `offline-ui-crawl` | offline | ui | 1 | 37 | 221.1 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 12 with findings
[offline/gcp] 12 services crawled, 12 with findings
[offline/azure] 14 services crawled, 13 with findings
UI crawl offline: 1/38 services clean → tests/conformance/hourly/out/ui-offline.json
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.048,"docs":"https://cl
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.list0] - AssertionError: GCP storage.list GET /api/gcp/storage/v1/b → HTTP 429 (expected one of (200, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.045,"docs":"https://cl
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.list1] - AssertionError: GCP storage.list GET /api/gcp/storage/v1/b → HTTP 429 (expected one of (200, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.042,"docs":"https://cl
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.vpc.create] - AssertionError: GCP vpc.create POST /api/gcp/compute/v1/projects/cloudlearn/global/networks → HTTP 429 (expected one of (200, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.034,"docs":"https://cl
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.vpc.list] - AssertionError: GCP vpc.list GET /api/gcp/compute/v1/projects/cloudlearn/global/networks → HTTP 429 (expected one of (200, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.031,"docs":"https://cl
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.vpc.firewalls] - AssertionError: GCP vpc.firewalls GET /api/gcp/compute/v1/projects/cloudlearn/global/firewalls → HTTP 429 (expected one of (200, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.027,"docs":"https://cl
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.vpc.subnetworks] - AssertionError: GCP vpc.subnetworks GET /api/gcp/compute/v1/projects/cloudlearn/regions/us-central1/subnetworks → HTTP 429 (expected one of (200, 201, 202, 204)). Body: {"error":{"ok":false,"code":"rate_limited","reason":"free tier limit: 10 requests/sec sustained","active_tier":"free","tenant_id":"default","rate_limit_rps":10,"retry_after_s":0.023,"docs":"https://cl
assert False
93 failed, 67 passed, 96 skipped in 3.87s
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
FAIL: aws: savings check ran :: ClientError('An error occurred (403) when calling the CreateBucket operation: Forbidden')

== gcp: Cloud Storage bucket ==
FAIL: gcp: creating a Cloud Storage bucket raises the space resource_count :: 6 → 6
FAIL: gcp: creating a Cloud Storage bucket raises gcp savings :: $0.88 → $0.88
FAIL: gcp: using the Cloud Storage bucket (5 × 2 MB uploads) raises savings :: $0.88 → $0.88 (real gcp bills storage + requests)

== azure: Storage account ==
PASS: azure: creating a Storage account raises the space resource_count
PASS: azure: creating a Storage account raises azure savings
FAIL: azure: using the Storage account (5 × 2 MB uploads) raises savings :: $0.7 → $0.7 (real azure bills storage + requests)

RESULT fail=5
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 12 services crawled, 12 with findings
[nano/gcp] 12 services crawled, 12 with findings
[nano/azure] 19 services crawled, 19 with findings
UI crawl nano: 0/43 services clean → tests/conformance/hourly/out/ui-nano.json
```

</details>

<details><summary>❌ <code>nano-cores</code> log</summary>

```
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/conformance/test_nats_backed_store.py:13: in <module>
    from core.nats_backed_store import NatsBackedMessagingStore
core/nats_backed_store.py:23: in <module>
    import nats
E   ModuleNotFoundError: No module named 'nats'
_______ ERROR collecting tests/conformance/test_postgres_backed_store.py _______
ImportError while importing test module '/home/runner/work/appliance/appliance/tests/conformance/test_postgres_backed_store.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/conformance/test_postgres_backed_store.py:9: in <module>
    from core.postgres_backed_store import PostgresBackedSqlStore
core/postgres_backed_store.py:14: in <module>
    import psycopg2
E   ModuleNotFoundError: No module named 'psycopg2'
____________________ ERROR collecting tests/conformance/ui _____________________
E   ModuleNotFoundError: No module named 'playwright'
__________________ ERROR collecting tests/conformance/ui_real __________________
E   ModuleNotFoundError: No module named 'playwright'
=========================== short test summary info ============================
ERROR tests/conformance/test_nats_backed_store.py
ERROR tests/conformance/test_postgres_backed_store.py
ERROR tests/conformance/ui - ModuleNotFoundError: No module named 'playwright'
ERROR tests/conformance/ui_real - ModuleNotFoundError: No module named 'playwright'
!!!!!!!!!!!!!!!!!!! Interrupted: 4 errors during collection !!!!!!!!!!!!!!!!!!!!
256 deselected, 4 errors in 0.88s
```

</details>

## New features without tests

None since the last run.

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-26T08:05:52+00:00 | 9/20 | 147 | 220 | 86 | 10.3% |  |
| 2026-10-26T07:46:18+00:00 | 9/20 | 137 | 228 | 86 | 10.3% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
