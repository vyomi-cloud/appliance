# v4/iam-faithful

Owner: this session - Started: 2026-11-23 - Base: origin/v4-on-main (4a9f89f93) - Status: in progress (Phase 0)

## Purpose
Faithful IAM (AWS IAM, GCP IAM, Azure RBAC) for every in-scope service, with per-resource enforcement on/off, on Mesh and Nano. Full design: `docs/architecture/v4.0/IAM-FAITHFUL-DESIGN.md`.

## Architecture
- Phase 0: `scripts/gen_iam_catalog.py <aws|gcp|azure>` writes `core/iam_catalog/<cloud>/`: AWS Service Reference (37 prefixes, 4,463 actions, access level, resources, condition keys, API-operation map), GCP roles-permissions pages (34 products, 8,004 unique permissions, 451 roles), Azure docs permission tables (27 providers, 10,951 operations incl. data actions). All IDs verbatim.
- `tests/conformance/test_iam_catalog.py` checks the committed slices offline.
- Next: Azure built-in role definitions, GCP REST method->permission map, request->permission contract, shared engine `core/iam_engine/` (pure Python), middleware + nano-sw hooks.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Verbatim vendor permission IDs, Vyomi metadata beside them | `vyomi:`-prefixed or cross-cloud canonical IDs | real SDKs, Terraform and pasted policies use the real strings |
| Generate catalogs from vendor data, commit them | hand-typed permissions; fetch at runtime | reviewable diffs; Nano/offline need no network |
| Ship only the in-scope slice | whole-cloud catalogs (~45-50k IDs) | size; refreshed per service by the onboarding gate |

## Open issues
- [ ] Owner decisions assumed (design doc section 4/7/8): full-vs-in-scope catalog, Entra out of scope, Nano same release, default `off`.
- [ ] Azure built-in roles + GCP method->permission map (owner: this branch). GCP parser reads HTML and will need a fixture test if Google changes the page layout.
- [ ] Engine, hooks, UI, proof (phases 1-5).

