# Branch v4/iam-onboard-tfstudio

The `iam-faithful` release check failed on `test_every_inventory_service_is_in_the_service_map`: `aws/tfstudio` and `gcp/infra-manager` were in `wasm/service-inventory.json` with no IAM onboarding.

- `core/iam_catalog/service_map.json`: both onboarded as `catalog: none` with a reason. `tfstudio` is a client-side Terraform workspace (calls are authorised under the target service's actions). `infra-manager` first went in as `none`, but the GCP gate (`test_iam_gcp_coverage`) requires a real slice, so it is onboarded properly: `core/iam_catalog/gcp/config.json` (generated from the roles-permissions page via `gen_iam_catalog.py`, slug `config`), `config:v1` added to `scripts/gen_iam_gcp_methods.py` (+45 methods, none removed), mapped as `catalog [config], apis [config]`. It is IAM-enforced.
- `wasm/iam-coverage.json`, `docs/architecture/v4.0/IAM-COVERAGE.md`: regenerated with `scripts/gen_iam_coverage.py --bump-floors`.

Vendored copies under `wasm/core/` regenerated with `wasm/build_cores.py`.

Verified: global + GCP IAM pytest groups 262 passed / 6 skipped; `gen_iam_coverage.py --check` and `wasm/build_cores.py --check` pass.

Open: none for IAM; `aws/tfstudio` stays `catalog: none` (client-side workspace, no actions of its own).
