#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Network Watcher packet capture (Microsoft.Network/networkWatchers/packetCaptures) — endpoint override
# only: `az rest` (the CLI's documented client for any ARM provider). ENDPOINT (default http://127.0.0.1:9000), SUB.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-pc-$SFX"
AV="api-version=2023-11-01"
RP="/subscriptions/$SUB/resourceGroups/$RG"      # ARM ids carry no host
R="$BASE$RP"
N="$R/providers/Microsoft.Network"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG =="
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}' >/dev/null
chk $? "create resource group"
rest --method put --url "$R/providers/Microsoft.Storage/storageAccounts/pccli$SFX?api-version=2023-01-01" --body '{"location":"eastus","kind":"StorageV2","sku":{"name":"Standard_LRS"}}' >/dev/null
chk $? "create storage account"
NSG=$(rest --method put --url "$N/networkSecurityGroups/nsg?$AV" --body '{"location":"eastus","properties":{}}' | jq_ 'd["id"]')
rest --method put --url "$N/virtualNetworks/vn?$AV" --body "{\"location\":\"eastus\",\"properties\":{\"addressSpace\":{\"addressPrefixes\":[\"10.0.0.0/16\"]},\"subnets\":[{\"name\":\"s\",\"properties\":{\"addressPrefix\":\"10.0.1.0/24\",\"networkSecurityGroup\":{\"id\":\"$NSG\"}}}]}}" >/dev/null
NIC=$(rest --method put --url "$N/networkInterfaces/nic?$AV" --body "{\"location\":\"eastus\",\"properties\":{\"ipConfigurations\":[{\"name\":\"c\",\"properties\":{\"subnet\":{\"id\":\"$RP/providers/Microsoft.Network/virtualNetworks/vn/subnets/s\"}}}]}}")
IP=$(echo "$NIC" | jq_ 'd["properties"]["ipConfigurations"][0]["properties"]["privateIPAddress"]')
NICID=$(echo "$NIC" | jq_ 'd["id"]')
VM="$RP/providers/Microsoft.Compute/virtualMachines/vm"
rest --method put --url "$BASE$VM?api-version=2023-09-01" --body "{\"location\":\"eastus\",\"properties\":{\"networkProfile\":{\"networkInterfaces\":[{\"id\":\"$NICID\"}]}}}" >/dev/null
chk $? "create VM with a NIC"
rest --method put --url "$N/networkWatchers/nw?$AV" --body '{"location":"eastus"}' >/dev/null
chk $? "create network watcher"

PC="$N/networkWatchers/nw/packetCaptures"
ST="$RP/providers/Microsoft.Storage/storageAccounts/pccli$SFX"
out=$(rest --method put --url "$PC/c1?$AV" --body "{\"properties\":{\"target\":\"$VM\",\"storageLocation\":{\"storageId\":\"$ST\"},\"timeLimitInSeconds\":600,\"filters\":[{\"protocol\":\"TCP\",\"remotePort\":\"443\"}]}}")
[ "$(echo "$out" | jq_ 'd["properties"]["timeLimitInSeconds"]')" = "600" ] && echo "$out" | grep -q 'network-watcher-logs'
chk $? "az rest PUT packetCapture (start) returns storagePath in network-watcher-logs" "$out"
out=$(rest --method put --url "$PC/bad?$AV" --body "{\"properties\":{\"target\":\"$VM\",\"timeLimitInSeconds\":99999,\"storageLocation\":{\"storageId\":\"$ST\"}}}"); echo "$out" | grep -q 'InvalidRequestFormat'
chk $? "timeLimit above 18000 rejected" "$out"
out=$(rest --method get --url "$PC?$AV"); echo "$out" | grep -q '"c1"'
chk $? "list packet captures" "$out"
out=$(rest --method post --url "$PC/c1/queryStatus?$AV"); [ "$(echo "$out" | jq_ 'd["packetCaptureStatus"]')" = "Running" ]
chk $? "queryStatus Running" "$out"
rest --method post --url "$N/networkWatchers/nw/ipFlowVerify?$AV" --body "{\"targetResourceId\":\"$VM\",\"direction\":\"Outbound\",\"protocol\":\"TCP\",\"localPort\":\"50000\",\"remotePort\":\"443\",\"localIPAddress\":\"$IP\",\"remoteIPAddress\":\"203.0.113.9\"}" >/dev/null
rest --method post --url "$PC/c1/stop?$AV" >/dev/null
chk $? "stop"
out=$(rest --method post --url "$PC/c1/queryStatus?$AV"); [ "$(echo "$out" | jq_ 'd["packetCaptureStatus"]+d["stopReason"]+str(d["vyomiSummary"]["packets"])')" = "StoppedManual1" ]
chk $? "Stopped / Manual with the one allowed flow captured" "$out"
out=$(rest --method delete --url "$PC/c1?$AV"); rest --method get --url "$PC/c1?$AV" | grep -q 'ResourceNotFound'
chk $? "delete, then GET is 404" "$out"
echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
