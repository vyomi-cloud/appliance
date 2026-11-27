# v4/release-checks-total

Why: the portal's "Checks run in the latest release" showed 277 for v4.1.1. `app/release_checks.py` counts only `| ✅ |` / `| ❌ |` rows of RELEASE-CHECKS.md (packages 110 + CLI 84 + Nano CLI 83), but the report also states 89 Nano console UI suites and 1478 native-SDK checks: 1844 in total (1826 passed, 18 failed).

- `scripts/release_checks_total.py` prints `<!-- checks-total: passed= failed= total= rows= ui_suites= sdk= -->` from the finished report; `release-checks.yml` appends it after the SDK section. Verified on the v4.1.1 report: passed=1826 failed=18 total=1844 rows=277 ui_suites=89 sdk=1478.
- `tests/release/test_release_checks_total.py`.
- Units differ (rows, suites, SDK checks); the marker carries the breakdown so the portal can show "1,844 checks" with the split.
- Portal repo change still needed (not reachable from here): in `app/release_checks.py` `_compute_latest`, prefer the marker (`<!--\s*checks-total:\s*(.*?)\s*-->`, same key=value parse as `_SDK_RE`) and fall back to the row count for older reports. Reports written before this lands have no marker, so the tile changes from the next release.
