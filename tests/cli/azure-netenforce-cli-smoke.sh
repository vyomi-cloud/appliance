#!/usr/bin/env bash
# Real `az` CLI (az rest, the CLI's documented client for any ARM provider / data plane) against Vyomi: network rules, CORS and diagnostic
# settings configured through az are ENFORCED - a blocked request is refused, an allowed one passes. Endpoint override only.
# ENDPOINT (default http://127.0.0.1:9000), SUB. The simulated client is declared with x-vyomi-source-ip / -trusted-service headers.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-ne-$SFX"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
command -v az >/dev/null 2>&1 || { echo "[FAIL] az CLI not installed"; exit 1; }
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }     # data-plane status for the blocked/allowed assertions
rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}' >/dev/null

# Service Bus network rule set
rest --method put --url "$P/Microsoft.ServiceBus/namespaces/sb$SFX?api-version=2022-10-01-preview" --body '{"location":"eastus","sku":{"name":"Premium","tier":"Premium","capacity":1}}' >/dev/null
out=$(rest --method put --url "$P/Microsoft.ServiceBus/namespaces/sb$SFX/networkRuleSets/default?api-version=2022-10-01-preview" --body '{"properties":{"defaultAction":"Deny","publicNetworkAccess":"Enabled","ipRules":[{"ipMask":"198.51.100.0/24","action":"Allow"}]}}')
echo "$out" | grep -q '"defaultAction": "Deny"'; chk $? "az rest PUT Service Bus networkRuleSets/default" "$out"
c=$(code -X PUT "$BASE/q$SFX" -H "x-vyomi-namespace: sb$SFX" -H 'content-type: application/atom+xml' -H 'x-vyomi-source-ip: 198.51.100.4'); [ "$c" = 200 ] || [ "$c" = 201 ]; chk $? "Service Bus: allowed IP passes ($c)"
c=$(code -X PUT "$BASE/q$SFX" -H "x-vyomi-namespace: sb$SFX" -H 'x-vyomi-source-ip: 192.0.2.9'); [ "$c" = 403 ]; chk $? "Service Bus: other IP BLOCKED ($c)"

# Log Analytics public network access
W="$P/Microsoft.OperationalInsights/workspaces/law-$SFX"
rest --method put --url "$W?api-version=2022-10-01" --body '{"location":"eastus","properties":{"publicNetworkAccessForIngestion":"Enabled","publicNetworkAccessForQuery":"Disabled"}}' >/dev/null
c=$(code -X POST "$W/api/query?api-version=2022-10-01" -H 'content-type: application/json' -d '{"query":"Heartbeat | take 1"}'); [ "$c" = 403 ]; chk $? "Log Analytics: query BLOCKED while publicNetworkAccessForQuery=Disabled ($c)"
c=$(code -X POST "$W/api/logs?api-version=2022-10-01&logType=Cli" -H 'content-type: application/json' -d '[{"a":1}]'); [ "$c" = 200 ]; chk $? "Log Analytics: ingestion allowed ($c)"

# Cosmos CORS preflight
rest --method put --url "$P/Microsoft.DocumentDB/databaseAccounts/cz$SFX?api-version=2024-05-15" --body '{"location":"eastus","kind":"GlobalDocumentDB","properties":{"databaseAccountOfferType":"Standard","locations":[{"locationName":"East US","failoverPriority":0}],"cors":[{"allowedOrigins":"https://app.contoso.com","maxAgeInSeconds":300}]}}' >/dev/null
c=$(code -X OPTIONS "$BASE/dbs" -H 'Origin: https://app.contoso.com' -H 'Access-Control-Request-Method: GET' -H "x-vyomi-account: cz$SFX"); [ "$c" = 200 ]; chk $? "Cosmos CORS preflight: listed origin allowed ($c)"
c=$(code -X OPTIONS "$BASE/dbs" -H 'Origin: https://evil.example' -H 'Access-Control-Request-Method: GET' -H "x-vyomi-account: cz$SFX"); [ "$c" = 403 ]; chk $? "Cosmos CORS preflight: unlisted origin BLOCKED ($c)"

# Diagnostic settings -> workspace
rest --method put --url "$P/Microsoft.ServiceBus/namespaces/sb$SFX/providers/Microsoft.Insights/diagnosticSettings/toLaw?api-version=2021-05-01-preview" --body "{\"properties\":{\"workspaceId\":\"/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.OperationalInsights/workspaces/law-$SFX\",\"logs\":[{\"category\":\"OperationalLogs\",\"enabled\":true}]}}" >/dev/null
rest --method put --url "$P/Microsoft.ServiceBus/namespaces/sb$SFX?api-version=2022-10-01-preview" --body '{"location":"eastus","sku":{"name":"Premium","tier":"Premium","capacity":1},"tags":{"x":"1"}}' >/dev/null
rest --method put --url "$W?api-version=2022-10-01" --body '{"location":"eastus","properties":{"publicNetworkAccessForQuery":"Enabled"}}' >/dev/null
out=$(rest --method post --url "$W/api/query?api-version=2022-10-01" --body "{\"query\":\"AzureDiagnostics | where Category == 'OperationalLogs'\"}")
echo "$out" | grep -q 'OperationalLogs'; chk $? "diagnostic setting delivered an OperationalLogs row to the workspace" "$out"

echo "passed=$pass failed=$fail"; [ "$fail" = 0 ]
