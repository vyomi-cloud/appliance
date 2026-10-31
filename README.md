# Vyomi Conformance — hourly report

Run **2026-10-31T19:13:42+00:00** · commit `88df98f824d6` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 190/220 | 4863 | 260 | 43/74 | 37/69 | 63 | 49.5% (191/386) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 90/96 | 2183 | 7 | 2/31 | 2/31 | 58 |
| [GCP](#gcp) | 40/59 | 630 | 176 | 18/18 | 17/18 | 1 |
| [Azure](#azure) | 56/58 | 1233 | 13 | 23/25 | 18/20 | 4 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-aws-ec2-row` | nano | ui | 5 | 1 | 14.1 |
| ❌ | `nano-ui-aws-stepfunctions` | nano | ui | 21 | 1 | 21.8 |
| ❌ | `offline-api-aws-detail-tabs` | offline | api | 199 | 1 | 275.5 |
| ❌ | `offline-ui-aws-real-tabs` | offline | ui | 57 | 2 | 274.8 |
| ❌ | `offline-ui-aws-sns` | offline | ui | 35 | 1 | 55.5 |
| ❌ | `offline-ui-aws-stepfunctions` | offline | ui | 21 | 1 | 22.4 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.3 |
| ✅ | `nano-core-aws-detail-tabs` | nano | core | 104 | 0 | 0.1 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.0 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 21.6 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 14.2 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 21 | 0 | 15.4 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 7.4 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.2 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 21.8 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 11.7 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.0 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 15.2 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 3.3 |
| ✅ | `nano-ui-aws-kinesis` | nano | ui | 19 | 0 | 9.8 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 15.2 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 19.5 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 12.1 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 9.9 |
| ✅ | `nano-ui-aws-real-tabs` | nano | ui | 59 | 0 | 253.6 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 2.9 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 10.8 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 30.4 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.6 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 20.2 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 14.5 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.2 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.1 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 15.5 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 8.6 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 6.7 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.7 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 1.5 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.1 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 0.9 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 5.6 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.1 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 21.4 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 28.6 |
| ✅ | `offline-cli-aws-cloudwatch` | offline | cli | 31 | 0 | 26.1 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 41.2 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 19.9 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 30.3 |
| ✅ | `offline-cli-aws-sns` | offline | cli | 76 | 0 | 148.7 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 27.2 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 14.4 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 31.9 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 5.3 |
| ✅ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 37 | 0 | 17.2 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 44.6 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 16.7 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 33.0 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 68.9 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 18.7 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 6.7 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 10.7 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 6.3 |
| ✅ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 26 | 0 | 16.7 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 37.1 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 30.0 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 24.0 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 72.7 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 16.6 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 8.1 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 79 | 0 | 2.4 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.4 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.6 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.0 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 22.3 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 11.1 |
| ✅ | `offline-ui-aws-cloudwatch` | offline | ui | 23 | 0 | 18.2 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 16.8 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 22.4 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.6 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 30.1 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 13.6 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 27.5 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 17.7 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.6 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 9.2 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 21.5 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 9.2 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 9.8 |

<details><summary>❌ <code>offline-api-aws-detail-tabs</code> log</summary>

```
[PASS] Key users: unknown principal rejected
[PASS] Key administrators: added
[PASS] Grants: grant created
[PASS] Grants: invalid operation rejected
[PASS] Grants: revoked
[PASS] General: disabling shows Disabled
── EventBridge rule
[PASS] create rule
[PASS] Rule details: this rule's ARN on the default bus
[PASS] Rule details: disable persists
[PASS] Targets: SQS target added
[PASS] Targets: duplicate Id rejected
[PASS] Targets: list row target count
[PASS] Event pattern: non-array value rejected
[PASS] Event pattern: TestEventPattern matches / rejects sample events
[PASS] Dead-letter queue: non-existent DLQ rejected
[PASS] Dead-letter queue: retry policy + DLQ on the target
── API Gateway REST API
[PASS] create REST API
[PASS] Models: the Empty and Error models every REST API gets
[PASS] Models: create Pet
[PASS] Models: non-alphanumeric name rejected
[PASS] Authorizers: Lambda TOKEN authorizer with its invocation URI
[PASS] Authorizers: missing Lambda rejected
[PASS] Deployments: deployment to prod listed
[PASS] Logs/Tracing: INFO logs + X-Ray on the prod stage
[PASS] Logs/Tracing: unknown stage rejected
[PASS] Resource policy: non execute-api resource rejected
[PASS] Resource policy: IP-restricting policy saved
[PASS] Settings: UpdateRestApi persists
```

</details>

<details><summary>❌ <code>offline-ui-aws-real-tabs</code> log</summary>

```
[FAIL] apigateway Deployments: deployment made in the tab is listed api-0fc3351926ad
AWS/ApiGateway · us-east-1 · 123456789012
delete
Delete
info
API Gateway summary
API ID
api-0fc3351926ad
NAME
rt-api-mvwrgpvm
ENDPOINT TYPE
REGIONAL
CREATED
2026-10-31T18:55:09.000Z
Overview
Activity
Tags
Resources
Authorizers
Models
Stages
Deployments
Settings
Resource policy
Dashb
[PASS] apigateway Settings: API ID from the backend
[PASS] stepfunctions Definition: the machine's states from its ASL
[PASS] stepfunctions Definition: an edited definition persists (UpdateStateMachine)
[PASS] ssm Value: GetParameter value + version of this parameter
[PASS] ssm Properties: DescribeParameters metadata without the value
```

</details>

<details><summary>❌ <code>offline-ui-aws-stepfunctions</code> log</summary>

```
[PASS] Step Functions is on the AWS console rail
[PASS] create form has a realistic default name
[PASS] create with defaults returns 2xx
[PASS] new state machine appears in the list
[PASS] every grid column is filled
[PASS] cost-savings metrics include the new state machine (aws.stepfunctions priced)
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity" renders
[PASS] tab "Tags" renders
[PASS] tab "Executions" renders
[PASS] tab "Definition" renders
[PASS] tab "Versions" renders
[PASS] tab "Aliases" renders
[PASS] tab "Properties" renders
[PASS] tab "Monitoring" renders
[PASS] starting an execution runs the default definition to SUCCEEDED
[PASS] Executions tab lists the SUCCEEDED run
[FAIL] Definition tab shows the Amazon States Language
[PASS] delete removes the state machine from the list
[PASS] deleted state machine is gone from the backend
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-aws-stepfunctions</code> log</summary>

```
[PASS] Step Functions is on the Nano AWS console rail
[PASS] create form has a realistic default name
[PASS] create with defaults returns 2xx
[PASS] new state machine appears in the list
[PASS] every grid column is filled
[PASS] cost-savings metrics updated by the create
[PASS] detail view shows its tabs
[PASS] tab "Overview" renders
[PASS] tab "Activity" renders
[PASS] tab "Tags" renders
[PASS] tab "Executions" renders
[PASS] tab "Definition" renders
[PASS] tab "Versions" renders
[PASS] tab "Aliases" renders
[PASS] tab "Properties" renders
[PASS] tab "Monitoring" renders
[PASS] starting an execution runs the default definition to SUCCEEDED
[PASS] Executions tab lists the SUCCEEDED run
[FAIL] Definition tab shows the Amazon States Language
[PASS] delete removes the state machine from the list
[PASS] deleted state machine is gone from the backend
[PASS] no API errors / page errors during the flow
1 check(s) failed
```

</details>

<details><summary>❌ <code>nano-ui-aws-ec2-row</code> log</summary>

```
[PASS] launched instance is listed with an i-… id [["","Instance ID","Name","Instance type","State","Public IPv4","Private IPv4"],["","i-4c2942f3b7c4adf19","my-ec2-instance","t3.micro","running","54.175.130.30","172.31.4.208"]]
[PASS] no placeholder cells in the row ["","i-4c2942f3b7c4adf19","my-ec2-instance","t3.micro","running","54.175.130.30","172.31.4.208"]
[PASS] state is running ["","i-4c2942f3b7c4adf19","my-ec2-instance","t3.micro","running","54.175.130.30","172.31.4.208"]
[PASS] instance detail by its i-… id answers 200 with the same id status 200
[FAIL] instance carries its default security group 
[PASS] instance survives a console reload [{"tags":{},"name":"my-ec2-instance","image_id":"ami-amzn2023-x86_64","architecture":"x86_64","instance_type":"t3.micro","create_security_group":{"requested":true,"name":"launch-wizard-1","description
```

</details>

<details><summary>❌ <code>offline-ui-aws-sns</code> log</summary>

```
[PASS] topics grid: every column filled
[PASS] topic is a Standard topic
[PASS] creating a topic moves the space's cost-savings metrics
[PASS] detail page has tabs
[PASS] detail tab "Overview" renders
[PASS] detail tab "Activity" renders
[PASS] detail tab "Tags" renders
[PASS] detail tab "Subscriptions" renders
[PASS] detail tab "Publish message" renders
[PASS] detail tab "Access policy" renders
[PASS] detail tab "Properties" renders
[PASS] detail summary shows the topic's real values
[FAIL] Publish message from the tab returns 200 :: HTTP null
[PASS] create subscriptions entry
[PASS] Subscriptions grid lists the new entry
[PASS] Subscriptions: every column filled
[PASS] create mobile push applications entry
[PASS] Mobile push applications grid lists the new entry
[PASS] Mobile push applications: every column filled
[PASS] create sms sandbox entry
[PASS] SMS sandbox grid lists the new entry
[PASS] SMS sandbox: every column filled
[PASS] confirm the pending email subscription
[PASS] publish to the confirmed subscription
[PASS] Message log lists the subscription confirmation
[PASS] Message log lists the published notification
[PASS] Message log: every column filled
[PASS] topic is gone after Delete
[PASS] no API 5xx during the flow
sns ui (offline): FAILED
```

</details>

**UI findings: 58**

<details><summary><b>menu</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Compute</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>EC2</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Lambda</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Storage</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>S3</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Databases</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>RDS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>DynamoDB</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Application Integration</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>SQS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Amazon SNS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Gateway</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Gateway V2</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>EventBridge</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Step Functions</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Analytics</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Kinesis</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Networking & Content Delivery</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>VPC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Elastic Load Balancing</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Security, Identity & Compliance</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>IAM</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>KMS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Management & Governance</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>CloudWatch Logs</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Systems Manager</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>CloudWatch</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>menu</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Compute</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>EC2</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Lambda</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Storage</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>S3</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Databases</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>RDS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>DynamoDB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Application Integration</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>SQS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Amazon SNS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Gateway</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>API Gateway V2</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>EventBridge</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Step Functions</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Analytics</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Kinesis</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Networking & Content Delivery</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>VPC</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Elastic Load Balancing</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Security, Identity & Compliance</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>IAM</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>KMS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Management & Governance</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>CloudWatch Logs</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>Systems Manager</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<details><summary><b>CloudWatch</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `CRAWL_ERROR` |  | locator.click: Timeout 5000ms exceeded. |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-gcp-tabs` | nano | ui | 4 | 2 | 5.1 |
| ❌ | `offline-api-gcp-grid-columns` | offline | api | 0 | 6 | 0.2 |
| ❌ | `offline-sdk-go-gcp` | offline | sdk-go | 0 | 5 | 25.6 |
| ❌ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 0 | 13 | 15.7 |
| ❌ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 0 | 1 | 12.8 |
| ❌ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 0 | 13 | 10.5 |
| ❌ | `offline-sdk-go-gcp-container` | offline | sdk-go | 0 | 15 | 2.2 |
| ❌ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 2 | 14 | 1.3 |
| ❌ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 0 | 2 | 1.2 |
| ❌ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 0 | 16 | 1.4 |
| ❌ | `offline-sdk-java-gcp` | offline | sdk-java | 0 | 6 | 9.6 |
| ❌ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 0 | 1 | 4.3 |
| ❌ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 0 | 12 | 4.5 |
| ❌ | `offline-sdk-java-gcp-container` | offline | sdk-java | 0 | 14 | 4.6 |
| ❌ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 1 | 10 | 4.9 |
| ❌ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 0 | 24 | 4.3 |
| ❌ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 1 | 14 | 4.4 |
| ❌ | `offline-ui-gcp-artifactregistry` | offline | ui | 1 | 6 | 23.2 |
| ❌ | `offline-ui-gcp-cloudscheduler` | offline | ui | 22 | 2 | 24.2 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 5.0 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 15 | 0 | 20.1 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 27.7 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 24.5 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 68.7 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 5.0 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 5.2 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 19.8 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 5.1 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 26.0 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 7.4 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 5.0 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 25.0 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.6 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.8 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.4 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 32.8 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.7 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.7 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.3 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 12.4 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 8.9 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 8.9 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 11.7 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 2.2 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 8.1 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 10.9 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.9 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 21.1 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 66.2 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 0.9 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 18.3 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.6 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.3 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.8 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.7 |

<details><summary>❌ <code>offline-sdk-go-gcp</code> log</summary>

```
go: downloading github.com/googleapis/gax-go/v2 v2.12.5
go: downloading golang.org/x/oauth2 v0.21.0
go: downloading google.golang.org/api v0.187.0
go: downloading google.golang.org/genproto v0.0.0-20240624140628-dc46fd24d27d
go: downloading google.golang.org/grpc v1.64.0
go: downloading google.golang.org/protobuf v1.34.2
go: downloading go.opencensus.io v0.24.0
go: downloading go.opentelemetry.io/otel v1.24.0
go: downloading go.opentelemetry.io/otel/trace v1.24.0
go: downloading google.golang.org/genproto/googleapis/rpc v0.0.0-20240624140628-dc46fd24d27d
go: downloading google.golang.org/genproto/googleapis/api v0.0.0-20240617180043-68d350f18fd4
go: downloading cloud.google.com/go/auth v0.6.1
go: downloading cloud.google.com/go/auth/oauth2adapt v0.2.2
go: downloading go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp v0.49.0
go: downloading golang.org/x/net v0.26.0
go: downloading github.com/golang/groupcache v0.0.0-20210331224755-41bb18bfe9da
go: downloading github.com/go-logr/logr v1.4.1
go: downloading go.opentelemetry.io/otel/metric v1.24.0
go: downloading go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc v0.49.0
go: downloading golang.org/x/time v0.5.0
go: downloading github.com/google/s2a-go v0.1.7
go: downloading github.com/googleapis/enterprise-certificate-proxy v0.3.2
go: downloading golang.org/x/sys v0.21.0
go: downloading github.com/go-logr/stdr v1.2.2
go: downloading github.com/felixge/httpsnoop v1.0.4
go: downloading github.com/golang/protobuf v1.5.4
go: downloading golang.org/x/text v0.16.0
go: downloading golang.org/x/sync v0.7.0
go: downloading golang.org/x/crypto v0.24.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-admin</code> log</summary>

```
[
  {
    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
    "domain": "googleapis.com",
    "metadata": {
      "consumer": "projects/gcp-dev"
    },
    "reason": "CONSUMER_INVALID"
  }
]
FAIL secretmanager secrets.create :: googleapi: Error 403: Permission 'secretmanager.secrets.create' denied for resource 'projects/gcp-dev' (or it may not exist).
FAIL pubsub topics.create :: googleapi: Error 404: Requested project not found or user does not have access to it (project=gcp-dev). Make sure to specify the unique project identifier and not the Google Cloud Console display name.
FAIL pubsub subscriptions.create :: googleapi: Error 404: Requested project not found or user does not have access to it (project=gcp-dev). Make sure to specify the unique project identifier and not the Google Cloud Console display name.
FAIL pubsub subscriptions.get (GetSubscription) :: googleapi: Error 404: Requested project not found or user does not have access to it (project=gcp-dev). Make sure to specify the unique project identifier and not the Google Cloud Console display name.
FAIL pubsub subscriptions.delete :: googleapi: Error 404: Requested project not found or user does not have access to it (project=gcp-dev). Make sure to specify the unique project identifier and not the Google Cloud Console display name.
FAIL pubsub topics.delete :: googleapi: Error 404: Requested project not found or user does not have access to it (project=gcp-dev). Make sure to specify the unique project identifier and not the Google Cloud Console display name.
RESULT pass=0 fail=13
go: downloading google.golang.org/api v0.190.0
go: downloading cloud.google.com/go/auth v0.7.3
go: downloading google.golang.org/grpc v1.64.1
go: downloading cloud.google.com/go/auth/oauth2adapt v0.2.3
go: downloading cloud.google.com/go/compute/metadata v0.5.0
go: downloading github.com/google/s2a-go v0.1.8
go: downloading github.com/googleapis/gax-go/v2 v2.13.0
go: downloading golang.org/x/net v0.27.0
go: downloading google.golang.org/genproto/googleapis/rpc v0.0.0-20240730163845-b1a4ccb954bf
go: downloading github.com/go-logr/logr v1.4.2
go: downloading golang.org/x/sys v0.22.0
go: downloading golang.org/x/crypto v0.25.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp</code> log</summary>

```
== google-cloud-storage (Java) against http://localhost:9000 project=gcp-dev ==
FAIL buckets.insert :: com.google.cloud.storage.StorageException: The caller does not have storage.buckets.list access to the Google Cloud project. Permission 'storage.buckets.list' denied on resource (or it may not exist).
FAIL buckets.list :: com.google.cloud.storage.StorageException: The caller does not have storage.buckets.list access to the Google Cloud project. Permission 'storage.buckets.list' denied on resource (or it may not exist).
FAIL objects.insert :: com.google.cloud.storage.StorageException: 404 Not Found
POST http://localhost:9000/upload/storage/v1/b/java-sdk-test-1793472118975/o?projection=full&uploadType=multipart
FAIL objects.get :: com.google.cloud.storage.StorageException: 404 Not Found
GET http://localhost:9000/download/storage/v1/b/java-sdk-test-1793472118975/o/greeting.txt?alt=media
FAIL objects.delete :: false
FAIL buckets.delete :: false
RESULT pass=0 fail=6
```

</details>

<details><summary>❌ <code>nano-ui-gcp-tabs</code> log</summary>

```
RESULT boot_errors = []
RESULT createInstance = 200
RESULT createUser = 400
RESULT listUsers = ["postgres"]
RESULT deleteUser = 404
RESULT listUsersAfterDelete = 1
RESULT createDb = 200
RESULT listDatabases = ["appdb"]
RESULT createBackup = 200
RESULT listBackups = 1
RESULT eventsOk = true
RESULT eventActions = ["CreateBackup","DeleteUser","CreateUser","Create"]
[PASS] Cloud SQL instance created
[FAIL] user created and listed
[FAIL] user deleted
[PASS] database created and listed
[PASS] backup created and listed
[PASS] activity log records the create
```

</details>

<details><summary>❌ <code>offline-api-gcp-grid-columns</code> log</summary>

```
[FAIL] create VPC network {"error":{"code":404,"message":"The resource 'projects/cloudlearn' was not found","errors":[{"message":"The resource 'pr
[FAIL] create Firestore database {"error":{"code":403,"status":"PERMISSION_DENIED","message":"Permission denied on resource project cloudlearn.","details
[FAIL] create Cloud Function {"error":{"code":403,"status":"PERMISSION_DENIED","message":"Permission denied on resource project cloudlearn.","details
[FAIL] vpc: created resource gridnet-508c34 is listed 
[FAIL] firestore: created resource griddb-508c34 is listed 
[FAIL] functions: created resource gridfn-508c34 is listed
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-cloudscheduler</code> log</summary>

```
== google-cloud-scheduler (Java) against http://localhost:9000 project=java-sched-proj ==
[FAIL] CreateJob (http target) :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateJob duplicate -> ALREADY_EXISTS :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateJob bad schedule -> INVALID_ARGUMENT :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetJob :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetJob missing -> NOT_FOUND :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] ListJobs :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] UpdateJob (patch schedule+description) :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] PauseJob :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] RunJob on paused job -> FAILED_PRECONDITION :: PERMISSION_DENIED
[FAIL] ResumeJob :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] RunJob stamps lastAttemptTime :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] DeleteJob :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
RESULT pass=0 fail=12
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-cloudscheduler</code> log</summary>

