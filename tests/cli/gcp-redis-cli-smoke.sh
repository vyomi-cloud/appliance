#!/usr/bin/env bash
# Real `gcloud redis` CLI against Vyomi's Memorystore for Redis API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cli-redis-proj}"
LOC=us-central1
ID="cli-redis-$(date +%s)"
HA="${ID}-ha"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_REDIS="$BASE/"
F="--region=$LOC --project=$PROJECT --quiet"
echo "== gcloud redis against $BASE project=$PROJECT =="

out=$(gcloud redis instances create "$ID" $F --size=2 --tier=basic --redis-version=redis_7_0 --labels=env=dev 2>&1)
chk $? "gcloud redis instances create (basic, 2 GB)" "$out"

out=$(gcloud redis instances describe "$ID" $F --format=json 2>&1)
echo "$out" | grep -q '"state": "READY"' && echo "$out" | grep -q '"memorySizeGb": 2' && echo "$out" | grep -q '"tier": "BASIC"' && echo "$out" | grep -q '"port": 6379' && echo "$out" | grep -q '"redisVersion": "REDIS_7_0"'
chk $? "describe (READY, 2 GB, BASIC, port 6379, REDIS_7_0)" "$(echo "$out" | head -5)"

out=$(gcloud redis instances list $F --format='value(name,state)' 2>&1); echo "$out" | grep -q "$ID.*READY"
chk $? "instances list contains the instance" "$out"

out=$(gcloud redis instances update "$ID" $F --size=4 2>&1); chk $? "gcloud redis instances update --size" "$out"
out=$(gcloud redis instances describe "$ID" $F --format='value(memorySizeGb)' 2>&1); [ "$out" = "4" ]
chk $? "resize persisted (4 GB)" "$out"

out=$(gcloud redis instances update "$ID" $F --update-labels=team=core --update-redis-config=maxmemory-policy=allkeys-lru 2>&1)
chk $? "gcloud redis instances update --update-labels --update-redis-config" "$out"
out=$(gcloud redis instances describe "$ID" $F --format=json 2>&1); echo "$out" | grep -q '"team": "core"' && echo "$out" | grep -q 'allkeys-lru'
chk $? "labels and redis config persisted" "$(echo "$out" | head -5)"

out=$(gcloud redis instances create "$HA" $F --size=1 --tier=standard --enable-auth 2>&1); chk $? "gcloud redis instances create (standard HA, AUTH)" "$out"
out=$(gcloud redis instances describe "$HA" $F --format='value(alternativeLocationId,replicaCount)' 2>&1); echo "$out" | grep -q "us-central1-b"
chk $? "standard tier has an alternative zone and replica" "$out"
out=$(gcloud redis instances get-auth-string "$HA" $F 2>&1); echo "$out" | grep -q "auth-"
chk $? "gcloud redis instances get-auth-string" "$out"
out=$(gcloud redis instances failover "$HA" $F --data-protection-mode=limited-data-loss 2>&1); chk $? "gcloud redis instances failover" "$out"
out=$(gcloud redis instances describe "$HA" $F --format='value(currentLocationId)' 2>&1); [ "$out" = "us-central1-b" ]
chk $? "failover swapped the primary zone" "$out"
out=$(gcloud redis instances upgrade "$HA" $F --redis-version=redis_7_2 2>&1); chk $? "gcloud redis instances upgrade" "$out"
out=$(gcloud redis instances describe "$HA" $F --format='value(redisVersion)' 2>&1); [ "$out" = "REDIS_7_2" ]
chk $? "upgrade persisted (REDIS_7_2)" "$out"

out=$(gcloud redis instances export gs://cli-redis-bkt/dump.rdb "$ID" $F 2>&1); chk $? "gcloud redis instances export" "$out"
out=$(gcloud redis instances import gs://cli-redis-bkt/dump.rdb "$ID" $F 2>&1); chk $? "gcloud redis instances import" "$out"

out=$(gcloud redis operations list $F --format='value(name)' 2>&1); [ -n "$out" ]
chk $? "gcloud redis operations list" "$out"

out=$(gcloud redis instances delete "$HA" $F 2>&1); chk $? "gcloud redis instances delete (HA)" "$out"
out=$(gcloud redis instances delete "$ID" $F 2>&1); chk $? "gcloud redis instances delete" "$out"
out=$(gcloud redis instances describe "$ID" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not found\|NOT_FOUND"
chk $? "deleted instance is gone (NOT_FOUND)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
