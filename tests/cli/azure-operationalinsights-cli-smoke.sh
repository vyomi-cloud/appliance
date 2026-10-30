#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Log Analytics (Microsoft.OperationalInsights) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider.
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-law-$SFX"
WS="law-cli-$SFX"
AV="api-version=2022-10-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights"
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

out=$(rest --method put --url "$P/workspaces/$WS?$AV" --body '{"location":"eastus","tags":{"env":"cli"},"properties":{"sku":{"name":"PerGB2018"},"retentionInDays":60}}')
[ "$(echo "$out" | jq_ 'd["properties"]["retentionInDays"]')" = "60" ] && [ "$(echo "$out" | jq_ 'd["properties"]["provisioningState"]')" = "Succeeded" ]
chk $? "az rest PUT workspace (retention 60, Succeeded)" "$out"
[ -n "$(echo "$out" | jq_ 'd["properties"]["customerId"]')" ]
chk $? "workspace has a customerId" "$out"
out=$(rest --method get --url "$P/workspaces/$WS?$AV"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET workspace returns tags" "$out"
out=$(rest --method put --url "$P/workspaces/x?$AV" --body '{"location":"eastus","properties":{}}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid workspace name → BadRequest" "$out"
out=$(rest --method patch --url "$P/workspaces/$WS?$AV" --body '{"properties":{"retentionInDays":90}}'); [ "$(echo "$out" | jq_ 'd["properties"]["retentionInDays"]')" = "90" ]
chk $? "PATCH workspace retention" "$out"
out=$(rest --method get --url "$P/workspaces?$AV"); echo "$out" | grep -q "\"$WS\""
chk $? "list workspaces in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.OperationalInsights/workspaces?$AV"); echo "$out" | grep -q "\"$WS\""
chk $? "list workspaces in the subscription" "$out"

out=$(rest --method post --url "$P/workspaces/$WS/sharedKeys?$AV")
[ -n "$(echo "$out" | jq_ 'd["primarySharedKey"]')" ] && [ -n "$(echo "$out" | jq_ 'd["secondarySharedKey"]')" ]
chk $? "POST sharedKeys returns primary and secondary" "$out"
out=$(rest --method get --url "$P/workspaces/$WS/usages?$AV"); echo "$out" | grep -q 'DataAnalyzed'
chk $? "GET usages lists DataAnalyzed" "$out"

out=$(rest --method put --url "$P/workspaces/$WS/savedSearches/top-computers?$AV" --body '{"properties":{"category":"General","displayName":"Top computers","query":"Heartbeat | summarize count() by Computer","version":2}}')
echo "$out" | grep -q '"displayName": "Top computers"'
chk $? "create saved search" "$out"
out=$(rest --method put --url "$P/workspaces/$WS/savedSearches/bad?$AV" --body '{"properties":{"category":"General","displayName":"x"}}'); echo "$out" | grep -q 'BadRequest'
chk $? "saved search without query → BadRequest" "$out"
out=$(rest --method get --url "$P/workspaces/$WS/savedSearches?$AV"); echo "$out" | grep -q 'top-computers'
chk $? "list saved searches" "$out"

out=$(rest --method get --url "$P/workspaces/$WS/tables?$AV"); echo "$out" | grep -q '"Heartbeat"'
chk $? "built-in tables are listed" "$out"
out=$(rest --method put --url "$P/workspaces/$WS/tables/Orders_CL?$AV" --body '{"properties":{"retentionInDays":30,"totalRetentionInDays":90,"schema":{"name":"Orders_CL","columns":[{"name":"TimeGenerated","type":"dateTime"},{"name":"OrderId","type":"string"}]}}}')
[ "$(echo "$out" | jq_ 'd["properties"]["totalRetentionInDays"]')" = "90" ]
chk $? "create custom table Orders_CL" "$out"
out=$(rest --method patch --url "$P/workspaces/$WS/tables/Orders_CL?$AV" --body '{"properties":{"retentionInDays":45,"totalRetentionInDays":120}}'); [ "$(echo "$out" | jq_ 'd["properties"]["totalRetentionInDays"]')" = "120" ]
chk $? "PATCH table retention" "$out"
out=$(rest --method delete --url "$P/workspaces/$WS/tables/Heartbeat?$AV"); echo "$out" | grep -q 'BadRequest'
chk $? "deleting a built-in table → BadRequest" "$out"
out=$(rest --method delete --url "$P/workspaces/$WS/tables/Orders_CL?$AV"); chk $? "delete custom table" "$out"

out=$(rest --method delete --url "$P/workspaces/$WS?$AV"); chk $? "delete workspace" "$out"
out=$(rest --method get --url "$P/workspaces/$WS?$AV"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted workspace → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
