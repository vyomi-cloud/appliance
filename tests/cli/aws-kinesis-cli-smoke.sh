#!/usr/bin/env bash
# Real aws-cli smoke for Amazon Kinesis Data Streams against Vyomi: the unmodified
# binary with only --endpoint-url changed.
#
#   ENDPOINT=http://localhost:9000 bash tests/cli/aws-kinesis-cli-smoke.sh
#
# One [PASS]/[FAIL] line per check; exit 1 on any failure.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_PAGER=""

if ! command -v aws >/dev/null 2>&1; then
    echo "[FAIL] aws-cli is not installed"
    exit 1
fi

NAME="cli-kin-$(date +%s)"
fail=0
k() { aws --endpoint-url "$BASE" kinesis "$@"; }
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
q() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

out=$(k create-stream --stream-name "$NAME" --shard-count 2 2>&1); chk $? "create-stream" "$out"
out=$(k create-stream --stream-name "$NAME" --shard-count 1 2>&1); echo "$out" | grep -q ResourceInUseException; chk $? "duplicate create-stream -> ResourceInUseException" "$out"
out=$(k list-streams 2>&1); echo "$out" | grep -q "$NAME"; chk $? "list-streams shows the stream" "$out"
out=$(k describe-stream-summary --stream-name "$NAME" 2>&1)
[ "$(echo "$out" | q "d['StreamDescriptionSummary']['OpenShardCount']" 2>/dev/null)" = "2" ]; chk $? "describe-stream-summary: 2 open shards" "$out"
out=$(k describe-stream --stream-name "$NAME" 2>&1)
SHARD=$(echo "$out" | q "d['StreamDescription']['Shards'][0]['ShardId']" 2>/dev/null)
[ "$SHARD" = "shardId-000000000000" ]; chk $? "describe-stream lists shardId-000000000000" "$out"

DATA=$(printf 'hello-cli' | base64)
out=$(k put-record --stream-name "$NAME" --partition-key pk --data "$DATA" --explicit-hash-key 0 2>&1)
SEQ=$(echo "$out" | q "d['SequenceNumber']" 2>/dev/null)
[ "${#SEQ}" = "56" ]; chk $? "put-record returns a 56-digit sequence number" "$out"
out=$(k put-records --stream-name "$NAME" --records "PartitionKey=a,Data=$DATA,ExplicitHashKey=0" "PartitionKey=b,Data=$DATA,ExplicitHashKey=0" 2>&1)
[ "$(echo "$out" | q "d['FailedRecordCount']" 2>/dev/null)" = "0" ]; chk $? "put-records (2 records)" "$out"

IT=$(k get-shard-iterator --stream-name "$NAME" --shard-id shardId-000000000000 --shard-iterator-type TRIM_HORIZON 2>&1 | q "d['ShardIterator']" 2>/dev/null)
out=$(k get-records --shard-iterator "$IT" 2>&1)
[ "$(echo "$out" | q "len(d['Records'])" 2>/dev/null)" = "3" ]; chk $? "get-records reads the 3 records back" "$out"
[ "$(echo "$out" | q "d['Records'][0]['Data']" 2>/dev/null)" = "hello-cli" ] || [ "$(echo "$out" | q "d['Records'][0]['Data']" 2>/dev/null)" = "$DATA" ]; chk $? "get-records returns the record data" "$out"

out=$(k increase-stream-retention-period --stream-name "$NAME" --retention-period-hours 48 2>&1); chk $? "increase-stream-retention-period" "$out"
out=$(k describe-stream-summary --stream-name "$NAME" 2>&1)
[ "$(echo "$out" | q "d['StreamDescriptionSummary']['RetentionPeriodHours']" 2>/dev/null)" = "48" ]; chk $? "retention is 48 hours" "$out"
out=$(k add-tags-to-stream --stream-name "$NAME" --tags env=dev,team=core 2>&1); chk $? "add-tags-to-stream" "$out"
out=$(k list-tags-for-stream --stream-name "$NAME" 2>&1)
[ "$(echo "$out" | q "len(d['Tags'])" 2>/dev/null)" = "2" ]; chk $? "list-tags-for-stream" "$out"
out=$(k update-shard-count --stream-name "$NAME" --target-shard-count 4 --scaling-type UNIFORM_SCALING 2>&1); chk $? "update-shard-count 2 -> 4" "$out"
out=$(k list-shards --stream-name "$NAME" 2>&1)
[ "$(echo "$out" | q "len(d['Shards'])" 2>/dev/null)" = "6" ]; chk $? "list-shards: 2 closed parents + 4 children" "$out"

ARN=$(k describe-stream-summary --stream-name "$NAME" 2>&1 | q "d['StreamDescriptionSummary']['StreamARN']" 2>/dev/null)
out=$(k register-stream-consumer --stream-arn "$ARN" --consumer-name analytics 2>&1); chk $? "register-stream-consumer" "$out"
out=$(k list-stream-consumers --stream-arn "$ARN" 2>&1); echo "$out" | grep -q analytics; chk $? "list-stream-consumers" "$out"
out=$(k delete-stream --stream-name "$NAME" 2>&1); echo "$out" | grep -q ResourceInUseException; chk $? "delete-stream blocked by the consumer" "$out"
out=$(k delete-stream --stream-name "$NAME" --enforce-consumer-deletion 2>&1); chk $? "delete-stream --enforce-consumer-deletion" "$out"
out=$(k describe-stream --stream-name "$NAME" 2>&1); echo "$out" | grep -q ResourceNotFoundException; chk $? "describe-stream after delete -> ResourceNotFoundException" "$out"

[ "$fail" = "0" ] && echo "all checks passed" || echo "$fail check(s) failed"
exit $((fail > 0))
