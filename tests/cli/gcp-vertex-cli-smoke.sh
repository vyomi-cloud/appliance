#!/usr/bin/env bash
# Real `gcloud ai ...` / `gcloud workbench ...` against Vyomi's Vertex AI control plane (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
if [ -z "${PROJECT:-}" ]; then
  PROJECT=$(CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDRESOURCEMANAGER="$BASE/" CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true \
    CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud projects list --format='value(projectId)' --limit=1 2>/dev/null | head -1)
  PROJECT="${PROJECT:-vyomi-project}"
fi
R=us-central1
S="cli$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
export CLOUDSDK_CORE_DISABLE_PROMPTS=1 CLOUDSDK_CORE_PROJECT="$PROJECT" CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_AIPLATFORM="$BASE/" CLOUDSDK_API_ENDPOINT_OVERRIDES_NOTEBOOKS="$BASE/"
F="--region=$R --project=$PROJECT --quiet"
echo "== gcloud ai against $BASE project=$PROJECT =="
id() { awk -F/ '{print $NF}'; }

out=$(gcloud ai endpoints create $F --display-name="$S-ep" 2>&1); chk $? "ai endpoints create" "$out"
EP=$(gcloud ai endpoints list $F --filter="displayName=$S-ep" --format='value(name)' 2>/dev/null | head -1 | id)
[ -n "$EP" ]; chk $? "ai endpoints list finds it" "$EP"
out=$(gcloud ai models upload $F --display-name="$S-model" --container-image-uri=us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest 2>&1); chk $? "ai models upload" "$out"
MD=$(gcloud ai models list $F --filter="displayName=$S-model" --format='value(name)' 2>/dev/null | head -1 | id)
[ -n "$MD" ]; chk $? "ai models list finds it" "$MD"
out=$(gcloud ai endpoints deploy-model "$EP" $F --model="$MD" --display-name=dep --machine-type=n1-standard-2 2>&1); chk $? "ai endpoints deploy-model" "$out"
dm=$(gcloud ai endpoints describe "$EP" $F --format='value(deployedModels[0].id)' 2>/dev/null); [ -n "$dm" ]
chk $? "endpoint describe shows the deployed model" "$dm"
out=$(gcloud ai endpoints undeploy-model "$EP" $F --deployed-model-id="$dm" 2>&1); chk $? "ai endpoints undeploy-model" "$out"
out=$(gcloud ai custom-jobs create $F --display-name="$S-job" --worker-pool-spec=machine-type=n1-standard-4,replica-count=1,container-image-uri=gcr.io/x/y 2>&1); chk $? "ai custom-jobs create" "$out"
sleep 6
st=$(gcloud ai custom-jobs list $F --filter="displayName=$S-job" --format='value(state)' 2>/dev/null | head -1); [ "$st" = "JOB_STATE_SUCCEEDED" ]
chk $? "custom job ran to JOB_STATE_SUCCEEDED" "$st"
echo '{"contentsDeltaUri":"gs://b/idx","config":{"dimensions":2,"approximateNeighborsCount":5,"distanceMeasureType":"COSINE_DISTANCE","algorithmConfig":{"treeAhConfig":{}}}}' > "/tmp/$S-idx.json"
out=$(gcloud ai indexes create $F --display-name="$S-idx" --metadata-file="/tmp/$S-idx.json" 2>&1); chk $? "ai indexes create" "$out"
out=$(gcloud ai index-endpoints create $F --display-name="$S-ie" --public-endpoint-enabled 2>&1); chk $? "ai index-endpoints create" "$out"
out=$(gcloud ai tensorboards create $F --display-name="$S-tb" 2>&1); chk $? "ai tensorboards create" "$out"
out=$(gcloud workbench instances create "$S-wb" --location=${R}-a --project=$PROJECT --quiet 2>&1); chk $? "workbench instances create" "$out"
out=$(gcloud workbench instances list --location=${R}-a --project=$PROJECT --format='value(name)' 2>&1); echo "$out" | grep -q "$S-wb"
chk $? "workbench instances list" "$out"
out=$(gcloud workbench instances delete "$S-wb" --location=${R}-a --project=$PROJECT --quiet 2>&1); chk $? "workbench instances delete" "$out"
out=$(gcloud ai endpoints delete "$EP" $F 2>&1); chk $? "ai endpoints delete" "$out"
out=$(gcloud ai endpoints list $F --filter="displayName=$S-ep" --format='value(name)' 2>/dev/null); [ -z "$out" ]
chk $? "endpoint is gone" "$out"
echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
