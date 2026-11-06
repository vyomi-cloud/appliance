#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Managed Identities (Microsoft.ManagedIdentity/userAssignedIdentities) —
# endpoint override only: `az rest` (the CLI's documented client for any ARM provider) against the resource
# provider. ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-msi-$SFX"
ID="cli-id-$SFX"
API="api-version=2023-01-31"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ManagedIdentity"
RID="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$ID"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG identity=$ID =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method put --url "$P/userAssignedIdentities/$ID?$API" --body '{"location":"eastus","tags":{"env":"cli"}}')
chk $? "az rest PUT userAssignedIdentities" "$out"
echo "$out" | grep -q '"clientId"' && echo "$out" | grep -q '"principalId"' && echo "$out" | grep -q '"tenantId"'
chk $? "identity has clientId, principalId and tenantId" "$(echo "$out" | head -20)"
CLIENT=$(echo "$out" | jq_ 'd["properties"]["clientId"]')
out=$(rest --method get --url "$P/userAssignedIdentities/$ID?$API")
[ "$(echo "$out" | jq_ 'd["properties"]["clientId"]')" = "$CLIENT" ] && echo "$out" | grep -q '"env": "cli"'
chk $? "GET identity returns the same clientId and tags" "$out"
[ "$(echo "$out" | jq_ 'd["type"]')" = "Microsoft.ManagedIdentity/userAssignedIdentities" ]
chk $? "identity type" "$out"
out=$(rest --method get --url "$P/userAssignedIdentities?$API"); echo "$out" | grep -q "\"$ID\""
chk $? "list identities in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.ManagedIdentity/userAssignedIdentities?$API"); echo "$out" | grep -q "\"$ID\""
chk $? "list identities in the subscription" "$out"
out=$(rest --method put --url "$P/userAssignedIdentities/x?$API" --body '{"location":"eastus"}'); echo "$out" | grep -q 'InvalidResourceName'
chk $? "too-short identity name → InvalidResourceName" "$out"
out=$(rest --method put --url "$P/userAssignedIdentities/$ID?$API" --body '{"location":"westus"}'); echo "$out" | grep -q 'InvalidResourceLocation'
chk $? "changing the location → InvalidResourceLocation" "$out"
out=$(rest --method patch --url "$P/userAssignedIdentities/$ID?$API" --body '{"tags":{"env":"patched"}}'); echo "$out" | grep -q '"env": "patched"'
chk $? "PATCH identity tags" "$out"

FC="$P/userAssignedIdentities/$ID/federatedIdentityCredentials"
out=$(rest --method put --url "$FC/gh-main?$API" --body '{"properties":{"issuer":"https://token.actions.githubusercontent.com","subject":"repo:cloudlearn/demo:ref:refs/heads/main","audiences":["api://AzureADTokenExchange"]}}')
echo "$out" | grep -q '"subject": "repo:cloudlearn/demo:ref:refs/heads/main"'
chk $? "create federated credential" "$out"
out=$(rest --method put --url "$FC/gh-dup?$API" --body '{"properties":{"issuer":"https://token.actions.githubusercontent.com","subject":"repo:cloudlearn/demo:ref:refs/heads/main","audiences":["api://AzureADTokenExchange"]}}')
echo "$out" | grep -q 'Conflict'
chk $? "same issuer+subject → Conflict" "$out"
out=$(rest --method put --url "$FC/bad-issuer?$API" --body '{"properties":{"issuer":"http://insecure","subject":"s","audiences":["api://AzureADTokenExchange"]}}')
echo "$out" | grep -q 'BadRequest'
chk $? "non-https issuer → BadRequest" "$out"
out=$(rest --method get --url "$FC?$API"); [ "$(echo "$out" | jq_ 'len(d["value"])')" = "1" ]
chk $? "list federated credentials" "$out"
out=$(rest --method get --url "$FC/gh-main?$API"); echo "$out" | grep -q 'federatedIdentityCredentials'
chk $? "GET federated credential" "$out"

# a resource that uses the identity shows up under listAssociatedResources
out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/acct$SFX?api-version=2024-10-01" \
  --body '{"location":"eastus","kind":"OpenAI","sku":{"name":"S0"},"identity":{"type":"UserAssigned","userAssignedIdentities":{"'$RID'":{}}},"properties":{}}')
chk $? "create an AI services account that uses the identity" "$out"
out=$(rest --method post --url "$P/userAssignedIdentities/$ID/listAssociatedResources?$API")
echo "$out" | grep -q "acct$SFX" && echo "$out" | grep -q 'Microsoft.CognitiveServices/accounts'
chk $? "listAssociatedResources returns the account" "$out"
out=$(rest --method post --url "$P/userAssignedIdentities/$ID/listAssociatedResources?$API&\$filter=contains(name,'nomatch')")
[ "$(echo "$out" | jq_ 'len(d["value"])')" = "0" ]
chk $? "listAssociatedResources \$filter narrows the result" "$out"
rest --method delete --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/acct$SFX?api-version=2024-10-01" >/dev/null

out=$(rest --method delete --url "$FC/gh-main?$API"); chk $? "delete federated credential" "$out"
out=$(rest --method get --url "$FC/gh-main?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted federated credential → ResourceNotFound" "$out"
out=$(rest --method delete --url "$P/userAssignedIdentities/$ID?$API"); chk $? "delete identity" "$out"
out=$(rest --method get --url "$P/userAssignedIdentities/$ID?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted identity → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
