# endurance-aws-observability

Branch `v4/endurance-aws-observability` (from v4-on-main + `v4/vyomi-endurance`). Mission: AWS estate stage 7 (observability / security / governance) and stage 8 (lifecycle / cost / ops) as Terraform that passes the cycle on the real simulator.

## Estate
- `estate/aws/modules/stage7-observability`: 2 log groups (retention, KMS), log stream, metric filter, log resource policy, Insights query definition, 6 metric alarms (SQS depth, DLQ, DynamoDB throttles, RDS CPU, app errors from the metric filter, EC2 status) with SNS actions, a composite alarm, a dashboard, 3 SSM parameters (one SecureString/KMS), an SSM document, a maintenance window, a CloudTrail trail + bucket policy on the stage-2 bucket.
- `estate/aws/modules/stage8-lifecycle`: Backup vault (KMS) + plan + selection on the DynamoDB table and RDS instance, a monthly Budget with notification, a Resource Group over the estate tag.
- Wired in `main.tf` as `module.observability` / `module.lifecycle`; stage 2/3 gained output-only additions.

## Simulator fixes
| F | Fix |
|---|-----|
| F200 | CloudWatch composite `AlarmRule` tokenizer split hyphenated alarm names (`ALARM(a-b)`), "Unable to parse AlarmRule" |
| F202 | PutMetricAlarm invented `DatapointsToAlarm` (= EvaluationPeriods) on read-back; real CloudWatch omits it when unset (perpetual diff) |
| F203 | SSM maintenance window returned `ScheduleTimezone: UTC` when unset (perpetual diff) |
| F204 | New AWS Budgets control plane (`core/aws_governance_core.py`, json-1.1, epoch times, default CostTypes) routed by `budgetservice` / `AWSBudgetServiceGateway` |
| F205 | New Resource Groups control plane (same core, rest-json) routed by `resource-groups` (also added to `routes/aws_s3.py` `_ROUTER_REST_SERVICES`) |
Regression tests: `tests/conformance/test_endurance_aws_observability_core.py`. Vendored to Nano (`wasm/build_cores.py` lists the new core).

## Result
On a fresh server (:19102): apply, no-diff re-plan (exit 0), destroy (~20 s, no hang), rebuild, re-plan, final destroy all PASS for the targeted set (stage 7+8 and their dependencies, 39 resources). Not run: the stage-2 `aws_instance` and the `ec2_status` alarm that depends on it — the simulator disk guard (`core/disk_health.py`, host Mac at >92% full, free tier) returns 507 on RunInstances; I did not bypass the guard. Re-run the full `run_estate.sh` once disk is freed.

## Not Terraform-expressible / open gaps
- Manifest has no aws ids for SSM, CloudTrail, Backup, Budgets, Resource Groups: they are exercised in Terraform but map to no capability id.
- Not applied: log subscription filters (need Lambda/Kinesis target), anomaly detection, contributor insights, data protection, field indexes, transformers, live tail, CloudWatch metrics queries, alarm actions for ec2/lambda, CloudFormation (21 ids; `aws_cloudformation_stack` not attempted), GuardDuty/Security Hub.
- Cloud-only operations (live tail, insights query execution, stack drift, change sets, metrics queries) belong to the SDK/CLI proof layer.
