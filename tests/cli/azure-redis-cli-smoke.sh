#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Cache for Redis (Microsoft.Cache/redis) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider, plus a
# real Redis-protocol PING answered by the shared Valkey data plane. ENDPOINT (default http://127.0.0.1:9000), SUB.
# One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-redis-$SFX"
NAME="clicache$SFX"
PREM="cliprem$SFX"
API="api-version=2024-03-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Cache"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG cache=$NAME =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.Cache/CheckNameAvailability?$API" --body '{"type":"Microsoft.Cache/Redis","name":"'$NAME'"}')
chk $? "CheckNameAvailability: free name" "$out"

out=$(rest --method put --url "$P/Redis/$NAME?$API" --body '{"location":"eastus","tags":{"env":"cli"},"properties":{"sku":{"name":"Basic","family":"C","capacity":0},"enableNonSslPort":false,"minimumTlsVersion":"1.2"}}')
chk $? "az rest PUT Redis" "$out"
[ "$(echo "$out" | jq_ 'd["properties"]["hostName"]')" = "$NAME.redis.cache.windows.net" ] && [ "$(echo "$out" | jq_ 'd["properties"]["sslPort"]')" = "6380" ] \
  && [ "$(echo "$out" | jq_ 'd["type"]')" = "Microsoft.Cache/Redis" ]
chk $? "cache has host name, SSL port 6380 and type Microsoft.Cache/Redis" "$(echo "$out" | head -12)"
out=$(rest --method get --url "$P/Redis/$NAME?$API"); [ "$(echo "$out" | jq_ 'd["properties"]["provisioningState"]')" = "Succeeded" ] && echo "$out" | grep -q '"env": "cli"'
chk $? "GET cache: Succeeded, tags kept" "$out"
echo "$out" | grep -q 'accessKeys'; [ $? -ne 0 ]
chk $? "GET cache does not leak access keys" "$out"
[ "$(echo "$out" | jq_ 'd["properties"]["redisConfiguration"]["maxclients"]')" = "256" ]
chk $? "redisConfiguration.maxclients computed for C0" "$out"
out=$(rest --method get --url "$P/redis?$API"); echo "$out" | grep -q "\"$NAME\""
chk $? "list caches in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.Cache/redis?$API"); echo "$out" | grep -q "\"$NAME\""
chk $? "list caches in the subscription" "$out"
out=$(rest --method post --url "$BASE/subscriptions/$SUB/providers/Microsoft.Cache/CheckNameAvailability?$API" --body '{"type":"Microsoft.Cache/Redis","name":"'$NAME'"}'); echo "$out" | grep -qi 'Conflict\|409'
chk $? "CheckNameAvailability: taken name → Conflict" "$out"
out=$(rest --method put --url "$P/Redis/bad--name?$API" --body '{"location":"eastus","properties":{"sku":{"name":"Basic","family":"C","capacity":0}}}'); echo "$out" | grep -q 'BadRequest'
chk $? "consecutive hyphens → BadRequest" "$out"
out=$(rest --method put --url "$P/Redis/cap$SFX?$API" --body '{"location":"eastus","properties":{"sku":{"name":"Basic","family":"C","capacity":9}}}'); echo "$out" | grep -q 'BadRequest'
chk $? "capacity out of range → BadRequest" "$out"

out=$(rest --method patch --url "$P/Redis/$NAME?$API" --body '{"properties":{"sku":{"name":"Standard","family":"C","capacity":1},"redisConfiguration":{"maxmemory-policy":"allkeys-lru"}}}')
[ "$(echo "$out" | jq_ 'd["properties"]["sku"]["name"]')" = "Standard" ] && [ "$(echo "$out" | jq_ 'd["properties"]["redisConfiguration"]["maxmemory-policy"]')" = "allkeys-lru" ] \
  && [ "$(echo "$out" | jq_ 'd["properties"]["redisConfiguration"]["maxclients"]')" = "1000" ]
