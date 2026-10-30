#!/usr/bin/env bash
# Real `gcloud artifacts` against Vyomi's Artifact Registry (artifactregistry/v1),
# only the endpoint overridden. One [PASS]/[FAIL] line per check; non-zero on failure.
#   ENDPOINT=http://localhost:9000 bash tests/cli/gcp-artifactregistry-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
# Default PROJECT: the appliance's GCP project, discovered the way a user's gcloud
# sees it (Cloud Resource Manager) — the same project the GCP console works in.
if [ -z "${PROJECT:-}" ]; then
  PROJECT=$(CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDRESOURCEMANAGER="$BASE/" CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true \
    CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud projects list --format='value(projectId)' --limit=1 2>/dev/null | head -1)
  [ -n "$PROJECT" ] || { echo "FAIL discover project :: \`gcloud projects list\` against $BASE returned nothing"; exit 1; }
fi
LOC="us-central1"
REPO="cli-ar-$(date +%s)"
fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

gcloud config set auth/disable_credentials true >/dev/null 2>&1
gcloud config set core/project "$PROJECT" >/dev/null 2>&1
gcloud config set core/disable_prompts true >/dev/null 2>&1
export CLOUDSDK_API_ENDPOINT_OVERRIDES_ARTIFACTREGISTRY="$BASE/"

out=$(gcloud artifacts repositories create "$REPO" --repository-format=docker --location=$LOC \
      --description="cli smoke" --project="$PROJECT" 2>&1); chk $? "gcloud artifacts repositories create" "$out"
out=$(gcloud artifacts repositories create "$REPO" --repository-format=docker --location=$LOC --project="$PROJECT" 2>&1)
echo "$out" | grep -qi "already exists"; chk $? "duplicate create fails with ALREADY_EXISTS" "$out"
out=$(gcloud artifacts repositories describe "$REPO" --location=$LOC --project="$PROJECT" --format='value(format,description)' 2>&1)
echo "$out" | grep -q "DOCKER"; chk $? "describe returns format DOCKER" "$out"
out=$(gcloud artifacts repositories list --location=$LOC --project="$PROJECT" --format='value(name)' 2>&1)
echo "$out" | grep -q "$REPO"; chk $? "list contains the new repository" "$out"
out=$(gcloud artifacts repositories update "$REPO" --location=$LOC --description="updated" --project="$PROJECT" 2>&1); chk $? "update description" "$out"
out=$(gcloud artifacts repositories describe "$REPO" --location=$LOC --project="$PROJECT" --format='value(description)' 2>&1)
echo "$out" | grep -qx "updated"; chk $? "describe shows the updated description" "$out"
out=$(gcloud artifacts repositories set-iam-policy "$REPO" <(echo '{"bindings":[{"role":"roles/artifactregistry.reader","members":["allUsers"]}]}') --location=$LOC --project="$PROJECT" 2>&1)
chk $? "set-iam-policy" "$out"
out=$(gcloud artifacts repositories get-iam-policy "$REPO" --location=$LOC --project="$PROJECT" --format=json 2>&1)
echo "$out" | grep -q "allUsers"; chk $? "get-iam-policy returns the binding" "$out"
out=$(gcloud artifacts docker images list "$LOC-docker.pkg.dev/$PROJECT/$REPO" --project="$PROJECT" 2>&1)
chk $? "docker images list (empty repository)" "$out"
out=$(gcloud artifacts repositories delete "$REPO" --location=$LOC --project="$PROJECT" 2>&1); chk $? "gcloud artifacts repositories delete" "$out"
out=$(gcloud artifacts repositories describe "$REPO" --location=$LOC --project="$PROJECT" 2>&1)
echo "$out" | grep -qi "not found"; chk $? "describe after delete is NOT_FOUND" "$out"

[ "$fail" = "0" ] || { echo "$fail check(s) failed"; exit 1; }
echo "all checks passed"
