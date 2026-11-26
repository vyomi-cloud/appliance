# Suites retarget: AWS (+ cloud=all)

Branch `v4/suites-retarget-aws`. Registry: `tests/conformance/hourly/suites.json`. Legacy v3 console (`wasm/aws-console.html`, `/console/aws`) was deleted in 0218b1f16; the appliance 4.0.0 is headless (no offline console), so every `offline-ui-*` variant is C.

A = retargeted to the v4 console and run green (pending removed). B = `retired: covered by <suite>` (kept pending, reported not run). C = behaviour/route gone or not retargeted (pending with a specific reason).

New scripts: `wasm/ui-tests/validate-aws-v4-detail.mjs` (+ `_aws_v4_seed.py`; list -> detail -> every tab per service, 25 profiles), `validate-aws-v4-metrics.mjs`, `validate-aws-v4-nano-persist.mjs`, `validate-aws-v4-nano-savings.mjs`, `validate-v4-nano-drawer.mjs`, `_aws_roundtrip_cli.py` (SDKPY for the existing round-trip), `validate-aws-v4-validation.mjs` (not live). Wrappers: `tests/conformance/nightly/aws-v4-detail.mjs` (dev_server; `SCRIPT=` selects another script), `v4-nano-run.mjs` (nano_preview). Playwright was run with the system Chrome (`PW_CHANNEL=chrome`); boto3 from a python 3.14 install.

