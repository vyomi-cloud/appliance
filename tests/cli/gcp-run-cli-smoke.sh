#!/usr/bin/env bash
# Real `gcloud run` CLI against Vyomi's Cloud Run API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
#
# gcloud run speaks the regional Knative-style API on `{region}-run.googleapis.com`: it prepends
# `{region}-` to the overridden host, so the override uses a *.localhost name (resolves to
# loopback, RFC 6761) on the appliance's port: http://vyomi.localhost:PORT -> us-central1-vyomi.localhost.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PORT=$(echo "$BASE" | sed -E 's#^https?://[^/:]+(:([0-9]+))?.*#\2#'); PORT="${PORT:-80}"
PROJECT="${PROJECT:-cli-run-proj}"
LOC=us-central1
SVC="cli-run-$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_RUN="http://vyomi.localhost:$PORT/"
F="--region=$LOC --project=$PROJECT --quiet"
echo "== gcloud run against $BASE (via vyomi.localhost:$PORT) project=$PROJECT =="

out=$(gcloud run deploy "$SVC" --image=us-docker.pkg.dev/cloudrun/container/hello $F --allow-unauthenticated --memory=512Mi --cpu=1 --port=8080 --max-instances=5 --labels=env=dev 2>&1)
echo "$out" | grep -q "has been deployed and is serving 100 percent of traffic"
chk $? "gcloud run deploy (create + allow-unauthenticated)" "$(echo "$out" | tail -3)"

out=$(gcloud run services describe "$SVC" $F --format=json 2>&1)
echo "$out" | grep -q '"image": "us-docker.pkg.dev/cloudrun/container/hello"' && echo "$out" | grep -q '"status": "True"' && echo "$out" | grep -q '"url": "https://'
chk $? "describe (image, Ready condition, run.app URL)" "$(echo "$out" | head -5)"

out=$(gcloud run services list $F --format='value(metadata.name)' 2>&1); echo "$out" | grep -qx "$SVC"
chk $? "services list contains the service" "$out"

out=$(gcloud run services get-iam-policy "$SVC" $F --format='value(bindings[0].members)' 2>&1); echo "$out" | grep -q allUsers
chk $? "IAM policy has the allUsers invoker binding" "$out"

out=$(gcloud run services update "$SVC" $F --memory=1Gi --min-instances=1 --update-env-vars=GREETING=hi 2>&1)
echo "$out" | grep -q "has been deployed"
chk $? "gcloud run services update (new revision)" "$(echo "$out" | tail -3)"
out=$(gcloud run services describe "$SVC" $F --format='value(spec.template.spec.containers[0].resources.limits.memory)' 2>&1); [ "$out" = "1Gi" ]
chk $? "update persisted (memory 1Gi)" "$out"

out=$(gcloud run revisions list --service="$SVC" $F --format='value(metadata.name)' 2>&1)
[ "$(echo "$out" | grep -c "^$SVC-")" = "2" ]
chk $? "revisions list shows both revisions" "$out"
OLD=$(echo "$out" | tail -1)
out=$(gcloud run revisions describe "$OLD" $F --format='value(metadata.labels."serving.knative.dev/service")' 2>&1); [ "$out" = "$SVC" ]
chk $? "revisions describe" "$out"
out=$(gcloud run revisions delete "$OLD" $F 2>&1); chk $? "gcloud run revisions delete (non-serving revision)" "$out"

out=$(gcloud run services update-traffic "$SVC" $F --to-latest 2>&1); chk $? "gcloud run services update-traffic --to-latest" "$out"

out=$(gcloud run services delete "$SVC" $F 2>&1); chk $? "gcloud run services delete" "$out"
out=$(gcloud run services describe "$SVC" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|does not exist\|NOT_FOUND\|Cannot find"
chk $? "deleted service is gone (NOT_FOUND)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
