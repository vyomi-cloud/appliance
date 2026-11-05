# Vyomi Conformance — hourly report

Run **2026-11-05T22:56:03+00:00** · commit `c10f15848994` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 273/288 | 5963 | 38 | 60/63 | 56/58 | 6 | 57.8% (223/386) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 107/112 | 2319 | 15 | 20/20 | 20/20 | 0 |
| [GCP](#gcp) | 84/87 | 1262 | 3 | 18/18 | 18/18 | 0 |
| [Azure](#azure) | 72/77 | 1292 | 15 | 22/25 | 18/20 | 6 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-post-create-aws-ec2-ssh` | nano | ui | 17 | 1 | 123.9 |
| ❌ | `nano-ui-aws-apigw-row` | nano | ui | 1 | 5 | 16.9 |
| ❌ | `nano-ui-aws-kinesis` | nano | ui | 16 | 3 | 12.7 |
| ❌ | `nano-ui-aws-lambda-row` | nano | ui | 1 | 3 | 17.3 |
| ❌ | `nano-ui-aws-vpc-row` | nano | ui | 4 | 3 | 17.1 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.4 |
| ✅ | `nano-core-aws-detail-tabs` | nano | core | 104 | 0 | 0.2 |
| ✅ | `nano-store-delete-sync` | nano | core | 4 | 0 | 0.0 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 4.9 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 24.5 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 23 | 0 | 17.9 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 10.5 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 10.9 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 24.7 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 13.3 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 17.0 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 26.1 |
| ✅ | `nano-ui-aws-event-delivery` | nano | ui | 9 | 0 | 6.9 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 17.1 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 5.3 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 21.3 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 14.2 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 11.9 |
| ✅ | `nano-ui-aws-real-tabs` | nano | ui | 59 | 0 | 273.9 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 4.7 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 12.9 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 32.7 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 10.3 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 22.3 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 24.2 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 16.3 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 4.8 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 12.4 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 10.9 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 1.0 |
| ✅ | `offline-api-aws-detail-tabs` | offline | api | 200 | 0 | 24.9 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 0.3 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.2 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 0.3 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 0.8 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.5 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.2 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 13.0 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 26.9 |
| ✅ | `offline-cli-aws-cloudwatch` | offline | cli | 31 | 0 | 21.0 |
| ✅ | `offline-cli-aws-ec2-sg-description` | offline | cli | 2 | 0 | 5.8 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 20.8 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 14.5 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 15.0 |
| ✅ | `offline-cli-aws-sns` | offline | cli | 76 | 0 | 65.7 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 23.3 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 17.0 |
| ✅ | `offline-core-aws-vpc-nacl` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-post-create-aws-apigateway-invoke` | offline | api | 4 | 0 | 1.1 |
| ✅ | `offline-post-create-aws-apigatewayv2-invoke` | offline | api | 1 | 0 | 1.2 |
| ✅ | `offline-post-create-aws-ec2-ssh` | offline | api | 10 | 0 | 5.6 |
| ✅ | `offline-post-create-aws-event-delivery` | offline | api | 6 | 0 | 2.7 |
| ✅ | `offline-post-create-aws-iam-actions` | offline | api | 13 | 0 | 1.4 |
| ✅ | `offline-post-create-aws-rds-db-connect` | offline | api | 6 | 0 | 3.7 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.3 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 42.8 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 3.5 |
| ✅ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 37 | 0 | 6.1 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 7.1 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 3.4 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 8.0 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 9.6 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 7.8 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 2.6 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 15.3 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 4.7 |
| ✅ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 26 | 0 | 6.0 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 7.3 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 20.1 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 5.9 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 12.2 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 5.5 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 4.8 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 79 | 0 | 3.4 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.7 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 2.1 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.2 |
| ✅ | `offline-sdk-python-aws-ops3` | offline | sdk-python | 12 | 0 | 0.9 |
| ✅ | `offline-sdk-python-aws-ops4` | offline | sdk-python | 15 | 0 | 1.5 |
| ✅ | `offline-sdk-python-aws-ops5` | offline | sdk-python | 4 | 0 | 1.1 |
| ✅ | `offline-sweepA-aws` | offline | sdk-python | 14 | 0 | 3.8 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 21.5 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 8.8 |
| ✅ | `offline-ui-aws-cloudwatch` | offline | ui | 23 | 0 | 14.8 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 11.1 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 19.1 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 9.6 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 22.5 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 10.7 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 19.9 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 10.3 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 8.2 |
| ✅ | `offline-ui-aws-real-tabs` | offline | ui | 59 | 0 | 224.7 |
| ✅ | `offline-ui-aws-sns` | offline | ui | 36 | 0 | 30.4 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 6.8 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 19.4 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 21.0 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 8.6 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 7.3 |
| ✅ | `offline-ui-sdk-roundtrip` | offline | ui | 18 | 0 | 45.4 |

<details><summary>❌ <code>nano-ui-aws-lambda-row</code> log</summary>

```
[FAIL] created function is listed by name [["","Function name","Runtime","Handler","Memory (MB)","Timeout (s)","Last modified"],["","my-function-5b18","python3.12","lambda_function.lambda_handler","128","3","2026-11-05T22:49:46.000Z"]]
[FAIL] no placeholder cells in the row 
[FAIL] function survives a console reload ["my-function-5b18"]
[PASS] no page error while opening the create wizard
```

</details>

<details><summary>❌ <code>nano-ui-aws-apigw-row</code> log</summary>

```
[FAIL] created API is listed by name [["","API ID","Name","Endpoint type","Created"],["","6fe2efdce1","MyApi-ba90","REGIONAL","2026-11-05T22:50:20.000Z"]]
[FAIL] no placeholder cells in the row 
[FAIL] API survives a console reload ["MyApi-ba90"]
[FAIL] GET .../resources lists the API's resource tree with methods []
[FAIL] GET .../stages lists the deployed stage with an invoke URL []
[PASS] no page error while opening the create wizard
```

</details>

<details><summary>❌ <code>nano-ui-aws-vpc-row</code> log</summary>

```
[FAIL] created VPC is listed by name [["","VPC ID","Name","IPv4 CIDR","State","Subnets"],["","vpc-819753c7cf01","my-vpc-46d1","10.0.0.0/16","available","0"]]
[FAIL] no placeholder cells in the row 
[FAIL] VPC survives a console reload ["my-vpc-46d1"]
[PASS] GET /api/vpc/subnets answers 200 200
[PASS] GET /api/vpc/internet-gateways answers 200 200
[PASS] GET /api/vpc/route-tables lists the new VPC's main route table [{"id":"rtb-996d71d3b9f1","route_table_id":"rtb-996d71d3b9f1","name":"rtb-996d71d3b9f1","vpc_id":"vpc-819753c7cf01","is_main":true,"routes":[{"destination":"10.0.0.0/16","target":"local"}],"associatio
[PASS] no page error while opening the create wizard
```

</details>

<details><summary>❌ <code>nano-post-create-aws-ec2-ssh</code> log</summary>

```
[PASS] instance launched through the console
[PASS] vyomi-tunnel reachable and VM-capable (vm-tcp)
[PASS] connect info available (CONNECT_INFO_MISSING)
[PASS] console shows an ssh command (CONNECT_INFO_MISSING)
[PASS] shown host is this machine, not an in-browser address (CONNECT_INFO_UNREACHABLE)
[PASS] shown host:port reachable from the user's machine (CONNECT_INFO_UNREACHABLE)
[PASS] key obtainable from what the console shows (CONNECT_INFO_MISSING)
[PASS] shown -i path is a path on the user's machine
[PASS] ssh with the shown command runs a command (POST_CREATE_UNUSABLE)
[PASS] logged in as the aws default user (ec2-user)
[PASS] file write + read back on the instance
[PASS] a python http.server runs and answers inside the VM
[PASS] console exec runs in the instance VM
[PASS] Connect tab shows the working ssh command
[FAIL] Connect tab's browser terminal runs in the VM :: TimeoutError: locator.fill: Timeout 30000ms exceeded.
[PASS] stop: the VM stops and its ssh port closes
[PASS] start: the VM comes back with its files (state saved on stop)
[PASS] delete removes the VM (tunnel port closed, no leak)
```

</details>

<details><summary>❌ <code>nano-ui-aws-kinesis</code> log</summary>

```
[PASS] Kinesis is on the service rail
[PASS] create with the form's defaults returns 2xx
[PASS] the new stream appears in the list
[PASS] column "Name" is filled
[PASS] column "Status" is filled
[PASS] column "Capacity mode" is filled
[PASS] column "Open shards" is filled
[PASS] column "Data retention" is filled
[PASS] column "Encryption" is filled
[PASS] column "Consumers" is filled
[PASS] column "Created" is filled
[PASS] tab "Overview" renders content
[PASS] tab "Configuration" renders content
[PASS] tab "Shards and consumers" renders content
[PASS] tab "Tags" renders content
[FAIL] the stream is in the Nano store the relay serves :: ["my-stream-1961"]
[FAIL] delete the stream :: HTTP 404
[FAIL] the stream is gone from the list :: 1
[PASS] no API 5xx while driving the console
3 check(s) failed
```

</details>

**UI findings: 0**

No open UI findings.

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-post-create-gcp-gce-ssh` | nano | ui | 17 | 1 | 104.4 |
| ❌ | `nano-ui-gcp-apigw-monitoring-tabs` | nano | ui | 2 | 1 | 37.8 |
| ❌ | `offline-ui-gcp-create-defaults` | offline | ui | 35 | 1 | 66.2 |
| ✅ | `nano-core-triggers` | nano | api | 11 | 0 | 0.6 |
| ✅ | `nano-gcp-cloudsql-core` | nano | core | 43 | 0 | 0.0 |
| ✅ | `nano-gcp-compute-core` | nano | core | 18 | 0 | 0.1 |
| ✅ | `nano-gcp-kms-core` | nano | core | 35 | 0 | 0.3 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.9 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 16 | 0 | 22.1 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 26.4 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 23.3 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 67.8 |
| ✅ | `nano-ui-gcp-eventarc-delivery` | nano | ui | 7 | 0 | 9.4 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 3.8 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 59 | 0 | 4.2 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.4 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 4.1 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 25.6 |
| ✅ | `nano-ui-gcp-properties` | nano | ui | 12 | 0 | 15.2 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.4 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 4.0 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 24.4 |
| ✅ | `nano-ui-gcp-scheduler-pubsub` | nano | ui | 5 | 0 | 4.0 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 4.1 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.5 |
| ✅ | `offline-api-gcp-artifactregistry-console` | offline | api | 16 | 0 | 0.5 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.8 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.4 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 41.7 |
| ✅ | `offline-api-gcp-console-maintenance-routes` | offline | api | 5 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.7 |
| ✅ | `offline-api-gcp-console-tools-routes` | offline | api | 16 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 21 | 0 | 0.2 |
| ✅ | `offline-api-gcp-kms-importjobs-ar-tags` | offline | api | 17 | 0 | 0.8 |
| ✅ | `offline-api-gcp-provider-connect` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.6 |
| ✅ | `offline-api-gcp-pubsub-tabs-project` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-sql-patch-monitoring` | offline | api | 10 | 0 | 0.3 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 11.0 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 8.2 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 7.9 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 11.4 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 1.7 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 7.6 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 10.4 |
| ✅ | `offline-cli-gcp-scheduler-pubsub` | offline | cli | 6 | 0 | 4.3 |
| ✅ | `offline-cli-gcp-scheduler-pubsub-gcloud` | offline | cli | 7 | 0 | 4.4 |
| ✅ | `offline-post-create-gcp-apigateway-invoke` | offline | api | 5 | 0 | 0.3 |
| ✅ | `offline-post-create-gcp-artifactregistry-reachable` | offline | api | 5 | 0 | 5.3 |
| ✅ | `offline-post-create-gcp-cloudsql-db-connect` | offline | api | 5 | 0 | 3.3 |
| ✅ | `offline-post-create-gcp-event-delivery` | offline | api | 7 | 0 | 1.9 |
| ✅ | `offline-post-create-gcp-gce-ssh` | offline | api | 10 | 0 | 7.2 |
| ✅ | `offline-post-create-gcp-memorystore-reachable` | offline | api | 5 | 0 | 1.2 |
| ✅ | `offline-sdk-gcp-kms-python` | offline | sdk | 5 | 0 | 8.3 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 25.4 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 16.1 |
| ✅ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 21 | 0 | 13.8 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 18.1 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 2.2 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 1.9 |
| ✅ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 36 | 0 | 1.5 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 2.0 |
| ✅ | `offline-sdk-go-gcp-sqladmin` | offline | sdk-go | 4 | 0 | 1.1 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 9.6 |
| ✅ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 13 | 0 | 5.5 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 4.7 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 4.6 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 4.9 |
| ✅ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 24 | 0 | 4.3 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 4.7 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.8 |
| ✅ | `offline-ui-gcp-artifactregistry` | offline | ui | 16 | 0 | 23.6 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 24 | 0 | 24.2 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 21.1 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 59 | 0 | 1.1 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 18.3 |
| ✅ | `offline-ui-gcp-metrics-tab` | offline | ui | 6 | 0 | 6.8 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.6 |
| ✅ | `offline-ui-gcp-properties` | offline | ui | 12 | 0 | 11.8 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.3 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.8 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.6 |

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
[FAIL] Eventarc: create with defaults is accepted [409] 409 http://localhost:9000/api/gcp/extras/eventarc/triggers
[PASS] Eventarc: the new resource is listed
[PASS] Eventarc: no placeholder cells
[PASS] Pub/Sub: service is on the rail
[PASS] Pub/Sub: create with defaults is accepted
[PASS] Pub/Sub: the new resource is listed
[PASS] Pub/Sub: no placeholder cells
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
[FAIL] Connect tab's browser terminal runs in the VM :: TimeoutError: locator.fill: Timeout 30000ms exceeded.
[PASS] stop: the VM stops and its ssh port closes
[PASS] start: the VM comes back with its files (state saved on stop)
[PASS] delete removes the VM (tunnel port closed, no leak)
```

</details>

<details><summary>❌ <code>nano-ui-gcp-apigw-monitoring-tabs</code> log</summary>

```
[PASS] API Gateway: has a gateway
[PASS] API Gateway: Configs tab offers an Add action
[FAIL] run :: TimeoutError: locator.fill: Timeout 30000ms exceeded.
```

</details>

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-post-create-azure-vm-ssh` | nano | ui | 17 | 1 | 120.1 |
| ❌ | `nano-ui-azure-app` | nano | ui | 28 | 1 | 23.1 |
| ❌ | `nano-ui-azure-appconfiguration` | nano | ui | 3 | 6 | 44.9 |
| ❌ | `nano-ui-azure-cognitiveservices` | nano | ui | 3 | 6 | 45.9 |
| ❌ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 0 | 1 | 19.6 |
| ✅ | `nano-sweepA-azure` | nano | ui | 8 | 0 | 5.1 |
| ✅ | `nano-ui-azure-apim-appinsights` | nano | ui | 6 | 0 | 15.6 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 25.4 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 11.9 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 29.4 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 20.5 |
| ✅ | `nano-ui-azure-home` | nano | ui | 8 | 0 | 6.1 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 4.9 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 14.0 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 29.6 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 12.3 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 11.8 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 29.4 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 4.8 |
| ✅ | `nano-ui-azure-resource-group-detail` | nano | ui | 6 | 0 | 5.5 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 7.2 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 9.6 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 10.8 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 19.0 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 49.8 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 13.8 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.4 |
| ✅ | `offline-api-azure-new-api-versions` | offline | api | 4 | 0 | 0.7 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 11.6 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 8.5 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 13.1 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.1 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 6.7 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.6 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.3 |
| ✅ | `offline-post-create-azure-container-app` | offline | api | 9 | 0 | 3.9 |
| ✅ | `offline-post-create-azure-event-delivery` | offline | api | 7 | 0 | 3.0 |
| ✅ | `offline-post-create-azure-eventgrid-endpoint` | offline | api | 2 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-keyvault-uri` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-loganalytics` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-openai` | offline | api | 6 | 0 | 0.5 |
| ✅ | `offline-post-create-azure-rbac-checkaccess` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-servicebus-endpoint` | offline | api | 2 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-sql-fqdn` | offline | api | 2 | 0 | 0.4 |
| ✅ | `offline-post-create-azure-vm-ssh` | offline | api | 10 | 0 | 5.5 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 20.6 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 5.0 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 1.9 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.8 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.2 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.4 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 33.0 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 22.4 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 6.8 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.4 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.4 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.6 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.0 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.7 |
| ✅ | `offline-sdk-python-azure-vm-runcommand` | offline | sdk-python | 11 | 0 | 1.5 |
| ✅ | `offline-sweepA-azure` | offline | api | 13 | 0 | 4.4 |
| ✅ | `offline-ui-azure-apim-appinsights` | offline | ui | 6 | 0 | 7.9 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.9 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 23.0 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.8 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.5 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.3 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.9 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 26.1 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 11.0 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 8.9 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.5 |
| ✅ | `offline-ui-azure-resource-group-detail` | offline | ui | 6 | 0 | 1.6 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.7 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 51.7 |

<details><summary>❌ <code>nano-ui-azure-app</code> log</summary>

```
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
[FAIL] Ingress tab shows the application URL :: Ingress
Ingress routes HTTP/TCP traffic to the app.
Ingress
Enabled
Ingress traffic
Accepting traffic from anywhere
Target port
80
Transport
Auto
Insecure connections
Not allowed
Application URL
https
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
[FAIL] create form defaults the pricing tier to Standard :: ["appconfig-cloudlearn-fb4a","Standard-36b4","false","7","eastus"]
[FAIL] create with defaults returns 2xx :: HTTP 400
[FAIL] new store appears in the list :: appconfig-cloudlearn-fb4a
[FAIL] every grid column is filled :: blank: - · []
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[FAIL] console flow :: locator.click: Timeout 5000ms exceeded.
6 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-azure-cognitiveservices</code> log</summary>

```
[PASS] Azure AI services is on the Nano Azure console rail
[PASS] service page explains what the service does
[PASS] create form has a realistic default name
[FAIL] create form defaults kind OpenAI and tier S0 :: ["ai-cloudlearn-f236","OpenAI","S0-f0af","ai-cloudlearn","Enabled","eastus"]
[FAIL] create with defaults returns 2xx :: HTTP 400
[FAIL] new account appears in the list :: ai-cloudlearn-f236
[FAIL] every grid column is filled :: blank: - · []
[FAIL] cost-savings metrics updated by the create :: count 0→0, $0→$0
[FAIL] console flow :: locator.click: Timeout 5000ms exceeded.
6 check(s) failed
```

</details>

<details><summary>❌ <code>offline-sdk-go-azure-operationalinsights</code> log</summary>

```
go: downloading go1.24.0 (linux/amd64)
go: downloading github.com/Azure/azure-sdk-for-go/sdk/azcore v1.20.0
go: downloading github.com/Azure/azure-sdk-for-go/sdk/monitor/azquery v1.2.0
go: downloading github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/operationalinsights/armoperationalinsights/v2 v2.0.2
go: downloading github.com/Azure/azure-sdk-for-go/sdk/internal v1.11.2
go: downloading golang.org/x/net v0.48.0
go: downloading golang.org/x/text v0.32.0
# azureoperationalinsights
./main.go:174:14: undefined: azlogs
./main.go:176:4: undefined: azlogs
./main.go:179:14: undefined: rewriteTransport
./main.go:183:41: undefined: azlogs
./main.go:191:43: undefined: azlogs
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
[FAIL] Connect tab's browser terminal runs in the VM :: TimeoutError: locator.fill: Timeout 30000ms exceeded.
[PASS] stop: the VM stops and its ssh port closes
[PASS] start: the VM comes back with its files (state saved on stop)
[PASS] delete removes the VM (tunnel port closed, no leak)
```

</details>

**UI findings: 6**

<details><summary><b>Storage accounts</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_REJECTED` |  | create with default values was rejected: "error" |
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>App Configuration</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Azure AI services</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Virtual Machines</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<details><summary><b>Storage accounts</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CREATE_NO_ROW` |  | create with defaults added no resource to the list |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 60 | 3 | 1703.6 |
| ❌ | `offline-ui-crawl` | offline | ui | 56 | 2 | 1603.8 |
| ✅ | `nano-cores` | nano | core | 347 | 0 | 6.4 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 6.2 |
| ✅ | `nano-ui-default-cloud` | nano | ui | 15 | 0 | 8.2 |
| ✅ | `nano-ui-drawer` | nano | ui | 72 | 0 | 31.4 |
| ✅ | `offline-console-actions` | offline | api | 375 | 0 | 21.1 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 8.9 |
| ✅ | `offline-ui-console-home` | offline | ui | 35 | 0 | 6.3 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 12.9 |
| ✅ | `offline-ui-default-cloud` | offline | ui | 18 | 0 | 8.6 |
| ✅ | `offline-ui-drawer` | offline | ui | 87 | 0 | 28.5 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 20 services crawled, 0 with findings
UI crawl offline: 20/20 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"live":252,"static":18}
[offline/azure] 20 services crawled, 2 with findings
UI crawl offline: 18/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":273,"unimplemented":2}
[offline/gcp] 18 services crawled, 0 with findings
UI crawl offline: 18/18 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":229}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 20 services crawled, 0 with findings
UI crawl nano: 20/20 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":253,"static":17}
[nano/azure] 25 services crawled, 3 with findings
UI crawl nano: 22/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":279,"unimplemented":3}
[nano/gcp] 18 services crawled, 0 with findings
UI crawl nano: 18/18 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":229}
```

</details>

## New features since the last run

First inventory taken this run; new features are reported from the next run.

## Upstream changes (AWS / GCP / Azure backlog)

17 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #520 | Azure | spec-commit | Azure keyvault: [KeyVault] Introduce Version 2026-10-01-preview for Azure Key Vault (#47789) | 2026-11-05 |
| #519 | GCP | lifecycle | API Gateway: Announcement (November 04, 2026) | 2026-11-05 |
| #516 | Azure | lifecycle | Retirement: Transition to Entra ID (formerly known as Azure AD) to query data from Azure Monitor application insights by March 31, 2027 | 2026-11-04 |
| #515 | AWS | operation-added | AWS dynamodb: new operation StartBulkPutItems | 2026-11-04 |
| #514 | AWS | operation-added | AWS dynamodb: new operation ListBulkOperations | 2026-11-04 |
| #512 | AWS | operation-added | AWS dynamodb: new operation CancelBulkOperation | 2026-11-04 |
| #513 | AWS | operation-added | AWS dynamodb: new operation DescribeBulkOperation | 2026-11-04 |
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

## SDK operations without a test (88 of 1262)

<details><summary>AWS · <code>apigatewayv2_core</code> (nano) — 5</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (nano) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>eventbridge_core</code> (nano) — 2</summary>

GetArchive, SendSqs

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
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 23</summary>

DescribeMapRun, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RunMachine, RunState, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun

</details>
<details><summary>AWS · <code>apigatewayv2_core</code> (offline) — 5</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (offline) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>eventbridge_core</code> (offline) — 2</summary>

GetArchive, SendSqs

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
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 23</summary>

DescribeMapRun, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RunMachine, RunState, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-11-05T22:56:03+00:00 | 273/288 | 5963 | 38 | 6 | 57.8% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
|  | 0/0 | 0 | 0 | 0 | 0.0% |  |
| 2026-11-04T21:28:55+00:00 | 284/286 | 6003 | 401 | 0 | 57.8% |  |
| 2026-11-04T19:20:25+00:00 | 283/286 | 5990 | 405 | 4 | 57.8% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
