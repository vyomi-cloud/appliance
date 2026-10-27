# Vyomi Conformance — hourly report

Run **2026-10-27T05:34:11+00:00** · commit `6424bbe1d030` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 24/33 | 604 | 74 | 13/43 | 16/38 | 149 | 14.0% (45/321) |

> **Agent this run:** Fixed 2 offline UI findings (API Gateway Resources/Stages tab 404s; EventBridge rules Status/Targets/Event bus blank), added 2 tests, 0 regressions.

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 9/11 | 170 | 2 | 4/12 | 4/12 | 74 |
| [GCP](#gcp) | 6/7 | 29 | 1 | 0/12 | 2/12 | 43 |
| [Azure](#azure) | 7/8 | 122 | 1 | 9/19 | 10/14 | 32 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 3.4 |
| ❌ | `offline-sdk-python-aws` | offline | sdk-python | 87 | 1 | 312.8 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 12.5 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 3.1 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 21.8 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 40.7 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 13 | 0 | 10.7 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 15.8 |

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

**UI findings: 74**

<details><summary><b>EventBridge</b> (offline) — 27 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Status" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Targets" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |
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

<details><summary><b>EC2</b> (nano) — 15 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PAGE_ERROR` |  | during create: Cannot set properties of null (setting 'textContent') |
| `PLACEHOLDER_CELL` |  | after create: column "Instance ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "State" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Public IPv4" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Private IPv4" shows "-"/blank in 1 row(s) |
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

<details><summary><b>Secrets Manager</b> (offline) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Encryption key" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 15 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |

</details>

<details><summary><b>VPC</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |
| `DEAD_TAB` | VPC details | clicking the tab changes nothing |
| `PLACEHOLDER_CELL` | Security groups | tab Security groups: column "Security group ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security groups | tab Security groups: column "Name" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>IAM</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 15 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |
| `PLACEHOLDER_CELL` | Users | tab Users: column "ARN" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>IAM</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $58.07 (real aws would bill this resource) |
| `HTTP_404` |  | resource detail: /api/iam/users/new-user → 404 |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |

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
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 15 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |

</details>

<details><summary><b>Lambda</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>DynamoDB</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |

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

<details><summary><b>DynamoDB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-gcp-tabs` | nano | ui | 0 | 1 | 3.4 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 5.8 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 16.5 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 15.3 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 5.3 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.5 |

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

**UI findings: 43**

<details><summary><b>VPC Network</b> (nano) — 8 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ROUTING MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $25.41 (real gcp would bill this resource) |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Network metrics | tab Network metrics: column "SUBNETS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Network metrics | tab Network metrics: column "FIREWALL RULES" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Network metrics | tab Network metrics: column "ROUTES" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud KMS</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "KEY RING" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ALGORITHM" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "PROTECTION LEVEL" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud Functions</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LAST DEPLOYED" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Firestore</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "TYPE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LOCATION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Compute Engine</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PAGE_ERROR` |  | during create: Cannot set properties of null (setting 'textContent') |
| `PLACEHOLDER_CELL` |  | after create: column "ZONE" shows "-"/blank in 1 row(s) |

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
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $25.41 (real gcp would bill this resource) |

</details>

<details><summary><b>Pub/Sub</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 5 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $25.41 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 7 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $25.41 (real gcp would bill this resource) |

</details>

<details><summary><b>Cloud Storage</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Activity | tab Activity: column "Detail" shows "-"/blank in 1 row(s) |

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
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $27.81 (real gcp would bill this resource) |

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
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $25.41 (real gcp would bill this resource) |

</details>

<details><summary><b>Secret Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM & Admin</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $25.41 (real gcp would bill this resource) |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-cli-azure` | offline | cli | 5 | 1 | 12.8 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.8 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 7.7 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 17.4 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 8.7 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 9.7 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 21.4 |

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

**UI findings: 32**

<details><summary><b>Resource groups</b> (nano) — 19 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `BAD_TEXT` |  | shows 'undefined' |
| `PLACEHOLDER_CELL` |  | list: column "Virtual Machines" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Storage accounts" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "SQL servers" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Service Bus" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Cosmos DB" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Function apps" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "API Management" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Virtual networks" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Network Security Group" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Event Grid topics" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Key vaults" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Role Definition" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Entra ID / RBAC" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Blob containers" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Cosmos databases" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Key Vault secrets" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Key Vault keys" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | list: column "Storage queues" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Virtual Machines</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PAGE_ERROR` |  | Cannot set properties of null (setting 'innerHTML') |

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

<details><summary><b>Blob containers</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | resource detail: /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined/demo1?api-version=2023-01-01 → 404 |

</details>

<details><summary><b>Cosmos databases</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | resource detail: /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined/demo1?api-version=2023-01-01 → 404 |

</details>

<details><summary><b>Key Vault secrets</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | resource detail: /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined/demo1?api-version=2023-01-01 → 404 |

</details>

<details><summary><b>Key Vault keys</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | resource detail: /subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/cloudlearn-rg/providers/undefined/undefined/demo1?api-version=2023-01-01 → 404 |

</details>

<details><summary><b>Storage queues</b> (nano) — 1 finding(s)</summary>

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
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $96.62 (real azure would bill this resource) |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-cores` | nano | core | 0 | 1 | 1.0 |
| ❌ | `nano-ui-crawl` | nano | ui | 13 | 30 | 903.9 |
| ❌ | `offline-console-actions` | offline | api | 232 | 14 | 7.3 |
| ❌ | `offline-cost-savings` | offline | api | 8 | 3 | 49.4 |
| ❌ | `offline-ui-crawl` | offline | ui | 16 | 22 | 866.8 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.8 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 23.1 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 8 with findings
[offline/gcp] 12 services crawled, 10 with findings
[offline/azure] 14 services crawled, 4 with findings
UI crawl offline: 16/38 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":205,"static":156,"unimplemented":30,"partial":23}
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
conf-test-vm-53a0ae60/start → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.stop] - AssertionError: GCP compute.stop POST /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-53a0ae60/stop → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.reset] - AssertionError: GCP compute.reset POST /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-53a0ae60/reset → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.delete] - AssertionError: GCP compute.delete DELETE /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-53a0ae60 → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.firestore.documents] - AssertionError: GCP firestore.documents GET /api/gcp/firestore/v1/projects/cloudlearn/databases/(default)-53a0ae60/documents → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.firestore.indexes] - AssertionError: GCP firestore.indexes GET /api/gcp/firestore/v1/projects/cloudlearn/databases/(default)-53a0ae60/collectionGroups/-/indexes → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.kms.create] - AssertionError: GCP kms.create POST /api/gcp/kms/keys → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"missing 'name'"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.secretmanager.create] - AssertionError: GCP secretmanager.create POST /api/gcp/secrets → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"missing 'name'"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.deleteObject] - AssertionError: GCP storage.deleteObject DELETE /api/gcp/storage/v1/b/vyomi-conf-gcs-53a0ae60/o/{object} → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Object not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.uploadObject] - AssertionError: GCP storage.uploadObject POST /api/gcp/storage/v1/b/vyomi-conf-gcs-53a0ae60/upload → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"detail":"missing 'file' field"}
assert False
14 failed, 232 passed, 10 skipped in 7.04s
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
PASS: aws: creating a S3 bucket raises the space resource_count
PASS: aws: creating a S3 bucket raises aws savings
FAIL: aws: using the S3 bucket (5 × 2 MB uploads) raises savings :: $116.94 → $116.94 (real aws bills storage + requests)

