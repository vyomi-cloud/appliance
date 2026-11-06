#!/usr/bin/env bash
# Real `gcloud logging` CLI against Vyomi's Cloud Logging API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cli-log-proj}"
SFX="$(date +%s)"
LOG="cli-log-$SFX"; SINK="cli-sink-$SFX"; METRIC="cli_metric_$SFX"; EXCL="cli-excl-$SFX"; BKT="cli-bkt-$SFX"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_LOGGING="$BASE/"
F="--project=$PROJECT --quiet"
echo "== gcloud logging against $BASE project=$PROJECT =="

out=$(gcloud logging write "$LOG" "hello from the cli" --severity=INFO $F 2>&1); chk $? "gcloud logging write (text)" "$out"
out=$(gcloud logging write "$LOG" '{"user":"ada","code":42}' --payload-type=json --severity=ERROR $F 2>&1); chk $? "gcloud logging write (json, ERROR)" "$out"

out=$(gcloud logging read "logName=projects/$PROJECT/logs/$LOG" $F --format=json 2>&1)
echo "$out" | grep -q "hello from the cli" && echo "$out" | grep -q '"code": 42'
chk $? "gcloud logging read returns both entries" "$(echo "$out" | head -5)"
out=$(gcloud logging read "logName=projects/$PROJECT/logs/$LOG AND severity>=ERROR" $F --format='value(jsonPayload.user)' 2>&1)
[ "$out" = "ada" ]; chk $? "gcloud logging read with a severity filter" "$out"
out=$(gcloud logging read "logName=projects/$PROJECT/logs/$LOG" $F --limit=1 --order=desc --format='value(severity)' 2>&1)
[ "$out" = "ERROR" ]; chk $? "gcloud logging read --limit --order=desc" "$out"

out=$(gcloud logging logs list $F --format='value(NAME)' 2>&1); echo "$out" | grep -q "$LOG"
chk $? "gcloud logging logs list contains the log" "$out"

out=$(gcloud logging sinks create "$SINK" "storage.googleapis.com/cli-archive-$SFX" --log-filter="severity>=ERROR" --description="cli sink" $F 2>&1)
chk $? "gcloud logging sinks create" "$out"
out=$(gcloud logging sinks describe "$SINK" $F --format=json 2>&1)
echo "$out" | grep -q "storage.googleapis.com/cli-archive-$SFX" && echo "$out" | grep -q 'severity>=ERROR' && echo "$out" | grep -q writerIdentity
chk $? "gcloud logging sinks describe (destination, filter, writerIdentity)" "$(echo "$out" | head -5)"
out=$(gcloud logging sinks list $F --format='value(name)' 2>&1); echo "$out" | grep -q "$SINK"
chk $? "gcloud logging sinks list contains the sink" "$out"
out=$(gcloud logging sinks update "$SINK" --log-filter="severity>=WARNING" --description="updated" $F 2>&1); chk $? "gcloud logging sinks update" "$out"
out=$(gcloud logging sinks describe "$SINK" $F --format='value(filter)' 2>&1); [ "$out" = "severity>=WARNING" ]
chk $? "sink update persisted (filter)" "$out"
out=$(gcloud logging sinks create bad-sink "ftp://nope" $F 2>&1); [ $? -ne 0 ]
chk $? "sink with an invalid destination is rejected" "$out"

out=$(gcloud logging metrics create "$METRIC" --description="error count" --log-filter="severity>=ERROR" $F 2>&1); chk $? "gcloud logging metrics create" "$out"
out=$(gcloud logging metrics describe "$METRIC" $F --format='value(filter,description)' 2>&1)
echo "$out" | grep -q "severity>=ERROR"; chk $? "gcloud logging metrics describe" "$out"
out=$(gcloud logging metrics list $F --format='value(name)' 2>&1); echo "$out" | grep -q "$METRIC"
chk $? "gcloud logging metrics list" "$out"
out=$(gcloud logging metrics update "$METRIC" --description="updated count" $F 2>&1); chk $? "gcloud logging metrics update" "$out"
out=$(gcloud logging metrics delete "$METRIC" $F 2>&1); chk $? "gcloud logging metrics delete" "$out"

out=$(gcloud logging buckets create "$BKT" --location=global --retention-days=14 --description="cli bucket" $F 2>&1); chk $? "gcloud logging buckets create" "$out"
out=$(gcloud logging buckets describe "$BKT" --location=global $F --format='value(retentionDays,lifecycleState)' 2>&1)
echo "$out" | grep -q "14"; chk $? "gcloud logging buckets describe (retention)" "$out"
out=$(gcloud logging buckets list --location=global $F --format=json 2>&1)
echo "$out" | grep -q "_Default" && echo "$out" | grep -q "$BKT"; chk $? "gcloud logging buckets list (default + custom)" "$out"
out=$(gcloud logging buckets update "$BKT" --location=global --retention-days=30 $F 2>&1); chk $? "gcloud logging buckets update" "$out"
out=$(gcloud logging buckets delete "$BKT" --location=global $F 2>&1); chk $? "gcloud logging buckets delete" "$out"

out=$(gcloud logging resource-descriptors list $F --format='value(type)' 2>&1); echo "$out" | grep -q "gce_instance"
chk $? "gcloud logging resource-descriptors list" "$out"

out=$(gcloud logging sinks delete "$SINK" $F 2>&1); chk $? "gcloud logging sinks delete" "$out"
out=$(gcloud logging sinks describe "$SINK" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|NOT_FOUND\|does not exist"
chk $? "deleted sink is gone (NOT_FOUND)" "$out"
out=$(gcloud logging logs delete "$LOG" $F 2>&1); chk $? "gcloud logging logs delete" "$out"
out=$(gcloud logging read "logName=projects/$PROJECT/logs/$LOG" $F --format=json 2>&1); [ "$(echo "$out" | tr -d ' \n')" = "[]" ]
chk $? "deleted log has no entries" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
