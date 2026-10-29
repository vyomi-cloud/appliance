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

out=$(G create-http-task "t-$Q" --queue="$Q" --url=https://example.com/handler --method=POST --body-content=hello --schedule-time="$(date -u -d "+1 day" +%Y-%m-%dT%H:%M:%SZ)" --format='value(name)' 2>&1); rc=$?
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

# Real dispatch: the appliance's dispatcher calls the HTTP target (the appliance itself, reached on its
# in-container port, so no host networking is needed). 2xx completes the task; a failing target is retried
# per the queue's retryConfig, then given up on.
QD="cli-d-$(date +%s)"
G queues create "$QD" --max-attempts=3 --min-backoff=0.2s --max-backoff=1s --max-dispatches-per-second=5 >/dev/null 2>&1
G create-http-task "ok-$QD" --queue="$QD" --method=GET --url="http://127.0.0.1:9000/v2/projects/$PROJECT/locations" >/dev/null 2>&1
G create-http-task "bad-$QD" --queue="$QD" --method=GET --url="http://127.0.0.1:9000/no-such-target" >/dev/null 2>&1
saw=0; for _ in $(seq 1 20); do
  c=$(G describe "bad-$QD" --queue="$QD" --format='value(dispatchCount)' 2>/dev/null); [ "${c:-0}" -ge 2 ] 2>/dev/null && { saw=1; break; }; sleep 0.3
done
chk $((1-saw)) "failing target is retried per retryConfig (dispatchCount >= 2)" "$c"
sleep 3
out=$(G list --queue="$QD" --format='value(name)' 2>/dev/null); [ -z "$out" ]; chk $? "completed task removed; exhausted task given up after maxAttempts" "$out"
G create-http-task "fut-$QD" --queue="$QD" --method=GET --url="http://127.0.0.1:9000/v2/projects/$PROJECT/locations" --schedule-time="$(date -u -d "+1 hour" +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1
sleep 1.5
out=$(G describe "fut-$QD" --queue="$QD" --format='value(dispatchCount)' 2>&1); [ "$out" = "0" ] || [ -z "$out" ]; chk $? "task with a future scheduleTime is not dispatched early" "$out"
G queues pause "$QD" >/dev/null 2>&1
G create-http-task "p-$QD" --queue="$QD" --method=GET --url="http://127.0.0.1:9000/v2/projects/$PROJECT/locations" >/dev/null 2>&1
sleep 1.5
out=$(G describe "p-$QD" --queue="$QD" --format='value(name)' 2>/dev/null); [ -n "$out" ]; chk $? "paused queue holds its tasks" "$out"
G queues resume "$QD" >/dev/null 2>&1
gone=0; for _ in $(seq 1 20); do
  G describe "p-$QD" --queue="$QD" >/dev/null 2>&1 || { gone=1; break; }; sleep 0.3
done
chk $((1-gone)) "resumed queue dispatches the held task" ""
G queues delete "$QD" >/dev/null 2>&1

out=$(G queues delete "$Q" 2>&1); chk $? "queues delete" "$out"
G queues describe "$Q" >/dev/null 2>/tmp/ct-cli.err; rc=$?; grep -qi "not found\|NOT_FOUND\|does not exist" /tmp/ct-cli.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "describe a deleted queue → NOT_FOUND" "$(cat /tmp/ct-cli.err)"

echo "$pass passed, $fail failed"
[ "$fail" = "0" ] || exit 1
