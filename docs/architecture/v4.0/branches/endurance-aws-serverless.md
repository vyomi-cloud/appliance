# v4/endurance-aws-serverless

## Why
AWS estate stage 5 (serverless-api in `tests/endurance/estate/stages.json`): Lambda, API Gateway (REST + HTTP v2), Step Functions, wired into the existing reference estate and run through the real provider (validate, apply, no-diff replan, destroy, rebuild, destroy).

## Estate
`tests/endurance/estate/aws/modules/stage5-serverless` (+ `module "serverless"` and lambda/apigateway/apigatewayv2/sfn endpoints and the `archive` provider in `main.tf`; four additive outputs in stage 2/3 modules):
orders API: Lambda layer, orders function (published version, KMS key, X-Ray, DLQ, env), alias `live`, function URL + public permission, event invoke config, processor function (reserved concurrency 5) fed by an SQS event-source mapping, EventBridge rule -> Lambda (+permission), REST API (resource, GET method requiring API key, AWS_PROXY integration, deployment, stage `prod`, API key, usage plan + key), HTTP API (JWT authorizer, route, integration, `$default` stage), Step Functions state machine (logging + tracing), IAM roles. Coverage: `tests/endurance/estate/coverage-map.aws-serverless.json` (17 ids).

## Simulator fixes (endurance F100-F109), regression `tests/conformance/test_endurance_aws_serverless_core.py`
- F100 IAM: AWS-managed policy ARNs (`arn:aws:iam::aws:policy/...`) resolve without being created.
- F101 Lambda GetFunctionCodeSigningConfig: 200 without ARN when none attached (was 404).
- F102 CreateFunction `Publish=true` publishes version 1; published snapshot keeps layers/KMS/tracing/DLQ/role.
- F103/F104 Lambda KMSKeyArn round-trips; empty Environment omitted.
- F105 GetFunction returns `Concurrency`; alias omits empty RoutingConfig.
- F106 Lambda AddPermission/GetPolicy honour `Qualifier`; `FunctionUrlAuthType` condition.
- F107 Lambda functions addressable by name, name:qualifier, partial or full ARN; event-source-mapping and event-invoke-config LastModified are epoch numbers; ESM echoes batching window and tuning fields.
- F108 API Gateway v1 timestamps are epoch numbers on the wire (state stays ISO); stage tags persist from CreateStage.
- F109 Step Functions ARNs use account 123456789012 (was 000000000000).
Vendored cores re-synced with `wasm/build_cores.py`.

## Result
See the final report in the PR/handoff: the targeted stage-5 cycle (`-target=module.serverless`, which pulls in KMS/DynamoDB/SQS/SNS/EventBridge dependencies) passes apply, no-diff replan, destroy, rebuild, final destroy.

## Open issues
- The full-estate gate could not complete on this host: stage 2 `aws_instance` is rejected by the simulator's `disk_freeze` guard (Mac at 98% disk, ~4 GiB free). Not a serverless defect; re-run `tests/endurance/run_estate.sh` on estate/aws once disk is free.
- Only the AWS-managed policy path pattern is validated (any well-formed name accepted); Lambda destinations config, code signing, provisioned concurrency, canary stages, WebSocket APIs, VPC links, custom domains, SFN versions/aliases are not yet in the estate.
- CI `GetFunction` `Code.Location` is a placeholder URL.
