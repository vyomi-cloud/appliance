# v4/iam-check-fix

Owner: Claude session - Started: 2026-11-26 - Base: origin/v4-on-main (6ded284d4) - Status: in review

## Purpose
The v4 release checklist `iam-faithful` check failed (1 failed, 105 passed, 4 skipped) on run 45675982423 for all clouds.
The failing test was `tests/conformance/test_service_inventory.py::test_inventory_is_current`: `wasm/service-inventory.json`
was stale after the Infrastructure Studio (aws `tfstudio`) and Infrastructure Manager (gcp `infra-manager`) console entries
landed. Not a CI-environment issue; reproduces locally.

## Fix
Regenerated with `python3 scripts/gen_service_inventory.py` (88 services; aws 27, gcp 30, azure 31). Data-only change.
