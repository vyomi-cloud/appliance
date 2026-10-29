#!/usr/bin/env bash
# Real `gcloud container` CLI against Vyomi's Kubernetes Engine API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cli-gke-proj}"
LOC=us-central1
CL="cli-gke-$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_CONTAINER="$BASE/"
F="--region=$LOC --project=$PROJECT --quiet"
echo "== gcloud container against $BASE project=$PROJECT =="

out=$(gcloud container clusters create "$CL" $F --num-nodes=2 --machine-type=e2-medium --no-enable-autoupgrade --labels=env=dev 2>&1)
chk $? "gcloud container clusters create" "$out"

out=$(gcloud container clusters describe "$CL" $F --format=json 2>&1)
echo "$out" | grep -q '"status": "RUNNING"' && echo "$out" | grep -q '"name": "default-pool"' && echo "$out" | grep -q '"machineType": "e2-medium"'
chk $? "describe (RUNNING, default-pool, machineType)" "$(echo "$out" | head -5)"

out=$(gcloud container clusters list $F --format='value(name,status)' 2>&1); echo "$out" | grep -q "$CL.*RUNNING"
chk $? "clusters list contains the cluster" "$out"

out=$(gcloud container node-pools create pool-2 --cluster="$CL" $F --num-nodes=1 --machine-type=e2-standard-4 2>&1)
chk $? "gcloud container node-pools create" "$out"
out=$(gcloud container node-pools list --cluster="$CL" $F --format='value(name)' 2>&1); echo "$out" | grep -q pool-2 && echo "$out" | grep -q default-pool
chk $? "node-pools list shows both pools" "$out"

out=$(gcloud container clusters resize "$CL" --node-pool=default-pool --num-nodes=3 $F 2>&1); chk $? "gcloud container clusters resize" "$out"
out=$(gcloud container node-pools describe default-pool --cluster="$CL" $F --format='value(initialNodeCount)' 2>&1); [ "$out" = "3" ]
chk $? "resize persisted (3 nodes)" "$out"

out=$(gcloud container clusters update "$CL" $F --update-labels=team=core 2>&1); chk $? "gcloud container clusters update --update-labels" "$out"
out=$(gcloud container clusters describe "$CL" $F --format='value(resourceLabels)' 2>&1); echo "$out" | grep -q "team"
chk $? "labels persisted" "$out"

out=$(gcloud container operations list $F --format='value(name)' 2>&1); [ -n "$out" ]
chk $? "gcloud container operations list" "$out"
out=$(gcloud container get-server-config $F --format='value(defaultClusterVersion)' 2>&1); [ -n "$out" ] && ! echo "$out" | grep -qi error
chk $? "gcloud container get-server-config" "$out"

out=$(gcloud container node-pools delete pool-2 --cluster="$CL" $F 2>&1); chk $? "gcloud container node-pools delete" "$out"
out=$(gcloud container clusters delete "$CL" $F 2>&1); chk $? "gcloud container clusters delete" "$out"
out=$(gcloud container clusters describe "$CL" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|NOT_FOUND"
chk $? "deleted cluster is gone (NOT_FOUND)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
