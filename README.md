# Vyomi Conformance — hourly report

Run **2026-11-07T12:08:08+00:00** · commit `9f7ee2c770e7` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 289/290 | 6103 | 400 | 63/63 | 58/58 | 0 | 62.7% (242/386) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 114/114 | 2356 | 0 | 20/20 | 20/20 | 0 |
| [GCP](#gcp) | 87/87 | 1269 | 0 | 18/18 | 18/18 | 0 |
| [Azure](#azure) | 76/77 | 1355 | 400 | 25/25 | 20/20 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `aws-dynamodb-bulk-ops-core` | nano | api | 13 | 0 | 0.0 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.4 |
| ✅ | `nano-core-aws-detail-tabs` | nano | core | 104 | 0 | 0.2 |
| ✅ | `nano-post-create-aws-ec2-ssh` | nano | ui | 18 | 0 | 90.6 |
| ✅ | `nano-store-delete-sync` | nano | core | 4 | 0 | 0.0 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 5.1 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 24.3 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 17.0 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 23 | 0 | 17.8 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 10.2 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 10.8 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 24.4 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 13.3 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 17.0 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 25.9 |
| ✅ | `nano-ui-aws-event-delivery` | nano | ui | 9 | 0 | 6.8 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 17.0 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 5.1 |
| ✅ | `nano-ui-aws-kinesis` | nano | ui | 19 | 0 | 12.6 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 17.0 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 21.3 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 14.0 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 12.0 |
| ✅ | `nano-ui-aws-real-tabs` | nano | ui | 59 | 0 | 274.2 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 4.9 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 12.8 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 33.1 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 10.3 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 22.6 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 24.3 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 16.4 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 4.8 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 12.4 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 16.9 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 11.0 |
| ✅ | `offline-api-aws-console-next` | offline | api | 7 | 0 | 0.2 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 0.8 |
| ✅ | `offline-api-aws-detail-tabs` | offline | api | 200 | 0 | 20.6 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 0.4 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.1 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 0.2 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 0.6 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.1 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 12.9 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 22.9 |
| ✅ | `offline-cli-aws-cloudwatch` | offline | cli | 31 | 0 | 17.6 |
| ✅ | `offline-cli-aws-ec2-sg-description` | offline | cli | 2 | 0 | 4.7 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 17.0 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 11.9 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 12.4 |
| ✅ | `offline-cli-aws-sns` | offline | cli | 76 | 0 | 57.1 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 19.5 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 14.0 |
| ✅ | `offline-core-aws-vpc-nacl` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-post-create-aws-apigateway-invoke` | offline | api | 4 | 0 | 0.8 |
| ✅ | `offline-post-create-aws-apigatewayv2-invoke` | offline | api | 1 | 0 | 1.2 |
| ✅ | `offline-post-create-aws-ec2-ssh` | offline | api | 10 | 0 | 5.5 |
| ✅ | `offline-post-create-aws-event-delivery` | offline | api | 6 | 0 | 2.1 |
| ✅ | `offline-post-create-aws-iam-actions` | offline | api | 13 | 0 | 1.4 |
| ✅ | `offline-post-create-aws-rds-db-connect` | offline | api | 6 | 0 | 3.6 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 35.6 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 2.8 |
| ✅ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 37 | 0 | 5.4 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 6.0 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 2.8 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 7.1 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 8.1 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 6.4 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 2.2 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 14.1 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 3.9 |
| ✅ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 26 | 0 | 5.2 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 6.1 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 19.2 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 5.1 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 10.5 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 4.8 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 3.8 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 79 | 0 | 2.9 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.5 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.7 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.1 |
| ✅ | `offline-sdk-python-aws-ops3` | offline | sdk-python | 12 | 0 | 0.8 |
| ✅ | `offline-sdk-python-aws-ops4` | offline | sdk-python | 17 | 0 | 1.2 |
| ✅ | `offline-sdk-python-aws-ops5` | offline | sdk-python | 4 | 0 | 0.8 |
| ✅ | `offline-sweepA-aws` | offline | sdk-python | 14 | 0 | 3.4 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 21.0 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 8.5 |
| ✅ | `offline-ui-aws-cloudwatch` | offline | ui | 23 | 0 | 14.6 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 10.5 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 18.8 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 9.4 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 22.0 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 10.3 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 19.4 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 10.1 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 7.9 |
| ✅ | `offline-ui-aws-real-tabs` | offline | ui | 59 | 0 | 222.7 |
| ✅ | `offline-ui-aws-sns` | offline | ui | 36 | 0 | 29.8 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 6.6 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 18.9 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 20.7 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 8.4 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 7.1 |
| ✅ | `offline-ui-sdk-roundtrip` | offline | ui | 18 | 0 | 44.4 |

**UI findings: 0**

No open UI findings.

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-core-triggers` | nano | api | 11 | 0 | 0.4 |
| ✅ | `nano-gcp-cloudsql-core` | nano | core | 43 | 0 | 0.0 |
| ✅ | `nano-gcp-compute-core` | nano | core | 18 | 0 | 0.0 |
| ✅ | `nano-gcp-kms-core` | nano | core | 35 | 0 | 0.1 |
| ✅ | `nano-post-create-gcp-gce-ssh` | nano | ui | 18 | 0 | 62.2 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.2 |
| ✅ | `nano-ui-gcp-apigw-monitoring-tabs` | nano | ui | 7 | 0 | 24.5 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 16 | 0 | 19.6 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 25.3 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 23.4 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 66.0 |
| ✅ | `nano-ui-gcp-eventarc-delivery` | nano | ui | 7 | 0 | 7.5 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 3.1 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 59 | 0 | 3.4 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.7 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 24.0 |
| ✅ | `nano-ui-gcp-properties` | nano | ui | 12 | 0 | 14.6 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 5.6 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.2 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 22.9 |
| ✅ | `nano-ui-gcp-scheduler-pubsub` | nano | ui | 5 | 0 | 3.3 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 3.2 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.5 |
| ✅ | `offline-api-gcp-artifactregistry-console` | offline | api | 16 | 0 | 0.5 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.7 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.3 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 32.8 |
| ✅ | `offline-api-gcp-console-maintenance-routes` | offline | api | 5 | 0 | 0.1 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.6 |
| ✅ | `offline-api-gcp-console-tools-routes` | offline | api | 16 | 0 | 0.1 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.2 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 21 | 0 | 0.2 |
| ✅ | `offline-api-gcp-kms-importjobs-ar-tags` | offline | api | 17 | 0 | 0.7 |
| ✅ | `offline-api-gcp-provider-connect` | offline | api | 15 | 0 | 0.2 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.7 |
| ✅ | `offline-api-gcp-pubsub-tabs-project` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-sql-patch-monitoring` | offline | api | 10 | 0 | 0.2 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 12.6 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 6.7 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 6.2 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 9.0 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 1.5 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 6.1 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 7.2 |
| ✅ | `offline-cli-gcp-scheduler-pubsub` | offline | cli | 6 | 0 | 3.3 |
| ✅ | `offline-cli-gcp-scheduler-pubsub-gcloud` | offline | cli | 7 | 0 | 3.2 |
| ✅ | `offline-post-create-gcp-apigateway-invoke` | offline | api | 5 | 0 | 0.3 |
| ✅ | `offline-post-create-gcp-artifactregistry-reachable` | offline | api | 5 | 0 | 5.0 |
| ✅ | `offline-post-create-gcp-cloudsql-db-connect` | offline | api | 5 | 0 | 3.3 |
| ✅ | `offline-post-create-gcp-event-delivery` | offline | api | 7 | 0 | 1.7 |
| ✅ | `offline-post-create-gcp-gce-ssh` | offline | api | 10 | 0 | 7.7 |
| ✅ | `offline-post-create-gcp-memorystore-reachable` | offline | api | 5 | 0 | 1.1 |
| ✅ | `offline-sdk-gcp-kms-python` | offline | sdk | 5 | 0 | 5.5 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 20.7 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 11.9 |
| ✅ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 21 | 0 | 9.2 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 14.3 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 1.7 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 1.6 |
| ✅ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 36 | 0 | 1.2 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 1.6 |
| ✅ | `offline-sdk-go-gcp-sqladmin` | offline | sdk-go | 4 | 0 | 0.9 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 10.5 |
| ✅ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 13 | 0 | 4.1 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 3.7 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 3.5 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 3.5 |
| ✅ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 24 | 0 | 3.6 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 3.5 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.7 |
| ✅ | `offline-ui-gcp-artifactregistry` | offline | ui | 16 | 0 | 23.2 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 24 | 0 | 23.9 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 20.7 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 65.9 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 59 | 0 | 0.9 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 18.0 |
| ✅ | `offline-ui-gcp-metrics-tab` | offline | ui | 6 | 0 | 6.6 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.3 |
| ✅ | `offline-ui-gcp-properties` | offline | ui | 12 | 0 | 11.5 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.2 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.7 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.3 |

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 0 | 400 | 20.3 |
| ✅ | `nano-post-create-azure-vm-ssh` | nano | ui | 18 | 0 | 85.8 |
| ✅ | `nano-sweepA-azure` | nano | ui | 8 | 0 | 4.8 |
| ✅ | `nano-ui-azure-apim-appinsights` | nano | ui | 6 | 0 | 15.1 |
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 22.9 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 23.7 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 25.4 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 25.1 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 11.7 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 29.1 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 11 | 0 | 27.1 |
| ✅ | `nano-ui-azure-home` | nano | ui | 8 | 0 | 6.1 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 4.7 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 13.8 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 29.5 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 12.3 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 11.8 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 29.2 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 4.5 |
| ✅ | `nano-ui-azure-resource-group-detail` | nano | ui | 6 | 0 | 5.3 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 7.2 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 9.1 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 10.4 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.7 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 49.7 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 12.3 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.4 |
| ✅ | `offline-api-azure-new-api-versions` | offline | api | 8 | 0 | 1.0 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 10.0 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 8.6 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 14.1 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.6 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 7.1 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 8.0 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.9 |
| ✅ | `offline-post-create-azure-container-app` | offline | api | 9 | 0 | 2.7 |
| ✅ | `offline-post-create-azure-event-delivery` | offline | api | 7 | 0 | 2.4 |
| ✅ | `offline-post-create-azure-eventgrid-endpoint` | offline | api | 2 | 0 | 0.3 |
| ✅ | `offline-post-create-azure-keyvault-uri` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-loganalytics` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-openai` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-rbac-checkaccess` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-servicebus-endpoint` | offline | api | 2 | 0 | 0.3 |
| ✅ | `offline-post-create-azure-sql-fqdn` | offline | api | 2 | 0 | 0.3 |
| ✅ | `offline-post-create-azure-vm-ssh` | offline | api | 10 | 0 | 5.2 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 21.1 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 4.6 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 1.9 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 3.1 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.0 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.4 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 28.2 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 22.0 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 7.1 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.0 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.2 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.4 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.1 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.1 |
| ✅ | `offline-sdk-python-azure-vm-runcommand` | offline | sdk-python | 11 | 0 | 1.3 |
| ✅ | `offline-sweepA-azure` | offline | api | 13 | 0 | 4.2 |
| ✅ | `offline-ui-azure-apim-appinsights` | offline | ui | 6 | 0 | 7.9 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.8 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 23.0 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.8 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.5 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 11 | 0 | 24.2 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.8 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 25.9 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 11.0 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 8.8 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.5 |
| ✅ | `offline-ui-azure-resource-group-detail` | offline | ui | 6 | 0 | 1.5 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 50.6 |

<details><summary>❌ <code>offline-sdk-go-azure-operationalinsights</code> log</summary>

```
[PASS] SavedSearches.CreateOrUpdate
[PASS] SavedSearches.Get
[PASS] saved search without query → 400
[PASS] SavedSearches.ListByWorkspace
[PASS] SavedSearches.Delete
[PASS] deleted saved search → 404
[PASS] Tables.ListByWorkspace has built-in tables
[PASS] Tables.BeginCreateOrUpdate custom table
[PASS] custom table name without _CL → 400
[PASS] Tables.Get
[PASS] Tables.BeginUpdate retention
[PASS] deleting a built-in table → 400
[PASS] Tables.BeginDelete custom table
[PASS] deleted table → 404
[PASS] DataSources.CreateOrUpdate
[PASS] DataSources.ListByWorkspace filtered by kind
[PASS] DataSources.Delete
[PASS] Data Collector ingest → 200
[PASS] LogsClient.QueryWorkspace runs KQL (where + count)
[PASS] unsupported KQL → 400 error
[PASS] BeginDelete workspace (LRO)
[PASS] deleted workspace → 404
all checks passed
go: downloading go1.24.0 (linux/amd64)
go: downloading github.com/Azure/azure-sdk-for-go/sdk/azcore v1.20.0
go: downloading github.com/Azure/azure-sdk-for-go/sdk/monitor/azquery v1.2.0
go: downloading github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/operationalinsights/armoperationalinsights/v2 v2.0.2
go: downloading github.com/Azure/azure-sdk-for-go/sdk/internal v1.11.2
go: downloading golang.org/x/net v0.48.0
go: downloading golang.org/x/text v0.32.0
```

</details>

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-cores` | nano | core | 375 | 0 | 5.9 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 6.2 |
| ✅ | `nano-ui-crawl` | nano | ui | 63 | 0 | 1414.9 |
| ✅ | `nano-ui-default-cloud` | nano | ui | 15 | 0 | 8.2 |
| ✅ | `nano-ui-drawer` | nano | ui | 72 | 0 | 31.6 |
| ✅ | `offline-console-actions` | offline | api | 375 | 0 | 18.8 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 8.2 |
| ✅ | `offline-ui-console-home` | offline | ui | 35 | 0 | 5.4 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 12.5 |
| ✅ | `offline-ui-crawl` | offline | ui | 58 | 0 | 1301.0 |
| ✅ | `offline-ui-default-cloud` | offline | ui | 18 | 0 | 7.9 |
| ✅ | `offline-ui-drawer` | offline | ui | 87 | 0 | 27.4 |

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

16 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #534 | Azure | spec-commit | Azure storage: [Storage] `2027-03-07` svc version for STG105 Rust releease TypeSpec Changes (#48016) | 2026-11-07 |
| #530 | AWS | operation-added | AWS ssm: new operation RegisterDefaultHostManagementConfiguration | 2026-11-06 |
| #529 | AWS | operation-added | AWS ssm: new operation DeregisterDefaultHostManagementConfiguration | 2026-11-06 |
| #528 | Azure | spec-commit | Azure sql: Update client settings for sql release 2026-08-01-preview (#47938) | 2026-11-06 |
| #519 | GCP | lifecycle | API Gateway: Announcement (November 04, 2026) | 2026-11-05 |
| #516 | Azure | lifecycle | Retirement: Transition to Entra ID (formerly known as Azure AD) to query data from Azure Monitor application insights by March 31, 2027 | 2026-11-04 |
| #180 | Cross-cloud |  | [shared] Conformance crawl must catch: fake charts, page errors under real tiers, cross-cloud layout drift | 2026-10-29 |
| #178 | GCP |  | [gcp] Console Metrics tabs: real charts for every service (replace seeded fake sparklines) | 2026-10-29 |
| #171 | AWS |  | [aws] EventBridge: deliver to every target type through NATS (today only SQS targets) | 2026-10-28 |
| #149 | GCP |  | [gcp] Cloud Scheduler → Pub/Sub: scheduled message must reach gcloud pubsub subscriptions pull (offline appliance) | 2026-10-27 |
| #146 | GCP | lifecycle | Google Kubernetes Engine: Change (October 26, 2026) | 2026-10-27 |
| #144 | GCP | lifecycle | Google Kubernetes Engine: Stable channel (October 26, 2026) | 2026-10-27 |
| #145 | GCP | lifecycle | Google Kubernetes Engine: No channel (deprecated) (October 26, 2026) | 2026-10-27 |
| #143 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (October 26, 2026) | 2026-10-27 |
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

## SDK operations without a test (0 of 1022)


## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-11-07T12:08:08+00:00 | 289/290 | 6103 | 400 | 0 | 62.7% |  |
| 2026-11-07T10:19:21+00:00 | 288/290 | 6101 | 402 | 2 | 62.7% |  |
| 2026-11-07T08:30:08+00:00 | 287/289 | 6092 | 402 | 2 | 60.9% |  |
| 2026-11-07T06:42:03+00:00 | 288/289 | 6094 | 400 | 0 | 60.9% |  |
| 2026-11-07T04:53:19+00:00 | 288/289 | 6094 | 400 | 0 | 60.9% |  |
| 2026-11-07T03:05:22+00:00 | 288/289 | 6094 | 400 | 0 | 60.9% |  |
| 2026-11-07T01:12:19+00:00 | 288/289 | 6094 | 400 | 0 | 57.8% |  |
| 2026-11-06T23:15:54+00:00 | 288/289 | 6092 | 400 | 0 | 57.8% |  |
| 2026-11-06T21:28:41+00:00 | 288/289 | 6068 | 400 | 0 | 57.8% |  |
| 2026-11-06T19:29:54+00:00 | 288/289 | 6063 | 400 | 0 | 57.8% |  |
| 2026-11-06T17:38:45+00:00 | 289/291 | 6078 | 401 | 0 | 61.4% |  |
| 2026-11-06T15:52:34+00:00 | 289/290 | 6071 | 400 | 0 | 60.9% |  |
| 2026-11-06T14:00:09+00:00 | 289/290 | 6071 | 400 | 0 | 58.8% |  |
| 2026-11-06T12:02:15+00:00 | 289/290 | 6070 | 400 | 0 | 58.8% |  |
| 2026-11-06T10:15:41+00:00 | 289/290 | 6067 | 400 | 0 | 58.8% |  |
| 2026-11-06T08:26:54+00:00 | 289/290 | 6067 | 400 | 0 | 58.8% |  |
| 2026-11-06T06:34:39+00:00 | 289/290 | 6067 | 400 | 0 | 57.8% |  |
| 2026-11-06T04:46:43+00:00 | 289/290 | 6067 | 400 | 0 | 57.8% |  |
| 2026-11-06T02:53:02+00:00 | 287/289 | 6062 | 401 | 0 | 57.8% |  |
| 2026-11-06T01:07:06+00:00 | 287/288 | 6050 | 400 | 0 | 57.8% |  |
| 2026-11-05T22:56:03+00:00 | 273/288 | 5963 | 38 | 6 | 57.8% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
