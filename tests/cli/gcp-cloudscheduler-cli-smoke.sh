#!/usr/bin/env bash
# Real `gcloud scheduler` CLI against Vyomi's Cloud Scheduler API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
# Default PROJECT: the appliance's GCP project, discovered the way a user's gcloud
# sees it (Cloud Resource Manager) — the same project the GCP console works in.
if [ -z "${PROJECT:-}" ]; then
  PROJECT=$(CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDRESOURCEMANAGER="$BASE/" CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true \
    CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud projects list --format='value(projectId)' --limit=1 2>/dev/null | head -1)
  [ -n "$PROJECT" ] || { echo "FAIL discover project :: \`gcloud projects list\` against $BASE returned nothing"; exit 1; }
fi
LOC=us-central1
JOB="cli-job-$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDSCHEDULER="$BASE/"
F="--location=$LOC --project=$PROJECT --quiet"
echo "== gcloud scheduler against $BASE project=$PROJECT =="

out=$(gcloud scheduler jobs create http "$JOB" $F --schedule="*/5 * * * *" --uri="https://example.com/hook" --http-method=POST \
      --message-body='{"x":1}' --time-zone="America/New_York" --description="cli job" 2>&1)
chk $? "gcloud scheduler jobs create http" "$out"

out=$(gcloud scheduler jobs describe "$JOB" $F --format=json 2>&1)
echo "$out" | grep -q '"schedule": "\*/5 \* \* \* \*"' && echo "$out" | grep -q '"state": "ENABLED"' && echo "$out" | grep -q 'America/New_York'
chk $? "gcloud scheduler jobs describe (schedule, state, timeZone)" "$(echo "$out" | head -5)"

out=$(gcloud scheduler jobs list $F --format='value(name)' 2>&1); echo "$out" | grep -q "$JOB"
chk $? "gcloud scheduler jobs list contains the job" "$out"

out=$(gcloud scheduler jobs update http "$JOB" $F --schedule="0 9 * * 1-5" --description="updated" 2>&1); chk $? "gcloud scheduler jobs update http" "$out"
out=$(gcloud scheduler jobs describe "$JOB" $F --format='value(schedule,description)' 2>&1); echo "$out" | grep -q "0 9 \* \* 1-5"
chk $? "update persisted (schedule)" "$out"

out=$(gcloud scheduler jobs pause "$JOB" $F 2>&1); chk $? "gcloud scheduler jobs pause" "$out"
out=$(gcloud scheduler jobs describe "$JOB" $F --format='value(state)' 2>&1); [ "$out" = "PAUSED" ]; chk $? "job is PAUSED" "$out"
out=$(gcloud scheduler jobs resume "$JOB" $F 2>&1); chk $? "gcloud scheduler jobs resume" "$out"
out=$(gcloud scheduler jobs run "$JOB" $F 2>&1); chk $? "gcloud scheduler jobs run" "$out"
out=$(gcloud scheduler jobs describe "$JOB" $F --format='value(lastAttemptTime)' 2>&1); [ -n "$out" ]; chk $? "run recorded lastAttemptTime" "$out"

out=$(gcloud scheduler jobs create pubsub "$JOB-ps" $F --schedule="@hourly" --topic="projects/$PROJECT/topics/t1" --message-body=tick 2>&1)
chk $? "gcloud scheduler jobs create pubsub" "$out"

out=$(gcloud scheduler jobs delete "$JOB" $F 2>&1); chk $? "gcloud scheduler jobs delete" "$out"
gcloud scheduler jobs delete "$JOB-ps" $F >/dev/null 2>&1
out=$(gcloud scheduler jobs describe "$JOB" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|NOT_FOUND"
chk $? "deleted job is gone (NOT_FOUND)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
