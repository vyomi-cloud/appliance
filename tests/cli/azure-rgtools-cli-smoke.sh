#!/usr/bin/env bash
# Real `az` CLI against Vyomi's resource group tools: Insights + force delete (forceDeletionTypes) — endpoint override only (`az rest`).
# ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-rgt-$SFX"
G="$BASE/subscriptions/$SUB/resourcegroups/$RG"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
echo "== az against $BASE sub=$SUB rg=$RG =="
rest --method put --url "$G?api-version=2021-04-01" --body '{"location":"eastus"}' >/dev/null
chk $? "create resource group"
rest --method put --url "$G/providers/Microsoft.Compute/virtualMachines/vm1?api-version=2023-09-01" --body '{"location":"eastus","tags":{"env":"cli"},"properties":{}}' >/dev/null
chk $? "create VM"
rest --method put --url "$G/providers/Microsoft.Network/networkSecurityGroups/nsg?api-version=2023-11-01" --body '{"location":"eastus","properties":{}}' >/dev/null
chk $? "create untagged NSG"
out=$(rest --method get --url "$G/providers/Microsoft.Vyomi/insights?api-version=2024-01-01")
[ "$(echo "$out" | jq_ 'str(d["inventory"]["resourceCount"])+"/"+str(d["tags"]["untagged"])+"/"+str(d["compute"]["virtualMachines"])')" = "2/1/1" ]
chk $? "Insights: 2 resources, 1 untagged, 1 VM" "$out"
out=$(rest --method delete --url "$G?api-version=2021-04-01&forceDeletionTypes=Microsoft.Storage/storageAccounts"); echo "$out" | grep -q 'InvalidForceDeletionType'
chk $? "unsupported forceDeletionTypes rejected" "$out"
out=$(rest --method delete --url "$G?api-version=2021-04-01&forceDeletionTypes=Microsoft.Compute/virtualMachines,Microsoft.Compute/virtualMachineScaleSets")
chk $? "force delete the group" "$out"
rest --method get --url "$G?api-version=2021-04-01" | grep -q 'ResourceGroupNotFound'
chk $? "group is gone"
echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
