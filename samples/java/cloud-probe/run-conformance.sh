#!/usr/bin/env bash
# Cross-cloud native-SDK conformance run.
#
# Exercises the cloud-probe's SEPARATE per-service endpoints for each cloud —
# they are intentionally NOT merged into one aggregate, so each service passes
# or fails independently and you can see exactly which surface broke:
#
#     /probe/{cloud}    object store + NoSQL  (S3/GCS/Blob, DynamoDB/Firestore/Cosmos)
#     /queue/{cloud}    SQS / Pub/Sub / Storage Queue
#     /secret/{cloud}   Secrets Manager / Secret Manager / Key Vault Secrets
#     /kms/{cloud}      KMS / Cloud KMS / Key Vault Keys
#
# Usage:
#   1) Start the probe pointed at the appliance (separate terminal / container):
#        export CLOUDPROBE_ENDPOINT=http://<appliance>:9000      # sim (HTTP)
#        export CLOUDPROBE_CADDY_HOST=<appliance>:9443           # HTTPS (Cosmos/GCP-HttpJson/KeyVault)
#        export FIRESTORE_EMULATOR_HOST=<appliance>:8080
#        export PUBSUB_EMULATOR_HOST=<appliance>:8085
#        java -jar target/cloud-probe.jar
#   2) Run this harness against the probe:
#        ./run-conformance.sh                 # defaults to http://localhost:8080
#        ./run-conformance.sh http://host:8080
#
# Exit code 0 = every endpoint green; non-zero = at least one failed.
set -uo pipefail

BASE="${1:-${PROBE_BASE:-http://localhost:8080}}"
CLOUDS=(aws gcp azure)
SERVICES=(probe queue secret kms)
# EC2 (compute) + RDS (managed DB) — AWS-only for now; the cross-cloud
# equivalents (GCE/CloudSQL, Azure VM/SQL) aren't wired into the probe yet.
AWS_ONLY_SERVICES=(compute rds)
HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1

pass=0; fail=0; FAILURES=()

hit() {
  local svc="$1" cloud="$2" url="${BASE}/${1}/${2}"
  local body code ok="false"
  body=$(curl -s -w $'\n%{http_code}' "$url" 2>/dev/null)
  code=$(printf '%s' "$body" | tail -n1)
  body=$(printf '%s' "$body" | sed '$d')
  if [ "$HAVE_JQ" = 1 ]; then
    ok=$(printf '%s' "$body" | jq -r '.ok // false' 2>/dev/null)
  else
    printf '%s' "$body" | grep -q '"ok"[: ]*true' && ok=true
  fi
  if [ "$ok" = "true" ]; then
    printf "  %-7s %-6s  PASS (HTTP %s)\n" "$svc" "$cloud" "$code"; pass=$((pass+1))
  else
    printf "  %-7s %-6s  FAIL (HTTP %s)\n" "$svc" "$cloud" "$code"; fail=$((fail+1))
    local detail
    if [ "$HAVE_JQ" = 1 ]; then
      detail=$(printf '%s' "$body" | jq -r '(.steps // [])[] | select(.ok==false) | "      x \(.step): \(.detail)"' 2>/dev/null)
      [ -z "$detail" ] && detail="      $(printf '%s' "$body" | jq -c . 2>/dev/null | cut -c1-400)"
    else
      detail="      $(printf '%s' "$body" | cut -c1-400)"
    fi
    FAILURES+=("${svc}/${cloud}"$'\n'"${detail}")
  fi
}

echo "cloud-probe conformance @ ${BASE}"
echo "healthz: $(curl -s "${BASE}/healthz" 2>/dev/null || echo UNREACHABLE)"
echo
for svc in "${SERVICES[@]}"; do
  for cloud in "${CLOUDS[@]}"; do hit "$svc" "$cloud"; done
done
for svc in "${AWS_ONLY_SERVICES[@]}"; do hit "$svc" aws; done
echo
echo "=== ${pass} passed, ${fail} failed ==="
if [ "$fail" -gt 0 ]; then
  echo; echo "Failures (failing steps):"
  for f in "${FAILURES[@]}"; do echo "$f"; done
  exit 1
fi
