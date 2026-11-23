# v4/iam-aws-azure-gaps

Owner: IAM work package aws-azure-gaps (Claude) - Started: 2026-11-23 - Base: origin/v4/iam-faithful (1e8f127f5) - Status: ready to merge into v4/iam-faithful

## Purpose
Close the AWS and Azure gaps listed in `iam-resource-policies.md` / `iam-mesh-gcp-azure.md`: request-map resolution, more resource policies, faithful anonymous S3, Azure Shared Key + SAS, and Azure group membership.

## What is in it
### AWS
| Item | Change |
|---|---|
| execute-api API id | `map_aws._execute_api_target`: id from the host label, `/restapis/<id>/<stage>/_user_request_/..`, `/apigw/<id>/<stage>/..`, `/<id>/<stage>/..`; `<id>.execute-api.*` hosts are recognised unsigned too. REST API resource policy (fed as `arn:aws:execute-api:r:a:<id>`) now matches the Invoke ARN. |
| S3 DeleteObjects | one `s3:DeleteObject` (or `DeleteObjectVersion` when a `<VersionId>` is given) per `<Key>` of the XML body; unparseable body keeps the old bucket-wide fallback. |
| CloudWatch CBOR | `_cbor_loads` (RFC 8949 subset, pure Python) decodes `smithy-rpc-v2-cbor` bodies, so alarm/metric resources bind exactly like the JSON/query protocols. |
| SNS default policy | topics without an explicit Policy get the document SNS generates (`__default_policy_ID`, `AWS:SourceOwner` = account). The engine supplies `AWS:SourceOwner` = the caller's account (1 line in `aws_eval._build_context`, not for anonymous). |
| S3 access point / Object Lambda policies | read from `buckets[b].access_points[n].policy` and `account.olaps[n].policy`; `owner_of` maps `accesspoint/<n>/object/<k>` to the access point (previously mis-parsed as bucket "accesspoint"). |
| ECR registry policy | `account.ecr.registryPolicy` is merged into every repository's policy and keyed as `registry/<acct>` so a not-yet-existing repository (CreateRepository / ReplicateImage) resolves to it. |
| Lambda alias / layer | statements whose Resource is a qualified ARN are keyed on that alias/version ARN (not folded into the function policy); layer version policies read from `_lambda_layers[n].versions[v].policy_statements` (the store does not record AddLayerVersionPermission yet: feed is ready, data is empty). |
| Anonymous S3 | see below. |

### Anonymous S3 (faithful, default still off)
- `iam_state_adapters.aws_resolve(hr, settings)` is the AWS half of the host gate (middleware calls it): signed (header, presigned query `X-Amz-Credential`/`AWSAccessKeyId`, `X-Amz-Target`) resolves the signer exactly as before; a browser form POST resolves the key id from its `x-amz-credential` / `AWSAccessKeyId` field (the `x-vyomi-form-akid` header is stripped from the wire and only set by the adapter); anything else addressed to an EXISTING bucket (path-style or virtual-host) is the principal `{type: anonymous, arn: ""}`.
- The engine already treats `anonymous` as resource-policy-only: bucket policy with `Principal: "*"` allows, everything else (including ListBucket without a grant) denies, an explicit Deny beats the Allow. Denial shape: S3 XML `AccessDenied` / "Access Denied".
- Not gated: console pages, static assets, `/`, health, OPTIONS (CORS preflight, not IAM), and paths that are not an existing bucket (real S3 answers NoSuchBucket 404). `settings.anonymousS3 = "allow"` restores the old never-gate behaviour (validated in `modes.py`).
- The map takes `http_request["service_hint"] = "s3"` (the host already knows) because an unsigned request has no credential scope and an arbitrary Host.

### Azure
- `core/iam_engine/azure_sas.py` + a 6-line hook in `azure_eval.evaluate` (`type` in `sas`/`sharedkey`): NOT RBAC.
  - Shared Key: full access to its own account's blob/queue/table data plane; other account -> `AuthenticationFailed`; ARM -> denied; `allowSharedKeyAccess=false` on the account (fed from the ARM record) -> `KeyBasedAuthenticationNotPermitted` (also for SAS signed with the account key).
  - SAS: authorization by the token. `sp` letters vs the operation (blob r/w/c/a/d/l/t, queue r/a/u/p/d, table r/a/u/d), `se`/`st`, service SAS `sr` (b vs c), account SAS `ss` + `srt`, user-delegation (`skoid`): token AND the delegator's RBAC. Errors are the Storage ones (`AuthorizationPermissionMismatch`, `AuthorizationResourceTypeMismatch`, `AuthenticationFailed`) in XML with `x-ms-error-code` (gate `denial_spec`).
  - Principal order (adapter): `X-Cloudlearn-Principal` > `Authorization: SharedKey|SharedKeyLite acct:sig` > SAS query (`sig` + `sv/sp/se/si`) > bearer claims > active principal. SharedKey/SAS are recognised only on `/azure-data/{blob,queue,queue-core,table,tableroot}` paths (a `sig=` on another service is not a storage SAS).
  - `map_azure` carries `hint` ("list", "update") because list-vs-read and update-vs-process share an RBAC action but differ in SAS letter; the gate passes it as `context.hint`.
