#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure App Configuration — endpoint override only.
# Control plane: `az rest` (the CLI's documented client for any ARM provider) against Microsoft.AppConfiguration.
# Data plane: `az appconfig kv|feature|revision|snapshot` in the CLI's emulator mode (--auth-mode anonymous --endpoint).
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
RG="rg-cli-appcfg-$(date +%s)"
STORE="clicfg$(date +%s | tail -c 7)"
API="api-version=2024-05-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.AppConfiguration"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG store=$STORE =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$P/configurationStores/$STORE?$API" --body '{"location":"eastus","sku":{"name":"Standard"},"tags":{"env":"cli"}}')
chk $? "az rest PUT configurationStores" "$out"
echo "$out" | grep -q '"endpoint"' && echo "$out" | grep -q '"provisioningState": "Succeeded"' && echo "$out" | grep -q '"softDeleteRetentionInDays": 7'
chk $? "store has endpoint, Succeeded, soft-delete 7d" "$(echo "$out" | head -8)"
EP=$(echo "$out" | jq_ 'd["properties"]["endpoint"]')
out=$(rest --method get --url "$P/configurationStores/$STORE?$API"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET store returns tags" "$out"
out=$(rest --method get --url "$P/configurationStores?$API"); echo "$out" | grep -q "\"$STORE\""
chk $? "list stores in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.AppConfiguration/configurationStores?$API"); echo "$out" | grep -q "\"$STORE\""
chk $? "list stores in the subscription" "$out"
out=$(rest --method post --url "$P/configurationStores/$STORE/listKeys?$API"); echo "$out" | grep -q 'connectionString' && echo "$out" | grep -q 'Primary Read Only'
chk $? "listKeys returns connection strings" "$(echo "$out" | head -5)"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.AppConfiguration/checkNameAvailability?$API" --body '{"name":"'$STORE'","type":"Microsoft.AppConfiguration/configurationStores"}')
echo "$out" | grep -q '"nameAvailable": false'
chk $? "checkNameAvailability: name taken" "$out"

out=$(rest --method put --url "$P/configurationStores/ab?$API" --body '{"location":"eastus"}'); echo "$out" | grep -q 'InvalidParameter'
chk $? "short store name → InvalidParameter" "$out"

D="--auth-mode anonymous --endpoint $EP"
out=$(az appconfig kv set $D --key app:color --value blue --label dev --content-type text/plain --tags env=dev --yes -o json 2>&1)
chk $? "az appconfig kv set" "$out"
out=$(az appconfig kv show $D --key app:color --label dev -o json 2>&1); echo "$out" | grep -q '"value": "blue"' && echo "$out" | grep -q '"env": "dev"'
chk $? "kv show returns value + tags" "$out"
az appconfig kv set $D --key app:size --value L --label dev --yes -o none 2>&1
az appconfig kv set $D --key other --value x --yes -o none 2>&1
out=$(az appconfig kv list $D --key 'app:*' --label dev -o json 2>&1); [ "$(echo "$out" | jq_ 'len(d)')" = "2" ]
chk $? "kv list with key/label filter returns 2" "$out"
out=$(az appconfig kv list $D --key '*' --label '\0' -o json 2>&1); [ "$(echo "$out" | jq_ 'len(d)')" = "1" ]
chk $? "kv list null label returns 1" "$out"
out=$(az appconfig kv list $D --fields key value -o json 2>&1); echo "$out" | grep -q '"key": "other"'
chk $? "kv list --fields" "$out"
out=$(az appconfig kv lock $D --key other --yes -o json 2>&1); echo "$out" | grep -q '"locked": true'
chk $? "kv lock" "$out"
out=$(az appconfig kv set $D --key other --value y --yes -o json 2>&1); echo "$out" | grep -qi 'read only\|locked\|Modifing\|409'
chk $? "write to a locked key is refused" "$out"
out=$(az appconfig kv unlock $D --key other --yes -o json 2>&1); echo "$out" | grep -q '"locked": false'
chk $? "kv unlock" "$out"
az appconfig kv set $D --key other --value y --yes -o none 2>&1
out=$(az appconfig revision list $D --key other -o json 2>&1); [ "$(echo "$out" | jq_ 'len(d)')" -ge 2 ]
chk $? "revision list keeps history" "$out"
out=$(az appconfig feature set $D --feature beta --yes -o json 2>&1); echo "$out" | grep -q '.appconfig.featureflag/beta'
chk $? "feature set creates a feature flag key-value" "$out"
out=$(az appconfig feature enable $D --feature beta --yes -o json 2>&1); echo "$out" | grep -q '"enabled": true\|"state": "on"'
chk $? "feature enable" "$out"
out=$(az appconfig snapshot create $D -s snap-cli --filters '{"key":"app:*","label":"dev"}' -o json 2>&1); echo "$out" | grep -q '"name": "snap-cli"'
chk $? "snapshot create" "$out"
out=$(az appconfig snapshot show $D -s snap-cli -o json 2>&1); echo "$out" | grep -q '"status": "ready"' && echo "$out" | grep -q '"itemsCount": 2'
chk $? "snapshot is ready with 2 items" "$out"
out=$(az appconfig kv list $D --snapshot snap-cli -o json 2>&1); [ "$(echo "$out" | jq_ 'len(d)')" = "2" ]
chk $? "kv list --snapshot returns the frozen items" "$out"
out=$(az appconfig snapshot archive $D -s snap-cli -o json 2>&1); echo "$out" | grep -q '"status": "archived"'
chk $? "snapshot archive" "$out"
out=$(az appconfig kv export $D -d file --path /tmp/appcfg-export-$$.json --format json --yes 2>&1); grep -q 'other' /tmp/appcfg-export-$$.json 2>/dev/null
chk $? "kv export to a file" "$out"
rm -f /tmp/appcfg-export-$$.json
out=$(az appconfig kv delete $D --key app:color --label dev --yes -o json 2>&1); echo "$out" | grep -q '"key": "app:color"'
chk $? "kv delete returns the deleted setting" "$out"
out=$(az appconfig kv show $D --key app:color --label dev -o json 2>&1); echo "$out" | grep -qi 'not exist\|not found\|404'
chk $? "deleted kv → not found" "$out"

# ARM keyValues sees the same data
out=$(rest --method get --url "$P/configurationStores/$STORE/keyValues?$API"); echo "$out" | grep -q 'app:size'
chk $? "ARM keyValues lists data-plane keys" "$out"
out=$(rest --method post --url "$P/configurationStores/$STORE/listKeyValue?$API" --body '{"key":"other"}'); echo "$out" | grep -q '"value": "y"'
chk $? "ARM listKeyValue" "$out"

out=$(rest --method delete --url "$P/configurationStores/$STORE?$API"); chk $? "delete store" "$out"
out=$(rest --method get --url "$P/configurationStores/$STORE?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted store → ResourceNotFound" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.AppConfiguration/locations/eastus/deletedConfigurationStores?$API"); echo "$out" | grep -q "\"$STORE\""
chk $? "soft-deleted store is listed" "$out"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.AppConfiguration/locations/eastus/deletedConfigurationStores/$STORE/purge?$API"); chk $? "purge soft-deleted store" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
