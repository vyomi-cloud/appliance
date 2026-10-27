# Vyomi Conformance — hourly report

Run **2026-10-27T12:41:53+00:00** · commit `17294086ff41` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 66/69 | 1019 | 6 | 40/43 | 36/38 | 8 | 16.5% (53/321) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 27/28 | 272 | 1 | 10/12 | 10/12 | 6 |
| [GCP](#gcp) | 19/19 | 195 | 0 | 12/12 | 12/12 | 0 |
| [Azure](#azure) | 15/15 | 168 | 0 | 18/19 | 14/14 | 2 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 3.2 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.2 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 7.6 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.4 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 11.8 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 10.3 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.9 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 12.5 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.4 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.4 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 5.2 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 1.7 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 4.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 21.7 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 45.8 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 13 | 0 | 11.4 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 4.0 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 10.7 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 15.4 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 12.9 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.3 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 8.7 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 11.4 |

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

**UI findings: 6**

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

<details><summary><b>DynamoDB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 3.4 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 3.5 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 5.8 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 3.4 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 5.5 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 2.7 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 2.0 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 8 | 0 | 6.8 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 1.7 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 15.7 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 15.6 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 5.3 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 1.3 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 3.0 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.7 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 1.6 |

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.9 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 26.8 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 18.0 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 3.5 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.2 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 8.2 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 7.9 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 17.5 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 9.0 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 19.8 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 10.5 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 21.6 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 19.0 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |

**UI findings: 2**

<details><summary><b>Key vaults</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_404` | Secrets | /azure-data/keyvault/kv-cloudlearn/secrets → 404 |
| `HTTP_404` | Keys | /azure-data/keyvault/kv-cloudlearn/keys → 404 |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 40 | 3 | 1011.3 |
| ❌ | `offline-ui-crawl` | offline | ui | 36 | 2 | 870.4 |
| ✅ | `nano-cores` | nano | core | 37 | 0 | 2.2 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.7 |
| ✅ | `offline-console-actions` | offline | api | 246 | 0 | 10.0 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 15.9 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 25.0 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 2 with findings
[offline/gcp] 12 services crawled, 0 with findings
[offline/azure] 14 services crawled, 0 with findings
UI crawl offline: 36/38 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":230,"static":198,"partial":17,"unimplemented":3}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 12 services crawled, 2 with findings
[nano/gcp] 12 services crawled, 0 with findings
[nano/azure] 19 services crawled, 1 with findings
UI crawl nano: 40/43 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":310,"static":125,"partial":14,"unimplemented":14}
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

## SDK operations without a test (116 of 436)

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
<details><summary>Azure · <code>azure_arm_core</code> (nano) — 1</summary>

ListResourceGroups

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
<details><summary>Azure · <code>azure_arm_core</code> (offline) — 1</summary>

ListResourceGroups

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
| 2026-10-27T12:41:53+00:00 | 66/69 | 1019 | 6 | 8 | 16.5% |  |
| 2026-10-27T11:50:53+00:00 | 61/64 | 993 | 11 | 32 | 15.9% |  |
| 2026-10-27T10:35:59+00:00 | 55/58 | 956 | 24 | 41 | 15.9% |  |
| 2026-10-27T09:18:09+00:00 | 40/45 | 799 | 33 | 68 | 14.0% |  |
| 2026-10-27T06:28:14+00:00 | 28/35 | 638 | 58 | 93 | 14.0% | Fixed offline GCP Secret Manager / Cloud KMS (blank Created, wrong value stored, not counted in cost savings) and two crawler false positives; added 1 test, 0 regressions. |
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

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
