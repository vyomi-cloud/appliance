# v4/iam-resource-policies

Owner: this session - Started: 2026-11-23 - Base: origin/v4/iam-faithful (d4b716218) - Status: ready for integration

## Purpose
Feed resource-based policies and org SCP/RCP to the AWS faithful-IAM engine (before: `resource_policies = {}`, identity-only; explicit Denies in bucket/queue/key policies and cross-principal Allows were invisible, no SCP applied).

## Architecture
- `core/iam_resource_policies.py` (pure Python, Pyodide-safe, vendored via `IAM_CORE_EXTRAS` in wasm/build_cores.py). `aws_resource_policies(stores)`, `aws_resource_tags(stores)`, `aws_requires_grant(stores)`, `aws_state_extras(iam_store)`, `org_levels(iam_store)`, `host_stores()` (Mesh `core.appliance_stores`, else Nano `nano_registry`).
- One additive hook in `aws_state()` (core/iam_state_adapters.py), try/except guarded: `out.update(_rp.aws_state_extras(store))`.
- Fed (key = ARN the request map emits):

| Service | Source | Key |
|---|---|---|
| S3 bucket policy | `buckets[b]["cfg"]["policy"]` | `arn:aws:s3:::b` (object ARNs resolve to it) |
| ECR repository policy | `s3.account["ecr"]["regions"][r][n]["policy"]` | `...:repository/n` |
| SQS queue policy | `queues[n].attributes.Policy` | `queue_arn` |
| SNS topic policy | `topics[n].attributes.Policy` (explicit only; the generated default is not fed) | `topic_arn` |
| KMS key policy | `keys[id].Policy` | key ARN and every alias ARN of the key (the map cannot resolve alias -> key) |
| Secrets Manager | `secrets[n].resource_policy` | full ARN (with suffix) and the suffix-less by-name ARN the map emits |
| Lambda function policy | `_lambda_functions[n].policy_statements` | function ARN (qualified ARNs resolve to it) |
| API Gateway REST resource policy | `_apigateway_apis[id].policy` | `arn:aws:execute-api:r:a:<apiId>` (see open issue) |

- `ResourcePolicyMap(dict).get()` widens lookups: S3 object -> bucket, Lambda `function:n:qual` -> `function:n`, execute-api `<apiId>/<stage>/..` -> `<apiId>`. The engine is unchanged for this (it calls `.get(resource)`). The state must reach the engine in-process (gate/Nano do); a JSON round trip degrades to exact-ARN lookup.
- KMS rule (the only aws_eval change, 3 lines + 1 comment): `state["resource_policy_requires_grant"]` lists key ARNs whose policy does NOT enable IAM (no condition-less Allow naming the account root / `*`); for those an identity Allow alone is an implicit deny, only a direct key-policy grant allows. Default key policy (root `kms:*`) behaves as before.
- SCP/RCP: attachment already existed in `core/organizations_core.py` (`extras["org"]["attachments"]`, AttachPolicy/DetachPolicy), the old adapter looked for a non-existent `targets` field. `org_levels` builds one level per node root -> OU... -> account (every level must allow). AWS: SCPs never restrict the MANAGEMENT account, so it gets none; Vyomi extension for single-account learners: `extras["org"]["scp_apply_to_management"] = True`.
- GCP/Azure (verified by reading, not changed): GCP bucket/object IAM is in `gcp_iam_state` policies and reaches `gcp_state`; Azure resource-scope role assignments are ARM `Microsoft.Authorization/roleAssignments` records picked up by `azure_state`. Not exercised against live stores here (owned by the mesh-gcp-azure WP).

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Widen lookup in a dict subclass | change `aws_eval` lookup | engine behaviour unchanged, existing tests untouched |
| KMS rule via host-provided ARN list | key-type logic inside the engine | the engine stays service-agnostic |
| Management account exempt from SCPs (opt-in override) | always apply | AWS fidelity; override keeps the single-account lab useful |

## Open issues
- [ ] API Gateway: the request map emits `arn:aws:execute-api:r:a:*/*/GET/<apiId>/<stage>/...` (api id not parsed from the path-style URL), so the REST API resource policy is fed but does not match until the map resolves the API id.
- [ ] Not fed: SNS default policy, S3 access point / Object Lambda policies, ECR registry policy, Lambda layer/alias policies, SQS/SNS policies via non-AWS-API paths, VPC endpoint policies, cross-account principals (single-account store).
- [ ] KMS rule ignores conditions on the root statement (treated as not enabling IAM); KMS grants (CreateGrant) not evaluated.
- [ ] Resource policy `Condition` keys needing request context beyond what the gate supplies follow the engine's missing-context behaviour.
- [ ] `tests/conformance/test_nano_core_manifest.py` fails on the base too (`aws_governance_core.py` not loaded by nano-boot.js), unrelated.
- [ ] Nano run of the new feed not executed in a browser (same stores' attributes via `nano_registry`; python-side only).

## Tests
`tests/conformance/test_iam_resource_policies.py`: unit (fake stores + real engine: per-service keys, lookup widening, bucket Deny on object ARN, cross-account allow, SQS grant, KMS rule, SCP levels + management exemption, hook failure safety) and end-to-end through `server.app` (bucket-policy explicit Deny for a user with `s3:*`, SQS queue-policy allow for a user with no SQS identity grant, enforce off restores, plus every service's policy reaching the feed from live stores).