```
[FAIL] ResumeJob :: googleapi: Error 403: Permission denied on resource project go-sched-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-sched-proj]
[FAIL] RunJob stamps lastAttemptTime :: googleapi: Error 403: Permission denied on resource project go-sched-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-sched-proj]
[FAIL] DeleteJob :: googleapi: Error 403: Permission denied on resource project go-sched-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-sched-proj] / googleapi: Error 403: Permission denied on resource project go-sched-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-sched-proj]
RESULT pass=0 fail=13
go: downloading cloud.google.com/go/scheduler v1.11.0
go: downloading google.golang.org/api v0.196.0
go: downloading google.golang.org/genproto v0.0.0-20240903143218-8af14fe29dc1
go: downloading google.golang.org/grpc v1.66.0
go: downloading google.golang.org/genproto/googleapis/api v0.0.0-20240827150818-7e3bb234dfed
go: downloading google.golang.org/genproto/googleapis/rpc v0.0.0-20240903143218-8af14fe29dc1
go: downloading cloud.google.com/go/auth v0.9.3
go: downloading cloud.google.com/go/auth/oauth2adapt v0.2.4
go: downloading go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc v0.54.0
go: downloading golang.org/x/oauth2 v0.22.0
go: downloading golang.org/x/time v0.6.0
go: downloading go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp v0.54.0
go: downloading golang.org/x/net v0.28.0
go: downloading go.opentelemetry.io/otel v1.29.0
go: downloading go.opentelemetry.io/otel/metric v1.29.0
go: downloading go.opentelemetry.io/otel/trace v1.29.0
go: downloading github.com/googleapis/enterprise-certificate-proxy v0.3.3
go: downloading golang.org/x/sys v0.24.0
go: downloading golang.org/x/sync v0.8.0
go: downloading golang.org/x/text v0.17.0
go: downloading golang.org/x/crypto v0.26.0
exit status 1
```

