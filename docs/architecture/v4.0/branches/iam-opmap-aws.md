# Branch v4/iam-opmap-aws (WP opmap-aws)

Owner files: `core/iam_engine/map_aws.py`, `core/iam_engine/aws_routes_data.py` (generated), `scripts/gen_iam_aws_routes.py`, `tests/conformance/test_iam_map_aws.py`.

## API
`map_aws.required(http_request) -> [{"action","resource","service","operation"}]`; `identify(req)` -> service+operation; `coverage()`; `python3 -m core.iam_engine.map_aws --coverage [-v] | --overrides`.
`http_request` = `{method, path (may include ?query), query (dict|str), headers, body, account?}`; account defaults to 123456789012, region comes from the SigV4 credential scope (header or `X-Amz-Credential`).
Several entries = all are required (AWS ANDs them).

## How it works
- Service: SigV4 signing name -> IAM prefix (`monitoring`->cloudwatch, `states`, `bedrock-runtime`->bedrock, ...), else `X-Amz-Target` prefix, else Host.
- Operation: `X-Amz-Target`, `Action=` (query string or form body), cbor path `/service/*/operation/<Op>`, or a REST route table (method + URI template + literal/required query + required headers) generated from botocore models into `aws_routes_data.py` (botocore is generation-time only; run `<python with botocore> scripts/gen_iam_aws_routes.py`).
- Actions: catalog `operations`; only the op's own action (or the same-verb action for renamed ones) plus conditional extras the request triggers (tag, acl, lock, retention, legal hold, ownership, version, bypass, policy). Other listed actions are ancillary and not required.
- Resources: catalog resource ARN formats; variables filled from URI labels, query/form/JSON params (name normalisation + synonyms), ARN-valued params matched against the service's formats; unresolved variables become `*`.
- Overrides (each with reason, `OVERRIDES` dict): S3 host styles / access points / versions / copy, SQS QueueUrl, API Gateway (action = HTTP method), execute-api data plane, KMS alias, CloudWatch cbor, EC2 RunInstances wildcards, create-noun, name fallback.

## Numbers
Coverage = for every catalog operation of the in-scope services, a request is synthesised from the route/target/action tables and run through `required()`; mapped if it returns that operation (or an identical-wire twin with the same actions). 4285/4286 operations (100.0%; only `s3:PutBucketNotificationConfiguration` is unmapped, it shares its wire form with `PutBucketNotification` which authorises a different action). Tests: 123 passed.

## Open / not verified
- Resource ARNs were checked against catalog formats and my knowledge of AWS, not against a real account; where the Service Reference lacks a resource type (e.g. CloudWatch `PutMetricData` lists `dataset`) the catalog wins.
- CBOR (rpc-v2) bodies are not decoded, so CloudWatch resources fall back to wildcards; real traffic from the simulator is Query/JSON.
- Parameters outside the request (account of the caller, IAM path, S3 multi-key DeleteObjects keys in the XML body, MRAP, S3 Control account-scoped ops) are approximated with `*`/defaults.
- API Gateway `UpdateRestApiPolicy`/`SetWebACL` style extra actions are not derived; execute-api has no catalog operations (hand rule).
- `aws_routes_data.py` and the catalog JSON are read from files/modules; `wasm/build_cores.py` must vendor them (or call `set_catalog_loader`) for Nano.
