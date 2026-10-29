#!/usr/bin/env bash
# Real aws-cli smoke for CloudWatch Logs against Vyomi (endpoint override only).
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-logs-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
command -v aws >/dev/null 2>&1 || { echo "[FAIL] aws-cli installed"; exit 1; }

fail=0
ok()  { echo "[PASS] $1"; }
bad() { echo "[FAIL] $1 :: $2"; fail=$((fail+1)); }
L() { aws --endpoint-url "$BASE" logs "$@" 2>&1; }
chk() { # name, expected-substring, command...
  local name="$1" want="$2"; shift 2
  local out; out="$("$@")"; local rc=$?
  if [ $rc -eq 0 ] && { [ -z "$want" ] || echo "$out" | grep -q -- "$want"; }; then ok "$name"; else bad "$name" "$(echo "$out" | head -c 200)"; fi
}

G="/vyomi/cli-$(date +%s)-$$"
NOW=$(( $(date +%s) * 1000 ))
chk "create-log-group" "" L create-log-group --log-group-name "$G" --tags env=dev
chk "describe-log-groups lists it" "$G" L describe-log-groups --log-group-name-prefix "$G"
out="$(L create-log-group --log-group-name "$G")"; echo "$out" | grep -q ResourceAlreadyExistsException && ok "duplicate group → ResourceAlreadyExistsException" || bad "duplicate group → ResourceAlreadyExistsException" "$out"
chk "put-retention-policy" "" L put-retention-policy --log-group-name "$G" --retention-in-days 7
chk "retention visible" '"retentionInDays": 7' L describe-log-groups --log-group-name-prefix "$G"
chk "create-log-stream" "" L create-log-stream --log-group-name "$G" --log-stream-name web-1
chk "put-log-events" "nextSequenceToken" L put-log-events --log-group-name "$G" --log-stream-name web-1 \
  --log-events "timestamp=$NOW,message=GET /index 200" "timestamp=$((NOW+1)),message=GET /boom 500 ERROR"
chk "describe-log-streams" "web-1" L describe-log-streams --log-group-name "$G"
chk "get-log-events" "GET /index 200" L get-log-events --log-group-name "$G" --log-stream-name web-1 --start-from-head
out="$(L filter-log-events --log-group-name "$G" --filter-pattern ERROR)"
{ echo "$out" | grep -q "500 ERROR" && ! echo "$out" | grep -q "/index 200"; } && ok "filter-log-events ERROR" || bad "filter-log-events ERROR" "$out"
chk "put-metric-filter" "" L put-metric-filter --log-group-name "$G" --filter-name errs --filter-pattern ERROR \
  --metric-transformations metricName=Errors,metricNamespace=Vyomi,metricValue=1
chk "describe-metric-filters" "errs" L describe-metric-filters --log-group-name "$G"
chk "delete-metric-filter" "" L delete-metric-filter --log-group-name "$G" --filter-name errs
chk "tag-log-group + list-tags-log-group" "team" bash -c "aws --endpoint-url $BASE logs tag-log-group --log-group-name '$G' --tags team=x && aws --endpoint-url $BASE logs list-tags-log-group --log-group-name '$G'"
QID="$(L start-query --log-group-name "$G" --start-time $((NOW/1000-60)) --end-time $((NOW/1000+60)) --query-string 'fields @message | filter @message like /ERROR/' --query 'queryId' --output text)"
[ -n "$QID" ] && ok "start-query" || bad "start-query" "no queryId"
chk "get-query-results" "500 ERROR" L get-query-results --query-id "$QID"
chk "delete-log-stream" "" L delete-log-stream --log-group-name "$G" --log-stream-name web-1
chk "delete-log-group" "" L delete-log-group --log-group-name "$G"
out="$(L describe-log-streams --log-group-name "$G")"; echo "$out" | grep -q ResourceNotFoundException && ok "deleted group → ResourceNotFoundException" || bad "deleted group → ResourceNotFoundException" "$out"
[ $fail -eq 0 ]
