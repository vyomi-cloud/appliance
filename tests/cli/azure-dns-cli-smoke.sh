#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure DNS (Microsoft.Network/dnsZones) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider,
# plus a DNS question answered over HTTP from the zone. ENDPOINT (default http://127.0.0.1:9000), SUB.
# One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-dns-$SFX"
ZONE="cli$SFX.example.com"
API="api-version=2018-05-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Network"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG zone=$ZONE =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method put --url "$P/dnsZones/$ZONE?$API" --body '{"location":"global","tags":{"env":"cli"}}')
chk $? "az rest PUT dnsZones" "$out"
echo "$out" | grep -q '"nameServers"' && echo "$out" | grep -q '"zoneType": "Public"' && echo "$out" | grep -q '"numberOfRecordSets": 2'
chk $? "zone has name servers, zoneType Public, SOA+NS record sets" "$(echo "$out" | head -12)"
out=$(rest --method get --url "$P/dnsZones/$ZONE?$API"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET zone returns tags" "$out"
out=$(rest --method get --url "$P/dnsZones?$API"); echo "$out" | grep -q "\"$ZONE\""
chk $? "list zones in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.Network/dnsZones?$API"); echo "$out" | grep -q "\"$ZONE\""
chk $? "list zones in the subscription" "$out"
out=$(rest --method put --url "$P/dnsZones/bad?$API" --body '{"location":"global"}'); echo "$out" | grep -q 'BadRequest'
chk $? "single-label zone name → BadRequest" "$out"

out=$(rest --method put --url "$P/dnsZones/$ZONE/A/www?$API" --body '{"properties":{"TTL":300,"ARecords":[{"ipv4Address":"10.1.2.3"},{"ipv4Address":"10.1.2.4"}]}}')
echo "$out" | grep -q '"10.1.2.3"' && echo "$out" | grep -q "\"fqdn\": \"www.$ZONE.\""
chk $? "create A record set" "$out"
out=$(rest --method put --url "$P/dnsZones/$ZONE/CNAME/app?$API" --body '{"properties":{"TTL":3600,"CNAMERecord":{"cname":"www.'$ZONE'"}}}')
echo "$out" | grep -q '"cname"'
chk $? "create CNAME record set" "$out"
out=$(rest --method put --url "$P/dnsZones/$ZONE/MX/@?$API" --body '{"properties":{"TTL":3600,"MXRecords":[{"preference":10,"exchange":"mail.'$ZONE'"}]}}')
echo "$out" | grep -q '"preference": 10'
chk $? "create MX record set at the apex" "$out"
out=$(rest --method put --url "$P/dnsZones/$ZONE/TXT/@?$API" --body '{"properties":{"TTL":3600,"TXTRecords":[{"value":["v=spf1 -all"]}]}}')
echo "$out" | grep -q 'v=spf1'
chk $? "create TXT record set" "$out"
out=$(rest --method put --url "$P/dnsZones/$ZONE/A/app?$API" --body '{"properties":{"ARecords":[{"ipv4Address":"10.9.9.9"}]}}'); echo "$out" | grep -q 'Conflict'
chk $? "A next to a CNAME of the same name → Conflict" "$out"
out=$(rest --method get --url "$P/dnsZones/$ZONE/A/www?$API"); [ "$(echo "$out" | jq_ 'd["properties"]["TTL"]')" = "300" ]
chk $? "GET record set returns its TTL" "$out"
out=$(rest --method patch --url "$P/dnsZones/$ZONE/A/www?$API" --body '{"properties":{"TTL":60}}'); [ "$(echo "$out" | jq_ 'len(d["properties"]["ARecords"])')" = "2" ] && [ "$(echo "$out" | jq_ 'd["properties"]["TTL"]')" = "60" ]
chk $? "PATCH record set changes TTL and keeps records" "$out"
out=$(rest --method get --url "$P/dnsZones/$ZONE/recordsets?$API"); [ "$(echo "$out" | jq_ 'len(d["value"])')" = "6" ]
chk $? "list record sets (SOA, NS, A, CNAME, MX, TXT)" "$out"
out=$(rest --method get --url "$P/dnsZones/$ZONE/A?$API"); echo "$out" | grep -q '"www"'
chk $? "list record sets by type" "$out"

out=$(curl -s "$BASE/azure-data/dns/query?name=app.$ZONE&type=A"); echo "$out" | grep -q '"10.1.2.3"' && echo "$out" | grep -q '"CNAME"'
chk $? "DNS query follows the CNAME to the A records" "$out"
out=$(curl -s "$BASE/azure-data/dns/query?name=nope.$ZONE&type=A"); [ "$(echo "$out" | jq_ 'd["Status"]')" = "3" ]
chk $? "DNS query for a missing name → NXDOMAIN" "$out"
out=$(curl -s "$BASE/azure-data/dns/query?name=other.example.net&type=A"); [ "$(echo "$out" | jq_ 'd["Status"]')" = "5" ]
chk $? "DNS query outside every zone → REFUSED" "$out"

out=$(rest --method delete --url "$P/dnsZones/$ZONE/A/www?$API"); chk $? "delete record set" "$out"
out=$(rest --method get --url "$P/dnsZones/$ZONE/A/www?$API"); echo "$out" | grep -q 'NotFound'
chk $? "deleted record set → NotFound" "$out"
out=$(rest --method delete --url "$P/dnsZones/$ZONE/SOA/@?$API"); echo "$out" | grep -q 'BadRequest'
chk $? "deleting the SOA record set → BadRequest" "$out"
out=$(rest --method delete --url "$P/dnsZones/$ZONE?$API"); chk $? "delete zone" "$out"
out=$(rest --method get --url "$P/dnsZones/$ZONE?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted zone → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
