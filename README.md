# Vyomi Conformance — hourly report

Run **2026-10-29T17:38:33+00:00** · commit `8d200a007397` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 203/215 | 4682 | 78 | 60/63 | 55/58 | 6 | 42.6% (145/340) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 88/92 | 1707 | 55 | 17/20 | 17/20 | 6 |
| [GCP](#gcp) | 53/58 | 878 | 15 | 18/18 | 18/18 | 0 |
| [Azure](#azure) | 58/58 | 1246 | 0 | 25/25 | 20/20 | 0 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-cli-aws-cloudwatch` | offline | cli | 17 | 14 | 36.3 |
| ❌ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 16 | 21 | 81.1 |
| ❌ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 11 | 15 | 8.7 |
| ❌ | `offline-ui-aws-cloudwatch` | offline | ui | 3 | 5 | 11.9 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.3 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 4.0 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 23.0 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 14.9 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 21 | 0 | 16.4 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 8.7 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 10.0 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 23.8 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 12.4 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 16.1 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 24.8 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 15.0 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 4.3 |
| ✅ | `nano-ui-aws-kinesis` | nano | ui | 19 | 0 | 40.3 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 16.4 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 50.2 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 13.2 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 11.0 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 3.9 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 11.9 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 31.2 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 9.4 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 22.1 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 23.9 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 15.4 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 4.1 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 11.0 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 16.4 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 9.5 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 7.1 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.6 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.1 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 1.5 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.1 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 1.3 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 5.6 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.6 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.2 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.2 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 20.2 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 28.4 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 44.1 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 22.3 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 32.3 |
| ✅ | `offline-cli-aws-sns` | offline | cli | 76 | 0 | 163.0 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 29.3 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 14.4 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.2 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 34.2 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 4.8 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 45.6 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 17.4 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 32.7 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 71.4 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 18.9 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 6.4 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 10.0 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 6.1 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 37.9 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 30.7 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 23.2 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 73.9 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 16.8 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 7.4 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 3.8 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.4 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 1.9 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.1 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 22.3 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 11.1 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 17.4 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 22.5 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.4 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 32.5 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 45.9 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 59.6 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 18.2 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 11.2 |
| ✅ | `offline-ui-aws-sns` | offline | ui | 36 | 0 | 54.6 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 11.5 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 22.9 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 22.4 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 9.8 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 10.2 |

<details><summary>❌ <code>offline-sdk-java-aws-cloudwatch</code> log</summary>

```
ull (Service: CloudWatch, Status Code: 500, Request ID: null)
[PASS] PutMetricData into an AWS/ namespace is rejected
[PASS] ListMetrics returns the two metrics
[PASS] ListMetrics filters by dimension
[FAIL] GetMetricStatistics aggregates (Sum 190, SampleCount 5, Min 10, Max 120) :: returned false
[PASS] GetMetricStatistics without Statistics → InvalidParameterCombination
[FAIL] GetMetricData with a metric-math expression :: returned false
[FAIL] PutMetricAlarm :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[PASS] DescribeAlarms round-trips the alarm
[FAIL] a breaching datapoint moves the alarm to ALARM :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[PASS] DescribeAlarms StateValue filter
[PASS] DescribeAlarms rejects AlarmNames + AlarmNamePrefix
[FAIL] SetAlarmState OK with a reason :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[PASS] SetAlarmState on a missing alarm → ResourceNotFound
[PASS] DescribeAlarmHistory has state-update items
[FAIL] PutCompositeAlarm evaluates its rule :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[PASS] DeleteAlarms protects an alarm used by a composite
[FAIL] Disable/EnableAlarmActions :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[FAIL] TagResource / ListTagsForResource / UntagResource :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[FAIL] PutDashboard / GetDashboard / ListDashboards / DeleteDashboards :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[FAIL] GetDashboard on a missing dashboard → ResourceNotFound :: returned false
[PASS] PutDashboard with an invalid body → InvalidParameterInput
[FAIL] PutAnomalyDetector / DescribeAnomalyDetectors / DeleteAnomalyDetector :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[FAIL] PutInsightRule / DescribeInsightRules / DeleteInsightRules :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[FAIL] PutMetricStream / ListMetricStreams / Start / Stop / Delete :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)
[FAIL] DeleteAlarms removes composite + metric alarm :: software.amazon.awssdk.services.cloudwatch.model.CloudWatchException: null (Service: CloudWatch, Status Code: 500, Request ID: null)

11 passed, 15 failed
```

</details>

<details><summary>❌ <code>offline-sdk-go-aws-cloudwatch</code> log</summary>

```
[PASS] GetDashboard returns the body and ARN
[PASS] ListDashboards by prefix
[FAIL] DeleteDashboards :: ResourceNotFound
[PASS] GetDashboard after delete → ResourceNotFound
[FAIL] PutAnomalyDetector + DescribeAnomalyDetectors :: operation error CloudWatch: PutAnomalyDetector, exceeded maximum number of attempts, 3, https response error StatusCode: 500, RequestID: , api error UnknownError: UnknownError <nil>
[FAIL] DeleteAnomalyDetector :: ResourceNotFoundException
[FAIL] PutInsightRule + DescribeInsightRules :: operation error CloudWatch: PutInsightRule, exceeded maximum number of attempts, 3, https response error StatusCode: 500, RequestID: , api error UnknownError: UnknownError <nil>
[FAIL] DeleteInsightRules reports the missing rule as a failure :: operation error CloudWatch: DeleteInsightRules, exceeded maximum number of attempts, 3, https response error StatusCode: 500, RequestID: , api error UnknownError: UnknownError
[FAIL] PutMetricStream returns the stream ARN :: operation error CloudWatch: PutMetricStream, exceeded maximum number of attempts, 3, https response error StatusCode: 500, RequestID: , api error UnknownError: UnknownError
[FAIL] StopMetricStreams → GetMetricStream state stopped :: operation error CloudWatch: StopMetricStreams, exceeded maximum number of attempts, 3, https response error StatusCode: 500, RequestID: , api error UnknownError: UnknownError <nil>
[FAIL] DeleteMetricStream then Get → ResourceNotFoundException :: ResourceNotFoundException
[PASS] DeleteAlarms refuses an alarm a composite still references (ResourceConflict)
[FAIL] DeleteAlarms removes both :: operation error CloudWatch: DeleteAlarms, exceeded maximum number of attempts, 3, https response error StatusCode: 500, RequestID: , api error UnknownError: UnknownError 0

16 passed, 21 failed
go: downloading github.com/aws/aws-sdk-go-v2 v1.36.3
go: downloading github.com/aws/aws-sdk-go-v2/config v1.29.9
go: downloading github.com/aws/aws-sdk-go-v2/credentials v1.17.62
go: downloading github.com/aws/aws-sdk-go-v2/service/cloudwatch v1.44.1
go: downloading github.com/aws/smithy-go v1.22.2
go: downloading github.com/aws/aws-sdk-go-v2/feature/ec2/imds v1.16.30
go: downloading github.com/aws/aws-sdk-go-v2/internal/ini v1.8.3
go: downloading github.com/aws/aws-sdk-go-v2/service/sso v1.25.1
go: downloading github.com/aws/aws-sdk-go-v2/service/ssooidc v1.29.1
go: downloading github.com/aws/aws-sdk-go-v2/service/sts v1.33.17
go: downloading github.com/aws/aws-sdk-go-v2/internal/configsources v1.3.34
go: downloading github.com/aws/aws-sdk-go-v2/internal/endpoints/v2 v2.6.34
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/presigned-url v1.12.15
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/accept-encoding v1.12.3
exit status 1
```

</details>

<details><summary>❌ <code>offline-cli-aws-cloudwatch</code> log</summary>

```
[PASS] describe-alarms --state-value OK
[PASS] describe-alarm-history
[PASS] describe-alarms-for-metric
[FAIL] disable-alarm-actions :: 
aws: [ERROR]: An error occurred (500) when calling the DisableAlarmActions operation (reached max retries: 2): Internal Server Error
[PASS] actions are disabled
[FAIL] enable-alarm-actions :: 
aws: [ERROR]: An error occurred (500) when calling the EnableAlarmActions operation (reached max retries: 2): Internal Server Error
[PASS] list-tags-for-resource
[FAIL] tag-resource :: 
aws: [ERROR]: An error occurred (500) when calling the TagResource operation (reached max retries: 2): Internal Server Error
[FAIL] untag-resource :: 
aws: [ERROR]: An error occurred (500) when calling the UntagResource operation (reached max retries: 2): Internal Server Error
[FAIL] put-composite-alarm :: 
aws: [ERROR]: An error occurred (500) when calling the PutCompositeAlarm operation (reached max retries: 2): Internal Server Error
[PASS] composite alarm follows its rule
[FAIL] put-dashboard :: 
aws: [ERROR]: An error occurred (500) when calling the PutDashboard operation (reached max retries: 2): Internal Server Error
[PASS] get-dashboard
[PASS] list-dashboards
[FAIL] delete-dashboards :: 
aws: [ERROR]: An error occurred (ResourceNotFound) when calling the DeleteDashboards operation: Dashboards ['cli-dash-43808'] do not exist
[PASS] get-dashboard after delete → ResourceNotFound
[PASS] delete-alarms keeps an alarm a composite uses
[FAIL] delete-alarms :: 
aws: [ERROR]: An error occurred (500) when calling the DeleteAlarms operation (reached max retries: 2): Internal Server Error
[PASS] alarm is gone
[PASS] put-metric-alarm without a comparison operator → MissingParameter

17 passed, 14 failed
```

</details>

<details><summary>❌ <code>offline-ui-aws-cloudwatch</code> log</summary>

```
[PASS] CloudWatch is on the AWS console rail
[PASS] opening CloudWatch causes no API 5xx
[PASS] create form shows the alarm name + metric fields
[FAIL] create with the default values returns 2xx :: HTTP 500
[FAIL] the new alarm appears in the list :: rows with my-alarm: 0
[FAIL] every grid column of the new row is filled :: blank: []
[FAIL] alarm state is INSUFFICIENT_DATA until data arrives
[FAIL] console flow :: locator.click: Timeout 5000ms exceeded.
```

</details>

**UI findings: 6**

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

<details><summary><b>API Gateway V2</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Routes | tab Routes: column "Authorization" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>DynamoDB</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>API Gateway V2</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Routes | tab Routes: column "Authorization" shows "-"/blank in 1 row(s) |

</details>

<details><summary><b>CloudWatch</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_5XX` |  | during create: /api/aws/cloudwatch/alarms → 500 Internal Server Error |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-gcp-metrics-counts` | nano | ui | 0 | 1 | 2.4 |
| ❌ | `offline-cli-gcp-container` | offline | cli | 8 | 6 | 99.1 |
| ❌ | `offline-sdk-go-gcp-container` | offline | sdk-go | 14 | 1 | 1.8 |
| ❌ | `offline-sdk-java-gcp-container` | offline | sdk-java | 13 | 1 | 3.1 |
| ❌ | `offline-ui-gcp-artifactregistry` | offline | ui | 1 | 6 | 23.0 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 2.3 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 15 | 0 | 17.9 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 25.0 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 21.8 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 66.1 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 2.4 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 19.1 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 23.4 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 4.9 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 2.3 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 22.4 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 2.4 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.5 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.7 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.3 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 34.6 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.2 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.1 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 0.5 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.1 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 0.1 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 0.5 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 11.7 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 6.5 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 6.6 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 1.4 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 6.3 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 7.0 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 18.2 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 12.9 |
| ✅ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 21 | 0 | 11.2 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 14.6 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 1.7 |
| ✅ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 34 | 0 | 1.1 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 1.5 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 7.3 |
| ✅ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 13 | 0 | 3.9 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 3.5 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 3.6 |
| ✅ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 24 | 0 | 3.1 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 3.4 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.6 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 24 | 0 | 23.8 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 20.7 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 65.8 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 0.6 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 19.9 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.3 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.0 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.5 |
| ✅ | `offline-ui-gcp-redis` | offline | ui | 22 | 0 | 21.3 |

<details><summary>❌ <code>nano-ui-gcp-metrics-counts</code> log</summary>

```
[FAIL] run Error: page.evaluate: ReferenceError: _recordFieldCount is not defined
```

</details>

<details><summary>❌ <code>offline-sdk-java-gcp-container</code> log</summary>

```
== google-cloud-container (Java) against http://localhost:9000 project=java-gke-proj ==
[PASS] CreateCluster -> CREATE_CLUSTER operation, DONE
[PASS] CreateCluster duplicate -> ALREADY_EXISTS
[PASS] CreateCluster bad name -> INVALID_ARGUMENT
[PASS] GetCluster (RUNNING, endpoint, version, pool)
[PASS] GetCluster missing -> NOT_FOUND
[PASS] ListClusters contains the cluster
[PASS] CreateNodePool + GetNodePool
[PASS] SetNodePoolSize persisted
[PASS] ListNodePools (2 pools)
[PASS] SetLabels persisted
[PASS] UpdateCluster (upgrade master)
[FAIL] ListOperations + GetOperation :: com.google.api.gax.rpc.NotFoundException: Not Found
[PASS] GetServerConfig
[PASS] DeleteNodePool + DeleteCluster
RESULT pass=13 fail=1
```

</details>

<details><summary>❌ <code>offline-sdk-go-gcp-container</code> log</summary>

```
== cloud.google.com/go/container (Go) against http://localhost:9000 project=go-gke-proj ==
[PASS] CreateCluster -> CREATE_CLUSTER operation, DONE
[PASS] CreateCluster duplicate -> 409 ALREADY_EXISTS
[PASS] CreateCluster bad name -> 400 INVALID_ARGUMENT
[PASS] GetCluster (RUNNING, endpoint, channel, machine type)
[PASS] GetCluster missing -> 404 NOT_FOUND
[PASS] ListClusters contains the cluster
[PASS] CreateNodePool + GetNodePool (autoscaling)
[PASS] SetNodePoolSize persisted
[PASS] ListNodePools (2 pools)
[PASS] SetLabels persisted
[PASS] SetLabels stale fingerprint -> 409
[PASS] UpdateCluster (upgrade master)
[FAIL] ListOperations + GetOperation :: <nil>
[PASS] GetServerConfig
[PASS] DeleteNodePool + DeleteCluster
RESULT pass=14 fail=1
go: downloading cloud.google.com/go/container v1.39.0
exit status 1
```

</details>

<details><summary>❌ <code>offline-cli-gcp-container</code> log</summary>

```
== gcloud container against http://localhost:9000 project=cli-gke-proj ==
[FAIL] gcloud container clusters create :: Note: Your Pod address range (`--cluster-ipv4-cidr`) can accommodate at most 1008 node(s).
Creating cluster cli-gke-1793293361 in us-central1...
...........................................................................failed.
ERROR: (gcloud.container.clusters.create) ResponseError: code=404, message=Operation "projects/cli-gke-proj/locations/us-central1/operations/operation-16-f233789d" not found.
[PASS] describe (RUNNING, default-pool, machineType)
[PASS] clusters list contains the cluster
[FAIL] gcloud container node-pools create :: Creating node pool pool-2...
...........................................................................failed.
ERROR: (gcloud.container.node-pools.create) ResponseError: code=404, message=Operation "projects/cli-gke-proj/locations/us-central1/operations/operation-17-26d0e8da" not found.
[PASS] node-pools list shows both pools
[FAIL] gcloud container clusters resize :: Resizing cli-gke-1793293361...
...........................................................................failed.
ERROR: (gcloud.container.clusters.resize) ResponseError: code=404, message=Operation "projects/cli-gke-proj/locations/us-central1/operations/operation-18-82e3ccde" not found.
[PASS] resize persisted (3 nodes)
[FAIL] gcloud container clusters update --update-labels :: Updating cli-gke-1793293361...
...........................................................................failed.
ERROR: (gcloud.container.clusters.update) ResponseError: code=404, message=Operation "projects/cli-gke-proj/locations/us-central1/operations/operation-19-db82f3c7" not found.
[PASS] labels persisted
[PASS] gcloud container operations list
[PASS] gcloud container get-server-config
[FAIL] gcloud container node-pools delete :: Deleting node pool pool-2...
...........................................................................failed.
ERROR: (gcloud.container.node-pools.delete) ResponseError: code=404, message=Operation "projects/cli-gke-proj/locations/us-central1/operations/operation-20-e958f8af" not found.
[FAIL] gcloud container clusters delete :: Deleting cluster cli-gke-1793293361...
...........................................................................failed.
ERROR: (gcloud.container.clusters.delete) ResponseError: code=404, message=Operation "projects/cli-gke-proj/locations/us-central1/operations/operation-21-854a978f" not found.
[PASS] deleted cluster is gone (NOT_FOUND)
RESULT pass=8 fail=6
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

**UI findings: 0**

No open UI findings.

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 20.4 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 22.1 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 22.8 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 22.7 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 10.0 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 25.9 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 17.2 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.6 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 2.9 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 11.7 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 26.8 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 10.0 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 9.5 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 26.6 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 2.9 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.2 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 7.2 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 6.7 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 16.9 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 46.2 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 7.4 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.5 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.4 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 6.1 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 7.5 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 13.2 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.4 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 6.9 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.8 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.7 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 23.5 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 3.8 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 2.8 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 3.0 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.3 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.6 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 24.2 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 28.1 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.2 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 6.9 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.2 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.3 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.4 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.0 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.0 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.9 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 23.0 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.8 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.5 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.9 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.9 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 28.1 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.9 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 10.4 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.6 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.9 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 49.7 |

**UI findings: 0**

No open UI findings.

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 60 | 3 | 1204.0 |
| ❌ | `offline-console-actions` | offline | api | 367 | 2 | 15.3 |
| ❌ | `offline-ui-crawl` | offline | ui | 55 | 3 | 1132.3 |
| ✅ | `nano-cores` | nano | core | 344 | 0 | 4.4 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 5.4 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 24.2 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 24.2 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 20 services crawled, 3 with findings
UI crawl offline: 17/20 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"static":92,"live":140,"partial":4,"unimplemented":1}
[offline/azure] 20 services crawled, 0 with findings
UI crawl offline: 20/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":183,"static":50}
[offline/gcp] 18 services crawled, 0 with findings
UI crawl offline: 18/18 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":111,"static":105}
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
........................................................................ [ 37%]
........................................................................ [ 56%]
......................................................................s. [ 75%]
..s..................................................................... [ 94%]
.....................                                                    [100%]
=================================== FAILURES ===================================
E   AssertionError: AWS cloudwatch.create POST /api/aws/cloudwatch/alarms → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
    assert False
/home/runner/work/appliance/appliance/tests/conformance/console_actions/test_aws_console.py:364: AssertionError: AWS cloudwatch.create POST /api/aws/cloudwatch/alarms → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
E   http.client.RemoteDisconnected: Remote end closed connection without response

During handling of the above exception, another exception occurred:
E   urllib3.exceptions.ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))

During handling of the above exception, another exception occurred:
E   requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))

During handling of the above exception, another exception occurred:
E   Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
/home/runner/work/appliance/appliance/tests/conformance/console_actions/test_aws_console.py:262: Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
========================= console conformance summary ==========================
  ⚠ aws    171/173  (98.8%)
  ✓ azure  76/76  (100.0%)
  ✓ gcp    132/132  (100.0%)
  Full report → tests/conformance/console_actions/REPORT.md
=========================== short test summary info ============================
FAILED tests/conformance/console_actions/test_aws_console.py::test_aws_action[aws.cloudwatch.create] - AssertionError: AWS cloudwatch.create POST /api/aws/cloudwatch/alarms → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_aws_console.py::test_aws_action[aws.cloudwatch.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
2 failed, 367 passed, 12 skipped in 14.99s
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 20 services crawled, 3 with findings
UI crawl nano: 17/20 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":187,"static":45,"partial":5}
[nano/azure] 25 services crawled, 0 with findings
UI crawl nano: 25/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":198,"static":50}
[nano/gcp] 18 services crawled, 0 with findings
UI crawl nano: 18/18 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":129,"static":87}
```

</details>

## New features since the last run

| Target | Cloud | Service | Kind | Feature | SDK test |
|---|---|---|---|---|---|
| offline | AWS | Amazon SNS | service | Amazon SNS | — |
| offline | AWS | Amazon SNS | tab | Overview | — |
| offline | AWS | Amazon SNS | tab | Activity | — |
| offline | AWS | Amazon SNS | tab | Tags | — |
| offline | AWS | Amazon SNS | tab | Subscriptions | — |
| offline | AWS | Amazon SNS | tab | Publish message | — |
| offline | AWS | Amazon SNS | tab | Access policy | — |
| offline | AWS | Amazon SNS | tab | Properties | — |
| offline | AWS | Amazon SNS | create_field | Topic name | — |
| offline | AWS | Amazon SNS | create_field | Type | — |
| offline | AWS | Amazon SNS | create_field | Display name | — |
| offline | AWS | Amazon SNS | column | Name | — |
| offline | AWS | Amazon SNS | column | Type | — |
| offline | AWS | Amazon SNS | column | ARN | — |
| offline | AWS | Amazon SNS | column | Subscriptions confirmed | — |
| offline | AWS | Amazon SNS | column | Subscriptions pending | — |
| offline | AWS | Amazon SNS | column | Display name | — |
| offline | AWS | Amazon SNS | column | Encryption | — |
| offline | AWS | Amazon SNS | column | Created | — |
| offline | AWS | Amazon SNS | action | topics | — |
| offline | AWS | Amazon SNS | action | subscriptions | — |
| offline | AWS | Amazon SNS | action | platform-applications | — |
| offline | AWS | Amazon SNS | action | deliveries | — |
| offline | AWS | Amazon SNS | action | sms-sandbox | — |
| offline | AWS | Amazon SNS | action | publish | — |
| offline | AWS | Amazon SNS | action | subscribe | — |
| offline | AWS | Amazon SNS | action | delete | — |
| offline | AWS | API Gateway V2 | service | API Gateway V2 | — |
| offline | AWS | API Gateway V2 | tab | Overview | — |
| offline | AWS | API Gateway V2 | tab | Activity | — |
| offline | AWS | API Gateway V2 | tab | Tags | — |
| offline | AWS | API Gateway V2 | tab | Routes | — |
| offline | AWS | API Gateway V2 | tab | Integrations | — |
| offline | AWS | API Gateway V2 | tab | Authorization | — |
| offline | AWS | API Gateway V2 | tab | Stages | — |
| offline | AWS | API Gateway V2 | tab | Deployments | — |
| offline | AWS | API Gateway V2 | tab | Properties | — |
| offline | AWS | API Gateway V2 | tab | Monitoring | — |
| offline | AWS | API Gateway V2 | create_field | API name | — |
| offline | AWS | API Gateway V2 | create_field | Protocol (HTTP or WEBSOCKET) | — |
| offline | AWS | API Gateway V2 | create_field | Quick-create target (URL or Lambda ARN) | — |
| offline | AWS | API Gateway V2 | create_field | Description | — |
| offline | AWS | API Gateway V2 | column | API ID | — |
| offline | AWS | API Gateway V2 | column | Name | — |
| offline | AWS | API Gateway V2 | column | Protocol | — |
| offline | AWS | API Gateway V2 | column | Invoke URL | — |
| offline | AWS | API Gateway V2 | column | Routes | — |
| offline | AWS | API Gateway V2 | column | Created | — |
| offline | AWS | API Gateway V2 | action | routes | — |
| offline | AWS | API Gateway V2 | action | integrations | — |
| offline | AWS | API Gateway V2 | action | stages | — |
| offline | AWS | API Gateway V2 | action | deployments | — |
| offline | AWS | API Gateway V2 | action | authorizers | — |
| offline | AWS | API Gateway V2 | action | models | — |
| offline | AWS | API Gateway V2 | action | delete | — |
| offline | AWS | Secrets Manager | column | Created | — |
| offline | AWS | CloudWatch | service | CloudWatch | — |
| offline | AWS | CloudWatch | tab | Overview | — |
| offline | AWS | CloudWatch | tab | Activity | — |
| offline | AWS | CloudWatch | tab | Tags | — |
| offline | AWS | CloudWatch | tab | Details | — |
| offline | AWS | CloudWatch | tab | History | — |
| offline | AWS | CloudWatch | tab | Actions | — |
| offline | AWS | CloudWatch | tab | Properties | — |
| offline | AWS | CloudWatch | tab | Permissions | — |
| offline | AWS | CloudWatch | create_field | Alarm name | — |
| offline | AWS | CloudWatch | create_field | Namespace | — |
| offline | AWS | CloudWatch | create_field | Metric name | — |
| offline | AWS | CloudWatch | create_field | Dimensions (Name=Value, ...) | — |
| offline | AWS | CloudWatch | create_field | Statistic | — |
| offline | AWS | CloudWatch | create_field | Period (seconds) | — |
| offline | AWS | CloudWatch | create_field | Threshold | — |
| offline | AWS | CloudWatch | create_field | Comparison operator | — |
| offline | AWS | CloudWatch | create_field | Evaluation periods | — |
| offline | AWS | CloudWatch | create_field | Alarm action (SNS topic ARN) | — |
| offline | AWS | CloudWatch | column | Alarm name | — |
| offline | AWS | CloudWatch | column | State | — |
| offline | AWS | CloudWatch | column | Metric | — |
| offline | AWS | CloudWatch | column | Conditions | — |
| offline | AWS | CloudWatch | column | Period | — |
| offline | AWS | CloudWatch | column | Actions | — |
| offline | AWS | CloudWatch | column | Last state update | — |
| offline | AWS | CloudWatch | action | alarms | — |
| offline | AWS | CloudWatch | action | delete | — |
| offline | AWS | Kinesis | service | Kinesis | — |
| offline | AWS | Kinesis | tab | Overview | — |
| offline | AWS | Kinesis | tab | Activity | — |
| offline | AWS | Kinesis | tab | Tags | — |
| offline | AWS | Kinesis | tab | Configuration | — |
| offline | AWS | Kinesis | tab | Shards and consumers | — |
| offline | AWS | Kinesis | create_field | Data stream name | — |
| offline | AWS | Kinesis | create_field | Capacity mode | — |
| offline | AWS | Kinesis | create_field | Provisioned shards | — |
| offline | AWS | Kinesis | create_field | Data retention (hours) | — |
| offline | AWS | Kinesis | column | Name | — |
| offline | AWS | Kinesis | column | Status | — |
| offline | AWS | Kinesis | column | Capacity mode | — |
| offline | AWS | Kinesis | column | Open shards | — |
| offline | AWS | Kinesis | column | Data retention | — |
| offline | AWS | Kinesis | column | Encryption | — |

## Upstream changes (AWS / GCP / Azure backlog)

52 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
| #235 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-29 |
| #234 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-29 |
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
| #179 | Azure |  | [azure] Console Metrics/Monitoring: real charts for every service from measured requests | 2026-10-29 |
| #178 | GCP |  | [gcp] Console Metrics tabs: real charts for every service (replace seeded fake sparklines) | 2026-10-29 |
| #171 | AWS |  | [aws] EventBridge: deliver to every target type through NATS (today only SQS targets) | 2026-10-28 |
| #169 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |
| #170 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-28 |
| #168 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-28 |
| #167 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-28 |
| #165 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |
| #166 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-28 |
| #163 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-28 |
| #164 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-28 |
| #160 | GCP | lifecycle | Google Kubernetes Engine: Change (October 27, 2026) | 2026-10-28 |
| #159 | GCP | lifecycle | Google Kubernetes Engine: No channel (deprecated) (October 27, 2026) | 2026-10-28 |
| #158 | GCP | lifecycle | Google Kubernetes Engine: Regular channel (October 27, 2026) | 2026-10-28 |
| #156 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-27 |
| #157 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-27 |
| #155 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.startReplay changed | 2026-10-27 |
| #154 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.start changed | 2026-10-27 |
| #153 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stopReplay changed | 2026-10-27 |

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

## SDK operations without a test (208 of 1216)

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
<details><summary>AWS · <code>stepfunctions_core</code> (nano) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (nano) — 7</summary>

CreateRepo, DeleteRepo, GetRepo, ListRepos, PatchRepo, TagTarget, TagView

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
<details><summary>AWS · <code>stepfunctions_core</code> (offline) — 35</summary>

DeleteStateMachineVersion, DescribeActivity, DescribeMapRun, DescribeStateMachineAlias, DescribeStateMachineForExecution, InvokeLambda, IsNumeric, IsPresent, IsString, IsTimestamp, ListMapRuns, ListStateMachineAliases, NumericEquals, NumericGreaterThanEquals, NumericLessThan, NumericLessThanEquals, RedriveExecution, RunMachine, RunState, SendTaskFailure, SendTaskHeartbeat, StringEquals, StringGreaterThan, StringGreaterThanEquals, StringLessThan, StringLessThanEquals, StringMatches, TagTarget, TimestampEquals, TimestampGreaterThan, TimestampGreaterThanEquals, TimestampLessThan, TimestampLessThanEquals, UpdateMapRun, UpdateStateMachineAlias

</details>
<details><summary>GCP · <code>gcp_artifactregistry_core</code> (offline) — 7</summary>

CreateRepo, DeleteRepo, GetRepo, ListRepos, PatchRepo, TagTarget, TagView

</details>
<details><summary>GCP · <code>gcp_monitoring_core</code> (offline) — 16</summary>

CreateChannel, CreateDescriptor, CreateUptime, DeleteChannel, DeleteDescriptor, DeleteGroup, GetDescriptor, GetUptime, ListChannels, ListDescriptors, ListGroups, ListTimeSeries, PatchChannel, PatchPolicy, PatchUptime, UpdateGroup

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
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

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
