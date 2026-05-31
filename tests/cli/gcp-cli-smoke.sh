#!/usr/bin/env bash
# Real gcloud / gsutil CLI smoke against the CloudLearn simulator, run inside the
# google-cloud-cli image. Proves whether the unmodified CLIs work when pointed at
# the simulator via endpoint overrides + disabled credentials.
#
# Run on the appliance (so 127.0.0.1:9000 reaches the simulator):
#   multipass exec cloudlearn-appliance -- bash -lc \
#     'docker run --rm --network host -e PROJECT=gcp-dev \
#        -v /workspace/cloud-learn/tests/conformance:/work -w /work \
#        gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators bash gcp-cli-smoke.sh'
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-gcp-dev}"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "PASS $2"; pass=$((pass+1)); else echo "FAIL $2 :: $3"; fail=$((fail+1)); fi; }

echo "== gcloud/gsutil against $BASE project=$PROJECT =="

# Disable real credentials + point the Storage JSON API at the simulator.
gcloud config set auth/disable_credentials true >/dev/null 2>&1
gcloud config set core/project "$PROJECT" >/dev/null 2>&1
export CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE="$BASE/storage/v1/"
export STORAGE_EMULATOR_HOST="${BASE#http://}"

BUCKET="cli-smoke-$(date +%s)"

out=$(gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT" 2>&1); chk $? "gcloud storage buckets create" "$out"
out=$(gcloud storage buckets list 2>&1); echo "$out" | grep -q "$BUCKET"; chk $? "gcloud storage buckets list contains new bucket" "$(echo "$out" | tail -2)"
echo "hello-from-gcloud" > /tmp/cli-obj.txt
out=$(gcloud storage cp /tmp/cli-obj.txt "gs://$BUCKET/obj.txt" 2>&1); chk $? "gcloud storage cp (upload)" "$out"
out=$(gcloud storage cat "gs://$BUCKET/obj.txt" 2>&1); echo "$out" | grep -q "hello-from-gcloud"; chk $? "gcloud storage cat (download)" "$out"
out=$(gcloud storage rm "gs://$BUCKET/obj.txt" 2>&1); chk $? "gcloud storage rm object" "$out"
out=$(gcloud storage buckets delete "gs://$BUCKET" 2>&1); chk $? "gcloud storage buckets delete" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
