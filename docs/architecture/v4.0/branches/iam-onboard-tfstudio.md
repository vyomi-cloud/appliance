# Branch v4/iam-onboard-tfstudio

The `iam-faithful` release check failed on `test_every_inventory_service_is_in_the_service_map`: `aws/tfstudio` and `gcp/infra-manager` were in `wasm/service-inventory.json` with no IAM onboarding.

- `core/iam_catalog/service_map.json`: both onboarded as `catalog: none` with a reason. `tfstudio` is a client-side Terraform workspace (calls are authorised under the target service's actions). `infra-manager` has no permission slice yet, so it is **not IAM-enforced** until one is generated.
- `wasm/iam-coverage.json`, `docs/architecture/v4.0/IAM-COVERAGE.md`: regenerated with `scripts/gen_iam_coverage.py --bump-floors`.

Verified: global IAM pytest group 106 passed / 4 skipped; `gen_iam_coverage.py --check` and `wasm/build_cores.py --check` pass.

Open: generate a `config` permission slice for Infrastructure Manager and switch it to an enforced entry.
