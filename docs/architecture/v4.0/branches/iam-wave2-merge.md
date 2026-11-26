# v4/iam-wave2-merge

Integration of the second faithful-IAM wave on top of v4/iam-pickers-integ. NOT merged to trunk; the release (4.1.1) is cut by the owner.

Merged: v4/trunk-hygiene, v4/verify-mesh, v4/verify-nano, v4/console-look, v4/iam-catalog-complete, v4/iam-governance, v4/iam-identity-audit, v4/compute-sizes, v4/azure-all-services. See each branch's own doc.

Merge notes
- Generated files (wasm/v4 bundles, wasm/core, coverage, inventory) were regenerated, not hand-merged.
- core/iam_engine/api.py: governance_fn + trail_fn/events_fn + 'governance'/'events' routes kept; /evaluate takes `data` only when the caller states it (Azure engine tries both planes otherwise).
- core/iam_state_nano.py: PIM schedules, kind=deny deny-assignments and plain assignments all kept.
- GCP Policy Troubleshooter: native v3 iam:troubleshoot call + normalizeMember (service-account emails).
- IAM onboarding: service_map entries added for aws/tfstudio (no IAM namespace), gcp/infra-manager (config:v1 surface appended to _methods.json, NOT a regeneration: a full regeneration drifted existing mappings), azure/managementgroups.
- smoke-aws-iam-sweep2 updated: every SCP target now carries FullAWSAccess (real AWS), so detaching a non-last SCP succeeds.

Verified here: IAM pytest set 836 passed; script-style IAM suites exit 0; build_cores/gen_iam_coverage/gen_service_inventory --check clean; UI smokes: iam-ui 34/34, aws pickers 24/24, gcp pickers all, azure pickers 13/13, resource tabs aws 13/13 gcp all azure 8/8, governance all, events all, azure-all-services all, compute-sizes 26/26, sweep 23/23, sweep2 37/37, rolemanager no page errors, iam-pickers-unit 11/11.
Verified on real Mesh (verify-mesh) and real Nano (verify-nano, per-cloud phases; running all three in one process hung once).

Open issues (carry into 4.1.1 notes)
- test_capabilities: 84 pre-existing failures identical on trunk (bedrock, vertex, azure services).
- test_mesh_capacity needs a clean disk/licence environment (compute-sizes edited two assertions); m5 tests need VYOMI_MESH_MODE=0 on a licensed machine.
- iam-hook-e2e.mjs boots /aws-console.html, which trunk does not ship.
- Azure Access-control blade is from Microsoft docs (only the member picker captured); GCP catalog has 192 permissions without stage; AWS action Info text is catalog data, not AWS prose.
- GCP org-policy constraints ~45 curated; ValidatePolicy ~12 codes; Azure PIM has no approval/MFA; assertion signatures not verified.
- Intermittent: test_iam_aws_gaps anonymous S3 public-bucket e2e failed once in an aggregated run.
- ci/v4/v4-release-checklist.yml must be moved into .github/workflows by the owner.

## Rebased on trunk 2026-11-26
Merged origin/v4-on-main (7 commits: release-check fixes, trunk's own tfstudio/infra-manager onboarding). Trunk's versions won for service_map tfstudio/infra-manager, _methods.json and the infra-manager catalog; re-added: azure/managementgroups, backupdr strict_floor 36 (slice gained 5 real permissions), the full GCP catalog generator. Re-verified: IAM pytest 836 passed; script suites 0; UI smokes green (iam-ui 34/34, pickers aws 24/24 gcp azure 13/13, resource tabs, sweep2 37/37, azure-all-services in-scope).
Also merged: v4/azure-all-services-scope (All services lists only in-scope services).