</details>

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
[FAIL] job target repointed at a reachable listener :: HTTP 403
[FAIL] Force run → last execution result Success
[PASS] delete removes the job from the list
[PASS] deleted job is gone from the backend
[PASS] no API errors / page errors during the flow
2 check(s) failed
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-container</code> log</summary>

```
== google-cloud-container (Java) against http://localhost:9000 project=java-gke-proj ==
[FAIL] CreateCluster -> CREATE_CLUSTER operation, DONE :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateCluster duplicate -> ALREADY_EXISTS :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateCluster bad name -> INVALID_ARGUMENT :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetCluster (RUNNING, endpoint, version, pool) :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetCluster missing -> NOT_FOUND :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] ListClusters contains the cluster :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateNodePool + GetNodePool :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] SetNodePoolSize persisted :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] ListNodePools (2 pools) :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] SetLabels persisted :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] UpdateCluster (upgrade master) :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] ListOperations + GetOperation :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetServerConfig :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] DeleteNodePool + DeleteCluster :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
RESULT pass=0 fail=14
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-container</code> log</summary>

```
.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj]
[FAIL] CreateNodePool + GetNodePool (autoscaling) :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] <nil>
[FAIL] SetNodePoolSize persisted :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] <nil>
[FAIL] ListNodePools (2 pools) :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj]
[FAIL] SetLabels persisted :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] map[]
[FAIL] SetLabels stale fingerprint -> 409 :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj]
[FAIL] UpdateCluster (upgrade master) :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] 
[FAIL] ListOperations + GetOperation :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj]
[FAIL] GetServerConfig :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj]
[FAIL] DeleteNodePool + DeleteCluster :: googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] / googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj] / googleapi: Error 403: Permission denied on resource project go-gke-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-gke-proj]
RESULT pass=0 fail=15
go: downloading cloud.google.com/go/container v1.39.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-iamcredentials</code> log</summary>

