# Vyomi Conformance — hourly report

Run **not yet** · commit `` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 0/0 | 0 | 0 | 27/52 | 30/52 | 96 | 14.3% (46/322) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 0/0 | 0 | 0 | 5/16 | 8/16 | 53 |
| [GCP](#gcp) | 0/0 | 0 | 0 | 5/16 | 6/16 | 36 |
| [Azure](#azure) | 0/0 | 0 | 0 | 17/20 | 16/20 | 7 |

<a id="aws"></a>
## AWS

**UI findings: 53**

<details><summary><b>IAM</b> (nano) — 12 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $46.63 (real aws would bill this resource) |
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

<details><summary><b>RDS</b> (nano) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Endpoints | tab Endpoints: column "ENDPOINT" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PRIVATE IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 ADDRESS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "PUBLIC IPV4 DNS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SUBNET ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SECURITY GROUPS" shows "-"/blank in 1 row(s) |
| `HTTP_404` | Modify | /api/aws/sub/rds~database-1~modify/get/_settings → 404 |

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
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 17 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $95.88 (real aws would bill this resource) |

</details>

<details><summary><b>VPC</b> (offline) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $79.45 (real aws would bill this resource) |
| `DEAD_TAB` | VPC details | clicking the tab changes nothing |
| `PLACEHOLDER_CELL` | Security groups | tab Security groups: column "Security group ID" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security groups | tab Security groups: column "Name" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>IAM</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 17 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $95.88 (real aws would bill this resource) |
| `PLACEHOLDER_CELL` | Users | tab Users: column "ARN" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>S3</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Default encryption | /api/aws/sub/s3~my-bucket-cloudlearn~encryption/get/_settings → 404 |
| `HTTP_404` | Block Public Access | /api/aws/sub/s3~my-bucket-cloudlearn~blockPublic/get/_settings → 404 |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>KMS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 17 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $95.88 (real aws would bill this resource) |

</details>

<details><summary><b>EC2</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

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

<details><summary><b>EventBridge</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: aws savings stayed $76.95 (real aws would bill this resource) |

</details>

<details><summary><b>Systems Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

**UI findings: 36**

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

<details><summary><b>Eventarc</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "REGION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "STATE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Metrics | tab Metrics: column "EVENT FILTERS" shows "-"/blank in 1 row(s) |

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

**UI findings: 7**

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

## New features since the last run

| Target | Cloud | Service | Kind | Feature | SDK test |
|---|---|---|---|---|---|
| offline | AWS | Systems Manager | service | Systems Manager | — |
| offline | AWS | Systems Manager | tab | Overview | — |
| offline | AWS | Systems Manager | tab | Activity | — |
| offline | AWS | Systems Manager | tab | Tags | — |
| offline | AWS | Systems Manager | tab | Value | — |
| offline | AWS | Systems Manager | tab | History | — |
| offline | AWS | Systems Manager | tab | Properties | — |
| offline | AWS | Systems Manager | tab | Monitoring | — |
| offline | AWS | Systems Manager | create_field | Name | — |
| offline | AWS | Systems Manager | create_field | Type (String, StringList or SecureString) | — |
| offline | AWS | Systems Manager | create_field | Tier (Standard or Advanced) | — |
| offline | AWS | Systems Manager | create_field | Value | — |
| offline | AWS | Systems Manager | create_field | Description | — |
| offline | AWS | Systems Manager | column | Name | — |
| offline | AWS | Systems Manager | column | Type | — |
| offline | AWS | Systems Manager | column | Tier | — |
| offline | AWS | Systems Manager | column | Version | — |
| offline | AWS | Systems Manager | column | Data type | — |
| offline | AWS | Systems Manager | column | Last modified | — |
| offline | AWS | Systems Manager | action | history | — |
| offline | AWS | Systems Manager | action | delete | — |
| offline | AWS | Step Functions | service | Step Functions | — |
| offline | AWS | Step Functions | tab | Overview | — |
| offline | AWS | Step Functions | tab | Activity | — |
| offline | AWS | Step Functions | tab | Tags | — |
| offline | AWS | Step Functions | tab | Executions | — |
| offline | AWS | Step Functions | tab | Definition | — |
| offline | AWS | Step Functions | tab | Versions | — |
| offline | AWS | Step Functions | tab | Aliases | — |
| offline | AWS | Step Functions | tab | Properties | — |
| offline | AWS | Step Functions | tab | Monitoring | — |
| offline | AWS | Step Functions | create_field | State machine name | — |
| offline | AWS | Step Functions | create_field | Type (STANDARD or EXPRESS) | — |
| offline | AWS | Step Functions | create_field | Execution role ARN | — |
| offline | AWS | Step Functions | create_field | Definition (Amazon States Language) | — |
| offline | AWS | Step Functions | column | Name | — |
| offline | AWS | Step Functions | column | Type | — |
| offline | AWS | Step Functions | column | Status | — |
| offline | AWS | Step Functions | column | States | — |
| offline | AWS | Step Functions | column | Executions | — |
| offline | AWS | Step Functions | column | Created | — |
| offline | AWS | Step Functions | action | executions | — |
| offline | AWS | Step Functions | action | versions | — |
| offline | AWS | Step Functions | action | aliases | — |
| offline | AWS | Step Functions | action | delete | — |
| offline | AWS | CloudWatch Logs | service | CloudWatch Logs | — |
| offline | AWS | CloudWatch Logs | tab | Overview | — |
| offline | AWS | CloudWatch Logs | tab | Activity | — |
| offline | AWS | CloudWatch Logs | tab | Tags | — |
| offline | AWS | CloudWatch Logs | tab | Log streams | — |
| offline | AWS | CloudWatch Logs | tab | Log events | — |
| offline | AWS | CloudWatch Logs | tab | Metric filters | — |
| offline | AWS | CloudWatch Logs | tab | Subscription filters | — |
| offline | AWS | CloudWatch Logs | tab | Properties | — |
| offline | AWS | CloudWatch Logs | create_field | Log group name | — |
| offline | AWS | CloudWatch Logs | create_field | Retention (days, 0 = never expire) | — |
| offline | AWS | CloudWatch Logs | create_field | Log class | — |
| offline | AWS | CloudWatch Logs | column | Log group | — |
| offline | AWS | CloudWatch Logs | column | Log class | — |
| offline | AWS | CloudWatch Logs | column | Retention | — |
| offline | AWS | CloudWatch Logs | column | Log streams | — |
| offline | AWS | CloudWatch Logs | column | Metric filters | — |
| offline | AWS | CloudWatch Logs | column | Stored bytes | — |
| offline | AWS | CloudWatch Logs | column | Creation time | — |
| offline | AWS | CloudWatch Logs | action | streams | — |
| offline | AWS | CloudWatch Logs | action | events | — |
| offline | AWS | CloudWatch Logs | action | metric-filters | — |
| offline | AWS | CloudWatch Logs | action | subscription-filters | — |
| offline | AWS | CloudWatch Logs | action | delete | — |
| offline | AWS | Elastic Load Balancing | service | Elastic Load Balancing | — |
| offline | AWS | Elastic Load Balancing | tab | Overview | — |
| offline | AWS | Elastic Load Balancing | tab | Activity | — |
| offline | AWS | Elastic Load Balancing | tab | Tags | — |
| offline | AWS | Elastic Load Balancing | tab | Details | — |
| offline | AWS | Elastic Load Balancing | tab | Configuration | — |
| offline | AWS | Elastic Load Balancing | create_field | Load balancer name | — |
| offline | AWS | Elastic Load Balancing | create_field | Type (application, network, gateway) | — |
| offline | AWS | Elastic Load Balancing | create_field | Scheme (internet-facing, internal) | — |
| offline | AWS | Elastic Load Balancing | column | Name | — |
| offline | AWS | Elastic Load Balancing | column | DNS name | — |
| offline | AWS | Elastic Load Balancing | column | State | — |
| offline | AWS | Elastic Load Balancing | column | Type | — |
| offline | AWS | Elastic Load Balancing | column | Scheme | — |
| offline | AWS | Elastic Load Balancing | column | VPC ID | — |
| offline | AWS | Elastic Load Balancing | column | Availability Zones | — |
| offline | AWS | Elastic Load Balancing | column | Date created | — |
| offline | AWS | Elastic Load Balancing | action | loadBalancers | — |
| offline | AWS | Elastic Load Balancing | action | targetGroups | — |
| offline | AWS | Elastic Load Balancing | action | listeners | — |
| offline | AWS | Elastic Load Balancing | action | delete | — |
| offline | GCP | Firestore | column | State | — |
| offline | GCP | VPC Network | column | IPv4 range | — |
| offline | GCP | Cloud Scheduler | service | Cloud Scheduler | — |
| offline | GCP | Cloud Scheduler | tab | Overview | — |
| offline | GCP | Cloud Scheduler | tab | Last execution | — |
| offline | GCP | Cloud Scheduler | tab | Target | — |
| offline | GCP | Cloud Scheduler | tab | Retry policy | — |
| offline | GCP | Cloud Scheduler | tab | Schedule | — |
| offline | GCP | Cloud Scheduler | tab | Properties | — |
| offline | GCP | Cloud Scheduler | tab | JSON | — |

## Upstream changes (AWS / GCP / Azure backlog)

7 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
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
|  | 0/0 | 0 | 0 | 96 | 14.3% |  |
| 2026-10-27T19:14:57+00:00 | 78/81 | 1213 | 5 | 6 | 28.0% |  |
| 2026-10-27T18:08:29+00:00 | 76/79 | 1167 | 7 | 10 | 20.2% |  |
| 2026-10-27T17:09:42+00:00 | 74/77 | 1122 | 6 | 7 | 16.5% |  |
| 2026-10-27T16:09:07+00:00 | 73/76 | 1112 | 8 | 11 | 16.5% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
