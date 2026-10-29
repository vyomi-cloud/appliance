#!/usr/bin/env bash
# Real `aws stepfunctions` CLI smoke against Vyomi — only --endpoint-url is overridden.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-stepfunctions-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
if ! command -v aws >/dev/null 2>&1; then echo "[FAIL] aws-cli not installed"; exit 1; fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
A() { aws --endpoint-url "$BASE" stepfunctions "$@"; }
SFX=$(date +%s)
ROLE="arn:aws:iam::000000000000:role/service-role/StepFunctions-ExecutionRole"
DEF='{"StartAt":"Hello","States":{"Hello":{"Type":"Pass","Result":{"msg":"hi"},"ResultPath":"$.out","Next":"Pick"},"Pick":{"Type":"Choice","Choices":[{"Variable":"$.go","BooleanEquals":true,"Next":"Ok"}],"Default":"Bad"},"Ok":{"Type":"Succeed"},"Bad":{"Type":"Fail","Error":"NotGo","Cause":"go was false"}}}'

SM=$(A create-state-machine --name "cli-$SFX" --definition "$DEF" --role-arn "$ROLE" --query stateMachineArn --output text 2>&1); rc=$?
chk $rc "create-state-machine" "$SM"
[ $rc -ne 0 ] && { echo "$pass passed, $((fail)) failed"; exit 1; }

out=$(A describe-state-machine --state-machine-arn "$SM" --query name --output text 2>&1); [ "$out" = "cli-$SFX" ]; chk $? "describe-state-machine returns the name" "$out"
out=$(A list-state-machines --query "stateMachines[?stateMachineArn=='$SM'].name" --output text 2>&1); [ "$out" = "cli-$SFX" ]; chk $? "list-state-machines lists it" "$out"
A describe-state-machine --state-machine-arn "$SM-nope" >/dev/null 2>/tmp/sfn-cli.err; rc=$?; grep -q StateMachineDoesNotExist /tmp/sfn-cli.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "describe unknown → StateMachineDoesNotExist" "$(cat /tmp/sfn-cli.err)"
A update-state-machine --state-machine-arn "$SM" --role-arn "${ROLE}2" >/dev/null 2>&1; chk $? "update-state-machine"
out=$(A describe-state-machine --state-machine-arn "$SM" --query roleArn --output text 2>&1); [ "$out" = "${ROLE}2" ]; chk $? "update is visible" "$out"

EX=$(A start-execution --state-machine-arn "$SM" --name run-ok --input '{"go":true}' --query executionArn --output text 2>&1); chk $? "start-execution" "$EX"
out=$(A describe-execution --execution-arn "$EX" --query status --output text 2>&1); [ "$out" = "SUCCEEDED" ]; chk $? "execution SUCCEEDED" "$out"
out=$(A describe-execution --execution-arn "$EX" --query output --output text 2>&1); echo "$out" | grep -q '"msg":"hi"'; chk $? "output carries the ResultPath data" "$out"
EX2=$(A start-execution --state-machine-arn "$SM" --name run-bad --input '{"go":false}' --query executionArn --output text 2>&1)
out=$(A describe-execution --execution-arn "$EX2" --query "[status,error,cause]" --output text 2>&1); [ "$out" = "$(printf 'FAILED\tNotGo\tgo was false')" ]; chk $? "Fail state → FAILED with error and cause" "$out"
out=$(A list-executions --state-machine-arn "$SM" --status-filter FAILED --query "length(executions)" --output text 2>&1); [ "$out" = "1" ]; chk $? "list-executions --status-filter" "$out"
out=$(A get-execution-history --execution-arn "$EX" --query "events[0].type" --output text 2>&1); [ "$out" = "ExecutionStarted" ]; chk $? "get-execution-history" "$out"

VER=$(A publish-state-machine-version --state-machine-arn "$SM" --query stateMachineVersionArn --output text 2>&1); chk $? "publish-state-machine-version" "$VER"
AL=$(A create-state-machine-alias --name prod --routing-configuration "stateMachineVersionArn=$VER,weight=100" --query stateMachineAliasArn --output text 2>&1); chk $? "create-state-machine-alias" "$AL"
A start-execution --state-machine-arn "$AL" --input '{"go":true}' >/dev/null 2>&1; chk $? "start-execution through the alias"
A delete-state-machine-alias --state-machine-alias-arn "$AL" >/dev/null 2>&1; chk $? "delete-state-machine-alias"

A tag-resource --resource-arn "$SM" --tags key=team,value=x >/dev/null 2>&1; chk $? "tag-resource"
out=$(A list-tags-for-resource --resource-arn "$SM" --query "tags[?key=='team'].value" --output text 2>&1); [ "$out" = "x" ]; chk $? "list-tags-for-resource" "$out"
A untag-resource --resource-arn "$SM" --tag-keys team >/dev/null 2>&1; chk $? "untag-resource"

ACT=$(A create-activity --name "cli-act-$SFX" --query activityArn --output text 2>&1); chk $? "create-activity" "$ACT"
out=$(A list-activities --query "activities[?activityArn=='$ACT'].name" --output text 2>&1); [ "$out" = "cli-act-$SFX" ]; chk $? "list-activities" "$out"
A delete-activity --activity-arn "$ACT" >/dev/null 2>&1; chk $? "delete-activity"

out=$(A validate-state-machine-definition --definition '{"StartAt":"x","States":{}}' --query result --output text 2>&1); [ "$out" = "FAIL" ]; chk $? "validate-state-machine-definition rejects a bad definition" "$out"
out=$(A validate-state-machine-definition --definition "$DEF" --query result --output text 2>&1); [ "$out" = "OK" ]; chk $? "validate-state-machine-definition accepts a good one" "$out"

A delete-state-machine --state-machine-arn "$SM" >/dev/null 2>&1; chk $? "delete-state-machine"
A describe-state-machine --state-machine-arn "$SM" >/dev/null 2>&1; [ $? -ne 0 ]; chk $? "describe after delete fails"

echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
