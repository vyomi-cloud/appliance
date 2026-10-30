#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Monitor (Microsoft.Insights) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider.
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-mon-$SFX"
AG="cliag$SFX"; ALERT="clicpu$SFX"; ACT="cliact$SFX"; AS="cliasc$SFX"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Insights"
VM="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Compute/virtualMachines/vm$SFX"
AGID="/subscriptions/$SUB/resourceGroups/$RG/providers/microsoft.insights/actionGroups/$AG"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method put --url "$P/actionGroups/$AG?api-version=2023-01-01" --body '{"location":"Global","tags":{"env":"cli"},"properties":{"groupShortName":"cliag","enabled":true,"emailReceivers":[{"name":"oncall","emailAddress":"oncall@example.com","useCommonAlertSchema":true}],"webhookReceivers":[{"name":"hook","serviceUri":"https://example.com/hook"}]}}')
echo "$out" | grep -q '"groupShortName": "cliag"' && [ "$(echo "$out" | jq_ 'd["properties"]["emailReceivers"][0]["status"]')" = "Enabled" ]
chk $? "az rest PUT actionGroups (email receiver Enabled)" "$out"
out=$(rest --method get --url "$P/actionGroups/$AG?api-version=2023-01-01"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET action group returns tags" "$out"
out=$(rest --method put --url "$P/actionGroups/bad$SFX?api-version=2023-01-01" --body '{"location":"Global","properties":{"groupShortName":"waytoolongshortname","enabled":true}}'); echo "$out" | grep -q 'BadRequest'
chk $? "groupShortName over 12 characters → BadRequest" "$out"
out=$(rest --method patch --url "$P/actionGroups/$AG?api-version=2023-01-01" --body '{"properties":{"enabled":false}}'); [ "$(echo "$out" | jq_ 'd["properties"]["enabled"]')" = "False" ]
chk $? "PATCH disables the action group" "$out"
out=$(rest --method get --url "$P/actionGroups?api-version=2023-01-01"); echo "$out" | grep -q "\"$AG\""
chk $? "list action groups in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.Insights/actionGroups?api-version=2023-01-01"); echo "$out" | grep -q "\"$AG\""
chk $? "list action groups in the subscription" "$out"
out=$(rest --method post --url "$P/actionGroups/$AG/subscribe?api-version=2023-01-01" --body '{"receiverName":"oncall"}'); echo "$out" | grep -q 'Conflict'
chk $? "enabling an already-enabled receiver → Conflict" "$out"

out=$(rest --method put --url "$P/metricAlerts/$ALERT?api-version=2018-03-01" --body '{"location":"global","properties":{"description":"cpu","severity":3,"enabled":true,"scopes":["'$VM'"],"evaluationFrequency":"PT1M","windowSize":"PT5M","criteria":{"odata.type":"Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria","allOf":[{"criterionType":"StaticThresholdCriterion","name":"HighCpu","metricName":"Percentage CPU","operator":"GreaterThan","threshold":80,"timeAggregation":"Average"}]},"actions":[{"actionGroupId":"'$AGID'"}]}}')
echo "$out" | grep -q '"autoMitigate": true' && echo "$out" | grep -q '"lastUpdatedTime"'
chk $? "create metric alert (autoMitigate default, lastUpdatedTime)" "$out"
out=$(rest --method get --url "$P/metricAlerts/$ALERT?api-version=2018-03-01"); [ "$(echo "$out" | jq_ 'd["properties"]["criteria"]["allOf"][0]["threshold"]')" = "80" ]
chk $? "GET metric alert returns the criteria" "$out"
out=$(rest --method put --url "$P/metricAlerts/bad$SFX?api-version=2018-03-01" --body '{"location":"global","properties":{"severity":7,"enabled":true,"scopes":["'$VM'"],"evaluationFrequency":"PT1M","windowSize":"PT5M","criteria":{"allOf":[]}}}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid metric alert → BadRequest" "$out"
out=$(rest --method patch --url "$P/metricAlerts/$ALERT?api-version=2018-03-01" --body '{"properties":{"severity":1}}'); [ "$(echo "$out" | jq_ 'd["properties"]["severity"]')" = "1" ] && [ "$(echo "$out" | jq_ 'len(d["properties"]["criteria"]["allOf"])')" = "1" ]
chk $? "PATCH metric alert changes severity and keeps criteria" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.Insights/metricAlerts?api-version=2018-03-01"); echo "$out" | grep -q "\"$ALERT\""
chk $? "list metric alerts in the subscription" "$out"

out=$(rest --method put --url "$P/activityLogAlerts/$ACT?api-version=2020-10-01" --body '{"location":"Global","properties":{"scopes":["/subscriptions/'$SUB'"],"enabled":true,"condition":{"allOf":[{"field":"category","equals":"Administrative"},{"field":"status","equals":"Failed"}]},"actions":{"actionGroups":[{"actionGroupId":"'$AGID'"}]}}}')
echo "$out" | grep -q '"category"'
chk $? "create activity log alert" "$out"
out=$(rest --method put --url "$P/activityLogAlerts/bad$SFX?api-version=2020-10-01" --body '{"location":"Global","properties":{"scopes":["/subscriptions/'$SUB'"],"condition":{"allOf":[{"field":"status","equals":"Failed"}]}}}'); echo "$out" | grep -q 'BadRequest'
chk $? "activity log alert without a category → BadRequest" "$out"

out=$(rest --method put --url "$P/autoscaleSettings/$AS?api-version=2022-10-01" --body '{"location":"eastus","properties":{"enabled":true,"targetResourceUri":"'$VM'","profiles":[{"name":"default","capacity":{"minimum":"1","maximum":"5","default":"2"},"rules":[]}]}}')
[ "$(echo "$out" | jq_ 'd["properties"]["profiles"][0]["capacity"]["maximum"]')" = "5" ]
chk $? "create autoscale setting" "$out"

out=$(rest --method delete --url "$P/autoscaleSettings/$AS?api-version=2022-10-01"); chk $? "delete autoscale setting" "$out"
out=$(rest --method delete --url "$P/activityLogAlerts/$ACT?api-version=2020-10-01"); chk $? "delete activity log alert" "$out"
out=$(rest --method delete --url "$P/metricAlerts/$ALERT?api-version=2018-03-01"); chk $? "delete metric alert" "$out"
out=$(rest --method get --url "$P/metricAlerts/$ALERT?api-version=2018-03-01"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted metric alert → ResourceNotFound" "$out"
out=$(rest --method delete --url "$P/actionGroups/$AG?api-version=2023-01-01"); chk $? "delete action group" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
