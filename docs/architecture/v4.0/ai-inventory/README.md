# AI enterprise plan: API inventory (Phase 0)

First draft of the "100% conformance" denominator (owner approved building it, 2026-11-14). **AWS only so far**; GCP (API
discovery docs / protos) and Azure (OpenAPI specs) come next.

- `aws_inventory.py` reads the official botocore service models (botocore 1.43.18 when generated) for the services the 13
  components touch and writes `aws_inventory.csv` (service, operation, in_scope, core_mentions, components).
- `in_scope` is `yes` for everything now. The owner flips non-goals to `no`; that list is what needs sign-off.
- `core_mentions` = number of `core/*.py` files at trunk `origin/v4-on-main` that contain the operation name. It is a CRUDE
  signal only: services routed by path (REST) often never mention operation names, and names such as CloudTrail event names
  appear in unrelated cores. It is NOT an implementation status. Contract tests through the native SDK replace it.

Draft totals (27 services, 1632 operations): bedrock 106, bedrock-runtime 10, bedrock-agent 72, bedrock-agent-runtime 31,
bedrock-agentcore-control 147, bedrock-agentcore 65, cognito-idp 122, cognito-identity 23, wafv2 55, opensearchserverless 46,
opensearch 88, stepfunctions 37, cloudtrail 60, cloudwatch 46, logs 113, xray 38, lambda 85, dynamodb 57, kms 54, sns 42,
sqs 23, events 57, s3 111, timestream-write 19, timestream-query 15, textract 25, comprehend 85.

Next: (1) owner triage of non-goals per service (many ops are admin/billing/rare); (2) replace `core_mentions` with a probe that
sends each operation through the simulator with the real SDK and records served / rejected / 404; (3) the same for GCP and Azure.
