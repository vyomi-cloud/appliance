#!/usr/bin/env bash
# Real aws-cli smoke for Amazon ECS against the Vyomi appliance (only --endpoint-url changed).
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-ecs-cli-smoke.sh
# One [PASS]/[FAIL] line per check; exit 1 on any failure.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
command -v aws >/dev/null 2>&1 || { echo "[FAIL] aws-cli not installed"; exit 1; }

fails=0
ok()  { echo "[PASS] $1"; }
bad() { echo "[FAIL] $1 :: $2"; fails=$((fails+1)); }
ecs() { aws --endpoint-url "$BASE" ecs "$@" 2>&1; }
# expect <name> <needle> <aws ecs args...>: command must succeed and output contain needle
expect() { local n="$1" needle="$2"; shift 2; local out; out=$(ecs "$@"); local rc=$?
  if [ $rc -eq 0 ] && echo "$out" | grep -q -- "$needle"; then ok "$n"; else bad "$n" "rc=$rc ${out:0:200}"; fi; }

C="cli-smoke-$$"; FAM="cli-web-$$"; SVC="cli-svc-$$"
CDEF='[{"name":"web","image":"nginx:1.27","cpu":128,"memory":256,"essential":true,"portMappings":[{"containerPort":80}]}]'

expect "create-cluster" "$C" create-cluster --cluster-name "$C" --tags key=env,value=test
expect "describe-clusters" "ACTIVE" describe-clusters --clusters "$C"
expect "list-clusters" "cluster/$C" list-clusters
expect "register-task-definition" "$FAM" register-task-definition --family "$FAM" --container-definitions "$CDEF" --cpu 256 --memory 512 --network-mode awsvpc --requires-compatibilities FARGATE
expect "describe-task-definition" "nginx:1.27" describe-task-definition --task-definition "$FAM"
expect "list-task-definitions" "$FAM:1" list-task-definitions --family-prefix "$FAM"
expect "create-service" "$SVC" create-service --cluster "$C" --service-name "$SVC" --task-definition "$FAM" --desired-count 1 --launch-type FARGATE --network-configuration 'awsvpcConfiguration={subnets=[subnet-0a1b2c3d4e5f60718]}'
expect "describe-services" "ACTIVE" describe-services --cluster "$C" --services "$SVC"
expect "list-services" "$SVC" list-services --cluster "$C"
expect "update-service" '"desiredCount": 2' update-service --cluster "$C" --service "$SVC" --desired-count 2
RUN=$(ecs run-task --cluster "$C" --task-definition "$FAM" --launch-type FARGATE --network-configuration 'awsvpcConfiguration={subnets=[subnet-0a1b2c3d4e5f60718]}' --query 'tasks[0].taskArn' --output text)
case "$RUN" in arn:aws:ecs:*) ok "run-task";; *) bad "run-task" "$RUN";; esac
TASK="$RUN"
expect "list-tasks" "${RUN##*/}" list-tasks --cluster "$C" --desired-status RUNNING
expect "describe-tasks" "lastStatus" describe-tasks --cluster "$C" --tasks "$TASK"
expect "stop-task" "STOPPED" stop-task --cluster "$C" --task "$TASK" --reason smoke
ARN=$(ecs describe-clusters --clusters "$C" --query 'clusters[0].clusterArn' --output text)
expect "tag-resource" "" tag-resource --resource-arn "$ARN" --tags key=team,value=platform
expect "list-tags-for-resource" "platform" list-tags-for-resource --resource-arn "$ARN"
out=$(ecs describe-services --cluster "no-such-$$" --services x); echo "$out" | grep -q "ClusterNotFoundException" && ok "missing cluster -> ClusterNotFoundException" || bad "missing cluster error code" "${out:0:200}"
expect "delete-service" "$SVC" delete-service --cluster "$C" --service "$SVC" --force
expect "deregister-task-definition" "INACTIVE" deregister-task-definition --task-definition "$FAM:1"
expect "delete-cluster" "$C" delete-cluster --cluster "$C"
out=$(ecs list-clusters); echo "$out" | grep -q "cluster/$C\"" && bad "cluster gone after delete" "$out" || ok "cluster gone after delete"

[ $fails -eq 0 ] && echo "all checks passed" || echo "$fails check(s) failed"
[ $fails -eq 0 ]
