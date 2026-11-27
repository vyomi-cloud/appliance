# v4/release-fixes-4-1-2

Fixes for the failures in the v4.1.1 release checks (`release/v4.1.1:RELEASE-CHECKS.md`).

## Nano CLI: GCP Cloud Storage (gcloud storage ...) 0/6 and console<->CLI check
Cause: `core/aws_wire_router.py` imports `core.gcp_orgpolicy_core` lazily inside a `try` and the `except _orgp.Violation` clause names the import. In Nano the module was not in the core lists of `wasm/nano-boot.js` / `wasm/relay/relay-shared-worker.js`, so the import failed and the except clause raised `UnboundLocalError: cannot access local variable '_orgp'`: every `gcp-gcs` call returned 500.
- the import no longer sits in the `try` that names it (`_orgp = None` when the module is not shipped);
- `gcp_orgpolicy_core`, `aws_governance_core`, `azure_mgmt_groups_core` added to both Nano lists (Budgets / Resource Groups / management groups were silently disabled in Nano); `aws_eks_core`, `bedrock_bda_core`, `bedrock_build_core` added to the relay list;
- `tests/conformance/test_nano_core_lists.py` fails for any lazily imported `*_core` missing from the lists (the static import-closure check cannot see function-level imports).
