# Vyomi Conformance — hourly report

Run **2026-10-26T13:05:38+00:00** · commit `50a4d7daa3e7` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 13/22 | 509 | 108 | 1/43 | 5/38 | 171 | 12.8% (41/321) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 4/6 | 139 | 6 | 0/12 | 3/12 | 64 |
| [GCP](#gcp) | 3/4 | 17 | 1 | 0/12 | 1/12 | 76 |
| [Azure](#azure) | 5/6 | 107 | 1 | 1/19 | 1/14 | 31 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 4.6 |
| ❌ | `offline-sdk-python-aws` | offline | sdk-python | 81 | 5 | 310.6 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 12.5 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 20.5 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 40.4 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 13 | 0 | 8.4 |

<details><summary>❌ <code>offline-sdk-python-aws</code> log</summary>

```
  s3      parity 100.0%   pass=12 warn(deviation)=0 fail=0
  iam     parity 100.0%   pass=4 warn(deviation)=0 fail=0
  ec2     parity 100.0%   pass=2 warn(deviation)=0 fail=0
  sqs     parity 100.0%   pass=6 warn(deviation)=0 fail=0
  rds     parity 100.0%   pass=4 warn(deviation)=0 fail=0
  dynamodb  parity 100.0%   pass=5 warn(deviation)=0 fail=0
  gcp.storage  parity  50.0%   pass=2 warn(deviation)=1 fail=1
  gcp.vpc  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.compute  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.sql  parity 100.0%   pass=2 warn(deviation)=0 fail=0
  gcp.pubsub  parity  75.0%   pass=3 warn(deviation)=0 fail=1
  gcp.firestore  parity   0.0%   pass=0 warn(deviation)=0 fail=2
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
  ----  OVERALL parity  89.0%  pass=81 warn=5 fail=5 skip=0
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

**UI findings: 64**

<details><summary><b>EC2</b> (nano) — 9 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Instance ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "State" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Public IPv4" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Private IPv4" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "Instance ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "State" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Public IPv4" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Private IPv4" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 8 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Encryption key" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 11 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $98.48 (real aws would bill this resource) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Next rotation" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Encryption key" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Next rotation" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>EventBridge</b> (offline) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Status" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Targets" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 8 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $98.48 (real aws would bill this resource) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Status" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Targets" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "Sort key" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_5XX` |  | /api/dynamodb/tables → 500 |
| `HTTP_5XX` |  | during create: /api/dynamodb/tables → 500 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Lambda</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>S3</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>RDS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>SQS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>API Gateway</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>EventBridge</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>VPC</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>IAM</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>KMS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | /assets/lazy_backends.js → 404 |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>EC2</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Public IPv4" shows "-"/blank in 1 row(s) |
| `HTTP_404` |  | resource detail: /api/ec2/instances/i-9f400eb6cf0b → 404 |

</details>

<details><summary><b>S3</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Creation date" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "Creation date" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>IAM</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 11 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $98.48 (real aws would bill this resource) |

</details>

<details><summary><b>KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 11 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $98.48 (real aws would bill this resource) |

</details>

<details><summary><b>SQS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` |  | resource detail: /api/sqs/queues/ → 404 |

</details>

<details><summary><b>VPC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $98.48 (real aws would bill this resource) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-gcp-tabs` | nano | ui | 0 | 1 | 3.4 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 14.2 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 16.3 |
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

**UI findings: 76**

<details><summary><b>Cloud KMS</b> (nano) — 9 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "KEY RING" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ALGORITHM" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "PROTECTION LEVEL" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "KEY RING" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "ALGORITHM" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "PROTECTION LEVEL" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Firestore</b> (nano) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "TYPE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LOCATION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "TYPE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "LOCATION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "STATE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>VPC Network</b> (nano) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ROUTING MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "ROUTING MODE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Pub/Sub</b> (nano) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "RETENTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "ENCRYPTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "SUBSCRIPTIONS" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "RETENTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "ENCRYPTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "SUBSCRIPTIONS" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud Functions</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "LAST DEPLOYED" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "STATUS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "LAST DEPLOYED" shows "-"/blank in 1 row(s) |

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

<details><summary><b>Compute Engine</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PAGE_ERROR` |  | during create: Cannot set properties of null (setting 'textContent') |
| `PLACEHOLDER_CELL` |  | after create: column "ZONE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |
| `PLACEHOLDER_CELL` |  | resource detail: column "ZONE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Cloud Functions</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATUS" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |
| `PLACEHOLDER_CELL` |  | resource detail: column "STATUS" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>VPC Network</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |
| `PLACEHOLDER_CELL` |  | resource detail: column "IPV4 RANGE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Eventarc</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "REGION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

</details>

<details><summary><b>Eventarc</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "REGION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

</details>

<details><summary><b>Firestore</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 1 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: gcp savings stayed $24.53 (real gcp would bill this resource) |

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

<details><summary><b>Cloud Storage</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_MISSING` |  | create: active space has no cost_savings metrics |

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
| ❌ | `offline-cli-azure` | offline | cli | 5 | 1 | 13.0 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.8 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.7 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 10.3 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 20.9 |

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
| ❌ | `nano-ui-crawl` | nano | ui | 1 | 42 | 633.5 |
| ❌ | `offline-console-actions` | offline | api | 229 | 17 | 7.0 |
| ❌ | `offline-cost-savings` | offline | api | 2 | 7 | 68.2 |
| ❌ | `offline-ui-crawl` | offline | ui | 5 | 33 | 585.1 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 22.5 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 9 with findings
[offline/gcp] 12 services crawled, 11 with findings
[offline/azure] 14 services crawled, 13 with findings
UI crawl offline: 5/38 services clean → tests/conformance/hourly/out/ui-offline.json
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
conf-test-vm-cf714507/start → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.stop] - AssertionError: GCP compute.stop POST /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-cf714507/stop → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.reset] - AssertionError: GCP compute.reset POST /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-cf714507/reset → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.compute.delete] - AssertionError: GCP compute.delete DELETE /api/gcp/compute/v1/projects/cloudlearn/zones/us-central1-a/instances/insert-conf-test-vm-cf714507 → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"NoSuchInstance"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.firestore.documents] - AssertionError: GCP firestore.documents GET /api/gcp/firestore/v1/projects/cloudlearn/databases/(default)-cf714507/documents → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.firestore.indexes] - AssertionError: GCP firestore.indexes GET /api/gcp/firestore/v1/projects/cloudlearn/databases/(default)-cf714507/collectionGroups/-/indexes → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.kms.create] - AssertionError: GCP kms.create POST /api/gcp/kms/keys → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"missing 'name'"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.secretmanager.create] - AssertionError: GCP secretmanager.create POST /api/gcp/secrets → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"missing 'name'"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.deleteObject] - AssertionError: GCP storage.deleteObject DELETE /api/gcp/storage/v1/b/vyomi-conf-gcs-cf714507/o/{object} → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"detail":"Object not found"}
assert False
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.storage.uploadObject] - AssertionError: GCP storage.uploadObject POST /api/gcp/storage/v1/b/vyomi-conf-gcs-cf714507/upload → HTTP 400 (expected one of (200, 201, 202, 204)). Body: {"detail":"missing 'file' field"}
assert False
17 failed, 229 passed, 10 skipped in 6.70s
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
FAIL: aws: creating a S3 bucket raises the space resource_count :: 16 → 16
FAIL: aws: creating a S3 bucket raises aws savings :: $155.7 → $155.7
FAIL: aws: using the S3 bucket (5 × 2 MB uploads) raises savings :: $155.7 → $155.7 (real aws bills storage + requests)