```
== google-cloud-iamcredentials (Java) against http://localhost:9000 project=java-iamc-proj ==
[FAIL] IAM: create service account java-sa-266246 :: 403 {"error":{"code":403,"status":"PERMISSION_DENIED","message":"Permission denied on resource project java-iamc-proj.","details":[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"CONSUMER_INVALID","domain":"googleapis.com","metadata":{"consumer":"projects/java-iamc-proj"}}]}}
[FAIL] IAM: create service account java-del-266246 :: 403 {"error":{"code":403,"status":"PERMISSION_DENIED","message":"Permission denied on resource project java-iamc-proj.","details":[{"@type":"type.googleapis.com/google.rpc.ErrorInfo","reason":"CONSUMER_INVALID","domain":"googleapis.com","metadata":{"consumer":"projects/java-iamc-proj"}}]}}
[FAIL] generateAccessToken :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] generateAccessToken with delegate chain :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] generateAccessToken without scope -> 400 :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[PASS] unknown service account -> 403
[FAIL] generateIdToken :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] signBlob :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] signJwt :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] signJwt non-JSON payload -> 400 :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] console lists the issued credentials (no secrets) :: 200 {"items":[{"id":"cred-1e4d45bef50d","type":"Access token","method":"generateAccessToken","serviceAccount":"vyomi-sa@
RESULT pass=1 fail=10
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-iamcredentials</code> log</summary>

```
== cloud.google.com/go/iam/credentials (Go) against http://localhost:9000 project=go-iamc-proj ==
[FAIL] IAM: create service account go-sa-472268 :: 403
[FAIL] IAM: create service account go-del-472268 :: 403
[FAIL] GenerateAccessToken :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] GenerateAccessToken with lifetime :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] GenerateAccessToken with delegate chain :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] GenerateAccessToken without scope -> 400 :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] GenerateAccessToken lifetime > 12h -> 400 :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[PASS] unknown service account -> 403 PERMISSION_DENIED
[FAIL] project other than '-' -> 400 :: googleapi: Error 403: Permission denied on resource project go-iamc-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-iamc-proj]
[PASS] unknown delegate -> 403
[FAIL] GenerateIdToken :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] GenerateIdToken without audience -> 400 :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] SignBlob :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] SignJwt :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] SignJwt with a non-JSON payload -> 400 :: googleapi: Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).
[FAIL] console lists the issued credentials (no secrets) :: 200
RESULT pass=2 fail=14
go: downloading cloud.google.com/go/iam v1.1.13
go: downloading google.golang.org/genproto/googleapis/api v0.0.0-20240725223205-93522f1f2a9f
exit status 1
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-redis</code> log</summary>

