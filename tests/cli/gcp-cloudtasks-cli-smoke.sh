#!/usr/bin/env bash
# Real `gcloud tasks` CLI smoke against Vyomi — only the Cloud Tasks API endpoint is overridden.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/gcp-cloudtasks-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cloudlearn}"
LOC=us-central1
if ! command -v gcloud >/dev/null 2>&1; then echo "[FAIL] gcloud not installed"; exit 1; fi
export CLOUDSDK_CORE_DISABLE_PROMPTS=1 CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDTASKS="$BASE/"
gcloud config set auth/disable_credentials true >/dev/null 2>&1
gcloud config set core/project "$PROJECT" >/dev/null 2>&1

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
G() { gcloud tasks "$@" --location="$LOC" --project="$PROJECT" --quiet; }
Q="cli-q-$(date +%s)"

out=$(G queues create "$Q" --max-dispatches-per-second=25 --max-attempts=7 --format='value(name)' 2>&1); rc=$?
chk $rc "queues create" "$out"
[ $rc -ne 0 ] && { echo "$pass passed, $fail failed"; exit 1; }
out=$(G queues describe "$Q" --format='value(name)' 2>/dev/null); [ "${out##*/}" = "$Q" ]; chk $? "queues describe returns the name" "$out"
out=$(G queues describe "$Q" --format='value(rateLimits.maxDispatchesPerSecond)' 2>&1); [ "${out%%.*}" = "25" ]; chk $? "queue keeps --max-dispatches-per-second" "$out"
out=$(G queues describe "$Q" --format='value(retryConfig.maxAttempts)' 2>&1); [ "$out" = "7" ]; chk $? "queue keeps --max-attempts" "$out"
out=$(G queues list --format='value(name)' 2>/dev/null); echo "$out" | grep -qx "$Q"; chk $? "queues list contains the queue" "$out"
out=$(G queues update "$Q" --max-dispatches-per-second=9 --format='value(rateLimits.maxDispatchesPerSecond)' 2>/dev/null); [ "${out%%.*}" = "9" ]; chk $? "queues update changes the rate" "$out"
G queues pause "$Q" >/dev/null 2>&1; chk $? "queues pause"
out=$(G queues describe "$Q" --format='value(state)' 2>/dev/null); [ "$out" = "PAUSED" ]; chk $? "paused queue reports PAUSED" "$out"
G queues resume "$Q" >/dev/null 2>&1; chk $? "queues resume"
out=$(G queues describe "$Q" --format='value(state)' 2>/dev/null); [ "$out" = "RUNNING" ]; chk $? "resumed queue reports RUNNING" "$out"

out=$(G create-http-task "t-$Q" --queue="$Q" --url=https://example.com/handler --method=POST --body-content=hello --format='value(name)' 2>&1); rc=$?
chk $rc "tasks create-http-task" "$out"
out=$(G list --queue="$Q" --format='value(name)' 2>/dev/null); echo "$out" | grep -qx "t-$Q"; chk $? "tasks list contains the task" "$out"
out=$(G describe "t-$Q" --queue="$Q" --format='value(httpRequest.url)' 2>&1); [ "$out" = "https://example.com/handler" ]; chk $? "tasks describe returns the URL" "$out"
out=$(G run "t-$Q" --queue="$Q" --format='value(dispatchCount)' 2>&1); [ "$out" = "1" ]; chk $? "tasks run dispatches once" "$out"
G create-http-task "t2-$Q" --queue="$Q" --url=https://example.com/two >/dev/null 2>&1
out=$(G delete "t2-$Q" --queue="$Q" 2>&1); chk $? "tasks delete" "$out"
G describe "t2-$Q" --queue="$Q" >/dev/null 2>/tmp/ct-cli.err; rc=$?; grep -qi "not found\|NOT_FOUND\|does not exist" /tmp/ct-cli.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "describe a deleted task → NOT_FOUND" "$(cat /tmp/ct-cli.err)"
G create-http-task "t3-$Q" --queue="$Q" --url=https://example.com/three >/dev/null 2>&1
out=$(G queues purge "$Q" 2>&1); chk $? "queues purge" "$out"
out=$(G list --queue="$Q" --format='value(name)' 2>/dev/null); [ -z "$out" ]; chk $? "queue is empty after purge" "$out"

out=$(G queues delete "$Q" 2>&1); chk $? "queues delete" "$out"
G queues describe "$Q" >/dev/null 2>/tmp/ct-cli.err; rc=$?; grep -qi "not found\|NOT_FOUND\|does not exist" /tmp/ct-cli.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "describe a deleted queue → NOT_FOUND" "$(cat /tmp/ct-cli.err)"

echo "$pass passed, $fail failed"
[ "$fail" = "0" ] || exit 1
