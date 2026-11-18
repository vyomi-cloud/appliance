# v4/release-checks-sdk-rate

Adds the SDK pass rate to the release-checks report so the portal's "SDK pass rate" and "SDK failure rate" tiles get data.

## What it does
- New job `sdk-checks` in `.github/workflows/release-checks.yml` (matrix aws / gcp / azure, `continue-on-error`): boots the
  PUBLISHED release like `vyomi up` (same as the `cli` job) and runs the native-SDK suites of that cloud from
  `tests/conformance/hourly/suites.json` (kinds `sdk`, `sdk-python`, `sdk-go`, `sdk-java`, target offline) with the existing
  `run_suites.py --cloud <c> --only <ids>`. Same suites and runner as the hourly conformance agent; nothing new to maintain.
- `scripts/release_checks_sdk_rate.py` aggregates the three `checks-sdk-<cloud>/results-offline-<cloud>.json` artifacts.
- The report job appends a "SDK checks (Python, Go, Java)" section to RELEASE-CHECKS.md ending with the one marker line
  `<!-- sdk-pass-rate: passed=P total=T not_run=N rate=X.X -->`. Existing sections are untouched.

## Contract with the portal (portal `app/release_checks.py` `parse_sdk`, `app/metrics_series.py` `apply_release_checks`)
- `passed` / `failed` are checks (PASS/FAIL lines, pytest counts) of the SDK suites; a suite that crashes or prints nothing is 1 failed check.
- `not_run` = suites marked `pending` in suites.json. Not scored.
- `total = passed + failed + not_run` (the portal derives the failing bar as `total - passed - not_run`).
- `rate = passed / (passed + failed) * 100`, one decimal (not_run excluded).
- Nothing ran -> no marker, the tiles stay "collecting". A cloud whose job did not finish is named in the section and not counted. Nothing is estimated or back-filled for earlier releases.

## Notes
- Report job reads the script from its own checkout, else from the checks trunk (`checks_ref`), so a `workflow_run` run (workflow file from `main`) works once this is on `v4-on-main` and `main`.
- Tests: `tests/release/test_release_checks_sdk_rate.py` (aggregation, pending, malformed input, marker parses with the portal's regex copied verbatim, workflow wiring).
- Cost: three extra ubuntu jobs per release (Java/Go compile per suite; each suite has its own timeout in suites.json).