```
== google-cloud-redis (Java) against http://localhost:9000 project=java-redis-proj ==
[FAIL] CreateInstance (LRO) -> Instance READY with host/port :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateInstance duplicate -> ALREADY_EXISTS :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateInstance bad id -> INVALID_ARGUMENT :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetInstance (READY, 2 GB, BASIC, version, labels, node) :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetInstance missing -> NOT_FOUND :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] ListInstances contains the instance :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] UpdateInstance (memory + labels) persisted :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] FailoverInstance on BASIC -> FAILED_PRECONDITION :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] CreateInstance STANDARD_HA (alt zone, 2 nodes, AUTH) :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] FailoverInstance swaps the primary zone :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] UpgradeInstance -> REDIS_7_2 :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] GetInstanceAuthString :: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[PASS] GetInstanceAuthString without AUTH -> error
[FAIL] ExportInstance + ImportInstance (gs:// URIs) :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
[FAIL] DeleteInstance (LRO) removes the instance :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
RESULT pass=1 fail=14
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-redis</code> log</summary>

```
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj]
[FAIL] FailoverInstance on BASIC -> 400 FAILED_PRECONDITION :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj]
[FAIL] CreateInstance STANDARD_HA (alt zone, 2 nodes, AUTH) :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj] <nil>
[FAIL] FailoverInstance swaps the primary zone :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj] <nil>
[FAIL] UpgradeInstance -> REDIS_7_2 :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj] <nil>
[FAIL] GetInstanceAuthString :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj]
[FAIL] GetInstanceAuthString without AUTH -> 400 :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj]
[FAIL] ExportInstance + ImportInstance (gs:// URIs) :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj] / googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj]
[FAIL] DeleteInstance (LRO) removes the instance :: googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj] / googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj] / googleapi: Error 403: Permission denied on resource project go-redis-proj.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/go-redis-proj]
RESULT pass=0 fail=16
go: downloading cloud.google.com/go/redis v1.17.0
go: downloading cloud.google.com/go v0.115.1
go: downloading cloud.google.com/go/longrunning v0.6.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-artifactregistry</code> log</summary>

