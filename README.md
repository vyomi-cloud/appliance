# Vyomi Conformance — hourly report

Run **2026-10-27T17:09:42+00:00** · commit `e039eeb1aaa1` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 74/77 | 1122 | 6 | 40/43 | 36/38 | 7 | 16.5% (53/321) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 31/32 | 296 | 1 | 9/12 | 10/12 | 7 |
| [GCP](#gcp) | 20/20 | 221 | 0 | 12/12 | 12/12 | 0 |
| [Azure](#azure) | 18/18 | 221 | 0 | 19/19 | 14/14 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 2.4 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.1 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 6.3 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 8.5 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 10.8 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 9.4 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.1 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 11.6 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 2.4 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 9.3 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 8.0 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 6.4 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.3 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 4.8 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 20.1 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 32.3 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 13 | 0 | 9.3 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 2.8 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.3 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.7 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 11.5 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 17.2 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 13.6 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.4 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 9.1 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 9.6 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 9.4 |

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

**UI findings: 7**

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

<details><summary><b>API Gateway</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Stages | tab Stages: column "Description" shows "-"/blank in 1 row(s) |

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
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 2.4 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 2.5 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 2.5 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 4.9 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 2.6 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 2.4 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 7.1 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 1.9 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 2.8 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 8 | 0 | 9.0 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 1.9 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 17.7 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 13.4 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 10.9 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 3.8 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 1.5 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 3.6 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.9 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 1.9 |

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.7 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 26.0 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 17.3 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.7 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 2.5 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 2.9 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 4.9 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 7.0 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 6.0 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 16.5 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 6.7 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.3 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 19.0 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 7.9 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 20.2 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 0.8 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 19.4 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.6 |

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 40 | 3 | 1004.7 |
| ❌ | `offline-ui-crawl` | offline | ui | 36 | 2 | 890.1 |
| ✅ | `nano-cores` | nano | core | 37 | 0 | 1.6 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.0 |
| ✅ | `offline-console-actions` | offline | api | 246 | 0 | 9.5 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 21.5 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 26.0 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 2 with findings
[offline/gcp] 12 services crawled, 0 with findings
[offline/azure] 14 services crawled, 0 with findings
UI crawl offline: 36/38 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":236,"static":209,"partial":3}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 12 services crawled, 3 with findings
[nano/gcp] 12 services crawled, 0 with findings
[nano/azure] 19 services crawled, 0 with findings
UI crawl nano: 40/43 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":329,"static":130,"partial":4}
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

## SDK operations without a test (52 of 436)

<details><summary>AWS · <code>apigateway_core</code> (nano) — 4</summary>

CreateDeployment, GetResources, GetRestApis, PutIntegration

</details>
<details><summary>AWS · <code>dynamodb_core</code> (nano) — 9</summary>

CreateTableRecord, DeleteItemRecord, DeleteTableRecord, GetItemRecord, PutItemRecord, QueryFilter, ScanFilter, SetTags, UpdateItemRecord

</details>
<details><summary>AWS · <code>kms_core</code> (nano) — 2</summary>

SetKeyRotation, SetKeyState

</details>
<details><summary>AWS · <code>rds_core</code> (nano) — 3</summary>

CreateDbSnapshot, DescribeDbSnapshots, SetStatus

</details>
<details><summary>AWS · <code>rds_data_core</code> (nano) — 1</summary>

ExecuteStatement

</details>
<details><summary>AWS · <code>s3_object_core</code> (nano) — 4</summary>

DeleteMarkerResponse, DeleteVersion, InsertSimpleDeleteMarker, ListAllBuckets

</details>
<details><summary>AWS · <code>secrets_core</code> (nano) — 1</summary>

PutValue

</details>
<details><summary>Azure · <code>azure_subresource_core</code> (nano) — 4</summary>

CreateChild, DeleteChild, ListChildren, UpdateChild

</details>
<details><summary>AWS · <code>apigateway_core</code> (offline) — 4</summary>

CreateDeployment, GetResources, GetRestApis, PutIntegration

</details>
<details><summary>AWS · <code>dynamodb_core</code> (offline) — 9</summary>

CreateTableRecord, DeleteItemRecord, DeleteTableRecord, GetItemRecord, PutItemRecord, QueryFilter, ScanFilter, SetTags, UpdateItemRecord

</details>
<details><summary>AWS · <code>kms_core</code> (offline) — 2</summary>

SetKeyRotation, SetKeyState

</details>
<details><summary>AWS · <code>rds_core</code> (offline) — 3</summary>

CreateDbSnapshot, DescribeDbSnapshots, SetStatus

</details>
<details><summary>AWS · <code>rds_data_core</code> (offline) — 1</summary>

ExecuteStatement

</details>
<details><summary>AWS · <code>s3_object_core</code> (offline) — 4</summary>

DeleteMarkerResponse, DeleteVersion, InsertSimpleDeleteMarker, ListAllBuckets

</details>
<details><summary>AWS · <code>secrets_core</code> (offline) — 1</summary>

PutValue

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-27T17:09:42+00:00 | 74/77 | 1122 | 6 | 7 | 16.5% |  |
| 2026-10-27T16:09:07+00:00 | 73/76 | 1112 | 8 | 11 | 16.5% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
