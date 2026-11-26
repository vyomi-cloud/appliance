# v4/iam-catalog-complete

Closes the GCP IAM catalog gap from PUBLIC sources only (no logins). Based on `origin/v4/iam-pickers-integ`.

## Sources (generator: `scripts/gen_iam_catalog.py gcp`, extended, not hand-edited)
- Predefined roles reference: every page listed on https://cloud.google.com/iam/docs/roles-permissions (359 pages; was 40 hand-listed slugs; `GCP_SLUGS` stays as a must-be-subset floor).
- Permission support levels: https://cloud.google.com/iam/docs/custom-roles-permissions-support (same data as `permissions:queryTestablePermissions` `customRolesSupportLevel`; absent there == SUPPORTED).
- `VYOMI_IAM_SRC_CACHE=<dir>` caches fetched pages so re-runs/review need no network.

## Shape
- `permissions[p]` = `{}` or `{"stage": "SUPPORTED"|"TESTING"|"NOT_SUPPORTED"}`. Console labels: Supported / Testing / Not applicable. A permission Google has not yet put in the list has no `stage` (console shows Supported, the API default).
- Role descriptions: parser fixed (plain `role-description` span, multi-paragraph); each role lives on exactly one shard.
- `core/iam_catalog/gcp/_index.json`: shard list + counts. Console `catalog.js` reads it (falls back to its built-in list), fetches shards with concurrency 12, maps `stage` to status.
- Shards are per roles-reference page (largest ~1.4 MB: jobfunctions). Permissions only in the support list and on no page are homed on the shard owning their service prefix (159).

## Counts (before -> after)
| | before | after |
|---|---|---|
| shards | 39 | 363 (+`_index`) |
| distinct permissions | 8,082 | 14,543 |
| roles | 477 | 1,811 |
| roles with description | 124 | 1,806 |
| permissions with stage | 0 | 14,351 (SUPPORTED 13,886, TESTING 416, NOT_SUPPORTED 49; 192 unlisted by Google) |
| catalog size | 3.0 MB | 10 MB (wasm vendored copy 13 MB, lazy, not fetched at boot) |

`service_map.json`: backupdr `strict_floor` 37 -> 36 (its slice gained 5 real permissions, reach 37.0 -> 36.5; no mapping regressed). Coverage doc/json regenerated.

## AWS: skipped (documented)
The Service Reference JSON (what `gen_aws` reads) has no per-action description field. Descriptions exist only in the HTML Service Authorization Reference, AWS-copyrighted documentation with no machine-readable licence for redistribution; scraping and vendoring it is not safe. `test_aws_reference_has_no_descriptions` pins the action shape so a future JSON field is noticed. Azure untouched.

## Verification
- `tests/conformance/test_iam_gcp_catalog_complete.py` (counts, shape, stages, index, shard size, AWS note); full pytest-style `test_iam_*.py`: 774 passed (8 pre-existing script-style files collect no tests).
- `build_cores.py --check` and `gen_iam_coverage.py --check` green.
- Console: syntax-checked only (`node --check` as module); `smoke-gcp-iam-pickers.mjs` not run (no consoles/node_modules here).