```
[FAIL] CreateRepository completes with the repository :: java.util.concurrent.ExecutionException: com.google.api.gax.rpc.PermissionDeniedException: Forbidden
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-artifactregistry</code> log</summary>

```
[FAIL] CreateRepository returns an operation :: googleapi: Error 403: Permission denied on resource project gcp-dev.
error details: name = ErrorInfo reason = CONSUMER_INVALID domain = googleapis.com metadata = map[consumer:projects/gcp-dev]
go: downloading cloud.google.com/go/artifactregistry v1.16.0
go: downloading google.golang.org/api v0.214.0
go: downloading google.golang.org/genproto v0.0.0-20241015192408-796eee8c2d53
go: downloading google.golang.org/protobuf v1.35.2
go: downloading cloud.google.com/go/iam v1.2.1
go: downloading cloud.google.com/go/longrunning v0.6.1
go: downloading github.com/googleapis/gax-go/v2 v2.14.0
go: downloading google.golang.org/grpc v1.67.1
go: downloading google.golang.org/genproto/googleapis/api v0.0.0-20241104194629-dd2ea8efbc28
go: downloading google.golang.org/genproto/googleapis/rpc v0.0.0-20241209162323-e6fa225c2576
go: downloading cloud.google.com/go/auth v0.13.0
go: downloading cloud.google.com/go/auth/oauth2adapt v0.2.6
go: downloading cloud.google.com/go/compute/metadata v0.6.0
go: downloading golang.org/x/oauth2 v0.24.0
go: downloading golang.org/x/time v0.8.0
go: downloading golang.org/x/net v0.33.0
go: downloading github.com/googleapis/enterprise-certificate-proxy v0.3.4
go: downloading golang.org/x/sys v0.28.0
go: downloading golang.org/x/sync v0.10.0
go: downloading golang.org/x/text v0.21.0
go: downloading golang.org/x/crypto v0.31.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-ui-gcp-artifactregistry</code> log</summary>

```
[PASS] Artifact Registry: service opens from the rail
[FAIL] Artifact Registry: create with defaults adds a row :: rows 1 → 0
[FAIL] Artifact Registry: every grid column is filled :: no row
[FAIL] Artifact Registry: detail view opens
[FAIL] Artifact Registry: detail tabs render
[FAIL] Artifact Registry: Images rows are filled after the push :: {"rows":0,"blank":0}
[FAIL] Artifact Registry console flow :: locator.click: Timeout 5000ms exceeded.
6 check(s) failed
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-monitoring</code> log</summary>

```
      "@type": "type.googleapis.com/google.rpc.ErrorInfo",
      "reason": "CONSUMER_INVALID",
      "domain": "googleapis.com",
      "metadata": {
        "consumer": "projects/java-mon-proj"
      }
    }
  ],
  "message": "Permission denied on resource project java-mon-proj.",
  "status": "PERMISSION_DENIED"
}
[FAIL] groups create/update/delete :: com.google.api.client.googleapis.json.GoogleJsonResponseException: 403 Forbidden
POST http://localhost:9000/v3/projects/java-mon-proj/groups
{
  "code": 403,
  "details": [
    {
      "@type": "type.googleapis.com/google.rpc.ErrorInfo",
      "reason": "CONSUMER_INVALID",
      "domain": "googleapis.com",
      "metadata": {
        "consumer": "projects/java-mon-proj"
      }
    }
  ],
  "message": "Permission denied on resource project java-mon-proj.",
  "status": "PERMISSION_DENIED"
}

0 passed, 24 failed
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-monitoring</code> log</summary>

```
Details:
[
  {
    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
    "domain": "googleapis.com",
    "metadata": {
      "consumer": "projects/go-mon-proj"
    },
    "reason": "CONSUMER_INVALID"
  }
] <nil>
[FAIL] NotificationChannels.Create missing label → 400 :: googleapi: Error 403: Permission denied on resource project go-mon-proj.
Details:
[
  {
    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
    "domain": "googleapis.com",
    "metadata": {
      "consumer": "projects/go-mon-proj"
    },
    "reason": "CONSUMER_INVALID"
  }
]
panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x50 pc=0x9b3430]

goroutine 1 [running]:
main.main()
	/home/runner/work/appliance/appliance/tests/conformance/gcp-sdk-go-monitoring/main.go:69 +0x890
exit status 2
```

</details>

**UI findings: 1**

