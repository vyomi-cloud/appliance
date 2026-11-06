#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Container Registry — endpoint override only.
# Control plane: `az rest` (the CLI's documented client for any ARM provider) against Microsoft.ContainerRegistry.
# Data plane: when a `docker` daemon is reachable, push + pull an image through the registry's /v2 endpoint.
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
RG="rg-cli-acr-$(date +%s)"
REG="cliacr$(date +%s | tail -c 7)"
API="api-version=2023-07-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ContainerRegistry"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG registry=$REG =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourceGroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "az rest PUT resource group" "$out"
out=$(rest --method put --url "$P/registries/$REG?$API" --body '{"location":"eastus","sku":{"name":"Standard"},"tags":{"env":"cli"},"properties":{"adminUserEnabled":true}}')
chk $? "az rest PUT registries" "$out"
echo "$out" | grep -q "\"loginServer\": \"$REG.azurecr.io\"" && echo "$out" | grep -q '"provisioningState": "Succeeded"'
chk $? "registry has loginServer and Succeeded" "$(echo "$out" | head -8)"
out=$(rest --method get --url "$P/registries/$REG?$API"); echo "$out" | grep -q '"env": "cli"' && echo "$out" | grep -q '"name": "Standard"'
chk $? "GET registry returns tags and SKU" "$out"
out=$(rest --method get --url "$P/registries?$API"); echo "$out" | grep -q "\"$REG\""
chk $? "list registries in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.ContainerRegistry/registries?$API"); echo "$out" | grep -q "\"$REG\""
chk $? "list registries in the subscription" "$out"
out=$(rest --method post --url "$P/registries/$REG/listCredentials?$API"); echo "$out" | grep -q "\"username\": \"$REG\"" && echo "$out" | grep -q '"password2"'
chk $? "listCredentials returns the admin username and two passwords" "$(echo "$out" | head -6)"
OLD=$(echo "$out" | jq_ 'd["passwords"][0]["value"]')
out=$(rest --method post --url "$P/registries/$REG/regenerateCredential?$API" --body '{"name":"password"}')
NEW=$(echo "$out" | jq_ 'd["passwords"][0]["value"]'); [ -n "$NEW" ] && [ "$NEW" != "$OLD" ]
chk $? "regenerateCredential rotates the password" "$out"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.ContainerRegistry/checkNameAvailability?$API" --body '{"name":"'$REG'","type":"Microsoft.ContainerRegistry/registries"}')
echo "$out" | grep -q '"nameAvailable": false' && echo "$out" | grep -q 'AlreadyExists'
chk $? "checkNameAvailability: name taken" "$out"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.ContainerRegistry/checkNameAvailability?$API" --body '{"name":"free'$REG'","type":"Microsoft.ContainerRegistry/registries"}')
echo "$out" | grep -q '"nameAvailable": true'
chk $? "checkNameAvailability: free name" "$out"
out=$(rest --method put --url "$P/registries/ab-c?$API" --body '{"location":"eastus","sku":{"name":"Basic"}}'); echo "$out" | grep -q 'InvalidParameter'
chk $? "invalid registry name → InvalidParameter" "$out"
out=$(rest --method patch --url "$P/registries/$REG?$API" --body '{"properties":{"adminUserEnabled":false}}'); echo "$out" | grep -q '"adminUserEnabled": false'
chk $? "PATCH disables the admin user" "$out"
out=$(rest --method post --url "$P/registries/$REG/listCredentials?$API"); echo "$out" | grep -q 'Admin user is disabled'
chk $? "listCredentials refused while admin is disabled" "$out"
out=$(rest --method get --url "$P/registries/$REG/listUsages?$API"); echo "$out" | grep -q '"Size"' && echo "$out" | grep -q '"Webhooks"'
chk $? "listUsages reports Size and Webhooks" "$out"

out=$(rest --method put --url "$P/registries/$REG/webhooks/hook1ci?$API" --body '{"location":"eastus","properties":{"serviceUri":"https://example.com/hook","actions":["push","delete"],"status":"enabled"}}')
echo "$out" | grep -q '"serviceUri": "https://example.com/hook"'
chk $? "create webhook" "$out"
out=$(rest --method get --url "$P/registries/$REG/webhooks?$API"); echo "$out" | grep -q 'hook1ci'
chk $? "list webhooks" "$out"
out=$(rest --method put --url "$P/registries/$REG/replications/westus?$API" --body '{"location":"westus"}'); echo "$out" | grep -q 'InvalidSku'
chk $? "replication on a Standard registry → InvalidSku" "$out"
out=$(rest --method patch --url "$P/registries/$REG?$API" --body '{"sku":{"name":"Premium"}}'); echo "$out" | grep -q '"name": "Premium"'
chk $? "upgrade to Premium" "$out"
out=$(rest --method put --url "$P/registries/$REG/replications/westus?$API" --body '{"location":"westus"}'); echo "$out" | grep -q '"provisioningState": "Succeeded"'
chk $? "create geo-replication" "$out"
out=$(rest --method put --url "$P/registries/$REG/scopeMaps/readonlymap?$API" --body '{"properties":{"actions":["repositories/*/content/read"]}}'); echo "$out" | grep -q 'content/read'
chk $? "create scope map" "$out"
SM=$(echo "$out" | jq_ 'd["id"]')
out=$(rest --method put --url "$P/registries/$REG/tokens/tok1?$API" --body '{"properties":{"scopeMapId":"'$SM'","status":"enabled"}}'); echo "$out" | grep -q '"scopeMapId"'
chk $? "create token bound to the scope map" "$out"
out=$(rest --method get --url "$P/registries/$REG/scopeMaps?$API"); echo "$out" | grep -q '_repositories_pull'
chk $? "system scope maps are listed" "$out"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  HOSTPORT="${BASE##*:}"
  IMG="$REG.azurecr.localhost:$HOSTPORT/cli/app:v1"
  if docker image inspect alpine:3.19 >/dev/null 2>&1 || docker pull -q alpine:3.19 >/dev/null 2>&1; then
    docker tag alpine:3.19 "$IMG"
    out=$(docker push "$IMG" 2>&1); echo "$out" | grep -q 'digest: sha256'
    chk $? "docker push through the registry endpoint" "$(echo "$out" | tail -3)"
    out=$(curl -s "http://$REG.azurecr.localhost:$HOSTPORT/v2/_catalog"); echo "$out" | grep -q 'cli/app'
    chk $? "catalog lists the pushed repository (registry namespace hidden)" "$out"
    docker rmi "$IMG" >/dev/null 2>&1
    out=$(docker pull "$IMG" 2>&1); docker image inspect "$IMG" >/dev/null 2>&1
    chk $? "docker pull returns the pushed image" "$(echo "$out" | tail -3)"
    docker rmi "$IMG" >/dev/null 2>&1
  else
    echo "[SKIP] docker push/pull (no base image available)"
  fi
else
  echo "[SKIP] docker push/pull (no docker daemon)"
fi

out=$(rest --method delete --url "$P/registries/$REG?$API"); chk $? "delete registry" "$out"
out=$(rest --method get --url "$P/registries/$REG?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted registry → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