| suite id | class | evidence / reason | verification |
|---|---|---|---|
| nano-ui-crawl | pending | not retargeted: the v3 generic click-through crawler (toolbar/row actions, toggles, drawers) has no v4 DOM equivalent yet; tab-walk is covered by nano-ui-aws-real-tabs and spec fidelity by consoles/tests/ui-conformance.mjs | not run (pending) |
| offline-request-metrics | A | cmd `python3 -m pytest tests/conformance/test_request_metrics.py -q --tb=line` | 4 passed (pytest, tests/conformance/test_request_metrics.py) |
| nano-ui-aws-metrics | A | cmd `SCRIPT=wasm/ui-tests/validate-aws-v4-metrics.mjs node tests/conformance/nightly/aws-v4-detail.mjs` | 7/7 (validate-aws-v4-metrics.mjs via aws-v4-detail.mjs wrapper) |
| offline-ui-aws-metrics | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-metrics | not run (pending) |
| nano-ui-aws-api | B | retired: covered by nightly-aws-v4-roundtrip (create/list/delete of every core service over the v4 wire) | not run (pending) |
| nano-ui-aws-tabs | B | retired: covered by nano-ui-aws-real-tabs (s3 profile walks every bucket tab) | not run (pending) |
| nano-ui-aws-vpc-apigw-lists | B | retired: covered by nano-ui-aws-vpc-details-tab (subnets/route tables/igw lists) and nano-ui-aws-real-tabs (apigw/httpapi Resources/Stages tabs) | not run (pending) |
| nano-ui-aws-compute-reload | B | retired: covered by nano-ui-aws-rds-persist (lambda, api gateway, vpc survive a Nano reload; eventbridge rule not re-asserted) | not run (pending) |
| nano-ui-aws-compute-savings | B | retired: covered by nano-ui-budget-savings (sqs/lambda/api gateway/vpc move cost_savings on Nano; eventbridge rule not re-asserted) | not run (pending) |
| nano-ui-aws-ec2-detail-tabs | A | cmd `NANO_DIR=$PWD/wasm RELAY_HTTP={RELAY} node wasm/ui-tests/validate-aws-ec2-detail-tabs.mjs` | 15/15 (wrapper ONLY=ec2) |
| offline-ui-aws-ec2-detail-tabs | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-ec2-detail-tabs | not run (pending) |
| nano-ui-aws-real-tabs | A | cmd `NANO_DIR=$PWD/wasm RELAY_HTTP={RELAY} node wasm/ui-tests/validate-aws-real-tabs.mjs` | 248/248 passed, 1 skipped (full run, 25 service profiles) |
| offline-ui-aws-real-tabs | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-real-tabs | not run (pending) |
| offline-ui-aws-sqs-dlq-tab | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-sqs-dlq-tab | not run (pending) |
| nano-ui-aws-sqs-dlq-tab | pending | blocked, product gap: v4 console DLQ tab renders "-" for a queue without a redrive policy, real SQS says "Disabled" (consoles/src/aws/services/sqs/QueueDetail.jsx DlqTab); the sqs profile of nano-ui-aws-real-tabs prints it as a SK | not run (pending) |
| nano-ui-aws-rds-connectivity-tabs | A | cmd `NANO_DIR=$PWD/wasm RELAY_HTTP={RELAY} node wasm/ui-tests/validate-aws-rds-connectivity-tabs.mjs` | profile rds passed within the 248/248 full run |
| offline-ui-aws-rds-connectivity-tabs | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-rds-connectivity-tabs | not run (pending) |
| nano-ui-aws-vpc-details-tab | A | cmd `NANO_DIR=$PWD/wasm RELAY_HTTP={RELAY} node wasm/ui-tests/validate-aws-vpc-details-tab.mjs` | vpc,subnet,sg,igw,rtb passed within 248/248 (also 31/31 for subnet,sg,rtb alone) |
| offline-ui-aws-vpc-details-tab | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-vpc-details-tab | not run (pending) |
| nano-ui-aws-vpc-sg-iam-cells | B | retired: covered by nano-ui-aws-vpc-details-tab (sg id/name) and nano-ui-aws-real-tabs (iam ARN) | not run (pending) |
| offline-ui-aws-vpc-sg-iam-cells | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-vpc-details-tab | not run (pending) |
| nano-ui-budget-savings | A | cmd `SCRIPT=wasm/ui-tests/validate-aws-v4-nano-savings.mjs node tests/conformance/nightly/v4-nano-run.mjs` | 12/12 on real Nano preview (red before the nano-boot.js census fix) |
| nano-ui-aws-elbv2 | B | retired: covered by nano-ui-aws-real-tabs (elbv2 profile); UI create/delete flow not re-asserted | not run (pending) |
| nano-ui-aws-logs | B | retired: covered by nano-ui-aws-real-tabs (logs profile) and nightly-aws-v4-roundtrip (cloudwatch) | not run (pending) |
| nano-ui-aws-ssm | B | retired: covered by nano-ui-aws-real-tabs (ssm profile) and nightly-aws-v4-roundtrip (ssm) | not run (pending) |
| nano-ui-aws-event-delivery | B | retired: covered by offline-post-create-aws-event-delivery (same events/lambda/stepfunctions cores; Nano Pyodide sandbox itself not re-asserted) | not run (pending) |
| nano-ui-aws-stepfunctions | B | retired: covered by nano-ui-aws-real-tabs (states profile) and nightly-aws-v4-roundtrip (states) | not run (pending) |
| nano-ui-aws-lambda-row | B | retired: covered by nano-ui-aws-real-tabs (lambda profile: row cells, detail, tabs) | not run (pending) |
| nano-ui-aws-ec2-row | B | retired: covered by nano-ui-aws-ec2-detail-tabs (row cells, detail, tabs) | not run (pending) |
| nano-ui-aws-apigw-row | B | retired: covered by nano-ui-aws-real-tabs (apigw/httpapi profiles) | not run (pending) |
| nano-ui-aws-detail-tabs | B | retired: covered by nano-ui-aws-real-tabs | not run (pending) |
| offline-ui-aws-detail-tabs | C | retired: headless 4.0.0 appliance serves no console (MESH-CODESPACES-GITHUB-APP.md s10; core/mesh.py _UI_PREFIXES); the v4 console runs on Nano, covered by nano-ui-aws-real-tabs | not run (pending) |
| nano-ui-aws-vpc-row | B | retired: covered by nano-ui-aws-vpc-details-tab | not run (pending) |
| nano-ui-aws-eventbridge-row | B | retired: covered by nano-ui-aws-real-tabs (rule + events bus profiles) | not run (pending) |
| nano-ui-aws-settings-tabs | B | retired: covered by nano-ui-aws-real-tabs (ddb/sqs/secret/kms tabs load unset settings with no wire error); saved-edit-survives-reload not re-asserted | not run (pending) |
| nano-ui-aws-iam-detail | B | retired: covered by nano-ui-aws-real-tabs (iam profile asserts the user ARN) | not run (pending) |
| nano-post-create-aws-ec2-ssh | pending | not retargeted: needs the v4 EC2 launch wizard + Connect modal driven through a real vyomi-tunnel >= 1.1 and an in-browser v86 VM, which a headless run cannot supply here; offline twin is offline-post-create-aws-ec2-ssh | not run (pending) |
| nano-ui-aws-kinesis | B | retired: covered by nano-ui-aws-real-tabs (kinesis profile) and nightly-aws-v4-roundtrip (kinesis) | not run (pending) |
| nano-ui-aws-apigatewayv2 | B | retired: covered by nano-ui-aws-real-tabs (httpapi profile: HTTP API created with apigatewayv2) | not run (pending) |
| nano-ui-aws-cloudwatch | B | retired: covered by nano-ui-aws-real-tabs (alarm + logs profiles) and nightly-aws-v4-roundtrip | not run (pending) |
| nano-ui-aws-sns | B | retired: covered by nano-ui-aws-real-tabs (sns profile) and nightly-aws-v4-roundtrip (sns); publish/SMS-sandbox flows not re-asserted | not run (pending) |
| nano-ui-aws-secrets-created | B | retired: covered by nano-ui-aws-real-tabs (secret profile: no blank row cell) | not run (pending) |
| nano-ui-drawer | A | cmd `NANO_DIR=$PWD/wasm RELAY_HTTP={RELAY} node wasm/ui-tests/validate-drawer.mjs` | 46/46 on real Nano preview (aws, gcp, azure) |
| nightly-aws-tunnel-recovery | pending | written (aws-tunnel-recovery.py) but needs the Codespace leg: NIGHTLY_CODESPACES_PAT + NIGHTLY_TUNNEL_FAULTS=1 (dimension 6) | not run (pending) |
| nano-ui-aws-rds-persist | A | cmd `NANO_DIR=$PWD/wasm RELAY_HTTP={RELAY} node wasm/ui-tests/validate-nano-rds-persist.mjs` | 17/17 on real Nano preview (wrapper v4-nano-run.mjs) |
| bidi-aws-cli-ui | A | cmd `SDKPY=wasm/ui-tests/_aws_roundtrip_cli.py ONLY=s3,sqs,sns,dynamodb,secretsmanager,iam,ssm,kinesis,cloudwatch,e` | 40/40 (10 services, real aws CLI vs v4 console) |
| bidi-aws-sdk-ui | B | retired: covered by nightly-aws-v4-roundtrip (boto3 <-> v4 console, 23 services) | not run (pending) |
| bidi-aws-api-ui | B | retired: covered by nightly-aws-v4-roundtrip (the v4 console speaks only the native wire, so the API leg is the SDK leg) | not run (pending) |
| crawl-aws-ui | pending | not retargeted: v4 action crawler (toolbar/row actions, toggles) not written; tab-walk covered by nano-ui-aws-real-tabs | not run (pending) |
| validation-aws-ui | pending | script written (wasm/ui-tests/validate-aws-v4-validation.mjs) but 13/17 on its first run: SNS accepts an invalid topic name (a real-console rejection is missing) and the valid-name control steps for SQS/DynamoDB/IAM need driver fi | not run (pending) |