- Root-wire Storage paths (`/azure-data/queue-core/..`, `/azure-data/tableroot/..`, the form the v4 console / host-style SDKs hit) were UNMAPPED (403 under enforce). Now mapped; account = host label `<acct>.queue.*`, else the `SharedKey acct:` header, else `_default`, which the adapter maps to the sole storage account (several accounts: the first account's subscription scope).
- Entra groups: `state["groups"]` from `graph_store()` (transitive in the engine); a UPN/mail or an application (client) id in `X-Cloudlearn-Principal` / `appid` resolves to the object id role assignments use.
- Management groups: NO store models `Microsoft.Management/managementGroups` (`PUT /providers/Microsoft.Management/managementGroups/x` falls through to S3 NoSuchBucket). `azure_state` feeds `management_groups` / `subscriptions` from such ARM records if one ever exists (unit-tested with synthetic records); nothing live.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| SAS/Shared Key rule in its own pure module, called from `azure_eval.evaluate` | encode SAS as synthetic role assignments | SAS is token-claim authorization (no role, no scope inheritance); synthetic roles would give wrong errors and wrong precedence |
| anonymous only for EXISTING buckets | gate every unsigned request | console pages / assets / unknown buckets must never 403; matches S3 (NoSuchBucket) |
| `aws_resolve` in the adapter, middleware change is 5 lines | logic in middleware | testable without the app, shared with Nano later |
| ECR registry policy merged per repo + `registry/<acct>` key | engine learns two documents | the engine takes ONE resource document per ARN |

## Open issues
- [ ] SAS signature is not verified and a stored access policy (`si`, no `sp`) is allowed (permissions live in the container ACL; not resolved). `spr` (https only) is not enforced.
- [ ] Table errors are Storage XML, real Table answers OData JSON.
- [ ] SNS default policy / anonymous principal feed the in-process Mesh path; Nano (`iam_state_nano.azure_principal`) got SharedKey/SAS but its Azure state has no `data_scopes` / `storage_accounts` (so `allowSharedKeyAccess` and account inheritance are Mesh-only) and Nano's `state_and_principal` does not pass the request path. Not run in a browser.
- [ ] Anonymous S3: Block Public Access (account/bucket), ACL-based public access, access point alias hosts, S3 website endpoint and Object Lambda hosts are not modelled; an unsigned download link opened from a console tab is now denied when enforcing (use `anonymousS3: "allow"`).
- [ ] AWS multi-key DeleteAlarms-style list parameters still bind the first name (JSON path too).
- [ ] The offline alias `/azure-data/queue/<acct>/..` is served by an Azurite-backed handler (503 without it); live tests drive the in-process root wire (`queue-core`) via a host-style request (`VYOMI_AZURE_STORAGE_SUFFIX`).
- [ ] The built-in "Storage Queue Data Contributor" in the vendored catalog has no `messages/add/action`, so sending needs the Message Sender role there (catalog is verbatim; not changed).
- [ ] Script-style files (`test_iam_access_report.py`, `_actions_core`, `_core`, `_list_member_shape_core`, `_role_manager`, `_sweepiam*`, `_unification`) call `sys.exit` at collection, so the single glob `pytest tests/conformance/test_iam_*.py` aborts with INTERNALERROR on the base too.

## Tests (`PYTHONPATH=repo:repo/core CLOUDLEARN_TIER_ENFORCE=0 .../portal-run/.venv/bin/python -m pytest -q -p no:cacheprovider`)
- `tests/conformance/test_iam_aws_gaps.py` (17): map forms, per-key DeleteObjects, CBOR decoder + CloudWatch, SNS/AP/OLAP/ECR/alias/layer policies, anonymous resolution + gate shape, and live: public bucket policy, presigned URLs resolve their signer, console/unknown bucket never gated, explicit Deny, `anonymousS3: allow`, audit.
- `tests/conformance/test_iam_azure_gaps.py` (16): SAS rule matrix, Shared Key, delegation SAS, root-wire mapping, principal order, Entra groups (nested) + UPN, management-group feed, and live queue / table / Key Vault data planes through the app, SAS and Shared Key over real blob/queue/table requests.
