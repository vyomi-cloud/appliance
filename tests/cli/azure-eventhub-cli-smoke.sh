#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Event Hubs (Microsoft.EventHub) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider, plus curl for the
# Event Hubs REST send API. ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-eh-$SFX"
NS="clieh$SFX"
API="api-version=2024-01-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.EventHub"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG namespace=$NS =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method put --url "$P/namespaces/$NS?$API" --body '{"location":"eastus","sku":{"name":"Standard","tier":"Standard","capacity":1},"tags":{"env":"cli"}}')
chk $? "az rest PUT namespace" "$out"
echo "$out" | grep -q '"serviceBusEndpoint"' && echo "$out" | grep -q '"provisioningState": "Succeeded"' && echo "$out" | grep -q '"kafkaEnabled": true'
chk $? "namespace has endpoint, Succeeded, Kafka on" "$(echo "$out" | head -12)"
out=$(rest --method get --url "$P/namespaces/$NS?$API"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET namespace returns tags" "$out"
out=$(rest --method get --url "$P/namespaces?$API"); echo "$out" | grep -q "\"$NS\""
chk $? "list namespaces in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.EventHub/namespaces?$API"); echo "$out" | grep -q "\"$NS\""
chk $? "list namespaces in the subscription" "$out"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.EventHub/checkNameAvailability?$API" --body '{"name":"'$NS'"}')
echo "$out" | grep -q '"nameAvailable": false'
chk $? "checkNameAvailability: taken" "$out"
out=$(rest --method put --url "$P/namespaces/ab?$API" --body '{"location":"eastus"}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid namespace name → BadRequest" "$out"

out=$(rest --method post --url "$P/namespaces/$NS/authorizationRules/RootManageSharedAccessKey/listKeys?$API")
echo "$out" | grep -q "Endpoint=sb://$NS.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;"
chk $? "listKeys returns a connection string" "$out"
K1=$(echo "$out" | jq_ 'd["primaryKey"]')
out=$(rest --method post --url "$P/namespaces/$NS/authorizationRules/RootManageSharedAccessKey/regenerateKeys?$API" --body '{"keyType":"PrimaryKey"}'); [ "$(echo "$out" | jq_ 'd["primaryKey"]')" != "$K1" ]
chk $? "regenerateKeys rotates the primary key" "$out"

out=$(rest --method put --url "$P/namespaces/$NS/eventhubs/orders?$API" --body '{"properties":{"partitionCount":4,"messageRetentionInDays":3}}')
echo "$out" | grep -q '"partitionCount": 4' && echo "$out" | grep -q '"messageRetentionInDays": 3'
chk $? "create event hub" "$out"
out=$(rest --method get --url "$P/namespaces/$NS/eventhubs?$API"); echo "$out" | grep -q '"orders"'
chk $? "list event hubs" "$out"
out=$(rest --method put --url "$P/namespaces/$NS/eventhubs/toomany?$API" --body '{"properties":{"partitionCount":500}}'); echo "$out" | grep -q 'BadRequest'
chk $? "too many partitions → BadRequest" "$out"
out=$(rest --method put --url "$P/namespaces/$NS/eventhubs/orders/consumergroups/analytics?$API" --body '{"properties":{"userMetadata":"cli"}}'); echo "$out" | grep -q '"userMetadata": "cli"'
chk $? "create consumer group" "$out"
out=$(rest --method get --url "$P/namespaces/$NS/eventhubs/orders/consumergroups?$API"); echo "$out" | grep -q '\$Default' && echo "$out" | grep -q '"analytics"'
chk $? "list consumer groups includes \$Default" "$out"

DATA="$BASE/azure-data/eventhub/$NS"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$DATA/orders/messages" -H 'Content-Type: application/atom+xml;type=entry;charset=utf-8' -H 'BrokerProperties: {"PartitionKey":"k1"}' -d 'hello-cli')
[ "$code" = "201" ]; chk $? "REST send event → 201" "HTTP $code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$DATA/orders/messages" -H 'Content-Type: application/vnd.microsoft.servicebus.json' -d '[{"Body":"b1"},{"Body":"b2"}]')
[ "$code" = "201" ]; chk $? "REST send batch → 201" "HTTP $code"
out=$(rest --method get --url "$P/namespaces/$NS/eventhubs/orders/events?$API&maxCount=20"); echo "$out" | grep -q '"hello-cli"' && echo "$out" | grep -q '"count": 3'
chk $? "sent events are readable" "$out"

out=$(rest --method delete --url "$P/namespaces/$NS/eventhubs/orders?$API"); chk $? "delete event hub" "$out"
out=$(rest --method delete --url "$P/namespaces/$NS?$API"); chk $? "delete namespace" "$out"
out=$(rest --method get --url "$P/namespaces/$NS?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted namespace → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
