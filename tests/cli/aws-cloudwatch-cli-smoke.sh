#!/usr/bin/env bash
# Real aws-cli CloudWatch smoke against Vyomi: only --endpoint-url is changed.
# aws-cli v2 speaks smithy-rpc-v2-cbor to CloudWatch, so this exercises the CBOR wire.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-cloudwatch-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
if ! command -v aws >/dev/null 2>&1; then echo "SKIP aws-cli not installed"; exit 0; fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
cw() { aws --endpoint-url "$BASE" cloudwatch "$@"; }

S="$$"
NS="CliApp$S"
A="cli-alarm-$S"
D="cli-dash-$S"
T="$(mktemp -d)"
echo '{"widgets":[{"type":"text","x":0,"y":0,"width":6,"height":3,"properties":{"markdown":"cli"}}]}' > "$T/dash.json"

echo "== aws-cli cloudwatch against $BASE =="
out=$(cw put-metric-data --namespace "$NS" --metric-name Latency --dimensions Service=cart --value 250 --unit Milliseconds 2>&1); chk $? "put-metric-data" "$out"
out=$(cw put-metric-data --namespace "$NS" --metric-name Latency --dimensions Service=cart --statistic-values Sum=100,Minimum=10,Maximum=90,SampleCount=2 2>&1); chk $? "put-metric-data --statistic-values" "$out"
out=$(cw list-metrics --namespace "$NS" --query 'Metrics[0].MetricName' --output text 2>&1); chk $([ "$out" = "Latency" ]; echo $?) "list-metrics" "$out"
out=$(cw list-metrics --namespace "$NS" --query 'Metrics[0].Dimensions[0].Value' --output text 2>&1); chk $([ "$out" = "cart" ]; echo $?) "list-metrics shows dimensions" "$out"
# python, not `date -d` (GNU-only): the suite also runs on macOS.
iso() { python3 -c "import datetime as d,sys;print((d.datetime.now(d.timezone.utc)+d.timedelta(minutes=int(sys.argv[1]))).strftime('%Y-%m-%dT%H:%M:%SZ'))" "$1"; }
START=$(iso -10); END=$(iso 2)
out=$(cw get-metric-statistics --namespace "$NS" --metric-name Latency --dimensions Name=Service,Value=cart --start-time "$START" --end-time "$END" --period 3600 --statistics Sum SampleCount --query 'sum(Datapoints[].Sum)' --output text 2>&1); chk $([ "$out" = "350.0" ]; echo $?) "get-metric-statistics Sum=350" "$out"
out=$(cw get-metric-statistics --namespace "$NS" --metric-name Latency --dimensions Name=Service,Value=cart --start-time "$START" --end-time "$END" --period 3600 --statistics SampleCount --query 'sum(Datapoints[].SampleCount)' --output text 2>&1); chk $([ "$out" = "3.0" ]; echo $?) "get-metric-statistics SampleCount=3" "$out"
out=$(cw get-metric-data --start-time "$START" --end-time "$END" --metric-data-queries "[{\"Id\":\"m\",\"MetricStat\":{\"Metric\":{\"Namespace\":\"$NS\",\"MetricName\":\"Latency\",\"Dimensions\":[{\"Name\":\"Service\",\"Value\":\"cart\"}]},\"Period\":3600,\"Stat\":\"Maximum\"}}]" --query 'MetricDataResults[0].Values[0]' --output text 2>&1); chk $([ "$out" = "250.0" ]; echo $?) "get-metric-data Maximum=250" "$out"

