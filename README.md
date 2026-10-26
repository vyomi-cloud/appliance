# Vyomi Conformance — hourly report

Run **2026-10-26T17:45:15+00:00** · commit `d044b33fa2e2` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 13/22 | 515 | 104 | 1/43 | 3/38 | 260 | 12.8% (41/321) |

> **Agent this run:** Fixed 1 UI finding (offline EC2 detail tabs 404: missing GET /api/ec2/instances/{id}), added 1 api test, 0 regressions known.

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 4/6 | 145 | 2 | 0/12 | 1/12 | 160 |
| [GCP](#gcp) | 3/4 | 17 | 1 | 0/12 | 1/12 | 69 |
| [Azure](#azure) | 5/6 | 107 | 1 | 1/19 | 1/14 | 31 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 3.3 |
| ❌ | `offline-sdk-python-aws` | offline | sdk-python | 87 | 1 | 307.5 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 12.4 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 20.4 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 41.2 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 13 | 0 | 8.4 |

<details><summary>❌ <code>offline-sdk-python-aws</code> log</summary>

```
  s3      parity 100.0%   pass=12 warn(deviation)=0 fail=0
  iam     parity 100.0%   pass=4 warn(deviation)=0 fail=0
  ec2     parity 100.0%   pass=2 warn(deviation)=0 fail=0
  sqs     parity 100.0%   pass=6 warn(deviation)=0 fail=0
  rds     parity 100.0%   pass=4 warn(deviation)=0 fail=0
  dynamodb  parity 100.0%   pass=5 warn(deviation)=0 fail=0
  gcp.storage  parity 100.0%   pass=4 warn(deviation)=0 fail=0
  gcp.vpc  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.compute  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.sql  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.pubsub  parity 100.0%   pass=5 warn(deviation)=0 fail=0
  gcp.firestore  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.functions  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.iam  parity 100.0%   pass=6 warn(deviation)=0 fail=0
  azure.spaces  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  azure.sql  parity 100.0%   pass=3 warn(deviation)=0 fail=0
  azure.keyvault  parity  50.0%   pass=2 warn(deviation)=2 fail=0
  aws.kms  parity  50.0%   pass=1 warn(deviation)=1 fail=0
  aws.secretsmanager  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.kms  parity  50.0%   pass=1 warn(deviation)=1 fail=0
  gcp.secretmanager  parity 100.0%   pass=3 warn(deviation)=0 fail=0
  nats    parity 100.0%   pass=1 warn(deviation)=0 fail=0
  aws.eventbridge  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.eventarc  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  azure.eventgrid  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  aws.iam  parity 100.0%   pass=3 warn(deviation)=0 fail=0
  azure.rbac  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  aws.s3.minio  parity  75.0%   pass=3 warn(deviation)=0 fail=1
  ----  OVERALL parity  94.6%  pass=87 warn=4 fail=1 skip=0
===========================================================
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

**UI findings: 160**

<details><summary><b>EventBridge</b> (offline) — 28 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Status" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Targets" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 9 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $99.73 (real aws would bill this resource) |
| `PLACEHOLDER_CELL` |  | resource detail: column "STATUS" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "TARGETS" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Overview | tab Overview: column "STATUS" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Overview | tab Overview: column "TARGETS" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Tags | tab Tags: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Tags | tab Tags: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Rule details | tab Rule details: column "STATUS" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Rule details | tab Rule details: column "TARGETS" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Targets | tab Targets: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Targets | tab Targets: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Event pattern | tab Event pattern: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Event pattern | tab Event pattern: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Invocations | tab Invocations: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Invocations | tab Invocations: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Properties | tab Properties: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Properties | tab Properties: column "TARGETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Properties | tab Properties: column "state" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Properties | tab Properties: column "target_count" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Permissions | tab Permissions: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Permissions | tab Permissions: column "TARGETS" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>EC2</b> (offline) — 20 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Public IPv4" shows "-"/blank in 1 row(s) |
| `HTTP_404` |  | resource detail: /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Overview | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Activity | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Tags | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Details | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Status and alarms | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Monitoring | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `DEAD_TAB` | Monitoring | clicking the tab changes nothing |
| `HTTP_404` | Networking | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 DNS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SUBNET ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SECURITY GROUPS" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Security | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "LAUNCH TIME" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Storage | /api/ec2/instances/i-8e774bcaf2db → 404 |
| `HTTP_404` | Connect | /api/ec2/instances/i-8e774bcaf2db → 404 |

</details>

<details><summary><b>EC2</b> (nano) — 15 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Instance ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "State" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Public IPv4" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Private IPv4" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `DEAD_TAB` | Monitoring | clicking the tab changes nothing |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PRIVATE IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 DNS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SUBNET ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SECURITY GROUPS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "LAUNCH TIME" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (offline) — 13 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `HTTP_404` |  | resource detail: /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Overview | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Activity | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Tags | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Explore items | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Explore items | /api/dynamodb/tables//items → 404 |
| `HTTP_404` | Query/Scan | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Indexes | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Streams and triggers | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Read/write capacity | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Encryption at rest | /api/dynamodb/tables/ → 404 |
| `HTTP_404` | Time to live | /api/dynamodb/tables/ → 404 |

</details>

<details><summary><b>IAM</b> (nano) — 12 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `HTTP_404` |  | resource detail: /api/iam/users/new-user → 404 |
| `HTTP_404` | Overview | /api/iam/users/new-user → 404 |
| `HTTP_404` | Users | /api/iam/users/new-user → 404 |
| `HTTP_404` | User groups | /api/iam/users/new-user → 404 |
| `HTTP_404` | Roles | /api/iam/users/new-user → 404 |
| `HTTP_404` | Policies | /api/iam/users/new-user → 404 |
| `HTTP_404` | Identity providers | /api/iam/users/new-user → 404 |
| `HTTP_404` | Password policy | /api/iam/users/new-user → 404 |
| `HTTP_404` | Password policy | /api/aws/sub/iam~new-user~passwordPolicy/get/_settings → 404 |
| `HTTP_404` | Access Analyzer | /api/iam/users/new-user → 404 |
| `HTTP_404` | Access Analyzer | /api/aws/sub/iam~new-user~accessAdvisor/get/_settings → 404 |

</details>

<details><summary><b>SQS</b> (offline) — 12 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | resource detail: /api/sqs/queues/ → 404 |
| `HTTP_404` | Overview | /api/sqs/queues/ → 404 |
| `HTTP_404` | Activity | /api/sqs/queues/ → 404 |
| `HTTP_404` | Tags | /api/sqs/queues/ → 404 |
| `HTTP_404` | Send and receive messages | /api/sqs/queues/ → 404 |
| `HTTP_404` | Purge messages | /api/sqs/queues/ → 404 |
| `HTTP_404` | Configuration | /api/sqs/queues/ → 404 |
| `HTTP_404` | Dead-letter queue | /api/sqs/queues/ → 404 |
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "MAXIMUM RECEIVES" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Encryption | /api/sqs/queues/ → 404 |
| `HTTP_404` | Access policy | /api/sqs/queues/ → 404 |
| `HTTP_404` | Monitoring | /api/sqs/queues/ → 404 |

</details>

<details><summary><b>RDS</b> (nano) — 9 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Endpoints | tab Endpoints: column "ENDPOINT" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PRIVATE IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 DNS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SUBNET ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SECURITY GROUPS" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Modify | /api/aws/sub/rds~database-1~modify/get/_settings → 404 |

</details>

<details><summary><b>DynamoDB</b> (nano) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Streams and triggers | /api/aws/sub/dynamodb~Music~streams/get/_settings → 404 |
| `HTTP_404` | Read/write capacity | /api/aws/sub/dynamodb~Music~capacity/get/_settings → 404 |
| `HTTP_404` | Encryption at rest | /api/aws/sub/dynamodb~Music~encryption/get/_settings → 404 |
| `HTTP_404` | Time to live | /api/aws/sub/dynamodb~Music~ttl/get/_settings → 404 |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Rotation | /api/aws/sub/secretsmanager~my-secret~rotation/get/_settings → 404 |
| `HTTP_404` | Encryption key | /api/aws/sub/secretsmanager~my-secret~kmsKey/get/_settings → 404 |

</details>

<details><summary><b>RDS</b> (offline) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Endpoints | tab Endpoints: column "ENDPOINT" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PRIVATE IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 DNS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SUBNET ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SECURITY GROUPS" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>SQS</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Purge messages | /api/aws/sub/sqs~MyQueue~purge/get/_settings → 404 |
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "MAXIMUM RECEIVES" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Encryption | /api/aws/sub/sqs~MyQueue~encryption/get/_settings → 404 |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Encryption key" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 12 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $99.73 (real aws would bill this resource) |

</details>

<details><summary><b>S3</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Default encryption | /api/aws/sub/s3~my-bucket-cloudlearn~encryption/get/_settings → 404 |
| `HTTP_404` | Block Public Access | /api/aws/sub/s3~my-bucket-cloudlearn~blockPublic/get/_settings → 404 |

</details>

<details><summary><b>VPC</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $99.73 (real aws would bill this resource) |
| `DEAD_TAB` | VPC details | clicking the tab changes nothing |
| `PLACEHOLDER_CELL` | Security groups | tab Security groups: column "Security group ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security groups | tab Security groups: column "Name" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>IAM</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 12 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $99.73 (real aws would bill this resource) |
| `PLACEHOLDER_CELL` | Users | tab Users: column "ARN" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>KMS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `HTTP_404` | Key rotation | /api/aws/sub/kms~73fa60eef6724adea09659dd12668631~rotation/get/_settings → 404 |

</details>

<details><summary><b>API Gateway</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Resources | /api/apigateway/apis/MyApi/resources → 404 |
| `HTTP_404` | Stages | /api/apigateway/apis/MyApi/stages → 404 |

</details>

<details><summary><b>KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 12 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $99.73 (real aws would bill this resource) |

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

<details><summary><b>S3</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Creation date" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-gcp-tabs` | nano | ui | 0 | 1 | 3.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 20.8 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 14.3 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 4.9 |

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

**UI findings: 69**

<details><summary><b>VPC Network</b> (nano) — 8 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ROUTING MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Network metrics | tab Network metrics: column "SUBNETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Network metrics | tab Network metrics: column "FIREWALL RULES" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Network metrics | tab Network metrics: column "ROUTES" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud KMS</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "KEY RING" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ALGORITHM" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "PROTECTION LEVEL" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Firestore</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "TYPE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LOCATION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Pub/Sub</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "RETENTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ENCRYPTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "SUBSCRIPTIONS" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Eventarc</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "REGION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Metrics | tab Metrics: column "EVENT FILTERS" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Pub/Sub</b> (offline) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "RETENTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ENCRYPTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "SUBSCRIPTIONS" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud Functions</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LAST DEPLOYED" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Eventarc</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "REGION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>Compute Engine</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "ZONE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud Functions</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>Firestore</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>VPC Network</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud Storage</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud Storage</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>IAM & Admin</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

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
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>Cloud SQL</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>API Gateway</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Secret Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-cli-azure` | offline | cli | 5 | 1 | 15.4 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 10.3 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 17.3 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 9.8 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 20.6 |

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

**UI findings: 31**

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
| ❌ | `nano-cores` | nano | core | 0 | 1 | 1.0 |
| ❌ | `nano-ui-crawl` | nano | ui | 1 | 42 | 786.7 |
| ❌ | `offline-console-actions` | offline | api | 231 | 15 | 7.1 |
| ❌ | `offline-cost-savings` | offline | api | 2 | 7 | 68.1 |
| ❌ | `offline-ui-crawl` | offline | ui | 3 | 35 | 775.4 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 22.6 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 11 with findings
[offline/gcp] 12 services crawled, 11 with findings
[offline/azure] 14 services crawled, 13 with findings
UI crawl offline: 3/38 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":101,"partial":25,"unimplemented":52,"static":110}
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
conf-test-vm-062a0ad7/start → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.stop] - AssertionError: GCP compute.stop POST /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-062a0ad7/stop → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.reset] - AssertionError: GCP compute.reset POST /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-062a0ad7/reset → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.delete] - AssertionError: GCP compute.delete DELETE /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-062a0ad7 → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.firestore.documents] - AssertionError: GCP firestore.documents GET /api/gcp/firestore/v1/projects/cloudlearn/databases/(default)-062a0ad7/documents → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.firestore.indexes] - AssertionError: GCP firestore.indexes GET /api/gcp/firestore/v1/projects/cloudlearn/databases/(default)-062a0ad7/collectionGroups/-/indexes → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.kms.create] - AssertionError: GCP kms.create POST /api/gcp/kms/keys → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"missing 'name'"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.secretmanager.create] - AssertionError: GCP secretmanager.create POST /api/gcp/secrets → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"missing 'name'"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.deleteObject] - AssertionError: GCP storage.deleteObject DELETE /api/gcp/storage/v1/b/vyomi-conf-gcs-062a0ad7/o/{object} → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Object not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.uploadObject] - AssertionError: GCP storage.uploadObject POST /api/gcp/storage/v1/b/vyomi-conf-gcs-062a0ad7/upload → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"detail":"missing 'file' field"}
assert False
15 failed, 231 passed, 10 skipped in 6.83s
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
FAIL: aws: creating a S3 bucket raises the space resource_count :: 18 → 18
FAIL: aws: creating a S3 bucket raises aws savings :: $158.2 → $158.2
FAIL: aws: using the S3 bucket (5 × 2 MB uploads) raises savings :: $158.2 → $158.2 (real aws bills storage + requests)

== gcp: Cloud Storage bucket ==
FAIL: gcp: creating a Cloud Storage bucket raises the space resource_count :: 16 → 16
FAIL: gcp: creating a Cloud Storage bucket raises gcp savings :: $100.17 → $100.17
FAIL: gcp: using the Cloud Storage bucket (5 × 2 MB uploads) raises savings :: $100.17 → $100.17 (real gcp bills storage + requests)

== azure: Storage account ==
PASS: azure: creating a Storage account raises the space resource_count
PASS: azure: creating a Storage account raises azure savings
FAIL: azure: using the Storage account (5 × 2 MB uploads) raises savings :: $0.5 → $0.5 (real azure bills storage + requests)

RESULT fail=7
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 12 services crawled, 12 with findings
[nano/gcp] 12 services crawled, 12 with findings
[nano/azure] 19 services crawled, 18 with findings
UI crawl nano: 1/43 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":109,"partial":31,"static":62,"unimplemented":47}
```

</details>

<details><summary>❌ <code>nano-cores</code> log</summary>

```
no tests ran in 0.75s
```

</details>

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

2 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #92 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-26 |
| #90 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-26 |

## Nano ↔ offline parity gaps

- Azure operation **CreateChild** (azure_subresource_core): only in nano
- Azure operation **DeleteChild** (azure_subresource_core): only in nano
- Azure operation **ListChildren** (azure_subresource_core): only in nano
- Azure operation **UpdateChild** (azure_subresource_core): only in nano
- Azure service **Blob containers** (Blob containers): only in nano
- Azure service **Cosmos databases** (Cosmos databases): only in nano
- Azure service **Key Vault keys** (Key Vault keys): only in nano
- Azure service **Key Vault secrets** (Key Vault secrets): only in nano
- Azure service **Storage queues** (Storage queues): only in nano

## SDK operations without a test (118 of 436)

<details><summary>AWS · <code>apigateway_core</code> (nano) — 4</summary>

CreateDeployment, GetResources, GetRestApis, PutIntegration

</details>
<details><summary>AWS · <code>dynamodb_core</code> (nano) — 11</summary>

CreateTableRecord, DeleteItemRecord, DeleteTableRecord, GetItemRecord, PutItemRecord, QueryFilter, ScanFilter, SetTags, TransactGetItems, TransactWriteItems, UpdateItemRecord

</details>
<details><summary>AWS · <code>eventbridge_core</code> (nano) — 2</summary>

DeleteRule, RemoveTargets

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
<details><summary>AWS · <code>vpc_core</code> (nano) — 1</summary>

AuthorizeSecurityGroupEgress

</details>
<details><summary>Azure · <code>azure_arm_core</code> (nano) — 2</summary>

GetPath, ListResourceGroups

</details>
<details><summary>Azure · <code>azure_blob_core</code> (nano) — 1</summary>

ListContainers

</details>
<details><summary>Azure · <code>azure_iam_core</code> (nano) — 3</summary>

DeleteRoleAssignment, PutRoleAssignment, PutRoleDefinition

</details>
<details><summary>Azure · <code>azure_keyvault_keys_core</code> (nano) — 2</summary>

DeleteKey, GetKey

</details>
<details><summary>Azure · <code>azure_subresource_core</code> (nano) — 4</summary>

CreateChild, DeleteChild, ListChildren, UpdateChild

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (nano) — 6</summary>

DeleteInstance, GetInstanceResp, InsertDatabase, InsertInstance, ListInstances, ListInstancesResp

</details>
<details><summary>GCP · <code>gcp_iam_core</code> (nano) — 4</summary>

CreateServiceAccount, DeleteServiceAccount, GetServiceAccount, ListServiceAccounts

</details>
<details><summary>GCP · <code>gcp_pubsub_core</code> (nano) — 1</summary>

GetSubscription

</details>
<details><summary>GCP · <code>gcp_secretmanager_core</code> (nano) — 1</summary>

SetVersionState

</details>
<details><summary>AWS · <code>apigateway_core</code> (offline) — 4</summary>

CreateDeployment, GetResources, GetRestApis, PutIntegration

</details>
<details><summary>AWS · <code>dynamodb_core</code> (offline) — 11</summary>

CreateTableRecord, DeleteItemRecord, DeleteTableRecord, GetItemRecord, PutItemRecord, QueryFilter, ScanFilter, SetTags, TransactGetItems, TransactWriteItems, UpdateItemRecord

</details>
<details><summary>AWS · <code>eventbridge_core</code> (offline) — 2</summary>

DeleteRule, RemoveTargets

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
<details><summary>AWS · <code>vpc_core</code> (offline) — 1</summary>

AuthorizeSecurityGroupEgress

</details>
<details><summary>Azure · <code>azure_arm_core</code> (offline) — 2</summary>

GetPath, ListResourceGroups

</details>
<details><summary>Azure · <code>azure_blob_core</code> (offline) — 1</summary>

ListContainers

</details>
<details><summary>Azure · <code>azure_iam_core</code> (offline) — 3</summary>

DeleteRoleAssignment, PutRoleAssignment, PutRoleDefinition

</details>
<details><summary>Azure · <code>azure_keyvault_keys_core</code> (offline) — 2</summary>

DeleteKey, GetKey

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (offline) — 6</summary>

DeleteInstance, GetInstanceResp, InsertDatabase, InsertInstance, ListInstances, ListInstancesResp

</details>
<details><summary>GCP · <code>gcp_iam_core</code> (offline) — 4</summary>

CreateServiceAccount, DeleteServiceAccount, GetServiceAccount, ListServiceAccounts

</details>
<details><summary>GCP · <code>gcp_pubsub_core</code> (offline) — 1</summary>

GetSubscription

</details>
<details><summary>GCP · <code>gcp_secretmanager_core</code> (offline) — 1</summary>

SetVersionState

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-26T17:45:15+00:00 | 13/22 | 515 | 104 | 260 | 12.8% | Fixed 1 UI finding (offline EC2 detail tabs 404: missing GET /api/ec2/instances/{id}), added 1 api test, 0 regressions known. |
| 2026-10-26T16:30:13+00:00 | 13/22 | 517 | 102 | 169 | 12.8% | Fixed 2 product UI findings (offline S3 Creation date, offline Secrets Manager Encryption key) and 1 harness bug (Azure wizard blade, behind 17+ CRAWL_ERRORs per target), added 2 validators, 0 regress |
| 2026-10-26T15:30:03+00:00 | 13/22 | 516 | 103 | 188 | 12.8% |  |
| 2026-10-26T14:22:51+00:00 | 13/22 | 517 | 102 | 117 | 12.8% | Fixed 2 UI findings (crawler Azure wizard/blade cascade = harness bug; offline S3 blank "Creation date"), added 1 test, 0 regressions checked beyond touched suites; commits are local only — the push t |
| 2026-10-26T13:05:38+00:00 | 13/22 | 509 | 108 | 171 | 12.8% |  |
|  | 0/0 | 0 | 0 | 69 | 12.8% |  |
| 2026-10-26T08:41:08+00:00 | 1/2 | 20 | 1 | 86 | 10.3% | Fixed /api/spaces 500 (binary S3 objects), EC2/GCE create 500 (unwritable deploy dir) and Nano Azure home `providers/undefined/undefined` 404s; fixed 2 crawler bugs that hid most AWS/GCP findings; add |
| 2026-10-26T08:05:52+00:00 | 9/20 | 147 | 220 | 86 | 10.3% |  |
| 2026-10-26T07:46:18+00:00 | 9/20 | 137 | 228 | 86 | 10.3% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
