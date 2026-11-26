# v4/suites-retarget-azure

Owner: Claude session - Started: 2026-11-26 - Base: origin/v4-on-main - Status: pushed, for review

## Purpose
The Azure suites in `tests/conformance/hourly/suites.json` marked `pending` drove the removed v3 console. Each is retargeted to the v4
console (`/v4/azure/`), covered by an existing suite, or retired with a specific reason.

The harness `wasm/ui-tests/validate-azure-v4-actions.mjs` now has three substrates: genuine Nano (default), `SIM_URL=<appliance>` (offline, the
same proxy pattern as offline-ui-azure-v4-bidirectional) and `DEV_BASE=<url>` (consoles/dev_server.py inner loop). It also waits for the Nano engine to
answer before starting (the first fetch after the service-worker reload used to throw "Failed to fetch" and failed the whole run). New drivers in
`wasm/ui-tests/azure-actions/`: resourcegroups, apim, cognitiveservices, monitor, sweepA, and shell.mjs (home, tabs, metrics, tags).

## Per-suite result (A retarget, B covered, C retired)
Run evidence: genuine Nano, headless system Chrome, `ONLY=<ids> NANO_DIR=$PWD/wasm node wasm/ui-tests/validate-azure-v4-actions.mjs`, 2026-11-26.

| Suite | Class | Evidence / reason |
|---|---|---|
| nano-ui-azure-dns | A | ONLY=dns: 6/6 PASS in Nano |
| nano-ui-azure-nsg-rules | A | ONLY=nsgs: all PASS in Nano (add/delete rule, API<->UI, delete NSG) |
| nano-ui-azure-operationalinsights | A | ONLY=loganalytics: all PASS in Nano |
| nano-ui-azure-appconfiguration | A | ONLY=appconfiguration: all PASS in Nano |
| nano-ui-azure-storage-console | A | ONLY=storage: all PASS in Nano (containers, blob upload, API<->UI, delete) |
| nano-ui-azure-resource-group-detail | A | ONLY=resourcegroups: 11/11 PASS in Nano (detail, location, tags, resources, UI delete) |
| nano-ui-azure-rg-nav | A | ONLY=home,resourcegroups: PASS in Nano |
| nano-ui-azure-home | A | ONLY=home: PASS in Nano (tiles, no undefined, no 404/5xx) |
| nano-ui-azure-tabs | A | ONLY=tabs: PASS in Nano (kv 24, storage 41, vnet 28, nsg 18 tabs, none blank; honest Not-simulated panels are NOTEd) |
| nano-ui-azure-metrics | A | ONLY=metrics: PASS in Nano (measured ActivityOperations A=4 vs B=1, idle window empty, Metrics tab opens) |
| nano-sweepA-azure | A | ONLY=sweepA: PASS in Nano (SQL password never echoed, RG delete destroys vault data, APIM keys) |
| nano-ui-azure-monitor | A | ONLY=monitor: PASS in Nano (action group + metric alert API->UI, UI delete rule -> ARM) |
| nano-ui-azure-apim-appinsights | A | ONLY=apim: PASS in Nano (logger API->UI, UI add -> ARM, delete service) |
| nano-ui-azure-tags-tab | A | ONLY=tags: PASS in Nano (vnet, Log Analytics, App Configuration: UI Apply -> ARM tags, shown again) |
| nano-ui-azure-keyvault-tabs | A, pending | ONLY=keyvaults in Nano: 1 FAIL, a secret deleted over the API is still listed in the v4 secrets list (console bug) |
| nano-ui-azure-cognitiveservices | A, pending | all PASS on dev_server; in Nano the Deploy-model dialog has no gpt-4o option, UI->API leg fails |
| offline-ui-azure-metrics / -rg-nav / -resource-group-detail | A, pending | cmd now SIM_URL mode; PASS with dev_server as the simulator only, not run on a real offline appliance |
| offline-ui-azure-apim-appinsights | A, pending | SIM_URL cmd; not rerun against a simulator |
| nano-ui-azure-app | pending | no containerapps driver yet (offline covered by offline-ui-azure-v4-bidirectional) |
| offline-ui-azure-flat-create | B | covered by offline-ui-azure-v4-bidirectional |
| nano-ui-azure-flat-create, -nsg-roledef-create | B/C | v3 flat blade gone; NSG covered offline by bidirectional and by nano-ui-azure-nsg-rules; role defs in IAM |
| nano-ui-azure-dp, -dp-detail | B | covered by nano-ui-azure-storage-console; no separate data-plane pages in v4 |
| bidi-azure-cli-ui, bidi-azure-api-ui | B | covered by offline-ui-azure-v4-bidirectional (+ the nano-ui-azure-* suites) |
| nano-ui-azure-savings, -rail-last, nano-ui-reload-backend | C | v3-only behaviour (cost_savings counter, #rail banner, Pyodide reload race) |
| nano-post-create-azure-vm-ssh | C | needs tunnel relay + VM compute; offline twin exists |
| bidi-azure-sdk-ui, crawl-azure-ui, validation-azure-ui | C | placeholders (cmd true) with no v4 implementation |

Counts (35 suites): 14 A now passing and live, 4 A retargeted but still pending (keyvault-tabs, cognitiveservices + 4 offline = 6 entries), 1 pending, 7 B, 8 C-ish retired.

## Known gaps found
- v4 key vault secrets list keeps an API-deleted secret (keyvaults driver).
- Existing `vms` and vnets "Add subnet" sections of the same harness fail in Nano (not in scope here, untouched).

## Open issues
- Offline variants need one run on a real offline appliance before `pending` is dropped.

## Testing
See the table; node --check on the harness; `tests/release/v4_checklist.py --cloud azure` suites-json-valid PASS.
