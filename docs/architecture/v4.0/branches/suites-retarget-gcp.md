# v4/suites-retarget-gcp

Owner: Claude session (suites retarget, GCP) - Started: 2026-11-26 - Base: origin/v4-on-main (0b97c20e0) - Status: in progress, pushed

## Purpose
`tests/conformance/hourly/suites.json` carried about 35 GCP suites marked `pending` because their scripts drove the decommissioned
v3 console (`wasm/gcp-console.html`, `/console/gcp`, `/api/gcp/*`) and were deleted with it (0218b1f16, rule 12). Each was decided
on evidence as A retarget, B replaced by an existing passing v4 suite, or C retired (behaviour gone) or kept pending for a real gap or
missing infrastructure.

One new script replaces the deleted per-feature ones: `wasm/ui-tests/validate-gcp-v4-intents.mjs`. It boots genuine Nano
(`tests/conformance/nightly/lib/nano-gcp.mjs`: wasm bundle, service worker, in-browser engines), drives the v4 console at `/v4/gcp/`
in Playwright and the native REST wire (`/_wire`, what gcloud and the SDKs call). `CHECKS=<group,group>` selects what a suite runs.

## Decisions
| Suite id | Class | Evidence | Verification |
|---|---|---|---|
| nano-ui-gcp-tabs | A | Cloud SQL users and databases sub-resources round-trip on the native sqladmin wire (group `sqlsubs`) | run: PASS |
| nano-ui-gcp-grid-defaults | A | group `grid`: 7 services created with default bodies, v4 list row has no undefined/null/[object Object]/NaN and more real cells than em-dashes (v4 renders empty optionals as an em dash like the real console) | run: PASS |
| nano-ui-gcp-pubsub-grid | A | `grid` limited to the Pub/Sub topic row (`GRID_ONLY=pubsub`) | run: PASS |
| nano-ui-gcp-pubsub-subscriptions | A | group `subscriptions`: project subscriptions list 200, created sub listed natively and on the v4 Subscriptions page | run: PASS |
| nano-ui-gcp-firestore-usage | A | group `firestore`: documents list served, written document listed | run: PASS |
| nano-ui-gcp-scheduler-pubsub | A | group `schedpubsub`: pubsubTarget job `:run` delivers data and attributes, pulled from a subscription | run: PASS |
| nano-ui-gcp-cloudscheduler | A | group `scheduler`: create, v4 list, pause, resume, run, delete | run: PASS |
| nano-ui-gcp-container | A | group `gke`: create, v4 list, RUNNING, node pool, setSize 5, delete | run: PASS |
| nano-ui-gcp-redis | A | group `redis`: create, v4 list, READY, resize to 5 GB, delete | run: PASS |
| nano-ui-gcp-monitoring | A | group `alerting`: alert policy create, v4 list, condition/combiner/documentation, disable/enable, delete | run: PASS |
| nano-ui-gcp-apigw-monitoring-tabs | A | groups `apigw,alerting`: API config added natively shows on the v4 API detail page, config carries the real service config | run: PASS |
| nano-ui-gcp-artifactregistry | A | group `artifactregistry`: create, v4 list, native format, delete | run: PASS |
| nano-ui-gcp-iamcredentials | A | group `iamcreds`: generateAccessToken / generateIdToken / signBlob real-shaped, unknown SA refused, SA listed in v4 | run: PASS |
| nightly-gcp-roundtrip | B | replaced by `nightly-gcp-v4-roundtrip` | roundtrip run, see below |
| nano-ui-gcp-eventarc-delivery | B | `nightly-gcp-v4-roundtrip` eventarc: UI CRUD, trigger detail, object upload fires trigger, delivery listed | roundtrip run |
| nano-ui-gcp-create-defaults | B | roundtrip step A (every service created through its real v4 form) + `grid` | roundtrip + grid run |
| bidi-gcp-cli-ui / -sdk-ui / -api-ui | B | UI <-> native wire both ways = `nightly-gcp-v4-roundtrip` and `nightly-gcp-compute-vertex-bidi` (CLI, SDK and API share that wire) | roundtrip run |
| validation-gcp-ui | B | wire validation = `nightly-gcp-validation` (live); form creation = roundtrip step A | not re-run here |
| offline-ui-gcp-* (pubsub-subscriptions, activity-detail, grid-defaults, pubsub-grid, create-defaults, properties) | C | the offline appliance serves no v4 console: no `/v4` or `/console/gcp` route in `server.py` or `routes/`; the 4.0 UI target is Nano (`wasm/v4`), the same intents run in the matching `nano-ui-gcp-*` suites | grep |
| nano-ui-gcp-metrics-counts | C | v3 detail-tab Metrics count fetchers do not exist in v4; related-collection views asserted by roundtrip + grid | grep |
| nano-ui-gcp-properties | C | the v3 generic Properties editor (custom properties, Last modified) has no v4 component under `consoles/src/gcp` | grep |
| nano-ui-gcp-activity-detail | kept pending (real gap) | the v4 Home > Activity feed reads `/api/cloudsim/events` but resources created through `/_wire` record no events (probe: empty feed after a topic + network create). `CHECKS=events` encodes the intent and currently FAILS; it is opt-in and not in the default groups | probe |
| nano-post-create-gcp-gce-ssh | kept pending (infra) | needs a real vyomi-tunnel >= 1.1.0 and the in-browser VM host; not ported to the v4 VM Connect UI | none |
| nightly-gcp-tunnel-recovery | kept pending (infra) | needs a Mesh Codespace + `NIGHTLY_CODESPACES_PAT` | none |
| nano-ui-gateway-eventarc-portal-e2e | kept pending (infra) | live v4 script, needs a portal + signed-in cookie (:8099 is off limits) | none |
| nano-core-hosted-gw-egress-live | kept pending (infra) | needs `wrangler dev`; wrangler not installed | none |
| crawl-gcp-ui | kept pending | placeholder; the generic crawler is cloud=all `nano-ui-crawl`, itself pending until `ui_crawler.mjs` is rebuilt for v4 | none |

## Open issues
- v4 GCP Activity feed is empty for wire-created resources (see nano-ui-gcp-activity-detail). A product fix, not a test change.
- `crawl-*-ui` placeholders across clouds depend on rebuilding `ui_crawler.mjs` for the v4 consoles.

## Testing
Run from a clean checkout with Playwright from another tree: `NODE_PATH=<dir with playwright> PLAYWRIGHT_BROWSERS_PATH=<browsers>`
then `NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-gcp-v4-intents.mjs` (all default groups), or
`python3 tests/conformance/hourly/run_suites.py --target nano --only <ids>`.
