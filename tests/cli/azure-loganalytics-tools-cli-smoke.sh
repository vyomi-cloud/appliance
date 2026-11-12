#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Log Analytics workspace tools: linked storage accounts + Computer groups (classic) — endpoint override
# only (`az rest`). ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-lt-$SFX"
RP="/subscriptions/$SUB/resourceGroups/$RG"
WSP="$RP/providers/Microsoft.OperationalInsights/workspaces/lt-law"
ST="$RP/providers/Microsoft.Storage/storageAccounts/ltcli$SFX"
AV="api-version=2022-10-01"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
echo "== az against $BASE sub=$SUB rg=$RG =="
rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}' >/dev/null
chk $? "create resource group"
rest --method put --url "$BASE$WSP?$AV" --body '{"location":"eastus"}' >/dev/null
chk $? "create workspace"
rest --method put --url "$BASE$ST?api-version=2023-01-01" --body '{"location":"eastus","kind":"StorageV2","sku":{"name":"Standard_LRS"}}' >/dev/null
chk $? "create storage account"

out=$(rest --method put --url "$BASE$WSP/linkedStorageAccounts/Nope?$AV" --body "{\"properties\":{\"storageAccountIds\":[\"$ST\"]}}"); echo "$out" | grep -q 'BadRequest'
chk $? "unknown data source type rejected" "$out"
out=$(rest --method put --url "$BASE$WSP/linkedStorageAccounts/CustomLogs?$AV" --body "{\"properties\":{\"storageAccountIds\":[\"$ST\"]}}")
[ "$(echo "$out" | jq_ 'd["properties"]["dataSourceType"]')" = "CustomLogs" ]
chk $? "link a storage account for CustomLogs" "$out"
out=$(rest --method get --url "$BASE$WSP/linkedStorageAccounts?$AV"); echo "$out" | grep -q 'CustomLogs'
chk $? "list linked storage accounts" "$out"

for h in db1 db2 app1; do
  rest --method post --url "$BASE$WSP/api/logs?$AV&logType=Nodes" --body "{\"Computer\":\"$h\",\"Role\":\"${h%%[0-9]*}\"}" >/dev/null
done
chk $? "ingest nodes"
out=$(rest --method put --url "$BASE$WSP/computerGroups/Databases?$AV" --body '{"properties":{"displayName":"Databases","query":"Nodes_CL | where Role_s == '"'"'db'"'"' | project Computer_s"}}')
[ "$(echo "$out" | jq_ 'd["properties"]["memberCount"]')" = "2" ]
chk $? "create computer group (2 live members)" "$out"
out=$(rest --method get --url "$BASE$WSP/savedSearches/Databases?$AV"); echo "$out" | grep -q 'Computer Groups'
chk $? "group is a saved search in category 'Computer Groups'" "$out"
out=$(rest --method post --url "$BASE$WSP/api/query?$AV" --body '{"query":"Nodes_CL | where Computer_s in (Databases) | count"}')
[ "$(echo "$out" | jq_ 'd["tables"][0]["rows"][0][0]')" = "2" ]
chk $? "KQL 'Computer in (Databases)' counts the 2 members" "$out"
rest --method delete --url "$BASE$WSP/computerGroups/Databases?$AV" >/dev/null
chk $? "delete group"
rest --method delete --url "$BASE$WSP/linkedStorageAccounts/CustomLogs?$AV" >/dev/null
chk $? "unlink storage account"
echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
