#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Application Insights (Microsoft.Insights) ARM API — endpoint override only.
# `az rest` is the Azure CLI's documented client for any ARM resource provider, so every call goes
# through the unmodified binary. ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
RG="rg-cli-ai-$(date +%s)"
AI="appi-cli"; WT="wt-cli"
API="api-version=2020-02-02"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Insights"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az rest against $BASE sub=$SUB rg=$RG =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }

out=$(rest --method put --url "$P/components/$AI?$API" --body '{"location":"eastus","kind":"web","tags":{"env":"cli"},"properties":{"Application_Type":"web","RetentionInDays":90,"Request_Source":"rest"}}')
chk $? "az rest PUT components" "$out"
echo "$out" | grep -q '"InstrumentationKey"' && echo "$out" | grep -q '"ConnectionString"' && echo "$out" | grep -q '"provisioningState": "Succeeded"'
chk $? "component has InstrumentationKey, ConnectionString, Succeeded" "$(echo "$out" | head -5)"
CID=$(echo "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])' 2>/dev/null)
IKEY=$(echo "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin)["properties"]["InstrumentationKey"])' 2>/dev/null)

out=$(rest --method get --url "$P/components/$AI?$API"); echo "$out" | grep -q "$IKEY"
chk $? "GET component returns the same instrumentation key" "$(echo "$out" | head -3)"
out=$(rest --method patch --url "$P/components/$AI?$API" --body '{"tags":{"env":"prod"}}'); echo "$out" | grep -q '"env": "prod"'
chk $? "PATCH tags" "$out"
out=$(rest --method get --url "$P/components?$API"); echo "$out" | grep -q "\"$AI\""
chk $? "list components in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.Insights/components?$API"); echo "$out" | grep -q "\"$AI\""
chk $? "list components in the subscription" "$out"

out=$(rest --method post --url "$P/components/$AI/ApiKeys?$API" --body '{"name":"cli-key","linkedReadProperties":["'"$CID"'/api"],"linkedWriteProperties":["'"$CID"'/annotations"]}')
echo "$out" | grep -q '"apiKey"'
chk $? "create API key returns the key value" "$out"
KID=$(echo "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"].rsplit("/",1)[-1])' 2>/dev/null)
out=$(rest --method get --url "$P/components/$AI/ApiKeys?$API"); echo "$out" | grep -q '"cli-key"' && ! echo "$out" | grep -q '"apiKey"'
chk $? "list API keys hides key values" "$out"
out=$(rest --method delete --url "$P/components/$AI/ApiKeys/$KID?$API"); chk $? "delete API key" "$out"

out=$(rest --method put --url "$P/components/$AI/currentbillingfeatures?$API" --body '{"CurrentBillingFeatures":["Basic"],"DataVolumeCap":{"Cap":2.0}}')
echo "$out" | grep -q '"Cap": 2'
chk $? "set daily volume cap" "$out"

out=$(rest --method put --url "$P/webtests/$WT?api-version=2022-06-15" --body '{"location":"eastus","kind":"ping","tags":{"hidden-link:'"$CID"'":"Resource"},"properties":{"SyntheticMonitorId":"'"$WT"'","Name":"'"$WT"'","Kind":"ping","Enabled":true,"Frequency":300,"Timeout":30,"RetryEnabled":true,"Locations":[{"Id":"us-fl-mia-edge"}],"Configuration":{"WebTest":"<WebTest Name=\"wt-cli\" Url=\"https://example.com\"/>"}}}')
chk $? "az rest PUT webtests" "$out"
out=$(rest --method get --url "$P/components/$AI/webtests?api-version=2022-06-15"); echo "$out" | grep -q "\"$WT\""
chk $? "list web tests by component" "$out"
out=$(rest --method put --url "$P/webtests/wt-bad?api-version=2022-06-15" --body '{"location":"eastus","properties":{"Name":"wt-bad","Frequency":42,"Locations":[{"Id":"x"}]}}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid web test frequency → BadRequest" "$out"
out=$(rest --method delete --url "$P/webtests/$WT?api-version=2022-06-15"); chk $? "delete web test" "$out"

out=$(rest --method put --url "$P/components/appi-bad?$API" --body '{"location":"eastus","kind":"web","properties":{"Application_Type":"web","RetentionInDays":31}}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid retention → BadRequest" "$out"
out=$(rest --method delete --url "$P/components/$AI?$API"); chk $? "delete component" "$out"
out=$(rest --method get --url "$P/components/$AI?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted component → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
