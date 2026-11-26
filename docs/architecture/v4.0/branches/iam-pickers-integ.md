# v4/iam-pickers-integ

Integration of the faithful-IAM UI/backend wave, on top of origin/v4-on-main. Not merged to trunk (needs owner go).

Merged branches: v4/aws-iam-pickers (incl. v4/aws-ux-refresh), v4/gcp-iam-pickers, v4/azure-iam-pickers, v4/iam-integ-fixes, v4/iam-resource-tabs, v4/iam-simulate-analyze. See each branch's own doc.

Verified on this branch: IAM pytest set 770 passed; all IAM UI smokes pass (see PR text); build_cores/gen_iam_coverage --check clean.

Open issues:
- tests/conformance/test_service_inventory.py::test_inventory_is_current fails on plain trunk too (wasm/service-inventory.json lacks a tfstudio entry).
- Azure blade built from Microsoft docs, only the member picker from a real capture.
- GCP catalog: 8082 of 14524 permissions, no per-permission status; AWS Info text is catalog data, not AWS prose.
- ValidatePolicy emits 7 issue codes; analyzeIamPolicy allow-only; Azure eligibility empty (no PIM store).
- Azure capability entries (azure.*.iam) not yet checked against test_capabilities.py.
