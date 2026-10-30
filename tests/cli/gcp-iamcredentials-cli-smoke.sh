#!/usr/bin/env bash
# Real `gcloud iam service-accounts sign-blob|sign-jwt` (IAM Credentials API) against Vyomi
# (endpoint override only). ENDPOINT (default http://127.0.0.1:9000), PROJECT.
# One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
CONSOLE="${CONSOLE:-$BASE}"   # the console's own API: the same server offline, the Nano tab on Nano
# Default PROJECT: the appliance's GCP project, discovered the way a user's gcloud
# sees it (Cloud Resource Manager) — the same project the GCP console works in.
if [ -z "${PROJECT:-}" ]; then
  PROJECT=$(CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDRESOURCEMANAGER="$BASE/" CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true \
    CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud projects list --format='value(projectId)' --limit=1 2>/dev/null | head -1)
  [ -n "$PROJECT" ] || { echo "FAIL discover project :: \`gcloud projects list\` against $BASE returned nothing"; exit 1; }
fi
SFX="$(date +%s)"
SA_ID="cli-sa-$SFX"
SA="$SA_ID@$PROJECT.iam.gserviceaccount.com"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_IAM="$BASE/"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_IAMCREDENTIALS="$BASE/"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "== gcloud iam service-accounts (IAM Credentials) against $BASE project=$PROJECT =="

# Service accounts come from the IAM API (a separate service): create one over REST.
out=$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$BASE/v1/projects/$PROJECT/serviceAccounts" -H 'content-type: application/json' -d "{\"accountId\":\"$SA_ID\"}")
[ "$out" = "200" ]
chk $? "IAM: create service account" "$out"

printf 'data to sign %s' "$SFX" > "$TMP/in.txt"
out=$(gcloud iam service-accounts sign-blob "$TMP/in.txt" "$TMP/out.sig" --iam-account="$SA" --project="$PROJECT" --quiet 2>&1)
chk $? "gcloud iam service-accounts sign-blob" "$out"
[ -s "$TMP/out.sig" ] && [ "$(wc -c < "$TMP/out.sig" | tr -d ' ')" = "256" ]   # BSD wc pads
chk $? "signature is 256 bytes (RSA-2048)" "$(wc -c < "$TMP/out.sig" 2>/dev/null)"
echo "$out" | grep -qE '[0-9a-f]{40}'
chk $? "sign-blob reports the 40-hex key id" "$out"

printf '{"iss":"%s","sub":"%s","aud":"https://example.com","exp":9999999999}' "$SA" "$SA" > "$TMP/claims.json"
out=$(gcloud iam service-accounts sign-jwt "$TMP/claims.json" "$TMP/out.jwt" --iam-account="$SA" --project="$PROJECT" --quiet 2>&1)
chk $? "gcloud iam service-accounts sign-jwt" "$out"
[ "$(tr -cd '.' < "$TMP/out.jwt" | wc -c | tr -d ' ')" = "2" ]
chk $? "signed JWT has three dot-separated parts" "$(cat "$TMP/out.jwt" 2>/dev/null | head -c 80)"
cut -d. -f2 < "$TMP/out.jwt" | tr '_-' '/+' | { read -r p; echo "$p$(printf '=%.0s' 1 2 3)" | base64 -d 2>/dev/null; } | grep -q '"aud":"https://example.com"'
chk $? "JWT payload carries the claims" "$(cut -d. -f2 < "$TMP/out.jwt")"

out=$(gcloud iam service-accounts sign-blob "$TMP/in.txt" "$TMP/out2.sig" --iam-account="ghost-$SFX@$PROJECT.iam.gserviceaccount.com" --project="$PROJECT" --quiet 2>&1)
[ $? -ne 0 ] && echo "$out" | grep -qi "permission\|denied\|403"
chk $? "unknown service account is rejected (PERMISSION_DENIED)" "$out"

out=$(curl -s "$CONSOLE/api/gcp/iamcredentials/credentials")
echo "$out" | grep -q "$SA" && echo "$out" | grep -q '"Signed blob"' && echo "$out" | grep -q '"Signed JWT"'
chk $? "console log shows the signed blob + JWT issued by the CLI" "$(echo "$out" | head -c 160)"

curl -s -o /dev/null -XDELETE "$BASE/v1/projects/$PROJECT/serviceAccounts/$SA"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