<details><summary><b>API Gateway</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Metrics | tab 'Metrics' shows no backend data and nothing about this resource |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-azure-home` | nano | ui | 2 | 5 | 4.2 |
| ❌ | `nano-ui-azure-savings` | nano | ui | 0 | 8 | 94.8 |
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 20.8 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 22.6 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 23.3 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 23.0 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 10.0 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 27.3 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 18.3 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 4.2 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 13.5 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 27.5 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 11.4 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 11.0 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 27.1 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 4.0 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.3 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 9.9 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.4 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 48.9 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 11.6 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.2 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.3 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.2 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 6.9 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 5.4 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 9.0 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 4.6 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 4.9 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 5.2 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 4.8 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 13.6 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 2.6 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 1.6 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.2 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 0.8 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 2.5 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 14.7 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 28.3 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 18.7 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 4.9 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 3.8 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 18.8 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 3.9 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 18.6 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 0.8 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.4 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 22.6 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.3 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.1 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.0 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.5 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 27.7 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.5 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 8.7 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.0 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.5 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 49.7 |

<details><summary>❌ <code>nano-ui-azure-savings</code> log</summary>

```
[FAIL] Storage account: ARM PUT ok 404
[FAIL] Storage account: resource_count rises 0 → 0
[FAIL] Storage account: azure savings rise 0 → 0
[FAIL] Key vault: ARM PUT ok 404
[FAIL] Key vault: resource_count rises 0 → 0
[FAIL] Key vault: azure savings rise 0 → 0
[FAIL] Virtual network: ARM PUT ok 404
[FAIL] Virtual network: resource_count rises 0 → 0
```

</details>

<details><summary>❌ <code>nano-ui-azure-home</code> log</summary>

```
[PASS] home makes no requests to .../undefined
[PASS] data-plane services present on the home dashboard
[FAIL] tile "Blob containers" shows its real count :: shown=null api=0
[FAIL] tile "Cosmos databases" shows its real count :: shown=null api=0
[FAIL] tile "Key Vault secrets" shows its real count :: shown=null api=0
[FAIL] tile "Key Vault keys" shows its real count :: shown=null api=0
[FAIL] tile "Storage queues" shows its real count :: shown=null api=0
2/7 Azure home checks passed
```

</details>

**UI findings: 4**

<details><summary><b>Storage accounts</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Metrics | tab 'Metrics' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cosmos DB</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Metrics | tab 'Metrics' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Storage accounts</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Metrics | tab 'Metrics' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cosmos DB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Metrics | tab 'Metrics' shows no backend data and nothing about this resource |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 43 | 31 | 599.5 |
| ❌ | `offline-cost-savings` | offline | api | 8 | 1 | 19.5 |
| ❌ | `offline-ui-crawl` | offline | ui | 37 | 32 | 462.5 |
| ✅ | `nano-cores` | nano | core | 344 | 0 | 3.4 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.5 |
| ✅ | `offline-console-actions` | offline | api | 371 | 0 | 13.4 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 19.9 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 31 services crawled, 29 with findings
UI crawl offline: 2/31 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"unimplemented":29,"live":1,"static":5}
[offline/azure] 20 services crawled, 2 with findings
UI crawl offline: 18/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":313,"static":2}
[offline/gcp] 18 services crawled, 1 with findings
UI crawl offline: 17/18 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":227,"static":1}
```

</details>

<details><summary>❌ <code>offline-cost-savings</code> log</summary>

```
== aws: S3 bucket ==
PASS: aws: creating a S3 bucket raises the space resource_count
PASS: aws: creating a S3 bucket raises aws savings
PASS: aws: using the S3 bucket (5 × 2 MB uploads) raises savings

== gcp: Cloud Storage bucket ==
FAIL: gcp: savings check ran :: <HTTPError 403: 'Forbidden'>

== azure: Storage account ==
PASS: azure: creating a Storage account raises the space resource_count
PASS: azure: creating a Storage account raises azure savings
PASS: azure: using the Storage account (5 × 2 MB uploads) raises savings

== azure: Virtual machine (Standard_B1s) ==
PASS: azure: creating a VM raises the space resource_count
PASS: azure: a Standard_B1s VM adds its 730 h list price ($7.59) to Azure savings

RESULT fail=1
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 31 services crawled, 29 with findings
UI crawl nano: 2/31 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"unimplemented":29,"live":1,"static":5}
[nano/azure] 25 services crawled, 2 with findings
UI crawl nano: 23/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":327,"static":3}
[nano/gcp] 18 services crawled, 0 with findings
UI crawl nano: 18/18 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":228}
```

</details>

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

## SDK operations without a test (226 of 1244)

<details><summary>AWS · <code>apigatewayv2_core</code> (nano) — 6</summary>

CreateGrand, CreateMapping, CreateVpclink, GetChild, GetGrand, TagTarget

</details>
<details><summary>AWS · <code>cloudwatch_core</code> (nano) — 5</summary>

QueryEnvelope, RunQueries, SetState, StateReasonData, StateUpdatedTimestamp

</details>
<details><summary>AWS · <code>elbv2_core</code> (nano) — 1</summary>

TagTarget

</details>
<details><summary>AWS · <code>kinesis_core</code> (nano) — 7</summary>

DescribeConsumer, DisableMonitoring, EnableMonitoring, ListConsumers, PutPolicy, StartEncryption, StopEncryption

</details>
<details><summary>AWS · <code>logs_core</code> (nano) — 1</summary>

RunInsights

</details>
<details><summary>AWS · <code>sns_core</code> (nano) — 4</summary>

PublishToEndpoint, PublishToPhone, PublishToTopic, SubscribeResult

</details>
<details><summary>AWS · <code>ssm_core</code> (nano) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 34</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>Azure · <code>azure_arm_ext_core</code> (nano) — 2</summary>

