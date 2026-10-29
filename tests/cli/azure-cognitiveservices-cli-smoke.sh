#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure AI services (Microsoft.CognitiveServices) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider. ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-ai-$SFX"
ACCT="cliai$SFX"
API="api-version=2024-10-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG account=$ACCT =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method put --url "$P/accounts/$ACCT?$API" --body '{"kind":"OpenAI","location":"eastus","sku":{"name":"S0"},"properties":{"customSubDomainName":"'$ACCT'"},"tags":{"env":"cli"}}')
chk $? "az rest PUT accounts" "$out"
echo "$out" | grep -q '"endpoint"' && echo "$out" | grep -q '"provisioningState": "Succeeded"' && echo "$out" | grep -q '"kind": "OpenAI"'
chk $? "account has endpoint, kind OpenAI, Succeeded" "$(echo "$out" | head -8)"
out=$(rest --method get --url "$P/accounts/$ACCT?$API"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET account returns tags" "$out"
out=$(rest --method get --url "$P/accounts?$API"); echo "$out" | grep -q "\"$ACCT\""
chk $? "list accounts in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.CognitiveServices/accounts?$API"); echo "$out" | grep -q "\"$ACCT\""
chk $? "list accounts in the subscription" "$out"
out=$(rest --method post --url "$P/accounts/$ACCT/listKeys?$API"); echo "$out" | grep -q '"key1"' && echo "$out" | grep -q '"key2"'
chk $? "listKeys returns key1 + key2" "$out"
K1=$(echo "$out" | jq_ 'd["key1"]')
out=$(rest --method post --url "$P/accounts/$ACCT/regenerateKey?$API" --body '{"keyName":"Key1"}'); [ "$(echo "$out" | jq_ 'd["key1"]')" != "$K1" ]
chk $? "regenerateKey rotates key1" "$out"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.CognitiveServices/checkDomainAvailability?$API" --body '{"subdomainName":"'$ACCT'","type":"Microsoft.CognitiveServices/accounts"}')
echo "$out" | grep -q '"isSubdomainAvailable": false'
chk $? "checkDomainAvailability: taken" "$out"
out=$(rest --method put --url "$P/accounts/bad$ACCT?$API" --body '{"kind":"NoSuchKind","location":"eastus","sku":{"name":"S0"}}'); echo "$out" | grep -q 'InvalidParameter'
chk $? "unknown kind → InvalidParameter" "$out"

out=$(rest --method put --url "$P/accounts/$ACCT/deployments/chat?$API" --body '{"sku":{"name":"Standard","capacity":10},"properties":{"model":{"format":"OpenAI","name":"gpt-4o","version":"2024-08-06"}}}')
echo "$out" | grep -q '"name": "chat"' && echo "$out" | grep -q '"gpt-4o"'
chk $? "create model deployment" "$out"
out=$(rest --method get --url "$P/accounts/$ACCT/deployments?$API"); echo "$out" | grep -q '"chat"'
chk $? "list deployments" "$out"
out=$(rest --method put --url "$P/accounts/$ACCT/deployments/big?$API" --body '{"sku":{"name":"Standard","capacity":99999},"properties":{"model":{"format":"OpenAI","name":"gpt-4o","version":"2024-08-06"}}}'); echo "$out" | grep -q 'InsufficientQuota'
chk $? "over-quota deployment → InsufficientQuota" "$out"
out=$(rest --method get --url "$P/accounts/$ACCT/usages?$API"); echo "$out" | grep -q 'gpt-4o'
chk $? "account usages list model quotas" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.CognitiveServices/locations/eastus/models?$API"); echo "$out" | grep -q 'text-embedding-3-small'
chk $? "location models list" "$out"
out=$(rest --method delete --url "$P/accounts/$ACCT/deployments/chat?$API"); chk $? "delete deployment" "$out"

out=$(rest --method delete --url "$P/accounts/$ACCT?$API"); chk $? "delete account" "$out"
out=$(rest --method get --url "$P/accounts/$ACCT?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted account → ResourceNotFound" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.CognitiveServices/locations/eastus/resourceGroups/$RG/deletedAccounts/$ACCT?$API"); echo "$out" | grep -q "\"$ACCT\""
chk $? "soft-deleted account is listed" "$out"
out=$(rest --method delete --url "$BASE/subscriptions/$SUB/providers/Microsoft.CognitiveServices/locations/eastus/resourceGroups/$RG/deletedAccounts/$ACCT?$API"); chk $? "purge soft-deleted account" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
