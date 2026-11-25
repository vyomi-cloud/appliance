# v4/release-checks-fix

Fixes the failing post-release checks of v4.1.0 (Release checks report + v4 release checklist).

## Causes and fixes
- `tunnel-version-sync`: `packaging/brew/vyomi-tunnel.rb` served 1.3.2 while 1.4.0 is on npm and in the tap; formula now 1.4.0 with the real sha256.
- IAM checks (`iam-faithful`, `iam-enforcement`): the CI job has no pytest; `tests/release/v4_checklist.py` installs it when missing.
- `nano-cli`: `tests/release/nano_cli_check.mjs` opened the removed legacy `/<cloud>-console.html`; it opens `/v4/<cloud>/` (nano-boot.js still sets the "backend ready" banner there).
- `nano-ui` (aws/gcp/azure): 96 suites in `tests/conformance/hourly/suites.json` ran scripts deleted with the legacy console (0218b1f16, incl. `ui_crawler.mjs`). They are marked `pending` with the reason (visible in every run, never counted as pass), not deleted.

## Open
- Retarget or retire the 96 pending suites against the v4 consoles (owner decision); v4 replacements exist (`wasm/ui-tests/*v4*`, `aws-bd`, `gcp-bd`, `azure-bd`).
- `ci.yml` `nano-kernel-once` (deleted test file) and `conformance` (81.5% < 85%, same on the pre-release trunk): need a `.github/workflows` edit, which the integrator token cannot push.
- nano_cli_check not run end to end locally (no Chromium/ws here); verified by the CI run.
