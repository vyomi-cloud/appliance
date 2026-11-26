# v4/verify-mesh

Base: origin/v4/iam-pickers-integ (15609b757). Purpose: verify faithful IAM end to end on the REAL Mesh server (server.py under uvicorn, no
mocks, no Docker) with the BUILT v4 console bundles served by it, driven by Playwright (chrome) plus boto3 / REST. Enforcement mode `enforce`.

## Harness
- `tests/conformance/mesh_verify/serve_mesh.py PORT [STATE_DIR]` runs server.py and mounts `wasm/v4` at `/v4/<cloud>/`.
- `tests/conformance/mesh_verify/lib.mjs` (Playwright helper; neutralises only the Nano boot scripts, defaults the GCP project to `vyomi-project`).
- `tests/conformance/mesh_verify/flows/*.mjs|py` the flows run (aws1-4, gcp1-2, az1-2) with their SDK/REST helpers. They were run against port 18741 and
  carry the fixture names used (vfy-*).

## Product bugs found and fixed
1. GCP Policy Troubleshooter used legacy `:testIamPermissions` (exact-resource bindings only, no conditions/inheritance): a conditional grant showed Denied.
   Now calls policytroubleshooter v3 `iam:troubleshoot` (faithful engine). `consoles/src/gcp/services/iam-admin/{api.js,PolicyTroubleshooter.jsx}`.
2. Azure ABAC role-assignment conditions never matched on the live gate (no attribute context): every conditional assignment denied. The Azure blob map now
   emits `@Resource` container name / blob path and `@Request` prefix / snapshot / versionId / encryption scope per permission; the gate merges it.
   `core/iam_engine/{map_azure,gate}.py`.
3. Azure role assignment PUT at a resource scope (what the SDKs do) dropped `condition` / `conditionVersion` (silently widening the grant) and the deny
   extension fields. `core/azure_arm_ext_core.py` `_role_assignments`.
4. Azure console Check access: sent no `isDataAction` (data actions evaluated as control plane), and read `result.value[0]` although ARM answers a bare array
   (decision always blank). Fixed in `ResourceIam.jsx`, `iam.js`, `Fields.jsx`, `IamEnforcement.jsx`; `/api/iam/<cloud>/evaluate` now accepts `data`.
5. AWS conditions on request-derived keys never matched on the live gate (no context): `s3:prefix`, `s3:delimiter`, `s3:x-amz-*`, `aws:RequestedRegion`,
   `aws:SourceIp`, `aws:SecureTransport`, `aws:UserAgent`. `core/iam_engine/map_aws.py` (S3), `core/iam_state_adapters.aws_request_context`, `core/middleware.py`.

## Tests added
`test_iam_mesh_server_e2e.py::test_aws_request_derived_condition_keys_reach_the_gate`, `test_iam_mesh_azure_e2e.py::test_azure_abac_condition_on_blob_data_plane`,
`test_iam_map_azure.py::test_blob_permissions_carry_abac_attribute_context`, `test_iam_map_aws.py::test_s3_entries_carry_request_condition_keys`.

## Not changed (noted)
- The built consoles carry `substrate=nano` (headless 4.0), so against a Mesh server the GCP console defaults to `nano-project`, which the Mesh server 403s
  (its project is `vyomi-project`). Real Mesh use routes only compute paths to Mesh (mesh-link.js), so this is harness-only; the harness presets the project.
- Azure Subscription / Resource-group blades keep their own checkAccess form (no data-action flag).
- The Azure `@Resource` blob index tag attributes and `isHnsEnabled` are not derived (the gate has no stored-blob-tag access).
