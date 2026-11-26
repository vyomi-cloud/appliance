# v4/iam-governance

Base: `origin/v4/iam-pickers-integ`. Real, engine-backed org-level governance for all three clouds (see "Governance" in `IAM-ENGINE-CONTRACT.md`).

## Shipped
- AWS: Organizations tree + SCP/RCP attach/detach/effective/check (`core/iam_governance.py`), FullAWSAccess default attachments, management-account opt-in, S3 Block Public Access (account + bucket) enforced in `aws_eval`. Console: IAM > Organization governance, S3 > Public access overview.
- GCP: Org Policy v2 on organizations / folders / projects (`core/gcp_orgpolicy_core.py`, ~45-constraint catalog, inheritance, dry run, `:check`), bucket-create enforcement on Mesh and Nano. Console: IAM & Admin > Resource hierarchy (deny policies and PAB link to their existing pages).
- Azure: management groups on the native ARM wire (`core/azure_mgmt_groups_core.py`), MG-scope role + policy assignments inherited through `azure_eval`, ARM policy evaluation includes MG-scope assignments. Console: Management groups service.
- Nano: cores vendored; `iam_state_nano.azure_state` now reads wire-created role assignments (MG scope).

## Tests
`tests/conformance/test_iam_governance_{aws,gcp,azure}.py`, `consoles/tests/smoke-iam-governance.mjs` (save-payload assertions + screenshots; needs `consoles/dev_server.py`), `consoles/tests/nano-governance-pyodide.mjs` (real Pyodide). `test_organizations_core.py` adapted: a new OU/account carries FullAWSAccess, an allow-list is built by detaching it (as in AWS).

## Not done / honest gaps
Curated (not full) GCP constraint catalog; conditional org-policy rules not evaluated; per-member-account live enforcement (one account); no AWS `DescribeEffectivePolicy`; the Nano path was verified in Pyodide (Node) and not in a full browser run.