chk $? "PATCH scales to Standard C1 and sets the eviction policy" "$out"
out=$(rest --method patch --url "$P/Redis/$NAME?$API" --body '{"properties":{"redisConfiguration":{"maxmemory-policy":"bogus"}}}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid eviction policy → BadRequest" "$out"

k0=$(rest --method post --url "$P/Redis/$NAME/listKeys?$API")
[ "$(echo "$k0" | jq_ 'len(d["primaryKey"])')" = "44" ]
chk $? "listKeys returns a 44-char primary key" "$k0"
k1=$(rest --method post --url "$P/Redis/$NAME/regenerateKey?$API" --body '{"keyType":"Primary"}')
[ "$(echo "$k1" | jq_ 'd["primaryKey"]')" != "$(echo "$k0" | jq_ 'd["primaryKey"]')" ] && [ "$(echo "$k1" | jq_ 'd["secondaryKey"]')" = "$(echo "$k0" | jq_ 'd["secondaryKey"]')" ]
chk $? "regenerateKey rotates only the primary key" "$k1"
out=$(rest --method post --url "$P/Redis/$NAME/forceReboot?$API" --body '{"rebootType":"AllNodes"}'); echo "$out" | grep -q '"message"'
chk $? "forceReboot AllNodes" "$out"

out=$(rest --method put --url "$P/Redis/$NAME/firewallRules/office?$API" --body '{"properties":{"startIP":"10.0.0.1","endIP":"10.0.0.20"}}'); echo "$out" | grep -q '"endIP": "10.0.0.20"'
chk $? "create firewall rule" "$out"
out=$(rest --method get --url "$P/Redis/$NAME/firewallRules?$API"); [ "$(echo "$out" | jq_ 'len(d["value"])')" = "1" ]
chk $? "list firewall rules" "$out"
out=$(rest --method put --url "$P/Redis/$NAME/firewallRules/bad?$API" --body '{"properties":{"startIP":"nope","endIP":"10.0.0.20"}}'); echo "$out" | grep -q 'BadRequest'
chk $? "invalid firewall IP → BadRequest" "$out"
out=$(rest --method delete --url "$P/Redis/$NAME/firewallRules/office?$API"); chk $? "delete firewall rule" "$out"
out=$(rest --method get --url "$P/Redis/$NAME/firewallRules/office?$API"); echo "$out" | grep -q 'NotFound'
chk $? "deleted firewall rule → NotFound" "$out"

out=$(rest --method put --url "$P/Redis/$PREM?$API" --body '{"location":"eastus","properties":{"sku":{"name":"Premium","family":"P","capacity":1},"shardCount":2}}')
[ "$(echo "$out" | jq_ 'len(d["properties"]["instances"])')" = "2" ]
chk $? "create Premium P1 with 2 shards" "$out"
out=$(rest --method put --url "$P/Redis/$NAME/patchSchedules/default?$API" --body '{"properties":{"scheduleEntries":[{"dayOfWeek":"Monday","startHourUtc":3}]}}'); echo "$out" | grep -q 'BadRequest'
chk $? "patch schedule on Standard → BadRequest" "$out"
out=$(rest --method put --url "$P/Redis/$PREM/patchSchedules/default?$API" --body '{"properties":{"scheduleEntries":[{"dayOfWeek":"Sunday","startHourUtc":2,"maintenanceWindow":"PT5H"}]}}'); echo "$out" | grep -q '"Sunday"'
chk $? "create patch schedule on Premium" "$out"
out=$(rest --method get --url "$P/Redis/$PREM/patchSchedules/default?$API"); echo "$out" | grep -q '"startHourUtc": 2'
chk $? "GET patch schedule" "$out"
out=$(rest --method post --url "$P/Redis/$PREM/export?$API" --body '{"format":"RDB","prefix":"bk","container":"https://cloudlearn.blob.core.windows.net/backups"}'); chk $? "export data (Premium)" "$out"
out=$(rest --method post --url "$P/Redis/$NAME/import?$API" --body '{"files":["https://x/y.rdb"]}'); echo "$out" | grep -q 'BadRequest'
chk $? "import on Standard → BadRequest" "$out"

out=$(curl -s "$BASE/azure-data/redis/ping"); echo "$out" | grep -q 'PONG'
chk $? "Valkey data plane answers PING over the Redis protocol" "$out"

out=$(rest --method delete --url "$P/Redis/$PREM?$API"); chk $? "delete Premium cache" "$out"
out=$(rest --method delete --url "$P/Redis/$NAME?$API"); chk $? "delete cache" "$out"
out=$(rest --method get --url "$P/Redis/$NAME?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted cache → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