== gcp: Cloud Storage bucket ==
PASS: gcp: creating a Cloud Storage bucket raises the space resource_count
PASS: gcp: creating a Cloud Storage bucket raises gcp savings
FAIL: gcp: using the Cloud Storage bucket (5 × 2 MB uploads) raises savings :: $63.87 → $63.87 (real gcp bills storage + requests)

== azure: Storage account ==
PASS: azure: creating a Storage account raises the space resource_count
PASS: azure: creating a Storage account raises azure savings
FAIL: azure: using the Storage account (5 × 2 MB uploads) raises savings :: $97.12 → $97.12 (real azure bills storage + requests)

== azure: Virtual machine (Standard_B1s) ==
PASS: azure: creating a VM raises the space resource_count
PASS: azure: a Standard_B1s VM adds its 730 h list price ($7.59) to Azure savings

RESULT fail=3
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 12 services crawled, 8 with findings
[nano/gcp] 12 services crawled, 12 with findings
[nano/azure] 19 services crawled, 10 with findings
UI crawl nano: 13/43 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":200,"unimplemented":45,"partial":28,"static":108}
```

</details>

<details><summary>❌ <code>nano-cores</code> log</summary>

```
no tests ran in 0.78s
```

</details>

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

5 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
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
| 2026-10-27T05:34:11+00:00 | 24/33 | 604 | 74 | 149 | 14.0% | Fixed 2 offline UI findings (API Gateway Resources/Stages tab 404s; EventBridge rules Status/Targets/Event bus blank), added 2 tests, 0 regressions. |
| 2026-10-27T04:36:36+00:00 | 22/31 | 586 | 76 | 135 | 14.0% | Fixed 2 offline findings (DynamoDB/SQS detail 404 with empty name; Secrets Manager/KMS/Secret Manager/Eventarc not moving cost savings), added 2 tests, 0 regressions in re-run suites. |
| 2026-10-27T03:33:05+00:00 | 21/30 | 577 | 79 | 111 | 13.1% | Fixed 1 UI finding (offline GCP Eventarc triggers blank Region/State after default create), added 1 test, 0 known regressions (other suites not re-run). |
| 2026-10-27T02:34:16+00:00 | 19/28 | 570 | 80 | 144 | 13.1% | Fixed 2 offline UI findings (EC2 blank Public IPv4/DNS, S3 blank Creation date), added 2 API tests, ran only the 3 related suites (not the full green set). |
| 2026-10-27T01:37:42+00:00 | 17/26 | 564 | 80 | 164 | 13.1% | Fixed 1 UI finding group (GCP Pub/Sub topics grid blank Retention/Encryption/Subscriptions, Nano + offline), added 1 validator (2 suites), 0 regressions seen. |
| 2026-10-27T00:45:10+00:00 | 15/24 | 542 | 87 | 389 | 13.1% | Fixed 2 Nano UI findings (236 Azure HTTP_5XX "backend timeout" cascade; Azure storage Containers/Queues 501), added 2 validators, 0 regressions in the suites re-run. |
| 2026-10-26T23:41:36+00:00 | 14/23 | 530 | 94 | 418 | 12.8% | Fixed Nano's `/api/runtime/budget` 501 and its missing `cost_savings` (including Azure/GCP data-plane resources), added 1 Playwright validator, 0 regressions in the 5 green Nano suites re-run. |
| 2026-10-26T22:44:40+00:00 | 13/22 | 524 | 97 | 483 | 12.8% | Fixed 1 offline UI finding (EC2 resource detail 404), added 1 API test; the rest of the UI backlog is untouched this run. |
| 2026-10-26T21:37:59+00:00 | 13/22 | 516 | 103 | 216 | 12.8% | Fixed the Azure create-wizard harness mistake (17 services) and Azure VM cost savings, added 1 conformance check, 0 regressions known. |
| 2026-10-26T20:39:12+00:00 | 13/22 | 516 | 103 | 214 | 12.8% |  |
| 2026-10-26T19:35:34+00:00 | 13/22 | 516 | 103 | 228 | 12.8% |  |
| 2026-10-26T18:32:21+00:00 | 14/23 | 522 | 101 | 150 | 12.8% | Fixed the Azure create-flow harness false findings and Azure VM billing; 2 commits, 1 test file added, offline stack not restarted so the live fix is unverified end to end. |
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
