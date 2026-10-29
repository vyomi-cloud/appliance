# Vyomi Conformance — hourly report

Run **2026-10-29T08:59:30+00:00** · commit `7553c40169e0` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 174/176 | 3654 | 6 | 54/57 | 49/52 | 10 | 34.4% (111/323) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 68/68 | 1019 | 0 | 13/16 | 13/16 | 10 |
| [GCP](#gcp) | 45/45 | 682 | 0 | 16/16 | 16/16 | 0 |
| [Azure](#azure) | 56/56 | 1222 | 0 | 25/25 | 20/20 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.2 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.4 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 14.4 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 7.9 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.5 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 21.8 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 11.9 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 16.1 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.1 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 16.0 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 3.8 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 14.5 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 49.8 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 12.4 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 10.5 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 11.3 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.9 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 21.8 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 23.6 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 14.8 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.4 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.5 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 16.0 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 9.0 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 8.0 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.9 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 1.9 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 1.7 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 6.7 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.1 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 31.0 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 55.9 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 38.3 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 34.2 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 17.5 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 35.7 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 53 | 0 | 55.7 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 19 | 0 | 29.5 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 22.0 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 8.4 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 13.6 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 44.3 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 33.4 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 21.4 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 9.8 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 3.1 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.5 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.5 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.2 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 12.0 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 18.6 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 23.3 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.6 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 35.6 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 62.7 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 19.4 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.9 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 9.7 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 24.3 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 23.9 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 10.0 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 10.8 |

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
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.8 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 27.3 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 23.0 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 66.6 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 3.9 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.3 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 3.7 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.2 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.8 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 24.8 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 3.7 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.6 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.2 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 0.2 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.5 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 19.5 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 7.6 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 10.5 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 1.5 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 8.2 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 21.5 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 12.8 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 9.0 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 2.0 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 1.7 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 1.6 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 4.6 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 3.7 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 3.7 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 4.0 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 3.9 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.6 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 23 | 0 | 24.6 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 20.9 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 65.9 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 0.7 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 19.9 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.1 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.6 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.4 |

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 20.4 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 22.1 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 23.0 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 22.7 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.7 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 25.9 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 17.2 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.6 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 2.5 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 26.9 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 9.9 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 9.4 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 26.6 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 2.8 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.0 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 6.9 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 6.4 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 16.6 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 46.1 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 6.6 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.4 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 11.8 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 8.0 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 14.3 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.5 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 7.0 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.8 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.6 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 21.4 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 3.2 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 2.1 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.6 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.1 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.2 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 21.0 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 29.8 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.7 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 7.2 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.5 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.6 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 6.0 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.5 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.1 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.7 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 22.9 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.7 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.4 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.2 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 28.1 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.9 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 10.1 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.6 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 50.0 |

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 54 | 3 | 757.9 |
| ❌ | `offline-ui-crawl` | offline | ui | 49 | 3 | 720.8 |
| ✅ | `nano-cores` | nano | core | 280 | 0 | 3.2 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.9 |
| ✅ | `offline-console-actions` | offline | api | 323 | 0 | 12.9 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 26.5 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 26.1 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 16 services crawled, 3 with findings
UI crawl offline: 13/16 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"static":86,"live":104,"partial":5}
[offline/azure] 20 services crawled, 0 with findings
UI crawl offline: 20/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":183,"static":50}
[offline/gcp] 16 services crawled, 0 with findings
UI crawl offline: 16/16 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":93,"static":101}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 16 services crawled, 3 with findings
UI crawl nano: 13/16 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":149,"static":40,"partial":6}
[nano/azure] 25 services crawled, 0 with findings
UI crawl nano: 25/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":199,"static":49}
[nano/gcp] 16 services crawled, 0 with findings
UI crawl nano: 16/16 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":131,"static":62,"partial":1}
```

</details>

## New features since the last run

None.

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
| 2026-10-29T08:59:30+00:00 | 174/176 | 3654 | 6 | 10 | 34.4% |  |
| 2026-10-29T07:25:18+00:00 | 172/175 | 3647 | 6 | 7 | 34.4% |  |
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

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
