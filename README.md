# Vyomi Conformance — hourly report

Run **2026-10-29T01:35:23+00:00** · commit `622398c8946d` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 93/105 | 2464 | 85 | 25/52 | 30/52 | 81 | 14.3% (46/322) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 32/33 | 787 | 1 | 5/16 | 8/16 | 36 |
| [GCP](#gcp) | 26/27 | 372 | 1 | 5/16 | 6/16 | 35 |
| [Azure](#azure) | 34/38 | 941 | 8 | 15/20 | 16/20 | 10 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 3.9 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 25.6 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 50.9 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 23.1 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 24.4 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 13.4 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 1.8 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 3.4 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 24.7 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 42.6 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 31.7 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 34.7 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 22.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 54.8 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 53 | 0 | 35.6 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 19 | 0 | 21.9 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 18.4 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 8.1 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 20.2 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 33.3 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 22.0 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 17.6 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 10.2 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 4.1 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 10.6 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 16.6 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 29.5 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 57.7 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 21.5 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 22.5 |

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

**UI findings: 36**

<details><summary><b>DynamoDB</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Streams and triggers | /api/aws/sub/dynamodb~Music~streams/get/_settings → 404 |
| `HTTP_404` | Read/write capacity | /api/aws/sub/dynamodb~Music~capacity/get/_settings → 404 |
| `HTTP_404` | Encryption at rest | /api/aws/sub/dynamodb~Music~encryption/get/_settings → 404 |
| `HTTP_404` | Time to live | /api/aws/sub/dynamodb~Music~ttl/get/_settings → 404 |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Encryption key" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 17 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $95.88 (real aws would bill this resource) |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Rotation | /api/aws/sub/secretsmanager~my-secret~rotation/get/_settings → 404 |
| `HTTP_404` | Encryption key | /api/aws/sub/secretsmanager~my-secret~kmsKey/get/_settings → 404 |

</details>

<details><summary><b>SQS</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Purge messages | /api/aws/sub/sqs~MyQueue~purge/get/_settings → 404 |
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "MAXIMUM RECEIVES" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Encryption | /api/aws/sub/sqs~MyQueue~encryption/get/_settings → 404 |

</details>

<details><summary><b>EC2</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PAGE_ERROR` |  | during create: Cannot set properties of null (setting 'textContent') |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $46.63 (real aws would bill this resource) |
| `HTTP_404` |  | resource detail: /api/iam/users/new-user → 404 |

</details>

<details><summary><b>IAM</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 17 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $95.88 (real aws would bill this resource) |

</details>

<details><summary><b>KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 17 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $95.88 (real aws would bill this resource) |

</details>

<details><summary><b>Lambda</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>API Gateway</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>EventBridge</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>VPC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>KMS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Key rotation | /api/aws/sub/kms~e6aba2cf35ff444baeb1eef1a469ef79~rotation/get/_settings → 404 |

</details>

<details><summary><b>Systems Manager</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>SQS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "MAXIMUM RECEIVES" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>EventBridge</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |

</details>

<details><summary><b>VPC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $79.45 (real aws would bill this resource) |

</details>

<details><summary><b>Systems Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-gcp-tabs` | nano | ui | 0 | 1 | 4.2 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 28.7 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 22.6 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 22.4 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 7.0 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 25.7 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 14.6 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 14.6 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 15.2 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 4.6 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 16.0 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 18.9 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 17.4 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 5.5 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 11.1 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 7.8 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 13.4 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 10.7 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 7.9 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 11.5 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 10.3 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 23 | 0 | 28.6 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 23.3 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 20.9 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.6 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 24.1 |

<details><summary>❌ <code>nano-ui-gcp-tabs</code> log</summary>

```
RESULT boot_errors = []
RESULT createInstance = 200
RESULT createUser = 200
RESULT listUsers = ["appuser"]
RESULT deleteUser = 200
RESULT listUsersAfterDelete = 0
RESULT createDb = 200
RESULT listDatabases = ["appdb"]
RESULT createBackup = 200
RESULT listBackups = 1
RESULT eventsOk = true
RESULT eventActions = ["Create"]
RESULT PASS = true

NO CHECKS RAN (no PASS/FAIL lines recognised)
```

</details>

**UI findings: 35**

<details><summary><b>VPC Network</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ROUTING MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $134.18 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud KMS</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "KEY RING" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ALGORITHM" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "PROTECTION LEVEL" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Firestore</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "TYPE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LOCATION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud Functions</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LAST DEPLOYED" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Pub/Sub</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_501` |  | /api/gcp/pubsub/v1/projects/nano-project/subscriptions → 501 |
| `HTTP_501` |  | during create: /api/gcp/pubsub/v1/projects/nano-project/subscriptions → 501 |

</details>

<details><summary><b>Eventarc</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "REGION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>VPC Network</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $134.18 (real gcp would bill this resource) |

</details>

<details><summary><b>Pub/Sub</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 9 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $134.18 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 12 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $134.28 (real gcp would bill this resource) |

</details>

<details><summary><b>Compute Engine</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "ZONE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud SQL</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>API Gateway</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Secret Manager</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM & Admin</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $136.68 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud Functions</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud SQL</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Firestore</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>API Gateway</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Eventarc</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $134.18 (real gcp would bill this resource) |

</details>

<details><summary><b>Secret Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM & Admin</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $134.28 (real gcp would bill this resource) |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-azure-dp` | nano | ui | 0 | 5 | 0.9 |
| ❌ | `nano-ui-azure-home` | nano | ui | 1 | 1 | 3.8 |
| ❌ | `nano-ui-azure-operationalinsights` | nano | ui | 32 | 1 | 29.2 |
| ❌ | `offline-cli-azure` | offline | cli | 5 | 1 | 18.3 |
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 24.0 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 23.1 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 23.9 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 23.4 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 28.2 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 10.5 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.2 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 12.8 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 17.6 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 20.3 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 10.3 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 11.4 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 20.2 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 12.3 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 13.2 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 16.0 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 9.3 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 12.0 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 7.4 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 15.0 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 28.2 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 28.5 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 28.6 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 46.7 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 13.3 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 26.8 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 13.8 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 26.1 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 23.8 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 26.6 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 26.9 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 26.1 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 35.7 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 30.3 |

<details><summary>❌ <code>offline-cli-azure</code> log</summary>

```
== az against http://localhost:9000 subscription=sub-001 ==
azure-cli                         2.91.0
switched to Azure space: space-azure-default
FAIL az rest PUT Microsoft.Compute/virtualMachines :: ERROR: Forbidden({"detail":{"ok":false,"code":"tier_size_limit","reason":"free tier caps vm size at 'small'; requested 'Standard_D2s_v5' is 'medium'","active_tier":"free","resource_kind":"vm","requested_type":"Standard_D2s_v5","requested_size":"medium","max_size":"small","upgrade_to":"pro","docs":"https://cloudlearn.io/docs/tiers"}})
PASS az rest GET VM round-trip
PASS az rest PUT Microsoft.Storage/storageAccounts
PASS az rest PUT Microsoft.Sql/servers
PASS az rest PUT Microsoft.Sql/.../databases (real Postgres)
PASS az SQL DB connectionInfo surfaces real Postgres engine
RESULT pass=5 fail=1
```

</details>

<details><summary>❌ <code>nano-ui-azure-dp</code> log</summary>

```
===== Azure data-plane page validation =====
  [FAIL] Blob containers      undef:undefined create:undefined  | not in rail
  [FAIL] Storage queues       undef:undefined create:undefined  | not in rail
  [FAIL] Cosmos databases     undef:undefined create:undefined  | not in rail
  [FAIL] Key Vault secrets    undef:undefined create:undefined  | not in rail
  [FAIL] Key Vault keys       undef:undefined create:undefined  | not in rail

0/5 data-plane pages render cleanly (no 'undefined' + Create present)
```

</details>

<details><summary>❌ <code>nano-ui-azure-home</code> log</summary>

```
[PASS] home makes no requests to .../undefined
[FAIL] data-plane services present on the home dashboard :: 0 found
1/2 Azure home checks passed
```

</details>

<details><summary>❌ <code>nano-ui-azure-operationalinsights</code> log</summary>

```
[PASS] new workspace appears in the list
[PASS] every grid column is filled
[PASS] grid shows the pricing tier, retention and provisioning state
[PASS] cost-savings metrics updated by the create
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity log" renders
[PASS] tab "Access control (IAM)" renders
[PASS] tab "Tags" renders
[PASS] tab "Diagnose and solve problems" renders
[PASS] tab "Saved searches" renders
[PASS] tab "Tables" renders
[PASS] tab "Data sources" renders
[PASS] tab "Agents (keys)" renders
[PASS] tab "Usage and quota" renders
[PASS] tab "Properties" renders
[PASS] tab "Locks" renders
[PASS] tab "Metrics" renders
[PASS] Tables lists the built-in tables with their plan
[PASS] Agents tab shows the workspace ID and shared keys
[PASS] Usage tab lists the data-analysed quota
[PASS] saved search added in the blade is listed
[PASS] …and readable over ARM
[PASS] custom table added in the blade is listed
[PASS] …and readable over ARM
[PASS] data source added in the blade is listed
[PASS] delete removes the workspace from the list
[PASS] deleted workspace is gone from the ARM API
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

**UI findings: 10**

<details><summary><b>Key vaults</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Secrets | /azure-data/keyvault/kv-cloudlearn/secrets → 404 |
| `HTTP_404` | Keys | /azure-data/keyvault/kv-cloudlearn/keys → 404 |

</details>

<details><summary><b>API Management</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Policies | /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/Microsoft.ApiManagement/service/apim-cloudlearn/policies/policy?api-version=2023-05-01-preview → 404 |

</details>

<details><summary><b>Network Security Group</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Role Definition</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Entra ID / RBAC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Virtual networks</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $95.99 (real azure would bill this resource) |

</details>

<details><summary><b>Network Security Group</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Role Definition</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Entra ID / RBAC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $176.9 (real azure would bill this resource) |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-cores` | nano | core | 28 | 1 | 1.4 |
| ❌ | `nano-ui-budget-savings` | nano | ui | 3 | 2 | 31.5 |
| ❌ | `nano-ui-crawl` | nano | ui | 25 | 27 | 1494.7 |
| ❌ | `offline-console-actions` | offline | api | 261 | 20 | 10.6 |
| ❌ | `offline-cost-savings` | offline | api | 8 | 3 | 52.8 |
| ❌ | `offline-ui-crawl` | offline | ui | 30 | 22 | 1337.0 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 24.5 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 16 services crawled, 8 with findings
[offline/gcp] 16 services crawled, 10 with findings
[offline/azure] 20 services crawled, 4 with findings
UI crawl offline: 30/52 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":333,"static":223,"unimplemented":8,"partial":13}
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
have 2 to 34 labels of letters, digits, underscores and hyphens, each at most 63 characters, and at
assert False
FAILED tests/conformance/console_actions/test_azure_console.py::test_azure_action[azure.monitor.create] - AssertionError: Azure monitor.create PUT /subscriptions/sim-sub/resourceGroups/cloudlearn-rg/providers/Microsoft.Insights/metricAlerts/vyomi-conf-monitor → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"error":{"code":"BadRequest","message":"The request body must contain 'properties'."}}
assert False
FAILED tests/conformance/console_actions/test_azure_console.py::test_azure_action[azure.operationalinsights.create] - AssertionError: Azure operationalinsights.create PUT /subscriptions/sim-sub/resourceGroups/cloudlearn-rg/providers/Microsoft.OperationalInsights/workspaces/vyomi-conf-operationalinsights → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"error":{"code":"BadRequest","message":"The 'location' property is required when creating a workspace."}}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.cloudscheduler.create] - AssertionError: GCP cloudscheduler.create POST /api/gcp/cloudscheduler/jobs → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.cloudscheduler.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.container.create] - AssertionError: GCP container.create POST /api/gcp/container/clusters → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.container.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.iamcredentials.create] - AssertionError: GCP iamcredentials.create POST /api/gcp/iamcredentials/credentials → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.iamcredentials.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.redis.create] - AssertionError: GCP redis.create POST /api/gcp/redis/instances → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.redis.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
20 failed, 261 passed, 52 skipped in 10.17s
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
PASS: aws: creating a S3 bucket raises the space resource_count
PASS: aws: creating a S3 bucket raises aws savings
FAIL: aws: using the S3 bucket (5 × 2 MB uploads) raises savings :: $247.35 → $247.35 (real aws bills storage + requests)

== gcp: Cloud Storage bucket ==
PASS: gcp: creating a Cloud Storage bucket raises the space resource_count
PASS: gcp: creating a Cloud Storage bucket raises gcp savings
FAIL: gcp: using the Cloud Storage bucket (5 × 2 MB uploads) raises savings :: $175.32 → $175.32 (real gcp bills storage + requests)

== azure: Storage account ==
PASS: azure: creating a Storage account raises the space resource_count
PASS: azure: creating a Storage account raises azure savings
FAIL: azure: using the Storage account (5 × 2 MB uploads) raises savings :: $288.85 → $288.85 (real azure bills storage + requests)

== azure: Virtual machine (Standard_B1s) ==
PASS: azure: creating a VM raises the space resource_count
PASS: azure: a Standard_B1s VM adds its 730 h list price ($7.59) to Azure savings

RESULT fail=3
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 16 services crawled, 11 with findings
[nano/gcp] 16 services crawled, 11 with findings
[nano/azure] 20 services crawled, 5 with findings
UI crawl nano: 25/52 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":326,"unimplemented":37,"static":140,"partial":14}
```

</details>

<details><summary>❌ <code>nano-cores</code> log</summary>

```
INTERNALERROR>     self._register_setup_module_fixture()
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/_pytest/python.py", line 597, in _register_setup_module_fixture
INTERNALERROR>     self.obj, ("setUpModule", "setup_module")
INTERNALERROR>     ^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/_pytest/python.py", line 310, in obj
INTERNALERROR>     self._obj = obj = self._getobj()
INTERNALERROR>                       ^^^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/_pytest/python.py", line 581, in _getobj
INTERNALERROR>     return importtestmodule(self.path, self.config)
INTERNALERROR>            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/_pytest/python.py", line 528, in importtestmodule
INTERNALERROR>     mod = import_path(
INTERNALERROR>           ^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/_pytest/pathlib.py", line 640, in import_path
INTERNALERROR>     importlib.import_module(module_name)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/importlib/__init__.py", line 90, in import_module
INTERNALERROR>     return _bootstrap._gcd_import(name[level:], package, level)
INTERNALERROR>            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
INTERNALERROR>   File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
INTERNALERROR>   File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
INTERNALERROR>   File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/_pytest/assertion/rewrite.py", line 185, in exec_module
INTERNALERROR>     exec(co, module.__dict__)
INTERNALERROR>   File "/home/runner/work/appliance/appliance/tests/conformance/test_azure_app_core.py", line 112, in <module>
INTERNALERROR>     sys.exit(1 if FAIL else 0)
INTERNALERROR> SystemExit: 0

no tests ran in 1.08s
mainloop: caught unexpected SystemExit!
```

</details>

<details><summary>❌ <code>nano-ui-budget-savings</code> log</summary>

```
[PASS] budget returns 200 status 200
[PASS] budget has cpu/memory shape 
[PASS] spaces carry cost_savings {"resource_count":0,"savings_usd":0,"by_provider":{"aws":0,"gcp":0,"azure":0},"period":"monthly"}
[FAIL] resource_count rises after create 0 → 0
[FAIL] azure savings rise after create 0 → 0
```

</details>

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

37 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #171 | AWS |  | [aws] EventBridge: deliver to every target type through NATS (today only SQS targets) | 2026-10-28 |
| #169 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |
| #170 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-28 |
| #168 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-28 |
| #167 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-28 |
| #165 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |
| #166 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-28 |
| #163 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-28 |
| #164 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-28 |
| #161 | AWS | operation-added | AWS ec2: new operation GetCapacityManagerSupportabilityScores | 2026-10-28 |
| #162 | AWS | operation-changed | AWS ec2: operation CreateCapacityReservationFleet changed | 2026-10-28 |
| #160 | GCP | lifecycle | Google Kubernetes Engine: Change (October 27, 2026) | 2026-10-28 |
| #159 | GCP | lifecycle | Google Kubernetes Engine: No channel (deprecated) (October 27, 2026) | 2026-10-28 |
| #158 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (October 27, 2026) | 2026-10-28 |
| #156 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-27 |
| #157 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-27 |
| #155 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-27 |
| #154 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-27 |
| #153 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-27 |
| #152 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-27 |
| #151 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-27 |
| #150 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-27 |
| #149 | GCP |  | [gcp] Cloud Scheduler → Pub/Sub: scheduled message must reach gcloud pubsub subscriptions pull (offline appliance) | 2026-10-27 |
| #148 | GCP |  | [gcp] Cloud Scheduler: deliver httpTarget jobs with a real HTTP request (offline appliance) | 2026-10-27 |
| #147 | GCP |  | [gcp] Cloud Scheduler: fire jobs on time with a background timer (offline appliance) | 2026-10-27 |
| #146 | GCP | lifecycle | Google Kubernetes Engine: Change (October 26, 2026) | 2026-10-27 |
| #144 | GCP | lifecycle | Google Kubernetes Engine: Stable channel (October 26, 2026) | 2026-10-27 |
| #145 | GCP | lifecycle | Google Kubernetes Engine: No channel (deprecated) (October 26, 2026) | 2026-10-27 |
| #143 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (October 26, 2026) | 2026-10-27 |
| #142 | AWS | operation-added | AWS ec2: new operation GetImageFindings | 2026-10-27 |
| #139 | Azure | lifecycle | Retirement: Transition to using standard tests for single-step availability testing in Azure Monitor application insights by September 30, 2028 | 2026-10-27 |
| #138 | Azure | lifecycle | Retirement: Pod name dimension in AKS pod platform metrics | 2026-10-27 |
| #99 | AWS | operation-changed | AWS kms: operation GetPublicKey changed | 2026-10-26 |
| #98 | AWS | operation-added | AWS kms: new operation Encapsulate | 2026-10-26 |
| #97 | AWS | operation-added | AWS kms: new operation Decapsulate | 2026-10-26 |
| #92 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-26 |
| #90 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-26 |

## Nano ↔ offline parity gaps

- Azure operation **CreateChild** (azure_subresource_core): only in nano
- Azure operation **DeleteChild** (azure_subresource_core): only in nano
- Azure operation **ListChildren** (azure_subresource_core): only in nano
- Azure operation **UpdateChild** (azure_subresource_core): only in nano

## SDK operations without a test (292 of 936)

<details><summary>AWS · <code>apigateway_core</code> (nano) — 4</summary>

CreateDeployment, GetResources, GetRestApis, PutIntegration

</details>
<details><summary>AWS · <code>dynamodb_core</code> (nano) — 10</summary>

CreateTableRecord, DeleteItemRecord, DeleteTableRecord, GetItemRecord, PutItemRecord, QueryFilter, ScanFilter, TransactGetItems, TransactWriteItems, UpdateItemRecord

</details>
<details><summary>AWS · <code>elbv2_core</code> (nano) — 4</summary>

AddListenerCertificates, DescribeListenerCertificates, RemoveListenerCertificates, TagTarget

</details>
<details><summary>AWS · <code>eventbridge_core</code> (nano) — 1</summary>

RemoveTargets

</details>
<details><summary>AWS · <code>iam_core</code> (nano) — 3</summary>

GetPolicy, ListPolicies, ListRoles

</details>
<details><summary>AWS · <code>kms_core</code> (nano) — 2</summary>

SetKeyRotation, SetKeyState

</details>
<details><summary>AWS · <code>lambda_core</code> (nano) — 1</summary>

UpdateFunctionCode

</details>
<details><summary>AWS · <code>logs_core</code> (nano) — 6</summary>

AssociateKmsKey, DescribeQueries, DisassociateKmsKey, RunInsights, StopQuery, UntagLogGroup

</details>
<details><summary>AWS · <code>rds_core</code> (nano) — 5</summary>

CreateDbSnapshot, DescribeDbSnapshots, ModifyDbInstance, RebootDBInstance, SetStatus

</details>
<details><summary>AWS · <code>rds_data_core</code> (nano) — 1</summary>

ExecuteStatement

</details>
<details><summary>AWS · <code>s3_object_core</code> (nano) — 5</summary>

CopyObject, DeleteMarkerResponse, DeleteVersion, InsertSimpleDeleteMarker, ListAllBuckets

</details>
<details><summary>AWS · <code>secrets_core</code> (nano) — 1</summary>

PutValue

</details>
<details><summary>AWS · <code>sqs_core</code> (nano) — 1</summary>

SetQueueAttributes

</details>
<details><summary>AWS · <code>ssm_core</code> (nano) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>AWS · <code>vpc_core</code> (nano) — 1</summary>

AuthorizeSecurityGroupEgress

</details>
<details><summary>Azure · <code>azure_app_core</code> (nano) — 3</summary>

PutApp, PutJob, StopRuntime

</details>
<details><summary>Azure · <code>azure_appconfiguration_core</code> (nano) — 4</summary>

DeleteStore, ListKv, ListStores, PutStore

</details>
<details><summary>Azure · <code>azure_arm_core</code> (nano) — 2</summary>

GetPath, ListResourceGroups

</details>
<details><summary>Azure · <code>azure_blob_core</code> (nano) — 1</summary>

ListContainers

</details>
<details><summary>Azure · <code>azure_cognitiveservices_core</code> (nano) — 4</summary>

DeleteAccount, ListAccounts, PatchAccount, PutAccount

</details>
<details><summary>Azure · <code>azure_dns_core</code> (nano) — 4</summary>

DeleteZone, ListZones, PutRs, PutZone

</details>
<details><summary>Azure · <code>azure_iam_core</code> (nano) — 3</summary>

DeleteRoleAssignment, PutRoleAssignment, PutRoleDefinition

</details>
<details><summary>Azure · <code>azure_keyvault_keys_core</code> (nano) — 1</summary>

DeleteKey

</details>
<details><summary>Azure · <code>azure_operationalinsights_core</code> (nano) — 3</summary>

PutDataSource, PutTable, PutWorkspace

</details>
<details><summary>Azure · <code>azure_subresource_core</code> (nano) — 4</summary>

CreateChild, DeleteChild, ListChildren, UpdateChild

</details>
<details><summary>GCP · <code>gcp_cloudscheduler_core</code> (nano) — 2</summary>

PatchJob, SetState

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (nano) — 4</summary>

GetInstanceResp, InsertDatabase, InsertInstance, ListInstancesResp

</details>
<details><summary>GCP · <code>gcp_container_core</code> (nano) — 3</summary>

CreatePool, DeletePool, GetOp

</details>
<details><summary>GCP · <code>gcp_iam_core</code> (nano) — 4</summary>

CreateServiceAccount, DeleteServiceAccount, GetServiceAccount, ListServiceAccounts

</details>
<details><summary>GCP · <code>gcp_pubsub_core</code> (nano) — 1</summary>

GetSubscription

</details>
<details><summary>GCP · <code>gcp_redis_core</code> (nano) — 2</summary>

GetOp, PatchInstance

</details>
<details><summary>GCP · <code>gcp_secretmanager_core</code> (nano) — 1</summary>

SetVersionState

</details>
<details><summary>AWS · <code>apigateway_core</code> (offline) — 4</summary>

CreateDeployment, GetResources, GetRestApis, PutIntegration

</details>
<details><summary>AWS · <code>dynamodb_core</code> (offline) — 10</summary>

CreateTableRecord, DeleteItemRecord, DeleteTableRecord, GetItemRecord, PutItemRecord, QueryFilter, ScanFilter, TransactGetItems, TransactWriteItems, UpdateItemRecord

</details>
<details><summary>AWS · <code>elbv2_core</code> (offline) — 4</summary>

AddListenerCertificates, DescribeListenerCertificates, RemoveListenerCertificates, TagTarget

</details>
<details><summary>AWS · <code>eventbridge_core</code> (offline) — 1</summary>

RemoveTargets

</details>
<details><summary>AWS · <code>iam_core</code> (offline) — 3</summary>

GetPolicy, ListPolicies, ListRoles

</details>
<details><summary>AWS · <code>kms_core</code> (offline) — 2</summary>

SetKeyRotation, SetKeyState

</details>
<details><summary>AWS · <code>lambda_core</code> (offline) — 1</summary>

UpdateFunctionCode

</details>
<details><summary>AWS · <code>logs_core</code> (offline) — 6</summary>

AssociateKmsKey, DescribeQueries, DisassociateKmsKey, RunInsights, StopQuery, UntagLogGroup

</details>
<details><summary>AWS · <code>rds_core</code> (offline) — 5</summary>

CreateDbSnapshot, DescribeDbSnapshots, ModifyDbInstance, RebootDBInstance, SetStatus

</details>
<details><summary>AWS · <code>rds_data_core</code> (offline) — 1</summary>

ExecuteStatement

</details>
<details><summary>AWS · <code>s3_object_core</code> (offline) — 5</summary>

CopyObject, DeleteMarkerResponse, DeleteVersion, InsertSimpleDeleteMarker, ListAllBuckets

</details>
<details><summary>AWS · <code>secrets_core</code> (offline) — 1</summary>

PutValue

</details>
<details><summary>AWS · <code>sqs_core</code> (offline) — 1</summary>

SetQueueAttributes

</details>
<details><summary>AWS · <code>ssm_core</code> (offline) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>AWS · <code>vpc_core</code> (offline) — 1</summary>

AuthorizeSecurityGroupEgress

</details>
<details><summary>Azure · <code>azure_app_core</code> (offline) — 3</summary>

PutApp, PutJob, StopRuntime

</details>
<details><summary>Azure · <code>azure_appconfiguration_core</code> (offline) — 4</summary>

DeleteStore, ListKv, ListStores, PutStore

</details>
<details><summary>Azure · <code>azure_arm_core</code> (offline) — 2</summary>

GetPath, ListResourceGroups

</details>
<details><summary>Azure · <code>azure_blob_core</code> (offline) — 1</summary>

ListContainers

</details>
<details><summary>Azure · <code>azure_cognitiveservices_core</code> (offline) — 4</summary>

DeleteAccount, ListAccounts, PatchAccount, PutAccount

</details>
<details><summary>Azure · <code>azure_dns_core</code> (offline) — 4</summary>

DeleteZone, ListZones, PutRs, PutZone

</details>
<details><summary>Azure · <code>azure_iam_core</code> (offline) — 3</summary>

DeleteRoleAssignment, PutRoleAssignment, PutRoleDefinition

</details>
<details><summary>Azure · <code>azure_keyvault_keys_core</code> (offline) — 1</summary>

DeleteKey

</details>
<details><summary>Azure · <code>azure_operationalinsights_core</code> (offline) — 3</summary>

PutDataSource, PutTable, PutWorkspace

</details>
<details><summary>GCP · <code>gcp_cloudscheduler_core</code> (offline) — 2</summary>

PatchJob, SetState

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (offline) — 4</summary>

GetInstanceResp, InsertDatabase, InsertInstance, ListInstancesResp

</details>
<details><summary>GCP · <code>gcp_container_core</code> (offline) — 3</summary>

CreatePool, DeletePool, GetOp

</details>
<details><summary>GCP · <code>gcp_iam_core</code> (offline) — 4</summary>

CreateServiceAccount, DeleteServiceAccount, GetServiceAccount, ListServiceAccounts

</details>
<details><summary>GCP · <code>gcp_pubsub_core</code> (offline) — 1</summary>

GetSubscription

</details>
<details><summary>GCP · <code>gcp_redis_core</code> (offline) — 2</summary>

GetOp, PatchInstance

</details>
<details><summary>GCP · <code>gcp_secretmanager_core</code> (offline) — 1</summary>

SetVersionState

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-29T01:35:23+00:00 | 93/105 | 2464 | 85 | 81 | 14.3% |  |
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 98 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 104 | 14.3% |  |
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 104 | 14.3% |  |
|  | 0/0 | 0 | 0 | 98 | 14.3% |  |
|  | 0/0 | 0 | 0 | 106 | 14.3% |  |
|  | 0/0 | 0 | 0 | 106 | 14.3% |  |
|  | 0/0 | 0 | 0 | 78 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 106 | 14.3% |  |
|  | 0/0 | 0 | 0 | 97 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 104 | 14.3% |  |
|  | 0/0 | 0 | 0 | 78 | 14.3% |  |
|  | 0/0 | 0 | 0 | 106 | 14.3% |  |
|  | 0/0 | 0 | 0 | 85 | 14.3% |  |
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 87 | 14.3% |  |
|  | 0/0 | 0 | 0 | 84 | 14.3% |  |
|  | 0/0 | 0 | 0 | 78 | 14.3% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
