# Vyomi Conformance — hourly report

Run **2026-11-02T19:43:41+00:00** · commit `1eb01affbb14` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 269/277 | 5931 | 15 | 63/63 | 58/58 | 0 | 55.4% (214/386) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 109/110 | 2315 | 2 | 20/20 | 20/20 | 0 |
| [GCP](#gcp) | 77/79 | 1169 | 3 | 18/18 | 18/18 | 0 |
| [Azure](#azure) | 71/76 | 1357 | 10 | 25/25 | 20/20 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-post-create-aws-ec2-ssh` | offline | api | 1 | 2 | 189.1 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.3 |
| ✅ | `nano-core-aws-detail-tabs` | nano | core | 104 | 0 | 0.1 |
| ✅ | `nano-post-create-aws-ec2-ssh` | nano | ui | 18 | 0 | 60.9 |
| ✅ | `nano-store-delete-sync` | nano | core | 4 | 0 | 0.0 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.3 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 22.0 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 14.4 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 23 | 0 | 15.7 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 7.7 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.1 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 21.5 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 11.6 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 14.3 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.4 |
| ✅ | `nano-ui-aws-event-delivery` | nano | ui | 9 | 0 | 4.9 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 14.1 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 3.1 |
| ✅ | `nano-ui-aws-kinesis` | nano | ui | 19 | 0 | 9.9 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 14.2 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 19.4 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 12.1 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 10.3 |
| ✅ | `nano-ui-aws-real-tabs` | nano | ui | 59 | 0 | 252.8 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 3.0 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 11.0 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 30.6 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.7 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 20.0 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 22.0 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 14.7 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.2 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.9 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 14.1 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 9.4 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 0.6 |
| ✅ | `offline-api-aws-detail-tabs` | offline | api | 200 | 0 | 17.1 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 0.2 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.1 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 0.2 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 0.4 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.1 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 8.9 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 18.9 |
| ✅ | `offline-cli-aws-cloudwatch` | offline | cli | 31 | 0 | 14.4 |
| ✅ | `offline-cli-aws-ec2-sg-description` | offline | cli | 2 | 0 | 4.0 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 14.4 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 10.1 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 10.3 |
| ✅ | `offline-cli-aws-sns` | offline | cli | 76 | 0 | 47.4 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 16.0 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 11.3 |
| ✅ | `offline-post-create-aws-apigateway-invoke` | offline | api | 4 | 0 | 0.7 |
| ✅ | `offline-post-create-aws-apigatewayv2-invoke` | offline | api | 1 | 0 | 1.1 |
| ✅ | `offline-post-create-aws-event-delivery` | offline | api | 6 | 0 | 1.6 |
| ✅ | `offline-post-create-aws-iam-actions` | offline | api | 13 | 0 | 1.1 |
| ✅ | `offline-post-create-aws-rds-db-connect` | offline | api | 6 | 0 | 3.5 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 30.8 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 2.2 |
| ✅ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 37 | 0 | 4.4 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 4.9 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 2.2 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 6.0 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 6.6 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 5.6 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 1.8 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 10.3 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 3.3 |
| ✅ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 26 | 0 | 4.4 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 5.2 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 18.9 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 4.0 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 8.1 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 3.9 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 3.2 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 79 | 0 | 2.3 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.3 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.5 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 0.9 |
| ✅ | `offline-sdk-python-aws-ops3` | offline | sdk-python | 12 | 0 | 0.7 |
| ✅ | `offline-sdk-python-aws-ops4` | offline | sdk-python | 15 | 0 | 1.0 |
| ✅ | `offline-sweepA-aws` | offline | sdk-python | 14 | 0 | 2.7 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 20.9 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 8.4 |
| ✅ | `offline-ui-aws-cloudwatch` | offline | ui | 23 | 0 | 14.5 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 10.4 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 18.5 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 9.2 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 21.7 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 10.1 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 19.2 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 9.9 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 7.8 |
| ✅ | `offline-ui-aws-real-tabs` | offline | ui | 59 | 0 | 221.3 |
| ✅ | `offline-ui-aws-sns` | offline | ui | 36 | 0 | 29.2 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 6.4 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 18.9 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 20.6 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 8.3 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 6.9 |
| ✅ | `offline-ui-sdk-roundtrip` | offline | ui | 18 | 0 | 43.6 |

<details><summary>❌ <code>offline-post-create-aws-ec2-ssh</code> log</summary>

```
[PASS] [aws] create VM
[FAIL] [aws] VM reaches running :: state=stopped launch=ready
[FAIL] connect-info available (CONNECT_INFO_MISSING) :: {'ok': False, 'http': 409, 'body': '{"detail":{"error":"instance_not_running","state":"stopped","hint":"Start the instance before connecting."}}'}
```

</details>

**UI findings: 0**

No open UI findings.

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-post-create-gcp-gce-ssh` | nano | ui | 17 | 1 | 88.3 |
| ❌ | `offline-post-create-gcp-gce-ssh` | offline | api | 1 | 2 | 186.0 |
| ✅ | `nano-core-triggers` | nano | api | 11 | 0 | 0.7 |
| ✅ | `nano-gcp-cloudsql-core` | nano | core | 34 | 0 | 0.1 |
| ✅ | `nano-gcp-compute-core` | nano | core | 18 | 0 | 0.1 |
| ✅ | `nano-gcp-kms-core` | nano | core | 35 | 0 | 0.5 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 4.6 |
| ✅ | `nano-ui-gcp-apigw-monitoring-tabs` | nano | ui | 7 | 0 | 26.1 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 16 | 0 | 22.0 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 27.5 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 24.2 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 67.5 |
| ✅ | `nano-ui-gcp-eventarc-delivery` | nano | ui | 7 | 0 | 10.3 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 4.6 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 59 | 0 | 5.0 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 21.7 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 4.8 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 25.9 |
| ✅ | `nano-ui-gcp-properties` | nano | ui | 12 | 0 | 15.9 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 7.2 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 4.7 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 25.0 |
| ✅ | `nano-ui-gcp-scheduler-pubsub` | nano | ui | 5 | 0 | 4.6 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 4.8 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.6 |
| ✅ | `offline-api-gcp-artifactregistry-console` | offline | api | 16 | 0 | 0.5 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.8 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.4 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 41.7 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.8 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.3 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 21 | 0 | 0.3 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.7 |
| ✅ | `offline-api-gcp-pubsub-tabs-project` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 15.7 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 9.6 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 9.2 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 13.0 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 1.9 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 8.2 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 11.4 |
| ✅ | `offline-cli-gcp-scheduler-pubsub` | offline | cli | 6 | 0 | 4.8 |
| ✅ | `offline-post-create-gcp-apigateway-invoke` | offline | api | 5 | 0 | 0.4 |
| ✅ | `offline-post-create-gcp-artifactregistry-reachable` | offline | api | 5 | 0 | 5.3 |
| ✅ | `offline-post-create-gcp-cloudsql-db-connect` | offline | api | 5 | 0 | 3.4 |
| ✅ | `offline-post-create-gcp-event-delivery` | offline | api | 7 | 0 | 2.0 |
| ✅ | `offline-post-create-gcp-memorystore-reachable` | offline | api | 5 | 0 | 1.2 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 26.8 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 16.3 |
| ✅ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 21 | 0 | 13.2 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 17.7 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 2.5 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 2.0 |
| ✅ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 34 | 0 | 1.8 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 2.2 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 9.2 |
| ✅ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 13 | 0 | 5.9 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 5.2 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 5.3 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 5.4 |
| ✅ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 24 | 0 | 5.0 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 5.5 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 1.0 |
| ✅ | `offline-ui-gcp-artifactregistry` | offline | ui | 16 | 0 | 23.6 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 24 | 0 | 24.4 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 21.3 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 66.5 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 59 | 0 | 1.3 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 18.5 |
| ✅ | `offline-ui-gcp-metrics-tab` | offline | ui | 6 | 0 | 6.9 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.9 |
| ✅ | `offline-ui-gcp-properties` | offline | ui | 12 | 0 | 12.1 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.4 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.9 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.8 |

<details><summary>❌ <code>offline-post-create-gcp-gce-ssh</code> log</summary>

```
[PASS] [gcp] create VM
[FAIL] [gcp] VM reaches running :: status=TERMINATED
[FAIL] connect-info available (CONNECT_INFO_MISSING) :: {'ok': False, 'http': 409, 'body': '{"detail":{"error":"instance_not_running","state":"stopped","hint":"Start the instance before connecting."}}'}
```

</details>

<details><summary>❌ <code>nano-post-create-gcp-gce-ssh</code> log</summary>

```
[PASS] instance created through the console's Compute Engine API
[PASS] vyomi-tunnel reachable and VM-capable (vm-tcp)
[PASS] connect info available (CONNECT_INFO_MISSING)
[PASS] console shows an ssh command (CONNECT_INFO_MISSING)
[PASS] shown host is this machine, not an in-browser address (CONNECT_INFO_UNREACHABLE)
[PASS] shown host:port reachable from the user's machine (CONNECT_INFO_UNREACHABLE)
[PASS] key obtainable from what the console shows (CONNECT_INFO_MISSING)
[PASS] shown -i path is a path on the user's machine
[PASS] ssh with the shown command runs a command (POST_CREATE_UNUSABLE)
[PASS] logged in as the gcp default user (gcpuser)
[PASS] file write + read back on the instance
[PASS] a python http.server runs and answers inside the VM
[PASS] console exec runs in the instance VM
[PASS] Connect tab shows the working ssh command
[PASS] Connect tab's browser terminal runs in the VM
[PASS] stop: the VM stops and its ssh port closes
[FAIL] start: the VM comes back with its files (state saved on stop) :: rc=1  cat: /home/gcpuser/pc.txt: No such file or directory

[PASS] delete removes the VM (tunnel port closed, no leak)
```

</details>

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-post-create-azure-vm-ssh` | nano | ui | 17 | 1 | 103.7 |
| ❌ | `offline-post-create-azure-container-app` | offline | api | 4 | 5 | 16.0 |
| ❌ | `offline-post-create-azure-vm-ssh` | offline | api | 1 | 2 | 120.7 |
| ❌ | `offline-sdk-go-azure-app` | offline | sdk-go | 28 | 1 | 3.3 |
| ❌ | `offline-sweepA-azure` | offline | api | 12 | 1 | 84.6 |
| ✅ | `nano-sweepA-azure` | nano | ui | 8 | 0 | 5.2 |
| ✅ | `nano-ui-azure-apim-appinsights` | nano | ui | 6 | 0 | 16.0 |
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 23.1 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 23.9 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 25.8 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 25.5 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 12.0 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 29.4 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 18.8 |
| ✅ | `nano-ui-azure-home` | nano | ui | 8 | 0 | 6.3 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 5.1 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 14.3 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 29.8 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 12.5 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 12.0 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 29.8 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 4.8 |
| ✅ | `nano-ui-azure-resource-group-detail` | nano | ui | 6 | 0 | 5.7 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 7.4 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 9.5 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 12.3 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 19.1 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 50.2 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 13.5 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.4 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 9.5 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 7.7 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 14.1 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.7 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 7.0 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.9 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.8 |
| ✅ | `offline-post-create-azure-event-delivery` | offline | api | 7 | 0 | 3.0 |
| ✅ | `offline-post-create-azure-eventgrid-endpoint` | offline | api | 2 | 0 | 0.3 |
| ✅ | `offline-post-create-azure-keyvault-uri` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-loganalytics` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-openai` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-rbac-checkaccess` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-servicebus-endpoint` | offline | api | 2 | 0 | 0.3 |
| ✅ | `offline-post-create-azure-sql-fqdn` | offline | api | 2 | 0 | 0.3 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 21.2 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 1.8 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.6 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.5 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.5 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 21.9 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 30.5 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.3 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 7.1 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.3 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.4 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.5 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.2 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.1 |
| ✅ | `offline-sdk-python-azure-vm-runcommand` | offline | sdk-python | 11 | 0 | 1.0 |
| ✅ | `offline-ui-azure-apim-appinsights` | offline | ui | 6 | 0 | 7.9 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.8 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 23.0 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.8 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.5 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.2 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.8 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 25.9 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 11.0 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 8.9 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.5 |
| ✅ | `offline-ui-azure-resource-group-detail` | offline | ui | 6 | 0 | 1.6 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 50.2 |

<details><summary>❌ <code>offline-sdk-go-azure-app</code> log</summary>

```
[PASS] environment has staticIp + provisioningState Succeeded
[PASS] ContainerApps.BeginCreateOrUpdate
[PASS] ingress fqdn is assigned from the environment domain
[PASS] ContainerApps.Get hides secret values
[PASS] ContainerApps.ListSecrets returns the value
[PASS] update with a new template creates a new revision
[PASS] ContainerAppsRevisions.ListRevisions shows both revisions
[PASS] ContainerAppsRevisions.GetRevision
[PASS] ContainerAppsRevisions.DeactivateRevision
[PASS] deactivated revision reports Active=false
[PASS] ContainerAppsRevisions.ActivateRevision
[PASS] ContainerAppsRevisionReplicas.ListReplicas has min replicas
[PASS] ContainerApps.BeginStop → runningStatus Stopped
[FAIL] ContainerApps.BeginStart → runningStatus Running <nil>
[PASS] ContainerApps.NewListByResourceGroupPager
[PASS] ContainerApps.NewListBySubscriptionPager
[PASS] DaprComponents.CreateOrUpdate
[PASS] DaprComponents.Get
[PASS] Jobs.BeginCreateOrUpdate
[PASS] Jobs.BeginStart returns an execution
[PASS] Get missing app → 404 ResourceNotFound
[PASS] invalid cpu/memory pair → 400 ContainerAppInvalidResourceTotal
[PASS] delete environment with apps → 409
[PASS] Jobs.BeginDelete
[PASS] ContainerApps.BeginDelete
[PASS] deleted app → 404
[PASS] ManagedEnvironments.BeginDelete
1 check(s) failed
go: downloading github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/appcontainers/armappcontainers/v3 v3.0.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-post-create-azure-vm-ssh</code> log</summary>

```
[PASS] [azure] create VM
[FAIL] [azure] VM reaches running :: HTTP 409
[FAIL] connect-info available (CONNECT_INFO_MISSING) :: {'ok': False, 'http': 409, 'body': '{"detail":{"error":"instance_not_running","state":"","hint":"Start the instance before connecting."}}'}
```

</details>

<details><summary>❌ <code>nano-post-create-azure-vm-ssh</code> log</summary>

```
[PASS] VM created through ARM (the console's wire)
[PASS] vyomi-tunnel reachable and VM-capable (vm-tcp)
[PASS] connect info available (CONNECT_INFO_MISSING)
[PASS] console shows an ssh command (CONNECT_INFO_MISSING)
[PASS] shown host is this machine, not an in-browser address (CONNECT_INFO_UNREACHABLE)
[PASS] shown host:port reachable from the user's machine (CONNECT_INFO_UNREACHABLE)
[PASS] key obtainable from what the console shows (CONNECT_INFO_MISSING)
[PASS] shown -i path is a path on the user's machine
[PASS] ssh with the shown command runs a command (POST_CREATE_UNUSABLE)
[PASS] logged in as the azure default user (azureuser)
[PASS] file write + read back on the instance
[PASS] a python http.server runs and answers inside the VM
[PASS] console exec runs in the instance VM
[PASS] Connect tab shows the working ssh command
[PASS] Connect tab's browser terminal runs in the VM
[PASS] stop: the VM stops and its ssh port closes
[FAIL] start: the VM comes back with its files (state saved on stop) :: rc=1  cat: /home/azureuser/pc.txt: No such file or directory

[PASS] delete removes the VM (tunnel port closed, no leak)
```

</details>

<details><summary>❌ <code>offline-sweepA-azure</code> log</summary>

```
[PASS] SQL server PUT response omits administratorLoginPassword
[PASS] SQL server GET omits administratorLoginPassword
[PASS] SQL server LIST omits administratorLoginPassword
[PASS] Key Vault secret set
[FAIL] Azure VM has a running container :: none found
[PASS] RG delete accepted
[PASS] RG delete removed the VM container
[PASS] RG delete destroyed Key Vault secrets (no longer readable)
[PASS] APIM listSecrets returns a primaryKey
[PASS] APIM wrong subscription key -> 401
[PASS] APIM missing subscription key -> 401
[PASS] APIM unknown API -> 404
[PASS] APIM valid key proxies to the backend (no httpx 502)
```

</details>

<details><summary>❌ <code>offline-post-create-azure-container-app</code> log</summary>

```
[FAIL] a container exists for the app :: containers=[]
[FAIL] the app shows a reachable endpoint (properties.vyomiEndpoint) :: {'backend': 'docker', 'error': 'docker: permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Head "http://%2Fvar%2Frun%2Fdocker.sock/_ping": dial unix /var/run/docker.sock: connect: permission denied.\nSee \'docker run --help\'.'}
[FAIL] GET endpoint from this machine returns nginx's page :: 
[FAIL] app env vars reach the container :: 
[PASS] replica runningState is the container's real state
[PASS] stop removes the container
[FAIL] start runs it again :: []
[PASS] DELETE removes the container (no leak)
[PASS] an image that cannot start is reported Failed, not Running
```

</details>

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-cores` | nano | core | 346 | 0 | 3.7 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.9 |
| ✅ | `nano-ui-crawl` | nano | ui | 63 | 0 | 1303.0 |
| ✅ | `nano-ui-default-cloud` | nano | ui | 15 | 0 | 6.7 |
| ✅ | `nano-ui-drawer` | nano | ui | 72 | 0 | 23.7 |
| ✅ | `offline-console-actions` | offline | api | 371 | 0 | 12.5 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 6.4 |
| ✅ | `offline-ui-console-home` | offline | ui | 35 | 0 | 4.7 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 12.4 |
| ✅ | `offline-ui-crawl` | offline | ui | 58 | 0 | 1265.7 |
| ✅ | `offline-ui-default-cloud` | offline | ui | 18 | 0 | 7.4 |
| ✅ | `offline-ui-drawer` | offline | ui | 87 | 0 | 24.2 |

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

61 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #340 | Azure | spec-commit | Azure compute: WorkloadManager: correct 2026-11-01-preview resource contract (#47558) | 2026-10-30 |
| #252 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #250 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #251 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #249 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #247 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #246 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #244 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #245 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #239 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #240 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #237 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
| #238 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #234 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
| #235 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #233 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-29 |
| #232 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-29 |
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
| #178 | GCP |  | [gcp] Console Metrics tabs: real charts for every service (replace seeded fake sparklines) | 2026-10-29 |
| #171 | AWS |  | [aws] EventBridge: deliver to every target type through NATS (today only SQS targets) | 2026-10-28 |
| #169 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |
| #170 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-28 |
| #168 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-28 |
| #167 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-28 |

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

## SDK operations without a test (120 of 1220)

<details><summary>AWS · <code>apigatewayv2_core</code> (nano) — 6</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand, TagTarget

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (nano) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>elbv2_core</code> (nano) — 1</summary>

TagTarget

</details>
<details><summary>AWS · <code>eventbridge_core</code> (nano) — 1</summary>

SendSqs

</details>
<details><summary>AWS · <code>iam_core</code> (nano) — 1</summary>

UpdateAccessKey

</details>
<details><summary>AWS · <code>lambda_core</code> (nano) — 1</summary>

InvokeRaw

</details>
<details><summary>AWS · <code>logs_core</code> (nano) — 1</summary>

RunInsights

</details>
<details><summary>AWS · <code>sns_core</code> (nano) — 4</summary>

PublishToEndpoint, PublishToPhone, PublishToTopic, SubscribeResult

</details>
<details><summary>AWS · <code>ssm_core</code> (nano) — 3</summary>

AddDocVersion, GetVersion, TagHolder

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 24</summary>

DescribeMapRun, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RunMachine, RunState, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun

</details>
<details><summary>AWS · <code>vpc_core</code> (nano) — 1</summary>

DeleteNetworkAcl

</details>
<details><summary>Azure · <code>azure_operationalinsights_core</code> (nano) — 1</summary>

RunKql

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (nano) — 2</summary>

TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (nano) — 2</summary>

PatchInstance, PatchSettings

</details>
<details><summary>GCP · <code>gcp_kms_core</code> (nano) — 5</summary>

ImportJobCreate, ImportJobList, ImportJobRoute, ImportJobView, PurgeDestroyed

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (nano) — 2</summary>

GetUptime, ListGroups

</details>
<details><summary>AWS · <code>apigatewayv2_core</code> (offline) — 6</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand, TagTarget

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (offline) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>elbv2_core</code> (offline) — 1</summary>

TagTarget

</details>
<details><summary>AWS · <code>eventbridge_core</code> (offline) — 1</summary>

SendSqs

</details>
<details><summary>AWS · <code>iam_core</code> (offline) — 1</summary>

UpdateAccessKey

</details>
<details><summary>AWS · <code>lambda_core</code> (offline) — 1</summary>

InvokeRaw

</details>
<details><summary>AWS · <code>logs_core</code> (offline) — 1</summary>

RunInsights

</details>
<details><summary>AWS · <code>sns_core</code> (offline) — 4</summary>

PublishToEndpoint, PublishToPhone, PublishToTopic, SubscribeResult

</details>
<details><summary>AWS · <code>ssm_core</code> (offline) — 3</summary>

AddDocVersion, GetVersion, TagHolder

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 24</summary>

DescribeMapRun, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RunMachine, RunState, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun

</details>
<details><summary>AWS · <code>vpc_core</code> (offline) — 1</summary>

DeleteNetworkAcl

</details>
<details><summary>Azure · <code>azure_operationalinsights_core</code> (offline) — 1</summary>

RunKql

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (offline) — 2</summary>

TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (offline) — 2</summary>

PatchInstance, PatchSettings

</details>
<details><summary>GCP · <code>gcp_kms_core</code> (offline) — 5</summary>

ImportJobCreate, ImportJobList, ImportJobRoute, ImportJobView, PurgeDestroyed

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (offline) — 2</summary>

GetUptime, ListGroups

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-11-02T19:43:41+00:00 | 269/277 | 5931 | 15 | 0 | 55.4% |  |
| 2026-11-02T17:49:16+00:00 | 274/277 | 5946 | 4 | 2 | 55.4% |  |
| 2026-11-02T15:36:05+00:00 | 269/277 | 5931 | 15 | 0 | 55.4% |  |
| 2026-11-02T13:41:11+00:00 | 230/235 | 5263 | 12 | 14 | 54.4% |  |
| 2026-11-02T11:36:50+00:00 | 231/235 | 5291 | 9 | 14 | 54.4% |  |
| 2026-11-02T09:37:58+00:00 | 230/234 | 5279 | 9 | 22 | 54.4% |  |
| 2026-11-02T07:36:39+00:00 | 228/234 | 5237 | 18 | 14 | 54.4% |  |
| 2026-11-02T05:32:08+00:00 | 229/234 | 5265 | 15 | 14 | 54.4% |  |
| 2026-11-02T03:34:16+00:00 | 229/234 | 5265 | 15 | 22 | 54.4% |  |
| 2026-11-01T23:08:52+00:00 | 162/166 | 3157 | 11 | 14 | 54.4% |  |
| 2026-11-01T21:32:00+00:00 | 228/234 | 5239 | 16 | 22 | 54.4% |  |
| 2026-11-01T19:28:47+00:00 | 229/234 | 5263 | 17 | 14 | 54.4% |  |
| 2026-11-01T17:30:25+00:00 | 229/234 | 5265 | 15 | 14 | 54.4% |  |
| 2026-11-01T15:40:02+00:00 | 229/233 | 5265 | 14 | 22 | 54.4% |  |
| 2026-11-01T13:42:10+00:00 | 229/232 | 5263 | 15 | 14 | 51.0% |  |
| 2026-11-01T11:43:10+00:00 | 228/232 | 5239 | 14 | 14 | 51.0% |  |
| 2026-11-01T09:39:30+00:00 | 229/232 | 5265 | 13 | 22 | 51.0% |  |
| 2026-11-01T07:42:45+00:00 | 229/232 | 5263 | 15 | 14 | 51.0% |  |
| 2026-11-01T05:45:35+00:00 | 229/232 | 5265 | 13 | 14 | 51.0% |  |
| 2026-11-01T03:45:57+00:00 | 229/232 | 5265 | 13 | 22 | 51.0% |  |
| 2026-11-01T01:32:02+00:00 | 216/222 | 5189 | 19 | 14 | 49.5% |  |
| 2026-10-31T23:27:05+00:00 | 215/221 | 5184 | 18 | 20 | 49.5% |  |
| 2026-10-31T21:23:59+00:00 | 211/221 | 5168 | 32 | 38 | 49.5% |  |
| 2026-10-31T19:13:42+00:00 | 190/220 | 4863 | 260 | 63 | 49.5% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
