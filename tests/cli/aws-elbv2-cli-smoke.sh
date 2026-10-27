#!/usr/bin/env bash
# Real aws-cli ELBv2 smoke against Vyomi — the unmodified binary with only
# --endpoint-url pointed at the appliance. One [PASS]/[FAIL] line per check.
#
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-elbv2-cli-smoke.sh
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
el() { aws elbv2 --endpoint-url "$BASE" "$@" 2>&1; }
# q <expected-substring> <description> <aws args...>: run and look for a substring.
q() { local want="$1" what="$2"; shift 2; local out; out=$(el "$@"); local rc=$?
      if [ $rc -eq 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -q -- "$want"; }; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }
# v <description> <aws args...>: run, expect success, echo the text output via $OUT.
v() { local what="$1"; shift; OUT=$(el "$@"); local rc=$?
      if [ $rc -eq 0 ]; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$OUT" | head -c 300)"; OUT=""; fi; }

SFX=$(date +%s | tail -c 6)
LB="clb-$SFX"; TG="ctg-$SFX"
echo "== aws elbv2 against $BASE =="
aws --version 2>&1 | head -1

v "create-load-balancer" create-load-balancer --name "$LB" --subnets subnet-aaa111 subnet-bbb222 \
  --tags Key=env,Value=cli --query 'LoadBalancers[0].LoadBalancerArn' --output text
LBARN="$OUT"
q "$LB" "describe-load-balancers --names" describe-load-balancers --names "$LB"
q "application" "load balancer type is application" describe-load-balancers --load-balancer-arns "$LBARN" --query 'LoadBalancers[0].Type' --output text
q "us-east-1a" "availability zones are filled" describe-load-balancers --names "$LB" --query 'LoadBalancers[0].AvailabilityZones[].ZoneName' --output text
v "create-target-group" create-target-group --name "$TG" --protocol HTTP --port 80 \
  --vpc-id "$(el describe-load-balancers --names "$LB" --query 'LoadBalancers[0].VpcId' --output text)" \
  --health-check-path /healthz --query 'TargetGroups[0].TargetGroupArn' --output text
TGARN="$OUT"
q "/healthz" "describe-target-groups shows the health-check path" describe-target-groups --target-group-arns "$TGARN"
q "$TG" "modify-target-group" modify-target-group --target-group-arn "$TGARN" --health-check-interval-seconds 20
q "" "register-targets" register-targets --target-group-arn "$TGARN" --targets Id=i-0123456789abcdef0
q "unused" "describe-target-health (not attached yet)" describe-target-health --target-group-arn "$TGARN"
v "create-listener" create-listener --load-balancer-arn "$LBARN" --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn="$TGARN" --query 'Listeners[0].ListenerArn' --output text
LSARN="$OUT"
q "healthy" "describe-target-health (attached)" describe-target-health --target-group-arn "$TGARN"
q "$TGARN" "describe-listeners" describe-listeners --load-balancer-arn "$LBARN"
v "create-rule" create-rule --listener-arn "$LSARN" --priority 5 \
  --conditions Field=path-pattern,Values=/static/* \
  --actions Type=fixed-response,FixedResponseConfig='{StatusCode=200,ContentType=text/plain,MessageBody=hi}' \
  --query 'Rules[0].RuleArn' --output text
RULEARN="$OUT"
q "/static/" "describe-rules" describe-rules --listener-arn "$LSARN"
q "" "set-rule-priorities" set-rule-priorities --rule-priorities RuleArn="$RULEARN",Priority=7
q "" "delete-rule" delete-rule --rule-arn "$RULEARN"
q "" "add-tags" add-tags --resource-arns "$LBARN" --tags Key=team,Value=platform
q "platform" "describe-tags" describe-tags --resource-arns "$LBARN"
q "" "remove-tags" remove-tags --resource-arns "$LBARN" --tag-keys team
q "idle_timeout" "describe-load-balancer-attributes" describe-load-balancer-attributes --load-balancer-arn "$LBARN"
q "ELBSecurityPolicy" "describe-ssl-policies" describe-ssl-policies
out=$(el delete-target-group --target-group-arn "$TGARN"); echo "$out" | grep -q ResourceInUse && chk 0 "delete-target-group while in use is refused" || chk 1 "delete-target-group while in use is refused" "$out"
q "" "delete-listener" delete-listener --listener-arn "$LSARN"
q "" "deregister-targets" deregister-targets --target-group-arn "$TGARN" --targets Id=i-0123456789abcdef0
q "" "delete-target-group" delete-target-group --target-group-arn "$TGARN"
q "" "delete-load-balancer" delete-load-balancer --load-balancer-arn "$LBARN"
out=$(el describe-load-balancers --names "$LB"); echo "$out" | grep -q LoadBalancerNotFound && chk 0 "load balancer gone after delete" || chk 1 "load balancer gone after delete" "$out"

echo "elbv2 cli: $pass passed, $fail failed"
[ "$fail" = "0" ]
