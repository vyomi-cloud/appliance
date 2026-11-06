#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Kubernetes Service (Microsoft.ContainerService) — endpoint override only:
# `az rest` (the CLI's documented client for any ARM provider) against the resource provider. ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
SFX="$(date +%s | tail -c 7)"
RG="rg-cli-aks-$SFX"
CL="cliaks$SFX"
API="api-version=2024-09-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.ContainerService"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az against $BASE sub=$SUB rg=$RG cluster=$CL =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

out=$(rest --method put --url "$BASE/subscriptions/$SUB/resourcegroups/$RG?api-version=2021-04-01" --body '{"location":"eastus"}')
chk $? "create resource group" "$out"

out=$(rest --method put --url "$P/managedClusters/$CL?$API" --body '{"location":"eastus","identity":{"type":"SystemAssigned"},"sku":{"name":"Base","tier":"Free"},"tags":{"env":"cli"},"properties":{"dnsPrefix":"'$CL'-dns","kubernetesVersion":"1.29.9","agentPoolProfiles":[{"name":"nodepool1","count":2,"vmSize":"Standard_DS2_v2","mode":"System","osType":"Linux"}]}}')
chk $? "az rest PUT managedClusters" "$out"
echo "$out" | grep -q '"fqdn"' && echo "$out" | grep -q '"provisioningState": "Succeeded"' && echo "$out" | grep -q '"kubernetesVersion": "1.29.9"'
chk $? "cluster has fqdn, version 1.29.9, Succeeded" "$(echo "$out" | head -8)"
out=$(rest --method get --url "$P/managedClusters/$CL?$API"); echo "$out" | grep -q '"env": "cli"'
chk $? "GET cluster returns tags" "$out"
out=$(rest --method get --url "$P/managedClusters?$API"); echo "$out" | grep -q "\"$CL\""
chk $? "list clusters in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.ContainerService/managedClusters?$API"); echo "$out" | grep -q "\"$CL\""
chk $? "list clusters in the subscription" "$out"
out=$(rest --method put --url "$P/managedClusters/bad$CL?$API" --body '{"location":"eastus","properties":{"dnsPrefix":"bad-dns","kubernetesVersion":"9.9.9","agentPoolProfiles":[{"name":"nodepool1","count":1,"mode":"System"}]}}'); echo "$out" | grep -q 'K8sVersionNotSupported'
chk $? "unsupported version → K8sVersionNotSupported" "$out"

out=$(rest --method post --url "$P/managedClusters/$CL/listClusterUserCredential?$API"); echo "$out" | grep -q '"kubeconfigs"' && echo "$out" | grep -q '"value"'
chk $? "listClusterUserCredential returns a kubeconfig" "$out"
VAL=$(echo "$out" | jq_ 'd["kubeconfigs"][0]["value"]')
echo "$VAL" | base64 -d 2>/dev/null | grep -q 'kind: Config'
chk $? "kubeconfig decodes to a kubectl config" "$VAL"

out=$(rest --method put --url "$P/managedClusters/$CL/agentPools/userpool?$API" --body '{"properties":{"count":1,"vmSize":"Standard_D4s_v3","mode":"User","osType":"Linux"}}')
echo "$out" | grep -q '"Standard_D4s_v3"' && echo "$out" | grep -q '"mode": "User"'
chk $? "create user node pool" "$out"
out=$(rest --method get --url "$P/managedClusters/$CL/agentPools?$API"); echo "$out" | grep -q 'userpool' && echo "$out" | grep -q 'nodepool1'
chk $? "list node pools" "$out"
out=$(rest --method put --url "$P/managedClusters/$CL/agentPools/userpool?$API" --body '{"properties":{"count":3}}'); echo "$out" | grep -q '"count": 3'
chk $? "scale node pool to 3" "$out"
out=$(rest --method get --url "$P/managedClusters/$CL/upgradeProfiles/default?$API"); echo "$out" | grep -q '1.30.5'
chk $? "upgrade profile lists 1.30.5" "$out"
out=$(rest --method put --url "$P/managedClusters/$CL?$API" --body '{"location":"eastus","properties":{"dnsPrefix":"'$CL'-dns","kubernetesVersion":"1.31.1"}}'); echo "$out" | grep -q 'UpgradeNotAllowed'
chk $? "skipping a minor version → UpgradeNotAllowed" "$out"
out=$(rest --method put --url "$P/managedClusters/$CL?$API" --body '{"location":"eastus","properties":{"dnsPrefix":"'$CL'-dns","kubernetesVersion":"1.30.5"}}'); echo "$out" | grep -q '"kubernetesVersion": "1.30.5"'
chk $? "upgrade to 1.30.5" "$out"
out=$(rest --method post --url "$P/managedClusters/$CL/stop?$API"); chk $? "stop cluster" "$out"
out=$(rest --method get --url "$P/managedClusters/$CL?$API"); echo "$out" | grep -q '"code": "Stopped"'
chk $? "power state is Stopped" "$out"
out=$(rest --method post --url "$P/managedClusters/$CL/start?$API"); chk $? "start cluster" "$out"
out=$(rest --method put --url "$P/managedClusters/$CL/maintenanceConfigurations/default?$API" --body '{"properties":{"timeInWeek":[{"day":"Sunday","hourSlots":[1,2]}]}}'); echo "$out" | grep -q 'Sunday'
chk $? "maintenance configuration" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.ContainerService/locations/eastus/kubernetesVersions?$API"); echo "$out" | grep -q '1.30'
chk $? "location kubernetesVersions" "$out"
out=$(rest --method delete --url "$P/managedClusters/$CL/agentPools/userpool?$API"); chk $? "delete node pool" "$out"

out=$(rest --method delete --url "$P/managedClusters/$CL?$API"); chk $? "delete cluster" "$out"
out=$(rest --method get --url "$P/managedClusters/$CL?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted cluster → ResourceNotFound" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
