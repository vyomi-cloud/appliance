#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Workbooks (Microsoft.Insights/workbooks) + renderer — endpoint override only (`az rest`).
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-wb-$SFX"
RP="/subscriptions/$SUB/resourceGroups/$RG"
WSP="$RP/providers/Microsoft.OperationalInsights/workspaces/wb-law"
WBID="$(python3 -c 'import uuid;print(uuid.uuid4())')"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
echo "== az against $BASE sub=$SUB rg=$RG =="
rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}' >/dev/null
chk $? "create resource group"
rest --method put --url "$BASE$WSP?api-version=2022-10-01" --body '{"location":"eastus"}' >/dev/null
chk $? "create workspace"
for row in '{"Region":"west","Amount":10}' '{"Region":"east","Amount":5}' '{"Region":"west","Amount":7}'; do
  rest --method post --url "$BASE$WSP/api/logs?api-version=2022-10-01&logType=Sales" --body "$row" >/dev/null
done
chk $? "ingest rows through the data collector API"
SD=$(python3 -c "import json; print(json.dumps(json.dumps({'version':'Notebook/1.0','items':[{'type':3,'name':'q','content':{'queryType':0,'visualization':'barchart','crossComponentResources':['$WSP'],'query':'Sales_CL | summarize total = sum(Amount_d) by Region_s | order by total desc'}}]})))")
out=$(rest --method put --url "$BASE$RP/providers/Microsoft.Insights/workbooks/$WBID?api-version=2022-04-01" --body "{\"location\":\"eastus\",\"kind\":\"shared\",\"properties\":{\"displayName\":\"Sales\",\"category\":\"workbook\",\"sourceId\":\"$WSP\",\"serializedData\":$SD}}")
[ "$(echo "$out" | jq_ 'd["properties"]["displayName"]')" = "Sales" ]
chk $? "create workbook" "$out"
out=$(rest --method get --url "$BASE$RP/providers/Microsoft.Insights/workbooks?api-version=2022-04-01&category=workbook"); echo "$out" | grep -q "$WBID"
chk $? "list workbooks in the resource group" "$out"
out=$(rest --method post --url "$BASE$RP/providers/Microsoft.Insights/workbooks/$WBID/render?api-version=2022-04-01" --body '{}')
[ "$(echo "$out" | jq_ 'd["items"][0]["status"]+str(d["items"][0]["rows"])')" = "ok[['west', 17], ['east', 5]]" ]
chk $? "render returns the KQL table (west 17, east 5)" "$out"
out=$(rest --method post --url "$BASE$RP/providers/Microsoft.Insights/workbooks/nope/render?api-version=2022-04-01" --body '{}'); echo "$out" | grep -q 'ResourceNotFound'
chk $? "render of an unknown workbook is 404" "$out"
rest --method delete --url "$BASE$RP/providers/Microsoft.Insights/workbooks/$WBID?api-version=2022-04-01" >/dev/null
chk $? "delete workbook"
echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
