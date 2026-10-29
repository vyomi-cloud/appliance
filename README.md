# Vyomi Conformance — hourly report

Run **2026-10-29T12:34:40+00:00** · commit `057510d01725` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 177/181 | 3687 | 11 | 54/57 | 49/52 | 8 | 42.1% (136/323) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 71/71 | 1042 | 0 | 13/16 | 13/16 | 8 |
| [GCP](#gcp) | 45/47 | 692 | 5 | 16/16 | 16/16 | 0 |
| [Azure](#azure) | 56/56 | 1222 | 0 | 25/25 | 20/20 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.3 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.8 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 16.5 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 8.7 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.9 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 22.9 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 12.4 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 16.5 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.8 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 16.4 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 4.4 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 16.5 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 50.3 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 13.1 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 11.0 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 11.9 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 9.4 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 21.3 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 22.1 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 15.3 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.9 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 11.0 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 16.5 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 9.4 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 10.6 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 3.4 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 2.3 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.1 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 2.0 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 8.5 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.1 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 22.9 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 54.2 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 38.9 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 33.4 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 19.0 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 36.4 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 53 | 0 | 55.8 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 19 | 0 | 27.8 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 24.1 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 8.3 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 9.4 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 45.0 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 30.0 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 21.3 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 9.6 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 3.0 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.5 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.7 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.1 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 11.8 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 19.2 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 24.7 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.7 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 34.4 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 63.3 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 20.5 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 10.0 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 9.5 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 23.4 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 23.7 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 10.1 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 10.4 |

**UI findings: 8**

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

<details><summary><b>Systems Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-api-gcp-cloudscheduler-http` | offline | api | 2 | 4 | 51.2 |
| ❌ | `offline-ui-gcp-cloudscheduler` | offline | ui | 22 | 1 | 24.2 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.6 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 27.2 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 22.8 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 66.5 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 3.6 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.0 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 3.6 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.0 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.6 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 23.3 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 3.7 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.6 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 32.7 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.8 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 0.2 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.7 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 15.6 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 9.0 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 12.7 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 2.1 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 11.5 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 27.0 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 15.0 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 17.0 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 2.5 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 1.9 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 1.8 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 10.5 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 4.8 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 5.0 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 5.4 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 5.2 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.7 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 21.1 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 66.2 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 0.8 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 20.1 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.2 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.7 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.7 |

<details><summary>❌ <code>offline-ui-gcp-cloudscheduler</code> log</summary>

```
[PASS] Cloud Scheduler is on the GCP console rail
[PASS] create form has a realistic default name
[PASS] create with defaults returns 2xx
[PASS] new job appears in the list
[PASS] every grid column is filled
[PASS] cost-savings metrics include the new job (gcp.cloudscheduler priced)
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Last execution" renders
[PASS] tab "Target" renders
[PASS] tab "Retry policy" renders
[PASS] tab "Schedule" renders
[PASS] tab "Properties" renders
[PASS] tab "JSON" renders
[PASS] tab "Metrics" renders
[PASS] Schedule tab shows the cron frequency
[PASS] Target tab shows the HTTP target
[PASS] Pause → job state PAUSED
[PASS] Resume → job state ENABLED
[FAIL] Force run → last execution result Success
[PASS] delete removes the job from the list
[PASS] deleted job is gone from the backend
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>offline-api-gcp-cloudscheduler-http</code> log</summary>

```
[PASS] create httpTarget job
[PASS] run job
[FAIL] target received the request no request
[FAIL] 2xx leaves status OK 
[FAIL] 500 target shows failed status {'schedule': '0 0 1 1 *', 'httpTarget': {'uri': 'http://127.0.0.1:35909/hook', 'httpMethod': 'PUT', 'headers': {'X-Vyomi': 'yes'}, 'body': 'cGF5bG9hZC0x', 'oidcToken': {'serviceAccountEmail': 'a@b.iam'}}, 'name': 'projects/cloudlearn/locations/us-central1/jobs/http-6a3553', 'state': 'ENABLED', 'userUpdateTime': '2026-10-29T12:13:07.454747Z', 'status': {'code': 14, 'message': 'URL_ERROR-ERROR_CONNECTION. <urlopen error [Errno 111] Connection refused>'}, 'timeZone': 'Etc/UTC', 'retryConfig': {}, 'scheduleTime': '2027-01-01T00:00:00.000000Z', 'lastAttemptTime': '2026-10-29T12:13:37.698440Z'}
[FAIL] later success clears status None
```

</details>

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 20.2 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 21.9 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 22.7 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 22.5 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.5 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 25.6 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 16.9 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.5 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 2.2 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 26.8 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 9.8 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 9.4 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 26.4 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 2.6 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 4.7 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 6.7 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 5.6 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 16.2 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 45.9 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 5.7 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.6 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.5 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 9.1 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 8.0 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 14.7 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.3 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 7.0 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.8 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.6 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 22.1 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 3.3 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 2.0 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.6 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.1 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.2 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 21.0 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 29.0 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.7 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 7.9 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.6 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.9 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.9 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.5 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.4 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.9 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 23.1 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.9 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.5 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.2 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 28.3 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.7 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 10.1 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.5 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 49.8 |

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 54 | 3 | 806.2 |
| ❌ | `offline-ui-crawl` | offline | ui | 49 | 3 | 756.5 |
| ✅ | `nano-cores` | nano | core | 280 | 0 | 3.5 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 5.4 |
| ✅ | `offline-console-actions` | offline | api | 323 | 0 | 11.5 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 26.8 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 25.4 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 16 services crawled, 3 with findings
UI crawl offline: 13/16 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"static":84,"live":107,"partial":4}
[offline/azure] 20 services crawled, 0 with findings
UI crawl offline: 20/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":183,"static":50}
[offline/gcp] 16 services crawled, 0 with findings
UI crawl offline: 16/16 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":91,"static":103}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 16 services crawled, 3 with findings
UI crawl nano: 13/16 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":152,"static":38,"partial":5}
[nano/azure] 25 services crawled, 0 with findings
UI crawl nano: 25/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":202,"static":46}
[nano/gcp] 16 services crawled, 0 with findings
UI crawl nano: 16/16 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":130,"static":64}
```

</details>

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

54 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #231 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #230 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #228 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #229 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #219 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #220 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #218 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #217 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
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
| 2026-10-29T12:34:40+00:00 | 177/181 | 3687 | 11 | 8 | 42.1% |  |
| 2026-10-29T10:56:55+00:00 | 176/178 | 3670 | 5 | 7 | 39.6% |  |
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

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
