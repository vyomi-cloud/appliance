# Vyomi Conformance — hourly report

Run **2026-10-27T18:08:29+00:00** · commit `c1f98040744a` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 76/79 | 1167 | 7 | 40/43 | 35/38 | 10 | 20.2% (65/321) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 32/33 | 316 | 1 | 9/12 | 9/12 | 10 |
| [GCP](#gcp) | 21/21 | 236 | 0 | 12/12 | 12/12 | 0 |
| [Azure](#azure) | 18/18 | 221 | 0 | 19/19 | 14/14 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-api` | nano | ui | 5 | 1 | 3.3 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.2 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 7.4 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.3 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 11.7 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 10.2 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.8 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 11 | 0 | 12.5 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.3 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.5 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 8.8 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 4.7 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 1.7 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 3.8 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 22.4 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 40.8 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 13 | 0 | 13.4 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 3.7 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.6 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 2.0 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.4 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 10.5 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 14.9 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 12.6 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.1 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 8.5 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 9.0 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 8.6 |

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
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 5.8 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 3.3 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 4.8 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 2.2 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 1.2 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 1.8 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 8 | 0 | 6.2 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 1.6 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 16.1 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 15.6 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 13.8 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 5.2 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 1.3 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 2.9 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.7 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 1.5 |

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.8 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 26.7 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 17.9 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 3.3 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 3.6 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.1 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 7.8 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 7.7 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 17.3 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 8.7 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 19.9 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 9.0 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 21.3 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.3 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 18.8 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 40 | 3 | 975.9 |
| ❌ | `offline-ui-crawl` | offline | ui | 35 | 3 | 837.7 |
| ✅ | `nano-cores` | nano | core | 48 | 0 | 2.3 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.7 |
| ✅ | `offline-console-actions` | offline | api | 246 | 0 | 10.0 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 15.5 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 24.0 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 12 services crawled, 3 with findings
[offline/gcp] 12 services crawled, 0 with findings
[offline/azure] 14 services crawled, 0 with findings
UI crawl offline: 35/38 services clean → tests/conformance/hourly/out/ui-offline.json
Console surfaces offline: {"live":236,"static":209,"partial":3}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 12 services crawled, 3 with findings
[nano/gcp] 12 services crawled, 0 with findings
[nano/azure] 19 services crawled, 0 with findings
UI crawl nano: 40/43 services clean → tests/conformance/hourly/out/ui-nano.json
Console surfaces nano: {"live":331,"static":128,"partial":4}
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

## SDK operations without a test (0 of 436)


## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-27T18:08:29+00:00 | 76/79 | 1167 | 7 | 10 | 20.2% |  |
| 2026-10-27T17:09:42+00:00 | 74/77 | 1122 | 6 | 7 | 16.5% |  |
| 2026-10-27T16:09:07+00:00 | 73/76 | 1112 | 8 | 11 | 16.5% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
