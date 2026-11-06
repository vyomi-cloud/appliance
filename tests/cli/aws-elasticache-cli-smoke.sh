#!/usr/bin/env bash
# Real aws-cli ElastiCache smoke against Vyomi — the unmodified binary with only
# --endpoint-url pointed at the appliance. One [PASS]/[FAIL] line per check.
#
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-elasticache-cli-smoke.sh
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

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }
ec() { aws elasticache --endpoint-url "$BASE" "$@" 2>&1; }
# q <expected-substring> <description> <aws args...>: run and look for a substring.
q() { local want="$1" what="$2"; shift 2; local out; out=$(ec "$@"); local rc=$?
      if [ $rc -eq 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -q -- "$want"; }; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }

SFX=$(date +%s | tail -c 6)
SG="csg-$SFX"; PG="cpg-$SFX"; CL="ccache-$SFX"; RG="crg-$SFX"; SNAP="csnap-$SFX"
echo "== aws elasticache against $BASE =="
aws --version 2>&1 | head -1

q "$SG" "create-cache-subnet-group" create-cache-subnet-group --cache-subnet-group-name "$SG" \
  --cache-subnet-group-description "cli test" --subnet-ids subnet-aaa111 subnet-bbb222
q "subnet-bbb222" "describe-cache-subnet-groups" describe-cache-subnet-groups --cache-subnet-group-name "$SG"
q "$PG" "create-cache-parameter-group" create-cache-parameter-group --cache-parameter-group-name "$PG" \
  --cache-parameter-group-family valkey8 --description "cli test"
q "$PG" "modify-cache-parameter-group" modify-cache-parameter-group --cache-parameter-group-name "$PG" \
  --parameter-name-values ParameterName=timeout,ParameterValue=60
q "60" "describe-cache-parameters shows the new value" describe-cache-parameters --cache-parameter-group-name "$PG"
q "available" "create-cache-cluster" create-cache-cluster --cache-cluster-id "$CL" --engine valkey \
  --cache-node-type cache.t3.micro --num-cache-nodes 1 --cache-subnet-group-name "$SG" --cache-parameter-group-name "$PG"
q "Endpoint" "describe-cache-clusters --show-cache-node-info" describe-cache-clusters --cache-cluster-id "$CL" --show-cache-node-info
ARN=$(ec describe-cache-clusters --cache-cluster-id "$CL" --query 'CacheClusters[0].ARN' --output text)
case "$ARN" in arn:aws:elasticache:*) chk 0 "cluster ARN is well formed";; *) chk 1 "cluster ARN is well formed" "$ARN";; esac
q "cache.t3.small" "modify-cache-cluster node type" modify-cache-cluster --cache-cluster-id "$CL" --cache-node-type cache.t3.small --apply-immediately
q "$CL" "reboot-cache-cluster" reboot-cache-cluster --cache-cluster-id "$CL" --cache-node-ids-to-reboot 0001
q "team" "add-tags-to-resource" add-tags-to-resource --resource-name "$ARN" --tags Key=team,Value=platform
q "platform" "list-tags-for-resource" list-tags-for-resource --resource-name "$ARN"
q "TagList" "remove-tags-from-resource" remove-tags-from-resource --resource-name "$ARN" --tag-keys team
q "$SNAP" "create-snapshot" create-snapshot --snapshot-name "$SNAP" --cache-cluster-id "$CL"
q "available" "describe-snapshots" describe-snapshots --snapshot-name "$SNAP"
q "$RG" "create-replication-group" create-replication-group --replication-group-id "$RG" \
  --replication-group-description "cli rg" --engine valkey --cache-node-type cache.t3.micro --num-cache-clusters 2 \
  --automatic-failover-enabled
q "PrimaryEndpoint" "describe-replication-groups" describe-replication-groups --replication-group-id "$RG"
q "valkey" "describe-cache-engine-versions" describe-cache-engine-versions --engine valkey
q "Events" "describe-events" describe-events
out=$(ec describe-cache-clusters --cache-cluster-id "nope-$SFX"); echo "$out" | grep -q "CacheClusterNotFound" && chk 0 "missing cluster -> CacheClusterNotFound" || chk 1 "missing cluster -> CacheClusterNotFound" "$out"
q "$SNAP" "delete-snapshot" delete-snapshot --snapshot-name "$SNAP"
q "$RG" "delete-replication-group" delete-replication-group --replication-group-id "$RG"
q "$CL" "delete-cache-cluster" delete-cache-cluster --cache-cluster-id "$CL"
q "" "delete-cache-parameter-group" delete-cache-parameter-group --cache-parameter-group-name "$PG"
q "" "delete-cache-subnet-group" delete-cache-subnet-group --cache-subnet-group-name "$SG"
out=$(ec describe-cache-clusters --query "CacheClusters[?CacheClusterId=='$CL']" --output text); [ -z "$out" ] && chk 0 "cluster gone after delete" || chk 1 "cluster gone after delete" "$out"

# Data plane (only when a Redis-protocol client is installed and the shared Valkey is up):
if command -v valkey-cli >/dev/null 2>&1 || command -v redis-cli >/dev/null 2>&1; then
    CLI=$(command -v valkey-cli || command -v redis-cli)
    if "$CLI" -h "${VYOMI_VALKEY_HOST:-127.0.0.1}" -p "${VYOMI_VALKEY_PORT:-6379}" ping 2>/dev/null | grep -q PONG; then
        chk 0 "valkey data plane answers PING"
    else
        echo "[SKIP] valkey data plane not reachable (compose profile full not running)"
    fi
fi

echo "elasticache cli: $pass passed, $fail failed"
[ "$fail" = "0" ]
