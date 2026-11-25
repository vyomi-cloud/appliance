# Branch: v4/iam-simulate-analyze

Work package simulate-analyze: faithful IAM analysis APIs on both substrates (Mesh and Nano), from `origin/v4-on-main`.

## What is built (route table: `IAM-ENGINE-CONTRACT.md`, section "Analysis APIs")
- AWS IAM Query `SimulatePrincipalPolicy`, `SimulateCustomPolicy`, `GetContextKeysFor{Principal,Custom}Policy` answered by `aws_eval` over the live state (`core/iam_engine/analyze_aws.py`, wired in `core/iam_core.py`): identity, group, boundary, SCP/RCP and resource policies (`core/iam_resource_policies.py`), MatchedStatements with SourcePolicyId/Type and Start/EndPosition, MissingContextValues, OrganizationsDecisionDetail, PermissionsBoundaryDecisionDetail, ContextEntries.
- Access Analyzer REST (`core/iam_engine/access_analyzer.py`): analyzers, external-access findings (S3 / SQS / SNS / KMS / Lambda / Secrets / role trust), unused-access findings (unused keys, roles, permissions) from the activity log and the decision ring, ValidatePolicy, CheckNoNewAccess, CheckAccessNotGranted. The console's IAM-wire findings view now uses the same generator. `Get/GenerateServiceLastAccessedDetails` also fold the decision ring.
- GCP: Policy Troubleshooter v1/v3 and Cloud Asset `analyzeIamPolicy` (`analyze_gcp.py`, over `gcp_eval`: conditions TRUE/FALSE/UNKNOWN, deny policies, PAB).
- Azure: `checkAccess` (native PascalCase body, bare array), `permissions`, `roleAssignments?$filter=atScope()|principalId eq|assignedTo()`, eligibility / assignment schedule shapes (`analyze_azure.py`), deny assignments honoured.
- Routing: `analyze_wire.py` (pure route table). Mesh: `core/middleware.py` -> `core/iam_analyze_host.py`. Nano / relay: `core/aws_wire_router.py` fallback and `wasm/nano-iam-hook.js` (`analysisRoute`, `analyze`, `guardWire`) -> `nano_bridge.analyze` (catalogs prefetched on demand, like the gate).

## Verified (run)
- `tests/conformance/test_iam_simulate_analyze.py`: 20 passed (unit + real-app TestClient, one per cloud).
- Existing IAM pytest set: 758 passed, 1 failed (`test_service_inventory.py::test_inventory_is_current`: `wasm/service-inventory.json` is stale on trunk itself, tfstudio entry; not touched here). `*_core.py` script suites all green. `build_cores.py --check` and `gen_iam_coverage.py --check` green.
- Nano Chrome e2e `wasm/ui-tests/iam/iam-analyze-e2e.mjs`: 15/15 (AWS, GCP, Azure in the page, plus the same routes through the relay SharedWorker).
- boto3 1.43.18 against the real app: `simulate_principal_policy` (explicitDeny / allowed / implicitDeny), `simulate_custom_policy` (MissingContextValues aws:SourceIp), accessanalyzer `create_analyzer`, `list_analyzers`, `validate_policy` (INVALID_ACTION, PASS_ROLE_WITH_STAR_IN_RESOURCE), `check_no_new_access` (FAIL), `check_access_not_granted`.

## Approximated, not exact
- Statement positions come from a pretty-printed re-serialisation (line 1-based, column 0-based), not the caller's original text.
- ValidatePolicy emits only INVALID_ACTION, MISSING_ACTION, MISSING_RESOURCE, MISSING_PRINCIPAL, MISSING_VERSION, PASS_ROLE_WITH_STAR_IN_RESOURCE, PASS_ROLE_WITH_STAR_IN_ACTION_AND_RESOURCE. Services without a catalog slice are unverifiable: no INVALID_ACTION is claimed.
- v3 troubleshooter PAB / deny enum and field names are approximate; `analyzeIamPolicy` covers allow policies only.
- Eligibility lists are only as rich as the store (no PIM records today, so empty).
- `aws:PrincipalTag/*` is never reported in MissingContextValues (existing contract of `test_iam_sweepiam2_core`; real AWS would). `MissingContextValues` and `EvalDecisionDetails` are omitted when empty / identity-only.
- Analysis APIs are not gated by the enforcement gate (like testIamPermissions).
- On Nano an unknown GCP permission whose service catalog is not bundled is treated as unverifiable (200), not 400.

## Open issues
- `providers/aws_iam_query_ext.py` (offline adapter) still uses the legacy `simulate_xml`.
- Unused-access analyzer type and the `findingsv2` pagination are minimal.
- The trunk ships no generated `aws-console.html`; the Nano e2e writes a throwaway page for `nano-boot.js` instead.