== gcp: Cloud Storage bucket ==
FAIL: gcp: creating a Cloud Storage bucket raises the space resource_count :: 17 → 17
FAIL: gcp: creating a Cloud Storage bucket raises gcp savings :: $100.57 → $100.57
FAIL: gcp: using the Cloud Storage bucket (5 × 2 MB uploads) raises savings :: $100.57 → $100.57 (real gcp bills storage + requests)

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
```

</details>

<details><summary>❌ <code>nano-cores</code> log</summary>

```
no tests ran in 0.74s
```

</details>

## New features since the last run

None.

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
| 2026-10-26T13:05:38+00:00 | 13/22 | 509 | 108 | 171 | 12.8% |  |
|  | 0/0 | 0 | 0 | 69 | 12.8% |  |
| 2026-10-26T08:41:08+00:00 | 1/2 | 20 | 1 | 86 | 10.3% | Fixed /api/spaces 500 (binary S3 objects), EC2/GCE create 500 (unwritable deploy dir) and Nano Azure home `providers/undefined/undefined` 404s; fixed 2 crawler bugs that hid most AWS/GCP findings; add |
| 2026-10-26T08:05:52+00:00 | 9/20 | 147 | 220 | 86 | 10.3% |  |
| 2026-10-26T07:46:18+00:00 | 9/20 | 137 | 228 | 86 | 10.3% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
