# Vyomi Conformance — hourly report

Run **2026-10-29T03:56:27+00:00** · commit `96c4fc8af8cd` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 115/123 | 2760 | 39 | 43/57 | 48/52 | 29 | 16.1% (52/322) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 41/41 | 829 | 0 | 8/16 | 12/16 | 22 |
| [GCP](#gcp) | 29/30 | 462 | 2 | 15/16 | 16/16 | 2 |
| [Azure](#azure) | 42/45 | 1065 | 3 | 20/25 | 20/20 | 5 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.6 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 4 | 0 | 16.4 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 5 | 0 | 16.4 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.9 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 14.7 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 4.1 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 17.3 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 50.5 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 11.7 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 23.3 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 25.0 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 12.8 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 4 | 0 | 15.8 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 6 | 0 | 6.8 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.0 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 5.0 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.6 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 24.2 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 47.6 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 32.6 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 41.2 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 24.3 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 49.6 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 53 | 0 | 40.2 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 19 | 0 | 24.0 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 21.9 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 10.8 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 11.4 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 33.9 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 23.2 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 20.8 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 11.2 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 4.5 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 10.8 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 17.5 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 28.4 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 58.0 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 21.7 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 22.9 |

**UI findings: 22**

<details><summary><b>EC2</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `DEAD_TAB` | Monitoring | clicking the tab changes nothing |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "SECURITY GROUPS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |
| `HTTP_501` | Connect | /api/aws/ec2/instances/i-573ee0fb3f1838d61/connect-info → 501 |

</details>

<details><summary><b>VPC</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `DEAD_TAB` | VPC details | clicking the tab changes nothing |
| `HTTP_501` | Subnets | /api/vpc/subnets → 501 |
| `HTTP_501` | Route tables | /api/vpc/route-tables → 501 |
| `HTTP_501` | Internet gateways | /api/vpc/internet-gateways → 501 |

</details>

<details><summary><b>API Gateway</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_501` | Resources | /api/apigateway/apis/5872c29e5f/resources → 501 |
| `HTTP_501` | Stages | /api/apigateway/apis/5872c29e5f/stages → 501 |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Last rotated" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Next rotation" shows "-"/blank in 1 row(s) |

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

<details><summary><b>SQS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Dead-letter queue | tab Dead-letter queue: column "MAXIMUM RECEIVES" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>EventBridge</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `SAVINGS_NOT_UPDATED` |  | create: resource_count stayed 7 after creating a resource |

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

<details><summary><b>Systems Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-ui-gcp-create-defaults` | offline | ui | 34 | 2 | 69.6 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 25.7 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 25.0 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 67.4 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.1 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.2 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 25.7 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 8 | 0 | 3.7 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 6.4 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 20.8 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 15.8 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 15.1 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 5.2 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 16.1 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 16.2 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 20.9 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 6.6 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 12.7 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 8.5 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 5.8 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 14.2 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 9.7 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 12.6 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 11.5 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 23 | 0 | 28.4 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 23.4 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 21.5 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.6 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 24.0 |

<details><summary>❌ <code>offline-ui-gcp-create-defaults</code> log</summary>

```
[PASS] API Gateway: the new resource is listed
[PASS] API Gateway: no placeholder cells
[PASS] Secret Manager: service is on the rail
[PASS] Secret Manager: create with defaults is accepted
[PASS] Secret Manager: the new resource is listed
[PASS] Secret Manager: no placeholder cells
[PASS] Cloud Functions: service is on the rail
[PASS] Cloud Functions: create with defaults is accepted
[PASS] Cloud Functions: the new resource is listed
[PASS] Cloud Functions: no placeholder cells
[PASS] Firestore: service is on the rail
[FAIL] Firestore: create with defaults is accepted [409]
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
[FAIL] Pub/Sub: create with defaults is accepted [409]
[PASS] Pub/Sub: the new resource is listed
[PASS] Pub/Sub: no placeholder cells
```

</details>

**UI findings: 2**

<details><summary><b>API Gateway</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Metrics | tab Metrics: column "API CONFIGS" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Metrics | tab Metrics: column "ROUTES" shows "-"/blank in 1 row(s) |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-azure-app` | nano | ui | 28 | 1 | 23.0 |
| ❌ | `nano-ui-azure-appconfiguration` | nano | ui | 27 | 1 | 23.6 |
| ❌ | `nano-ui-azure-monitor` | nano | ui | 28 | 1 | 28.7 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 24.0 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 24.5 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 10.3 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 4.5 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 12 | 0 | 21.8 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 12.2 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 11.7 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 28.0 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 11.1 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.8 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 48.8 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 12.9 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 27.4 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 20.3 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 20.7 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 11.4 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 11.2 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 20.8 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 12.3 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 11.1 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 16.7 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 9.5 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 13.1 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 9.0 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 16.0 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 27.1 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 23.5 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 28.8 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 49.9 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 12.6 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 28.5 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 14.1 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 25.8 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 24.4 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 26.4 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 27.5 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 26.2 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 36.7 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 14.6 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 12.3 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 30.2 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 92.1 |

<details><summary>❌ <code>nano-ui-azure-app</code> log</summary>

```
[PASS] Container Apps is on the Nano Azure console rail
[FAIL] service page says what runs below the Pro tier (control plane / Docker)
[PASS] create form has a realistic default name
[PASS] create form defaults a container image
[PASS] create with defaults returns 2xx
[PASS] new container app appears in the list
[PASS] every grid column is filled
[PASS] cost-savings metrics updated by the create
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
[FAIL] service page explains what the service does
[PASS] create form has a realistic default name
[PASS] create form defaults the pricing tier to Standard
[PASS] create with defaults returns 2xx
[PASS] new store appears in the list
[PASS] every grid column is filled
[PASS] cost-savings metrics updated by the create
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

<details><summary>❌ <code>nano-ui-azure-monitor</code> log</summary>

```
[PASS] Monitor alerts is on the Nano Azure console rail
[FAIL] service page explains what the service does
[PASS] create form has a realistic default alert rule name
[PASS] create with defaults returns 2xx
[PASS] new alert rule appears in the list
[PASS] every grid column is filled
[PASS] grid shows severity, evaluation frequency and the scope
[PASS] cost-savings metrics updated by the create
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

**UI findings: 5**

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

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 43 | 14 | 1615.2 |
| ❌ | `offline-console-actions` | offline | api | 278 | 15 | 11.9 |
| ❌ | `offline-cost-savings` | offline | api | 10 | 1 | 29.8 |
| ❌ | `offline-ui-crawl` | offline | ui | 48 | 4 | 1391.1 |
| ✅ | `nano-cores` | nano | core | 11 | 0 | 2.2 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 6.0 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 28.1 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 16 services crawled, 4 with findings
[offline/gcp] 16 services crawled, 0 with findings
[offline/azure] 20 services crawled, 0 with findings
UI crawl offline: 48/52 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":369,"static":240,"unimplemented":3,"partial":10}
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
/console_actions/test_aws_console.py::test_aws_action[aws.ssm.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
FAILED tests/conformance/console_actions/test_aws_console.py::test_aws_action[aws.stepfunctions.create] - AssertionError: AWS stepfunctions.create POST /api/stepfunctions/machines → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_aws_console.py::test_aws_action[aws.stepfunctions.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
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
FAILED tests/conformance/console_actions/test_gcp_console.py::test_gcp_action[gcp.secretmanager.get] - AssertionError: GCP secretmanager.get GET /api/gcp/secrets/vyomi-conf-secret-33fd6988 → HTTP 404 (expected one of (200, 201, 202, 204)). Body: {"ok":false,"error":"secret not found","name":"vyomi-conf-secret-33fd6988"}
assert False
15 failed, 278 passed, 40 skipped in 11.48s
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
PASS: aws: creating a S3 bucket raises the space resource_count
PASS: aws: creating a S3 bucket raises aws savings
PASS: aws: using the S3 bucket (5 × 2 MB uploads) raises savings

== gcp: Cloud Storage bucket ==
PASS: gcp: creating a Cloud Storage bucket raises the space resource_count
PASS: gcp: creating a Cloud Storage bucket raises gcp savings
PASS: gcp: using the Cloud Storage bucket (5 × 2 MB uploads) raises savings

== azure: Storage account ==
PASS: azure: creating a Storage account raises the space resource_count
PASS: azure: creating a Storage account raises azure savings
FAIL: azure: using the Storage account (5 × 2 MB uploads) raises savings :: $290.37 → $290.37 (real azure bills storage + requests)

== azure: Virtual machine (Standard_B1s) ==
PASS: azure: creating a VM raises the space resource_count
PASS: azure: a Standard_B1s VM adds its 730 h list price ($7.59) to Azure savings

RESULT fail=1
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 16 services crawled, 8 with findings
[nano/gcp] 16 services crawled, 1 with findings
[nano/azure] 25 services crawled, 5 with findings
UI crawl nano: 43/57 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":447,"static":152,"unimplemented":25,"partial":11}
```

</details>

## New features since the last run

| Target | Cloud | Service | Kind | Feature | SDK test |
|---|---|---|---|---|---|
| offline | GCP | Firestore | column | Delete protection | — |
| offline | Azure | Network Security Group | tab | Overview | — |
| offline | Azure | Network Security Group | tab | Activity log | — |
| offline | Azure | Network Security Group | tab | Access control (IAM) | — |
| offline | Azure | Network Security Group | tab | Tags | — |
| offline | Azure | Network Security Group | tab | Diagnose and solve problems | — |
| offline | Azure | Network Security Group | tab | Security rules | — |
| offline | Azure | Network Security Group | tab | Properties | — |
| offline | Azure | Network Security Group | tab | Locks | — |
| offline | Azure | Role Definition | tab | Overview | — |
| offline | Azure | Role Definition | tab | Properties | — |
| offline | Azure | Role Definition | tab | JSON view | — |
| offline | Azure | Role Definition | create_field | Role definition name (GUID) | — |
| nano | GCP | Firestore | column | Delete protection | — |
| nano | Azure | Network Security Group | tab | Overview | — |
| nano | Azure | Network Security Group | tab | Activity log | — |
| nano | Azure | Network Security Group | tab | Access control (IAM) | — |
| nano | Azure | Network Security Group | tab | Tags | — |
| nano | Azure | Network Security Group | tab | Diagnose and solve problems | — |
| nano | Azure | Network Security Group | tab | Security rules | — |
| nano | Azure | Network Security Group | tab | Properties | — |
| nano | Azure | Network Security Group | tab | Locks | — |
| nano | Azure | Role Definition | tab | Overview | — |
| nano | Azure | Role Definition | tab | Properties | — |
| nano | Azure | Role Definition | tab | JSON view | — |
| nano | Azure | Role Definition | create_field | Role definition name (GUID) | — |
| nano | Azure | Blob containers | service | Blob containers | — |
| nano | Azure | Blob containers | create_field | Blob container | — |
| nano | Azure | Blob containers | column | Name | — |
| nano | Azure | Cosmos databases | service | Cosmos databases | — |
| nano | Azure | Cosmos databases | create_field | Cosmos database | — |
| nano | Azure | Cosmos databases | column | Name | — |
| nano | Azure | Key Vault secrets | service | Key Vault secrets | — |
| nano | Azure | Key Vault secrets | create_field | Key Vault secret | — |
| nano | Azure | Key Vault secrets | column | Name | — |
| nano | Azure | Key Vault keys | service | Key Vault keys | — |
| nano | Azure | Key Vault keys | create_field | Key Vault key | — |
| nano | Azure | Key Vault keys | column | Name | — |
| nano | Azure | Storage queues | service | Storage queues | — |
| nano | Azure | Storage queues | create_field | Storage queue | — |
| nano | Azure | Storage queues | column | Name | — |

## Upstream changes (AWS / GCP / Azure backlog)

42 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
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
| #143 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (October 26, 2026) | 2026-10-27 |
| #142 | AWS | operation-added | AWS ec2: new operation GetImageFindings | 2026-10-27 |
| #139 | Azure | lifecycle | Retirement: Transition to using standard tests for single-step availability testing in Azure Monitor application insights by September 30, 2028 | 2026-10-27 |
| #138 | Azure | lifecycle | Retirement: Pod name dimension in AKS pod platform metrics | 2026-10-27 |

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
|  | 0/0 | 0 | 0 | 84 | 14.3% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
