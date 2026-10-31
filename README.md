# Vyomi Conformance — hourly report

Run **2026-10-31T03:34:03+00:00** · commit `0a9111f71812` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 219/225 | 5201 | 21 | 60/63 | 54/58 | 22 | 49.5% (191/386) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 93/96 | 2180 | 8 | 17/20 | 16/20 | 22 |
| [GCP](#gcp) | 59/60 | 897 | 6 | 18/18 | 18/18 | 0 |
| [Azure](#azure) | 62/62 | 1270 | 0 | 25/25 | 20/20 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-cli-aws-sns` | offline | cli | 70 | 6 | 244.7 |
| ❌ | `offline-ui-aws-vpc-details-tab` | offline | ui | 0 | 1 | 34.7 |
| ❌ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 1 | 1 | 36.2 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.4 |
| ✅ | `nano-core-aws-detail-tabs` | nano | core | 104 | 0 | 0.2 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 4.8 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 22.3 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 16.9 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 21 | 0 | 17.0 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 10.0 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 10.6 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 23.2 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 13.1 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 15.8 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 25.6 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 17.0 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 5.1 |
| ✅ | `nano-ui-aws-kinesis` | nano | ui | 19 | 0 | 40.7 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 15.8 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 51.2 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 13.9 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 11.8 |
| ✅ | `nano-ui-aws-real-tabs` | nano | ui | 59 | 0 | 273.8 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 4.6 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 12.8 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 32.5 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 10.3 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 21.9 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 22.3 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 16.1 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 4.8 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 11.8 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 17.2 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 10.2 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 6.4 |
| ✅ | `offline-api-aws-detail-tabs` | offline | api | 200 | 0 | 284.4 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.6 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 1.5 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.1 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 1.0 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 5.8 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.1 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.1 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.1 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 20.5 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 28.1 |
| ✅ | `offline-cli-aws-cloudwatch` | offline | cli | 31 | 0 | 24.1 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 42.4 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 19.4 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 29.9 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 27.4 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 14.7 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 29.6 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 5.4 |
| ✅ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 37 | 0 | 15.7 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 45.1 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 16.8 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 33.1 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 70.7 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 18.3 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 5.9 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 13.4 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 5.9 |
| ✅ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 26 | 0 | 15.2 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 36.7 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 30.4 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 23.4 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 71.2 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 16.7 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 7.5 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 79 | 0 | 2.2 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.4 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.4 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 0.9 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 22.4 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 11.2 |
| ✅ | `offline-ui-aws-cloudwatch` | offline | ui | 23 | 0 | 17.6 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 17.1 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 22.9 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.6 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 32.4 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 45.6 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 59.7 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 17.6 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.5 |
| ✅ | `offline-ui-aws-real-tabs` | offline | ui | 59 | 0 | 277.6 |
| ✅ | `offline-ui-aws-sns` | offline | ui | 36 | 0 | 52.3 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 9.1 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 22.7 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 23.0 |

<details><summary>❌ <code>offline-ui-aws-vpc-details-tab</code> log</summary>

```
[FAIL] run TimeoutError: locator.click: Timeout 30000ms exceeded.
```

</details>

<details><summary>❌ <code>offline-ui-aws-vpc-sg-iam-cells</code> log</summary>

```
[PASS] IAM user listing carries an ARN
[FAIL] run TimeoutError: locator.click: Timeout 30000ms exceeded.
```

</details>

<details><summary>❌ <code>offline-cli-aws-sns</code> log</summary>

```
[FAIL] the notification signature verifies :: json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
[PASS] create-topic (failing endpoint)
[PASS] subscribe a 500-returning endpoint with a DeliveryPolicy + RedrivePolicy
[PASS] confirm the failing subscription
[PASS] publish to the failing topic
[FAIL] a 500-returning endpoint is retried per the delivery policy :: attempts: 0
[PASS] after the retries the message lands in the RedrivePolicy dead-letter queue
[PASS] unsubscribe the HTTP subscription
[PASS] delete the HTTP topic
[PASS] create-topic (FIFO, dedup)
[PASS] a FIFO duplicate within the 5-minute window is dropped (same MessageId, delivered once)
[PASS] unsubscribe
[PASS] delete-topic
[PASS] delete-topic (FIFO)
[PASS] deleted topic is gone from list-topics
aws sns cli: 70 passed, 6 failed
Traceback (most recent call last):
  File "/tmp/tmp.gyHPIsnuRa/recv.py", line 11, in <module>
    HTTPServer(("0.0.0.0", port), H).serve_forever()
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/socketserver.py", line 457, in __init__
    self.server_bind()
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/http/server.py", line 140, in server_bind
    socketserver.TCPServer.server_bind(self)
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/socketserver.py", line 478, in server_bind
    self.socket.bind(self.server_address)
OSError: [Errno 98] Address already in use
Traceback (most recent call last):
  File "<string>", line 4, in <module>
IndexError: list index out of range
```

</details>

**UI findings: 22**

<details><summary><b>EC2</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Details | tab Details: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Details | tab Details: column "KEY PAIR ASSIGNED AT LAUNCH" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Details | tab Details: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "Description" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "Description" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>EC2</b> (offline) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Details | tab Details: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Details | tab Details: column "KEY PAIR ASSIGNED AT LAUNCH" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Details | tab Details: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Networking | tab Networking: column "Description" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "Description" shows "-"/blank in 2 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Lambda</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Configuration | tab Configuration: column "DESCRIPTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Versions | tab Versions: column "Description" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "SORT KEY" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>Lambda</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Configuration | tab Configuration: column "DESCRIPTION" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Versions | tab Versions: column "Description" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | resource detail: column "SORT KEY" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>VPC</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | list: column "Name" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` |  | after create: column "Name" shows "-"/blank in 1 row(s) |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-ui-gcp-artifactregistry` | offline | ui | 1 | 6 | 24.4 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 4.3 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 15 | 0 | 19.6 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 25.6 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 22.4 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 67.1 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 4.4 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 5.0 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 19.6 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 4.4 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 24.1 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.9 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 4.4 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 23.0 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 4.4 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.6 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.8 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.5 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 23.7 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.7 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 0.3 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.7 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.4 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 17.5 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 10.1 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 10.5 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 13.3 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 2.5 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 9.0 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 12.3 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 27.0 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 17.0 |
| ✅ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 21 | 0 | 13.5 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 17.7 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 2.8 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 2.0 |
| ✅ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 34 | 0 | 1.7 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 2.3 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 12.4 |
| ✅ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 13 | 0 | 5.7 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 5.3 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 5.2 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 5.3 |
| ✅ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 24 | 0 | 4.9 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 5.3 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.8 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 24 | 0 | 24.3 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 21.1 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 66.3 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 0.9 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 20.2 |
| ✅ | `offline-ui-gcp-metrics-tab` | offline | ui | 6 | 0 | 6.9 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.7 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.3 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.8 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.7 |

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

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-apim-appinsights` | nano | ui | 6 | 0 | 11.8 |
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 20.3 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 22.4 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 22.9 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 22.6 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.8 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 25.8 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 17.3 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.6 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 2.7 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 11.8 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 26.9 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 9.9 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 9.4 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 26.6 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 2.7 |
| ✅ | `nano-ui-azure-resource-group-detail` | nano | ui | 6 | 0 | 3.2 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.2 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 7.3 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 6.7 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 16.8 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 46.7 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 7.8 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.6 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.5 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 10.4 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 7.7 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 14.8 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.5 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 7.0 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.3 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.5 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 22.4 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 3.1 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 1.9 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.9 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.1 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.1 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 21.0 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 31.8 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.5 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 7.9 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.7 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.6 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.7 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.4 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.3 |
| ✅ | `offline-ui-azure-apim-appinsights` | offline | ui | 6 | 0 | 7.8 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.9 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 23.2 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.8 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.6 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.3 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.9 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 28.2 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.8 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 8.9 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.5 |
| ✅ | `offline-ui-azure-resource-group-detail` | offline | ui | 6 | 0 | 1.5 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.8 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 49.9 |

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 60 | 3 | 1190.8 |
| ❌ | `offline-ui-crawl` | offline | ui | 54 | 4 | 1101.6 |
| ✅ | `nano-cores` | nano | core | 344 | 0 | 5.9 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 6.1 |
| ✅ | `offline-console-actions` | offline | api | 371 | 0 | 12.3 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 22.3 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 24.5 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 20 services crawled, 4 with findings
UI crawl offline: 16/20 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"live":235,"static":18,"partial":17}
[offline/azure] 20 services crawled, 0 with findings
UI crawl offline: 20/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":313,"static":2}
[offline/gcp] 18 services crawled, 0 with findings
UI crawl offline: 18/18 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":222,"unimplemented":5,"static":1}
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 20 services crawled, 3 with findings
UI crawl nano: 17/20 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":237,"static":18,"partial":15}
[nano/azure] 25 services crawled, 0 with findings
UI crawl nano: 25/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":328,"static":2}
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

## SDK operations without a test (226 of 1246)

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
| 2026-10-29T14:08:26+00:00 | 179/181 | 3708 | 5 | 7 | 42.1% |  |
| 2026-10-29T12:34:40+00:00 | 177/181 | 3687 | 11 | 8 | 42.1% |  |
| 2026-10-29T10:56:55+00:00 | 176/178 | 3670 | 5 | 7 | 39.6% |  |
| 2026-10-29T08:59:30+00:00 | 174/176 | 3654 | 6 | 10 | 34.4% |  |
| 2026-10-29T07:25:18+00:00 | 172/175 | 3647 | 6 | 7 | 34.4% |  |
| 2026-10-29T05:46:05+00:00 | 159/175 | 3589 | 54 | 44 | 34.4% |  |
| 2026-10-29T03:56:27+00:00 | 115/123 | 2760 | 39 | 29 | 16.1% |  |
| 2026-10-29T01:35:23+00:00 | 93/105 | 2464 | 85 | 81 | 14.3% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
