#!/usr/bin/env bash
# Real `gcloud monitoring` CLI against Vyomi's Cloud Monitoring API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cli-mon-proj}"
SFX="$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_MONITORING="$BASE/"   # `channels` live in the alpha track
F="--project=$PROJECT --quiet"
echo "== gcloud monitoring against $BASE project=$PROJECT =="

out=$(gcloud alpha monitoring channels create $F --display-name="cli-ops-$SFX" --type=email --channel-labels=email_address=ops@example.com --format='value(name)' 2>&1)
CH=$(echo "$out" | tail -1); echo "$CH" | grep -q "^projects/$PROJECT/notificationChannels/"
chk $? "gcloud alpha monitoring channels create (email)" "$out"

out=$(gcloud alpha monitoring channels describe "$CH" $F --format=json 2>&1)
echo "$out" | grep -q '"type": "email"' && echo "$out" | grep -q 'ops@example.com'
chk $? "gcloud alpha monitoring channels describe (type, label)" "$(echo "$out" | head -5)"

out=$(gcloud alpha monitoring channels list $F --format='value(name)' 2>&1); echo "$out" | grep -q "$CH"
chk $? "gcloud alpha monitoring channels list contains the channel" "$out"

out=$(gcloud alpha monitoring channels update "$CH" $F --display-name="cli-ops-renamed-$SFX" 2>&1); chk $? "gcloud alpha monitoring channels update" "$out"
out=$(gcloud alpha monitoring channels describe "$CH" $F --format='value(displayName)' 2>&1); [ "$out" = "cli-ops-renamed-$SFX" ]
chk $? "channel update persisted (displayName)" "$out"

out=$(gcloud alpha monitoring channel-descriptors list $F --format='value(type)' 2>&1); echo "$out" | grep -qx "slack"
chk $? "gcloud alpha monitoring channel-descriptors list" "$out"

POLICY_FILE="$(mktemp)"
cat > "$POLICY_FILE" <<JSON
{"displayName": "cli-cpu-$SFX", "combiner": "OR", "enabled": true,
 "documentation": {"content": "CPU is high", "mimeType": "text/markdown"},
 "notificationChannels": ["$CH"],
 "conditions": [{"displayName": "cpu above 80%", "conditionThreshold": {
   "filter": "metric.type=\"compute.googleapis.com/instance/cpu/utilization\" AND resource.type=\"gce_instance\"",
   "comparison": "COMPARISON_GT", "thresholdValue": 0.8, "duration": "300s",
   "aggregations": [{"alignmentPeriod": "60s", "perSeriesAligner": "ALIGN_MEAN"}]}}]}
JSON
out=$(gcloud monitoring policies create $F --policy-from-file="$POLICY_FILE" --format='value(name)' 2>&1)
POL=$(echo "$out" | tail -1); echo "$POL" | grep -q "^projects/$PROJECT/alertPolicies/"
chk $? "gcloud monitoring policies create --policy-from-file" "$out"
rm -f "$POLICY_FILE"

out=$(gcloud monitoring policies describe "$POL" $F --format=json 2>&1)
echo "$out" | grep -q "cli-cpu-$SFX" && echo "$out" | grep -q 'COMPARISON_GT' && echo "$out" | grep -q '"enabled": true'
chk $? "gcloud monitoring policies describe (name, comparison, enabled)" "$(echo "$out" | head -5)"

out=$(gcloud monitoring policies list $F --format='value(name)' 2>&1); echo "$out" | grep -q "$POL"
chk $? "gcloud monitoring policies list contains the policy" "$out"

out=$(gcloud monitoring policies update "$POL" $F --no-enabled --display-name="cli-cpu-renamed-$SFX" 2>&1); chk $? "gcloud monitoring policies update (disable + rename)" "$out"
out=$(gcloud monitoring policies describe "$POL" $F --format='value(displayName,enabled)' 2>&1)
echo "$out" | grep -q "cli-cpu-renamed-$SFX" && echo "$out" | grep -qi "false"
chk $? "policy update persisted (name, disabled)" "$out"

out=$(gcloud alpha monitoring channels delete "$CH" $F 2>&1); [ $? -ne 0 ]
chk $? "deleting a channel in use is refused" "$out"

out=$(gcloud monitoring policies delete "$POL" $F 2>&1); chk $? "gcloud monitoring policies delete" "$out"
out=$(gcloud alpha monitoring channels delete "$CH" $F 2>&1); chk $? "gcloud alpha monitoring channels delete" "$out"
out=$(gcloud monitoring policies describe "$POL" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|does not exist\|NOT_FOUND"
chk $? "deleted policy is gone (NOT_FOUND)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
