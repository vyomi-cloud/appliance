# Vyomi Conformance — hourly report

Run **2026-10-29T05:46:05+00:00** · commit `eaf80b5dc7ff` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 159/175 | 3589 | 54 | 35/57 | 49/52 | 44 | 34.4% (111/323) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 66/67 | 1013 | 2 | 13/16 | 13/16 | 10 |
| [GCP](#gcp) | 41/45 | 667 | 12 | 16/16 | 16/16 | 0 |
| [Azure](#azure) | 47/56 | 1197 | 15 | 6/25 | 20/20 | 34 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-eventbridge-row` | nano | ui | 2 | 2 | 16.1 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.2 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.5 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 16.0 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 8.0 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.5 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 22.2 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 12.0 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 14.6 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.3 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 3.8 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 14.6 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 49.9 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 12.7 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 10.6 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 11.4 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 9.0 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 20.8 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 22.5 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 15.0 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.5 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.6 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 14.6 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 9.0 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 6.4 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.1 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 1.5 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 2.0 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 5.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 24.5 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 42.9 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 30.8 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 35.8 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 20.8 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.3 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 46.2 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 53 | 0 | 38.8 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 19 | 0 | 23.5 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 20.8 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 8.2 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 20.1 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 35.0 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 23.6 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 17.5 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 10.3 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 3.9 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.6 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.9 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.4 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 10.7 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 15.4 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 21.7 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.4 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 29.3 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 56.7 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 15.7 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.5 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 9.0 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 21.7 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 22.4 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 9.3 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 9.8 |

<details><summary>❌ <code>nano-ui-aws-eventbridge-row</code> log</summary>

```
[FAIL] created rule is listed [["","Name","Event bus","Type","Status","Targets"],["","my-eventbridge-rule","default","EventPattern","available","0"]]
[FAIL] no placeholder cells in the row 
[PASS] rule survives a console reload ["my-eventbridge-rule"]
[PASS] no page error while opening the create wizard
```

</details>

**UI findings: 10**

<details><summary><b>EC2</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>EC2</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |

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
| ❌ | `nano-ui-gcp-create-defaults` | nano | ui | 27 | 9 | 66.6 |
| ❌ | `offline-api-gcp-grid-columns` | offline | api | 18 | 1 | 0.2 |
| ❌ | `offline-api-gcp-pubsub-savings` | offline | api | 7 | 1 | 13.1 |
| ❌ | `offline-ui-gcp-grid-defaults` | offline | ui | 38 | 1 | 0.7 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.9 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 27.4 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 22.9 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 3.8 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.2 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 3.7 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.2 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.7 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 23.5 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 3.7 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.5 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.6 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.2 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 11.6 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 6.6 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 9.7 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 1.4 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 7.9 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 18.9 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 11.4 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 8.3 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 1.7 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 1.8 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 1.6 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 5.2 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 3.4 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 3.6 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 3.7 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 3.5 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.6 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 23 | 0 | 23.9 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 20.8 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 65.8 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 19.8 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.0 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.5 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.4 |

<details><summary>❌ <code>offline-ui-gcp-grid-defaults</code> log</summary>

```
[PASS] apigateway: column 'Created' filled
[PASS] vpc: created resource listed
[PASS] vpc: column 'Name' filled
[FAIL] vpc: column 'Mode' filled 
[PASS] vpc: column 'Routing mode' filled
[PASS] vpc: column 'MTU' filled
[PASS] eventarc: created resource listed
[PASS] eventarc: column 'Name' filled
[PASS] eventarc: column 'Event provider' filled
[PASS] eventarc: column 'Destination' filled
[PASS] eventarc: column 'Region' filled
[PASS] eventarc: column 'State' filled
[PASS] secretmanager: created resource listed
[PASS] secretmanager: column 'Name' filled
[PASS] secretmanager: column 'Replication' filled
[PASS] secretmanager: column 'Created' filled
[PASS] secretmanager: column 'Latest version' filled
[PASS] kms: created resource listed
[PASS] kms: column 'Key name' filled
[PASS] kms: column 'Key ring' filled
[PASS] kms: column 'Purpose' filled
[PASS] kms: column 'Algorithm' filled
[PASS] kms: column 'Protection level' filled
[PASS] kms: column 'State' filled
[PASS] functions: created resource listed
[PASS] functions: column 'Name' filled
[PASS] functions: column 'Runtime' filled
[PASS] functions: column 'Status' filled
[PASS] functions: column 'Entry point' filled
[PASS] functions: column 'Last deployed' filled
```

</details>

<details><summary>❌ <code>offline-api-gcp-pubsub-savings</code> log</summary>

```
[PASS] console create topic
[PASS] topic raises resource_count (34 -> 36)
[PASS] topic raises gcp savings (169.25 -> 170.05)
[PASS] PUT create topic (client-library style)
[PASS] PUT topic raises resource_count (36 -> 38)
[PASS] PUT create subscription
[PASS] subscription raises resource_count (38 -> 40)
[FAIL] deleting them drops resource_count (40 -> 35) 34
```

</details>

<details><summary>❌ <code>offline-api-gcp-grid-columns</code> log</summary>

```
[PASS] create VPC network
[PASS] create Firestore database
[PASS] create Cloud Function
[PASS] vpc: created resource gridnet-aa1369 is listed
[PASS] vpc: column 'Name' (name) filled
[FAIL] vpc: column 'Mode' (mode) filled None
[PASS] vpc: column 'Routing mode' (routingConfig.routingMode) filled
[PASS] vpc: column 'MTU' (mtu) filled
[PASS] firestore: created resource griddb-aa1369 is listed
[PASS] firestore: column 'Database ID' (name) filled
[PASS] firestore: column 'Type' (type) filled
[PASS] firestore: column 'Location' (locationId) filled
[PASS] firestore: column 'Created' (createTime) filled
[PASS] functions: created resource gridfn-aa1369 is listed
[PASS] functions: column 'Name' (name) filled
[PASS] functions: column 'Runtime' (runtime) filled
[PASS] functions: column 'Status' (state) filled
[PASS] functions: column 'Entry point' (entryPoint) filled
[PASS] functions: column 'Last deployed' (updateTime) filled
```

</details>

<details><summary>❌ <code>nano-ui-gcp-create-defaults</code> log</summary>

```
[FAIL] API Gateway: the new resource is listed 
[FAIL] API Gateway: no placeholder cells []
[PASS] Secret Manager: service is on the rail
[FAIL] Secret Manager: create with defaults is accepted [] 
[FAIL] Secret Manager: the new resource is listed 
[FAIL] Secret Manager: no placeholder cells []
[PASS] Cloud Functions: service is on the rail
[PASS] Cloud Functions: create with defaults is accepted
[PASS] Cloud Functions: the new resource is listed
[PASS] Cloud Functions: no placeholder cells
[PASS] Firestore: service is on the rail
[PASS] Firestore: create with defaults is accepted
[PASS] Firestore: the new resource is listed
[PASS] Firestore: no placeholder cells
[PASS] VPC Network: service is on the rail
[PASS] VPC Network: create with defaults is accepted
[PASS] VPC Network: the new resource is listed
[PASS] VPC Network: no placeholder cells
[PASS] Cloud KMS: service is on the rail
[PASS] Cloud KMS: create with defaults is accepted
[PASS] Cloud KMS: the new resource is listed
[PASS] Cloud KMS: no placeholder cells
[PASS] Eventarc: service is on the rail
[PASS] Eventarc: create with defaults is accepted
[PASS] Eventarc: the new resource is listed
[PASS] Eventarc: no placeholder cells
[PASS] Pub/Sub: service is on the rail
[PASS] Pub/Sub: create with defaults is accepted
[PASS] Pub/Sub: the new resource is listed
[PASS] Pub/Sub: no placeholder cells
```

</details>

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-azure-app` | nano | ui | 28 | 1 | 41.9 |
| ❌ | `nano-ui-azure-appconfiguration` | nano | ui | 27 | 1 | 43.7 |
| ❌ | `nano-ui-azure-cognitiveservices` | nano | ui | 28 | 1 | 44.5 |
| ❌ | `nano-ui-azure-dns` | nano | ui | 27 | 1 | 44.4 |
| ❌ | `nano-ui-azure-flat-create` | nano | ui | 1 | 2 | 37.8 |
| ❌ | `nano-ui-azure-monitor` | nano | ui | 28 | 1 | 48.5 |
| ❌ | `nano-ui-azure-operationalinsights` | nano | ui | 32 | 1 | 48.3 |
| ❌ | `nano-ui-azure-savings` | nano | ui | 3 | 5 | 94.3 |
| ❌ | `offline-ui-azure-flat-create` | offline | ui | 1 | 2 | 36.9 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.9 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 27.2 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 3.7 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 11.2 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 10.6 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 3.8 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.3 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 8.7 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.0 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 47.6 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 10.3 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.3 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 5.2 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 6.8 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 12.7 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 5.9 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 6.4 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.1 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.1 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 20.8 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 3.0 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 2.1 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.5 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.2 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.3 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 20.4 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 25.0 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.1 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 6.6 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.1 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.2 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.6 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 19.8 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.0 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.5 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 22.8 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.5 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.3 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 27.9 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.6 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 10.1 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.3 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 49.5 |

<details><summary>❌ <code>nano-ui-azure-savings</code> log</summary>

```
[PASS] Storage account: ARM PUT ok
[FAIL] Storage account: resource_count rises 0 → 0
[FAIL] Storage account: azure savings rise 0 → 0
[PASS] Key vault: ARM PUT ok
[FAIL] Key vault: resource_count rises 0 → 0
[FAIL] Key vault: azure savings rise 0 → 0
[PASS] Virtual network: ARM PUT ok
[FAIL] Virtual network: resource_count rises 0 → 0
```

</details>

<details><summary>❌ <code>nano-ui-azure-flat-create</code> log</summary>

```
[PASS] Network Security Group service opens
[FAIL] NSG create with empty name is refused (blade stays open) :: 
[FAIL] validator ran :: locator.click: Timeout 30000ms exceeded.
```

</details>

<details><summary>❌ <code>offline-ui-azure-flat-create</code> log</summary>

```
[PASS] Network Security Group service opens
[FAIL] NSG create with empty name is refused (blade stays open) :: 
[FAIL] validator ran :: locator.click: Timeout 30000ms exceeded.
```

</details>

<details><summary>❌ <code>nano-ui-azure-app</code> log</summary>

```
[PASS] Container Apps is on the Nano Azure console rail
[PASS] service page says what runs below the Pro tier (control plane / Docker)
[PASS] create form has a realistic default name
[PASS] create form defaults a container image
[PASS] create with defaults returns 2xx
[PASS] new container app appears in the list
[PASS] every grid column is filled
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity log" renders
[PASS] tab "Access control (IAM)" renders
[PASS] tab "Tags" renders
[PASS] tab "Diagnose and solve problems" renders
[PASS] tab "Revisions and replicas" renders
[PASS] tab "Containers" renders
[PASS] tab "Scale" renders
[PASS] tab "Ingress" renders
[PASS] tab "Secrets" renders
[PASS] tab "Identity" renders
[PASS] tab "Properties" renders
[PASS] tab "Locks" renders
[PASS] tab "Metrics" renders
[PASS] Revisions tab lists the active revision
[PASS] Containers tab shows the image
[PASS] Ingress tab shows the application URL
[PASS] delete removes the app from the list
[PASS] deleted app is gone from the ARM API
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-azure-appconfiguration</code> log</summary>

```
[PASS] App Configuration is on the Nano Azure console rail
[PASS] service page explains what the service does
[PASS] create form has a realistic default name
[PASS] create form defaults the pricing tier to Standard
[PASS] create with defaults returns 2xx
[PASS] new store appears in the list
[PASS] every grid column is filled
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity log" renders
[PASS] tab "Access control (IAM)" renders
[PASS] tab "Tags" renders
[PASS] tab "Diagnose and solve problems" renders
[PASS] tab "Configuration explorer" renders
[PASS] tab "Geo-replication" renders
[PASS] tab "Access settings" renders
[PASS] tab "Identity" renders
[PASS] tab "Networking" renders
[PASS] tab "Properties" renders
[PASS] tab "Locks" renders
[PASS] tab "Metrics" renders
[PASS] Access settings lists keys with connection strings
[PASS] key-value created in the explorer is listed
[PASS] …and listKeyValue returns it
[PASS] delete removes the store from the list
[PASS] deleted store is gone from the ARM API
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-azure-cognitiveservices</code> log</summary>

```
[PASS] Azure AI services is on the Nano Azure console rail
[PASS] service page explains what the service does
[PASS] create form has a realistic default name
[PASS] create form defaults kind OpenAI and tier S0
[PASS] create with defaults returns 2xx
[PASS] new account appears in the list
[PASS] every grid column is filled
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity log" renders
[PASS] tab "Access control (IAM)" renders
[PASS] tab "Tags" renders
[PASS] tab "Diagnose and solve problems" renders
[PASS] tab "Keys and Endpoint" renders
[PASS] tab "Model deployments" renders
[PASS] tab "Quotas" renders
[PASS] tab "Identity" renders
[PASS] tab "Networking" renders
[PASS] tab "Properties" renders
[PASS] tab "Locks" renders
[PASS] tab "Metrics" renders
[PASS] Keys and Endpoint lists both keys and the endpoint
[PASS] deployment created in the blade is listed
[PASS] …and readable over ARM
[PASS] Quotas shows model quota usage
[PASS] delete removes the account from the list
[PASS] deleted account is gone from the ARM API
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-azure-dns</code> log</summary>

```
[PASS] DNS zones is on the Nano Azure console rail
[PASS] service page explains what the service does
[PASS] create form has a realistic default zone name
[PASS] create with defaults returns 2xx
[PASS] new zone appears in the list
[PASS] every grid column is filled
[PASS] grid shows the name servers and the SOA+NS record-set count
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity log" renders
[PASS] tab "Access control (IAM)" renders
[PASS] tab "Tags" renders
[PASS] tab "Diagnose and solve problems" renders
[PASS] tab "Recordsets" renders
[PASS] tab "Name servers" renders
[PASS] tab "Test query" renders
[PASS] tab "Properties" renders
[PASS] tab "Locks" renders
[PASS] tab "Metrics" renders
[PASS] Name servers lists the four delegation servers
[PASS] Recordsets lists the SOA and NS record sets
[PASS] record set added in the blade is listed
[PASS] …and readable over ARM
[PASS] Test query answers from the zone
[PASS] delete removes the zone from the list
[PASS] deleted zone is gone from the ARM API
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-azure-monitor</code> log</summary>

```
[PASS] Monitor alerts is on the Nano Azure console rail
[PASS] service page explains what the service does
[PASS] create form has a realistic default alert rule name
[PASS] create with defaults returns 2xx
[PASS] new alert rule appears in the list
[PASS] every grid column is filled
[PASS] grid shows severity, evaluation frequency and the scope
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity log" renders
[PASS] tab "Access control (IAM)" renders
[PASS] tab "Tags" renders
[PASS] tab "Diagnose and solve problems" renders
[PASS] tab "Condition" renders
[PASS] tab "Action groups" renders
[PASS] tab "Activity log alerts" renders
[PASS] tab "Autoscale settings" renders
[PASS] tab "Properties" renders
[PASS] tab "Locks" renders
[PASS] tab "Metrics" renders
[PASS] Condition shows the metric, operator, threshold and window
[PASS] action group added in the blade is listed
[PASS] …and readable over ARM
[PASS] activity log alert added in the blade is listed
[PASS] autoscale setting added in the blade is listed
[PASS] delete removes the alert rule from the list
[PASS] deleted alert rule is gone from the ARM API
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-azure-operationalinsights</code> log</summary>

```
[PASS] new workspace appears in the list
[PASS] every grid column is filled
[PASS] grid shows the pricing tier, retention and provisioning state
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
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

**UI findings: 34**

<details><summary><b>Virtual Machines</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Storage accounts</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>SQL servers</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Service Bus</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Cosmos DB</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Function apps</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>API Management</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Event Grid topics</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Key vaults</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Container Apps</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>App Configuration</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>DNS zones</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Monitor alerts</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Log Analytics</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Azure AI services</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |
| `SAVINGS_NOT_UPDATED` |  | create: azure savings stayed $0 (real azure would bill this resource) |

</details>

<details><summary><b>Virtual networks</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |

</details>

<details><summary><b>Network Security Group</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |

</details>

<details><summary><b>Role Definition</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |

</details>

<details><summary><b>Entra ID / RBAC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 0 after creating a resource |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 35 | 22 | 763.0 |
| ❌ | `offline-ui-crawl` | offline | ui | 49 | 3 | 721.4 |
| ✅ | `nano-cores` | nano | core | 280 | 0 | 3.4 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 5.0 |
| ✅ | `offline-console-actions` | offline | api | 323 | 0 | 13.7 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 19.6 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 23.3 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 16 services crawled, 3 with findings
UI crawl offline: 13/16 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"static":83,"live":102,"partial":9,"unimplemented":1}
[offline/azure] 20 services crawled, 0 with findings
UI crawl offline: 20/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":177,"static":56}
[offline/gcp] 16 services crawled, 0 with findings
UI crawl offline: 16/16 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":93,"static":101}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 16 services crawled, 3 with findings
UI crawl nano: 13/16 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":135,"static":36,"partial":7,"unimplemented":17}
[nano/azure] 25 services crawled, 19 with findings
UI crawl nano: 6/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":193,"static":55}
[nano/gcp] 16 services crawled, 0 with findings
UI crawl nano: 16/16 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":128,"static":64,"partial":2}
```

</details>

## New features since the last run

| Target | Cloud | Service | Kind | Feature | SDK test |
|---|---|---|---|---|---|
| offline | GCP | Firestore | column | Created | — |
| offline | GCP | VPC Network | column | MTU | — |
| nano | GCP | Firestore | column | Created | — |
| nano | GCP | VPC Network | column | MTU | — |
| offline | Cross-cloud | routes/metrics_series.py | route | GET /api/metrics/series | ✅ |

## Upstream changes (AWS / GCP / Azure backlog)

46 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #193 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #191 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #192 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #190 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #186 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #184 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #185 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #183 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #180 | Cross-cloud |  | [shared] Conformance crawl must catch: fake charts, page errors under real tiers, cross-cloud layout drift | 2026-10-29 |
| #179 | Azure |  | [azure] Console Metrics/Monitoring: real charts for every service from measured requests | 2026-10-29 |
| #178 | GCP |  | [gcp] Console Metrics tabs: real charts for every service (replace seeded fake sparklines) | 2026-10-29 |
| #177 | AWS |  | [aws] Console Monitoring tabs: real charts from measured requests (replace synthetic sparklines and EC2 synthetic CloudWatch) | 2026-10-29 |
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

## SDK operations without a test (184 of 936)

<details><summary>AWS · <code>elbv2_core</code> (nano) — 4</summary>

AddListenerCertificates, DescribeListenerCertificates, RemoveListenerCertificates, TagTarget

</details>
<details><summary>AWS · <code>logs_core</code> (nano) — 6</summary>

AssociateKmsKey, DescribeQueries, DisassociateKmsKey, RunInsights, StopQuery, UntagLogGroup

</details>
<details><summary>AWS · <code>ssm_core</code> (nano) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>Azure · <code>azure_app_core</code> (nano) — 3</summary>

PutApp, PutJob, StopRuntime

</details>
<details><summary>Azure · <code>azure_appconfiguration_core</code> (nano) — 4</summary>

DeleteStore, ListKv, ListStores, PutStore

</details>
<details><summary>Azure · <code>azure_cognitiveservices_core</code> (nano) — 4</summary>

DeleteAccount, ListAccounts, PatchAccount, PutAccount

</details>
<details><summary>Azure · <code>azure_dns_core</code> (nano) — 4</summary>

DeleteZone, ListZones, PutRs, PutZone

</details>
<details><summary>Azure · <code>azure_operationalinsights_core</code> (nano) — 3</summary>

PutDataSource, PutTable, PutWorkspace

</details>
<details><summary>GCP · <code>gcp_cloudscheduler_core</code> (nano) — 2</summary>

PatchJob, SetState

</details>
<details><summary>GCP · <code>gcp_container_core</code> (nano) — 3</summary>

CreatePool, DeletePool, GetOp

</details>
<details><summary>GCP · <code>gcp_redis_core</code> (nano) — 2</summary>

GetOp, PatchInstance

</details>
<details><summary>AWS · <code>elbv2_core</code> (offline) — 4</summary>

AddListenerCertificates, DescribeListenerCertificates, RemoveListenerCertificates, TagTarget

</details>
<details><summary>AWS · <code>logs_core</code> (offline) — 6</summary>

AssociateKmsKey, DescribeQueries, DisassociateKmsKey, RunInsights, StopQuery, UntagLogGroup

</details>
<details><summary>AWS · <code>ssm_core</code> (offline) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>Azure · <code>azure_app_core</code> (offline) — 3</summary>

PutApp, PutJob, StopRuntime

</details>
<details><summary>Azure · <code>azure_appconfiguration_core</code> (offline) — 4</summary>

DeleteStore, ListKv, ListStores, PutStore

</details>
<details><summary>Azure · <code>azure_cognitiveservices_core</code> (offline) — 4</summary>

DeleteAccount, ListAccounts, PatchAccount, PutAccount

</details>
<details><summary>Azure · <code>azure_dns_core</code> (offline) — 4</summary>

DeleteZone, ListZones, PutRs, PutZone

</details>
<details><summary>Azure · <code>azure_operationalinsights_core</code> (offline) — 3</summary>

PutDataSource, PutTable, PutWorkspace

</details>
<details><summary>GCP · <code>gcp_cloudscheduler_core</code> (offline) — 2</summary>

PatchJob, SetState

</details>
<details><summary>GCP · <code>gcp_container_core</code> (offline) — 3</summary>

CreatePool, DeletePool, GetOp

</details>
<details><summary>GCP · <code>gcp_redis_core</code> (offline) — 2</summary>

GetOp, PatchInstance

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-29T05:46:05+00:00 | 159/175 | 3589 | 54 | 44 | 34.4% |  |
| 2026-10-29T03:56:27+00:00 | 115/123 | 2760 | 39 | 29 | 16.1% |  |
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

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