out=$(cw put-metric-alarm --alarm-name "$A" --namespace "$NS" --metric-name Latency --dimensions Name=Service,Value=cart --statistic Maximum --period 60 --evaluation-periods 1 --threshold 200 --comparison-operator GreaterThanThreshold --alarm-actions arn:aws:sns:us-east-1:123456789012:cli --tags Key=team,Value=cli 2>&1); chk $? "put-metric-alarm" "$out"
out=$(cw describe-alarms --alarm-names "$A" --query 'MetricAlarms[0].StateValue' --output text 2>&1); chk $([ "$out" = "ALARM" ]; echo $?) "alarm evaluated against existing data → ALARM" "$out"
out=$(cw describe-alarms --alarm-names "$A" --query 'MetricAlarms[0].[Threshold,Period,ComparisonOperator]' --output text 2>&1); chk $([[ "$out" == *"200.0"*"60"*"GreaterThanThreshold"* ]]; echo $?) "describe-alarms fields" "$out"
out=$(cw set-alarm-state --alarm-name "$A" --state-value OK --state-reason "cli reset" 2>&1); chk $? "set-alarm-state" "$out"
out=$(cw describe-alarms --state-value OK --alarm-name-prefix "cli-alarm-$S" --query 'MetricAlarms[0].StateReason' --output text 2>&1); chk $([ "$out" = "cli reset" ]; echo $?) "describe-alarms --state-value OK" "$out"
out=$(cw describe-alarm-history --alarm-name "$A" --history-item-type StateUpdate --query 'length(AlarmHistoryItems)' --output text 2>&1); chk $([ "${out:-0}" -ge 2 ] 2>/dev/null; echo $?) "describe-alarm-history" "$out"
out=$(cw describe-alarms-for-metric --namespace "$NS" --metric-name Latency --dimensions Name=Service,Value=cart --query 'length(MetricAlarms)' --output text 2>&1); chk $([ "$out" = "1" ]; echo $?) "describe-alarms-for-metric" "$out"
out=$(cw disable-alarm-actions --alarm-names "$A" 2>&1); chk $? "disable-alarm-actions" "$out"
out=$(cw describe-alarms --alarm-names "$A" --query 'MetricAlarms[0].ActionsEnabled' --output text 2>&1); chk $([ "$out" = "False" ]; echo $?) "actions are disabled" "$out"
out=$(cw enable-alarm-actions --alarm-names "$A" 2>&1); chk $? "enable-alarm-actions" "$out"
out=$(cw list-tags-for-resource --resource-arn "arn:aws:cloudwatch:us-east-1:123456789012:alarm:$A" --query 'Tags[0].Key' --output text 2>&1); chk $([ "$out" = "team" ]; echo $?) "list-tags-for-resource" "$out"
out=$(cw tag-resource --resource-arn "arn:aws:cloudwatch:us-east-1:123456789012:alarm:$A" --tags Key=env,Value=ci 2>&1); chk $? "tag-resource" "$out"
out=$(cw untag-resource --resource-arn "arn:aws:cloudwatch:us-east-1:123456789012:alarm:$A" --tag-keys env 2>&1); chk $? "untag-resource" "$out"
out=$(cw put-composite-alarm --alarm-name "$A-comp" --alarm-rule "OK(\"$A\")" 2>&1); chk $? "put-composite-alarm" "$out"
out=$(cw describe-alarms --alarm-types CompositeAlarm --alarm-names "$A-comp" --query 'CompositeAlarms[0].StateValue' --output text 2>&1); chk $([ "$out" = "ALARM" ]; echo $?) "composite alarm follows its rule" "$out"

out=$(cw put-dashboard --dashboard-name "$D" --dashboard-body "file://$T/dash.json" 2>&1); chk $? "put-dashboard" "$out"
out=$(cw get-dashboard --dashboard-name "$D" --query 'DashboardName' --output text 2>&1); chk $([ "$out" = "$D" ]; echo $?) "get-dashboard" "$out"
out=$(cw list-dashboards --dashboard-name-prefix "cli-dash-$S" --query 'DashboardEntries[0].DashboardName' --output text 2>&1); chk $([ "$out" = "$D" ]; echo $?) "list-dashboards" "$out"
out=$(cw delete-dashboards --dashboard-names "$D" 2>&1); chk $? "delete-dashboards" "$out"
out=$(cw get-dashboard --dashboard-name "$D" 2>&1); chk $([[ "$out" == *ResourceNotFound* ]]; echo $?) "get-dashboard after delete → ResourceNotFound" "$out"

out=$(cw delete-alarms --alarm-names "$A" 2>&1); chk $([[ "$out" == *ResourceConflict* ]]; echo $?) "delete-alarms keeps an alarm a composite uses" "$out"
out=$(cw delete-alarms --alarm-names "$A-comp" "$A" 2>&1); chk $? "delete-alarms" "$out"
out=$(cw describe-alarms --alarm-names "$A" --query 'length(MetricAlarms)' --output text 2>&1); chk $([ "$out" = "0" ]; echo $?) "alarm is gone" "$out"
# Older CLIs send it and the service answers MissingParameter; newer ones (2.3x) refuse it client-side.
out=$(cw put-metric-alarm --alarm-name "$A-bad" 2>&1); chk $([[ "$out" == *MissingParameter* || "$out" == *"arguments are required"*"--comparison-operator"* ]]; echo $?) "put-metric-alarm without a comparison operator → MissingParameter" "$out"

rm -rf "$T"
echo; echo "$pass passed, $fail failed"
[ "$fail" = "0" ]
