# Vyomi Conformance — hourly report

Run **2026-10-30T15:09:18+00:00** · commit `f849a88ed083` · Nano (in-browser) + offline appliance · updated every hour by [the conformance agent](https://github.com/vyomi-cloud/appliance/blob/main/tests/conformance/hourly/AGENT.md).

| Suites green | Checks passing | Checks failing | Nano UI clean | Offline UI clean | Open UI findings | API routes with tests |
|---|---|---|---|---|---|---|
| 229/237 | 4873 | 106 | 42/63 | 38/58 | 137 | 43.3% (149/344) |

## By cloud

| Cloud | Suites green | Checks ✓ | Checks ✗ | Nano UI clean | Offline UI clean | Open findings |
|---|---|---|---|---|---|---|
| [AWS](#aws) | 97/101 | 1819 | 57 | 4/20 | 4/20 | 112 |
| [GCP](#gcp) | 64/65 | 935 | 6 | 13/18 | 15/18 | 24 |
| [Azure](#azure) | 64/64 | 1300 | 0 | 25/25 | 19/20 | 1 |

<a id="aws"></a>
## AWS

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-cli-aws-cloudwatch` | offline | cli | 15 | 16 | 40.1 |
| ❌ | `offline-sdk-go-aws-cloudwatch` | offline | sdk-go | 16 | 21 | 73.6 |
| ❌ | `offline-sdk-java-aws-cloudwatch` | offline | sdk-java | 11 | 15 | 10.0 |
| ❌ | `offline-ui-aws-cloudwatch` | offline | ui | 3 | 5 | 12.1 |
| ✅ | `nano-aws-ec2-launch` | nano | core | 13 | 0 | 0.1 |
| ✅ | `nano-aws-iam-detail` | nano | core | 8 | 0 | 0.2 |
| ✅ | `nano-ui-aws-api` | nano | ui | 6 | 0 | 3.0 |
| ✅ | `nano-ui-aws-apigatewayv2` | nano | ui | 21 | 0 | 22.0 |
| ✅ | `nano-ui-aws-apigw-row` | nano | ui | 6 | 0 | 15.6 |
| ✅ | `nano-ui-aws-cloudwatch` | nano | ui | 21 | 0 | 15.5 |
| ✅ | `nano-ui-aws-compute-reload` | nano | ui | 4 | 0 | 7.3 |
| ✅ | `nano-ui-aws-compute-savings` | nano | ui | 6 | 0 | 9.1 |
| ✅ | `nano-ui-aws-detail-tabs` | nano | ui | 6 | 0 | 21.3 |
| ✅ | `nano-ui-aws-ec2-detail-tabs` | nano | ui | 5 | 0 | 11.6 |
| ✅ | `nano-ui-aws-ec2-row` | nano | ui | 6 | 0 | 15.7 |
| ✅ | `nano-ui-aws-elbv2` | nano | ui | 24 | 0 | 23.8 |
| ✅ | `nano-ui-aws-eventbridge-row` | nano | ui | 4 | 0 | 15.6 |
| ✅ | `nano-ui-aws-iam-detail` | nano | ui | 4 | 0 | 3.3 |
| ✅ | `nano-ui-aws-kinesis` | nano | ui | 19 | 0 | 39.8 |
| ✅ | `nano-ui-aws-lambda-row` | nano | ui | 4 | 0 | 15.6 |
| ✅ | `nano-ui-aws-logs` | nano | ui | 33 | 0 | 49.5 |
| ✅ | `nano-ui-aws-metrics` | nano | ui | 10 | 0 | 12.1 |
| ✅ | `nano-ui-aws-rds-connectivity-tabs` | nano | ui | 3 | 0 | 10.1 |
| ✅ | `nano-ui-aws-secrets-created` | nano | ui | 3 | 0 | 3.0 |
| ✅ | `nano-ui-aws-settings-tabs` | nano | ui | 10 | 0 | 10.9 |
| ✅ | `nano-ui-aws-sns` | nano | ui | 36 | 0 | 30.5 |
| ✅ | `nano-ui-aws-sqs-dlq-tab` | nano | ui | 2 | 0 | 8.6 |
| ✅ | `nano-ui-aws-ssm` | nano | ui | 19 | 0 | 20.9 |
| ✅ | `nano-ui-aws-stepfunctions` | nano | ui | 22 | 0 | 23.2 |
| ✅ | `nano-ui-aws-tabs` | nano | ui | 16 | 0 | 14.6 |
| ✅ | `nano-ui-aws-vpc-apigw-lists` | nano | ui | 5 | 0 | 3.1 |
| ✅ | `nano-ui-aws-vpc-details-tab` | nano | ui | 2 | 0 | 10.0 |
| ✅ | `nano-ui-aws-vpc-row` | nano | ui | 7 | 0 | 15.7 |
| ✅ | `nano-ui-aws-vpc-sg-iam-cells` | nano | ui | 3 | 0 | 8.6 |
| ✅ | `offline-api-aws-console-savings` | offline | api | 12 | 0 | 5.9 |
| ✅ | `offline-api-aws-eventbridge-rule-defaults` | offline | api | 14 | 0 | 2.1 |
| ✅ | `offline-api-aws-provider-connect` | offline | api | 11 | 0 | 0.2 |
| ✅ | `offline-api-aws-sdk-info-extras-config` | offline | api | 11 | 0 | 1.3 |
| ✅ | `offline-api-aws-sdk-info-routes` | offline | api | 8 | 0 | 0.2 |
| ✅ | `offline-api-aws-wire-routes` | offline | api | 7 | 0 | 2.0 |
| ✅ | `offline-api-cost-savings-extras` | offline | api | 12 | 0 | 7.4 |
| ✅ | `offline-api-ec2-capacity-manager-scores` | offline | api | 6 | 0 | 0.2 |
| ✅ | `offline-api-ec2-capacity-reservation-fleet` | offline | api | 9 | 0 | 0.2 |
| ✅ | `offline-api-ec2-default-public-ip` | offline | api | 3 | 0 | 0.4 |
| ✅ | `offline-api-ec2-get-image-findings` | offline | api | 4 | 0 | 0.2 |
| ✅ | `offline-api-ec2-instance-detail` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-api-s3-bucket-creation-date` | offline | api | 3 | 0 | 0.3 |
| ✅ | `offline-cli-aws` | offline | cli | 15 | 0 | 22.1 |
| ✅ | `offline-cli-aws-apigatewayv2` | offline | cli | 40 | 0 | 36.8 |
| ✅ | `offline-cli-aws-elbv2` | offline | cli | 27 | 0 | 45.0 |
| ✅ | `offline-cli-aws-kinesis` | offline | cli | 20 | 0 | 25.0 |
| ✅ | `offline-cli-aws-logs` | offline | cli | 19 | 0 | 31.8 |
| ✅ | `offline-cli-aws-sns` | offline | cli | 76 | 0 | 153.1 |
| ✅ | `offline-cli-aws-ssm` | offline | cli | 34 | 0 | 36.8 |
| ✅ | `offline-cli-aws-stepfunctions` | offline | cli | 26 | 0 | 22.1 |
| ✅ | `offline-request-metrics` | offline | core | 4 | 0 | 0.3 |
| ✅ | `offline-sdk-go-aws` | offline | sdk-go | 14 | 0 | 46.9 |
| ✅ | `offline-sdk-go-aws-apigatewayv2` | offline | sdk-go | 39 | 0 | 8.7 |
| ✅ | `offline-sdk-go-aws-elbv2` | offline | sdk-go | 60 | 0 | 44.6 |
| ✅ | `offline-sdk-go-aws-kinesis` | offline | sdk-go | 26 | 0 | 16.6 |
| ✅ | `offline-sdk-go-aws-logs` | offline | sdk-go | 29 | 0 | 33.6 |
| ✅ | `offline-sdk-go-aws-sns` | offline | sdk-go | 71 | 0 | 64.3 |
| ✅ | `offline-sdk-go-aws-ssm` | offline | sdk-go | 38 | 0 | 19.8 |
| ✅ | `offline-sdk-go-aws-stepfunctions` | offline | sdk-go | 39 | 0 | 8.7 |
| ✅ | `offline-sdk-java-aws` | offline | sdk-java | 29 | 0 | 14.3 |
| ✅ | `offline-sdk-java-aws-apigatewayv2` | offline | sdk-java | 46 | 0 | 10.8 |
| ✅ | `offline-sdk-java-aws-elbv2` | offline | sdk-java | 41 | 0 | 35.2 |
| ✅ | `offline-sdk-java-aws-kinesis` | offline | sdk-java | 34 | 0 | 31.0 |
| ✅ | `offline-sdk-java-aws-logs` | offline | sdk-java | 16 | 0 | 24.1 |
| ✅ | `offline-sdk-java-aws-sns` | offline | sdk-java | 73 | 0 | 67.9 |
| ✅ | `offline-sdk-java-aws-ssm` | offline | sdk-java | 33 | 0 | 18.4 |
| ✅ | `offline-sdk-java-aws-stepfunctions` | offline | sdk-java | 41 | 0 | 11.3 |
| ✅ | `offline-sdk-python-aws` | offline | sdk-python | 88 | 0 | 5.3 |
| ✅ | `offline-sdk-python-aws-kms-kem` | offline | sdk-python | 6 | 0 | 0.6 |
| ✅ | `offline-sdk-python-aws-ops` | offline | sdk-python | 12 | 0 | 2.0 |
| ✅ | `offline-sdk-python-aws-ops2` | offline | sdk-python | 20 | 0 | 1.5 |
| ✅ | `offline-sdk-python-aws-s3-config` | offline | sdk-python | 4 | 0 | 0.9 |
| ✅ | `offline-ui-aws-apigatewayv2` | offline | ui | 21 | 0 | 22.4 |
| ✅ | `offline-ui-aws-apigw-deployments` | offline | ui | 4 | 0 | 14.8 |
| ✅ | `offline-ui-aws-apigw-tabs` | offline | ui | 4 | 0 | 11.2 |
| ✅ | `offline-ui-aws-detail-name` | offline | ui | 4 | 0 | 17.1 |
| ✅ | `offline-ui-aws-detail-tabs` | offline | ui | 6 | 0 | 21.8 |
| ✅ | `offline-ui-aws-dynamodb-settings` | offline | ui | 14 | 0 | 33.5 |
| ✅ | `offline-ui-aws-ec2-detail-tabs` | offline | ui | 5 | 0 | 11.6 |
| ✅ | `offline-ui-aws-ec2-userdata-iam` | offline | ui | 7 | 0 | 19.8 |
| ✅ | `offline-ui-aws-elbv2` | offline | ui | 24 | 0 | 29.4 |
| ✅ | `offline-ui-aws-kinesis` | offline | ui | 19 | 0 | 44.7 |
| ✅ | `offline-ui-aws-kms-tabs` | offline | ui | 12 | 0 | 24.6 |
| ✅ | `offline-ui-aws-logs` | offline | ui | 33 | 0 | 57.4 |
| ✅ | `offline-ui-aws-metrics` | offline | ui | 10 | 0 | 17.5 |
| ✅ | `offline-ui-aws-rds-connectivity-tabs` | offline | ui | 3 | 0 | 9.3 |
| ✅ | `offline-ui-aws-rds-tabs` | offline | ui | 22 | 0 | 31.1 |
| ✅ | `offline-ui-aws-s3-config` | offline | ui | 35 | 0 | 42.6 |
| ✅ | `offline-ui-aws-secretsmanager-tabs` | offline | ui | 10 | 0 | 22.8 |
| ✅ | `offline-ui-aws-sns` | offline | ui | 36 | 0 | 47.4 |
| ✅ | `offline-ui-aws-sqs-dlq-tab` | offline | ui | 2 | 0 | 8.7 |
| ✅ | `offline-ui-aws-sqs-tabs` | offline | ui | 6 | 0 | 19.8 |
| ✅ | `offline-ui-aws-ssm` | offline | ui | 19 | 0 | 21.7 |
| ✅ | `offline-ui-aws-stepfunctions` | offline | ui | 22 | 0 | 22.4 |
| ✅ | `offline-ui-aws-vpc-details-tab` | offline | ui | 2 | 0 | 9.1 |
| ✅ | `offline-ui-aws-vpc-sg-iam-cells` | offline | ui | 3 | 0 | 9.1 |

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
go: downloading github.com/aws/aws-sdk-go-v2/internal/configsources v1.3.34
go: downloading github.com/aws/aws-sdk-go-v2/internal/endpoints/v2 v2.6.34
go: downloading github.com/aws/aws-sdk-go-v2/internal/ini v1.8.3
go: downloading github.com/aws/aws-sdk-go-v2/feature/ec2/imds v1.16.30
go: downloading github.com/aws/aws-sdk-go-v2/service/ssooidc v1.29.1
go: downloading github.com/aws/aws-sdk-go-v2/service/sso v1.25.1
go: downloading github.com/aws/aws-sdk-go-v2/service/sts v1.33.17
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/accept-encoding v1.12.3
go: downloading github.com/aws/aws-sdk-go-v2/service/internal/presigned-url v1.12.15
exit status 1
```

</details>

<details><summary>❌ <code>offline-cli-aws-cloudwatch</code> log</summary>

```
[PASS] describe-alarms --state-value OK
[FAIL] describe-alarm-history :: 1
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
aws: [ERROR]: An error occurred (ResourceNotFound) when calling the DeleteDashboards operation: Dashboards ['cli-dash-48090'] do not exist
[PASS] get-dashboard after delete → ResourceNotFound
[PASS] delete-alarms keeps an alarm a composite uses
[FAIL] delete-alarms :: 
aws: [ERROR]: An error occurred (500) when calling the DeleteAlarms operation (reached max retries: 2): Internal Server Error
[PASS] alarm is gone
[PASS] put-metric-alarm without a comparison operator → MissingParameter

15 passed, 16 failed
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

**UI findings: 112**

<details><summary><b>DynamoDB</b> (offline) — 10 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `STATIC_TAB` | Overview | tab 'Overview' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Query/Scan | tab 'Query/Scan' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Streams and triggers | tab 'Streams and triggers' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Read/write capacity | tab 'Read/write capacity' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Encryption at rest | tab 'Encryption at rest' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Time to live | tab 'Time to live' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Point-in-time recovery | tab 'Point-in-time recovery' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Insights | tab 'Insights' shows no backend data and nothing about this resource |

</details>

<details><summary><b>EC2</b> (offline) — 8 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Details | tab 'Details' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |
| `STATIC_TAB` | Storage | tab 'Storage' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Connect | tab 'Connect' shows no backend data and nothing about this resource |
| `STATIC_TAB` | User data | tab 'User data' shows no backend data and nothing about this resource |
| `STATIC_TAB` | IAM role | tab 'IAM role' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Lambda</b> (offline) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Code | tab 'Code' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Test | tab 'Test' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Environment variables | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Versions | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Aliases | placeholder pane ('This pane mirrors … view') |
| `STATIC_TAB` | Resource-based policy | tab 'Resource-based policy' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Execution role | tab 'Execution role' shows no backend data and nothing about this resource |

</details>

<details><summary><b>EventBridge</b> (offline) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Rule details | tab 'Rule details' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Targets | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Event pattern | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Dead-letter queue | placeholder pane ('This pane mirrors … view') |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | Trace logs | placeholder pane ('This pane mirrors … view') |

</details>

<details><summary><b>KMS</b> (offline) — 7 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | General configuration | tab 'General configuration' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Key rotation | tab 'Key rotation' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Key users | tab 'Key users' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Key administrators | tab 'Key administrators' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Grants | tab 'Grants' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>EC2</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Details | tab 'Details' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `PLACEHOLDER_CELL` | Security | tab Security: column "IAM ROLE" shows "-"/blank in 1 row(s) |
| `PLACEHOLDER_CELL` | Security | tab Security: column "STATE TRANSITION REASON" shows "-"/blank in 1 row(s) |
| `STATIC_TAB` | Storage | tab 'Storage' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Connect | tab 'Connect' shows no backend data and nothing about this resource |

</details>

<details><summary><b>SQS</b> (offline) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Send and receive messages | tab 'Send and receive messages' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Purge messages | tab 'Purge messages' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Configuration | tab 'Configuration' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Dead-letter queue | tab 'Dead-letter queue' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Encryption | tab 'Encryption' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Access policy | tab 'Access policy' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Secrets Manager</b> (offline) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Secret value | tab 'Secret value' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Rotation | tab 'Rotation' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Replication | tab 'Replication' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Resource policy | tab 'Resource policy' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>VPC</b> (offline) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | VPC details | tab 'VPC details' shows no backend data and nothing about this resource |
| `PLACEHOLDER_PANE` | NAT gateways | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Endpoints | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Network ACLs | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Flow logs | placeholder pane ('This pane mirrors … view') |

</details>

<details><summary><b>API Gateway</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` | Stages | tab Stages: column "Description" shows "-"/blank in 1 row(s) |
| `HTTP_501` | Deployments | /api/apigateway/apis/ab0552f0b2/deployments → 501 |
| `STATIC_TAB` | Settings | tab 'Settings' shows no backend data and nothing about this resource |
| `HTTP_501` | Logs/Tracing | /api/apigateway/apis/ab0552f0b2/logs → 501 |

</details>

<details><summary><b>DynamoDB</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_CELL` |  | after create: column "Sort key" shows "-"/blank in 1 row(s) |
| `STATIC_TAB` | Query/Scan | tab 'Query/Scan' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>SQS</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Send and receive messages | tab 'Send and receive messages' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Configuration | tab 'Configuration' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Dead-letter queue | tab 'Dead-letter queue' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Systems Manager</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Value | tab 'Value' shows no backend data and nothing about this resource |
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>RDS</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Endpoints | tab 'Endpoints' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>API Gateway</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Authorizers | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Models | placeholder pane ('This pane mirrors … view') |
| `STATIC_TAB` | Resource policy | tab 'Resource policy' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Systems Manager</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Value | tab 'Value' shows no backend data and nothing about this resource |
| `PLACEHOLDER_CELL` | History | tab History: column "Labels" shows "-"/blank in 1 row(s) |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>CloudWatch</b> (offline) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_5XX` |  | during create: /api/aws/cloudwatch/alarms → 500 Internal Server Error |
| `STATIC_TAB` | Actions | tab 'Actions' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Lambda</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Code | tab 'Code' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Test | tab 'Test' shows no backend data and nothing about this resource |

</details>

<details><summary><b>S3</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Bucket Versioning | tab 'Bucket Versioning' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>RDS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Endpoints | tab 'Endpoints' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Amazon SNS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Subscriptions | tab 'Subscriptions' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Publish message | tab 'Publish message' shows no backend data and nothing about this resource |

</details>

<details><summary><b>EventBridge</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Rule details | tab 'Rule details' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Step Functions</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Definition | tab 'Definition' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Secrets Manager</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Secret value | tab 'Secret value' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Amazon SNS</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Subscriptions | tab 'Subscriptions' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Publish message | tab 'Publish message' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Step Functions</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Definition | tab 'Definition' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>IAM</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `PLACEHOLDER_PANE` | Password policy | placeholder pane ('This pane mirrors … view') |
| `PLACEHOLDER_PANE` | Access Analyzer | placeholder pane ('This pane mirrors … view') |

</details>

<details><summary><b>VPC</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | VPC details | tab 'VPC details' shows no backend data and nothing about this resource |

</details>

<details><summary><b>IAM</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `HTTP_501` | Identity providers | /api/iam/identity-providers → 501 |

</details>

<details><summary><b>KMS</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | General configuration | tab 'General configuration' shows no backend data and nothing about this resource |

</details>

<details><summary><b>CloudWatch</b> (nano) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Actions | tab 'Actions' shows no backend data and nothing about this resource |

</details>

<details><summary><b>S3</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Permissions | tab 'Permissions' shows no backend data and nothing about this resource |

</details>

<a id="gcp"></a>
## GCP

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `offline-ui-gcp-artifactregistry` | offline | ui | 1 | 6 | 23.2 |
| ✅ | `nano-ui-gcp-activity-detail` | nano | ui | 2 | 0 | 3.9 |
| ✅ | `nano-ui-gcp-artifactregistry` | nano | ui | 15 | 0 | 18.1 |
| ✅ | `nano-ui-gcp-cloudscheduler` | nano | ui | 23 | 0 | 27.4 |
| ✅ | `nano-ui-gcp-container` | nano | ui | 21 | 0 | 24.1 |
| ✅ | `nano-ui-gcp-create-defaults` | nano | ui | 36 | 0 | 68.1 |
| ✅ | `nano-ui-gcp-detail-panes` | nano | ui | 4 | 0 | 25.7 |
| ✅ | `nano-ui-gcp-firestore-usage` | nano | ui | 2 | 0 | 4.0 |
| ✅ | `nano-ui-gcp-grid-defaults` | nano | ui | 39 | 0 | 3.9 |
| ✅ | `nano-ui-gcp-iam-detail` | nano | ui | 4 | 0 | 13.6 |
| ✅ | `nano-ui-gcp-iamcredentials` | nano | ui | 21 | 0 | 20.5 |
| ✅ | `nano-ui-gcp-labels-tab` | nano | ui | 18 | 0 | 85.6 |
| ✅ | `nano-ui-gcp-metrics-counts` | nano | ui | 3 | 0 | 4.0 |
| ✅ | `nano-ui-gcp-monitoring` | nano | ui | 23 | 0 | 24.7 |
| ✅ | `nano-ui-gcp-pubsub-grid` | nano | ui | 3 | 0 | 6.5 |
| ✅ | `nano-ui-gcp-pubsub-subscriptions` | nano | ui | 3 | 0 | 3.9 |
| ✅ | `nano-ui-gcp-redis` | nano | ui | 22 | 0 | 23.7 |
| ✅ | `nano-ui-gcp-tabs` | nano | ui | 6 | 0 | 4.0 |
| ✅ | `offline-api-gcp-apigateway-savings` | offline | api | 5 | 0 | 0.8 |
| ✅ | `offline-api-gcp-cloudscheduler-http` | offline | api | 10 | 0 | 0.8 |
| ✅ | `offline-api-gcp-cloudscheduler-pubsub` | offline | api | 7 | 0 | 0.9 |
| ✅ | `offline-api-gcp-cloudscheduler-timer` | offline | api | 9 | 0 | 43.2 |
| ✅ | `offline-api-gcp-console-next` | offline | api | 28 | 0 | 0.4 |
| ✅ | `offline-api-gcp-console-pubsub-lens` | offline | api | 16 | 0 | 0.3 |
| ✅ | `offline-api-gcp-console-savings` | offline | api | 12 | 0 | 1.8 |
| ✅ | `offline-api-gcp-console-vault-lens` | offline | api | 15 | 0 | 0.3 |
| ✅ | `offline-api-gcp-eventarc-trigger-defaults` | offline | api | 6 | 0 | 0.4 |
| ✅ | `offline-api-gcp-grid-columns` | offline | api | 19 | 0 | 0.8 |
| ✅ | `offline-api-gcp-pubsub-savings` | offline | api | 11 | 0 | 1.3 |
| ✅ | `offline-api-gcp-vault-console-secrets` | offline | api | 9 | 0 | 0.7 |
| ✅ | `offline-cli-gcp` | offline | cli | 6 | 0 | 13.6 |
| ✅ | `offline-cli-gcp-artifactregistry` | offline | cli | 11 | 0 | 8.8 |
| ✅ | `offline-cli-gcp-cloudscheduler` | offline | cli | 13 | 0 | 8.8 |
| ✅ | `offline-cli-gcp-container` | offline | cli | 14 | 0 | 12.6 |
| ✅ | `offline-cli-gcp-iamcredentials` | offline | cli | 9 | 0 | 2.3 |
| ✅ | `offline-cli-gcp-monitoring` | offline | cli | 15 | 0 | 7.8 |
| ✅ | `offline-cli-gcp-redis` | offline | cli | 20 | 0 | 10.8 |
| ✅ | `offline-sdk-go-gcp` | offline | sdk-go | 5 | 0 | 26.9 |
| ✅ | `offline-sdk-go-gcp-admin` | offline | sdk-go | 26 | 0 | 17.2 |
| ✅ | `offline-sdk-go-gcp-artifactregistry` | offline | sdk-go | 21 | 0 | 13.4 |
| ✅ | `offline-sdk-go-gcp-cloudscheduler` | offline | sdk-go | 13 | 0 | 17.7 |
| ✅ | `offline-sdk-go-gcp-container` | offline | sdk-go | 15 | 0 | 2.4 |
| ✅ | `offline-sdk-go-gcp-iamcredentials` | offline | sdk-go | 17 | 0 | 7.8 |
| ✅ | `offline-sdk-go-gcp-monitoring` | offline | sdk-go | 34 | 0 | 1.7 |
| ✅ | `offline-sdk-go-gcp-redis` | offline | sdk-go | 16 | 0 | 1.8 |
| ✅ | `offline-sdk-java-gcp` | offline | sdk-java | 6 | 0 | 11.5 |
| ✅ | `offline-sdk-java-gcp-artifactregistry` | offline | sdk-java | 13 | 0 | 5.9 |
| ✅ | `offline-sdk-java-gcp-cloudscheduler` | offline | sdk-java | 12 | 0 | 5.3 |
| ✅ | `offline-sdk-java-gcp-container` | offline | sdk-java | 14 | 0 | 5.2 |
| ✅ | `offline-sdk-java-gcp-iamcredentials` | offline | sdk-java | 11 | 0 | 6.1 |
| ✅ | `offline-sdk-java-gcp-monitoring` | offline | sdk-java | 24 | 0 | 4.9 |
| ✅ | `offline-sdk-java-gcp-redis` | offline | sdk-java | 15 | 0 | 5.3 |
| ✅ | `offline-ui-gcp-activity-detail` | offline | ui | 2 | 0 | 0.9 |
| ✅ | `offline-ui-gcp-cloudscheduler` | offline | ui | 24 | 0 | 24.4 |
| ✅ | `offline-ui-gcp-container` | offline | ui | 21 | 0 | 21.2 |
| ✅ | `offline-ui-gcp-create-defaults` | offline | ui | 36 | 0 | 66.4 |
| ✅ | `offline-ui-gcp-detail-panes` | offline | ui | 4 | 0 | 22.7 |
| ✅ | `offline-ui-gcp-grid-defaults` | offline | ui | 39 | 0 | 1.5 |
| ✅ | `offline-ui-gcp-iam-detail` | offline | ui | 5 | 0 | 9.8 |
| ✅ | `offline-ui-gcp-iamcredentials` | offline | ui | 21 | 0 | 20.2 |
| ✅ | `offline-ui-gcp-labels-tab` | offline | ui | 9 | 0 | 86.1 |
| ✅ | `offline-ui-gcp-monitoring` | offline | ui | 23 | 0 | 22.6 |
| ✅ | `offline-ui-gcp-pubsub-grid` | offline | ui | 3 | 0 | 3.3 |
| ✅ | `offline-ui-gcp-pubsub-subscriptions` | offline | ui | 3 | 0 | 0.9 |
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

**UI findings: 24**

<details><summary><b>VPC Network</b> (nano) — 6 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Subnets | tab 'Subnets' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Firewall rules | tab 'Firewall rules' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Routes | tab 'Routes' shows no backend data and nothing about this resource |
| `STATIC_TAB` | VPC peering | tab 'VPC peering' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Flow logs | tab 'Flow logs' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud Functions</b> (nano) — 5 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Source | tab 'Source' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Trigger | tab 'Trigger' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Variables | tab 'Variables' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Networking | tab 'Networking' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Logs | tab 'Logs' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Secret Manager</b> (nano) — 4 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Secret value | tab 'Secret value' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Rotation | tab 'Rotation' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Replication | tab 'Replication' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Encryption | tab 'Encryption' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud Storage</b> (nano) — 3 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Lifecycle | tab 'Lifecycle' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Encryption | tab 'Encryption' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Retention | tab 'Retention' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud KMS</b> (nano) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Rotation & labels | tab 'Rotation & labels' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Import jobs | tab 'Import jobs' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Secret Manager</b> (offline) — 2 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Secret value | tab 'Secret value' shows no backend data and nothing about this resource |
| `STATIC_TAB` | Replication | tab 'Replication' shows no backend data and nothing about this resource |

</details>

<details><summary><b>VPC Network</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Properties | tab 'Properties' shows no backend data and nothing about this resource |

</details>

<details><summary><b>Cloud KMS</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Rotation & labels | tab 'Rotation & labels' shows no backend data and nothing about this resource |

</details>

<a id="azure"></a>
## Azure

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ✅ | `nano-ui-azure-apim-tabs` | nano | ui | 11 | 0 | 16.9 |
| ✅ | `nano-ui-azure-app` | nano | ui | 29 | 0 | 21.6 |
| ✅ | `nano-ui-azure-appconfiguration` | nano | ui | 28 | 0 | 23.3 |
| ✅ | `nano-ui-azure-cognitiveservices` | nano | ui | 29 | 0 | 24.3 |
| ✅ | `nano-ui-azure-dns` | nano | ui | 28 | 0 | 24.0 |
| ✅ | `nano-ui-azure-dp` | nano | ui | 5 | 0 | 9.9 |
| ✅ | `nano-ui-azure-dp-detail` | nano | ui | 12 | 0 | 27.0 |
| ✅ | `nano-ui-azure-flat-create` | nano | ui | 8 | 0 | 18.2 |
| ✅ | `nano-ui-azure-home` | nano | ui | 7 | 0 | 3.8 |
| ✅ | `nano-ui-azure-keyvault-tabs` | nano | ui | 9 | 0 | 3.9 |
| ✅ | `nano-ui-azure-locks` | nano | ui | 8 | 0 | 8.2 |
| ✅ | `nano-ui-azure-metrics` | nano | ui | 12 | 0 | 13.2 |
| ✅ | `nano-ui-azure-monitor` | nano | ui | 29 | 0 | 28.7 |
| ✅ | `nano-ui-azure-nsg-roledef-create` | nano | ui | 7 | 0 | 11.0 |
| ✅ | `nano-ui-azure-nsg-rules` | nano | ui | 8 | 0 | 10.6 |
| ✅ | `nano-ui-azure-operationalinsights` | nano | ui | 33 | 0 | 28.2 |
| ✅ | `nano-ui-azure-rail-last` | nano | ui | 3 | 0 | 3.8 |
| ✅ | `nano-ui-azure-rg-nav` | nano | ui | 3 | 0 | 5.1 |
| ✅ | `nano-ui-azure-savings` | nano | ui | 8 | 0 | 8.5 |
| ✅ | `nano-ui-azure-storage-console` | nano | ui | 12 | 0 | 8.9 |
| ✅ | `nano-ui-azure-tabs` | nano | ui | 71 | 0 | 18.0 |
| ✅ | `nano-ui-azure-tags-tab` | nano | ui | 36 | 0 | 47.4 |
| ✅ | `nano-ui-reload-backend` | nano | ui | 3 | 0 | 10.3 |
| ✅ | `offline-api-azure-console-data-planes` | offline | api | 36 | 0 | 0.4 |
| ✅ | `offline-api-azure-console-lens` | offline | api | 33 | 0 | 0.6 |
| ✅ | `offline-api-azure-console-routes` | offline | api | 35 | 0 | 0.4 |
| ✅ | `offline-cli-azure` | offline | cli | 6 | 0 | 7.6 |
| ✅ | `offline-cli-azure-app` | offline | cli | 23 | 0 | 7.2 |
| ✅ | `offline-cli-azure-appconfiguration` | offline | cli | 32 | 0 | 12.9 |
| ✅ | `offline-cli-azure-cognitiveservices` | offline | cli | 20 | 0 | 6.1 |
| ✅ | `offline-cli-azure-dns` | offline | cli | 24 | 0 | 6.5 |
| ✅ | `offline-cli-azure-monitor` | offline | cli | 21 | 0 | 7.3 |
| ✅ | `offline-cli-azure-operationalinsights` | offline | cli | 20 | 0 | 6.4 |
| ✅ | `offline-sdk-go-azure` | offline | sdk-go | 14 | 0 | 21.4 |
| ✅ | `offline-sdk-go-azure-app` | offline | sdk-go | 29 | 0 | 3.1 |
| ✅ | `offline-sdk-go-azure-appconfiguration` | offline | sdk-go | 34 | 0 | 2.2 |
| ✅ | `offline-sdk-go-azure-cognitiveservices` | offline | sdk-go | 39 | 0 | 2.6 |
| ✅ | `offline-sdk-go-azure-dns` | offline | sdk-go | 31 | 0 | 1.1 |
| ✅ | `offline-sdk-go-azure-monitor` | offline | sdk-go | 30 | 0 | 3.0 |
| ✅ | `offline-sdk-go-azure-operationalinsights` | offline | sdk-go | 33 | 0 | 20.8 |
| ✅ | `offline-sdk-java-azure` | offline | sdk-java | 5 | 0 | 27.4 |
| ✅ | `offline-sdk-java-azure-app` | offline | sdk-java | 15 | 0 | 20.2 |
| ✅ | `offline-sdk-java-azure-appconfiguration` | offline | sdk-java | 28 | 0 | 6.8 |
| ✅ | `offline-sdk-java-azure-cognitiveservices` | offline | sdk-java | 28 | 0 | 5.5 |
| ✅ | `offline-sdk-java-azure-dns` | offline | sdk-java | 20 | 0 | 20.4 |
| ✅ | `offline-sdk-java-azure-monitor` | offline | sdk-java | 20 | 0 | 5.7 |
| ✅ | `offline-sdk-java-azure-operationalinsights` | offline | sdk-java | 23 | 0 | 20.2 |
| ✅ | `offline-sdk-python-azure-ops` | offline | sdk-python | 8 | 0 | 1.2 |
| ✅ | `offline-ui-azure-apim-tabs` | offline | ui | 11 | 0 | 15.3 |
| ✅ | `offline-ui-azure-app` | offline | ui | 29 | 0 | 19.6 |
| ✅ | `offline-ui-azure-appconfiguration` | offline | ui | 31 | 0 | 22.8 |
| ✅ | `offline-ui-azure-cognitiveservices` | offline | ui | 31 | 0 | 23.7 |
| ✅ | `offline-ui-azure-dns` | offline | ui | 30 | 0 | 23.4 |
| ✅ | `offline-ui-azure-flat-create` | offline | ui | 8 | 0 | 17.2 |
| ✅ | `offline-ui-azure-identity` | offline | ui | 9 | 0 | 7.0 |
| ✅ | `offline-ui-azure-locks` | offline | ui | 8 | 0 | 7.6 |
| ✅ | `offline-ui-azure-metrics` | offline | ui | 12 | 0 | 9.8 |
| ✅ | `offline-ui-azure-monitor` | offline | ui | 30 | 0 | 27.9 |
| ✅ | `offline-ui-azure-network-diagnose` | offline | ui | 7 | 0 | 9.6 |
| ✅ | `offline-ui-azure-nsg-roledef-create` | offline | ui | 7 | 0 | 10.7 |
| ✅ | `offline-ui-azure-nsg-rules` | offline | ui | 8 | 0 | 8.8 |
| ✅ | `offline-ui-azure-operationalinsights` | offline | ui | 34 | 0 | 27.3 |
| ✅ | `offline-ui-azure-rg-nav` | offline | ui | 3 | 0 | 4.8 |
| ✅ | `offline-ui-azure-tags-tab` | offline | ui | 36 | 0 | 49.5 |

**UI findings: 1**

<details><summary><b>API Management</b> (offline) — 1 finding(s)</summary>

| Problem | Tab | Detail |
|---|---|---|
| `STATIC_TAB` | Metrics | tab 'Metrics' shows no backend data and nothing about this resource |

</details>

<a id="all"></a>
## Cross-cloud

| Status | Suite | Target | Kind | Passed | Failed | Time (s) |
|---|---|---|---|---|---|---|
| ❌ | `nano-ui-crawl` | nano | ui | 42 | 21 | 1284.3 |
| ❌ | `offline-console-actions` | offline | api | 370 | 2 | 18.7 |
| ❌ | `offline-ui-crawl` | offline | ui | 38 | 20 | 1248.8 |
| ✅ | `nano-cores` | nano | core | 344 | 0 | 3.1 |
| ✅ | `nano-ui-budget-savings` | nano | ui | 5 | 0 | 4.5 |
| ✅ | `offline-cost-savings` | offline | api | 11 | 0 | 27.6 |
| ✅ | `offline-ui-core` | offline | ui | 9 | 0 | 24.2 |

<details><summary>❌ <code>offline-ui-crawl</code> log</summary>

```
[offline/aws] 20 services crawled, 16 with findings
UI crawl offline: 4/20 services clean → tests/conformance/hourly/out/ui-offline-aws.json
Console surfaces offline: {"static":75,"live":177,"partial":3,"unimplemented":16}
[offline/azure] 20 services crawled, 1 with findings
UI crawl offline: 19/20 services clean → tests/conformance/hourly/out/ui-offline-azure.json
Console surfaces offline: {"live":250,"unimplemented":39,"static":26}
[offline/gcp] 18 services crawled, 3 with findings
UI crawl offline: 15/18 services clean → tests/conformance/hourly/out/ui-offline-gcp.json
Console surfaces offline: {"live":207,"static":23}
```

</details>

<details><summary>❌ <code>offline-console-actions</code> log</summary>

```
........................................................................ [ 37%]
........................................................................ [ 56%]
........................................................................ [ 75%]
.s...s.................................................................. [ 93%]
........................                                                 [100%]
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
  ⚠ aws    174/176  (98.9%)
  ✓ azure  76/76  (100.0%)
  ✓ gcp    132/132  (100.0%)
  Full report → tests/conformance/console_actions/REPORT.md
=========================== short test summary info ============================
FAILED tests/conformance/console_actions/test_aws_console.py::test_aws_action[aws.cloudwatch.create] - AssertionError: AWS cloudwatch.create POST /api/aws/cloudwatch/alarms → HTTP 500 (expected one of (200, 201, 202, 204)). Body: Internal Server Error
assert False
FAILED tests/conformance/console_actions/test_aws_console.py::test_aws_action[aws.cloudwatch.list] - Failed: network error: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
2 failed, 370 passed, 12 skipped in 18.15s
```

</details>

<details><summary>❌ <code>nano-ui-crawl</code> log</summary>

```
[nano/aws] 20 services crawled, 16 with findings
UI crawl nano: 4/20 services clean → tests/conformance/hourly/out/ui-nano-aws.json
Console surfaces nano: {"live":217,"static":47,"partial":4,"unimplemented":3}
[nano/azure] 25 services crawled, 0 with findings
UI crawl nano: 25/25 services clean → tests/conformance/hourly/out/ui-nano-azure.json
Console surfaces nano: {"live":260,"static":55,"unimplemented":15}
[nano/gcp] 18 services crawled, 5 with findings
UI crawl nano: 13/18 services clean → tests/conformance/hourly/out/ui-nano-gcp.json
Console surfaces nano: {"live":176,"static":54}
```

</details>

## New features since the last run

None.

## Upstream changes (AWS / GCP / Azure backlog)

60 open `upstream-drift` issue(s) — real cloud changes the agent is working through. [All](https://github.com/vyomi-cloud/appliance/issues?q=label%3Aupstream-drift) · [watcher log](https://github.com/vyomi-cloud/appliance/tree/upstream-state)

| Issue | Cloud | Kind | Change | Opened |
|---|---|---|---|---|
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
| #165 | GCP | operation-changed | GCP sqladmin/v1beta4: operation sql.workloadCaptures.stop changed | 2026-10-28 |

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

## SDK operations without a test (210 of 1218)

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
<details><summary>GCP · <code>gcp_secretmanager_core</code> (nano) — 1</summary>

PatchSecret

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
<details><summary>GCP · <code>gcp_secretmanager_core</code> (offline) — 1</summary>

PatchSecret

</details>

## Last 24 runs

| Run | Suites | Checks ✓ | Checks ✗ | UI findings | API cov. | Agent |
|---|---|---|---|---|---|---|
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
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 98 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |
|  | 0/0 | 0 | 0 | 104 | 14.3% |  |
|  | 0/0 | 0 | 0 | 79 | 14.3% |  |
|  | 0/0 | 0 | 0 | 86 | 14.3% |  |

Raw data in this branch: `results.json`, `ui-findings.json`, `history.json`.