RunCommandAction, SetBackrefList

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (nano) — 7</summary>

CreateRepo, DeleteRepo, GetRepo, ListRepos, PatchRepo, TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (nano) — 2</summary>

PatchInstance, PatchSettings

</details>
<details><summary>GCP · <code>gcp_kms_core</code> (nano) — 6</summary>

ImportJobCreate, ImportJobList, ImportJobRoute, ImportJobView, ImportJobs, PurgeDestroyed

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (nano) — 16</summary>

CreateChannel, CreateDescriptor, CreateUptime, DeleteChannel, DeleteDescriptor, DeleteGroup, GetDescriptor, GetUptime, ListChannels, ListDescriptors, ListGroups, ListTimeSeries, PatchChannel, PatchPolicy, PatchUptime, UpdateGroup

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
<details><summary>AWS · <code>kinesis_core</code> (offline) — 7</summary>

DescribeConsumer, DisableMonitoring, EnableMonitoring, ListConsumers, PutPolicy, StartEncryption, StopEncryption

</details>
<details><summary>AWS · <code>logs_core</code> (offline) — 1</summary>

RunInsights

</details>
<details><summary>AWS · <code>sns_core</code> (offline) — 4</summary>

PublishToEndpoint, PublishToPhone, PublishToTopic, SubscribeResult

</details>
<details><summary>AWS · <code>ssm_core</code> (offline) — 22</summary>

AddDocVersion, CancelCommand, CreateBaseline, CreateWindow, DeleteBaseline, DeleteWindow, DescribeBaselines, DescribeInstanceInfo, DescribeInstanceInformation, DescribeTargets, DescribeWindows, GetBaseline, GetByPath, GetInvocation, GetVersion, GetWindow, ListDocVersions, ListInvocations, TagHolder, UnlabelParameterVersion, UpdateDefaultVersion, UpdateWindow

</details>
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 34</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>Azure · <code>azure_arm_ext_core</code> (offline) — 2</summary>

RunCommandAction, SetBackrefList

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (offline) — 7</summary>

CreateRepo, DeleteRepo, GetRepo, ListRepos, PatchRepo, TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_cloudsql_core</code> (offline) — 2</summary>

PatchInstance, PatchSettings

</details>
<details><summary>GCP · <code>gcp_kms_core</code> (offline) — 6</summary>

ImportJobCreate, ImportJobList, ImportJobRoute, ImportJobView, ImportJobs, PurgeDestroyed

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (offline) — 16</summary>

CreateChannel, CreateDescriptor, CreateUptime, DeleteChannel, DeleteDescriptor, DeleteGroup, GetDescriptor, GetUptime, ListChannels, ListDescriptors, ListGroups, ListTimeSeries, PatchChannel, PatchPolicy, PatchUptime, UpdateGroup

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
| 2026-10-31T19:13:42+00:00 | 190/220 | 4863 | 260 | 63 | 49.5% |  |
| 2026-10-31T17:27:12+00:00 | 226/230 | 5204 | 73 | 66 | 49.5% |  |
| 2026-10-31T15:39:35+00:00 | 222/229 | 5233 | 17 | 22 | 49.5% |  |
| 2026-10-31T13:41:06+00:00 | 225/229 | 5234 | 16 | 14 | 49.5% |  |
| 2026-10-31T11:36:15+00:00 | 224/229 | 5210 | 15 | 14 | 49.5% |  |
| 2026-10-31T09:30:46+00:00 | 225/228 | 5231 | 13 | 22 | 49.5% |  |
| 2026-10-31T07:33:08+00:00 | 225/228 | 5229 | 15 | 14 | 49.5% |  |
| 2026-10-31T05:34:56+00:00 | 221/226 | 5209 | 15 | 14 | 49.5% |  |
| 2026-10-31T03:34:03+00:00 | 219/225 | 5201 | 21 | 22 | 49.5% |  |
| 2026-10-31T01:29:57+00:00 | 202/225 | 4941 | 190 | 18 | 49.5% |  |
| 2026-10-30T23:27:06+00:00 | 200/225 | 4943 | 188 | 20 | 49.5% |  |
| 2026-10-30T21:13:04+00:00 | 209/220 | 5161 | 37 | 28 | 49.5% |  |
| 2026-10-30T19:00:40+00:00 | 229/237 | 4886 | 93 | 105 | 43.3% |  |
| 2026-10-30T17:07:13+00:00 | 229/237 | 4872 | 107 | 117 | 43.3% |  |
| 2026-10-30T15:09:18+00:00 | 229/237 | 4873 | 106 | 137 | 43.3% |  |
| 2026-10-30T07:35:16+00:00 | 17/18 | 254 | 9 | 88 | 43.3% |  |
| 2026-10-30T06:05:16+00:00 | 225/233 | 4848 | 84 | 71 | 43.3% |  |
| 2026-10-30T03:58:30+00:00 | 218/226 | 4774 | 100 | 156 | 43.3% |  |
| 2026-10-30T01:47:29+00:00 | 215/223 | 4740 | 109 | 148 | 43.1% |  |
| 2026-10-29T23:56:10+00:00 | 215/223 | 4762 | 87 | 79 | 43.1% |  |
| 2026-10-29T22:06:27+00:00 | 215/223 | 4749 | 100 | 161 | 43.1% |  |
| 2026-10-29T19:55:18+00:00 | 207/216 | 4653 | 111 | 224 | 42.6% |  |
| 2026-10-29T17:38:33+00:00 | 203/215 | 4682 | 78 | 6 | 42.6% |  |
| 2026-10-29T15:43:50+00:00 | 180/182 | 3721 | 6 | 8 | 42.1% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