nightly-aws-tunnel-recovery: untouched, pending for the Codespace leg (NIGHTLY_CODESPACES_PAT), unrelated to the legacy console.

## Findings from the retarget

- F1 RDS default security group `sg-default` is not an EC2 group: the RDS detail page's `DescribeSecurityGroups` answers 400 for a default-created DB (the suite seeds a real SG).
- F2 SQS DLQ tab renders `-` where real SQS says `Disabled` (`consoles/src/aws/services/sqs/QueueDetail.jsx`); printed as SKIP.
- F3 FIXED here: `wasm/nano-boot.js` only wrote the resource census on `<cloud>-console.html`, so on `/v4/<cloud>/` Nano cost_savings / host-distribution never moved. One-line match added; `nano-ui-budget-savings` was 0->0 before, 12/12 after.
- F4 `consoles/dev_server.py` does not mount the IAM engine API (`/api/iam/aws/enforcement`); the IAM Enforcement tab 404s there only (printed SKIP).
- F5 SNS create form accepts an invalid topic name and sends CreateTopic (validation-aws-ui, pending).
- Not carried over from the v3 suites (stated in each B reason): cost_savings moving per service in the SNS/SSM/... flows, saved-settings-survive-reload, EventBridge rule reload/savings, Nano Pyodide event-delivery, SNS publish/SMS flows.

