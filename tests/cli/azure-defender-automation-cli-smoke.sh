#!/usr/bin/env bash
# Real `az` CLI against Vyomi: subscription Activity-log export (az monitor diagnostic-settings subscription),
# Defender for Cloud workflow automation (az rest on Microsoft.Security/automations) and Resource Graph
# (az rest on Microsoft.ResourceGraph/resources) over an Event Grid topic. Endpoint override only.
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-auto-$SFX"
WS="cliws$SFX"
WSID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/$WS"
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
out=$(rest --method put --url "$BASE$WSID?api-version=2022-10-01" --body '{"location":"eastus","properties":{}}')
chk $? "create Log Analytics workspace" "$out"

# ── Activity log export: subscription diagnostic setting ──
D="$BASE/subscriptions/$SUB/providers/Microsoft.Insights/diagnosticSettings"
out=$(rest --method put --url "$D/cliexport?api-version=2021-05-01-preview" --body "{\"properties\":{\"workspaceId\":\"$WSID\",\"logs\":[{\"category\":\"Administrative\",\"enabled\":true}]}}")
[ "$(echo "$out" | jq_ 'd["name"]')" = "cliexport" ]
chk $? "PUT subscription diagnostic setting (Export Activity Logs)" "$out"
out=$(rest --method put --url "$D/clibad?api-version=2021-05-01-preview" --body "{\"properties\":{\"workspaceId\":\"$WSID\",\"logs\":[{\"category\":\"AuditEvent\",\"enabled\":true}]}}"); echo "$out" | grep -q 'BadRequest'
chk $? "a resource-log category is rejected at subscription scope" "$out"
out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG-b?api-version=2021-04-01" --body '{"location":"eastus"}')
out=$(rest --method post --url "$BASE$WSID/api/query?api-version=2022-10-01" --body "{\"query\":\"AzureDiagnostics | where Category == 'Administrative' | count\"}")
[ "$(echo "$out" | jq_ 'd["tables"][0]["rows"][0][0] >= 1')" = "True" ]
chk $? "the exported ARM write is a row in the workspace" "$out"
out=$(rest --method delete --url "$D/cliexport?api-version=2021-05-01-preview"); chk $? "DELETE the export setting" "$out"

# ── Workflow automation ──
A="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Security/automations"
BODY="{\"location\":\"eastus\",\"properties\":{\"isEnabled\":true,\"scopes\":[{\"description\":\"sub\",\"scopePath\":\"/subscriptions/$SUB\"}],\"sources\":[{\"eventSource\":\"Alerts\",\"ruleSets\":[{\"rules\":[{\"propertyJPath\":\"Severity\",\"propertyType\":\"String\",\"expectedValue\":\"Low\",\"operator\":\"GreaterThanOrEqualTo\"}]}]}],\"actions\":[{\"actionType\":\"Workspace\",\"workspaceResourceId\":\"$WSID\"}]}}"
out=$(rest --method put --url "$A/cliwf?api-version=2023-12-01-preview" --body "$BODY")
[ "$(echo "$out" | jq_ 'd["properties"]["actions"][0]["actionType"]')" = "Workspace" ]
chk $? "PUT workflow automation" "$out"
out=$(rest --method put --url "$A/clibad?api-version=2023-12-01-preview" --body '{"location":"eastus","properties":{"scopes":[],"sources":[],"actions":[]}}'); echo "$out" | grep -q 'InvalidRequestContent'
chk $? "an automation without scopes/sources/actions is rejected" "$out"
out=$(rest --method get --url "$A?api-version=2023-12-01-preview"); echo "$out" | grep -q '"cliwf"'
chk $? "list automations in the resource group" "$out"
S="$BASE/subscriptions/$SUB/providers/Microsoft.Security"
out=$(rest --method put --url "$S/pricings/StorageAccounts?api-version=2024-01-01" --body '{"properties":{"pricingTier":"Standard"}}'); chk $? "enable Defender for Storage" "$out"
SA="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/clisa$SFX"
out=$(rest --method put --url "$SA?api-version=2023-01-01" --body '{"location":"eastus","properties":{"allowBlobPublicAccess":false}}'); chk $? "create storage account" "$out"
out=$(rest --method patch --url "$SA?api-version=2023-01-01" --body '{"properties":{"allowBlobPublicAccess":true}}'); chk $? "open public blob access" "$out"
out=$(rest --method get --url "$S/alerts?api-version=2022-01-01"); echo "$out" | grep -q 'VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED'
chk $? "Defender raises the storage alert" "$out"
out=$(rest --method get --url "$A/cliwf/vyomiRuns?api-version=2023-12-01-preview")
[ "$(echo "$out" | jq_ 'd["value"][0]["status"]')" = "Succeeded" ]
chk $? "the automation ran for the alert" "$out"
out=$(rest --method post --url "$BASE$WSID/api/query?api-version=2022-10-01" --body '{"query":"SecurityAlert | count"}')
[ "$(echo "$out" | jq_ 'd["tables"][0]["rows"][0][0]')" = "1" ]
chk $? "the alert is a SecurityAlert row in the workspace" "$out"
out=$(rest --method delete --url "$A/cliwf?api-version=2023-12-01-preview"); chk $? "DELETE automation" "$out"

# ── Resource Graph over Event Grid topics ──
out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.EventGrid/topics/clitopic$SFX?api-version=2022-06-15" --body '{"location":"eastus"}'); chk $? "create Event Grid topic" "$out"
out=$(rest --method post --url "$BASE/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01" --body "{\"subscriptions\":[\"$SUB\"],\"query\":\"Resources | where type =~ 'microsoft.eventgrid/topics' | project name\"}")
echo "$out" | grep -q "clitopic$SFX"
chk $? "Resource Graph query returns the topic" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
