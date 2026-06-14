#!/usr/bin/env bash
# CI gate — fail if pass-rate falls below the threshold for ANY provider.
# Reads tests/conformance/console_actions/REPORT.md (auto-written by the
# pytest run). Set CONFORMANCE_MIN_PCT to override (defaults below).
#
# Thresholds ratchet UP only — when a session lands fixes, bump the floor
# in this file via a commit. Never reduce. Goal: monotonic march to 100%.

set -euo pipefail

REPORT="${1:-tests/conformance/console_actions/REPORT.md}"

# Current floor — bumped each time a session lands.
# Last bumped: 2026-06-14 — session 7 (env-skip Pattern C for disk/LXD
# gates, S3 ?force=1 + sweep, GCP cloudsql idempotent + payload key
# match + project defaults + LRO unwrap, JSON parse guards). All three
# providers now at 100% — gate is monotonic from here.
AWS_MIN="${AWS_MIN:-100}"     # current LIVE: 100.0% (session 7)
GCP_MIN="${GCP_MIN:-100}"     # current LIVE: 100.0% (session 7)
AZURE_MIN="${AZURE_MIN:-100}" # current LIVE: 100.0%

if [ ! -f "$REPORT" ]; then
  echo "✗ REPORT.md not found at $REPORT — pytest didn't write it"
  exit 1
fi

# Parse the per-provider pass-rate from the Markdown table
get_rate() {
  local prov="$1"
  grep -E "^\| (✓|✗) ${prov} \|" "$REPORT" | awk -F'|' '{print $5}' | tr -d ' %'
}

check() {
  local prov="$1" min="$2"
  local rate
  rate=$(get_rate "$prov")
  if [ -z "$rate" ]; then
    echo "✗ No rate found for $prov in $REPORT"
    return 1
  fi
  local rate_int
  rate_int=${rate%.*}
  if [ "$rate_int" -lt "$min" ]; then
    echo "✗ $prov $rate% < floor $min%"
    return 1
  fi
  echo "✓ $prov $rate% (floor $min%)"
}

fail=0
check aws   "$AWS_MIN"   || fail=1
check gcp   "$GCP_MIN"   || fail=1
check azure "$AZURE_MIN" || fail=1

if [ "$fail" -eq 1 ]; then
  echo ""
  echo "Gate failed. To raise (good — services improved):"
  echo "  Edit tests/conformance/console_actions/check_pass_rate.sh and bump the floors."
  echo "To lower (bad — regression):"
  echo "  Find the regression and fix it instead."
  exit 1
fi

echo ""
echo "All provider gates passed."
