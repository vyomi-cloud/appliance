#!/usr/bin/env bash
# Real `gcloud workflows` CLI against Vyomi's Workflows + Workflow Executions API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cli-wf-proj}"
LOC=us-central1
ID="cli-wf-$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_WORKFLOWS="$BASE/"
export CLOUDSDK_API_ENDPOINT_OVERRIDES_WORKFLOWEXECUTIONS="$BASE/"
F="--location=$LOC --project=$PROJECT --quiet"
echo "== gcloud workflows against $BASE project=$PROJECT =="

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/v1.yaml" <<'Y'
main:
  steps:
    - init:
        assign:
          - greeting: "Hello from gcloud"
    - done:
        return: ${greeting}
Y
cat > "$TMP/v2.yaml" <<'Y'
main:
  steps:
    - done:
        return: "v2"
Y

out=$(gcloud workflows deploy "$ID" $F --source="$TMP/v1.yaml" --description="cli workflow" --labels=env=dev 2>&1)
chk $? "gcloud workflows deploy (create)" "$out"

out=$(gcloud workflows describe "$ID" $F --format=json 2>&1)
echo "$out" | grep -q '"state": "ACTIVE"' && echo "$out" | grep -q '"description": "cli workflow"' && echo "$out" | grep -q '"env": "dev"' && echo "$out" | grep -q 'Hello from gcloud'
chk $? "describe (ACTIVE, description, labels, source)" "$(echo "$out" | head -8)"

out=$(gcloud workflows list $F --format='value(name,state)' 2>&1); echo "$out" | grep -q "$ID.*ACTIVE"
chk $? "workflows list contains the workflow" "$out"

out=$(gcloud workflows deploy "$ID" $F --source="$TMP/v2.yaml" --description="updated" 2>&1)
chk $? "gcloud workflows deploy (update source + description)" "$out"
out=$(gcloud workflows describe "$ID" $F --format='value(description,revisionId)' 2>&1); echo "$out" | grep -q "updated" && echo "$out" | grep -q "000002-"
chk $? "update persisted (description, revision 000002)" "$out"

out=$(gcloud workflows run "$ID" $F 2>&1); echo "$out" | grep -q "SUCCEEDED" && echo "$out" | grep -q "v2"
chk $? "gcloud workflows run -> SUCCEEDED, result v2" "$out"

out=$(gcloud workflows executions list "$ID" $F --format='value(name,state)' 2>&1); echo "$out" | grep -q "SUCCEEDED"
chk $? "executions list" "$out"
EID=$(echo "$out" | head -1 | awk '{print $1}' | sed 's#.*/##')
out=$(gcloud workflows executions describe "$EID" --workflow="$ID" $F --format='value(state,result)' 2>&1); echo "$out" | grep -q "SUCCEEDED"
chk $? "executions describe" "$out"

out=$(gcloud workflows delete "$ID" $F 2>&1); chk $? "gcloud workflows delete" "$out"
out=$(gcloud workflows describe "$ID" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|NOT_FOUND\|does not exist"
chk $? "deleted workflow is gone (NOT_FOUND)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
