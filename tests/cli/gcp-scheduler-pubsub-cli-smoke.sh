#!/usr/bin/env bash
# #149: a Cloud Scheduler pubsubTarget job run must reach `gcloud pubsub subscriptions pull`
# (real gcloud, endpoint override only). ENDPOINT (default http://127.0.0.1:9000).
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT=$(curl -s "$BASE/v1/projects" | python3 -c "import json,sys;print(json.load(sys.stdin)['projects'][0]['projectId'])") || exit 1
export CLOUDSDK_CORE_DISABLE_PROMPTS=1 CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDSCHEDULER="$BASE/" CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB="$BASE/"
T="sp-$(date +%s)"; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; else echo "[FAIL] $2 :: ${3:-}"; fail=1; fi; }
out=$(gcloud pubsub topics create "$T" 2>&1); chk $? "create topic" "$out"
out=$(gcloud pubsub subscriptions create "$T-s" --topic="$T" 2>&1); chk $? "create subscription" "$out"
out=$(gcloud scheduler jobs create pubsub "$T-j" --location=us-central1 --schedule="0 0 1 1 *" --topic="$T" --message-body=hello-sched --attributes=k=v 2>&1); chk $? "create pubsub job" "$out"
out=$(gcloud scheduler jobs run "$T-j" --location=us-central1 2>&1); chk $? "run job" "$out"
out=$(gcloud pubsub subscriptions pull "$T-s" --auto-ack --format=json 2>&1)
echo "$out" | grep -q '"k": "v"'; chk $? "pulled message has the job's attributes" "$out"
echo "$out" | grep -q "$(printf hello-sched | base64)"; chk $? "pulled message has the job's data" "$out"
gcloud scheduler jobs delete "$T-j" --location=us-central1 --quiet >/dev/null 2>&1
gcloud pubsub subscriptions delete "$T-s" >/dev/null 2>&1; gcloud pubsub topics delete "$T" >/dev/null 2>&1
exit $fail