## Integration (2026-11-23) - the eight work packages merged into this branch
engine-aws/gcp/azure, opmap-aws/gcp-azure, enforce-mesh, nano-hook, ui + service-inventory merged without conflicts. Integration findings fixed here:
- `gate.py` imported `xml.sax.saxutils` (pulls `socket` via urllib): replaced by a local escape (Pyodide-safe package rule).
- `gate.is_internal` let signed S3 requests to buckets named `assets/static/api/console-x/...` bypass enforcement: a SigV4/SigV2-signed request is never internal; only `/api/iam/` (and `/_wire`, `/nano/_wire` forms) is always internal so enforcement can be turned off.
- `aws_state` passed the raw store (engine reads `principals[arn].policies`): every IAM user would have been implicitly denied. Rewritten: identity policies (inline + attached managed + group), boundary documents, roles/assumed-role ARNs, attached SCPs.
- `aws_principal` put the boundary ARN on the principal, shadowing the boundary document: removed.
- New setting `unknownPrincipal` (`root` default | `deny`): credentials not in the IAM store (default test keys, the console's own signed traffic) act as the account root, so turning enforcement on does not lock out default-credential users; `deny` rejects them.
- Routes also served at `/_wire/api/iam/...` (the address the v4 consoles use on Mesh).
- `gcp_eval` skips `_*.json` catalog files (the 800 KB `_methods.json` is not a permission catalog).

Proven: `tests/conformance/test_iam_e2e_engine.py` (real map + real engine + gate, three clouds, real IAM store adapters) and `test_iam_mesh_server_e2e.py` (the real appliance app: limited IAM user, signed SQS calls, enforce/audit/off, per-service override, audit API). Nano: `wasm/ui-tests/iam/iam-hook-e2e.mjs` (S3, stand-in map/evaluator).

## Open (next work packages)
- Mesh GCP and Azure through the real server (needs a project/subscription bootstrap) and their state adapters (`gcp_state`, `azure_state` were never exercised against the live stores).
- Nano: state adapters from the in-browser stores (`iam_state_nano.py` does not exist), run the Nano e2e with the REAL map/engines, GCP/Azure in a browser, console-adapter path.
- Resource policies (S3 bucket policy, SQS/SNS/KMS/Lambda policies) are not fed to the AWS engine (`resource_policies` empty): identity-only evaluation today; explicit denies in resource policies are not seen.
- SCP attachment is not modelled by the Organizations store (no SCP is applied); service-agent/ACL oddities (GCP), conditions on built-in Azure roles.
- Request map gaps: 1,033 GCP methods unmapped (fail-closed in enforce), S3 DeleteObjects/CBOR resources are wildcards.
- Onboarding gate: wire `gen_iam_catalog.py` + request-map coverage into the service-expansion pipeline and CI.
- Entra ID is out of scope (assumption), Basic GCP roles are derived approximations.

## Second wave merged (2026-11-23): mesh-gcp-azure, resource-policies, nano-e2e, onboarding-gate, ui-live
- Mesh GCP + Azure proven on the real app (adapters rebuilt to the engines' state shape; gate passes host + query to the maps; deny-policy route fixed in `aws_wire_router.py` / `gcp_iam_core.py`).
- AWS resource policies (S3, SQS, SNS, KMS incl. the key-policy rule, Secrets Manager, Lambda, ECR, API Gateway) + attached SCP/RCP levels fed to the engine (`core/iam_resource_policies.py`).
- Nano: real engines in the browser for AWS/GCP/Azure (`core/iam_state_nano.py`), Chrome e2e 34/34; decision overhead < 1 ms p50.
- Onboarding gate (rule 14): 52 of 86 services enforceable (AWS 26/26, Azure 26/31, GCP 0/29 by the strict permission-reachability measure).
- UI verified against a live appliance (AWS full chain; GCP/Azure render and persist); Audit time + Azure audit grid fixed.
Merge result: 675 IAM pytest cases pass together, the 9 script-style IAM/RBAC suites exit 0, `build_cores.py --check` clean, `iamEnforce.test.mjs` passes.

## Still open
- Azure paths that never reach the gate: /openai, /azure-openai, /azure-sql, Graph, /oauth2, /_wire/arm. GCP path-style XML storage requests are routed as AWS S3.
- GCP: 1,033 unmapped methods; folder/org hierarchy, groups, PAB not fed from stores; opaque Nano tokens act as owner. Azure: management groups, PIM, groups not fed; non-blob data planes not driven live.
- AWS: API Gateway policy needs the API id resolved by the request map; SNS default policy, access-point/Object Lambda policies, cross-account principals.
- Re-run live-UI GCP/Azure "Allowed" cases against the merged backend (harness in the ui-live branch doc).
- `root` gets would-deny on ARM `roleDefinitions` reads in audit mode (ui-live finding, not yet investigated).
- Nothing has run in CI; nothing is on the trunk.

## Release gate
`tests/release/v4_checklist.py` (run by `v4-release-checklist.yml` on every release) now has `iam-faithful` (global: gate/Nano/resource-policy/onboarding tests, `gen_iam_coverage.py --check`, `build_cores.py --check`) and a per-cloud `iam-enforcement` check (engine + request map + real-server e2e for that cloud). A FAIL blocks the release unless waived with `--waive iam-faithful=<reason>`.

## Third wave merged (2026-11-23): gate-gaps, aws-azure-gaps, gcp-coverage
- Azure OpenAI/SQL/ARM-alias gated; Entra (Graph, /oauth2, OIDC) explicitly exempt; GCP XML storage API recognised and gated as GCP (`core/iam_engine/routing.py`, mirrored in `nano-iam-hook.js`).
- AWS: API Gateway id resolved, per-key DeleteObjects, CBOR bodies, more resource policies, anonymous S3 (default off, `anonymousS3: allow` opt-out). Azure: Shared Key + SAS (`azure_sas.py`), queue/table/Key Vault data planes live, Entra groups.
- GCP: 1033 -> 348 unmapped methods; 21/29 services enforceable under the NEW definition (share of the Discovery request surface mapped; strict catalog-reach kept as its own column with its own floor); hierarchy/groups/PAB fed; issued opaque tokens recorded.
- Post-merge: `testIamPermissions` needs no permission (gate), tested.
Merge result: 738 IAM pytest cases + 9 script-style suites green; build_cores/coverage checks clean.

### Still open
- GCP: 348 methods have no permission in the catalog (Vertex preview, SCC ETD, Backup&DR...); 1268 method ids use nearest-permission fallbacks; 8 services < 90%; denominator is the Discovery surface not the served set; folder/org `setIamPolicy` and project create not served.
- Azure: SAS signature not verified; stored-access-policy tokens allowed; management groups not modelled by any store; Nano has no storage_accounts/data_scopes for data planes; /contentsafety unmapped; Foundry /api/projects not gated.
- AWS: Block Public Access / ACL public access / website endpoints; multi-name AlarmNames binds alarm:*; layer policies not recorded by the store.
- Nano browser run for the new paths (OpenAI, GCS XML, anonymous S3, SAS) not done; nothing in CI; nothing on trunk.
