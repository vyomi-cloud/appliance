# v4 crawl scope matrix (gap map)

Required scope (owner, 2026-11-12): CLI<->UI, SDK<->UI, API<->UI bi-directional checks, plus UI: all sections,
subsections, clicks, toggles, dropdowns, form validations and every broken component behaviour, for all three clouds.
Status: **OK** = a suite asserts it (both targets noted), **PARTIAL** = covers some services/one direction, **MISSING** = nothing asserts it.
Missing/partial cells are registered as `pending` suites in `tests/conformance/hourly/suites.json` (reported every run, not counted as failures).

| Dimension | AWS | GCP | Azure |
|---|---|---|---|
| CLI<->UI | PARTIAL: `cli_crosscheck.py` (CLI side only, release); no UI-side assert. **`bidi-aws-cli-ui` pending** | PARTIAL: same + `nightly-gcp-compute-vertex-bidi` (nano). **`bidi-gcp-cli-ui` pending** | PARTIAL: `cli_crosscheck.py` only. **`bidi-azure-cli-ui` pending** |
| SDK<->UI | PARTIAL: `offline-ui-sdk-roundtrip`, `nightly-aws-v4-roundtrip` (core types) | PARTIAL: `nightly-gcp-roundtrip`, `nightly-gcp-v4-roundtrip` | PARTIAL: `offline-ui-azure-v4-bidirectional` (VMs, offline; Mesh harness `wasm/ui-tests/azure-mesh/vm-bidirectional.mjs`). **`bidi-azure-sdk-ui` pending** for the other services |
| API<->UI | PARTIAL: `nano-ui-aws-api`, roundtrip above | PARTIAL: roundtrips above | PARTIAL: vm-bidirectional only. **`bidi-azure-api-ui` pending** |
| Sections / subsections (rail + every tab) | OK: crawler walks every rail service + every detail tab (`nano-ui-crawl`, hourly crawl, `*-tabs` suites) | OK (same) | OK (same) |
| Clicks (buttons / row actions) | PARTIAL: crawler clicks rail, tabs, resource links, create defaults; row actions + toolbar buttons are not clicked generically (per-service suites only). **`crawl-<cloud>-ui` pending** | PARTIAL (same) | PARTIAL (same) |
| Toggles / switches / checkboxes | MISSING: crawler never flips a toggle | MISSING | MISSING |
| Dropdowns / selects | MISSING: no generic open-and-pick | MISSING | MISSING |
| Form validation | MISSING in UI (API-level only): `gcp-validation.mjs` (nightly) covers GCP wire errors | PARTIAL: `gcp-validation.mjs` (API), no UI-side | MISSING. **`validation-<cloud>-ui` pending** for all three |
| Broken-component detection | OK: crawler findings HTTP_5XX/404, PAGE_ERROR, PLACEHOLDER_CELL, STATIC_TAB/DETAIL, DEAD_TAB, CREATE_NO_ROW, SAVINGS_NOT_UPDATED, CRAWL_ERROR | OK | OK |

Counts (3 clouds x 9 dimensions = 27 cells): OK 9, PARTIAL 11, MISSING 7.

## What the crawler really does today (`tests/conformance/hourly/ui_crawler.mjs`)
Rail service -> every detail tab -> grid cells; opens resource links; with CREATE=1 submits the create form with default
values and checks the new row and the savings metric. It does NOT: flip toggles, open dropdowns, enter invalid input,
click toolbar/row actions generically, or compare UI to CLI/SDK/API output.

## Known-issue rows
CI-5 (toggles/dropdowns/form-validation crawl) and CI-6 (CLI/SDK/API<->UI bidi for every service, all clouds) in
`V4.0.0-KNOWN-ISSUES.md`; the hourly known-issues runner works them (build the generic crawler step, then the per-cloud bidi adapters).
